# Deployment Guide for DigitalOcean App Platform

This guide explains how to deploy the JD Writer MAS application to DigitalOcean App Platform with minimal configuration changes.

## Overview

The application automatically detects the environment and uses:
- **Local Development**: SQLite database + InMemoryStore (default)
- **Production (DigitalOcean)**: PostgreSQL database + PostgresStore (when `POSTGRES_CONNECTION_STRING` is set)

## Environment Variables

### Required for Production

Add these environment variables in DigitalOcean App Platform:

1. **PostgreSQL Connection** (if using managed PostgreSQL):
   ```
   POSTGRES_CONNECTION_STRING=postgresql://user:password@host:port/database
   ```
   - DigitalOcean provides this when you create a managed PostgreSQL database
   - The app automatically uses PostgreSQL when this is set

2. **API Keys**:
   ```
   OPENROUTER_API_KEY=your_openrouter_api_key
   ```

3. **Optional - Langfuse Tracing**:
   ```
   LANGFUSE_SECRET_KEY=your_secret_key
   LANGFUSE_PUBLIC_KEY=your_public_key
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   ```

4. **Optional - Password Protection** (MVP testing safeguard):
   ```
   STREAMLIT_PASSWORD=your_secure_password
   ```
   - If set, users must enter this password to access the Streamlit app
   - Leave unset to disable password protection

### Local Development (.env file)

For local testing, create a `.env` file with:
```bash
# API Keys
OPENROUTER_API_KEY=your_key_here

# Optional: Langfuse tracing
LANGFUSE_SECRET_KEY=your_key
LANGFUSE_PUBLIC_KEY=your_key

# Optional: Password protection
STREAMLIT_PASSWORD=test_password

# Leave POSTGRES_CONNECTION_STRING unset for local SQLite
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

## Vector Store

For MVP, the vector store (FAISS/Chroma) uses local file storage:
- **Local**: Files stored in `vector_store/` directory
- **Production**: Use DigitalOcean persistent volumes to mount `vector_store/` directory

### Option A: Persistent Volumes (Recommended for MVP)

1. In DigitalOcean App Platform, add a persistent volume
2. Mount it to `/app/vector_store`
3. No code changes needed

### Option B: PostgreSQL-backed Vector Store (Future)

For production scale, consider migrating to Chroma with PostgreSQL backend.

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

2. **Add Environment Variables**:
   - Add all required environment variables (see above)
   - Include `POSTGRES_CONNECTION_STRING` if using managed PostgreSQL

3. **Add Managed PostgreSQL Database** (if using):
   - Create database cluster
   - Link it to your app
   - Copy connection string to `POSTGRES_CONNECTION_STRING`

4. **Add Persistent Volume** (for vector store):
   - Create persistent volume
   - Mount to `/app/vector_store`

5. **Deploy**:
   - Push to GitHub
   - DigitalOcean will auto-deploy

## Code Changes Summary

The following minimal changes were made to support both local and production:

1. **`config.py`**:
   - Added `POSTGRES_CONNECTION_STRING` and `USE_PERSISTENT_STORE` (auto-detected)
   - Added `STREAMLIT_PASSWORD` for password protection

2. **`graph/job_graph.py`**:
   - Updated `build_job_graph()` to accept `postgres_connection_string`
   - Auto-detects: uses PostgreSQL if connection string provided, otherwise SQLite

3. **`services/graph_service.py`**:
   - Passes PostgreSQL connection string to `build_job_graph()`

4. **`app.py`**:
   - Added password protection check at startup (if `STREAMLIT_PASSWORD` is set)

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

### Vector Store Not Persisting

- Ensure persistent volume is mounted correctly
- Check volume permissions
- Verify `vector_store/` directory exists

## Next Steps (Future Production)

1. Implement proper authentication (OAuth, JWT, etc.)
2. Migrate vector store to PostgreSQL-backed Chroma
3. Add database migrations for schema changes
4. Set up monitoring and alerting
5. Configure backup strategies for PostgreSQL
