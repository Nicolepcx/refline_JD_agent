"""
Style Kit Retriever — assembles a compact StyleKit from RAG or defaults.

The retriever queries the vector store for style chunks (hooks, adjectives,
syntax rules, do/don't) filtered by Motivkompass color and dimension.

If the vector store is unavailable or empty, it falls back to hardcoded
defaults that are functional out of the box.

See AGENTS.md §2 for the workflow contract.
"""

from __future__ import annotations

from typing import Optional

from models.job_models import StyleProfile, StyleKit
from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Hardcoded fallback defaults per Motivkompass color
# ---------------------------------------------------------------------------
# These provide a working baseline before PDF ingestion into RAG.
# German defaults included where the primary use-case is de job ads.

_DEFAULTS: dict[str, dict[str, list[str]]] = {
    "red": {
        "do_and_dont": [
            "DO: Use direct, action-oriented language",
            "DO: Highlight impact, results, and growth potential",
            "DO: Emphasize speed, autonomy, and decision-making power",
            "DO: Show career acceleration and status markers",
            "DON'T: Use passive voice or hedging language",
            "DON'T: Overload with process descriptions or committee talk",
        ],
        "adjectives": [
            "ambitious", "driven", "high-impact", "strategic",
            "results-oriented", "decisive", "competitive", "dynamic",
            "performance-focused", "autonomous",
        ],
        "hooks": [
            "Lead. Build. Deliver.",
            "Ready to make an impact?",
            "Your next career move starts here.",
        ],
        "syntax": [
            "Short declarative sentences — subject-verb-object",
            "Active voice throughout",
            "Imperative allowed for calls to action",
            "Avoid subordinate clauses and qualifiers",
        ],
    },
    "yellow": {
        "do_and_dont": [
            "DO: Emphasize creativity, freedom, and team spirit",
            "DO: Use energetic, approachable language",
            "DO: Highlight variety, innovation, and personal growth",
            "DO: Show the fun side of the work environment",
            "DON'T: Be overly formal or bureaucratic",
            "DON'T: Use rigid or controlling language",
        ],
        "adjectives": [
            "creative", "flexible", "collaborative", "innovative",
            "dynamic", "inspiring", "open-minded", "energetic",
            "versatile", "enthusiastic",
        ],
        "hooks": [
            "Shape the future with us!",
            "Your creativity. Our platform.",
            "Where ideas come to life.",
        ],
        "syntax": [
            "Conversational tone, varied sentence length",
            "Questions and exclamations are welcome",
            "First and second person address ('you', 'we')",
            "Mix short punchy lines with flowing descriptions",
        ],
    },
    "green": {
        "do_and_dont": [
            "DO: Emphasize team, belonging, and work-life balance",
            "DO: Use warm, inclusive language",
            "DO: Highlight stability, trust, and mutual support",
            "DO: Show care for employee wellbeing",
            "DON'T: Use aggressive or competitive framing",
            "DON'T: Over-promise or use hype",
        ],
        "adjectives": [
            "supportive", "reliable", "inclusive", "caring",
            "balanced", "trustworthy", "collaborative", "stable",
            "harmonious", "community-oriented",
        ],
        "hooks": [
            "Become part of our team.",
            "A place where you belong.",
            "Growing together — at your pace.",
        ],
        "syntax": [
            "Longer, connecting sentences with smooth flow",
            "Conditional and inclusive phrasing ('together', 'we support')",
            "Avoid pressure language or ultimatums",
            "Warm closings that invite rather than demand",
        ],
    },
    "blue": {
        "do_and_dont": [
            "DO: Use facts, specifics, and evidence",
            "DO: Emphasize quality, structure, and expertise",
            "DO: Back claims with numbers or concrete examples",
            "DO: Show methodological rigor and clear processes",
            "DON'T: Use vague superlatives without backing",
            "DON'T: Use emotional manipulation or pressure",
        ],
        "adjectives": [
            "analytical", "structured", "expert", "precise",
            "thorough", "systematic", "methodical", "evidence-based",
            "quality-driven", "detail-oriented",
        ],
        "hooks": [
            "Excellence through expertise.",
            "Built on quality. Driven by data.",
            "Precision matters — and so do you.",
        ],
        "syntax": [
            "Clear topic sentences followed by evidence",
            "Precise, factual language — no filler words",
            "Numbered or structured lists where appropriate",
            "Professional but not cold — factual warmth",
        ],
    },
}

# German equivalents for de job ads
_DEFAULTS_DE: dict[str, dict[str, list[str]]] = {
    "red": {
        "do_and_dont": [
            "TUN: Direkte, handlungsorientierte Sprache verwenden",
            "TUN: Wirkung, Ergebnisse und Wachstumspotenzial hervorheben",
            "TUN: Geschwindigkeit, Autonomie und Entscheidungskraft betonen",
            "NICHT: Passive Formulierungen oder abschwächende Sprache",
            "NICHT: Prozessbeschreibungen oder Gremien-Sprache überladen",
        ],
        "adjectives": [
            "ambitioniert", "leistungsstark", "zielstrebig",
            "ergebnisorientiert", "strategisch", "entschlossen",
            "wettbewerbsfähig", "dynamisch", "eigenverantwortlich",
        ],
        "hooks": [
            "Gestalten Sie Ihre Karriere – mit echtem Einfluss.",
            "Bereit für den nächsten Schritt?",
            "Führen. Umsetzen. Bewegen.",
        ],
        "syntax": [
            "Kurze, direkte Sätze – Subjekt-Verb-Objekt",
            "Durchgehend aktive Formulierungen",
            "Imperativ für Handlungsaufforderungen erlaubt",
        ],
    },
    "yellow": {
        "do_and_dont": [
            "TUN: Kreativität, Freiheit und Teamgeist betonen",
            "TUN: Energische, nahbare Sprache verwenden",
            "TUN: Vielfalt, Innovation und persönliches Wachstum zeigen",
            "NICHT: Zu formell oder bürokratisch formulieren",
            "NICHT: Starre oder kontrollierende Sprache verwenden",
        ],
        "adjectives": [
            "kreativ", "flexibel", "innovativ", "inspirierend",
            "offen", "vielseitig", "begeisternd", "dynamisch",
        ],
        "hooks": [
            "Gestalte die Zukunft mit uns!",
            "Deine Kreativität. Unsere Plattform.",
            "Wo Ideen lebendig werden.",
        ],
        "syntax": [
            "Lockerer Ton, abwechslungsreiche Satzlänge",
            "Fragen und Ausrufe willkommen",
            "Direkte Ansprache ('du', 'wir')",
        ],
    },
    "green": {
        "do_and_dont": [
            "TUN: Team, Zugehörigkeit und Work-Life-Balance betonen",
            "TUN: Warme, inklusive Sprache verwenden",
            "TUN: Stabilität, Vertrauen und gegenseitige Unterstützung zeigen",
            "NICHT: Aggressive oder wettbewerbsorientierte Formulierungen",
            "NICHT: Übertreiben oder Hype verwenden",
        ],
        "adjectives": [
            "unterstützend", "verlässlich", "inklusiv", "fürsorglich",
            "ausgewogen", "vertrauenswürdig", "harmonisch", "stabil",
        ],
        "hooks": [
            "Werden Sie Teil unseres Teams.",
            "Ein Ort, an dem Sie dazugehören.",
            "Gemeinsam wachsen – in Ihrem Tempo.",
        ],
        "syntax": [
            "Längere, verbindende Sätze mit sanftem Fluss",
            "Konditionale und inklusive Formulierungen ('gemeinsam', 'wir unterstützen')",
            "Keine Druck-Sprache oder Ultimaten",
        ],
    },
    "blue": {
        "do_and_dont": [
            "TUN: Fakten, Konkretisierungen und Belege verwenden",
            "TUN: Qualität, Struktur und Expertise betonen",
            "TUN: Aussagen mit Zahlen oder konkreten Beispielen untermauern",
            "NICHT: Unspezifische Superlative ohne Beleg verwenden",
            "NICHT: Emotionale Manipulation oder Drucksprache",
        ],
        "adjectives": [
            "analytisch", "strukturiert", "fachkundig", "präzise",
            "gründlich", "systematisch", "methodisch", "qualitätsorientiert",
        ],
        "hooks": [
            "Exzellenz durch Expertise.",
            "Aufgebaut auf Qualität. Angetrieben durch Daten.",
            "Präzision zählt – und Sie auch.",
        ],
        "syntax": [
            "Klare Leitsätze gefolgt von Belegen",
            "Präzise, faktische Sprache – keine Füllwörter",
            "Nummerierte oder strukturierte Listen wo sinnvoll",
        ],
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def retrieve_style_kit(
    profile: StyleProfile,
    lang: str = "en",
    vector_store: Optional[object] = None,
) -> StyleKit:
    """
    Assemble a StyleKit for the given profile.

    Tries RAG retrieval first (if vector_store is available and has style data).
    Falls back to hardcoded defaults if RAG is empty or unavailable.

    Args:
        profile: The StyleProfile from the Style Router.
        lang: Language code ("en" or "de").
        vector_store: Optional VectorStoreManager instance.

    Returns:
        A populated StyleKit ready for prompt injection.
    """
    kit = StyleKit(profile=profile)

    # ── Try RAG retrieval ──
    if vector_store is not None:
        try:
            filled = _fill_from_rag(kit, profile, vector_store)
            if filled:
                logger.info(
                    f"[Style Retriever] RAG: {len(kit.do_and_dont)} rules, "
                    f"{len(kit.preferred_adjectives)} adj, "
                    f"{len(kit.hook_templates)} hooks, "
                    f"{len(kit.syntax_constraints)} syntax"
                )
                return kit
        except Exception as e:
            logger.warning(f"[Style Retriever] RAG retrieval failed, using defaults: {e}")

    # ── Fallback: hardcoded defaults ──
    _fill_defaults(kit, profile, lang)
    logger.info(
        f"[Style Retriever] Defaults ({lang}): "
        f"primary={profile.primary_color} "
        f"secondary={profile.secondary_color or 'none'}"
    )
    return kit


# ---------------------------------------------------------------------------
# RAG retrieval (uses existing VectorStoreManager)
# ---------------------------------------------------------------------------

def _fill_from_rag(kit: StyleKit, profile: StyleProfile, vs: object) -> bool:
    """
    Query vector store for style chunks by color + dimension.
    Returns True if at least some data was found.

    Style data is stored under company_name = "style_{color}" with metadata:
      - profile_color: red | yellow | green | blue | any
      - dimension: hooks | adjectives | syntax | do_dont
      - language: de | en
      - mode (optional): proaktiv | reaktiv  (for syntax chunks)
    """
    # Import here to avoid circular imports
    from services.vector_store import VectorStoreManager

    if not isinstance(vs, VectorStoreManager) or not vs.is_available():
        return False

    found_anything = False
    colors = [profile.primary_color]
    if profile.secondary_color:
        colors.append(profile.secondary_color)

    for color in colors:
        # Search for all style chunks for this color
        results = vs.search_company_content(
            company_name=f"style_{color}",
            query=f"{color} style job description",
            k=12,
        )

        for r in results:
            meta = r.get("metadata", {})
            dimension = meta.get("dimension", "")
            content = r.get("content", "").strip()
            if not content:
                continue

            found_anything = True

            if dimension == "hooks":
                kit.hook_templates.append(content)
            elif dimension == "adjectives":
                # Adjectives may be comma-separated in a single chunk
                kit.preferred_adjectives.extend(
                    [w.strip() for w in content.split(",") if w.strip()]
                )
            elif dimension == "syntax":
                kit.syntax_constraints.append(content)
            elif dimension == "do_dont":
                kit.do_and_dont.append(content)

    # Also query mode-specific syntax (proaktiv / reaktiv)
    mode_results = vs.search_company_content(
        company_name="style_syntax",
        query=f"{profile.interaction_mode} sentence structure",
        k=4,
    )
    for r in mode_results:
        content = r.get("content", "").strip()
        if content:
            kit.syntax_constraints.append(content)
            found_anything = True

    return found_anything


# ---------------------------------------------------------------------------
# Hardcoded default filler
# ---------------------------------------------------------------------------

def _fill_defaults(kit: StyleKit, profile: StyleProfile, lang: str = "en") -> None:
    """Fill kit from hardcoded defaults for primary (and optional secondary) color."""
    source = _DEFAULTS_DE if lang == "de" else _DEFAULTS

    primary = source.get(profile.primary_color, source["blue"])
    kit.do_and_dont = list(primary["do_and_dont"])
    kit.preferred_adjectives = list(primary["adjectives"])
    kit.hook_templates = list(primary["hooks"])
    kit.syntax_constraints = list(primary["syntax"])

    # Sprinkle secondary elements if present (max 2 adjectives + 1 hook)
    if profile.secondary_color and profile.secondary_color in source:
        secondary = source[profile.secondary_color]
        # Add a couple of secondary adjectives
        for adj in secondary["adjectives"][:2]:
            if adj not in kit.preferred_adjectives:
                kit.preferred_adjectives.append(adj)
        # Add one secondary hook
        if secondary["hooks"]:
            hook = secondary["hooks"][0]
            if hook not in kit.hook_templates:
                kit.hook_templates.append(hook)
