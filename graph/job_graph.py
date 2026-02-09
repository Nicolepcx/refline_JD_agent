"""
LangGraph workflow for job description generation using blackboard architecture.
"""
from typing import Annotated, List, Optional, TypedDict, Literal, Dict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from models.job_models import JobBody, JobGenerationConfig, StyleKit
import asyncio
from generators.job_generator import generate_job_body_candidate_async
from ruler.ruler_utils import jd_candidate_to_trajectory, score_group_with_fallback
from services.style_router import route_style, explain_style_routing
from services.style_retriever import retrieve_style_kit
from logging_config import get_logger
import art
from art.rewards import ruler_score_group

logger = get_logger(__name__)


def merge_blackboard(
    left: Optional[List[JobBody]],
    right: Optional[List[JobBody]],
) -> List[JobBody]:
    """Merge function for blackboard candidates."""
    if right is None:
        return left or []
    return right


class JobState(TypedDict, total=False):
    """State for the job generation graph."""
    messages: Annotated[List[BaseMessage], add_messages]
    job_title: str
    config: JobGenerationConfig
    company_urls: List[str]
    scraped_text: Optional[str]
    
    # Blackboard: candidates list
    candidates: Annotated[List[JobBody], merge_blackboard]
    
    # Style routing (Motivkompass)
    style_kit: Optional[StyleKit]
    
    # Outputs
    job_body_json: Optional[str]
    style_profile_json: Optional[str]
    consistency_report_json: Optional[str]
    
    # RULER tracking
    ruler_run: Dict[str, Any]
    ruler_runs: List[Dict[str, Any]]
    ruler_scores: Dict[int, float]  # Map candidate index to RULER score (for test-time compute)
    
    # Refinement tracking
    refinement_count: int  # Track number of refinement passes
    needs_refinement: bool  # Flag indicating if refinement is needed (HITL or RULER-based)
    
    # Feedback
    feedback_label: Literal["accepted", "rejected", "edited", "no_feedback"]
    user_feedback: Optional[str]


async def node_scrape_company(state: JobState) -> JobState:
    """
    Optional: Scrape company information from URLs.
    Modular - works without scraping if URLs are not provided or scraping fails.
    """
    company_urls = state.get("company_urls", [])
    
    # If no URLs provided, skip scraping (modular design)
    if not company_urls:
        return {"scraped_text": None}
    
    try:
        from services.company_scraper import get_scraper_manager
        from services.scraping_service import extract_company_name_from_url
        
        scraper_manager = get_scraper_manager()
        
        # Extract company name from first URL
        company_name = extract_company_name_from_url(company_urls[0])
        
        # Try to get existing content from vector store first
        existing_content = scraper_manager.get_company_content(company_name, limit=3)
        
        if existing_content:
            # Use existing content from vector store
            return {"scraped_text": existing_content}
        
        # If no existing content, scrape now (one-time, not saved to config)
        scraped_text = scraper_manager.scrape_company_from_urls(
            urls=company_urls,
            company_name=company_name
        )
        
        if scraped_text:
            return {"scraped_text": scraped_text}
        else:
            # Scraping failed, but continue without it (modular)
            return {"scraped_text": None}
            
    except Exception as e:
        # If scraping fails, continue without it (modular design)
        logger.warning(f"Company scraping failed: {e}", exc_info=True)
        return {"scraped_text": None}


async def node_style_router(state: JobState) -> Dict:
    """
    Style Router node — MUST run before generation.

    Uses the scoring rubric to select a Motivkompass profile
    (red/yellow/green/blue), then assembles a StyleKit from RAG or defaults.

    The resulting StyleKit is placed on the blackboard for downstream nodes
    (generator, style_expert) to consume.

    See AGENTS.md §3 for the workflow contract.
    """
    cfg = state["config"]
    lang = cfg.language

    # 1. Route: score-based profile selection
    profile = route_style(cfg)

    # 2. Retrieve: assemble compact style kit (RAG → defaults)
    #    Use the cached singleton from startup (avoids re-creating on every call)
    vector_store = None
    try:
        from services.startup import get_style_vector_store
        vector_store = get_style_vector_store()
    except Exception:
        pass  # Vector store not available — defaults will be used

    kit = retrieve_style_kit(profile, lang=lang, vector_store=vector_store)

    # 3. Persist profile JSON for downstream / UI consumption
    style_profile_json = profile.model_dump_json(indent=2, ensure_ascii=False)

    logger.info(
        f"[Style Router] Routed: primary={profile.primary_color}, "
        f"secondary={profile.secondary_color or 'none'}, "
        f"mode={profile.interaction_mode}, frame={profile.reference_frame}"
    )
    logger.debug(f"[Style Router] Kit prompt block:\n{kit.to_prompt_block(lang)}")

    return {
        "style_kit": kit,
        "style_profile_json": style_profile_json,
    }


async def node_generator_expert(
    state: JobState,
    config: RunnableConfig,
    *,
    store: BaseStore
) -> Dict:
    """
    Expert: Initial Drafter.
    Pulls 'Gold Standards' from store and generates initial candidates.
    Uses LangGraph store to access user memories across threads.
    Uses gold standards as few-shot examples to guide generation style and structure.
    """
    user_id = config["configurable"].get("user_id", "default")
    cfg = state["config"].with_industry_defaults()
    
    # Access Shared Memory for gold standards using LangGraph store
    # Namespace: (user_id, "gold_standard")
    namespace = (user_id, "gold_standard")
    
    # Search for gold standards - try both job title match and broader search
    # This helps find similar jobs from the same company/user
    past_gold_by_title = store.search(namespace, query=state["job_title"], limit=3)
    
    # Also get general gold standards (for company style consistency)
    # This helps maintain company identity across different job types
    # Use a broader search query to get general examples
    all_gold_standards = store.search(namespace, query="", limit=5) if hasattr(store, 'search') else []
    
    # Extract gold standard bodies with smart matching
    # Priority: 1) Exact/similar job title, 2) Same company/config, 3) General style
    gold_examples = []
    seen_bodies = set()
    
    # First, add job-title-matched examples (most relevant)
    for item in past_gold_by_title:
        if hasattr(item, 'value') and isinstance(item.value, dict):
            gold_body = item.value.get("body")
            gold_config = item.value.get("config")
            if gold_body and gold_body not in seen_bodies:
                # Check config similarity (company type, industry, formality)
                config_match = True
                if gold_config:
                    try:
                        from models.job_models import JobGenerationConfig
                        if isinstance(gold_config, dict):
                            gold_cfg = JobGenerationConfig(**gold_config)
                            # Match on key style attributes
                            if (gold_cfg.company_type != cfg.company_type or
                                gold_cfg.industry != cfg.industry or
                                gold_cfg.formality != cfg.formality):
                                config_match = False
                    except Exception:
                        pass  # If config parsing fails, still use the example
                
                # Prefer examples with matching config, but include others too
                if config_match or len(gold_examples) < 1:
                    gold_examples.append(gold_body)
                    seen_bodies.add(gold_body)
                    if len(gold_examples) >= 2:
                        break
    
    # If we don't have enough examples, add general ones (for company style)
    if len(gold_examples) < 2:
        for item in all_gold_standards:
            if hasattr(item, 'value') and isinstance(item.value, dict):
                gold_body = item.value.get("body")
                if gold_body and gold_body not in seen_bodies:
                    gold_examples.append(gold_body)
                    seen_bodies.add(gold_body)
                    if len(gold_examples) >= 2:
                        break
    
    # Get style kit from blackboard (populated by style_router node)
    style_kit = state.get("style_kit")
    
    # Generate initial candidates using gold standards as examples
    num_candidates = 3
    tasks = []
    for i in range(num_candidates):
        # Pass gold examples to guide generation (maintain consistency across candidates)
        tasks.append(
            generate_job_body_candidate_async(
                state["job_title"],
                cfg,
                temp_jitter=(i * 0.1),
                gold_examples=gold_examples if gold_examples else None,
                style_kit=style_kit,
            )
        )
    seeds = await asyncio.gather(*tasks)
    
    return {"candidates": seeds}


async def node_style_expert(
    state: JobState,
    config: RunnableConfig,
    *,
    store: BaseStore
) -> Dict:
    """
    Expert: Refiner.
    Refines candidates based on:
    1. HITL (Human-in-the-Loop) feedback from UI (primary)
    2. RULER scores (test-time compute) - identifies weak candidates
    3. Company context for style consistency
    
    Only refines when there's actual feedback or RULER indicates need for improvement.
    """
    user_id = config["configurable"].get("user_id", "default")
    candidates = state.get("candidates", [])
    refinement_count = state.get("refinement_count", 0)
    scraped_text = state.get("scraped_text")
    ruler_scores = state.get("ruler_scores", {})  # Candidate index -> score
    
    if not candidates:
        return {"candidates": [], "is_refined": True, "refinement_count": refinement_count + 1}
    
    # Check if refinement is needed (HITL or RULER-based)
    has_hitl_feedback = False
    needs_ruler_refinement = False
    
    # 1. Check for HITL feedback (primary source)
    namespace = (user_id, "user_gripes")
    gripes = store.search(namespace, limit=5)
    
    # Extract HITL feedback from gripes - prioritize job-specific feedback
    avoid_list = []
    general_feedback = []
    current_job_title = state.get("job_title", "").lower()
    
    for item in gripes:
        if hasattr(item, 'value') and isinstance(item.value, dict):
            feedback = item.value.get("feedback", "")
            gripe_job_title = item.value.get("job_title", "").lower()
            if feedback:
                has_hitl_feedback = True
                # Prioritize feedback for similar job titles
                if current_job_title and gripe_job_title and any(
                    word in gripe_job_title for word in current_job_title.split() if len(word) > 3
                ):
                    avoid_list.append(f"- {feedback}")
                else:
                    general_feedback.append(f"- {feedback}")
    
    # 2. Check RULER scores (test-time compute) - identify candidates needing refinement
    ruler_threshold = 0.7  # Refine candidates below this score
    candidates_to_refine = []
    if ruler_scores:
        for idx, candidate in enumerate(candidates):
            score = ruler_scores.get(idx, 1.0)  # Default to 1.0 if no score
            if score < ruler_threshold:
                needs_ruler_refinement = True
                candidates_to_refine.append((idx, candidate, score))
    
    # Only refine if we have HITL feedback OR RULER indicates need
    # HITL feedback takes priority (user explicitly provided feedback)
    if not has_hitl_feedback and not needs_ruler_refinement:
        # No refinement needed - return candidates as-is
        # This ensures we only refine when there's actual feedback or quality issues
        return {
            "candidates": candidates,
            "is_refined": False,
            "refinement_count": refinement_count,
            "needs_refinement": False
        }
    
    # Build refinement context with proper context engineering
    refinement_context = []
    
    # HITL feedback context (highest priority)
    if has_hitl_feedback:
        all_feedback = avoid_list + general_feedback[:2]  # Limit general feedback
        avoid_text = "\n".join(all_feedback) if all_feedback else ""
        if avoid_text:
            refinement_context.append(f"IMPORTANT - User Feedback (HITL): Avoid these issues from past feedback:\n{avoid_text}")
    
    # RULER-based refinement context (test-time compute)
    if needs_ruler_refinement and candidates_to_refine:
        ruler_feedback = []
        for idx, candidate, score in candidates_to_refine:
            ruler_feedback.append(f"Candidate {idx + 1} scored {score:.2f} (below threshold {ruler_threshold}) - needs improvement")
        refinement_context.append(f"RULER Analysis (Test-time Compute):\n" + "\n".join(ruler_feedback))
    
    # Company context (for style consistency, lower priority)
    if scraped_text:
        refinement_context.append(f"Company Context (for style consistency):\n{scraped_text[:300]}...")
    
    # Refine candidates (concurrent)
    refined_candidates = []
    try:
        from models.job_models import JobBody

        refinement_instructions = "\n\n".join(refinement_context) if refinement_context else ""

        refine_indices = set()
        if has_hitl_feedback:
            refine_indices = set(range(len(candidates)))
        elif needs_ruler_refinement:
            refine_indices = {i for i, _, _ in candidates_to_refine}

        async def refine_one(idx: int, candidate: JobBody) -> JobBody:
            if idx not in refine_indices:
                return candidate

            # Create a fresh LLM instance for this refinement call to avoid connection pool contention
            from langchain_openai import ChatOpenAI
            from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, MODEL_BASE
            from llm_service import _get_extra_body_for_model
            
            # Optimize for latency with provider routing + disable thinking for Qwen models
            extra_body = _get_extra_body_for_model(MODEL_BASE)
            
            fresh_llm = ChatOpenAI(
                model=MODEL_BASE,
                temperature=0,
                api_key=OPENROUTER_API_KEY,
                base_url=OPENROUTER_BASE_URL,
                extra_body=extra_body,
            )
            style_llm = fresh_llm.with_structured_output(JobBody).bind(temperature=0.3)

            candidate_json = candidate.model_dump_json(indent=2, ensure_ascii=False)
            ruler_info = ""
            if idx in ruler_scores:
                ruler_info = f"\nRULER Score: {ruler_scores[idx]:.3f} (target: >{ruler_threshold})"

            lang = state["config"].language
            if lang == "en":
                refine_prompt = (
                    "You are refining a job description based on feedback and quality analysis.\n"
                    f"{refinement_instructions}\n"
                    f"{ruler_info}\n\n"
                    f"Current job description:\n{candidate_json}\n\n"
                    "Refine this job description to:\n"
                    "- Maintain the same structure and format\n"
                    "- Address the feedback and issues mentioned above\n"
                    "- Improve clarity, professionalism, and alignment\n"
                    "- Ensure alignment with company style (if context provided)\n"
                    "- Keep all essential information\n"
                    "Return the refined JobBody instance."
                )
            else:
                refine_prompt = (
                    "Du verfeinerst eine Stellenbeschreibung basierend auf Feedback und Qualitätsanalyse.\n"
                    f"{refinement_instructions}\n"
                    f"{ruler_info}\n\n"
                    f"Aktuelle Stellenbeschreibung:\n{candidate_json}\n\n"
                    "Verfeinere diese Stellenbeschreibung, um:\n"
                    "- Die gleiche Struktur und das Format beizubehalten\n"
                    "- Auf die oben genannten Feedback-Probleme einzugehen\n"
                    "- Klarheit, Professionalität und Ausrichtung zu verbessern\n"
                    "- Ausrichtung am Unternehmensstil sicherzustellen (falls Kontext vorhanden)\n"
                    "- Alle wesentlichen Informationen beizubehalten\n"
                    "Gib die verfeinerte JobBody-Instanz zurück."
                )

            try:
                # Use ainvoke for true async execution
                return await style_llm.ainvoke(refine_prompt)
            except Exception as e:
                logger.warning(f"Refinement failed for candidate {idx}: {e}", exc_info=True)
                return candidate

        refined_candidates = await asyncio.gather(
            *[refine_one(idx, candidate) for idx, candidate in enumerate(candidates)]
        )
    except Exception as e:
        # If refinement system fails, use original candidates
        logger.warning(f"Style refinement system unavailable: {e}", exc_info=True)
        refined_candidates = candidates
    
    return {
        "candidates": refined_candidates,
        "is_refined": True,
        "refinement_count": refinement_count + 1,
        "needs_refinement": has_hitl_feedback or needs_ruler_refinement
    }


async def node_ruler_scorer(state: JobState) -> Dict:
    """
    Expert: RULER Scorer (Test-time Compute).
    Scores all candidates using RULER and stores scores for Style Expert to use.
    Does NOT select winner yet - that's done by curator after refinement.
    """
    candidates = state.get("candidates", [])
    if not candidates:
        return {"ruler_scores": {}}
    
    # RULER scoring (test-time compute)
    trajectories = [
        jd_candidate_to_trajectory(state["job_title"], state["config"], jb)
        for jb in candidates
    ]
    group = art.TrajectoryGroup(trajectories)
    
    # Score candidates using configured RULER judge model
    from config import MODEL_RULER_JUDGE, MODEL_RULER_JUDGE_FALLBACK
    judged_group = await score_group_with_fallback(
        group, MODEL_RULER_JUDGE, fallback_model=MODEL_RULER_JUDGE_FALLBACK, debug=False
    )
    
    # Store RULER scores for each candidate (for refinement decisions)
    ruler_scores = {}
    
    if not judged_group:
        # Graceful fallback: set default scores
        for idx in range(len(candidates)):
            ruler_scores[idx] = 0.0
        return {"ruler_scores": ruler_scores}
    
    # Store scores by candidate index
    for idx, (traj, jb) in enumerate(zip(judged_group.trajectories, candidates)):
        ruler_scores[idx] = float(traj.reward)
    
    return {"ruler_scores": ruler_scores}




async def node_ruler_scorer_after_style(state: JobState) -> Dict:
    """Re-score after style refinement to validate updated candidates."""
    return await node_ruler_scorer(state)


def should_rescore_after_style(state: JobState) -> str:
    """Only re-score if Style Expert actually refined candidates."""
    return "ruler_scorer_after_style" if state.get("is_refined") else "curator"


async def node_ruler_curator(state: JobState) -> Dict:
    """
    Expert: Final Judge.
    Selects the winner from candidates (after potential refinement).
    Uses existing RULER scores if available (from ruler_scorer or ruler_scorer_after_style).
    Only re-scores if scores are missing or candidate count changed.
    """
    candidates = state.get("candidates", [])
    if not candidates:
        return {"job_body_json": "Error: Blackboard was empty at Curate step."}
    
    # Check if we already have RULER scores
    # These could be from:
    # 1. ruler_scorer (initial scoring)
    # 2. ruler_scorer_after_style (re-scoring after refinement)
    existing_scores = state.get("ruler_scores", {})
    
    # If we have scores and same number of candidates, use them (avoid unnecessary re-scoring)
    # This handles both initial scores and post-refinement scores
    if existing_scores and len(existing_scores) == len(candidates):
        # Use existing scores
        scored_candidates = sorted(
            [(existing_scores.get(idx, 0.0), jb) for idx, jb in enumerate(candidates)],
            key=lambda x: x[0],
            reverse=True
        )
        best_jb = scored_candidates[0][1]
        best_score = scored_candidates[0][0]
        
        # Build rankings from existing scores
        rankings = []
        for rank, (score, jb) in enumerate(scored_candidates, start=1):
            rankings.append({
                "rank": rank,
                "score": float(score),
                "job_description_preview": (jb.job_description or "")[:100] + "..." if jb.job_description else ""
            })
    else:
        # Re-score candidates only if:
        # 1. No scores exist, OR
        # 2. Candidate count changed (shouldn't happen, but handle gracefully)
        # Note: If ruler_scorer_after_style ran, it should have updated ruler_scores,
        # so we shouldn't reach this branch. This is a fallback for edge cases.
        logger.debug(
            f"Re-scoring in curator: existing_scores={len(existing_scores) if existing_scores else 0}, "
            f"candidates={len(candidates)}"
        )
        trajectories = [
            jd_candidate_to_trajectory(state["job_title"], state["config"], jb)
            for jb in candidates
        ]
        group = art.TrajectoryGroup(trajectories)
        
        # Re-score using configured RULER judge model
        from config import MODEL_RULER_JUDGE, MODEL_RULER_JUDGE_FALLBACK
        judged_group = await score_group_with_fallback(
            group, MODEL_RULER_JUDGE, fallback_model=MODEL_RULER_JUDGE_FALLBACK, debug=False
        )
        
        if not judged_group:
            # Graceful fallback: use first candidate
            best_jb = candidates[0]
            return {
                "job_body_json": best_jb.model_dump_json(indent=2, ensure_ascii=False),
                "ruler_run": {
                    "best_score": 0.0,
                    "fallback": True,
                    "rankings": [],
                    "num_candidates": len(candidates)
                }
            }
        
        scored = sorted(
            zip(judged_group.trajectories, candidates),
            key=lambda x: x[0].reward,
            reverse=True
        )
        best_jb = scored[0][1]
        best_score = float(scored[0][0].reward)
        
        # Store all rankings for display
        rankings = []
        for rank, (traj, jb) in enumerate(scored, start=1):
            rankings.append({
                "rank": rank,
                "score": float(traj.reward),
                "job_description_preview": (jb.job_description or "")[:100] + "..." if jb.job_description else ""
            })
    
    return {
        "job_body_json": best_jb.model_dump_json(indent=2, ensure_ascii=False),
        "ruler_run": {
            "best_score": float(best_score),
            "rankings": rankings,
            "num_candidates": len(candidates)
        }
    }


def node_persist_feedback_to_store(
    state: JobState,
    config: RunnableConfig,
    *,
    store: BaseStore
) -> Dict:
    """
    Persist feedback to LangGraph store (gold standards, gripes, etc.).
    This allows the store to be accessed across threads for the same user.
    """
    user_id = config["configurable"]["user_id"]
    final_body = state.get("job_body_json")
    
    # Namespace for gold standards: (user_id, "gold_standard")
    if state.get("feedback_label") == "accepted" and final_body:
        namespace = (user_id, "gold_standard")
        # Use job_title as key (or generate unique ID)
        memory_key = state["job_title"]
        memory_value = {
            "body": final_body,
            "config": state.get("config"),
            "created_at": None,  # Could add timestamp
        }
        store.put(namespace, memory_key, memory_value)
    
    # Namespace for user gripes: (user_id, "user_gripes")
    if state.get("feedback_label") in ["rejected", "edited"] and state.get("user_feedback"):
        namespace = (user_id, "user_gripes")
        # Generate unique key for each gripe
        import uuid
        memory_key = f"{state['job_title']}_{uuid.uuid4().hex[:8]}"
        memory_value = {
            "feedback": state["user_feedback"],
            "type": state["feedback_label"],
            "job_title": state["job_title"],
        }
        store.put(namespace, memory_key, memory_value)
    
    return {}  # Side-effect node


def should_refine_again(state: JobState) -> str:
    """
    Conditional edge function to decide if Style Expert should refine.
    Only refines if:
    1. HITL feedback exists in store (user provided feedback via UI in past), OR
    2. RULER scores indicate candidates need improvement (test-time compute)
    
    This makes refinement HITL and RULER-based, not automatic.
    Note: HITL feedback check happens in Style Expert (it has store access),
    but we pre-check RULER scores here.
    """
    refinement_count = state.get("refinement_count", 0)
    
    # Check RULER scores (test-time compute) - available immediately
    ruler_scores = state.get("ruler_scores", {})
    needs_ruler_refinement = False
    if ruler_scores:
        ruler_threshold = 0.7
        for score in ruler_scores.values():
            if score < ruler_threshold:
                needs_ruler_refinement = True
                break
    
    # HITL feedback check will be done in Style Expert (it has store access)
    # For now, if RULER indicates need, go to Style Expert
    # Style Expert will also check for HITL feedback from store
    
    # Only refine if:
    # - We haven't refined yet AND
    # - RULER indicates issues (HITL check happens in Style Expert)
    if refinement_count == 0 and needs_ruler_refinement:
        return "style_expert"  # Go to style expert for refinement
    
    # Always check Style Expert on first pass - it will check for HITL feedback from store
    # and decide whether to refine based on HITL or RULER scores
    if refinement_count == 0:
        return "style_expert"  # Let Style Expert check HITL feedback and RULER scores
    
    # Already refined, go to curator for final selection
    return "curator"


async def build_job_graph(
    *,
    sqlite_path: str = "jd_threads.sqlite",
    use_persistent_store: bool = False,
    postgres_connection_string: Optional[str] = None
):
    """
    Build the LangGraph workflow for job description generation.
    
    Uses LangGraph's store system for user interactions across threads.
    - SQLite + InMemoryStore: For local development (default)
    - PostgreSQL + PostgresStore: For production (when postgres_connection_string is provided)
    
    Args:
        sqlite_path: Path to SQLite database for checkpointer (used if postgres_connection_string is None)
        use_persistent_store: If True, use PostgresStore; if False, use InMemoryStore
        postgres_connection_string: PostgreSQL connection string (if provided, uses PostgreSQL instead of SQLite)
        
    Returns:
        Compiled graph, connection (if SQLite), and store
    """
    # Import AsyncSqliteSaver - try multiple import paths
    AsyncSqliteSaver = None
    conn = None
    try:
        # Try the standard import path first
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        import aiosqlite
        # Try to create connection
        try:
            conn = await aiosqlite.connect(sqlite_path)
            if not hasattr(conn, "is_alive"):
                conn.is_alive = lambda: True
        except Exception as e:
            logger.warning(f"Could not connect to SQLite database: {e}", exc_info=True)
            conn = None
    except ImportError:
        try:
            # Try alternative import path
            from langgraph_checkpoint_sqlite.aio import AsyncSqliteSaver
            import aiosqlite
            try:
                conn = await aiosqlite.connect(sqlite_path)
                if not hasattr(conn, "is_alive"):
                    conn.is_alive = lambda: True
            except Exception as e:
                logger.warning(f"Could not connect to SQLite database: {e}", exc_info=True)
                conn = None
        except ImportError:
            try:
                # Try direct package import
                from langgraph_checkpoint_sqlite import AsyncSqliteSaver
                import aiosqlite
                try:
                    conn = await aiosqlite.connect(sqlite_path)
                    if not hasattr(conn, "is_alive"):
                        conn.is_alive = lambda: True
                except Exception as e:
                    logger.warning(f"Could not connect to SQLite database: {e}", exc_info=True)
                    conn = None
            except ImportError:
                # Fallback to InMemorySaver if SQLite checkpoint is not available
                # Note: InMemorySaver works fine for development, but checkpoints are lost on restart
                # For production with persistent checkpoints, install: pip install langgraph-checkpoint-sqlite
                AsyncSqliteSaver = None
                conn = None
    
    from langgraph.store.memory import InMemoryStore
    
    workflow = StateGraph(JobState)
    
    # Add nodes
    workflow.add_node("style_router", node_style_router)  # Motivkompass profile selection
    workflow.add_node("scrape_company", node_scrape_company)
    workflow.add_node("generator", node_generator_expert)
    workflow.add_node("ruler_scorer", node_ruler_scorer)  # RULER scoring (test-time compute)
    workflow.add_node("style_expert", node_style_expert)
    workflow.add_node("ruler_scorer_after_style", node_ruler_scorer_after_style)
    workflow.add_node("curator", node_ruler_curator)  # Final selection
    workflow.add_node("persist", node_persist_feedback_to_store)
    
    # Add edges
    # Style Router MUST run before generation (see AGENTS.md §3)
    # Scrape runs in parallel with style routing
    workflow.add_edge(START, "style_router")
    workflow.add_edge(START, "scrape_company")
    
    # Generator depends on style_router (needs style_kit on blackboard)
    workflow.add_edge("style_router", "generator")
    
    # Join scrape + generator before scoring
    workflow.add_edge("scrape_company", "ruler_scorer")
    workflow.add_edge("generator", "ruler_scorer")

    # Run RULER scorer first to get test-time compute scores (before refinement)
    
    # After RULER scoring, Style Expert can refine based on scores + HITL feedback
    workflow.add_conditional_edges(
        "ruler_scorer",
        should_refine_again,  # Check if refinement is needed (HITL or RULER-based)
        {
            "style_expert": "style_expert",  # Refine if needed
            "curator": "curator"  # Skip refinement, go directly to selection
        }
    )
    
    # After refinement, optionally re-score to validate updated candidates
    workflow.add_conditional_edges(
        "style_expert",
        should_rescore_after_style,
        {
            "ruler_scorer_after_style": "ruler_scorer_after_style",
            "curator": "curator",
        },
    )
    workflow.add_edge("ruler_scorer_after_style", "curator")
    
    # Final selection and persistence
    workflow.add_edge("curator", "persist")
    workflow.add_edge("persist", END)
    
    # Setup checkpointer and store based on environment
    # If PostgreSQL connection string is provided, use PostgreSQL; otherwise use SQLite
    if postgres_connection_string:
        # Production: Use PostgreSQL for both checkpointer and store
        try:
            from langgraph.store.postgres import PostgresStore
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            
            store = PostgresStore(connection_string=postgres_connection_string)
            checkpointer = AsyncPostgresSaver(connection_string=postgres_connection_string)
            conn = None  # No SQLite connection needed
            logger.info("Using PostgreSQL for checkpointer and store (production mode)")
        except ImportError as e:
            logger.warning(f"PostgreSQL support not available: {e}. Falling back to SQLite.")
            # Fall back to SQLite if PostgreSQL packages aren't installed
            if AsyncSqliteSaver is not None and conn is not None:
                checkpointer = AsyncSqliteSaver(conn)
            else:
                from langgraph.checkpoint.memory import MemorySaver
                checkpointer = MemorySaver()
                conn = None
            store = InMemoryStore()
    else:
        # Local development: Use SQLite for checkpointer, InMemoryStore for store
        if AsyncSqliteSaver is not None and conn is not None:
            checkpointer = AsyncSqliteSaver(conn)
        else:
            # Use MemorySaver as fallback if SQLite checkpoint is not available
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
            conn = None
        
        # Setup store for user interactions across threads
        # InMemoryStore for development, PostgresStore for production
        if use_persistent_store:
            try:
                from langgraph.store.postgres import PostgresStore
                # This branch is for when use_persistent_store=True but no connection string
                # In practice, postgres_connection_string should be set if use_persistent_store=True
                store = InMemoryStore()
                logger.warning("use_persistent_store=True but no postgres_connection_string provided. Using InMemoryStore.")
            except ImportError:
                store = InMemoryStore()
        else:
            # Use InMemoryStore - LangGraph handles this automatically
            # Memories are namespaced by (user_id, "gold_standard") or (user_id, "user_gripes")
            store = InMemoryStore()
            logger.info("Using SQLite checkpointer and InMemoryStore (local development mode)")
    
    # Compile graph with both checkpointer (for threads) and store (for user memory)
    compiled_graph = workflow.compile(checkpointer=checkpointer, store=store)
    
    return compiled_graph, conn, store

