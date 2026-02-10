"""
Pydantic models for the JD Writer evaluation harness.

EvalScenario — one test-case input (Step 1 output).
EvalResult   — one test-case result (Step 2 output / CSV row).
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Step 1 output: a single evaluation scenario
# ---------------------------------------------------------------------------

class EvalScenario(BaseModel):
    """One evaluation scenario built from a duty-chunk + randomized config."""

    scenario_id: str = Field(..., description="Unique ID, e.g. 'eval_001'")

    # Job identity
    job_title: str = Field(..., description="DE category name or EN translation")
    language: Literal["de", "en"]
    category_code: str = Field(..., description="e.g. '1000'")
    category_name: str = Field(..., description="Original DE category name")
    block_name: str = Field(..., description="e.g. 'Informatik / Telekommunikation'")

    # Randomized config axes
    formality: Literal["casual", "neutral", "formal"]
    company_type: Literal[
        "startup", "scaleup", "sme", "corporate",
        "public_sector", "social_sector", "agency",
        "consulting", "hospitality", "retail",
    ]
    seniority_label: Literal["junior", "senior"]

    # Duty template from the chunk
    duty_bullets: List[str] = Field(default_factory=list)
    duty_source: str = Field(default="category", description="Always 'category' for eval")


# ---------------------------------------------------------------------------
# Step 2 output: result of one headless eval run
# ---------------------------------------------------------------------------

class EvalResult(BaseModel):
    """Result of running one EvalScenario through the generator + RULER."""

    # Identity (copied from scenario)
    scenario_id: str
    job_title: str
    language: Literal["de", "en"]
    formality: Literal["casual", "neutral", "formal"]
    company_type: str
    seniority_label: str
    category_code: str
    block_name: str

    # RULER score (now style-aware — the RULER prompt includes expected color profile)
    ruler_score: float = Field(0.0, description="RULER score in [0, 1]")

    # ── Motivkompass style adherence ──
    expected_primary_color: Optional[str] = Field(
        None,
        description="Primary Motivkompass color from the style router (red/yellow/green/blue)",
    )
    expected_secondary_color: Optional[str] = Field(
        None,
        description="Secondary color if within margin, else None",
    )

    # ── Structural checks ──
    duty_count: int = 0
    req_count: int = 0
    benefit_count: int = 0
    has_summary: bool = False

    # ── Quality checks (DE-specific flags are None for EN) ──
    eszett_free: Optional[bool] = Field(
        None, description="True if no ß found (DE only)"
    )
    pronoun_ok: Optional[bool] = Field(
        None, description="True if Sie/du consistent with formality (DE only)"
    )

    # ── Swiss German vocabulary compliance (DE only) ──
    swiss_vocab_ok: Optional[bool] = Field(
        None,
        description="True if no DE-DE vocabulary found — text uses proper CH-DE terms (DE only)",
    )
    swiss_vocab_violations: int = Field(
        0,
        description="Count of DE-DE vocabulary occurrences that should be CH-DE (DE only)",
    )
    swiss_vocab_details: Optional[str] = Field(
        None,
        description="Human-readable list of DE-DE violations, e.g. 'Gehalt (→ Salär) ×1' (DE only)",
    )

    variety_score: float = Field(
        0.0, description="Ratio of unique first-words across all bullet lists"
    )

    # Excerpts / debug info
    job_description_excerpt: str = ""
    generation_time_s: float = 0.0
    error: Optional[str] = None
