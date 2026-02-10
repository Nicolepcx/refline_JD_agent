"""
UI panel for running the evaluation harness from the Streamlit sidebar.

Flow:
1. User picks sample count (100-300, step 50).
2. Click "Generate Test Samples" → builds eval dataset in session state.
3. Click "Run Eval" → generates JDs + RULER scores (async, streamed progress).
4. Results shown in a sortable dataframe (lowest scores first) + CSV download.
"""

from __future__ import annotations

import asyncio
import io
import csv
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import streamlit as st

from evals.eval_models import EvalScenario, EvalResult
from evals.generate_eval_dataset import generate_dataset
from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Thread-safe progress tracker
# ---------------------------------------------------------------------------

class _ProgressTracker:
    """Thread-safe container shared between worker thread and main thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.pct: float = 0.0
        self.msg: str = "Initialising …"
        self.done: bool = False
        self.result: Any = None
        self.error: Optional[Exception] = None

    # Called from the *worker* thread ─────────────────────────
    def update(self, pct: float, msg: str) -> None:
        with self._lock:
            self.pct = pct
            self.msg = msg

    def finish(self, result: Any = None, error: Optional[Exception] = None) -> None:
        with self._lock:
            self.result = result
            self.error = error
            self.done = True

    # Called from the *main* (Streamlit) thread ───────────────
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pct": self.pct,
                "msg": self.msg,
                "done": self.done,
                "result": self.result,
                "error": self.error,
            }


def _run_async_with_progress(
    coro_factory: Callable,
    progress_bar,
    status_text,
    poll_interval: float = 0.25,
):
    """
    Run an async coroutine in a background thread while polling progress
    back into Streamlit's main thread – gives a tqdm-style live progress bar.

    *coro_factory* is  ``lambda cb: _run_eval_async(scenarios, progress_callback=cb)``
    so that the callback is wired into the coroutine **before** it starts.
    """
    tracker = _ProgressTracker()

    def _worker() -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(coro_factory(tracker.update))
            loop.close()
            tracker.finish(result=result)
        except Exception as exc:
            tracker.finish(error=exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    # ── Poll progress from the main thread ──
    while True:
        snap = tracker.snapshot()
        # Clamp to [0, 0.99] while still running so the bar never "finishes" early
        display_pct = min(snap["pct"], 0.99) if not snap["done"] else 1.0
        progress_bar.progress(display_pct, text=snap["msg"])
        status_text.caption(snap["msg"])
        if snap["done"]:
            break
        time.sleep(poll_interval)

    t.join()

    if tracker.error:
        raise tracker.error
    return tracker.result


def _results_to_dataframe(results: List[EvalResult]) -> pd.DataFrame:
    """Convert a list of EvalResult to a nicely formatted DataFrame."""
    rows = [r.model_dump() for r in results]
    df = pd.DataFrame(rows)
    # Reorder columns for readability — style + Swiss checks are prominent
    col_order = [
        "scenario_id", "ruler_score",
        "expected_primary_color", "expected_secondary_color",
        "job_title", "language",
        "formality", "company_type", "seniority_label",
        "eszett_free", "pronoun_ok",
        "swiss_vocab_ok", "swiss_vocab_violations", "swiss_vocab_details",
        "duty_count", "req_count", "benefit_count", "has_summary",
        "variety_score",
        "generation_time_s", "category_code", "block_name",
        "job_description_excerpt", "error",
    ]
    cols = [c for c in col_order if c in df.columns]
    return df[cols]


def _dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Serialize a DataFrame to CSV bytes for download."""
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Phase 1 – Dataset generation (fast, CPU-only)
# ---------------------------------------------------------------------------

def _generate_eval_scenarios(num_samples: int) -> List[dict]:
    """Generate eval scenarios. num_samples must be even (DE+EN pairs)."""
    from config import DUTY_CHUNKS_PATH

    num_categories = num_samples // 2  # Each category yields 2 scenarios (DE+EN)
    seed = int(time.time()) % 100_000  # Different seed each run for variety

    scenarios = generate_dataset(
        duty_chunks_path=DUTY_CHUNKS_PATH,
        num_categories=num_categories,
        seed=seed,
    )
    return scenarios


# ---------------------------------------------------------------------------
# Phase 2 – Eval runner (async, calls LLMs)
# ---------------------------------------------------------------------------

async def _run_eval_async(
    scenarios_raw: List[dict],
    progress_callback: Optional[Callable] = None,
) -> List[EvalResult]:
    """
    Run the full evaluation pipeline:
      1. Generate JDs concurrently
      2. Score with RULER in batches
      3. Run quality checks
    Returns a list of EvalResult.

    ``progress_callback(pct: float, msg: str)`` is called frequently
    from the worker thread so the main thread can mirror it in the UI.
    """
    from evals.run_eval import (
        _run_one_scenario,
        _score_batch,
    )

    _cb = progress_callback or (lambda _p, _m: None)  # no-op if no callback

    scenarios = [EvalScenario(**s) for s in scenarios_raw]
    total = len(scenarios)

    semaphore = asyncio.Semaphore(5)
    phase1_t0 = time.monotonic()

    # ── Phase 1: Generate JDs (60 % of the bar) ──
    _cb(0.0, f"Phase 1/2 — generating {total} JDs …")

    tasks = [_run_one_scenario(s, semaphore) for s in scenarios]

    raw_results = []
    done_count = 0
    errors_count = 0
    for coro in asyncio.as_completed(tasks):
        scenario, job_body, result = await coro
        raw_results.append((scenario, job_body, result))
        done_count += 1
        if result.error:
            errors_count += 1
        # Update on every single scenario so the bar feels alive
        elapsed = time.monotonic() - phase1_t0
        rate = done_count / elapsed if elapsed > 0 else 0
        eta = (total - done_count) / rate if rate > 0 else 0
        pct = done_count / total * 0.60  # Phase 1 → 0 – 60 %
        _cb(
            pct,
            f"Phase 1/2 — JD {done_count}/{total}  "
            f"({rate:.1f} it/s, ~{eta:.0f}s left)"
            + (f"  ⚠ {errors_count} errors" if errors_count else ""),
        )

    # Separate successes from failures
    successes = []
    all_results: List[EvalResult] = []
    for scenario, job_body, result in raw_results:
        all_results.append(result)
        if job_body is not None:
            successes.append((scenario, job_body, result))

    fail_count = total - len(successes)
    _cb(
        0.60,
        f"Phase 1 done — {len(successes)} ok, {fail_count} failed.  "
        f"Starting RULER scoring …",
    )

    # ── Phase 2: RULER scoring in batches (35 % of the bar) ──
    batch_size = 5
    num_batches = max(1, (len(successes) + batch_size - 1) // batch_size)
    phase2_t0 = time.monotonic()

    for i in range(0, len(successes), batch_size):
        batch = successes[i : i + batch_size]
        await _score_batch(batch)
        batch_num = i // batch_size + 1
        elapsed = time.monotonic() - phase2_t0
        rate = batch_num / elapsed if elapsed > 0 else 0
        eta = (num_batches - batch_num) / rate if rate > 0 else 0
        pct = 0.60 + (batch_num / num_batches) * 0.35
        _cb(
            pct,
            f"Phase 2/2 — RULER batch {batch_num}/{num_batches}  "
            f"({rate:.1f} bat/s, ~{eta:.0f}s left)",
        )

    _cb(0.98, "Finalising results …")

    return all_results


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

def _compute_summary(results: List[EvalResult]) -> dict:
    """Compute summary statistics from eval results."""
    scored = [r for r in results if r.ruler_score > 0]
    de_results = [r for r in results if r.language == "de"]
    errors = [r for r in results if r.error]

    summary = {
        "total": len(results),
        "generated": len(results) - len(errors),
        "errors": len(errors),
    }

    if scored:
        scores = [r.ruler_score for r in scored]
        summary["ruler_avg"] = round(sum(scores) / len(scores), 3)
        summary["ruler_min"] = round(min(scores), 3)
        summary["ruler_max"] = round(max(scores), 3)
        summary["ruler_scored"] = len(scored)
    else:
        summary["ruler_avg"] = 0.0
        summary["ruler_min"] = 0.0
        summary["ruler_max"] = 0.0
        summary["ruler_scored"] = 0

    # ── Swiss German compliance (DE only) ──
    de_eszett = [r for r in de_results if r.eszett_free is not None]
    if de_eszett:
        ok = sum(1 for r in de_eszett if r.eszett_free)
        summary["eszett_compliance"] = f"{ok}/{len(de_eszett)}"
    else:
        summary["eszett_compliance"] = "n/a"

    de_pronoun = [r for r in de_results if r.pronoun_ok is not None]
    if de_pronoun:
        ok = sum(1 for r in de_pronoun if r.pronoun_ok)
        summary["pronoun_compliance"] = f"{ok}/{len(de_pronoun)}"
    else:
        summary["pronoun_compliance"] = "n/a"

    de_vocab = [r for r in de_results if r.swiss_vocab_ok is not None]
    if de_vocab:
        ok = sum(1 for r in de_vocab if r.swiss_vocab_ok)
        total_violations = sum(r.swiss_vocab_violations for r in de_vocab)
        summary["swiss_vocab_compliance"] = f"{ok}/{len(de_vocab)}"
        summary["swiss_vocab_total_violations"] = total_violations
    else:
        summary["swiss_vocab_compliance"] = "n/a"
        summary["swiss_vocab_total_violations"] = 0

    # ── Style color distribution ──
    color_counts: dict = {}
    for r in results:
        c = r.expected_primary_color
        if c:
            color_counts[c] = color_counts.get(c, 0) + 1
    summary["color_distribution"] = color_counts

    variety = [r.variety_score for r in results if r.variety_score > 0]
    summary["variety_avg"] = round(sum(variety) / len(variety), 3) if variety else 0.0

    times = [r.generation_time_s for r in results if r.generation_time_s > 0]
    summary["avg_time_s"] = round(sum(times) / len(times), 1) if times else 0.0

    return summary


# ---------------------------------------------------------------------------
# Main panel renderer
# ---------------------------------------------------------------------------

def render_eval_panel():
    """Render the evaluation harness panel in the sidebar."""
    with st.sidebar:
        st.markdown("---")
        st.header("🧪 Evaluation Harness")

        # ── Sample count slider ──
        num_samples = st.slider(
            "Number of test samples",
            min_value=100,
            max_value=300,
            value=st.session_state.get("eval_num_samples", 100),
            step=50,
            key="eval_num_samples",
            help="Each sample is one JD generation + RULER score. "
                 "Half are DE, half EN. More samples = longer runtime.",
        )

        # ── Step 1: Generate test scenarios ──
        if st.button("📋 Generate Test Samples", key="btn_generate_eval_samples"):
            with st.spinner(f"Generating {num_samples} test scenarios …"):
                try:
                    scenarios = _generate_eval_scenarios(num_samples)
                    st.session_state.eval_scenarios = scenarios
                    st.session_state.eval_results = None  # reset old results
                    st.session_state.eval_results_df = None
                    de_count = sum(1 for s in scenarios if s["language"] == "de")
                    en_count = sum(1 for s in scenarios if s["language"] == "en")
                    st.success(
                        f"Generated {len(scenarios)} scenarios "
                        f"({de_count} DE, {en_count} EN)"
                    )
                except Exception as exc:
                    st.error(f"Failed to generate scenarios: {exc}")

        # Show scenario summary if available
        scenarios = st.session_state.get("eval_scenarios")
        if scenarios:
            with st.expander(f"📊 {len(scenarios)} scenarios ready", expanded=False):
                sc_df = pd.DataFrame(scenarios)
                st.caption("**Language distribution**")
                st.dataframe(
                    sc_df["language"].value_counts().reset_index().rename(
                        columns={"index": "Language", "language": "Language", "count": "Count"}
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption("**Formality distribution**")
                st.dataframe(
                    sc_df["formality"].value_counts().reset_index().rename(
                        columns={"index": "Formality", "formality": "Formality", "count": "Count"}
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption("**Company type distribution**")
                st.dataframe(
                    sc_df["company_type"].value_counts().reset_index().rename(
                        columns={"index": "Type", "company_type": "Type", "count": "Count"}
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

            # ── Step 2: Run eval ──
            if st.button(
                "🚀 Run Eval Now",
                key="btn_run_eval",
                type="primary",
            ):
                progress_bar = st.progress(0.0, text="Starting evaluation …")
                status_text = st.empty()

                t0 = time.time()
                try:
                    results = _run_async_with_progress(
                        coro_factory=lambda cb: _run_eval_async(
                            scenarios, progress_callback=cb,
                        ),
                        progress_bar=progress_bar,
                        status_text=status_text,
                    )
                    elapsed = time.time() - t0

                    st.session_state.eval_results = results
                    df = _results_to_dataframe(results)
                    st.session_state.eval_results_df = df
                    st.session_state.eval_summary = _compute_summary(results)
                    st.session_state.eval_elapsed = round(elapsed, 1)

                    progress_bar.progress(1.0, text="✅ Complete")
                    status_text.success(
                        f"Eval complete — {len(results)} results in {elapsed:.0f}s"
                    )
                except Exception as exc:
                    logger.error(f"Eval run failed: {exc}", exc_info=True)
                    progress_bar.empty()
                    status_text.error(f"Eval failed: {exc}")

        # ── Display results ──
        _render_eval_results()


def _render_eval_results():
    """Render evaluation results in the main area (called from sidebar context)."""
    df = st.session_state.get("eval_results_df")
    summary = st.session_state.get("eval_summary")
    elapsed = st.session_state.get("eval_elapsed")

    if df is None or summary is None:
        return

    st.markdown("---")
    st.subheader("📈 Eval Results")

    # ── Summary metrics ──
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("RULER avg", f"{summary['ruler_avg']:.3f}")
        st.metric("RULER min", f"{summary['ruler_min']:.3f}")
    with col2:
        st.metric("RULER max", f"{summary['ruler_max']:.3f}")
        st.metric("Scored", f"{summary['ruler_scored']}/{summary['total']}")
    with col3:
        st.metric("Swiss vocab ✅", summary["swiss_vocab_compliance"])
        st.metric("DE-DE violations", summary.get("swiss_vocab_total_violations", 0))

    st.caption(
        f"Eszett-free: {summary['eszett_compliance']}  |  "
        f"Pronoun OK: {summary['pronoun_compliance']}  |  "
        f"Variety avg: {summary['variety_avg']:.3f}"
    )

    # ── Style color distribution ──
    color_dist = summary.get("color_distribution", {})
    if color_dist:
        color_emoji = {"red": "🔴", "yellow": "🟡", "blue": "🔵", "green": "🟢"}
        dist_str = "  |  ".join(
            f"{color_emoji.get(c, '⚪')} {c}: {n}"
            for c, n in sorted(color_dist.items())
        )
        st.caption(f"Style colors: {dist_str}")

    st.caption(
        f"Avg gen time: {summary['avg_time_s']}s  |  "
        f"Errors: {summary['errors']}  |  "
        f"Total runtime: {elapsed}s"
    )

    # ── Sortable table (default: lowest RULER score first) ──
    sort_col = st.selectbox(
        "Sort by",
        options=[
            "ruler_score", "variety_score", "swiss_vocab_violations",
            "expected_primary_color", "generation_time_s",
            "language", "formality", "company_type",
        ],
        index=0,
        key="eval_sort_col",
    )
    sort_asc = st.checkbox("Ascending", value=True, key="eval_sort_asc")

    sorted_df = df.sort_values(by=sort_col, ascending=sort_asc, na_position="last")

    st.dataframe(
        sorted_df,
        use_container_width=True,
        height=400,
    )

    # ── Flag lowest RULER scores ──
    low_threshold = summary["ruler_avg"] * 0.75 if summary["ruler_avg"] > 0 else 0.5
    low_scorers = df[df["ruler_score"] < low_threshold]
    if not low_scorers.empty:
        with st.expander(
            f"⚠️ {len(low_scorers)} low-scoring scenarios (< {low_threshold:.3f})",
            expanded=False,
        ):
            st.dataframe(
                low_scorers.sort_values("ruler_score", ascending=True),
                use_container_width=True,
            )

    # ── Flag Swiss vocab violations ──
    if "swiss_vocab_violations" in df.columns:
        vocab_fails = df[df["swiss_vocab_violations"] > 0]
        if not vocab_fails.empty:
            with st.expander(
                f"🇨🇭 {len(vocab_fails)} scenarios with DE-DE vocabulary violations",
                expanded=False,
            ):
                show_cols = [
                    "scenario_id", "job_title", "language",
                    "swiss_vocab_violations", "swiss_vocab_details",
                    "eszett_free", "pronoun_ok", "ruler_score",
                ]
                show_cols = [c for c in show_cols if c in vocab_fails.columns]
                st.dataframe(
                    vocab_fails[show_cols].sort_values(
                        "swiss_vocab_violations", ascending=False
                    ),
                    use_container_width=True,
                )

    # ── CSV download ──
    csv_bytes = _dataframe_to_csv_bytes(sorted_df)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    st.download_button(
        label="⬇️ Download CSV",
        data=csv_bytes,
        file_name=f"eval_results_{ts}.csv",
        mime="text/csv",
        key="btn_download_eval_csv",
    )
