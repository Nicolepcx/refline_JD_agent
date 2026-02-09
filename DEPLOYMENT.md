# Deployment Guide for DigitalOcean App Platform

This guide explains how to deploy the JD Writer MAS application to DigitalOcean App Platform with minimal configuration changes.

## Overview

The application automatically detects the environment and uses:
- **Local Development**: SQLite database + InMemoryStore (default)
- **Production (DigitalOcean)**: PostgreSQL database + PostgresStore (when `POSTGRES_CONNECTION_STRING` is set)

## Environment Variables

### Required for Production

Add these environment variables in DigitalOcean App Platform:

1. **API Keys**:
   ```
   OPENROUTER_API_KEY=your_openrouter_api_key
   ```
   Used for LLM generation **and** embeddings (OpenRouter routes to any model).

2. **Vector Store Path** (if using a persistent volume):
   ```
   VECTOR_STORE_DIR=/app/vector_store
   ```
   Points to the persistent volume mount. If unset, defaults to `vector_store/` in the working directory.

3. **PostgreSQL Connection** (if using managed PostgreSQL):
   ```
   POSTGRES_CONNECTION_STRING=postgresql://user:password@host:port/database
   ```
   - DigitalOcean provides this when you create a managed PostgreSQL database
   - The app automatically uses PostgreSQL when this is set

4. **Optional - Embedding Model**:
   ```
   MODEL_EMBEDDING=openai/text-embedding-3-small
   ```
   Defaults to `openai/text-embedding-3-small` via OpenRouter. Change to any embedding model available on OpenRouter.

5. **Optional - Langfuse Tracing**:
   ```
   LANGFUSE_SECRET_KEY=your_secret_key
   LANGFUSE_PUBLIC_KEY=your_public_key
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   ```

6. **Optional - Password Protection** (MVP testing safeguard):
   ```
   STREAMLIT_PASSWORD=your_secure_password
   ```
   - If set, users must enter this password to access the Streamlit app
   - Leave unset to disable password protection

### Local Development (.env file)

For local testing, create a `.env` file with:
```bash
# API Keys (required — used for LLM + embeddings)
OPENROUTER_API_KEY=your_key_here

# Optional: Langfuse tracing
LANGFUSE_SECRET_KEY=your_key
LANGFUSE_PUBLIC_KEY=your_key

# Optional: Password protection
STREAMLIT_PASSWORD=test_password

# Leave POSTGRES_CONNECTION_STRING unset for local SQLite
# Leave VECTOR_STORE_DIR unset to use local ./vector_store/
```

## Database Configuration

### Local Development (Default)

- **Checkpointer**: SQLite (`jd_threads.sqlite`)
- **Store**: InMemoryStore (in-memory, lost on restart)
- **ORM Database**: SQLite (`jd_database.sqlite`)

No configuration needed - works out of the box.

### Production (DigitalOcean)

1. **Create a Managed PostgreSQL Database** in DigitalOcean:
   - Go to Databases → Create Database Cluster
   - Choose PostgreSQL
   - Note the connection string

2. **Set Environment Variable**:
   ```
   POSTGRES_CONNECTION_STRING=postgresql://user:password@host:port/database
   ```

3. **The app automatically**:
   - Uses PostgreSQL for LangGraph checkpointer
   - Uses PostgreSQL for LangGraph store (gold standards, user gripes)
   - Falls back to SQLite if PostgreSQL connection fails

## Style Index (Motivkompass Vector Store)

The style system uses a FAISS vector store containing Motivkompass style chunks
(hooks, adjectives, syntax rules, do/don't guidelines) extracted from the selling
psychology PDFs. The index powers the Style Router → Style Retriever pipeline.

### How it works

1. **`style_chunks.jsonl`** — pre-extracted style chunks are committed to the repo (~23 KB).
2. **On startup**, `services/startup.py` checks if the FAISS index exists:
   - **Found** → reuses it instantly (zero API calls)
   - **Missing** → auto-rebuilds from the JSONL (one embedding API call, ~200 chunks, < 30 seconds)
3. **Fallback** — if both JSONL and PDFs are absent, the system uses hardcoded defaults
   (fully functional, just less nuanced).

### Option A: Persistent Volume (Recommended)

With a persistent volume the index is built **once** and survives deploys/restarts:

1. In DigitalOcean App Platform: **App → Settings → Components → jd-writer → Volumes**
2. Create volume:
   - Name: `vector-store`
   - Size: **1 GiB** (plenty)
   - Mount Path: **`/app/vector_store`**
3. Set environment variable: `VECTOR_STORE_DIR=/app/vector_store`
4. Deploy — the first startup builds the index; subsequent restarts reuse it.

### Option B: No Volume (Auto-rebuild)

Without a volume the index is rebuilt from `style_chunks.jsonl` on every deploy.
This adds ~30 seconds to cold starts and costs a small embedding API call.
No configuration needed — it just works.

### Option C: PostgreSQL-backed Vector Store (Future)

For production scale, consider migrating to Chroma with PostgreSQL backend.

## Vector Store (Company Content)

For company scraping content, the vector store uses local file storage:
- **Local**: Files stored in `vector_store/` directory
- **Production**: Same persistent volume as above (`/app/vector_store`)

## Password Protection

The app includes optional password protection for MVP testing:

1. **Set in `.env` or environment variables**:
   ```
   STREAMLIT_PASSWORD=your_secure_password
   ```

2. **Users will see** a login screen before accessing the app

3. **To disable**: Simply don't set `STREAMLIT_PASSWORD`

**Note**: This is basic protection for testing. For production, implement proper authentication.

## Deployment Steps

1. **Create DigitalOcean App**:
   - Connect your GitHub repository
   - Select Python as the runtime
   - Set build command: `pip install -r requirements.txt`
   - Set run command: `streamlit run app.py --server.port=$PORT --server.address=0.0.0.0`
   - Alternatively, import `.do/app.yaml` as an App Spec

2. **Add Environment Variables**:
   - `OPENROUTER_API_KEY` (required — powers LLM + embeddings)
   - `VECTOR_STORE_DIR=/app/vector_store` (if using persistent volume)
   - `POSTGRES_CONNECTION_STRING` (if using managed PostgreSQL)
   - See full list above

3. **Add Persistent Volume** (recommended, for style index):
   - Create persistent volume (1 GiB)
   - Mount to `/app/vector_store`
   - The style index auto-builds on first startup

4. **Add Managed PostgreSQL Database** (optional):
   - Create database cluster
   - Link it to your app
   - Copy connection string to `POSTGRES_CONNECTION_STRING`

5. **Deploy**:
   - Push to GitHub → DigitalOcean auto-deploys
   - First deploy: style index builds from `style_chunks.jsonl` (~30 sec)
   - Subsequent deploys: instant (index persists on volume)

## Code Changes Summary

The following changes support both local and production:

1. **`config.py`**:
   - `POSTGRES_CONNECTION_STRING` / `USE_PERSISTENT_STORE` (auto-detected)
   - `STREAMLIT_PASSWORD` for password protection
   - `VECTOR_STORE_DIR` — path to FAISS index directory
   - `STYLE_CHUNKS_PATH` — path to pre-extracted style JSONL
   - `MODEL_EMBEDDING` — embedding model name for OpenRouter

2. **`services/startup.py`** (new):
   - `ensure_style_index()` — auto-builds FAISS index from JSONL or PDFs
   - `get_style_vector_store()` — cached singleton for the style vector store

3. **`services/vector_store.py`**:
   - `_build_embeddings()` routes through OpenRouter by default
   - `get_vector_store_manager()` uses `VECTOR_STORE_DIR` from config

4. **`graph/job_graph.py`**:
   - `node_style_router` uses `get_style_vector_store()` from startup module
   - `build_job_graph()` accepts `postgres_connection_string`

5. **`app.py`**:
   - Calls `ensure_style_index()` on startup (before serving)
   - Password protection check (if `STREAMLIT_PASSWORD` is set)

6. **`.do/app.yaml`** (new):
   - DigitalOcean App Platform spec (reference template)

## Testing Locally

1. Ensure `.env` file exists with required keys
2. Don't set `POSTGRES_CONNECTION_STRING` (uses SQLite)
3. Run: `streamlit run app.py`
4. If `STREAMLIT_PASSWORD` is set, enter password to access

## Troubleshooting

### PostgreSQL Connection Issues

- Verify `POSTGRES_CONNECTION_STRING` format
- Check database firewall rules allow your app's IP
- App will fall back to SQLite if PostgreSQL fails (with warning in logs)

### Password Protection Not Working

- Ensure `STREAMLIT_PASSWORD` is set in environment variables
- Check Streamlit session state is not being cleared
- Try clearing browser cache/cookies

### Style Index Not Building

- Check logs for `[Startup]` messages — they explain what happened
- Verify `OPENROUTER_API_KEY` is set (needed for embedding API call)
- Verify `style_chunks.jsonl` exists in the repo root
- If no JSONL and no PDFs: the system uses hardcoded defaults (still functional)

### Vector Store Not Persisting

- Ensure persistent volume is mounted correctly at `/app/vector_store`
- Set `VECTOR_STORE_DIR=/app/vector_store` in environment variables
- Check volume permissions
- Without a volume, the index auto-rebuilds from JSONL on each deploy (still works)

## Architecture: Style Pipeline on Deploy

```
┌─────────────────────────────────────────────────┐
│  App Startup (app.py)                           │
│                                                 │
│  1. ensure_style_index()                        │
│     ├─ FAISS index exists? → load (instant)     │
│     ├─ style_chunks.jsonl? → embed (~30 sec)    │
│     └─ PDFs available?     → extract + embed    │
│     └─ Nothing?            → hardcoded defaults │
│                                                 │
│  2. get_style_vector_store()  ← singleton       │
│     └─ Used by node_style_router in LangGraph   │
│                                                 │
│  3. Graph Execution                             │
│     START → style_router → generator → ...      │
│              │                                  │
│              └─ StyleKit injected into prompt    │
└─────────────────────────────────────────────────┘
```

## Next Steps (Future Production)

1. Implement proper authentication (OAuth, JWT, etc.)
2. Migrate vector store to PostgreSQL-backed Chroma
3. Add database migrations for schema changes
4. Set up monitoring and alerting
5. Configure backup strategies for PostgreSQL
