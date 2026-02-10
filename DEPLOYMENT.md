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

## Vector Index (Style + Duty Templates)

The FAISS vector store serves **two** purposes from a single index:

| Data Source | JSONL File | Chunks | What it powers |
|---|---|---|---|
| **Marketing Psychology PDFs** (Motivkompass) | `style_chunks.jsonl` (~23 KB) | ~200 style chunks (hooks, adjectives, syntax, do/don'ts) | Style Router → Style Retriever pipeline |
| **Job Categories DOCX** (Aufgaben) | `duty_chunks.jsonl` (~224 KB) | ~376 duty templates (188 junior + 188 senior across 183 categories) | 3-tier duty cascade in the generator |

Both JSONL files are **committed to the repo** so no source PDFs or DOCX files need to be uploaded to the server. The FAISS index is built from these files on first startup.

### How it works

1. **`style_chunks.jsonl`** + **`duty_chunks.jsonl`** — pre-extracted chunks committed to the repo.
2. **On startup**, `services/startup.py` → `ensure_style_index()` checks if the FAISS index exists:
   - **Found** → reuses it instantly (zero API calls)
   - **Missing** → auto-rebuilds from both JSONL files (one embedding API call, ~576 chunks, < 60 seconds)
3. **Fallback** — if both JSONL files and source documents are absent:
   - Style routing falls back to hardcoded defaults (functional, less nuanced)
   - Duty cascade skips tier 2 (category match) and lets the LLM generate duties

### Duty cascade (3-tier priority)

The generator resolves duties in this order:

1. **User-provided duties** — pre-filled in the "Duty" text area (highest priority)
2. **Job category match** — semantic search against `duty_chunks.jsonl` in the vector store, filtered by seniority (junior/mid → junior templates; senior/lead/principal → senior templates)
3. **LLM generation** — fallback only if tiers 1 and 2 produce nothing

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

Without a volume the index is rebuilt from `style_chunks.jsonl` + `duty_chunks.jsonl` on every deploy.
This adds ~60 seconds to cold starts and costs a small embedding API call.
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

3. **Add Persistent Volume** (recommended, for style + duty index):
   - Create persistent volume (1 GiB)
   - Mount to `/app/vector_store`
   - The combined index auto-builds on first startup from committed JSONL files

4. **Add Managed PostgreSQL Database** (optional):
   - Create database cluster
   - Link it to your app
   - Copy connection string to `POSTGRES_CONNECTION_STRING`

5. **Deploy**:
   - Push to GitHub → DigitalOcean auto-deploys
   - First deploy: index builds from `style_chunks.jsonl` + `duty_chunks.jsonl` (~60 sec)
   - Subsequent deploys: instant (index persists on volume)

## Code Changes Summary

The following changes support both local and production:

1. **`config.py`**:
   - `POSTGRES_CONNECTION_STRING` / `USE_PERSISTENT_STORE` (auto-detected)
   - `STREAMLIT_PASSWORD` for password protection
   - `VECTOR_STORE_DIR` — path to FAISS index directory
   - `STYLE_CHUNKS_PATH` — path to pre-extracted style JSONL
   - `DUTY_CHUNKS_PATH` — path to pre-extracted duty JSONL
   - `MODEL_EMBEDDING` — embedding model name for OpenRouter

2. **`services/startup.py`**:
   - `ensure_style_index()` — auto-builds FAISS index from both JSONL files (style + duty)
   - `get_vector_store_manager()` — cached singleton for the combined vector store
   - `_embed_from_jsonl()` — reads both `style_chunks.jsonl` and `duty_chunks.jsonl`, embeds into a single FAISS index

3. **`services/vector_store.py`**:
   - `_build_embeddings()` routes through OpenRouter by default
   - `get_vector_store_manager()` uses `VECTOR_STORE_DIR` from config

4. **`services/duty_ingestion.py`**:
   - Extracts duty templates from `Aufgaben Jobcategories.docx` → `duty_chunks.jsonl`
   - Parses 183 job categories with junior/senior duty bullet points

5. **`services/duty_retriever.py`**:
   - `retrieve_duty_templates()` — semantic search for matching job category duties
   - `_map_seniority()` — maps detailed seniority labels to junior/senior for retrieval

6. **`graph/job_graph.py`**:
   - `node_style_router` uses `get_vector_store_manager()` from startup module
   - `node_generator_expert` resolves the 3-tier duty cascade before generation
   - `build_job_graph()` accepts `postgres_connection_string`

7. **`generators/job_generator.py`**:
   - `_build_duties_prompt_section()` — builds duty context block per tier
   - `_build_duties_instruction()` — output schema instruction for duties
   - `_post_process_duties()` — enforces provided duty bullets in LLM output

8. **`app.py`**:
   - Calls `ensure_style_index()` on startup (before serving)
   - Password protection check (if `STREAMLIT_PASSWORD` is set)

9. **`.do/app.yaml`**:
   - DigitalOcean App Platform spec (reference template)

10. **Committed data files**:
    - `style_chunks.jsonl` — ~200 Motivkompass style chunks (~23 KB)
    - `duty_chunks.jsonl` — ~376 job category duty templates (~224 KB)

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

### Style / Duty Index Not Building

- Check logs for `[Startup]` messages — they explain what happened
- Verify `OPENROUTER_API_KEY` is set (needed for embedding API call)
- Verify `style_chunks.jsonl` and `duty_chunks.jsonl` exist in the repo root
- If JSONL files are missing: style routing falls back to hardcoded defaults; duty cascade skips tier 2 (still functional)

### Vector Store Not Persisting

- Ensure persistent volume is mounted correctly at `/app/vector_store`
- Set `VECTOR_STORE_DIR=/app/vector_store` in environment variables
- Check volume permissions
- Without a volume, the index auto-rebuilds from JSONL on each deploy (still works)

## Architecture: Vector Index Pipeline on Deploy

```
┌──────────────────────────────────────────────────────────┐
│  App Startup (app.py)                                    │
│                                                          │
│  1. ensure_style_index()                                 │
│     ├─ FAISS index exists?  → load (instant, 0 API)     │
│     ├─ JSONL files present? → embed both (~60 sec)       │
│     │   ├─ style_chunks.jsonl  → ~200 style chunks       │
│     │   └─ duty_chunks.jsonl   → ~376 duty templates     │
│     ├─ Source PDFs/DOCX?    → extract → embed            │
│     └─ Nothing?             → hardcoded defaults          │
│                                                          │
│  2. get_vector_store_manager()  ← singleton              │
│     ├─ Used by node_style_router (style retrieval)       │
│     └─ Used by node_generator_expert (duty retrieval)    │
│                                                          │
│  3. Graph Execution                                      │
│     START ──┬─ style_router ──┐                          │
│             └─ scrape_company ─┤                         │
│                                ▼                         │
│                           generator                      │
│                         ┌─────┴─────┐                    │
│                         │ StyleKit  │ duty_bullets        │
│                         │ (prompt)  │ (prompt)            │
│                         └───────────┘                    │
│                              ▼                           │
│                      ruler_scorer → ...                   │
└──────────────────────────────────────────────────────────┘
```

### Data flow: Duty Cascade

```
┌────────────────────┐
│  User provides     │──→ Tier 1: duty_source = "user"
│  duty keywords?    │        (highest priority, used as-is)
└────────┬───────────┘
         │ No
         ▼
┌────────────────────┐
│  Vector DB match   │──→ Tier 2: duty_source = "category"
│  for job title +   │        (from duty_chunks.jsonl, filtered by seniority)
│  seniority?        │
└────────┬───────────┘
         │ No
         ▼
┌────────────────────┐
│  LLM generates     │──→ Tier 3: duty_source = "llm"
│  duties freely     │        (fallback, infers from job title + industry)
└────────────────────┘
```

## Next Steps (Future Production)

1. Implement proper authentication (OAuth, JWT, etc.)
2. Migrate vector store to PostgreSQL-backed Chroma
3. Add database migrations for schema changes
4. Set up monitoring and alerting
5. Configure backup strategies for PostgreSQL
6. Add more job category templates (expand `duty_chunks.jsonl`)
7. Implement A/B testing for style profiles vs. duty template effectiveness