# Latency Optimization Guide

This document describes the latency optimizations implemented in the JD Writer Multi-Agent System and how they can be adjusted for different API providers.

## Overview

The application implements several strategies to minimize latency:

1. **OpenRouter Provider Routing** - Routes requests to the fastest available providers
2. **Thinking Token Disabling** - Prevents reasoning tokens for Qwen 3 models
3. **Parallel Execution** - Concurrent candidate generation and refinement
4. **Performance Thresholds** - Prefers providers meeting latency/throughput requirements

## OpenRouter Provider Routing

### How It Works

OpenRouter automatically routes requests to the best available providers. We optimize this by:

- **Sorting by Latency**: Using `sort: "latency"` to prioritize providers with the lowest latency
- **Performance Thresholds**: Setting preferred maximum latency and minimum throughput at p90 percentile
- **Fallback Support**: Providers that don't meet thresholds are still available as fallbacks

### Configuration

The latency optimization is configured in `config.py`:

```python
# OpenRouter Provider Routing Configuration
OPENROUTER_PREFERRED_MAX_LATENCY_P90 = 3.0  # seconds (90% of requests meet this)
OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90 = 50.0  # tokens/sec (90% of requests meet this)
```

These can be overridden via environment variables:
- `OPENROUTER_PREFERRED_MAX_LATENCY_P90`
- `OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90`

### Implementation

The provider routing configuration is automatically applied to all LLM calls via `llm_service.py`:

```python
provider_config = {
    "sort": "latency",  # Prioritize lowest latency
    "preferred_max_latency": {"p90": 3.0},  # Prefer <3s latency for 90% of requests
    "preferred_min_throughput": {"p90": 50.0},  # Prefer >50 tokens/sec for 90% of requests
}
```

This is included in the `extra_body` parameter passed to ChatOpenAI instances.

## Thinking Token Disabling (Qwen Models)

### Why Disable Thinking Tokens?

Qwen 3 models support "thinking" mode, which generates reasoning tokens before the actual response. While useful for complex reasoning tasks, these tokens:

- **Increase Latency**: Additional tokens must be generated before the response
- **Increase Costs**: More tokens = higher API costs
- **Not Needed**: For job description generation, we don't need explicit reasoning chains

### Implementation

For Qwen models, we disable thinking tokens via:

```python
extra_body = {
    "chat_template_kwargs": {"enable_thinking": False}
}
```

This is automatically applied to all Qwen model calls (detected by checking if "qwen" is in the model name).

## Parallel Execution

The application uses parallel execution to reduce overall latency:

1. **Candidate Generation**: Multiple candidates are generated concurrently using `asyncio.gather()`
2. **Style Refinement**: Multiple refinements happen in parallel
3. **RULER Scoring**: Uses async scoring with parallel model calls

See `generators/job_generator.py` and `graph/job_graph.py` for implementation details.

## Performance Thresholds Explained

### Percentile-Based Thresholds

OpenRouter tracks latency and throughput metrics using percentile statistics over a rolling 5-minute window:

- **p50 (median)**: 50% of requests perform better than this value
- **p75**: 75% of requests perform better than this value
- **p90**: 90% of requests perform better than this value
- **p99**: 99% of requests perform better than this value

### Why p90?

We use p90 (90th percentile) because it:
- Provides confidence about worst-case performance
- Balances typical performance with reliability
- Ensures 90% of requests meet the threshold

### Threshold Behavior

**Important**: These thresholds are preferences, not hard limits. Providers that don't meet thresholds are:
- Deprioritized (moved to end of routing list)
- Still available as fallbacks if preferred providers fail
- Never completely excluded (unless explicitly configured)

## Adjusting for Different API Providers

### OpenRouter (Current Implementation)

The current implementation is optimized for OpenRouter. If you switch to a different provider, you may need to adjust:

#### 1. Remove Provider Routing Configuration

If your provider doesn't support provider routing (e.g., direct OpenAI, Anthropic, etc.), remove the `provider` configuration from `extra_body`:

```python
# For non-OpenRouter providers, remove provider config
def _get_extra_body_for_model(model_name: str) -> dict | None:
    if "qwen" in model_name.lower():
        return {
            "chat_template_kwargs": {"enable_thinking": False}
            # No provider config for direct API providers
        }
    return None
```

#### 2. Provider-Specific Parameters

Different providers may have different parameter names or structures:

- **OpenAI Direct**: No `extra_body` needed for provider routing
- **Anthropic**: Uses different parameter structure
- **Google Vertex AI**: May require different configuration
- **Azure OpenAI**: May need deployment-specific settings

#### 3. Thinking Token Configuration

Not all models support thinking tokens. Only disable if:
- The model supports thinking/reasoning mode
- The provider API supports the `chat_template_kwargs` parameter
- You want to explicitly disable it

For models that don't support thinking, simply don't include the `chat_template_kwargs` parameter.

### Example: Switching to Direct OpenAI

If switching from OpenRouter to direct OpenAI API:

1. **Update `config.py`**:
   ```python
   # Remove OpenRouter-specific config
   # OPENROUTER_PREFERRED_MAX_LATENCY_P90 = ...
   # OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90 = ...
   
   # Use OpenAI base URL
   OPENAI_BASE_URL = "https://api.openai.com/v1"
   ```

2. **Update `llm_service.py`**:
   ```python
   def _get_extra_body_for_model(model_name: str) -> dict | None:
       # OpenAI doesn't support provider routing or thinking tokens
       # Return None or provider-specific config only
       return None
   ```

3. **Update model names**:
   ```python
   MODEL_BASE = "gpt-4o"  # Direct OpenAI model name
   MODEL_STYLE = "gpt-4o-mini"
   ```

### Example: Switching to Anthropic

If switching to Anthropic:

1. **Update imports**:
   ```python
   from langchain_anthropic import ChatAnthropic
   ```

2. **Remove OpenRouter-specific config**:
   - No provider routing
   - No thinking token disabling (Anthropic uses different reasoning system)

3. **Use Anthropic-specific parameters**:
   ```python
   llm = ChatAnthropic(
       model="claude-sonnet-4-20250514",
       temperature=0,
       # Anthropic-specific parameters
   )
   ```

## Monitoring and Tuning

### Adjusting Latency Thresholds

If you're experiencing:
- **Too slow**: Lower `OPENROUTER_PREFERRED_MAX_LATENCY_P90` (e.g., 2.0 seconds)
- **Too many failures**: Raise `OPENROUTER_PREFERRED_MAX_LATENCY_P90` (e.g., 5.0 seconds)
- **Inconsistent performance**: Use multiple percentile thresholds (p50, p90, p99)

### Adjusting Throughput Thresholds

If you need:
- **Faster responses**: Raise `OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90` (e.g., 100 tokens/sec)
- **More provider options**: Lower `OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90` (e.g., 25 tokens/sec)

### Using Different Sort Strategies

You can change the sorting strategy in `llm_service.py`:

```python
def _get_openrouter_provider_config() -> dict:
    return {
        "sort": "latency",  # Options: "latency", "throughput", "price"
        # ...
    }
```

- **"latency"**: Best for real-time applications (current default)
- **"throughput"**: Best for batch processing
- **"price"**: Best for cost optimization

## Best Practices

1. **Start Conservative**: Begin with default thresholds and adjust based on actual performance
2. **Monitor Metrics**: Track actual latency and throughput to inform threshold adjustments
3. **Test Fallbacks**: Ensure fallback providers work when preferred providers fail
4. **Provider-Specific**: Always check provider documentation for supported parameters
5. **Model-Specific**: Some optimizations (like thinking token disabling) are model-specific

## Troubleshooting

### High Latency Despite Optimization

1. Check if provider routing is working (inspect OpenRouter dashboard)
2. Verify thresholds aren't too strict (may be excluding all providers)
3. Check network latency to API endpoints
4. Consider using `:nitro` suffix for throughput-optimized endpoints

### Thinking Tokens Still Being Generated

1. Verify model name contains "qwen" (case-insensitive check)
2. Check if provider supports `chat_template_kwargs` parameter
3. Verify `extra_body` is being passed correctly to ChatOpenAI

### Provider Routing Not Working

1. Verify you're using OpenRouter (not direct provider API)
2. Check `OPENROUTER_BASE_URL` is set correctly
3. Ensure `extra_body` includes `provider` configuration
4. Check OpenRouter API documentation for latest parameter format

## References

- [OpenRouter Provider Routing Documentation](https://openrouter.ai/docs/provider-routing)
- [OpenRouter Performance Metrics](https://openrouter.ai/docs/performance)
- [Qwen Model Documentation](https://qwenlm.github.io/)

## Notes

- **Provider-Specific**: This optimization is designed for OpenRouter. Other providers may require different approaches.
- **Model-Specific**: Thinking token disabling only applies to models that support it (currently Qwen 3).
- **Configuration**: All latency optimizations can be disabled or adjusted via environment variables.
- **Future Changes**: API providers may change their routing or parameter structures. Monitor provider documentation for updates.
