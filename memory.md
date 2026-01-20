# Memory & Database Architecture

This document explains the memory and database architecture used in the Job Description Writer application. The system uses a **dual-database architecture** combining SQLAlchemy ORM for structured data persistence and LangGraph's store system for user memories across threads.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [ORM Database (SQLAlchemy)](#orm-database-sqlalchemy)
3. [LangGraph Store System](#langgraph-store-system)
4. [LangGraph Checkpointer](#langgraph-checkpointer)
5. [Data Synchronization](#data-synchronization)
6. [Usage Examples](#usage-examples)
7. [Configuration](#configuration)
8. [Best Practices](#best-practices)

---

## Architecture Overview

The application uses four separate systems for different purposes:

### 1. ORM Database (SQLAlchemy)
- **Purpose**: Structured data persistence (Django-style ORM)
- **Use Case**: UI display, analytics, history
- **File**: `jd_database.sqlite`
- **Models**: `GoldStandard`, `UserFeedback`, `Interaction`

### 2. LangGraph Store (InMemoryStore/Persistent)
- **Purpose**: User memories accessible across threads
- **Use Case**: Blackboard architecture experts (Generator, Style)
- **Type**: InMemoryStore (default) or PostgresStore (production)
- **Namespaces**: `(user_id, "gold_standard")`, `(user_id, "user_gripes")`
- **Usage**:
  - **Gold Standards**: Used by Generator Expert as few-shot examples
  - **User Gripes**: Used by Style Expert for HITL-based refinement

### 3. LangGraph Checkpointer (SQLite)
- **Purpose**: Thread state management and conversation history
- **Use Case**: Graph execution tracking, state checkpoints
- **File**: `jd_threads.sqlite`
- **Type**: `AsyncSqliteSaver`

### 4. Vector Database (FAISS/Chroma) 🆕
- **Purpose**: Store scraped company website content
- **Use Case**: Company-specific content for Style Expert refinement
- **Type**: FAISS (default, local) or Chroma (optional)
- **Location**: `vector_store/` directory
- **Storage**: By company name with metadata (URLs, scrape date, interval)
- **Features**:
  - Semantic search for company-specific content
  - Automatic deduplication by company name
  - Interval-based re-scraping support
- **Modular**: Optional feature - system works without vector DB

### Data Flow

```
User Action (Accept/Reject/Edit)
    ↓
ORM Database (SQLAlchemy) ← Saves for UI/History
    ↓
Store Sync (automatic)
    ↓
LangGraph Store ← Available for next graph run
    ↓
Blackboard Experts ← Access store during generation
    ├─→ Generator Expert: Reads gold standards (few-shot examples)
    └─→ Style Expert: Reads user gripes (HITL feedback)

Company Scraping (Optional, Modular)
    ↓
Vector Database (FAISS/Chroma) ← Stores scraped content
    ↓
Style Expert ← Uses for company style consistency
```

---

## ORM Database (SQLAlchemy)

### Overview

The ORM database uses SQLAlchemy with Django-style declarative models. This provides:
- Type-safe database operations
- Automatic table creation
- Session-based transaction management
- No raw SQL queries

### Models

#### GoldStandard

Stores accepted job descriptions that serve as examples for future generations.

```python
class GoldStandard(Base):
    __tablename__ = "gold_standards"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)
    job_title = Column(String(500), nullable=False, index=True)
    job_body_json = Column(Text, nullable=False)
    config_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
```

**Fields**:
- `id`: Primary key
- `user_id`: User identifier (for multi-user support)
- `job_title`: Job title (indexed for fast lookups)
- `job_body_json`: Complete job description as JSON
- `config_json`: Generation config used (optional)
- `created_at`: Creation timestamp
- `updated_at`: Last update timestamp

**Indexes**: `(user_id, job_title)` for fast queries

#### UserFeedback

Stores user feedback including rejections, edits, and gripes.

```python
class UserFeedback(Base):
    __tablename__ = "user_feedback"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)
    job_title = Column(String(500), nullable=True)
    feedback_type = Column(String(50), nullable=False, index=True)  # 'accepted', 'rejected', 'edited', 'gripe'
    feedback_text = Column(Text, nullable=True)
    job_body_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
```

**Fields**:
- `id`: Primary key
- `user_id`: User identifier
- `job_title`: Related job title (optional)
- `feedback_type`: Type of feedback (`accepted`, `rejected`, `edited`, `gripe`)
- `feedback_text`: User's feedback text
- `job_body_json`: Related job description (optional)
- `created_at`: Creation timestamp

**Indexes**: `(user_id, feedback_type)` for filtering

#### Interaction

Stores complete history of all user interactions for analytics.

```python
class Interaction(Base):
    __tablename__ = "interactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)
    session_id = Column(String(255), nullable=True)
    interaction_type = Column(String(50), nullable=False)  # 'generation', 'edit', 'chat', 'feedback'
    job_title = Column(String(500), nullable=True)
    input_data = Column(Text, nullable=True)  # JSON
    output_data = Column(Text, nullable=True)  # JSON
    metadata_json = Column(Text, nullable=True)  # JSON (renamed from 'metadata' to avoid SQLAlchemy conflict)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)
```

**Fields**:
- `id`: Primary key
- `user_id`: User identifier
- `session_id`: Streamlit session ID (optional)
- `interaction_type`: Type of interaction
- `job_title`: Related job title (optional)
- `input_data`: Input data as JSON
- `output_data`: Output data as JSON
- `metadata_json`: Additional metadata as JSON (stored as `metadata` in API responses)
- `created_at`: Creation timestamp (indexed for chronological queries)

**Indexes**: `(user_id, created_at)` for chronological queries

### DatabaseManager

The `DatabaseManager` class provides a high-level interface for database operations.

```python
from database.models import get_db_manager

db = get_db_manager()

# Save gold standard
gold_id = db.save_gold_standard(
    user_id="user_123",
    job_title="Senior Software Engineer",
    job_body_json='{"job_description": "...", ...}',
    config_json='{"language": "en", ...}'
)

# Retrieve gold standards
standards = db.get_gold_standards(
    user_id="user_123",
    job_title="Engineer",  # Optional: filter by title
    limit=10
)

# Save user feedback
feedback_id = db.save_user_feedback(
    user_id="user_123",
    feedback_type="rejected",
    feedback_text="Too formal",
    job_title="Senior Software Engineer",
    job_body_json='{"job_description": "...", ...}'
)

# Retrieve feedback
feedback = db.get_user_feedback(
    user_id="user_123",
    feedback_type="rejected",  # Optional: filter by type
    limit=20
)

# Save interaction
interaction_id = db.save_interaction(
    user_id="user_123",
    interaction_type="generation",
    input_data={"job_title": "Engineer", "config": {...}},
    output_data={"job_body": {...}},
    metadata={"method": "blackboard", "ruler_score": 0.95},
    job_title="Senior Software Engineer"
)

# Retrieve interaction history
history = db.get_interaction_history(
    user_id="user_123",
    interaction_type="generation",  # Optional: filter by type
    limit=50
)
```

### Automatic Table Creation

Tables are automatically created when `DatabaseManager` is initialized:

```python
db = DatabaseManager(db_path="jd_database.sqlite")
# Tables are created automatically if they don't exist
```

---

## LangGraph Store System

### Overview

LangGraph's store system provides a namespace-based key-value store for user memories that persist across threads. This is essential for the blackboard architecture where experts need to access past interactions.

### Store Types

#### InMemoryStore (Default)

- **Location**: `langgraph.store.memory.InMemoryStore`
- **Use Case**: Development and testing
- **Persistence**: In-memory only (lost on restart)
- **Performance**: Fast, no I/O overhead
- **Activation**: Automatic when using blackboard architecture

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()
```

#### PostgresStore (Production)

- **Location**: `langgraph.store.postgres.PostgresStore`
- **Use Case**: Production deployments
- **Persistence**: Persistent across restarts
- **Performance**: Slightly slower, but persistent
- **Activation**: Set `use_persistent_store=True` in `build_job_graph()`

```python
from langgraph.store.postgres import PostgresStore

store = PostgresStore(
    connection_string="postgresql://user:pass@localhost/dbname"
)
```

### Namespaces

Memories are organized by **namespaces** (tuples). Each namespace represents a category of memories for a user.

#### Gold Standards Namespace

- **Namespace**: `(user_id, "gold_standard")`
- **Key**: `job_title` (or unique identifier)
- **Value**: Dictionary with job body and config

```python
namespace = (user_id, "gold_standard")
memory_key = "Senior Software Engineer"
memory_value = {
    "body": '{"job_description": "...", ...}',
    "config": '{"language": "en", ...}',
    "created_at": "2024-01-01T00:00:00Z"
}

store.put(namespace, memory_key, memory_value)
```

#### User Gripes Namespace

- **Namespace**: `(user_id, "user_gripes")`
- **Key**: Unique identifier per gripe
- **Value**: Dictionary with feedback text and metadata

```python
namespace = (user_id, "user_gripes")
memory_key = f"{job_title}_{uuid.uuid4().hex[:8]}"
memory_value = {
    "feedback": "Too formal, needs more casual tone",
    "type": "rejected",
    "job_title": "Senior Software Engineer"
}

store.put(namespace, memory_key, memory_value)
```

### Store Operations

#### Put (Store Memory)

```python
# Store a gold standard
store.put(
    (user_id, "gold_standard"),
    job_title,
    {"body": job_body_json, "config": config_json}
)

# Store a gripe
store.put(
    (user_id, "user_gripes"),
    f"{job_title}_{gripe_id}",
    {"feedback": feedback_text, "type": "rejected"}
)
```

#### Get (Retrieve Memory)

```python
# Get specific gold standard
memory = store.get((user_id, "gold_standard"), job_title)
if memory:
    job_body = memory.get("body")
```

#### Search (Find Memories)

```python
# Search gold standards (supports semantic search if configured)
memories = store.search(
    (user_id, "gold_standard"),
    query="software engineer",  # Optional: semantic search query
    limit=5
)

# Search user gripes
gripes = store.search(
    (user_id, "user_gripes"),
    limit=10
)

# Access search results
for item in memories:
    value = item.value  # Dictionary with memory data
    key = item.key      # Memory key
    namespace = item.namespace  # Namespace tuple
```

#### List (List Keys)

```python
# List all keys in a namespace
keys = store.list(
    (user_id, "gold_standard"),
    limit=10,
    before="some_key"  # Optional: pagination
)
```

#### Delete (Remove Memory)

```python
# Delete a specific memory
store.delete((user_id, "gold_standard"), job_title)
```

### Semantic Search

To enable semantic search in the store, configure it with embeddings:

```python
from langchain.embeddings import init_embeddings

store = InMemoryStore(
    index={
        "embed": init_embeddings("openai:text-embedding-3-small"),
        "dims": 1536,
        "fields": ["$"]  # Embed all fields, or specify ["body", "feedback"]
    }
)
```

Now you can use natural language queries:

```python
# Find memories about software engineering roles
memories = store.search(
    (user_id, "gold_standard"),
    query="What are good examples for software engineer roles?",
    limit=3
)
```

### Using Store in Graph Nodes

The store is automatically available in graph nodes:

```python
async def node_generator_expert(
    state: JobState,
    config: RunnableConfig,
    *,
    store: BaseStore
) -> Dict:
    user_id = config["configurable"]["user_id"]
    
    # Access gold standards from store
    namespace = (user_id, "gold_standard")
    # Smart matching: by job title and config similarity
    past_gold = store.search(namespace, query=state["job_title"], limit=3)
    
    # Extract gold examples for few-shot learning
    gold_examples = []
    for item in past_gold:
        if hasattr(item, 'value') and isinstance(item.value, dict):
            body_json = item.value.get("body", "")
            if body_json:
                gold_examples.append(body_json)
    
    # Use gold_examples as few-shot examples in generation prompt
    # Falls back gracefully if no gold standards exist
    # ...
```

```python
async def node_style_expert(
    state: JobState,
    config: RunnableConfig,
    *,
    store: BaseStore
) -> Dict:
    user_id = config["configurable"]["user_id"]
    
    # Access user gripes for HITL-based refinement
    namespace = (user_id, "user_gripes")
    gripes = store.search(namespace, limit=5)
    
    # Extract feedback - prioritize job-specific feedback
    avoid_list = []
    for item in gripes:
        if hasattr(item, 'value') and isinstance(item.value, dict):
            feedback = item.value.get("feedback", "")
            # Use feedback to refine candidates
            # ...
    
    # Also check RULER scores from state for test-time compute
    ruler_scores = state.get("ruler_scores", {})
    # Refine candidates with low scores (< 0.7 threshold)
    # ...
```

---

## LangGraph Checkpointer

### Overview

The checkpointer manages thread state and conversation history. It allows the graph to:
- Resume conversations across sessions
- Track state changes over time
- Maintain conversation context

### AsyncSqliteSaver

The application uses `AsyncSqliteSaver` for SQLite-based checkpointing:

```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite

conn = await aiosqlite.connect("jd_threads.sqlite")
checkpointer = AsyncSqliteSaver(conn)
```

### Thread Management

Each conversation is identified by a `thread_id`:

```python
config = {
    "configurable": {
        "thread_id": "thread_001",
        "user_id": "user_123"
    }
}

# Run graph with thread
result = await graph.ainvoke(initial_state, config=config)

# Resume conversation later
latest_state = await graph.aget_state(config)
```

### State History

Access the full history of a thread:

```python
# Get all state snapshots for a thread
history = [snap async for snap in graph.aget_state_history(config)]

for snapshot in history:
    state = snapshot.values
    checkpoint = snapshot.checkpoint
    # Process state...
```

### Alternative Checkpointers

For production, consider using Postgres checkpointer:

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

checkpointer = AsyncPostgresSaver(
    connection_string="postgresql://user:pass@localhost/dbname"
)
```

---

## Data Synchronization

### Overview

Data synchronization ensures that information saved to the ORM database is available in the LangGraph store for the blackboard architecture.

### Sync Functions

#### sync_gold_standards_to_store()

Syncs gold standards from ORM database to LangGraph store:

```python
from database.store_sync import sync_gold_standards_to_store

sync_gold_standards_to_store(
    store=store,
    user_id="user_123",
    db_manager=db,
    limit=10
)
```

#### sync_user_gripes_to_store()

Syncs user feedback (rejections/edits) from ORM database to LangGraph store:

```python
from database.store_sync import sync_user_gripes_to_store

sync_user_gripes_to_store(
    store=store,
    user_id="user_123",
    db_manager=db,
    limit=20
)
```

#### sync_all_to_store()

Syncs all relevant data (convenience function):

```python
from database.store_sync import sync_all_to_store

sync_all_to_store(
    store=store,
    user_id="user_123",
    db_manager=db
)
```

### Automatic Sync

The system automatically syncs data before graph execution:

```python
# In services/graph_service.py
async def generate_with_graph(...):
    graph, conn, store = await build_job_graph()
    
    # Automatic sync before generation
    db_manager = get_db_manager()
    sync_all_to_store(store, user_id, db_manager)
    
    # Now graph experts can access store
    # ...
```

### Sync Flow

1. **User Action**: User accepts/rejects/edits a job description
2. **ORM Save**: Data saved to SQLAlchemy database (for UI/history)
3. **Before Graph Run**: `sync_all_to_store()` copies data to LangGraph store
4. **During Graph Run**: Experts access store for gold standards and gripes
5. **After Graph Run**: New feedback saved to both ORM and store

---

## Usage Examples

### Complete Workflow Example

```python
from database.models import get_db_manager
from database.store_sync import sync_all_to_store
from graph.job_graph import build_job_graph
from models.job_models import JobGenerationConfig

# 1. Initialize database and store
db = get_db_manager()
graph, conn, store = await build_job_graph()

# 2. User accepts a job description
gold_id = db.save_gold_standard(
    user_id="user_123",
    job_title="Senior Software Engineer",
    job_body_json='{"job_description": "...", ...}',
    config_json='{"language": "en", ...}'
)

# 3. Sync to store (automatic in production)
sync_all_to_store(store, "user_123", db)

# 4. Generate new job using blackboard architecture
config = JobGenerationConfig(language="en", formality="neutral")
run_config = {
    "configurable": {
        "thread_id": "thread_001",
        "user_id": "user_123"
    }
}

initial_state = {
    "job_title": "Mid-Level Software Engineer",
    "config": config,
    # ... other state
}

# Generator Expert will now have access to gold standards
result = await graph.ainvoke(initial_state, config=run_config)
```

### Accessing Store in Custom Nodes

```python
async def my_custom_node(
    state: JobState,
    config: RunnableConfig,
    *,
    store: BaseStore
) -> Dict:
    user_id = config["configurable"]["user_id"]
    
    # Search for relevant memories
    memories = store.search(
        (user_id, "gold_standard"),
        query=state["job_title"],
        limit=3
    )
    
    # Use memories in your logic
    examples = [m.value["body"] for m in memories]
    
    # Store new memory
    store.put(
        (user_id, "custom_memory"),
        "key_123",
        {"data": "some value"}
    )
    
    return {"result": "done"}
```

---

## Configuration

### Database Paths

```python
# ORM Database
db = get_db_manager(db_path="jd_database.sqlite")

# Checkpointer
graph, conn, store = await build_job_graph(
    sqlite_path="jd_threads.sqlite"
)
```

### Store Configuration

```python
# Use InMemoryStore (default)
graph, conn, store = await build_job_graph()

# Use PostgresStore (production)
from langgraph.store.postgres import PostgresStore

store = PostgresStore(
    connection_string="postgresql://user:pass@localhost/dbname"
)
```

### Semantic Search Configuration

```python
from langchain.embeddings import init_embeddings

store = InMemoryStore(
    index={
        "embed": init_embeddings("openai:text-embedding-3-small"),
        "dims": 1536,
        "fields": ["body", "feedback"]  # Fields to embed
    }
)
```

---

## Best Practices

### 1. Always Sync Before Graph Execution

```python
# Good: Sync before using graph
sync_all_to_store(store, user_id, db_manager)
result = await graph.ainvoke(state, config)

# Bad: Using graph without sync
result = await graph.ainvoke(state, config)  # Store might be empty
```

### 2. Use Appropriate Namespaces

```python
# Good: Clear namespace structure
namespace = (user_id, "gold_standard")
namespace = (user_id, "user_gripes")

# Bad: Unclear namespaces
namespace = (user_id, "data")
namespace = (user_id, "stuff")
```

### 3. Handle Store Search Results Properly

```python
# Good: Check for attributes
memories = store.search(namespace, limit=5)
for item in memories:
    if hasattr(item, 'value') and isinstance(item.value, dict):
        data = item.value.get("body")

# Bad: Assuming structure
memories = store.search(namespace, limit=5)
data = memories[0].body  # Might fail
```

### 4. Use ORM for UI, Store for Graph

```python
# Good: Use ORM for UI queries
standards = db.get_gold_standards(user_id, limit=10)
# Display in UI

# Good: Use Store for graph experts
memories = store.search((user_id, "gold_standard"), limit=10)
# Use in graph node
```

### 5. Clean Up Old Memories

```python
# Periodically clean old memories
old_memories = store.list((user_id, "gold_standard"), limit=100)
for memory_key in old_memories[-50:]:  # Keep only 50 most recent
    store.delete((user_id, "gold_standard"), memory_key)
```

### 6. Use Thread IDs for Conversations

```python
# Good: Use consistent thread IDs
thread_id = f"job_{job_title}_{timestamp}"
config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

# Bad: Random thread IDs
thread_id = str(uuid.uuid4())  # Can't resume conversations
```

---

## Troubleshooting

### Store is Empty

**Problem**: Graph experts can't find gold standards or gripes.

**Solution**: Ensure sync is called before graph execution:
```python
sync_all_to_store(store, user_id, db_manager)
```

### Memory Not Persisting

**Problem**: InMemoryStore loses data on restart.

**Solution**: Use PostgresStore for production:
```python
store = PostgresStore(connection_string="...")
```

### Search Not Working

**Problem**: Semantic search returns no results.

**Solution**: Ensure store is configured with embeddings:
```python
store = InMemoryStore(index={...})
```

### Thread State Lost

**Problem**: Can't resume conversations.

**Solution**: Ensure checkpointer is properly configured:
```python
checkpointer = AsyncSqliteSaver(conn)
graph = workflow.compile(checkpointer=checkpointer, store=store)
```

---

## Migration Guide

### From Manual SQLite to ORM

If you have existing data in manual SQLite format:

1. **Export data** from old database
2. **Import to ORM** using DatabaseManager methods
3. **Sync to store** using sync functions

### From InMemoryStore to PostgresStore

1. **Export memories** from InMemoryStore
2. **Import to PostgresStore** using put operations
3. **Update graph** to use PostgresStore

---

## References

- [LangGraph Store Documentation](https://langchain-ai.github.io/langgraph/how-tos/memory/)
- [LangGraph Checkpointer Documentation](https://langchain-ai.github.io/langgraph/how-tos/persistence/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [PostgresStore Documentation](https://langchain-ai.github.io/langgraph/reference/stores/)

