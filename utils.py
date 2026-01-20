from models.job_models import JobBody


def bullets(text: str) -> str:
    """Convert multi-line text to markdown bullet points."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    return "\n".join(f"- {l}" for l in lines)


def job_body_to_dict(job_body: JobBody) -> dict:
    """Convert JobBody model to dictionary format used in session state."""
    return {
        "job_description": job_body.job_description,
        "requirements": "\n".join(job_body.requirements),
        "duties": "\n".join(job_body.duties),
        "benefits": "\n".join(job_body.benefits),
        "footer": job_body.summary or "",
    }


def dict_to_job_body(data: dict) -> JobBody:
    """Convert dictionary format to JobBody model."""
    return JobBody(
        job_description=data.get("description", ""),
        requirements=_parse_bullets(data.get("requirements", "")),
        duties=_parse_bullets(data.get("duties", "")),
        benefits=_parse_bullets(data.get("benefits", "")),
        summary=data.get("footer", ""),
    )


def _parse_bullets(text: str) -> list[str]:
    """Parse bullet point text into a list of strings."""
    if not text:
        return []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Remove bullet markers if present
    cleaned = [l.lstrip("- •*").strip() for l in lines]
    return cleaned
