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
from openai.types.chat.chat_completion import Choice
from openai.types.chat import ChatCompletionMessage

# Project imports  (run from project root: python -m evals.run_eval)
from models.job_models import JobBody, JobGenerationConfig, StyleProfile
from generators.job_generator import render_job_body_async
from ruler.ruler_utils import score_group_with_fallback
from services.swiss_german import check_pronoun_consistency, check_swiss_vocab
from services.style_router import route_style
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
# Motivkompass color descriptions (for RULER prompt injection)
# ---------------------------------------------------------------------------

_COLOR_TONE_DESCRIPTIONS: dict[str, str] = {
    "red": (
        "Red (Macher): Direct, results-oriented, short declarative sentences, "
        "active voice, power language, speed/status emphasis, no passive or committee-speak."
    ),
    "yellow": (
        "Yellow (Entertainer): Creative, friendly, freedom-focused, team spirit, "
        "variety, informal energy, fun, no rigidity or bureaucracy."
    ),
    "blue": (
        "Blue (Denker): Fact-based, structured, evidence-driven, precise, "
        "quality-focused, concrete, no hype or vague superlatives."
    ),
    "green": (
        "Green (Bewahrer): Trust-building, harmonious, relationship-oriented, "
        "safety-focused, belonging, inclusive, no pressure or aggression."
    ),
}

_AXIS_DESCRIPTIONS: dict[str, str] = {
    "proaktiv": "Proaktiv: Short declarative sentences, active voice, imperatives allowed.",
    "reaktiv": "Reaktiv: Longer connected sentences, conditional/inclusive phrasing.",
    "personenbezug": "Personenbezug: 'you/we' framing, emotional cues, community language.",
    "objektbezug": "Objektbezug: Third-person, evidence, data, process-oriented language.",
}


# ---------------------------------------------------------------------------
# Style-aware RULER trajectory builder (eval-only)
# ---------------------------------------------------------------------------

def _build_eval_trajectory(
    scenario: EvalScenario,
    cfg: JobGenerationConfig,
    job_body: JobBody,
    style_profile: StyleProfile,
) -> art.Trajectory:
    """
    Build a RULER trajectory that includes the expected Motivkompass profile
    and (for DE texts) Swiss German writing rules in the scoring context.

    This makes RULER penalise style drift and CH-DE vocabulary violations
    as part of the overall quality score.
    """
    # ── Style context block ──
    primary_desc = _COLOR_TONE_DESCRIPTIONS.get(style_profile.primary_color, "")
    mode_desc = _AXIS_DESCRIPTIONS.get(style_profile.interaction_mode, "")
    frame_desc = _AXIS_DESCRIPTIONS.get(style_profile.reference_frame, "")

    style_block = (
        f"\n## Expected Motivkompass Style Profile\n"
        f"Primary color: {style_profile.primary_color}\n"
        f"  → {primary_desc}\n"
        f"Mode: {mode_desc}\n"
        f"Frame: {frame_desc}\n"
    )
    if style_profile.secondary_color:
        sec_desc = _COLOR_TONE_DESCRIPTIONS.get(style_profile.secondary_color, "")
        style_block += f"Secondary color: {style_profile.secondary_color}\n  → {sec_desc}\n"

    # ── Swiss German block (DE only) ──
    swiss_block = ""
    if scenario.language == "de":
        swiss_block = (
            "\n## Swiss German Writing Rules (MANDATORY for DE texts)\n"
            "- No ß (Eszett) — always 'ss' (e.g. 'gross' not 'groß')\n"
            "- Swiss vocabulary: 'Salär' not 'Gehalt', 'Ferien' not 'Urlaub', "
            "'Matura' not 'Abitur', 'berufliche Vorsorge (BVG)' not 'betriebliche Altersvorsorge', "
            "'Arbeitnehmende' not 'Arbeitnehmer', 'Pensionskasse' not 'Betriebsrente'\n"
            "- Neutral, factual tone (less promotional than standard DE-DE)\n"
            "- Pronoun consistency: "
        )
        if scenario.formality == "casual":
            swiss_block += "'du' form throughout (never 'Sie' as formal address)\n"
        else:
            swiss_block += "'Sie' form throughout (never 'du' as informal address)\n"

    system_msg = {
        "role": "system",
        "content": (
            "You are an expert HR quality judge. You evaluate job descriptions for:\n"
            "1. Clarity, tone, alignment with the requested role and seniority\n"
            "2. Usefulness and realism for candidates\n"
            "3. **Adherence to the specified Motivkompass style profile** (tone, sentence structure, vocabulary)\n"
            "4. **Swiss German writing standards** (for DE texts: no ß, CH vocabulary, correct pronouns)\n"
            "5. Sentence-start variety (no repetitive patterns in bullet lists)\n\n"
            "Penalise texts that:\n"
            "- Don't match the expected style color/tone\n"
            "- Use DE-DE vocabulary instead of CH-DE (German texts only)\n"
            "- Contain ß characters (German texts only)\n"
            "- Have monotonous sentence openings\n"
            "- Are generic, templated, or misaligned with seniority level"
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            "Evaluate the quality of the following job description.\n\n"
            f"Job title: {scenario.job_title}\n"
            f"Language: {scenario.language.upper()}\n"
            f"Formality: {scenario.formality}\n"
            f"Company type: {cfg.company_type}\n"
            f"Seniority: {scenario.seniority_label}\n"
            f"{style_block}"
            f"{swiss_block}\n"
            f"JobBody JSON:\n{job_body.model_dump_json(indent=2, ensure_ascii=False)}\n"
        ),
    }

    assistant_msg = ChatCompletionMessage(
        role="assistant",
        content=job_body.model_dump_json(indent=2, ensure_ascii=False),
    )

    choice = Choice(
        finish_reason="stop",
        index=0,
        message=assistant_msg,
    )

    return art.Trajectory(
        messages_and_choices=[system_msg, user_msg, choice],
        reward=0.0,
    )


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
    cfg = _build_config(scenario)

    # ── Determine expected Motivkompass color ──
    style_profile = route_style(cfg)

    result = EvalResult(
        scenario_id=scenario.scenario_id,
        job_title=scenario.job_title,
        language=scenario.language,
        formality=scenario.formality,
        company_type=scenario.company_type,
        seniority_label=scenario.seniority_label,
        category_code=scenario.category_code,
        block_name=scenario.block_name,
        expected_primary_color=style_profile.primary_color,
        expected_secondary_color=style_profile.secondary_color,
    )

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

    # ── Full generated content (for gold-standard curation) ──
    _SEP = " || "
    result.gen_job_description = job_body.job_description or ""
    result.gen_duties = _SEP.join(job_body.duties) if job_body.duties else ""
    result.gen_requirements = _SEP.join(job_body.requirements) if job_body.requirements else ""
    result.gen_benefits = _SEP.join(job_body.benefits) if job_body.benefits else ""
    result.gen_summary = job_body.summary or ""

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

        # ── Swiss vocabulary compliance ──
        vocab_ok, vocab_count, vocab_details = check_swiss_vocab(all_text)
        result.swiss_vocab_ok = vocab_ok
        result.swiss_vocab_violations = vocab_count
        if vocab_details:
            result.swiss_vocab_details = "; ".join(vocab_details[:10])  # cap at 10 entries

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
    """
    Score a batch with RULER using style-aware trajectories.

    The RULER prompt now includes the expected Motivkompass profile and
    Swiss German rules, so the judge factors in style adherence and
    CH-DE vocabulary compliance when scoring.

    Mutates ``result.ruler_score`` in-place.
    """
    if not batch:
        return

    trajectories = []
    for scenario, job_body, result in batch:
        cfg = _build_config(scenario)
        # Re-derive full style profile with correct axes (cheap, no LLM call)
        style_profile = route_style(cfg)
        traj = _build_eval_trajectory(scenario, cfg, job_body, style_profile)
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
        "expected_primary_color",
        "expected_secondary_color",
        "duty_count",
        "req_count",
        "benefit_count",
        "has_summary",
        "eszett_free",
        "pronoun_ok",
        "swiss_vocab_ok",
        "swiss_vocab_violations",
        "swiss_vocab_details",
        "variety_score",
        # Full generated content (for gold-standard curation)
        "gen_job_description",
        "gen_duties",
        "gen_requirements",
        "gen_benefits",
        "gen_summary",
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

    pronoun_ok_list = [r for r in all_results if r.language == "de" and r.pronoun_ok is True]
    pronoun_total = [r for r in all_results if r.language == "de" and r.pronoun_ok is not None]
    if pronoun_total:
        print(f"  Pronoun OK:  {len(pronoun_ok_list)}/{len(pronoun_total)}")

    # Swiss vocabulary compliance
    vocab_ok_list = [r for r in all_results if r.language == "de" and r.swiss_vocab_ok is True]
    vocab_total = [r for r in all_results if r.language == "de" and r.swiss_vocab_ok is not None]
    if vocab_total:
        print(f"  Swiss vocab: {len(vocab_ok_list)}/{len(vocab_total)}")
        total_violations = sum(r.swiss_vocab_violations for r in vocab_total)
        if total_violations > 0:
            print(f"    Total DE-DE vocabulary violations: {total_violations}")

    # Style color distribution
    color_counts: dict[str, int] = {}
    for r in all_results:
        if r.expected_primary_color:
            color_counts[r.expected_primary_color] = color_counts.get(r.expected_primary_color, 0) + 1
    if color_counts:
        print(f"  Style colors: {' | '.join(f'{c}: {n}' for c, n in sorted(color_counts.items()))}")

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
