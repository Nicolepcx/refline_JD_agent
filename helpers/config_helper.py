"""
Helper functions to convert between session state and JobGenerationConfig.
"""
import streamlit as st
from models.job_models import JobGenerationConfig, SkillItem
from utils import job_body_to_dict, strip_bullet_prefix


def get_job_config_from_session() -> JobGenerationConfig:
    """
    Build JobGenerationConfig from session state.
    Uses session state values if available, otherwise defaults.
    """
    seniority = st.session_state.get("config_seniority_label", None) or None
    if seniority == "":
        seniority = None
    
    min_years = st.session_state.get("config_min_years", None)
    if min_years == 0:
        min_years = None
    
    max_years = st.session_state.get("config_max_years", None)
    if max_years == 0:
        max_years = None
    
    return JobGenerationConfig(
        language=st.session_state.get("config_language", "en"),
        formality=st.session_state.get("config_formality", "neutral"),
        company_type=st.session_state.get("config_company_type", "scaleup"),
        industry=st.session_state.get("config_industry", "generic"),
        seniority_label=seniority,
        min_years_experience=min_years,
        max_years_experience=max_years,
        skills=_parse_skills_from_session(),
        benefit_keywords=_parse_benefits_from_session(),
        duty_keywords=_parse_duty_keywords_from_session(),
    )


def update_session_from_job_body(job_body_dict: dict):
    """
    Update session state with values from a generated job body.
    IMPORTANT: Only updates body fields (description, requirements, duties, benefits, footer).
    Does NOT modify job_headline, job_intro, or caption - these are preserved.
    """
    # Preserve existing job_headline and job_intro before any updates
    # These are user-entered fields that should never be overwritten by generation
    preserved_headline = st.session_state.get("job_headline", "")
    preserved_intro = st.session_state.get("job_intro", "")
    preserved_caption = st.session_state.get("caption", "")
    
    # Map the job body fields to session state keys
    # Only update body fields, preserve job_headline and job_intro
    # Ensure all values are strings (text_area requires strings)
    if "job_description" in job_body_dict:
        value = job_body_dict["job_description"]
        st.session_state["description"] = str(value) if value is not None else ""
    if "requirements" in job_body_dict:
        value = job_body_dict["requirements"]
        # Handle both string and list formats; strip bullet markers to avoid doubling
        if isinstance(value, list):
            st.session_state["requirements"] = "\n".join(
                strip_bullet_prefix(str(item)) for item in value
            )
        else:
            st.session_state["requirements"] = _strip_bullets_from_text(value)
    if "duties" in job_body_dict:
        value = job_body_dict["duties"]
        if isinstance(value, list):
            st.session_state["duties"] = "\n".join(
                strip_bullet_prefix(str(item)) for item in value
            )
        else:
            st.session_state["duties"] = _strip_bullets_from_text(value)
    if "benefits" in job_body_dict:
        value = job_body_dict["benefits"]
        if isinstance(value, list):
            st.session_state["benefits"] = "\n".join(
                strip_bullet_prefix(str(item)) for item in value
            )
        else:
            st.session_state["benefits"] = _strip_bullets_from_text(value)
    if "footer" in job_body_dict:
        value = job_body_dict["footer"]
        st.session_state["footer"] = str(value) if value is not None else ""
    
    # Explicitly restore preserved values to ensure they're never overwritten
    if preserved_headline:
        st.session_state["job_headline"] = preserved_headline
    if preserved_intro:
        st.session_state["job_intro"] = preserved_intro
    if preserved_caption:
        st.session_state["caption"] = preserved_caption


def _strip_bullets_from_text(value) -> str:
    """Strip bullet markers from each line of a multi-line string."""
    if value is None:
        return ""
    text = str(value)
    lines = text.splitlines()
    cleaned = [strip_bullet_prefix(line) for line in lines]
    return "\n".join(cleaned)


def _parse_skills_from_session() -> list[SkillItem]:
    """Parse skills from session state if available."""
    skills_text = st.session_state.get("config_skills", "")
    if not skills_text:
        return []
    
    skills = []
    for line in skills_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Simple parsing: assume format is "name" or "name (category, level)"
        if "(" in line and ")" in line:
            name = line.split("(")[0].strip()
            rest = line.split("(")[1].split(")")[0].strip()
            parts = [p.strip() for p in rest.split(",")]
            category = parts[0] if len(parts) > 0 else None
            level = parts[1] if len(parts) > 1 else None
            skills.append(SkillItem(name=name, category=category, level=level))
        else:
            skills.append(SkillItem(name=line))
    
    return skills


def _parse_duty_keywords_from_session() -> list[str]:
    """
    Parse duty keywords from the 'duties' text area in session state.
    
    These are user-provided duty bullet points that take highest priority
    in the 3-tier duty cascade:
      1. User-provided (this function)
      2. Job-category match from vector DB
      3. LLM generation (fallback)
    """
    duties_text = st.session_state.get("duties", "")
    if not duties_text or not duties_text.strip():
        return []
    
    keywords = []
    for line in duties_text.strip().splitlines():
        line = strip_bullet_prefix(line)
        if line and len(line) > 5:
            keywords.append(line)
    
    return keywords


def _parse_benefits_from_session() -> list[str]:
    """Parse benefit keywords from session state if available.
    
    Supports both formats:
    - One keyword per line (newline-separated)
    - Comma-separated keywords on one or multiple lines
    """
    benefits_text = st.session_state.get("config_benefit_keywords", "")
    if not benefits_text:
        return []
    
    # First, split by newlines
    lines = [line.strip() for line in benefits_text.splitlines() if line.strip()]
    
    # Then, for each line, split by commas and flatten
    keywords = []
    for line in lines:
        # Split by comma and add each part as a keyword
        parts = [part.strip() for part in line.split(",") if part.strip()]
        keywords.extend(parts)
    
    return keywords

