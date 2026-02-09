#!/usr/bin/env python3
"""
Standalone runner for PDF ingestion — avoids the services/__init__.py import chain.

Usage:
    python run_pdf_ingestion.py                 # extract + JSONL only
    python run_pdf_ingestion.py --embed         # also embed into FAISS
"""
import sys
import os
import types
import importlib.util

# ---------------------------------------------------------------------------
# Bootstrap: stub heavy dependencies so pdf_ingestion.py can load standalone
# ---------------------------------------------------------------------------

# 1. Stub logging_config
import logging

def _get_logger(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s | %(name)s | %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

logging_config_mod = types.ModuleType("logging_config")
logging_config_mod.get_logger = _get_logger
sys.modules["logging_config"] = logging_config_mod

# 2. Stub models.job_models (pdf_ingestion imports StyleProfile / StyleKit at module level
#    but doesn't use them during extraction)
models_mod = types.ModuleType("models")
models_mod.__path__ = [os.path.join(os.path.dirname(__file__), "models")]
sys.modules["models"] = models_mod

job_models_mod = types.ModuleType("models.job_models")
class _StyleProfile: pass
class _StyleKit: pass
job_models_mod.StyleProfile = _StyleProfile
job_models_mod.StyleKit = _StyleKit
sys.modules["models.job_models"] = job_models_mod

# 3. Import pdf_ingestion directly (skip services/__init__.py)
_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "services.pdf_ingestion",
    os.path.join(_here, "services", "pdf_ingestion.py"),
    submodule_search_locations=[],
)
pdf_ingestion = importlib.util.module_from_spec(_spec)
sys.modules["services.pdf_ingestion"] = pdf_ingestion
_spec.loader.exec_module(pdf_ingestion)

# ---------------------------------------------------------------------------
# Embedding helper (imports vector_store directly, not through services pkg)
# ---------------------------------------------------------------------------

def _embed_chunks(chunks, store_dir="vector_store"):
    """Embed StyleChunks into FAISS via OpenRouter embeddings."""
    from dotenv import load_dotenv
    load_dotenv()

    # Resolve OpenRouter credentials (same logic as config.py)
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.getenv("MODEL_EMBEDDING", "openai/text-embedding-3-small")

    if not api_key:
        print("  ✗ No API key found (set OPENROUTER_API_KEY in .env)")
        return False

    print(f"  Using embedding model: {model}")
    print(f"  API base: {base_url}")

    # Import vector_store module directly (avoid services/__init__.py chain)
    vs_spec = importlib.util.spec_from_file_location(
        "vector_store_mod",
        os.path.join(_here, "services", "vector_store.py"),
    )
    vs_mod = importlib.util.module_from_spec(vs_spec)
    vs_spec.loader.exec_module(vs_mod)

    VectorStoreManager = vs_mod.VectorStoreManager

    from langchain_core.documents import Document

    vs = VectorStoreManager(
        store_type="faiss",
        persist_directory=store_dir,
        embedding_model=model,
        api_key=api_key,
        base_url=base_url,
    )

    if not vs.embeddings:
        print("  ✗ Embeddings not available — check API key and model name")
        return False

    documents = []
    for chunk in chunks:
        if chunk.dimension == "syntax" and chunk.profile_color == "any":
            company_name = "style_syntax"
        else:
            company_name = f"style_{chunk.profile_color}"

        metadata = {
            "company_name": company_name,
            "profile_color": chunk.profile_color,
            "dimension": chunk.dimension,
            "language": chunk.language,
            "use_case": chunk.use_case,
            "source_file": chunk.source_file,
        }
        if chunk.mode:
            metadata["mode"] = chunk.mode

        documents.append(Document(
            page_content=chunk.content,
            metadata=metadata,
        ))

    if not documents:
        print("  ✗ No documents to embed.")
        return False

    try:
        from langchain_community.vectorstores import FAISS as FAISSStore

        if vs.store is None:
            vs.store = FAISSStore.from_documents(documents, vs.embeddings)
        else:
            vs.store.add_documents(documents)

        from pathlib import Path
        faiss_path = Path(store_dir) / "faiss_index"
        faiss_path.mkdir(parents=True, exist_ok=True)
        vs.store.save_local(str(faiss_path))
        print(f"  ✓ Embedded {len(documents)} chunks into FAISS at {faiss_path}")
        print(f"    Model: {model} | Dimension: 1536 | Chunks: {len(documents)}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to embed: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
from collections import Counter


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract Motivkompass PDFs into atomic style chunks"
    )
    parser.add_argument("--pdf-dir", default="PDFs_selling_psychology")
    parser.add_argument("--output", default="style_chunks.jsonl")
    parser.add_argument("--embed", action="store_true",
                        help="Also embed into FAISS vector store (requires OPENAI_API_KEY)")
    parser.add_argument("--store-dir", default="vector_store")
    args = parser.parse_args()

    # 1. Extract
    chunks = pdf_ingestion.extract_all_chunks(args.pdf_dir)

    # 2. Write JSONL
    pdf_ingestion.chunks_to_jsonl(chunks, args.output)

    # 3. Summary
    dim_counts = Counter(c.dimension for c in chunks)
    color_counts = Counter(c.profile_color for c in chunks)
    print(f"\n{'='*50}")
    print(f"Extracted {len(chunks)} total chunks")
    print(f"  By dimension: {dict(dim_counts)}")
    print(f"  By color:     {dict(color_counts)}")

    for i, c in enumerate(chunks):
        content_preview = c.content[:200] + "..." if len(c.content) > 200 else c.content
        print(f"\n--- Chunk {i+1} [{c.profile_color}|{c.dimension}] ---")
        print(f"  {content_preview}")
        if c.mode:
            print(f"  mode: {c.mode}")
        print(f"  source: {c.source_file}")

    # 4. Optionally embed
    if args.embed:
        print(f"\nEmbedding into FAISS at {args.store_dir}...")
        _embed_chunks(chunks, store_dir=args.store_dir)


if __name__ == "__main__":
    main()
