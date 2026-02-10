"""
Duty Retriever — 3-tier cascade for job duties

Priority cascade:
  1. User-provided duties (pre-filled in the "Duty" text area → duty_keywords)
  2. Job-category match from the duty vector store (semantic search)
  3. LLM generation (fallback — no duties injected, LLM creates from scratch)

Seniority mapping (see duty_ingestion.py for details):
  intern              →  No template (interns have unique scopes)
  junior, mid         →  "junior" template
  senior, lead, principal  →  "senior" template
  None / unset        →  Both levels returned, best match by relevance

For lead/principal, the retrieved duties are augmented with a seniority-
escalation hint so the LLM adds budget/team oversight language on top.
"""

from __future__ import annotations

from typing import List, Optional

from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Seniority mapping (mirrors duty_ingestion.SENIORITY_MAP)
# ---------------------------------------------------------------------------

_SENIORITY_TO_TEMPLATE: dict[Optional[str], Optional[str]] = {
    "intern":    None,       # No template
    "junior":    "junior",
    "mid":       "junior",
    "senior":    "senior",
    "lead":      "senior",
    "principal": "senior",
    None:        None,       # Return both, let relevance decide
    "":          None,
}


# Additional context hints for lead/principal (added to duty list)
_SENIORITY_ESCALATION_HINTS: dict[str, dict[str, str]] = {
    "lead": {
        "de": "Führung und Weiterentwicklung des Teams sowie Verantwortung für die fachliche Steuerung",
        "en": "Leading and developing the team with responsibility for professional oversight",
    },
    "principal": {
        "de": "Strategische Verantwortung und fachliche Führung über mehrere Teams oder Bereiche hinweg",
        "en": "Strategic responsibility and technical leadership across multiple teams or domains",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def retrieve_duty_templates(
    job_title: str,
    seniority: Optional[str],
    lang: str = "de",
    vector_store=None,
    k: int = 3,
) -> List[str]:
    """
    Search the vector store for matching job-category duty templates.

    Uses semantic search on the job title to find the best matching
    category, then returns duties for the appropriate seniority level.

    Args:
        job_title:    The job title to match against categories
        seniority:    App-level seniority label (intern/junior/mid/senior/lead/principal)
        lang:         Language ("de" or "en")
        vector_store: VectorStoreManager instance (from startup.get_style_vector_store)
        k:            How many category matches to retrieve

    Returns:
        List of duty bullet-point strings (empty if no match or intern)
    """
    # --- Guard: interns get no template duties ---
    template_seniority = _SENIORITY_TO_TEMPLATE.get(seniority)
    if seniority == "intern":
        logger.info("[Duty Retriever] Seniority=intern → no template duties")
        return []

    if vector_store is None:
        logger.debug("[Duty Retriever] No vector store available")
        return []

    try:
        is_available = getattr(vector_store, "is_available", lambda: True)
        if not is_available():
            logger.debug("[Duty Retriever] Vector store not available")
            return []
    except Exception:
        return []

    # --- Semantic search across all duty categories ---
    try:
        results = vector_store.search_company_content(
            company_name="duty_templates",
            query=job_title,
            k=k * 2,  # over-retrieve then filter by seniority
        )
    except Exception as e:
        logger.warning(f"[Duty Retriever] Search failed: {e}")
        return []

    if not results:
        logger.debug(f"[Duty Retriever] No matches for '{job_title}'")
        return []

    # --- Filter by seniority ---
    matched_duties: List[str] = []
    best_category = None

    for r in results:
        meta = r.get("metadata", {})
        chunk_seniority = meta.get("seniority", "")

        # If we have a specific template seniority, filter
        if template_seniority and chunk_seniority != template_seniority:
            continue

        # Track which category we matched (for logging)
        if best_category is None:
            best_category = f"{meta.get('category_code', '?')} – {meta.get('category_name', '?')}"

        content = r.get("content", "")
        for line in content.split("\n"):
            line = line.strip().lstrip("•-* ").strip()
            if line and len(line) > 5 and line not in matched_duties:
                matched_duties.append(line)

    # --- Seniority escalation hints for lead/principal ---
    if seniority in _SENIORITY_ESCALATION_HINTS:
        hint = _SENIORITY_ESCALATION_HINTS[seniority].get(lang)
        if hint and hint not in matched_duties:
            matched_duties.append(hint)

    if matched_duties:
        logger.info(
            f"[Duty Retriever] Found {len(matched_duties)} duties for '{job_title}' "
            f"(seniority={seniority} → template={template_seniority}, "
            f"best_category={best_category})"
        )
    else:
        logger.debug(f"[Duty Retriever] No seniority-filtered matches for '{job_title}'")

    return matched_duties


def build_duty_cascade(
    user_duties: List[str],
    job_title: str,
    seniority: Optional[str],
    lang: str = "de",
    vector_store=None,
) -> tuple[List[str], str]:
    """
    Execute the full 3-tier duty cascade.

    Returns:
        (duties_list, source) where source is one of:
          "user"     — user provided duties in the text area
          "category" — matched from job-category vector store
          "llm"      — empty list, LLM should generate from scratch
    """
    # --- Tier 1: User-provided duties ---
    if user_duties:
        logger.info(f"[Duty Cascade] Tier 1: Using {len(user_duties)} user-provided duties")
        return user_duties, "user"

    # --- Tier 2: Job-category match ---
    category_duties = retrieve_duty_templates(
        job_title=job_title,
        seniority=seniority,
        lang=lang,
        vector_store=vector_store,
    )
    if category_duties:
        logger.info(f"[Duty Cascade] Tier 2: Using {len(category_duties)} category-matched duties")
        return category_duties, "category"

    # --- Tier 3: LLM fallback ---
    logger.info("[Duty Cascade] Tier 3: No duties found — LLM will generate from scratch")
    return [], "llm"
