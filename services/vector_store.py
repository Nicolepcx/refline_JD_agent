"""
Vector database service for storing and retrieving scraped company content.
Supports FAISS (local) and Chroma (local or remote).
Modular service - blackboard architecture works without it.

Embeddings are routed through OpenRouter by default (reads OPENROUTER_API_KEY
from config).  Any OpenAI-compatible embedding model available on OpenRouter
can be used — the model name is set via MODEL_EMBEDDING in config.py.
"""
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import json
from logging_config import get_logger

logger = get_logger(__name__)

# Try to import vector store libraries
FAISS_AVAILABLE = False
CHROMA_AVAILABLE = False

try:
    import faiss
    from langchain_community.vectorstores import FAISS
    from langchain_openai import OpenAIEmbeddings
    FAISS_AVAILABLE = True
except ImportError:
    pass

try:
    import chromadb
    from langchain_community.vectorstores import Chroma
    from langchain_openai import OpenAIEmbeddings
    CHROMA_AVAILABLE = True
except ImportError:
    pass


def _build_embeddings(
    embedding_model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> "OpenAIEmbeddings | None":
    """
    Create an OpenAIEmbeddings instance routed through OpenRouter.

    Resolution order for each parameter:
      1. Explicit argument
      2. config.py values (if importable)
      3. Environment variables
      4. Sensible defaults
    """
    # --- resolve api_key ---
    if not api_key:
        try:
            from config import OPENROUTER_API_KEY
            api_key = OPENROUTER_API_KEY
        except ImportError:
            api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")

    # --- resolve base_url ---
    if not base_url:
        try:
            from config import OPENROUTER_BASE_URL
            base_url = OPENROUTER_BASE_URL
        except ImportError:
            base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    # --- resolve model ---
    if not embedding_model:
        try:
            from config import MODEL_EMBEDDING
            embedding_model = MODEL_EMBEDDING
        except ImportError:
            embedding_model = os.getenv("MODEL_EMBEDDING", "openai/text-embedding-3-small")

    if not api_key:
        logger.warning("No API key found for embeddings (checked OPENROUTER_API_KEY, OPENAI_API_KEY)")
        return None

    try:
        from langchain_openai import OpenAIEmbeddings as _OAIEmb
        return _OAIEmb(
            model=embedding_model,
            openai_api_key=api_key,
            openai_api_base=base_url,
        )
    except Exception as e:
        logger.warning(f"Could not initialize embeddings: {e}", exc_info=True)
        return None


class VectorStoreManager:
    """
    Manages vector storage for scraped company content.
    Uses FAISS by default (local, no server needed), falls back to Chroma if FAISS unavailable.
    Embeddings are routed through OpenRouter.
    """
    
    def __init__(
        self,
        store_type: str = "faiss",  # "faiss" or "chroma"
        persist_directory: str = "vector_store",
        embedding_model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """
        Initialize vector store manager.
        
        Args:
            store_type: "faiss" or "chroma"
            persist_directory: Directory to persist vector store
            embedding_model: Embedding model name (default from config / env)
            api_key: API key (default from config / env)
            base_url: API base URL (default from config / env)
        """
        self.store_type = store_type
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        
        # Initialize embeddings (routed through OpenRouter)
        self.embeddings = _build_embeddings(embedding_model, api_key, base_url)
        
        self.store = None
        self._initialize_store()
    
    def _initialize_store(self):
        """Initialize the vector store based on available libraries."""
        if not self.embeddings:
            logger.warning("Embeddings not available, vector store disabled")
            return
        
        if self.store_type == "faiss" and FAISS_AVAILABLE:
            try:
                faiss_path = self.persist_directory / "faiss_index"
                if faiss_path.exists():
                    # Load existing FAISS index
                    self.store = FAISS.load_local(
                        str(faiss_path),
                        self.embeddings,
                        allow_dangerous_deserialization=True
                    )
                else:
                    # Create new empty FAISS store
                    # We'll add documents when needed
                    self.store = None
            except Exception as e:
                logger.error(f"Error loading FAISS store: {e}", exc_info=True)
                self.store = None
        
        elif self.store_type == "chroma" and CHROMA_AVAILABLE:
            try:
                chroma_path = self.persist_directory / "chroma"
                self.store = Chroma(
                    persist_directory=str(chroma_path),
                    embedding_function=self.embeddings
                )
            except Exception as e:
                logger.error(f"Error initializing Chroma store: {e}", exc_info=True)
                self.store = None
        else:
            logger.warning(f"{self.store_type} not available. Install faiss-cpu or chromadb.")
            self.store = None
    
    def is_available(self) -> bool:
        """Check if vector store is available and initialized."""
        return self.store is not None and self.embeddings is not None
    
    def add_company_content(
        self,
        company_name: str,
        urls: List[str],
        content_dict: Dict[str, str],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add scraped content for a company to the vector store.
        
        Args:
            company_name: Name of the company
            urls: List of URLs that were scraped
            content_dict: Dictionary mapping URL to scraped text
            metadata: Optional metadata (e.g., scrape_date, interval)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            return False
        
        try:
            from langchain_core.documents import Document
            
            # Create documents from scraped content
            documents = []
            metadatas = []
            
            for url, text in content_dict.items():
                if not text or len(text.strip()) < 50:  # Skip very short content
                    continue
                
                # Create metadata
                doc_metadata = {
                    "company_name": company_name,
                    "url": url,
                    "scrape_date": datetime.now(timezone.utc).isoformat(),
                    **(metadata or {})
                }
                
                # Create document
                doc = Document(
                    page_content=text,
                    metadata=doc_metadata
                )
                documents.append(doc)
                metadatas.append(doc_metadata)
            
            if not documents:
                return False
            
            # Add to vector store
            if self.store_type == "faiss" and FAISS_AVAILABLE:
                if self.store is None:
                    # Create new FAISS store with first batch
                    self.store = FAISS.from_documents(documents, self.embeddings)
                else:
                    # Add to existing store
                    self.store.add_documents(documents)
                
                # Save FAISS index
                faiss_path = self.persist_directory / "faiss_index"
                self.store.save_local(str(faiss_path))
            
            elif self.store_type == "chroma" and CHROMA_AVAILABLE:
                # Chroma automatically persists
                self.store.add_documents(documents, metadatas=metadatas)
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding company content to vector store: {e}", exc_info=True)
            return False
    
    def search_company_content(
        self,
        company_name: str,
        query: str,
        k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for company content using semantic search.
        
        Args:
            company_name: Name of the company to search for
            query: Search query
            k: Number of results to return
            
        Returns:
            List of search results with content and metadata
        """
        if not self.is_available():
            return []
        
        try:
            # Search with metadata filter if supported
            if self.store_type == "faiss" and FAISS_AVAILABLE:
                # FAISS doesn't support metadata filtering natively
                # We'll search all and filter results
                results = self.store.similarity_search_with_score(query, k=k * 3)
                
                # Filter by company name and return top k
                filtered = [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": score
                    }
                    for doc, score in results
                    if doc.metadata.get("company_name") == company_name
                ][:k]
                
                return filtered
            
            elif self.store_type == "chroma" and CHROMA_AVAILABLE:
                # Chroma supports metadata filtering
                results = self.store.similarity_search_with_score(
                    query,
                    k=k,
                    filter={"company_name": company_name}
                )
                
                return [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": score
                    }
                    for doc, score in results
                ]
            
            return []
            
        except Exception as e:
            logger.error(f"Error searching company content: {e}", exc_info=True)
            return []
    
    def get_company_content(
        self,
        company_name: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get all content for a company (without search query).
        
        Args:
            company_name: Name of the company
            limit: Maximum number of results
            
        Returns:
            List of content documents
        """
        # Use a generic query to retrieve company content
        return self.search_company_content(company_name, company_name, k=limit)


def get_vector_store_manager(
    store_type: Optional[str] = None,
    persist_directory: Optional[str] = None,
) -> VectorStoreManager:
    """
    Factory function to get vector store manager.
    Auto-selects best available store type.
    
    Args:
        store_type: "faiss" or "chroma" (auto-selects if None)
        persist_directory: Directory for persistence.
            Defaults to ``VECTOR_STORE_DIR`` from config (or ``"vector_store"``).
        
    Returns:
        VectorStoreManager instance
    """
    if persist_directory is None:
        try:
            from config import VECTOR_STORE_DIR
            persist_directory = VECTOR_STORE_DIR
        except ImportError:
            persist_directory = os.getenv("VECTOR_STORE_DIR", "vector_store")

    if store_type is None:
        # Auto-select: prefer FAISS (simpler, no server)
        if FAISS_AVAILABLE:
            store_type = "faiss"
        elif CHROMA_AVAILABLE:
            store_type = "chroma"
        else:
            store_type = "faiss"  # Will show warning if not available
    
    return VectorStoreManager(
        store_type=store_type,
        persist_directory=persist_directory
    )
