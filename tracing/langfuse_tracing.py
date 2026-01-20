"""
Langfuse tracing integration for LangGraph agent workflows.
Standard feature - automatically enabled when API keys are configured in .env.
Provides observability and tracing for the blackboard architecture.
"""
from typing import Optional, List, Any
from config import LANGFUSE_ENABLED, LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL
from logging_config import get_logger

logger = get_logger(__name__)

# Initialize Langfuse callbacks at module level (standard when keys are present)
_langfuse_handler: Optional[Any] = None


def _initialize_langfuse() -> Optional[Any]:
    """
    Initialize Langfuse callback handler.
    Standard feature - automatically enabled when API keys are present.
    CallbackHandler reads LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY from environment automatically.
    Returns the CallbackHandler directly (not wrapped in CallbackManager).
    """
    if not LANGFUSE_ENABLED:
        return None
    
    try:
        from langfuse.langchain import CallbackHandler
        
        # CallbackHandler() automatically reads LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, 
        # and LANGFUSE_HOST from os.environ (already set in config.py)
        # No parameters needed - matches the working pattern from user's code
        handler = CallbackHandler()
        
        logger.info("Langfuse tracing initialized and enabled")
        return handler
    except ImportError:
        logger.error(
            "Langfuse package not installed. Install with: pip install langfuse. "
            "Tracing will be disabled until package is installed."
        )
        return None
    except Exception as e:
        logger.error(
            f"Failed to initialize Langfuse tracing: {e}. "
            "Please check your LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY configuration."
        )
        return None


def get_langfuse_callbacks() -> Optional[List[Any]]:
    """
    Get Langfuse callback handler as a list (for LangGraph/LangChain config).
    Standard feature - automatically enabled when API keys are configured.
    Returns None only if keys are missing or initialization failed.
    """
    global _langfuse_handler
    
    if not LANGFUSE_ENABLED:
        return None
    
    # Initialize on first call (lazy initialization)
    if _langfuse_handler is None:
        _langfuse_handler = _initialize_langfuse()
    
    if _langfuse_handler is None:
        return None
    
    # Return as a list for LangGraph/LangChain config
    return [_langfuse_handler]


def add_langfuse_to_config(config: dict) -> dict:
    """
    Add Langfuse callbacks to a run configuration dictionary.
    Standard feature - automatically adds tracing when API keys are configured.
    
    Args:
        config: RunnableConfig dictionary
        
    Returns:
        Updated config with Langfuse callbacks (standard when keys are present)
    """
    if not LANGFUSE_ENABLED:
        return config
    
    callbacks = get_langfuse_callbacks()
    if callbacks:
        if "callbacks" not in config:
            config["callbacks"] = []
        if isinstance(config["callbacks"], list):
            # Extend the list with our callbacks
            config["callbacks"].extend(callbacks)
        else:
            # Convert single callback to list and add ours
            config["callbacks"] = [config["callbacks"]] + callbacks
    else:
        # Keys are configured but initialization failed - log warning
        logger.warning(
            "Langfuse keys are configured but callbacks could not be initialized. "
            "Tracing will not be available for this run."
        )
    
    return config
