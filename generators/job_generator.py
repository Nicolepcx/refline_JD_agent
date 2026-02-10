from typing import List, Optional
import asyncio
from models.job_models import JobBody, JobGenerationConfig, StyleKit
from llm_service import get_base_llm


def explain_temperature(cfg: JobGenerationConfig) -> str:
    """Explain how the temperature was calculated for debugging."""
    parts = []

    base_map = {"formal": 0.2, "neutral": 0.35, "casual": 0.55}
    base = base_map[cfg.formality]
    parts.append(f"Base from formality='{cfg.formality}': {base:.2f}")

    # company type
    if cfg.company_type == "startup":
        base += 0.05
        parts.append("Company type 'startup' => +0.05")
    elif cfg.company_type == "public_sector":
        base -= 0.05
        parts.append("Company type 'public_sector' => -0.05")
    else:
        parts.append(f"Company type '{cfg.company_type}' => +0.00")

    # seniority
    if cfg.seniority_label in ["senior", "lead", "principal"]:
        base -= 0.05
        parts.append(f"Seniority '{cfg.seniority_label}' => -0.05")
    elif cfg.seniority_label in ["intern", "junior"]:
        base += 0.05
        parts.append(f"Seniority '{cfg.seniority_label}' => +0.05")
    else:
        parts.append("Seniority not set => +0.00")

    # industry
    if cfg.industry in ["finance", "healthcare", "public_it"]:
        base -= 0.05
        parts.append(f"Industry '{cfg.industry}' => -0.05")
    elif cfg.industry in ["ai_startup", "ecommerce"]:
        base += 0.05
        parts.append(f"Industry '{cfg.industry}' => +0.05")
    else:
        parts.append(f"Industry '{cfg.industry}' => +0.00")

    clamped = max(0.1, min(base, 0.75))
    if clamped != base:
        parts.append(f"Clamped to [0.10, 0.75] => {clamped:.2f}")
    else:
        parts.append(f"Final temperature => {clamped:.2f}")

    return "\n".join(parts)


###############################################################################
# ── Duty helpers (shared by sync + async renderers) ────────────────────────
###############################################################################

def _build_duties_prompt_section(
    duty_bullets: Optional[List[str]],
    duty_source: Optional[str],
    lang: str,
) -> str:
    """
    Build the context section that tells the LLM *what* duty bullets to use.

    Three tiers:
      1. duty_source == "user"     → user-provided keywords (highest priority)
      2. duty_source == "category" → matched from job-category vector DB
      3. duty_source is None / "llm" → let the LLM generate freely
    """
    if not duty_bullets:
        # Tier 3: no pre-filled duties – LLM generates
        if lang == "en":
            return (
                "No specific duty templates are available. "
                "Generate 5 to 8 realistic bullet points describing day-to-day "
                "responsibilities for this role, industry, and seniority level."
            )
        return (
            "Es liegen keine spezifischen Aufgabenvorlagen vor. "
            "Erstelle 5 bis 8 realistische Stichpunkte zu den täglichen Aufgaben "
            "passend zu Rolle, Branche und Seniorität."
        )

    tags = "\n".join(f"• {b}" for b in duty_bullets)

    if duty_source == "user":
        # Tier 1: user-typed keywords
        if lang == "en":
            return (
                "IMPORTANT — Duties (provided by the user):\n"
                f"{tags}\n"
                "You MUST use ONLY these duty bullet points. "
                "Expand each one into a full, grammatically correct sentence. "
                "Do NOT add any duties beyond this list."
            )
        return (
            "WICHTIG — Aufgaben (vom Nutzer vorgegeben):\n"
            f"{tags}\n"
            "Du MUSST AUSSCHLIESSLICH diese Aufgaben verwenden. "
            "Erweitere jeden Punkt zu einem vollständigen, grammatikalisch korrekten Satz. "
            "Füge KEINE weiteren Aufgaben hinzu."
        )

    # Tier 2: category template from vector DB
    if lang == "en":
        return (
            "Duties (matched from job-category templates — use as a strong guide):\n"
            f"{tags}\n"
            "Use these duty templates as the primary basis for the duties section. "
            "You may lightly rephrase for fluency but do NOT remove any of these "
            "duties and do NOT invent entirely new ones."
        )
    return (
        "Aufgaben (aus Jobkategorie-Vorlagen — als starke Orientierung verwenden):\n"
        f"{tags}\n"
        "Verwende diese Aufgabenvorlagen als Hauptgrundlage für den Aufgabenbereich. "
        "Leichte Umformulierungen sind erlaubt, aber entferne KEINE der genannten "
        "Aufgaben und erfinde KEINE völlig neuen."
    )


def _build_duties_instruction(
    duty_bullets: Optional[List[str]],
    duty_source: Optional[str],
    lang: str,
) -> str:
    """
    One-line instruction for the output-schema section of the prompt that
    tells the LLM how to fill the ``duties`` field.
    """
    if duty_bullets and duty_source in ("user", "category"):
        n = len(duty_bullets)
        if lang == "en":
            return (
                f"duties: Use EXACTLY the {n} duty bullet points provided above. "
                "Expand each into a polished sentence. Do NOT add extras."
            )
        return (
            f"duties: Verwende GENAU die {n} oben angegebenen Aufgabenpunkte. "
            "Erweitere jeden zu einem ausformulierten Satz. Füge KEINE weiteren hinzu."
        )
    # LLM-generate fallback
    if lang == "en":
        return "duties: 5 to 8 bullets describing day-to-day responsibilities."
    return "duties: 5 bis 8 Stichpunkte zu den täglichen Aufgaben."


def _post_process_duties(
    generated_duties: List[str],
    duty_bullets: List[str],
    duty_source: str,
) -> List[str]:
    """
    Post-process LLM-generated duties to enforce the provided bullets.

    If the source is "user" or "category", we map each provided bullet to the
    best-matching generated sentence (same fuzzy logic used for benefits).
    Falls back to the raw bullet if no good match is found.
    """
    if not duty_bullets:
        return generated_duties

    filtered: List[str] = []
    for bullet in duty_bullets:
        bullet_lower = bullet.lower().strip()
        best_match: Optional[str] = None
        best_score = 0.0

        for gen in generated_duties:
            gen_lower = gen.lower()
            if bullet_lower in gen_lower:
                score = 1.0
            elif any(
                word in gen_lower
                for word in bullet_lower.split()
                if len(word) > 3
            ):
                score = 0.5
            else:
                score = 0.0

            if score > best_score:
                best_score = score
                best_match = gen

        filtered.append(best_match if best_match and best_score > 0 else bullet)

    return filtered


###############################################################################


def render_job_body(
    job_title: str,
    cfg: JobGenerationConfig,
    temperature: float | None = None,
    gold_examples: List[str] | None = None,
    style_kit: Optional[StyleKit] = None,
    duty_bullets: Optional[List[str]] = None,
    duty_source: Optional[str] = None,
) -> JobBody:
    """
    Pure JD generator.
    Builds the prompt from JobGenerationConfig and returns a JobBody instance.
    No LangGraph state, no messages list, no JSON.
    
    Args:
        job_title: Job title
        cfg: Job generation configuration
        temperature: Optional temperature override
        gold_examples: Optional list of gold standard JSON strings for few-shot learning.
                      If None or empty, generation works without examples (fallback).
        style_kit: Optional StyleKit from the Style Router (Motivkompass).
                   When present, its prompt block is injected to guide tone, adjectives,
                   hooks, and sentence structure.  When absent, generation works fine
                   using the existing tone/formality system.
        duty_bullets: Pre-resolved duty bullet points from the 3-tier cascade
                     (user input → category match → empty for LLM fallback).
        duty_source: Source of duty_bullets: "user", "category", or "llm".
    
    Context Engineering for MAS:
    - Gold examples are added as few-shot examples when available
    - Examples guide style/structure but content is adapted to current job
    - Falls back gracefully when no gold standards exist
    - StyleKit (when provided) is injected as a dedicated prompt section
    - Duty cascade: user duties > category template > LLM generation
    """
    cfg = cfg.with_industry_defaults()
    lang = cfg.language
    temp = temperature if temperature is not None else cfg.temperature

    base_llm = get_base_llm()
    writer_model = base_llm.with_structured_output(JobBody).bind(
        temperature=temp
    )

    # tone line
    if lang == "en":
        tone_map = {
            "casual": "Use a friendly modern tone, but stay professional.",
            "neutral": "Use a clear neutral professional tone.",
            "formal": "Use a formal corporate tone.",
        }
    else:
        tone_map = {
            "casual": "Verwende einen freundlichen modernen, aber professionellen Ton.",
            "neutral": "Verwende einen klaren sachlich professionellen Ton.",
            "formal": "Verwende einen formellen, eher konservativen Ton.",
        }
    tone_line = tone_map[cfg.formality]

    # company type line
    if lang == "en":
        type_map = {
            "startup": "The company is a young startup with a fast paced environment.",
            "scaleup": "The company is a growing scaleup with an established product.",
            "corporate": "The company is a larger established company.",
            "public_sector": "The organization operates in the public sector.",
            "agency": "The company is a digital agency working for multiple clients.",
            "consulting": "The company is a consulting firm that delivers client projects.",
        }
    else:
        type_map = {
            "startup": "Das Unternehmen ist ein junges Startup mit dynamischem Umfeld.",
            "scaleup": "Das Unternehmen ist ein wachsendes Scaleup mit etabliertem Produkt.",
            "corporate": "Das Unternehmen ist ein größeres etabliertes Unternehmen.",
            "public_sector": "Die Organisation ist im öffentlichen Sektor tätig.",
            "agency": "Das Unternehmen ist eine Agentur mit verschiedenen Kundenprojekten.",
            "consulting": "Das Unternehmen ist ein Beratungsunternehmen mit vielfältigen Kundenprojekten.",
        }
    company_line = type_map[cfg.company_type]

    # seniority line
    seniority_bits: List[str] = []
    if cfg.seniority_label:
        if lang == "en":
            seniority_bits.append(f"The role is a {cfg.seniority_label} level position.")
        else:
            seniority_bits.append(f"Die Rolle ist auf {cfg.seniority_label} Level ausgerichtet.")
    if cfg.min_years_experience is not None:
        if lang == "en":
            if cfg.max_years_experience:
                seniority_bits.append(
                    f"Target experience range is {cfg.min_years_experience} to {cfg.max_years_experience} years."
                )
            else:
                seniority_bits.append(
                    f"Target experience is at least {cfg.min_years_experience} years."
                )
        else:
            if cfg.max_years_experience:
                seniority_bits.append(
                    f"Die gewünschte Erfahrung liegt zwischen {cfg.min_years_experience} und {cfg.max_years_experience} Jahren."
                )
            else:
                seniority_bits.append(
                    f"Gesucht werden Kandidatinnen und Kandidaten mit mindestens {cfg.min_years_experience} Jahren Berufserfahrung."
                )
    seniority_line = " ".join(seniority_bits)

    # skills line
    skills_text = ", ".join([s.name for s in cfg.skills]) if cfg.skills else ""
    if lang == "en":
        skills_line = (
            f"Required core skills: {skills_text}."
            if skills_text
            else "Infer reasonable skills for this job title and industry."
        )
    else:
        skills_line = (
            f"Zentrale Skills: {skills_text}."
            if skills_text
            else "Ergänze sinnvolle Skills passend zu Titel und Branche."
        )

    # benefits line - STRICT: Only use provided keywords, no additions
    # IMPORTANT: Expand keywords into full, grammatically correct sentences (like skills)
    benefit_tags = ", ".join(cfg.benefit_keywords) if cfg.benefit_keywords else ""
    if lang == "en":
        if benefit_tags:
            benefits_line = (
                "IMPORTANT: For benefits, you MUST ONLY use these exact benefit keywords: {benefit_tags}. "
                "Expand each keyword into a full, grammatically correct sentence. "
                "For example: 'remote work switzerland' should become 'Remote work in Switzerland' or 'Remote work opportunities in Switzerland'. "
                "Each benefit must be a complete sentence, not just a phrase. "
                "Do NOT add any other benefits beyond these keywords. "
                "Create exactly one bullet point per keyword provided."
            ).format(benefit_tags=benefit_tags)
        else:
            # If no benefit keywords provided, return empty benefits
            benefits_line = (
                "IMPORTANT: No benefit keywords were provided. The benefits field must be an empty list []."
            )
    else:
        if benefit_tags:
            benefits_line = (
                "WICHTIG: Für Benefits musst du AUSSCHLIESSLICH diese genannten Benefit Stichworte verwenden: {benefit_tags}. "
                "Erweitere jedes Stichwort zu einem vollständigen, grammatikalisch korrekten Satz. "
                "Zum Beispiel: 'Remote Work Schweiz' sollte zu 'Remote Work in der Schweiz' oder 'Remote Work Möglichkeiten in der Schweiz' werden. "
                "Jeder Benefit muss ein vollständiger Satz sein, nicht nur eine Phrase. "
                "Füge KEINE weiteren Benefits hinzu außer diesen Stichwörtern. "
                "Erstelle genau einen Bullet Point pro angegebenem Stichwort."
            ).format(benefit_tags=benefit_tags)
        else:
            benefits_line = (
                "WICHTIG: Es wurden keine Benefit Stichworte angegeben. Das Benefits Feld muss eine leere Liste [] sein."
            )

    # Duties line — 3-tier cascade: user > category template > LLM fallback
    duties_line = _build_duties_prompt_section(duty_bullets, duty_source, lang)

    # Build few-shot examples from gold standards if available (with proper fallback)
    examples_section = ""
    if gold_examples and len(gold_examples) > 0:
        # Validate gold examples are valid JSON strings
        valid_examples = []
        for example_json in gold_examples[:2]:  # Use up to 2 examples
            if example_json and isinstance(example_json, str) and len(example_json.strip()) > 0:
                try:
                    # Validate it's valid JSON
                    import json
                    json.loads(example_json)
                    valid_examples.append(example_json)
                except (json.JSONDecodeError, TypeError):
                    # Skip invalid examples
                    continue
        
        if valid_examples:
            if lang == "en":
                examples_section = "\n\n## Examples of Previous Successful Job Descriptions (for reference on style and structure):\n\n"
                for i, example_json in enumerate(valid_examples, 1):
                    examples_section += f"Example {i}:\n{example_json}\n\n"
                examples_section += "Note: Use these examples as a guide for style, tone, and structure, but adapt the content to match the current job title and requirements. Do not copy verbatim.\n\n"
            else:
                examples_section = "\n\n## Beispiele früherer erfolgreicher Stellenbeschreibungen (als Referenz für Stil und Struktur):\n\n"
                for i, example_json in enumerate(valid_examples, 1):
                    examples_section += f"Beispiel {i}:\n{example_json}\n\n"
                examples_section += "Hinweis: Verwende diese Beispiele als Leitfaden für Stil, Ton und Struktur, passe aber den Inhalt an den aktuellen Stellentitel und die Anforderungen an. Nicht wörtlich kopieren.\n\n"
    # If no valid gold examples, examples_section remains empty (fallback - works without gold standards)
    
    # Style kit section (Motivkompass) — injected when available, ignored otherwise
    style_section = ""
    if style_kit is not None:
        style_section = "\n\n" + style_kit.to_prompt_block(lang) + "\n\n"
    
    # prompt
    if lang == "en":
        prompt = (
            "You are an experienced HR copywriter for a recruitment platform.\n"
            f"{tone_line}\n"
            f"{company_line}\n"
            f"{seniority_line}\n"
            f"{skills_line}\n"
            f"{benefits_line}\n"
            f"{duties_line}\n"
            f"{style_section}"
            f"{examples_section}"
            f"Job title: {job_title}\n\n"
            "Produce a JobBody instance in English.\n"
            "job_description: 2 to 4 sentences for role and context.\n"
            "requirements: 6 to 10 bullets matching seniority and skills.\n"
            "benefits: ONLY use the benefit keywords provided above. Expand each keyword into a full, grammatically correct sentence (like 'Remote work in Switzerland' from 'remote work switzerland'). Create exactly one bullet per keyword. Do NOT add any other benefits.\n"
            f"{_build_duties_instruction(duty_bullets, duty_source, 'en')}\n"
            "summary: 1 short closing line inviting candidates to apply.\n"
        )
    else:
        prompt = (
            "Du bist eine erfahrene HR Texterin für eine Recruiting Plattform.\n"
            f"{tone_line}\n"
            f"{company_line}\n"
            f"{seniority_line}\n"
            f"{skills_line}\n"
            f"{benefits_line}\n"
            f"{duties_line}\n"
            f"{style_section}"
            f"{examples_section}"
            f"Stellentitel: {job_title}\n\n"
            "Erstelle eine JobBody Struktur auf Deutsch.\n"
            "job_description: 2 bis 4 Sätze zu Rolle und Kontext.\n"
            "requirements: 6 bis 10 Stichpunkte, passend zur Seniorität und zu den Skills.\n"
            "benefits: Verwende AUSSCHLIESSLICH die oben angegebenen Benefit Stichworte. Erweitere jedes Stichwort zu einem vollständigen, grammatikalisch korrekten Satz (z.B. 'Remote Work in der Schweiz' aus 'Remote Work Schweiz'). Erstelle genau einen Bullet Point pro Stichwort. Füge KEINE weiteren Benefits hinzu.\n"
            f"{_build_duties_instruction(duty_bullets, duty_source, 'de')}\n"
            "summary: 1 kurzer Abschlusssatz, der zur Bewerbung einlädt.\n"
        )

    payload: JobBody = writer_model.invoke(prompt)
    
    # Post-process duties: if we had pre-filled duties (tier 1 or 2), enforce them
    if duty_bullets and duty_source in ("user", "category"):
        payload.duties = _post_process_duties(payload.duties, duty_bullets, duty_source)

    # Post-process benefits to ensure ONLY the provided keywords are used
    # Enforce: exactly one benefit per keyword, no more, no less
    if cfg.benefit_keywords:
        # Map each keyword to the best matching generated benefit
        filtered_benefits = []
        benefit_keywords_lower = [kw.lower().strip() for kw in cfg.benefit_keywords]
        
        # For each keyword, find the best matching benefit from LLM output
        for keyword in cfg.benefit_keywords:
            keyword_lower = keyword.lower().strip()
            best_match = None
            best_match_score = 0
            
            for benefit in payload.benefits:
                benefit_lower = benefit.lower()
                # Score: 1 if keyword is in benefit, 0.5 if benefit contains keyword-related words
                if keyword_lower in benefit_lower:
                    score = 1.0
                elif any(word in benefit_lower for word in keyword_lower.split() if len(word) > 3):
                    score = 0.5
                else:
                    score = 0.0
                
                if score > best_match_score:
                    best_match_score = score
                    best_match = benefit
            
            # Use the matched benefit, or fallback to the keyword itself
            if best_match and best_match_score > 0:
                filtered_benefits.append(best_match)
            else:
                # Fallback: use keyword as-is (LLM didn't generate a matching benefit)
                filtered_benefits.append(keyword)
        
        payload.benefits = filtered_benefits
    else:
        # If no benefit keywords provided, ensure benefits list is empty
        payload.benefits = []
    
    return payload


def generate_job_body_candidate(
    job_title: str,
    cfg: JobGenerationConfig,
    temp_jitter: float = 0.0,
    gold_examples: List[str] | None = None,
    style_kit: Optional[StyleKit] = None,
    duty_bullets: Optional[List[str]] = None,
    duty_source: Optional[str] = None,
) -> JobBody:
    """Use the same logic as the graph, with a slightly adjusted temperature."""
    base_temp = cfg.temperature
    temp = max(0.1, min(base_temp + temp_jitter, 0.9))
    return render_job_body(
        job_title, cfg, temperature=temp, gold_examples=gold_examples,
        style_kit=style_kit, duty_bullets=duty_bullets, duty_source=duty_source,
    )


async def render_job_body_async(
    job_title: str,
    cfg: JobGenerationConfig,
    temperature: float | None = None,
    gold_examples: List[str] | None = None,
    style_kit: Optional[StyleKit] = None,
    duty_bullets: Optional[List[str]] = None,
    duty_source: Optional[str] = None,
) -> JobBody:
    """
    Async version of render_job_body that uses ainvoke for true parallel execution.
    This allows multiple candidates to be generated concurrently without blocking.
    Creates a fresh LLM instance for each call to avoid connection pool contention.
    """
    from langchain_openai import ChatOpenAI
    from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, MODEL_BASE
    
    cfg = cfg.with_industry_defaults()
    lang = cfg.language
    temp = temperature if temperature is not None else cfg.temperature

    # Create a fresh LLM instance for this call to avoid connection pool contention
    # This ensures true parallelism when multiple calls happen simultaneously
    # Optimize for latency with provider routing + disable thinking for Qwen models
    from llm_service import _get_extra_body_for_model
    extra_body = _get_extra_body_for_model(MODEL_BASE)
    
    base_llm = ChatOpenAI(
        model=MODEL_BASE,
        temperature=0,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        extra_body=extra_body,
    )
    writer_model = base_llm.with_structured_output(JobBody).bind(
        temperature=temp
    )

    # tone line
    if lang == "en":
        tone_map = {
            "casual": "Use a friendly modern tone, but stay professional.",
            "neutral": "Use a clear neutral professional tone.",
            "formal": "Use a formal corporate tone.",
        }
    else:
        tone_map = {
            "casual": "Verwende einen freundlichen modernen, aber professionellen Ton.",
            "neutral": "Verwende einen klaren sachlich professionellen Ton.",
            "formal": "Verwende einen formellen, eher konservativen Ton.",
        }
    tone_line = tone_map[cfg.formality]

    # company type line
    if lang == "en":
        type_map = {
            "startup": "The company is a young startup with a fast paced environment.",
            "scaleup": "The company is a growing scaleup with an established product.",
            "corporate": "The company is a larger established company.",
            "public_sector": "The organization operates in the public sector.",
            "agency": "The company is a digital agency working for multiple clients.",
            "consulting": "The company is a consulting firm that delivers client projects.",
        }
    else:
        type_map = {
            "startup": "Das Unternehmen ist ein junges Startup mit dynamischem Umfeld.",
            "scaleup": "Das Unternehmen ist ein wachsendes Scaleup mit etabliertem Produkt.",
            "corporate": "Das Unternehmen ist ein größeres etabliertes Unternehmen.",
            "public_sector": "Die Organisation ist im öffentlichen Sektor tätig.",
            "agency": "Das Unternehmen ist eine Agentur mit verschiedenen Kundenprojekten.",
            "consulting": "Das Unternehmen ist ein Beratungsunternehmen mit vielfältigen Kundenprojekten.",
        }
    company_line = type_map[cfg.company_type]

    # seniority line
    seniority_bits: List[str] = []
    if cfg.seniority_label:
        if lang == "en":
            seniority_bits.append(f"The role is a {cfg.seniority_label} level position.")
        else:
            seniority_bits.append(f"Die Rolle ist auf {cfg.seniority_label} Level ausgerichtet.")
    if cfg.min_years_experience is not None:
        if lang == "en":
            if cfg.max_years_experience:
                seniority_bits.append(
                    f"Target experience range is {cfg.min_years_experience} to {cfg.max_years_experience} years."
                )
            else:
                seniority_bits.append(
                    f"Target experience is at least {cfg.min_years_experience} years."
                )
        else:
            if cfg.max_years_experience:
                seniority_bits.append(
                    f"Die gewünschte Erfahrung liegt zwischen {cfg.min_years_experience} und {cfg.max_years_experience} Jahren."
                )
            else:
                seniority_bits.append(
                    f"Gesucht werden Kandidatinnen und Kandidaten mit mindestens {cfg.min_years_experience} Jahren Berufserfahrung."
                )
    seniority_line = " ".join(seniority_bits)

    # skills line
    skills_text = ", ".join([s.name for s in cfg.skills]) if cfg.skills else ""
    if lang == "en":
        skills_line = (
            f"Required core skills: {skills_text}."
            if skills_text
            else "Infer reasonable skills for this job title and industry."
        )
    else:
        skills_line = (
            f"Zentrale Skills: {skills_text}."
            if skills_text
            else "Ergänze sinnvolle Skills passend zu Titel und Branche."
        )

    # benefits line - STRICT: Only use provided keywords, no additions
    # IMPORTANT: Expand keywords into full, grammatically correct sentences (like skills)
    benefit_tags = ", ".join(cfg.benefit_keywords) if cfg.benefit_keywords else ""
    if lang == "en":
        if benefit_tags:
            benefits_line = (
                "IMPORTANT: For benefits, you MUST ONLY use these exact benefit keywords: {benefit_tags}. "
                "Expand each keyword into a full, grammatically correct sentence. "
                "For example: 'remote work switzerland' should become 'Remote work in Switzerland' or 'Remote work opportunities in Switzerland'. "
                "Each benefit must be a complete sentence, not just a phrase. "
                "Do NOT add any other benefits beyond these keywords. "
                "Create exactly one bullet point per keyword provided."
            ).format(benefit_tags=benefit_tags)
        else:
            # If no benefit keywords provided, return empty benefits
            benefits_line = (
                "IMPORTANT: No benefit keywords were provided. The benefits field must be an empty list []."
            )
    else:
        if benefit_tags:
            benefits_line = (
                "WICHTIG: Für Benefits musst du AUSSCHLIESSLICH diese genannten Benefit Stichworte verwenden: {benefit_tags}. "
                "Erweitere jedes Stichwort zu einem vollständigen, grammatikalisch korrekten Satz. "
                "Zum Beispiel: 'Remote Work Schweiz' sollte zu 'Remote Work in der Schweiz' oder 'Remote Work Möglichkeiten in der Schweiz' werden. "
                "Jeder Benefit muss ein vollständiger Satz sein, nicht nur eine Phrase. "
                "Füge KEINE weiteren Benefits hinzu außer diesen Stichwörtern. "
                "Erstelle genau einen Bullet Point pro angegebenem Stichwort."
            ).format(benefit_tags=benefit_tags)
        else:
            benefits_line = (
                "WICHTIG: Es wurden keine Benefit Stichworte angegeben. Das Benefits Feld muss eine leere Liste [] sein."
            )

    # Duties line — 3-tier cascade (same logic as sync version)
    duties_line = _build_duties_prompt_section(duty_bullets, duty_source, lang)

    # Build few-shot examples from gold standards if available (with proper fallback)
    examples_section = ""
    if gold_examples and len(gold_examples) > 0:
        # Validate gold examples are valid JSON strings
        valid_examples = []
        for example_json in gold_examples[:2]:  # Use up to 2 examples
            if example_json and isinstance(example_json, str) and len(example_json.strip()) > 0:
                try:
                    # Validate it's valid JSON
                    import json
                    json.loads(example_json)
                    valid_examples.append(example_json)
                except (json.JSONDecodeError, TypeError):
                    # Skip invalid examples
                    continue
        
        if valid_examples:
            if lang == "en":
                examples_section = "\n\n## Examples of Previous Successful Job Descriptions (for reference on style and structure):\n\n"
                for i, example_json in enumerate(valid_examples, 1):
                    examples_section += f"Example {i}:\n{example_json}\n\n"
                examples_section += "Note: Use these examples as a guide for style, tone, and structure, but adapt the content to match the current job title and requirements. Do not copy verbatim.\n\n"
            else:
                examples_section = "\n\n## Beispiele früherer erfolgreicher Stellenbeschreibungen (als Referenz für Stil und Struktur):\n\n"
                for i, example_json in enumerate(valid_examples, 1):
                    examples_section += f"Beispiel {i}:\n{example_json}\n\n"
                examples_section += "Hinweis: Verwende diese Beispiele als Leitfaden für Stil, Ton und Struktur, passe aber den Inhalt an den aktuellen Stellentitel und die Anforderungen an. Nicht wörtlich kopieren.\n\n"
    # If no valid gold examples, examples_section remains empty (fallback - works without gold standards)
    
    # Style kit section (Motivkompass) — injected when available, ignored otherwise
    style_section = ""
    if style_kit is not None:
        style_section = "\n\n" + style_kit.to_prompt_block(lang) + "\n\n"
    
    # prompt
    if lang == "en":
        prompt = (
            "You are an experienced HR copywriter for a recruitment platform.\n"
            f"{tone_line}\n"
            f"{company_line}\n"
            f"{seniority_line}\n"
            f"{skills_line}\n"
            f"{benefits_line}\n"
            f"{duties_line}\n"
            f"{style_section}"
            f"{examples_section}"
            f"Job title: {job_title}\n\n"
            "Produce a JobBody instance in English.\n"
            "job_description: 2 to 4 sentences for role and context.\n"
            "requirements: 6 to 10 bullets matching seniority and skills.\n"
            "benefits: ONLY use the benefit keywords provided above. Expand each keyword into a full, grammatically correct sentence (like 'Remote work in Switzerland' from 'remote work switzerland'). Create exactly one bullet per keyword. Do NOT add any other benefits.\n"
            f"{_build_duties_instruction(duty_bullets, duty_source, 'en')}\n"
            "summary: 1 short closing line inviting candidates to apply.\n"
        )
    else:
        prompt = (
            "Du bist eine erfahrene HR Texterin für eine Recruiting Plattform.\n"
            f"{tone_line}\n"
            f"{company_line}\n"
            f"{seniority_line}\n"
            f"{skills_line}\n"
            f"{benefits_line}\n"
            f"{duties_line}\n"
            f"{style_section}"
            f"{examples_section}"
            f"Stellentitel: {job_title}\n\n"
            "Erstelle eine JobBody Struktur auf Deutsch.\n"
            "job_description: 2 bis 4 Sätze zu Rolle und Kontext.\n"
            "requirements: 6 bis 10 Stichpunkte, passend zur Seniorität und zu den Skills.\n"
            "benefits: Verwende AUSSCHLIESSLICH die oben angegebenen Benefit Stichworte. Erweitere jedes Stichwort zu einem vollständigen, grammatikalisch korrekten Satz (z.B. 'Remote Work in der Schweiz' aus 'Remote Work Schweiz'). Erstelle genau einen Bullet Point pro Stichwort. Füge KEINE weiteren Benefits hinzu.\n"
            f"{_build_duties_instruction(duty_bullets, duty_source, 'de')}\n"
            "summary: 1 kurzer Abschlusssatz, der zur Bewerbung einlädt.\n"
        )

    # Use ainvoke for true async execution
    payload: JobBody = await writer_model.ainvoke(prompt)
    
    # Post-process duties: if we had pre-filled duties (tier 1 or 2), enforce them
    if duty_bullets and duty_source in ("user", "category"):
        payload.duties = _post_process_duties(payload.duties, duty_bullets, duty_source)

    # Post-process benefits to ensure ONLY the provided keywords are used
    # Enforce: exactly one benefit per keyword, no more, no less
    if cfg.benefit_keywords:
        # Map each keyword to the best matching generated benefit
        filtered_benefits = []
        benefit_keywords_lower = [kw.lower().strip() for kw in cfg.benefit_keywords]
        
        # For each keyword, find the best matching benefit from LLM output
        for keyword in cfg.benefit_keywords:
            keyword_lower = keyword.lower().strip()
            best_match = None
            best_match_score = 0
            
            for benefit in payload.benefits:
                benefit_lower = benefit.lower()
                # Score: 1 if keyword is in benefit, 0.5 if benefit contains keyword-related words
                if keyword_lower in benefit_lower:
                    score = 1.0
                elif any(word in benefit_lower for word in keyword_lower.split() if len(word) > 3):
                    score = 0.5
                else:
                    score = 0.0
                
                if score > best_match_score:
                    best_match_score = score
                    best_match = benefit
            
            # Use the matched benefit, or fallback to the keyword itself
            if best_match and best_match_score > 0:
                filtered_benefits.append(best_match)
            else:
                # Fallback: use keyword as-is (LLM didn't generate a matching benefit)
                filtered_benefits.append(keyword)
        
        payload.benefits = filtered_benefits
    else:
        # If no benefit keywords provided, ensure benefits list is empty
        payload.benefits = []
    
    return payload


async def generate_job_body_candidate_async(
    job_title: str,
    cfg: JobGenerationConfig,
    temp_jitter: float = 0.0,
    gold_examples: List[str] | None = None,
    style_kit: Optional[StyleKit] = None,
    duty_bullets: Optional[List[str]] = None,
    duty_source: Optional[str] = None,
) -> JobBody:
    """Async version that uses ainvoke for true parallel execution."""
    base_temp = cfg.temperature
    temp = max(0.1, min(base_temp + temp_jitter, 0.9))
    return await render_job_body_async(
        job_title, cfg, temperature=temp, gold_examples=gold_examples,
        style_kit=style_kit, duty_bullets=duty_bullets, duty_source=duty_source,
    )

