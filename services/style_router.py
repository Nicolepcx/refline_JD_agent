"""
Style Router — Motivkompass-based style profile selector.

Uses a scoring rubric (not hard-mapping) to decide which Motivkompass color
profile best fits the current job configuration.  No LLM call needed for
standard cases; all logic is deterministic and auditable.

See SKILLS.md for the full scoring table and AGENTS.md for the workflow contract.
"""

from __future__ import annotations

from models.job_models import JobGenerationConfig, StyleProfile
from logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Scoring weights per signal
# ---------------------------------------------------------------------------
# Each key maps to a dict of {color: weight}.
# Weights are accumulated from industry, company_type, formality, seniority.

_COLOR_SIGNALS: dict[str, dict[str, float]] = {
    # ── Industry signals ──
    "finance":        {"blue": 0.4, "green": 0.2},
    "healthcare":     {"green": 0.4, "blue": 0.2},
    "social_care":    {"green": 0.4, "yellow": 0.2},
    "public_it":      {"blue": 0.3, "green": 0.3},
    "ai_startup":     {"yellow": 0.3, "red": 0.2},
    "ecommerce":      {"red": 0.3, "yellow": 0.2},
    "manufacturing":  {"blue": 0.3, "green": 0.2},
    "generic":        {"blue": 0.1},

    # ── Company type signals ──
    "startup":        {"yellow": 0.3, "red": 0.2},
    "scaleup":        {"red": 0.2, "blue": 0.2},
    "sme":            {"blue": 0.2, "green": 0.2},
    "corporate":      {"blue": 0.3, "green": 0.2},
    "public_sector":  {"blue": 0.3, "green": 0.3},
    "social_sector":  {"green": 0.4, "blue": 0.2},
    "agency":         {"yellow": 0.3, "red": 0.2},
    "consulting":     {"red": 0.3, "blue": 0.2},
    "hospitality":    {"yellow": 0.3, "green": 0.2},
    "retail":         {"yellow": 0.2, "red": 0.2},

    # ── Formality signals ──
    "casual":         {"yellow": 0.3, "red": 0.1},
    "neutral":        {"blue": 0.2},
    "formal":         {"blue": 0.3, "green": 0.2},

    # ── Seniority signals ──
    "intern":         {"green": 0.3, "yellow": 0.2},
    "junior":         {"yellow": 0.2, "green": 0.1},
    "mid":            {"blue": 0.1},
    "senior":         {"blue": 0.2, "red": 0.1},
    "lead":           {"red": 0.3, "blue": 0.2},
    "principal":      {"blue": 0.3, "red": 0.2},
}

# Secondary color is only added if within this margin of the primary score
_MARGIN = 0.15

# Mapping from primary color to the two Motivkompass axes
_AXIS_MAP: dict[str, tuple[str, str]] = {
    "red":    ("proaktiv",  "objektbezug"),
    "yellow": ("proaktiv",  "personenbezug"),
    "green":  ("reaktiv",   "personenbezug"),
    "blue":   ("reaktiv",   "objektbezug"),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_style(cfg: JobGenerationConfig) -> StyleProfile:
    """
    Score-based style router.

    Accumulates weights from industry, company_type, formality, and seniority,
    then picks primary (argmax) and optional secondary (within margin).
    Default bias: blue +0.10 — safer / more credible for job ads.

    Returns a fully populated StyleProfile.
    """
    scores: dict[str, float] = {"red": 0.0, "yellow": 0.0, "green": 0.0, "blue": 0.0}

    # Accumulate signals from all dimensions
    signal_keys = [cfg.industry, cfg.company_type, cfg.formality, cfg.seniority_label]
    for signal_key in signal_keys:
        if signal_key and signal_key in _COLOR_SIGNALS:
            for color, weight in _COLOR_SIGNALS[signal_key].items():
                scores[color] += weight

    # Default bias: blue-leaning for job ads (safe, credible, evidence-based)
    scores["blue"] += 0.10

    # Rank and select
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary_color = ranked[0][0]
    primary_score = ranked[0][1]

    runner_up_color = ranked[1][0]
    runner_up_score = ranked[1][1]

    secondary_color = runner_up_color if (primary_score - runner_up_score) < _MARGIN else None

    # Derive axes from primary color
    interaction_mode, reference_frame = _AXIS_MAP[primary_color]

    # Build rationale string for debugging / UI
    rationale = " | ".join(f"{c}: {s:.2f}" for c, s in ranked)

    profile = StyleProfile(
        primary_color=primary_color,
        secondary_color=secondary_color,
        interaction_mode=interaction_mode,
        reference_frame=reference_frame,
        scoring_rationale=rationale,
    )

    logger.info(
        f"[Style Router] primary={primary_color} "
        f"secondary={secondary_color or 'none'} "
        f"mode={interaction_mode} | scores: {rationale}"
    )

    return profile


def explain_style_routing(cfg: JobGenerationConfig) -> str:
    """
    Human-readable explanation of the style routing decision.
    Useful for the UI temperature-breakdown equivalent.
    """
    scores: dict[str, float] = {"red": 0.0, "yellow": 0.0, "green": 0.0, "blue": 0.0}
    parts: list[str] = []

    signal_keys = [
        ("industry", cfg.industry),
        ("company_type", cfg.company_type),
        ("formality", cfg.formality),
        ("seniority", cfg.seniority_label),
    ]

    for label, key in signal_keys:
        if key and key in _COLOR_SIGNALS:
            deltas = _COLOR_SIGNALS[key]
            delta_str = ", ".join(f"{c}+{w:.2f}" for c, w in deltas.items())
            parts.append(f"{label}='{key}' => {delta_str}")
            for color, weight in deltas.items():
                scores[color] += weight
        elif key:
            parts.append(f"{label}='{key}' => no signal")

    scores["blue"] += 0.10
    parts.append("Default blue bias => blue+0.10")

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = ranked[0]
    runner = ranked[1]

    parts.append(f"\nFinal scores: " + " | ".join(f"{c}: {s:.2f}" for c, s in ranked))
    parts.append(f"Primary: {primary[0]} ({primary[1]:.2f})")

    if (primary[1] - runner[1]) < _MARGIN:
        parts.append(f"Secondary: {runner[0]} ({runner[1]:.2f}) — within margin {_MARGIN}")
    else:
        parts.append(f"No secondary — gap {primary[1] - runner[1]:.2f} > margin {_MARGIN}")

    return "\n".join(parts)
