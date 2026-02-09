"""
Startup module — ensures the style vector index is ready before serving.

On first launch (or when the FAISS index is missing), this module
automatically rebuilds the index from:
  1. ``style_chunks.jsonl`` (pre-extracted, committed to the repo — fast, no PDFs needed)
  2. Fallback: re-extract from source PDFs if JSONL is absent

After the index is built, it is persisted to ``VECTOR_STORE_DIR`` (which should
be a DigitalOcean persistent volume in production so it survives restarts).

Usage:
    from services.startup import ensure_style_index, get_style_vector_store

    # Call once at app startup (idempotent)
    ensure_style_index()

    # Get the cached VectorStoreManager singleton
    vs = get_style_vector_store()
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from logging_config import get_logger

logger = get_logger(__name__)

# Module-level singleton
_style_vector_store: Optional[object] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_style_index() -> bool:
    """
    Ensure the FAISS style-chunk index exists and is ready.

    Checks ``VECTOR_STORE_DIR/faiss_index/``.  If the index is missing,
    rebuilds it from ``STYLE_CHUNKS_PATH`` (JSONL) or, as a fallback,
    re-extracts from the source PDFs.

    Returns True if the index is available, False on failure.
    """
    from config import VECTOR_STORE_DIR, STYLE_CHUNKS_PATH, PDF_DIR

    faiss_index_dir = Path(VECTOR_STORE_DIR) / "faiss_index"
    index_file = faiss_index_dir / "index.faiss"

    if index_file.exists():
        logger.info(f"[Startup] Style index found at {faiss_index_dir}")
        return True

    logger.info("[Startup] Style index not found — building now …")

    # --- Strategy 1: Build from pre-extracted JSONL (fast, no PDF deps) ---
    jsonl_path = Path(STYLE_CHUNKS_PATH)
    if jsonl_path.exists():
        logger.info(f"[Startup] Loading chunks from {jsonl_path}")
        ok = _embed_from_jsonl(jsonl_path, VECTOR_STORE_DIR)
        if ok:
            logger.info("[Startup] ✓ Style index built from JSONL")
            return True
        else:
            logger.warning("[Startup] JSONL embedding failed — trying PDF extraction")

    # --- Strategy 2: Extract from PDFs then embed (needs pdfminer.six) ---
    pdf_dir = Path(PDF_DIR)
    if pdf_dir.is_dir() and any(pdf_dir.glob("*.pdf")):
        logger.info(f"[Startup] Extracting from PDFs in {pdf_dir}")
        ok = _extract_and_embed(pdf_dir, jsonl_path, VECTOR_STORE_DIR)
        if ok:
            logger.info("[Startup] ✓ Style index built from PDFs")
            return True
        else:
            logger.error("[Startup] PDF extraction + embedding failed")

    # --- Neither source available: style routing will use hardcoded defaults ---
    logger.warning(
        "[Startup] No style index built (JSONL and PDFs both unavailable). "
        "Style routing will fall back to hardcoded defaults."
    )
    return False


def get_style_vector_store():
    """
    Return a cached VectorStoreManager pointing at the style index.

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _embed_from_jsonl(jsonl_path: Path, store_dir: str) -> bool:
    """
    Read StyleChunk data from JSONL and embed into a FAISS index.
    Does not require pdfminer — only needs the OpenRouter embedding API.
    """
    try:
        from langchain_core.documents import Document
        from services.vector_store import VectorStoreManager

        # Read JSONL
        chunks = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunks.append(json.loads(line))

        if not chunks:
            logger.warning("[Startup] JSONL is empty")
            return False

        # Create VectorStoreManager
        vs = VectorStoreManager(
            store_type="faiss",
            persist_directory=store_dir,
        )
        if not vs.embeddings:
            logger.error("[Startup] Embeddings not available (check OPENROUTER_API_KEY)")
            return False

        # Build Documents
        documents = []
        for chunk in chunks:
            # Determine company_name key (mirrors pdf_ingestion logic)
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

        if not documents:
            return False

        # Embed
        from langchain_community.vectorstores import FAISS as FAISSStore

        vs.store = FAISSStore.from_documents(documents, vs.embeddings)
        faiss_path = Path(store_dir) / "faiss_index"
        faiss_path.mkdir(parents=True, exist_ok=True)
        vs.store.save_local(str(faiss_path))

        logger.info(f"[Startup] Embedded {len(documents)} chunks → {faiss_path}")
        return True

    except Exception as e:
        logger.error(f"[Startup] _embed_from_jsonl failed: {e}", exc_info=True)
        return False


def _extract_and_embed(pdf_dir: Path, jsonl_path: Path, store_dir: str) -> bool:
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
        chunks_to_jsonl(chunks, str(jsonl_path))
        logger.info(f"[Startup] Wrote {len(chunks)} chunks → {jsonl_path}")

        # Now embed from the JSONL we just wrote
        return _embed_from_jsonl(jsonl_path, store_dir)

    except ImportError as e:
        logger.warning(f"[Startup] pdfminer.six not available for PDF extraction: {e}")
        return False
    except Exception as e:
        logger.error(f"[Startup] _extract_and_embed failed: {e}", exc_info=True)
        return False
