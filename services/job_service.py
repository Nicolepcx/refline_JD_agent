"""
Service layer for job description generation.
Provides high-level functions that can use either the simple LLM approach
or the advanced JobGenerationConfig approach with optional RULER ranking.
"""
import asyncio
from models.job_models import JobGenerationConfig, JobBody, SkillItem
from generators.job_generator import render_job_body
from ruler.ruler_utils import generate_best_job_body_with_ruler
from llm_service import call_llm
from utils import job_body_to_dict, dict_to_job_body, strip_bullet_prefix
from logging_config import get_logger

logger = get_logger(__name__)


def _run_async(coro):
    """Helper to run async functions, handling existing event loops."""
    try:
        # Try asyncio.run() first (works when no event loop exists)
        return asyncio.run(coro)
    except RuntimeError as e:
        # If event loop already exists, try to use it
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Loop is running - this is tricky in Streamlit
                # Fall back to creating a new thread with a new event loop
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
            # If all else fails, raise the original error
            raise e


def generate_full_job_description(
    job_title: str,
    config: JobGenerationConfig | None = None,
    use_advanced: bool = True,
    use_ruler: bool = False,
    num_candidates: int = 3,
    user_id: str = "default",
    company_urls: list | None = None,
) -> dict:
    """
    Generate a complete job description using blackboard architecture with multi-expert workflow.
    Optionally uses RULER to rank multiple candidates and select the best one.
    
    Args:
        job_title: The job title
        config: Optional JobGenerationConfig. If None, uses defaults
        use_advanced: If True, uses blackboard architecture (default). If False, uses simple call_llm
        use_ruler: If True, generates multiple candidates and uses RULER to rank them
        num_candidates: Number of candidates to generate when using RULER (default: 3)
        user_id: User ID for storing gold standards and feedback
        
    Returns:
        Dictionary with job fields compatible with session state
    """
    # Always use blackboard architecture (default behavior)
    if use_advanced and config:
        try:
            from services.graph_service import generate_job_with_blackboard
            from database.models import get_db_manager
            
            result = generate_job_with_blackboard(
                job_title, config, user_id=user_id, company_urls=company_urls
            )
            
            # Log interaction
            db = get_db_manager()
            db.save_interaction(
                user_id,
                "generation",
                input_data={"job_title": job_title, "config": config.model_dump()},
                output_data=result,
                metadata={"method": "blackboard", "ruler_score": result.get("ruler_score")},
                job_title=job_title
            )
            
            return result
        except Exception as e:
            logger.error(f"Blackboard generation failed: {e}", exc_info=True)
            # If blackboard fails, try direct generation as fallback
            pass
    
    if use_advanced and config:
        if use_ruler:
            # Use RULER to generate and rank multiple candidates
            try:
                # Run async function in sync context
                best_job_body, scored_candidates = _run_async(
                    generate_best_job_body_with_ruler(
                        job_title, config, num_candidates=num_candidates
                    )
                )
                result = job_body_to_dict(best_job_body)
                # Store RULER rankings for display
                rankings = []
                for rank, (score, jb) in enumerate(scored_candidates, start=1):
                    rankings.append({
                        "rank": rank,
                        "score": float(score),
                        "job_description_preview": (jb.job_description or "")[:100] + "..." if jb.job_description else ""
                    })
                result["ruler_rankings"] = rankings
                result["ruler_score"] = float(scored_candidates[0][0]) if scored_candidates else None
                result["ruler_num_candidates"] = len(scored_candidates)
                return result
            except Exception as e:
                # Fallback to single generation if RULER fails
                logger.error(f"RULER failed, falling back to single generation: {e}", exc_info=True)
                job_body = render_job_body(job_title, config)
                return job_body_to_dict(job_body)
        else:
            # Single generation without RULER
            job_body = render_job_body(job_title, config)
            return job_body_to_dict(job_body)
    elif use_advanced:
        # Use default config with blackboard architecture
        default_config = JobGenerationConfig()
        try:
            from services.graph_service import generate_job_with_blackboard
            from database.models import get_db_manager
            
            result = generate_job_with_blackboard(job_title, default_config, user_id=user_id)
            
            # Log interaction
            db = get_db_manager()
            db.save_interaction(
                user_id,
                "generation",
                input_data={"job_title": job_title, "config": default_config.model_dump()},
                output_data=result,
                metadata={"method": "blackboard", "ruler_score": result.get("ruler_score")},
                job_title=job_title
            )
            
            return result
        except Exception as e:
            logger.error(f"Blackboard generation failed with default config: {e}", exc_info=True)
            # Fallback to direct generation
            if use_ruler:
                try:
                    best_job_body, scored_candidates = _run_async(
                        generate_best_job_body_with_ruler(
                            job_title, default_config, num_candidates=num_candidates
                        )
                    )
                    result = job_body_to_dict(best_job_body)
                    # Store RULER rankings for display
                    rankings = []
                    for rank, (score, jb) in enumerate(scored_candidates, start=1):
                        rankings.append({
                            "rank": rank,
                            "score": float(score),
                            "job_description_preview": (jb.job_description or "")[:100] + "..." if jb.job_description else ""
                        })
                    result["ruler_rankings"] = rankings
                    result["ruler_score"] = float(scored_candidates[0][0]) if scored_candidates else None
                    result["ruler_num_candidates"] = len(scored_candidates)
                    return result
                except Exception as e:
                    logger.error(f"RULER failed, falling back to single generation: {e}", exc_info=True)
                    job_body = render_job_body(job_title, default_config)
                    return job_body_to_dict(job_body)
            else:
                job_body = render_job_body(job_title, default_config)
                return job_body_to_dict(job_body)
    else:
        # Fallback to simple approach
        return _generate_simple_job_description(job_title)


def generate_job_section(
    section: str,
    job_title: str,
    current_value: str,
    context: dict,
    config: JobGenerationConfig | None = None,
    use_advanced: bool = False,
) -> str:
    """
    Generate or improve a specific section of a job description.
    
    Args:
        section: One of 'description', 'requirements', 'duties', 'benefits', 'footer'
        job_title: The job title
        current_value: Current text for this section
        context: Other job fields for context
        config: Optional JobGenerationConfig for advanced generation
        use_advanced: Whether to use advanced generation
        
    Returns:
        Generated or improved text
    """
    if use_advanced and config:
        # Use advanced generation for the whole job, then extract the section
        job_body = render_job_body(job_title, config)
        section_map = {
            "description": job_body.job_description,
            "requirements": "\n".join(strip_bullet_prefix(r) for r in job_body.requirements),
            "duties": "\n".join(strip_bullet_prefix(d) for d in job_body.duties),
            "benefits": "\n".join(strip_bullet_prefix(b) for b in job_body.benefits),
            "footer": job_body.summary or "",
        }
        return section_map.get(section, current_value)
    else:
        # Use simple approach
        instructions = {
            "description": "Write a clear, attractive job description section as prose (not bullet points).",
            "requirements": "Write bullet points describing the key requirements for the role.",
            "duties": "Write bullet points describing the main responsibilities and daily tasks.",
            "benefits": "Write bullet points describing the main benefits for the candidate.",
            "footer": "Write a short closing sentence encouraging candidates to apply.",
        }
        instruction = instructions.get(section, "Improve this section.")
        return call_llm(instruction, current_value, context)


def _generate_simple_job_description(job_title: str) -> dict:
    """Fallback simple generation using call_llm."""
    context = {"job_headline": job_title}
    
    description = call_llm(
        "Write a clear, attractive job description section as prose (not bullet points).",
        "",
        context,
    )
    
    requirements = call_llm(
        "Write bullet points describing the key requirements for the role.",
        "",
        context,
    )
    
    duties = call_llm(
        "Write bullet points describing the main responsibilities and daily tasks.",
        "",
        context,
    )
    
    benefits = call_llm(
        "Write bullet points describing the main benefits for the candidate.",
        "",
        context,
    )
    
    footer = call_llm(
        "Write a short closing sentence encouraging candidates to apply.",
        "",
        context,
    )
    
    return {
        "job_description": description,
        "requirements": requirements,
        "duties": duties,
        "benefits": benefits,
        "footer": footer,
    }

