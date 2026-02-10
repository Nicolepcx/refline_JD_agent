#!/usr/bin/env python3
"""
Step 2 — Headless evaluation runner.

For each EvalScenario in eval_dataset.json:
  1. Build a JobGenerationConfig.
  2. Generate a JobBody via render_job_body_async().
  3. Score with ART RULER (batched).
  4. Run deterministic quality checks.
  5. Write results to CSV.

Usage
─────
    python -m evals.run_eval                              # defaults
    python -m evals.run_eval --dataset evals/eval_dataset.json --batch 5
    python -m evals.run_eval --concurrency 3              # lower parallelism
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import art

# Project imports  (run from project root: python -m evals.run_eval)
from models.job_models import JobBody, JobGenerationConfig
from generators.job_generator import render_job_body_async
from ruler.ruler_utils import jd_candidate_to_trajectory, score_group_with_fallback
from services.swiss_german import check_pronoun_consistency
from evals.eval_models import EvalScenario, EvalResult


# ---------------------------------------------------------------------------
# Quality-check helpers
# ---------------------------------------------------------------------------

def _check_eszett(text: str) -> bool:
    """Return True if the text contains NO ß (Schweizer Schriftdeutsch)."""
    return "ß" not in text


def _check_pronoun(all_text: str, formality: str) -> bool:
    """Return True if pronoun usage is consistent with formality."""
    ok, _ = check_pronoun_consistency(all_text, formality)
    return ok


def _sentence_start_variety(bullet_lists: List[List[str]]) -> float:
    """
    Measure variety of first words across all bullet-point lists.

    Returns the ratio  unique_first_words / total_bullets  in [0, 1].
    A score of 1.0 means every bullet starts with a different word.
    """
    first_words: List[str] = []
    for bullets in bullet_lists:
        for b in bullets:
            b = b.strip()
            if not b:
                continue
            # Take the first word (lowercased, stripped of punctuation)
            word = re.split(r"[\s:,;/]", b, maxsplit=1)[0].lower().strip()
            if word:
                first_words.append(word)
    if not first_words:
        return 0.0
    unique = len(set(first_words))
    return unique / len(first_words)


# ---------------------------------------------------------------------------
# Build a JobGenerationConfig from an EvalScenario
# ---------------------------------------------------------------------------

def _build_config(scenario: EvalScenario) -> JobGenerationConfig:
    """Create a JobGenerationConfig from the scenario parameters."""
    return JobGenerationConfig(
        language=scenario.language,
        formality=scenario.formality,
        company_type=scenario.company_type,
        seniority_label=scenario.seniority_label,
        # Let industry default to "generic" — the eval focuses on tone/formality axes
        industry="generic",
        # duty_keywords are injected separately via render_job_body_async params
    )


# ---------------------------------------------------------------------------
# Single-scenario runner
# ---------------------------------------------------------------------------

async def _run_one_scenario(
    scenario: EvalScenario,
    semaphore: asyncio.Semaphore,
) -> Tuple[EvalScenario, Optional[JobBody], EvalResult]:
    """
    Generate one JD and collect quality metrics.
    Does NOT score with RULER — that's done in batches afterward.
    """
    result = EvalResult(
        scenario_id=scenario.scenario_id,
        job_title=scenario.job_title,
        language=scenario.language,
        formality=scenario.formality,
        company_type=scenario.company_type,
        seniority_label=scenario.seniority_label,
        category_code=scenario.category_code,
        block_name=scenario.block_name,
    )

    cfg = _build_config(scenario)
    job_body: Optional[JobBody] = None

    async with semaphore:
        t0 = time.monotonic()
        try:
            job_body = await render_job_body_async(
                job_title=scenario.job_title,
                cfg=cfg,
                duty_bullets=scenario.duty_bullets if scenario.duty_bullets else None,
                duty_source=scenario.duty_source if scenario.duty_bullets else None,
            )
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.generation_time_s = round(time.monotonic() - t0, 2)
            return scenario, None, result

        result.generation_time_s = round(time.monotonic() - t0, 2)

    # ── Structural counts ──
    result.duty_count = len(job_body.duties)
    result.req_count = len(job_body.requirements)
    result.benefit_count = len(job_body.benefits)
    result.has_summary = bool(job_body.summary and job_body.summary.strip())
    result.job_description_excerpt = (job_body.job_description or "")[:200]

    # ── DE-specific checks ──
    if scenario.language == "de":
        all_text = " ".join(
            [job_body.job_description]
            + job_body.requirements
            + job_body.benefits
            + job_body.duties
            + ([job_body.summary] if job_body.summary else [])
        )
        result.eszett_free = _check_eszett(all_text)
        result.pronoun_ok = _check_pronoun(all_text, scenario.formality)

    # ── Sentence-start variety ──
    result.variety_score = round(
        _sentence_start_variety([
            job_body.duties,
            job_body.requirements,
            job_body.benefits,
        ]),
        3,
    )

    return scenario, job_body, result


# ---------------------------------------------------------------------------
# Batch RULER scoring
# ---------------------------------------------------------------------------

async def _score_batch(
    batch: List[Tuple[EvalScenario, JobBody, EvalResult]],
) -> None:
    """Score a batch of (scenario, job_body, result) with RULER. Mutates result.ruler_score."""
    if not batch:
        return

    trajectories = []
    for scenario, job_body, _ in batch:
        cfg = _build_config(scenario)
        traj = jd_candidate_to_trajectory(scenario.job_title, cfg, job_body)
        trajectories.append(traj)

    group = art.TrajectoryGroup(trajectories)

    try:
        judged = await score_group_with_fallback(group, debug=False)
    except Exception as exc:
        # If RULER fails for the whole batch, mark all with error
        for _, _, result in batch:
            result.error = (result.error or "") + f" | RULER error: {exc}"
        return

    if judged is None:
        return

    for (_, _, result), traj in zip(batch, judged.trajectories):
        result.ruler_score = round(float(traj.reward), 4)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def run_eval(
    dataset_path: str,
    output_csv: str,
    batch_size: int = 5,
    concurrency: int = 5,
) -> List[EvalResult]:
    """
    Run the full evaluation: generate JDs, score with RULER, write CSV.
    """
    # Load scenarios
    raw = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    scenarios = [EvalScenario(**s) for s in raw]
    print(f"[eval-run] Loaded {len(scenarios)} scenarios from {dataset_path}")

    semaphore = asyncio.Semaphore(concurrency)

    # ── Phase 1: Generate all JDs concurrently ──
    print(f"[eval-run] Phase 1: Generating JDs (concurrency={concurrency}) ...")
    tasks = [_run_one_scenario(s, semaphore) for s in scenarios]
    raw_results: List[Tuple[EvalScenario, Optional[JobBody], EvalResult]] = (
        await asyncio.gather(*tasks)
    )

    # Separate successes (have a JobBody) from failures
    successes: List[Tuple[EvalScenario, JobBody, EvalResult]] = []
    all_results: List[EvalResult] = []
    for scenario, job_body, result in raw_results:
        all_results.append(result)
        if job_body is not None:
            successes.append((scenario, job_body, result))

    failed = len(raw_results) - len(successes)
    print(
        f"[eval-run] Phase 1 done: {len(successes)} generated, {failed} failed"
    )

    # ── Phase 2: RULER scoring in batches ──
    print(f"[eval-run] Phase 2: RULER scoring (batch_size={batch_size}) ...")
    for i in range(0, len(successes), batch_size):
        batch = successes[i : i + batch_size]
        batch_ids = [r.scenario_id for _, _, r in batch]
        print(f"  Scoring batch {i // batch_size + 1}: {batch_ids}")
        await _score_batch(batch)

    # ── Phase 3: Write CSV ──
    csv_path = Path(output_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "scenario_id",
        "job_title",
        "language",
        "formality",
        "company_type",
        "seniority_label",
        "category_code",
        "block_name",
        "ruler_score",
        "duty_count",
        "req_count",
        "benefit_count",
        "has_summary",
        "eszett_free",
        "pronoun_ok",
        "variety_score",
        "job_description_excerpt",
        "generation_time_s",
        "error",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_results:
            writer.writerow(r.model_dump(include=set(fieldnames)))

    print(f"[eval-run] Wrote {len(all_results)} rows to {csv_path}")

    # ── Also write a timestamped copy ──
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ts_path = csv_path.with_name(f"eval_results_{ts}.csv")
    import shutil
    shutil.copy2(csv_path, ts_path)
    print(f"[eval-run] Timestamped copy: {ts_path}")

    # ── Summary stats ──
    scored = [r for r in all_results if r.ruler_score > 0]
    if scored:
        avg = sum(r.ruler_score for r in scored) / len(scored)
        min_s = min(r.ruler_score for r in scored)
        max_s = max(r.ruler_score for r in scored)
        print(f"\n[eval-run] RULER stats ({len(scored)} scored):")
        print(f"  avg={avg:.3f}  min={min_s:.3f}  max={max_s:.3f}")

    de_ok = [r for r in all_results if r.language == "de" and r.eszett_free is True]
    de_total = [r for r in all_results if r.language == "de" and r.eszett_free is not None]
    if de_total:
        print(f"  Eszett-free: {len(de_ok)}/{len(de_total)}")

    pronoun_ok = [r for r in all_results if r.language == "de" and r.pronoun_ok is True]
    pronoun_total = [r for r in all_results if r.language == "de" and r.pronoun_ok is not None]
    if pronoun_total:
        print(f"  Pronoun OK:  {len(pronoun_ok)}/{len(pronoun_total)}")

    variety = [r.variety_score for r in all_results if r.variety_score > 0]
    if variety:
        print(f"  Variety avg: {sum(variety)/len(variety):.3f}")

    avg_time = sum(r.generation_time_s for r in all_results) / max(len(all_results), 1)
    print(f"  Avg generation time: {avg_time:.1f}s")

    return all_results


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run headless JD evaluation with RULER scoring."
    )
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).resolve().parent / "eval_dataset.json"),
        help="Path to eval_dataset.json",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent / "eval_results.csv"),
        help="Output CSV path",
    )
    parser.add_argument(
        "--batch", type=int, default=5,
        help="RULER scoring batch size (default: 5)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=5,
        help="Max parallel JD generation calls (default: 5)",
    )
    args = parser.parse_args()

    asyncio.run(
        run_eval(
            dataset_path=args.dataset,
            output_csv=args.output,
            batch_size=args.batch,
            concurrency=args.concurrency,
        )
    )


if __name__ == "__main__":
    main()
