"""
Helper functions to convert between session state and JobGenerationConfig.
"""
import streamlit as st
from models.job_models import JobGenerationConfig, SkillItem
from utils import job_body_to_dict


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
        # Handle both string and list formats
        if isinstance(value, list):
            st.session_state["requirements"] = "\n".join(str(item) for item in value)
        else:
            st.session_state["requirements"] = str(value) if value is not None else ""
    if "duties" in job_body_dict:
        value = job_body_dict["duties"]
        if isinstance(value, list):
            st.session_state["duties"] = "\n".join(str(item) for item in value)
        else:
            st.session_state["duties"] = str(value) if value is not None else ""
    if "benefits" in job_body_dict:
        value = job_body_dict["benefits"]
        if isinstance(value, list):
            st.session_state["benefits"] = "\n".join(str(item) for item in value)
        else:
            st.session_state["benefits"] = str(value) if value is not None else ""
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

