import re

from models.job_models import JobBody


# ── bullet-marker cleanup ────────────────────────────────────────────
# Matches leading bullet / list markers that LLMs commonly inject:
#   -  •  *  –  —  or numbered prefixes like "1." / "1)"
_BULLET_RE = re.compile(
    r"^(?:[•\-\*–—]\s*|(?:\d+[.)]\s*))",
)


def strip_bullet_prefix(line: str) -> str:
    """Remove a single leading bullet / list-marker from *line*.

    Examples
    --------
    >>> strip_bullet_prefix("- Flexible hours")
    'Flexible hours'
    >>> strip_bullet_prefix("• Remote work")
    'Remote work'
    >>> strip_bullet_prefix("1. Health insurance")
    'Health insurance'
    >>> strip_bullet_prefix("No marker here")
    'No marker here'
    """
    return _BULLET_RE.sub("", line).strip()


def bullets(text: str) -> str:
    """Convert multi-line text to markdown bullet points.

    Any existing bullet markers are stripped first so the preview
    never shows doubled prefixes like ``- - item``.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    cleaned = [strip_bullet_prefix(l) for l in lines]
    return "\n".join(f"- {l}" for l in cleaned if l)


def job_body_to_dict(job_body: JobBody) -> dict:
    """Convert JobBody model to dictionary format used in session state.

    Bullet markers are stripped so the text-area shows clean lines
    and the preview renderer can add its own ``- `` prefix once.
    """
    return {
        "job_description": job_body.job_description,
        "requirements": "\n".join(strip_bullet_prefix(r) for r in job_body.requirements),
        "duties": "\n".join(strip_bullet_prefix(d) for d in job_body.duties),
        "benefits": "\n".join(strip_bullet_prefix(b) for b in job_body.benefits),
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
    # Remove bullet markers if present (reuse the shared regex helper)
    cleaned = [strip_bullet_prefix(l) for l in lines]
    return [c for c in cleaned if c]
