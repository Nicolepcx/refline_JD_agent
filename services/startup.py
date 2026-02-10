"""
Startup module — ensures the style + duty vector index is ready before serving.

On first launch (or when the FAISS index is missing), this module
automatically rebuilds the index from:
  1. ``style_chunks.jsonl`` + ``duty_chunks.jsonl`` (pre-extracted, committed to repo)
  2. Fallback: re-extract from source PDFs / DOCX if JSONL is absent

After the index is built, it is persisted to ``VECTOR_STORE_DIR`` (which should
be a DigitalOcean persistent volume in production so it survives restarts).

Usage:
    from services.startup import ensure_style_index, get_vector_store_manager

    # Call once at app startup (idempotent)
    ensure_style_index()

    # Get the cached VectorStoreManager singleton
    vs = get_vector_store_manager()
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from logging_config import get_logger

logger = get_logger(__name__)

# Pre-extracted duty chunks (committed to the repo alongside style_chunks.jsonl).
try:
    from config import DUTY_CHUNKS_PATH as _DUTY_CFG
except ImportError:
    _DUTY_CFG = None
DUTY_CHUNKS_PATH: str = _DUTY_CFG or os.getenv("DUTY_CHUNKS_PATH", "duty_chunks.jsonl")

# Module-level singleton
_style_vector_store: Optional[object] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_style_index() -> bool:
    """
    Ensure the FAISS style+duty index exists and is ready.

    Checks ``VECTOR_STORE_DIR/faiss_index/``.  If the index is missing,
    rebuilds it from JSONL files (style_chunks.jsonl + duty_chunks.jsonl)
    or, as a fallback, re-extracts from source PDFs/DOCX.

    Returns True if the index is available, False on failure.
    """
    from config import VECTOR_STORE_DIR, STYLE_CHUNKS_PATH, PDF_DIR

    faiss_index_dir = Path(VECTOR_STORE_DIR) / "faiss_index"
    index_file = faiss_index_dir / "index.faiss"

    if index_file.exists():
        logger.info(f"[Startup] Style+duty index found at {faiss_index_dir}")
        return True

    logger.info("[Startup] Style+duty index not found — building now …")

    # --- Strategy 1: Build from pre-extracted JSONL files (fast) ---
    style_jsonl = Path(STYLE_CHUNKS_PATH)
    duty_jsonl = Path(DUTY_CHUNKS_PATH)

    has_style = style_jsonl.exists()
    has_duty = duty_jsonl.exists()

    if has_style or has_duty:
        logger.info(
            f"[Startup] Loading chunks from JSONL "
            f"(style={has_style}, duty={has_duty})"
        )
        ok = _embed_from_jsonl(
            style_jsonl if has_style else None,
            duty_jsonl if has_duty else None,
            VECTOR_STORE_DIR,
        )
        if ok:
            logger.info("[Startup] ✓ Style+duty index built from JSONL")
            return True
        else:
            logger.warning("[Startup] JSONL embedding failed — trying source extraction")

    # --- Strategy 2: Extract from PDFs + DOCX then embed ---
    pdf_dir = Path(PDF_DIR)
    if pdf_dir.is_dir() and any(pdf_dir.glob("*.pdf")):
        logger.info(f"[Startup] Extracting from PDFs in {pdf_dir}")
        ok = _extract_and_embed(pdf_dir, style_jsonl, VECTOR_STORE_DIR)
        if ok:
            logger.info("[Startup] ✓ Style index built from PDFs")
            # duty JSONL might still exist even if style didn't — try adding duties
            if duty_jsonl.exists():
                _embed_duty_chunks_into_existing(duty_jsonl, VECTOR_STORE_DIR)
            return True
        else:
            logger.error("[Startup] PDF extraction + embedding failed")

    # --- Neither source available: style routing will use hardcoded defaults ---
    logger.warning(
        "[Startup] No style+duty index built (JSONL and source files both unavailable). "
        "Style routing will fall back to hardcoded defaults; duty cascade will skip tier 2."
    )
    return False


def get_vector_store_manager():
    """
    Return a cached VectorStoreManager pointing at the style + duty index.

    Creates the manager on first call and reuses it afterwards.
    Returns None if the index is not available.
    """
    global _style_vector_store

    if _style_vector_store is not None:
        return _style_vector_store

    try:
        from config import VECTOR_STORE_DIR
        from services.vector_store import VectorStoreManager

        vs = VectorStoreManager(
            store_type="faiss",
            persist_directory=VECTOR_STORE_DIR,
        )
        if vs.is_available():
            _style_vector_store = vs
            logger.info(f"[Startup] Style vector store loaded from {VECTOR_STORE_DIR}")
            return vs
        else:
            logger.warning("[Startup] Style vector store not available (no index or no embeddings)")
            return None
    except Exception as e:
        logger.warning(f"[Startup] Could not load style vector store: {e}")
        return None


# Backward-compatible alias
get_style_vector_store = get_vector_store_manager


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _embed_from_jsonl(
    style_jsonl: Optional[Path],
    duty_jsonl: Optional[Path],
    store_dir: str,
) -> bool:
    """
    Read style + duty chunks from JSONL files and embed into a single FAISS index.

    Style chunks are stored with ``company_name = "style_{color}"`` (or ``style_syntax``).
    Duty chunks are stored with ``company_name = "duty_templates"`` so the retriever
    can search them by job-title similarity and filter by seniority metadata.

    Does not require pdfminer or python-docx — only the OpenRouter embedding API.
    """
    try:
        from langchain_core.documents import Document
        from services.vector_store import VectorStoreManager

        # --- Read style chunks ---
        style_chunks = []
        if style_jsonl and style_jsonl.exists():
            with open(style_jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        style_chunks.append(json.loads(line))

        # --- Read duty chunks ---
        duty_chunks = []
        if duty_jsonl and duty_jsonl.exists():
            with open(duty_jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        duty_chunks.append(json.loads(line))

        if not style_chunks and not duty_chunks:
            logger.warning("[Startup] Both JSONL files are empty or missing")
            return False

        # Create VectorStoreManager
        vs = VectorStoreManager(
            store_type="faiss",
            persist_directory=store_dir,
        )
        if not vs.embeddings:
            logger.error("[Startup] Embeddings not available (check OPENROUTER_API_KEY)")
            return False

        documents = []

        # --- Build style documents ---
        for chunk in style_chunks:
            if chunk.get("dimension") == "syntax" and chunk.get("profile_color") == "any":
                company_name = "style_syntax"
            else:
                company_name = f"style_{chunk['profile_color']}"

            metadata = {
                "company_name": company_name,
                "profile_color": chunk.get("profile_color", ""),
                "dimension": chunk.get("dimension", ""),
                "language": chunk.get("language", "de"),
                "use_case": chunk.get("use_case", "job_ads"),
                "source_file": chunk.get("source_file", ""),
            }
            if chunk.get("mode"):
                metadata["mode"] = chunk["mode"]

            documents.append(Document(
                page_content=chunk["content"],
                metadata=metadata,
            ))

        # --- Build duty documents ---
        for chunk in duty_chunks:
            # Searchable text = category name + duties
            # This allows semantic search by job title to match category names
            search_text = f"{chunk.get('category_name', '')} — {chunk.get('block_name', '')}\n{chunk.get('content', '')}"

            metadata = {
                "company_name": "duty_templates",  # Fixed key for duty retriever
                "category_code": chunk.get("category_code", ""),
                "category_name": chunk.get("category_name", ""),
                "block_name": chunk.get("block_name", ""),
                "seniority": chunk.get("seniority", ""),
                "language": chunk.get("language", "de"),
                "dimension": "duties",
                "source_file": chunk.get("source_file", ""),
            }

            documents.append(Document(
                page_content=search_text,
                metadata=metadata,
            ))

        if not documents:
            return False

        # Embed all documents into a single FAISS index
        from langchain_community.vectorstores import FAISS as FAISSStore

        vs.store = FAISSStore.from_documents(documents, vs.embeddings)
        faiss_path = Path(store_dir) / "faiss_index"
        faiss_path.mkdir(parents=True, exist_ok=True)
        vs.store.save_local(str(faiss_path))

        logger.info(
            f"[Startup] Embedded {len(documents)} chunks "
            f"({len(style_chunks)} style + {len(duty_chunks)} duty) → {faiss_path}"
        )
        return True

    except Exception as e:
        logger.error(f"[Startup] _embed_from_jsonl failed: {e}", exc_info=True)
        return False


def _embed_duty_chunks_into_existing(duty_jsonl: Path, store_dir: str) -> bool:
    """
    Add duty chunks to an existing FAISS index (used when style index was built
    from PDFs but duty JSONL also exists).
    """
    try:
        from langchain_core.documents import Document
        from services.vector_store import VectorStoreManager
        from langchain_community.vectorstores import FAISS as FAISSStore

        duty_chunks = []
        with open(duty_jsonl, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    duty_chunks.append(json.loads(line))

        if not duty_chunks:
            return False

        vs = VectorStoreManager(store_type="faiss", persist_directory=store_dir)
        if not vs.embeddings or not vs.store:
            return False

        documents = []
        for chunk in duty_chunks:
            search_text = f"{chunk.get('category_name', '')} — {chunk.get('block_name', '')}\n{chunk.get('content', '')}"
            metadata = {
                "company_name": "duty_templates",
                "category_code": chunk.get("category_code", ""),
                "category_name": chunk.get("category_name", ""),
                "block_name": chunk.get("block_name", ""),
                "seniority": chunk.get("seniority", ""),
                "language": chunk.get("language", "de"),
                "dimension": "duties",
                "source_file": chunk.get("source_file", ""),
            }
            documents.append(Document(page_content=search_text, metadata=metadata))

        # Add to existing index
        duty_index = FAISSStore.from_documents(documents, vs.embeddings)
        vs.store.merge_from(duty_index)

        faiss_path = Path(store_dir) / "faiss_index"
        vs.store.save_local(str(faiss_path))
        logger.info(f"[Startup] Added {len(documents)} duty chunks to existing index")
        return True

    except Exception as e:
        logger.error(f"[Startup] _embed_duty_chunks failed: {e}", exc_info=True)
        return False


def _extract_and_embed(pdf_dir: Path, style_jsonl: Path, store_dir: str) -> bool:
    """
    Full pipeline: extract PDFs → JSONL → embed into FAISS.
    Requires pdfminer.six to be installed.
    """
    try:
        from services.pdf_ingestion import extract_all_chunks, chunks_to_jsonl

        # Extract
        chunks = extract_all_chunks(str(pdf_dir))
        if not chunks:
            logger.warning("[Startup] No chunks extracted from PDFs")
            return False

        # Write JSONL for future fast rebuilds
        chunks_to_jsonl(chunks, str(style_jsonl))
        logger.info(f"[Startup] Wrote {len(chunks)} chunks → {style_jsonl}")

        # Now embed from the JSONL we just wrote (duty_jsonl=None because
        # we only extracted style chunks here — duty JSONL is separate)
        duty_jsonl = Path(DUTY_CHUNKS_PATH)
        return _embed_from_jsonl(
            style_jsonl,
            duty_jsonl if duty_jsonl.exists() else None,
            store_dir,
        )

    except ImportError as e:
        logger.warning(f"[Startup] pdfminer.six not available for PDF extraction: {e}")
        return False
    except Exception as e:
        logger.error(f"[Startup] _extract_and_embed failed: {e}", exc_info=True)
        return False
