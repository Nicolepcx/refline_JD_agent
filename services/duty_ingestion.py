"""
Duty Ingestion Pipeline — Job Categories DOCX → Duty Template Chunks

Extracts structured duty templates from the Aufgaben Jobcategories document.
Each chunk contains duties for a specific job category at a specific seniority
level (Junior / Senior).

The data is stored with metadata that enables:
  1. Semantic search by job title → find the right category
  2. Seniority-aware filtering → return duties appropriate for the level

Seniority mapping (config → template level):
  intern              →  (no template — interns don't get standard duties)
  junior, mid         →  Junior template
  senior, lead, principal  →  Senior template
  None / unset        →  Both levels returned, LLM picks the best match

Chunk metadata:
  category_code    e.g. "1000", "1005", "1010"
  category_name    e.g. "Geschäftsführung / CEO / VR"
  block_name       e.g. "Management", "Informatik / Telekommunikation"
  seniority        "junior" | "senior"
  language         "de"
  dimension        "duties"
  source_file      "Aufgaben Jobcategories.docx"

See AGENTS.md for the workflow contract.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DutyChunk:
    """One duty template for a job category + seniority level."""
    content: str              # All bullets joined with newlines ("• Bullet 1\n• Bullet 2")
    duties: List[str]         # Individual duty bullet points (list)
    category_code: str        # e.g. "1000"
    category_name: str        # e.g. "Geschäftsführung / CEO / VR"
    block_name: str           # e.g. "Management"
    seniority: str            # "junior" | "senior"
    language: str = "de"
    dimension: str = "duties"
    source_file: str = "Aufgaben Jobcategories.docx"


# ---------------------------------------------------------------------------
# Seniority mapping
# ---------------------------------------------------------------------------

# Maps app seniority labels to template seniority keys.
# Interns get NO template (they don't perform standard role duties).
# Junior + Mid → "junior" template (operational, supporting tasks).
# Senior + Lead + Principal → "senior" template (ownership, strategy, leadership).

SENIORITY_MAP: dict[Optional[str], Optional[str]] = {
    "intern":    None,       # No template — interns have unique scopes
    "junior":    "junior",
    "mid":       "junior",   # Mid-level still does the "doing" part
    "senior":    "senior",
    "lead":      "senior",   # Lead = senior duties + team oversight (handled by LLM)
    "principal": "senior",   # Principal = senior duties + strategic scope (handled by LLM)
    None:        None,       # Unset → return both, let semantic search decide
    "":          None,
}


def map_seniority(app_seniority: Optional[str]) -> Optional[str]:
    """
    Map an app-level seniority label to the template seniority key.

    Returns:
        "junior", "senior", or None (meaning: return both / no template for interns).
    """
    return SENIORITY_MAP.get(app_seniority, None)


# ---------------------------------------------------------------------------
# DOCX extraction
# ---------------------------------------------------------------------------

def extract_duty_chunks(docx_path: str) -> List[DutyChunk]:
    """
    Extract duty templates from the Aufgaben Jobcategories DOCX.

    Expected format:
        BLOCK XX – Block Name (Category Refline XX)
        XXXX – Category Name
        Junior:
        • Duty bullet 1
        • Duty bullet 2
        Senior:
        • Duty bullet 1
        • Duty bullet 2
    """
    try:
        from docx import Document
    except ImportError:
        logger.error("python-docx not installed. Run: pip install python-docx")
        return []

    doc = Document(docx_path)

    # Get all non-empty lines
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    chunks: List[DutyChunk] = []
    current_block_name = "Unknown"

    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect BLOCK headers (e.g., "BLOCK 10 – Management")
        block_match = re.match(r"BLOCK\s+\d+\s*[–\-]\s*(.+?)(?:\s*\(.*\))?\s*$", line)
        if block_match:
            current_block_name = block_match.group(1).strip()
            i += 1
            continue

        # Detect category headers (e.g., "1000 – Geschäftsführung / CEO / VR")
        cat_match = re.match(r"(\d{4})\s*[–\-]\s*(.+)", line)
        if cat_match:
            code = cat_match.group(1).strip()
            name = cat_match.group(2).strip()
            i += 1

            # Parse Junior and Senior sections for this category
            junior_duties: List[str] = []
            senior_duties: List[str] = []
            current_section: Optional[str] = None

            while i < len(lines):
                inner = lines[i]

                # Stop if we hit the next category or block
                if re.match(r"\d{4}\s*[–\-]", inner) or inner.startswith("BLOCK"):
                    break

                # Detect section markers
                if re.match(r"Junior\s*:", inner, re.IGNORECASE):
                    current_section = "junior"
                    i += 1
                    continue
                elif re.match(r"Senior\s*:", inner, re.IGNORECASE):
                    current_section = "senior"
                    i += 1
                    continue

                # It's a duty bullet (strip bullet markers)
                duty = re.sub(r"^[•\-\*–]\s*", "", inner).strip()
                if duty and len(duty) > 5 and current_section:
                    if current_section == "junior":
                        junior_duties.append(duty)
                    elif current_section == "senior":
                        senior_duties.append(duty)

                i += 1

            # Create chunks
            if junior_duties:
                content = "\n".join(f"• {d}" for d in junior_duties)
                chunks.append(DutyChunk(
                    content=content,
                    duties=junior_duties,
                    category_code=code,
                    category_name=name,
                    block_name=current_block_name,
                    seniority="junior",
                ))

            if senior_duties:
                content = "\n".join(f"• {d}" for d in senior_duties)
                chunks.append(DutyChunk(
                    content=content,
                    duties=senior_duties,
                    category_code=code,
                    category_name=name,
                    block_name=current_block_name,
                    seniority="senior",
                ))

            continue  # Don't increment i — inner loop already did

        i += 1

    logger.info(
        f"Extracted {len(chunks)} duty chunks "
        f"({len([c for c in chunks if c.seniority == 'junior'])} junior, "
        f"{len([c for c in chunks if c.seniority == 'senior'])} senior) "
        f"from {docx_path}"
    )
    return chunks


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def duty_chunks_to_jsonl(chunks: List[DutyChunk], output_path: str) -> None:
    """Save duty chunks to JSONL for fast rebuilds (committed to repo)."""
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    logger.info(f"Wrote {len(chunks)} duty chunks to {output_path}")


def load_duty_chunks_from_jsonl(jsonl_path: str) -> List[dict]:
    """Load duty chunks from JSONL file."""
    chunks = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks
