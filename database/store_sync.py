"""
Helper functions to sync ORM database with LangGraph store.
This ensures gold standards and user gripes are available in the store for the blackboard architecture.
"""
import uuid
from typing import Optional
from langgraph.store.base import BaseStore
from database.models import DatabaseManager


def sync_gold_standards_to_store(
    store: BaseStore,
    user_id: str,
    db_manager: DatabaseManager,
    limit: int = 10
):
    """
    Sync gold standards from ORM database to LangGraph store.
    This makes them available for the Generator Expert in the blackboard architecture.
    """
    gold_standards = db_manager.get_gold_standards(user_id, limit=limit)
    namespace = (user_id, "gold_standard")
    
    for gs in gold_standards:
        # Use job_title as key, store the full job body
        memory_id = gs["job_title"]  # or use a hash if titles might conflict
        memory_value = {
            "body": gs["job_body_json"],
            "config": gs.get("config_json"),
            "created_at": gs.get("created_at"),
        }
        store.put(namespace, memory_id, memory_value)


def sync_user_gripes_to_store(
    store: BaseStore,
    user_id: str,
    db_manager: DatabaseManager,
    limit: int = 20
):
    """
    Sync user feedback (rejections/edits) from ORM database to LangGraph store.
    This makes them available for the Style Expert in the blackboard architecture.
    """
    feedback = db_manager.get_user_feedback(
        user_id,
        feedback_type=None,  # Get all types
        limit=limit
    )
    namespace = (user_id, "user_gripes")
    
    for fb in feedback:
        if fb["feedback_type"] in ["rejected", "edited"] and fb.get("feedback_text"):
            # Create unique key for each gripe
            memory_id = f"{fb.get('job_title', 'general')}_{fb['id']}"
            memory_value = {
                "feedback": fb["feedback_text"],
                "type": fb["feedback_type"],
                "job_title": fb.get("job_title"),
                "created_at": fb.get("created_at"),
            }
            store.put(namespace, memory_id, memory_value)


def sync_all_to_store(
    store: BaseStore,
    user_id: str,
    db_manager: Optional[DatabaseManager] = None
):
    """
    Sync all relevant data from ORM database to LangGraph store.
    Call this before running the graph to ensure store has latest data.
    """
    if db_manager is None:
        from database.models import get_db_manager
        db_manager = get_db_manager()
    
    sync_gold_standards_to_store(store, user_id, db_manager)
    sync_user_gripes_to_store(store, user_id, db_manager)

