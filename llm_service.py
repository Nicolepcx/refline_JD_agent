from functools import lru_cache
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    MODEL_BASE,
    MODEL_STYLE,
    OPENROUTER_PREFERRED_MAX_LATENCY_P90,
    OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90,
)


def _get_openrouter_provider_config() -> dict:
    """
    Returns OpenRouter provider routing configuration optimized for latency.
    
    Uses sort: "latency" to prioritize providers with lowest latency.
    Sets preferred_max_latency and preferred_min_throughput thresholds at p90 percentile
    to prefer providers that meet these performance requirements.
    """
    provider_config = {
        "sort": "latency",  # Prioritize lowest latency providers
    }
    
    # Add latency threshold if configured (p90 = 90% of requests meet this threshold)
    if OPENROUTER_PREFERRED_MAX_LATENCY_P90 > 0:
        provider_config["preferred_max_latency"] = {
            "p90": OPENROUTER_PREFERRED_MAX_LATENCY_P90
        }
    
    # Add throughput threshold if configured (p90 = 90% of requests meet this threshold)
    if OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90 > 0:
        provider_config["preferred_min_throughput"] = {
            "p90": OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90
        }
    
    return provider_config


def _get_qwen_extra_body() -> dict:
    """
    Returns extra_body parameters for Qwen 3 models:
    1. Disables thinking tokens to reduce latency and token usage
    2. Optimizes provider routing for lowest latency
    """
    extra_body = {
        "chat_template_kwargs": {"enable_thinking": False},
        "provider": _get_openrouter_provider_config(),
    }
    return extra_body


def _get_extra_body_for_model(model_name: str) -> dict | None:
    """
    Returns extra_body configuration for a given model.
    For Qwen models: disables thinking + optimizes for latency
    For other models: optimizes for latency only
    """
    provider_config = _get_openrouter_provider_config()
    
    if "qwen" in model_name.lower():
        # Qwen models: disable thinking + latency optimization
        return {
            "chat_template_kwargs": {"enable_thinking": False},
            "provider": provider_config,
        }
    else:
        # Other models: latency optimization only
        return {
            "provider": provider_config,
        }


@lru_cache(maxsize=1)
def get_base_llm() -> ChatOpenAI:
    """
    Initialize and cache the base LLM instance (writer).
    
    Uses OpenRouter API via ChatOpenAI with base_url set to OPENROUTER_BASE_URL.
    Model names should NOT include the "openrouter/" prefix when using this approach.
    
    Optimizes for latency by:
    1. For Qwen 3 models: disables thinking tokens + latency-optimized provider routing
    2. For other models: latency-optimized provider routing only
    
    Provider routing uses sort: "latency" to prioritize lowest latency providers,
    with optional preferred_max_latency and preferred_min_throughput thresholds.
    """
    extra_body = _get_extra_body_for_model(MODEL_BASE)
    
    return ChatOpenAI(
        model=MODEL_BASE,
        temperature=0,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        extra_body=extra_body,
    )


# Note: get_judge_llm() is not used for RULER scoring.
# RULER scoring uses model strings directly via ruler_score_group() from the art library.
# This function is kept for potential future use, but currently RULER scoring happens in:
# - graph/job_graph.py: node_ruler_scorer() and node_ruler_curator()
# - ruler/ruler_utils.py: score_group_with_fallback()
# All of which use MODEL_RULER_JUDGE from config.py as a string, not a LangChain instance.


@lru_cache(maxsize=1)
def get_style_llm() -> ChatOpenAI:
    """
    Initialize and cache the style LLM instance (for refinement).
    
    Uses OpenRouter API via ChatOpenAI with base_url set to OPENROUTER_BASE_URL.
    Model names should NOT include the "openrouter/" prefix when using this approach.
    
    Optimizes for latency using provider routing with sort: "latency" to prioritize
    lowest latency providers, with optional performance thresholds.
    """
    extra_body = _get_extra_body_for_model(MODEL_STYLE)
    
    return ChatOpenAI(
        model=MODEL_STYLE,
        temperature=0,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        extra_body=extra_body,
    )


def call_llm(instruction: str, current_value: str, context: dict) -> str:
    """
    Call the base model on OpenRouter (OpenAI-compatible endpoint) via ChatOpenAI.
    
    Args:
        instruction: What to do with the text
        current_value: Current text value (may be empty)
        context: Other fields of the job ad for context
        
    Returns:
        Generated or improved text
    """
    llm = get_base_llm()

    prompt = (
        "You are a recruitment copywriter. Improve or generate the requested section "
        "of a job advertisement.\n\n"
        f"Instruction:\n{instruction}\n\n"
        f"Current text (may be empty):\n{current_value}\n\n"
        "Other fields of the job ad (for context):\n"
        f"{context}\n\n"
        "Return only the rewritten text, without explanations."
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()

