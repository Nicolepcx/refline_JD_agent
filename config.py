from textwrap import dedent
from dotenv import load_dotenv
import os

load_dotenv()

# Environment configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Expose keys in os.environ for downstream libraries (LiteLLM / OpenAI-compatible clients).
if OPENROUTER_API_KEY:
    os.environ["OPENROUTER_API_KEY"] = OPENROUTER_API_KEY

# If the user only configured OpenRouter, provide an OpenAI-compatible fallback env
# for libraries that only look at OPENAI_* (without affecting explicit OpenRouter usage).
if OPENROUTER_API_KEY and not OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENROUTER_API_KEY
    os.environ["OPENAI_BASE_URL"] = OPENROUTER_BASE_URL
elif OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# Langfuse Configuration for Agent Tracing (Standard - enabled when keys are present)
LANGFUSE_BASE_URL = os.getenv('LANGFUSE_BASE_URL', 'https://cloud.langfuse.com')
LANGFUSE_SECRET_KEY = os.getenv('LANGFUSE_SECRET_KEY')
LANGFUSE_PUBLIC_KEY = os.getenv('LANGFUSE_PUBLIC_KEY')
LANGFUSE_ENABLED = bool(LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY)

# Set Langfuse environment variables for CallbackHandler (reads from os.environ automatically)
# CallbackHandler() reads LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST from environment
if LANGFUSE_SECRET_KEY:
    os.environ['LANGFUSE_SECRET_KEY'] = LANGFUSE_SECRET_KEY
if LANGFUSE_PUBLIC_KEY:
    os.environ['LANGFUSE_PUBLIC_KEY'] = LANGFUSE_PUBLIC_KEY
if LANGFUSE_BASE_URL and LANGFUSE_BASE_URL != 'https://cloud.langfuse.com':
    os.environ['LANGFUSE_HOST'] = LANGFUSE_BASE_URL

# Note: Langfuse status will be logged in app.py after logging is initialized
# to avoid circular import issues

# Logging Configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE')  # Set to filename to enable file logging
LOG_DIR = os.getenv('LOG_DIR', './logs')

# RULER / Concurrency Defaults
# 0 disables pruning by default; set >0 to enable top-K pruning.
RULER_TOP_K_DEFAULT = int(os.getenv("RULER_TOP_K_DEFAULT", "0"))

# LLM Model Configuration
# All model names used throughout the application are centralized here.
# Models are specified as OpenRouter model identifiers WITHOUT the "openrouter/" prefix
# when using ChatOpenAI with base_url=OPENROUTER_BASE_URL (OpenRouter accepts both formats).
# For RULER scoring (which uses model strings directly), we use the full format with prefix.
#
# OpenRouter Provider Routing & Latency Optimization:
# - All models use provider routing optimized for latency (sort: "latency")
# - For Qwen 3 models: additionally disable thinking tokens to reduce latency further
# - Performance thresholds (p90 percentile) can be set via environment variables:
#   - OPENROUTER_PREFERRED_MAX_LATENCY_P90: max latency in seconds (default: 3.0)
#   - OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90: min throughput in tokens/sec (default: 50.0)
# These thresholds prefer providers meeting the requirements but don't exclude others.

# Base/Writer Model: Used for generating job description candidates
# Format: "qwen/qwen3-32b" (no openrouter/ prefix needed when using ChatOpenAI with base_url)
MODEL_BASE = os.getenv("MODEL_BASE", "qwen/qwen3-32b")

# Style Model: Used for refining job descriptions based on feedback
# Format: "google/gemma-2-9b-it" (no openrouter/ prefix needed when using ChatOpenAI with base_url)
MODEL_STYLE = os.getenv("MODEL_STYLE", "google/gemma-2-9b-it")

# RULER Judge Model: Used for scoring/ranking job description candidates (fast model for evaluation)
# Format: "openrouter/openai/o3-mini" (full format with prefix for RULER which uses model strings directly)
MODEL_RULER_JUDGE = os.getenv("MODEL_RULER_JUDGE", "openrouter/openai/o3-mini")

# RULER Judge Fallback Models: Comma-separated list of fallback models for RULER scoring.
# These are passed to OpenRouter's native "models" fallback array so failover happens
# at the API level (automatic retry on provider downtime, rate-limits, content moderation).
# Format: LiteLLM routing format with "openrouter/" prefix (prefix is stripped automatically
# before sending to OpenRouter's body).
# See: https://openrouter.ai/docs/features/model-fallbacks
_ruler_fallbacks_raw = os.getenv(
    "MODEL_RULER_JUDGE_FALLBACKS",
    "openrouter/google/gemini-2.5-flash,openrouter/openai/gpt-4o-mini",
)
MODEL_RULER_JUDGE_FALLBACKS: list[str] = [
    m.strip() for m in _ruler_fallbacks_raw.split(",") if m.strip()
]

# Embedding Model: Used for vector store (style chunks, company content)
# Format: "openai/text-embedding-3-small" (routed via OpenRouter)
MODEL_EMBEDDING = os.getenv("MODEL_EMBEDDING", "openai/text-embedding-3-small")

# OpenRouter Provider Routing Configuration
# Optimize for latency by prioritizing providers with lowest latency
# Set preferred_max_latency thresholds (in seconds) to prefer providers meeting these requirements
# Using p90 percentile ensures 90% of requests meet the latency threshold
OPENROUTER_PREFERRED_MAX_LATENCY_P90 = float(os.getenv("OPENROUTER_PREFERRED_MAX_LATENCY_P90", "3.0"))  # 3 seconds at p90
OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90 = float(os.getenv("OPENROUTER_PREFERRED_MIN_THROUGHPUT_P90", "50.0"))  # 50 tokens/sec at p90

# Vector Store / Style Index Configuration
# Path to the FAISS vector store directory (persisted across restarts).
# On DigitalOcean App Platform, set to a persistent-volume mount, e.g. "/app/vector_store".
VECTOR_STORE_DIR = os.getenv("VECTOR_STORE_DIR", "vector_store")

# Pre-extracted style chunks (committed to the repo).
# Used to rebuild the FAISS index automatically when the index is missing.
STYLE_CHUNKS_PATH = os.getenv("STYLE_CHUNKS_PATH", "style_chunks.jsonl")

# Pre-extracted duty chunks from Aufgaben Jobcategories.docx (committed to the repo).
# Each chunk contains duties for a job category + seniority level.
DUTY_CHUNKS_PATH = os.getenv("DUTY_CHUNKS_PATH", "duty_chunks.jsonl")

# Path to source PDFs (fallback if JSONL doesn't exist).
PDF_DIR = os.getenv("PDF_DIR", "PDFs_selling_psychology")

# Database Configuration
# For local development: Leave unset to use SQLite
# For production (DigitalOcean): Set POSTGRES_CONNECTION_STRING to use PostgreSQL
POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING")
USE_PERSISTENT_STORE = bool(POSTGRES_CONNECTION_STRING)  # Auto-detect: use PostgreSQL if connection string is provided

# Streamlit Password Protection (MVP testing safeguard)
STREAMLIT_USERNAME = os.getenv("STREAMLIT_USERNAME")  # Set in .env to enable username requirement
STREAMLIT_PASSWORD = os.getenv("STREAMLIT_PASSWORD")  # Set in .env to enable password protection

# Default job advertisement values (all empty initially)
DEFAULT_JOB_DATA = {
    "job_headline": "",
    "job_intro": "",
    "caption": "",
    "description": "",
    "requirements": "",
    "duties": "",
    "benefits": "",
    "footer": "",
}

