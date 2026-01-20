"""
Service layer for using the LangGraph blackboard workflow.
"""
import asyncio
import json
from typing import Dict, Optional, Iterable
from models.job_models import JobGenerationConfig, JobBody
from graph.job_graph import build_job_graph, JobState
from utils import job_body_to_dict
from database.models import get_db_manager
from logging_config import get_logger
from tracing.langfuse_tracing import get_langfuse_callbacks
from config import LANGFUSE_ENABLED, USE_PERSISTENT_STORE, POSTGRES_CONNECTION_STRING

logger = get_logger(__name__)


def _chunk_text(text: str, size: int = 400) -> Iterable[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _build_preview_text(result: Dict) -> str:
    """Build a human-readable preview string for streaming display."""
    parts = []
    if result.get("job_description"):
        parts.append("Job Description:\n" + result["job_description"])
    if result.get("requirements"):
        parts.append("Requirements:\n" + result["requirements"])
    if result.get("duties"):
        parts.append("Duties:\n" + result["duties"])
    if result.get("benefits"):
        parts.append("Benefits:\n" + result["benefits"])
    if result.get("footer"):
        parts.append("Footer:\n" + result["footer"])
    return "\n\n".join(parts)


def _run_async(coro):
    """Helper to run async functions."""
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        # Handle existing event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                import threading
                
                result = None
                exception = None
                
                def run_in_thread():
                    nonlocal result, exception
                    try:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        result = new_loop.run_until_complete(coro)
                        new_loop.close()
                    except Exception as e:
                        exception = e
                
                thread = threading.Thread(target=run_in_thread)
                thread.start()
                thread.join()
                
                if exception:
                    raise exception
                return result
            else:
                return loop.run_until_complete(coro)
        except Exception:
            raise e


async def _generate_with_graph_impl(
    job_title: str,
    config: JobGenerationConfig,
    user_id: str = "default",
    thread_id: Optional[str] = None,
    company_urls: Optional[list] = None
):
    """
    Internal implementation that yields results as they become available.
    """
    from langchain_core.runnables import RunnableConfig
    from database.store_sync import sync_all_to_store
    
    # Build graph with environment-based database configuration
    # Uses PostgreSQL if POSTGRES_CONNECTION_STRING is set, otherwise SQLite (local dev)
    graph, conn, store = await build_job_graph(
        use_persistent_store=USE_PERSISTENT_STORE,
        postgres_connection_string=POSTGRES_CONNECTION_STRING
    )
    logger.info(f"Starting job generation for: {job_title} (user: {user_id})")
    
    try:
        # Sync ORM database to LangGraph store before generation
        # This ensures gold standards and gripes are available
        db_manager = get_db_manager()
        sync_all_to_store(store, user_id, db_manager)
        logger.debug(f"Synced store for user: {user_id}")
        # Create initial state
        initial_state: JobState = {
            "messages": [],
            "job_title": job_title,
            "config": config,
            "company_urls": company_urls or [],
            "scraped_text": None,
            "candidates": [],
            "job_body_json": None,
            "style_profile_json": None,
            "consistency_report_json": None,
            "ruler_run": {},
            "ruler_runs": [],
            "ruler_scores": {},  # Will be populated by RULER curator
            "refinement_count": 0,
            "needs_refinement": False,  # Will be set based on HITL feedback or RULER scores
            "feedback_label": "no_feedback",
            "user_feedback": None,
        }
        
        # Create config
        if not thread_id:
            import uuid
            thread_id = f"thread_{uuid.uuid4().hex[:8]}"
        
        run_config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id
            }
        }
        
        # Add Langfuse tracing (standard when API keys are configured)
        langfuse_callbacks = get_langfuse_callbacks()
        if langfuse_callbacks:
            run_config["callbacks"] = langfuse_callbacks
            logger.debug("Langfuse tracing active for this run")
        elif LANGFUSE_ENABLED:
            # Keys are configured but callbacks failed to initialize
            logger.warning("Langfuse keys configured but tracing not available for this run")
        
        # Run graph with streaming
        logger.info(f"Executing graph workflow (thread: {thread_id})")
        final_state = None
        async for update in graph.astream(initial_state, config=run_config, stream_mode="updates"):
            for node, payload in update.items():
                logger.debug(f"Graph node executed: {node}")
                # Emit progress updates so UI can show activity
                yield {"type": "progress", "node": node}
                # Stream final result as soon as curator completes
                if node == "curator":
                    logger.info("Curator node completed, final candidate selected")
                    final_state = payload
                    # Yield the result immediately for streaming
                    job_body_json = payload.get("job_body_json")
                    if job_body_json:
                        try:
                            job_body_dict = json.loads(job_body_json)
                            job_body = JobBody(**job_body_dict)
                            result = job_body_to_dict(job_body)
                            ruler_run = payload.get("ruler_run", {})
                            result["ruler_score"] = ruler_run.get("best_score")
                            result["ruler_rankings"] = ruler_run.get("rankings", [])
                            result["ruler_num_candidates"] = ruler_run.get("num_candidates", 0)
                            result["thread_id"] = thread_id
                            logger.info(f"Job generation completed successfully (RULER score: {result.get('ruler_score')})")
                            preview_text = _build_preview_text(result)
                            for chunk in _chunk_text(preview_text):
                                yield {"type": "result_chunk", "text": chunk}
                            yield {"type": "result", "data": result}
                        except Exception as e:
                            logger.error(f"Error parsing job body JSON: {e}", exc_info=True)
                            # If parsing fails, continue to final state retrieval
                            pass
        
        # Get final state if streaming didn't yield
        if not final_state:
            latest = await graph.aget_state(run_config)
            final_state = latest.values if latest else {}
        
        # Parse job body from final state (fallback)
        job_body_json = final_state.get("job_body_json")
        if job_body_json:
            job_body_dict = json.loads(job_body_json)
            job_body = JobBody(**job_body_dict)
            result = job_body_to_dict(job_body)
            ruler_run = final_state.get("ruler_run", {})
            result["ruler_score"] = ruler_run.get("best_score")
            result["ruler_rankings"] = ruler_run.get("rankings", [])
            result["ruler_num_candidates"] = ruler_run.get("num_candidates", 0)
            result["thread_id"] = thread_id
            logger.info(f"Job generation completed (fallback path, RULER score: {result.get('ruler_score')})")
            preview_text = _build_preview_text(result)
            for chunk in _chunk_text(preview_text):
                yield {"type": "result_chunk", "text": chunk}
            yield {"type": "result", "data": result}
        else:
            logger.error("No job body generated - graph execution failed")
            raise ValueError("No job body generated")
    
    finally:
        if conn is not None:
            await conn.close()


async def generate_with_graph(
    job_title: str,
    config: JobGenerationConfig,
    user_id: str = "default",
    thread_id: Optional[str] = None,
    company_urls: Optional[list] = None
) -> Dict:
    """
    Generate job description using the LangGraph blackboard workflow (non-streaming).
    
    Uses LangGraph's store system for user memory across threads.
    Syncs gold standards and user gripes from ORM database to store before generation.
    
    Returns:
        Dictionary with job fields and metadata
    """
    # Non-streaming: wait for the final result event
    async for event in _generate_with_graph_impl(job_title, config, user_id, thread_id, company_urls):
        if isinstance(event, dict):
            if event.get("type") == "result":
                return event.get("data")
            if "type" not in event:
                return event
        else:
            return event
    raise ValueError("No job body generated")


def generate_job_with_blackboard(
    job_title: str,
    config: JobGenerationConfig,
    user_id: str = "default",
    thread_id: Optional[str] = None,
    company_urls: Optional[list] = None
) -> Dict:
    """Synchronous wrapper for graph generation (non-streaming)."""
    return _run_async(generate_with_graph(job_title, config, user_id, thread_id, company_urls))


async def generate_with_graph_stream(
    job_title: str,
    config: JobGenerationConfig,
    user_id: str = "default",
    thread_id: Optional[str] = None,
    company_urls: Optional[list] = None
):
    """Async generator for streaming job description generation."""
    async for result in _generate_with_graph_impl(job_title, config, user_id, thread_id, company_urls):
        yield result

