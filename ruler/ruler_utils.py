from typing import List, Tuple, Optional
import asyncio
import art
from art.rewards import ruler_score_group
from openai.types.chat.chat_completion import Choice
from openai.types.chat import ChatCompletionMessage

from models.job_models import JobBody, JobGenerationConfig
from generators.job_generator import generate_job_body_candidate_async
from logging_config import get_logger

logger = get_logger(__name__)


async def score_group_with_fallback(
    group: art.TrajectoryGroup,
    primary_model: str | None = None,
    fallback_model: str | None = None,
    *,
    debug: bool = False,
) -> Optional[art.TrajectoryGroup]:
    """Score trajectories with a primary model and fall back on parsing errors."""
    from config import MODEL_RULER_JUDGE, MODEL_RULER_JUDGE_FALLBACK
    
    # Use configured models if not provided
    if primary_model is None:
        primary_model = MODEL_RULER_JUDGE
    if fallback_model is None:
        fallback_model = MODEL_RULER_JUDGE_FALLBACK
    
    try:
        return await ruler_score_group(group, primary_model, debug=debug)
    except AssertionError as e:
        logger.warning(
            f"RULER scoring failed to parse scores for model '{primary_model}'. "
            f"Falling back to '{fallback_model}'. Error: {e}"
        )
        return await ruler_score_group(group, fallback_model, debug=debug)
    except Exception as e:
        logger.warning(
            f"RULER scoring failed for model '{primary_model}'. "
            f"Falling back to '{fallback_model}'. Error: {e}",
            exc_info=True,
        )
        return await ruler_score_group(group, fallback_model, debug=debug)


def jd_candidate_to_trajectory(
    job_title: str,
    cfg: JobGenerationConfig,
    job_body: JobBody,
) -> art.Trajectory:
    """
    Wrap a JobBody candidate as a trajectory for RULER.
    Messages:
      system: what the judge should care about
      user: config and job body
      assistant: the job body content that is being judged
    """

    system_msg = {
        "role": "system",
        "content": (
            "You are an expert HR quality judge. You evaluate job descriptions for clarity, "
            "tone, alignment with the requested role, and usefulness to candidates. "
            "You prefer job ads that are specific, concise, aligned with the seniority level, "
            "and realistic for the company type and industry."
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            "Evaluate the quality of the following job description.\n\n"
            f"Job title: {job_title}\n\n"
            f"Config JSON:\n{cfg.model_dump_json(indent=2, ensure_ascii=False)}\n\n"
            f"JobBody JSON:\n{job_body.model_dump_json(indent=2, ensure_ascii=False)}\n"
        ),
    }

    assistant_msg = ChatCompletionMessage(
        role="assistant",
        content=job_body.model_dump_json(indent=2, ensure_ascii=False),
    )

    choice = Choice(
        finish_reason="stop",
        index=0,
        message=assistant_msg,
    )

    traj = art.Trajectory(
        messages_and_choices=[system_msg, user_msg, choice],
        reward=0.0,
    )
    return traj


async def generate_best_job_body_with_ruler(
    job_title: str,
    cfg: JobGenerationConfig,
    num_candidates: int = 3,
    jitter: float = 0.1,
    judge_model: str | None = None,
) -> Tuple[JobBody, List[Tuple[float, JobBody]]]:
    """
    Generate multiple JobBody candidates and use ART RULER to pick the best one.

    Returns:
      best_job_body,
      list of (score, job_body) sorted by score descending.
    """
    from config import MODEL_RULER_JUDGE
    
    # Use configured model if not provided
    if judge_model is None:
        judge_model = MODEL_RULER_JUDGE
    """
    Generate multiple JobBody candidates and use ART RULER to pick the best one.

    Returns:
      best_job_body,
      list of (score, job_body) sorted by score descending.
    """

    # Sample candidates with small temperature jitter
    candidates: List[JobBody] = []
    if num_candidates <= 0:
        raise ValueError("num_candidates must be at least 1")

    offsets: List[float] = []
    center = num_candidates // 2
    for i in range(num_candidates):
        offsets.append((i - center) * jitter)

    # Generate candidates concurrently
    tasks = [
        generate_job_body_candidate_async(job_title, cfg, temp_jitter=offset)
        for offset in offsets
    ]
    candidates = await asyncio.gather(*tasks)

    # wrap as trajectories
    trajectories = [
        jd_candidate_to_trajectory(job_title, cfg, jb)
        for jb in candidates
    ]
    group = art.TrajectoryGroup(trajectories)

    # score with RULER
    # ruler_score_group expects a string model identifier.
    # We default to OpenRouter here; ensure OPENROUTER_API_KEY is set in the environment (loaded in config.py).
    judged_group = await score_group_with_fallback(group, judge_model, debug=False)
    if not judged_group:
        # graceful fallback
        return candidates[0], [(0.0, jb) for jb in candidates]

    # collect scores and sort
    scored: List[Tuple[float, JobBody]] = []
    for traj, jb in zip(judged_group.trajectories, candidates):
        scored.append((traj.reward, jb))

    scored_sorted = sorted(scored, key=lambda t: t[0], reverse=True)
    best_score, best_job_body = scored_sorted[0]

    logger.info("\n[JD RULER ranking]")
    for rank, (score, jb) in enumerate(scored_sorted, start=1):
        logger.info(f"Rank {rank} | score={score:.3f}")
        logger.debug(f"  job_description: {(jb.job_description or '')[:140]}...")

    return best_job_body, scored_sorted

