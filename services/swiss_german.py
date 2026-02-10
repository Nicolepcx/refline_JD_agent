"""
Schweizer Schriftdeutsch — Swiss Standard German enforcement.

This module centralises all rules for Swiss German writing:
  1. ß → ss  replacement (Swiss German NEVER uses Eszett)
  2. Vocabulary mapping (DE-DE → DE-CH)
  3. Prompt injection block for generation agents
  4. Post-processing guard for any LLM-generated German text

Design:
  • Every German text leaving the system MUST pass through `enforce_swiss_german()`.
  • The CH prompt block is injected by generators when lang == "de".
  • The vocabulary map is applied deterministically after LLM generation.

References:
  Swiss Federal Chancellery style guide (Bundeskanzlei BK)
  — "In der Schweiz wird kein ß verwendet."
"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# §1  ß → ss  (mandatory, no exceptions)
# ---------------------------------------------------------------------------

def replace_eszett(text: str) -> str:
    """Replace every ß with ss.  Swiss German never uses Eszett."""
    return text.replace("ß", "ss")


# ---------------------------------------------------------------------------
# §2  DE-DE → DE-CH vocabulary mapping
# ---------------------------------------------------------------------------
# Each tuple is (pattern, replacement).
# Patterns use word boundaries to avoid false positives.
# The list is intentionally conservative — only well-established CH/DE
# differences that appear in HR / job-ad context.

_CH_TERM_MAP: list[tuple[str, str]] = [
    # Employment & contracts
    (r"\bTarifvertrag\b", "Gesamtarbeitsvertrag (GAV)"),
    (r"\bTarifverträge\b", "Gesamtarbeitsverträge (GAV)"),
    (r"\bTarifvertrags\b", "Gesamtarbeitsvertrags (GAV)"),
    (r"\bGehalt\b", "Salär"),
    (r"\bGehalts\b", "Salärs"),
    (r"\bGehälter\b", "Saläre"),
    (r"\bGehaltsvorstellung\b", "Salärvorstellung"),
    (r"\bGehaltsvorstellungen\b", "Salärvorstellungen"),
    (r"\bGehaltserhöhung\b", "Salärerhöhung"),
    (r"\bGehaltsabrechnung\b", "Lohnabrechnung"),
    (r"\bBruttolohn\b", "Bruttolohn"),  # same in CH, keep
    (r"\bArbeitnehmer\b", "Arbeitnehmende"),
    (r"\bArbeitnehmern\b", "Arbeitnehmenden"),
    (r"\bArbeitnehmers\b", "Arbeitnehmenden"),

    # Education & qualifications
    (r"\bAbitur\b", "Matura"),
    (r"\bAbiturient\b", "Maturand"),
    (r"\bAbiturientin\b", "Maturandin"),
    (r"\bAbiturienten\b", "Maturanden"),

    # Time & leave
    (r"\bUrlaub\b", "Ferien"),
    (r"\bUrlaubs\b", "Ferien"),
    (r"\bUrlaubstage\b", "Ferientage"),
    (r"\bUrlaubsanspruch\b", "Ferienanspruch"),

    # Social security & benefits (CH-specific terms)
    (r"\bKrankenversicherung\b", "Krankenversicherung (KVG)"),
    (r"\bRentenversicherung\b", "AHV"),
    (r"\bBetriebsrente\b", "Pensionskasse (BVG)"),
    (r"\bbetriebliche Altersvorsorge\b", "berufliche Vorsorge (BVG)"),
    (r"\bBetriebliche Altersvorsorge\b", "Berufliche Vorsorge (BVG)"),

    # Common phrasing
    (r"\bJanuar\b", "Januar"),        # same in CH, keep
    (r"\bBüro\b", "Büro"),            # same in CH, keep
    (r"\bVelo\b", "Velo"),            # already CH
    (r"\bFahrrad\b", "Velo"),         # DE → CH
    (r"\bParkplatz\b", "Parkplatz"),  # same
    (r"\bTram\b", "Tram"),            # already CH
    (r"\bStraßenbahn\b", "Tram"),
    (r"\bTüte\b", "Sack"),            # colloquial but common in benefits context
]


def _apply_ch_vocabulary(text: str) -> str:
    """Apply CH-specific vocabulary replacements (regex, case-sensitive)."""
    for pattern, replacement in _CH_TERM_MAP:
        text = re.sub(pattern, replacement, text)
    return text


# ---------------------------------------------------------------------------
# §3  Master enforcement function
# ---------------------------------------------------------------------------

def enforce_swiss_german(text: str) -> str:
    """
    Full Schweizer Schriftdeutsch post-processing pipeline.

    Call this on EVERY German string before it leaves the system:
      1. ß → ss
      2. DE-DE → DE-CH vocabulary
    """
    text = replace_eszett(text)
    text = _apply_ch_vocabulary(text)
    return text


def enforce_swiss_german_on_list(items: List[str]) -> List[str]:
    """Apply enforce_swiss_german to every item in a list."""
    return [enforce_swiss_german(item) for item in items]


# ---------------------------------------------------------------------------
# §4  Prompt injection block for Schweizer Schriftdeutsch
# ---------------------------------------------------------------------------

# This block is injected into EVERY German-language generation prompt.
# It instructs the LLM to write in Swiss Standard German from the start,
# reducing the need for post-processing corrections.
#
# The pronoun rule (Sie vs du) is injected dynamically based on formality.

_CH_BLOCK_HEADER = """\
## Schweizer Schriftdeutsch (OBLIGATORISCH)

Du schreibst AUSSCHLIESSLICH in Schweizer Schriftdeutsch (CH-Deutsch).
Beachte folgende Regeln STRIKT:

### Orthografie
- NIEMALS «ß» verwenden. Immer «ss» schreiben (z.B. «gross» statt «groß», «Strasse» statt «Straße»).

### Wortschatz (CH-spezifisch)
- «Salär» statt «Gehalt»
- «Gesamtarbeitsvertrag (GAV)» statt «Tarifvertrag»
- «Ferien» statt «Urlaub»
- «Matura» statt «Abitur»
- «berufliche Vorsorge (BVG)» statt «betriebliche Altersvorsorge»
- «Pensionskasse» statt «Betriebsrente»
- «Arbeitnehmende» statt «Arbeitnehmer»
- «Salärvorstellung» statt «Gehaltsvorstellung»
- «Lohnabrechnung» statt «Gehaltsabrechnung»

### Stilistische Merkmale von CH-Texten
- Neutraler, sachlicher Ton (weniger werblich als DE-DE)
- Etwas kürzere Sätze als in Deutschland üblich
- Weniger rhetorischer Schmuck, weniger Ausrufezeichen
- Prozedurale Klarheit hat Vorrang vor emotionaler Ansprache"""

_CH_PRONOUN_FORMAL = (
    "\n- DURCHGEHEND die Höflichkeitsform «Sie» verwenden (siezen). "
    "Beispiel: «Sie arbeiten…», «Ihr Team…», «Wir bieten Ihnen…». "
    "NIEMALS «du» oder «dir» als Anrede."
)

_CH_PRONOUN_CASUAL = (
    "\n- DURCHGEHEND die informelle «du»-Anrede verwenden (duzen). "
    "Beispiel: «Du arbeitest…», «Dein Team…», «Wir bieten dir…». "
    "NIEMALS «Sie» oder «Ihnen» als Höflichkeitsform."
)


def get_ch_prompt_block(formality: str = "neutral") -> str:
    """Return the Schweizer Schriftdeutsch instruction block for prompt injection.

    Args:
        formality: One of "casual", "neutral", "formal".
                   Controls Sie (neutral/formal) vs du (casual) pronoun rule.
    """
    pronoun_rule = _CH_PRONOUN_CASUAL if formality == "casual" else _CH_PRONOUN_FORMAL
    return _CH_BLOCK_HEADER + pronoun_rule + "\n"


# ---------------------------------------------------------------------------
# §5  Pronoun consistency check (Sie vs du)
# ---------------------------------------------------------------------------
# German pronoun forms used as direct address indicators.
# We check for the *wrong* form to detect LLM drift after generation.
#
# IMPORTANT: Automatic replacement is NOT safe for German pronouns because
# "Sie/sie" can mean "they" (3rd person) as well as formal "you".
# Instead, we detect violations and log warnings.  If the count exceeds
# a threshold, the caller can decide to re-generate or flag for review.

# Markers for informal "du"-address (duzen)
_DU_MARKERS = re.compile(
    r"""
    \b[Dd]u\b        |   # du / Du
    \b[Dd]ir\b       |   # dir / Dir  (dative)
    \b[Dd]ich\b      |   # dich / Dich (accusative)
    \b[Dd]ein(?:e[mnrs]?)?\b  # dein/deine/deinem/deinen/deiner/deines
    """,
    re.VERBOSE,
)

# Markers for formal "Sie"-address (siezen)
# We only check capitalised forms + unambiguous formal dative/possessive.
_SIE_FORMAL_MARKERS = re.compile(
    r"""
    \bIhnen\b        |   # formal dative  (always formal when capitalised mid-sentence)
    \bIhr(?:e[mnrs]?)?\b  # Ihr/Ihre/Ihrem/Ihren/Ihrer/Ihres (possessive formal)
    """,
    re.VERBOSE,
)


def check_pronoun_consistency(
    text: str,
    formality: str,
) -> Tuple[bool, int]:
    """Check whether a German text uses the correct pronoun form.

    Args:
        text: The German text to check.
        formality: "casual" expects du, "neutral"/"formal" expects Sie.

    Returns:
        (is_consistent, violation_count):
            is_consistent — True if no wrong-form markers were found.
            violation_count — number of wrong-form hits detected.
    """
    if formality == "casual":
        # Casual should use "du" — look for forbidden formal markers
        violations = _SIE_FORMAL_MARKERS.findall(text)
    else:
        # Neutral/formal should use "Sie" — look for forbidden informal markers
        violations = _DU_MARKERS.findall(text)

    count = len(violations)
    if count > 0:
        expected = "du" if formality == "casual" else "Sie"
        wrong = "Sie/Ihnen" if formality == "casual" else "du/dir"
        logger.warning(
            f"[Pronoun Check] Expected «{expected}» (formality={formality}) "
            f"but found {count} «{wrong}» marker(s) in text. "
            f"Samples: {violations[:5]}"
        )
    return count == 0, count


# ---------------------------------------------------------------------------
# §6  Swiss vocabulary violation detection (for eval / quality checks)
# ---------------------------------------------------------------------------
# These are the DE-DE source terms from _CH_TERM_MAP that should NEVER
# appear in properly written Schweizer Schriftdeutsch.  The list only
# includes entries where source ≠ replacement (i.e. actual differences).

_DE_DE_VIOLATIONS: list[tuple[str, str, str]] = [
    # (regex_pattern, plain_label, expected_CH_term)
    # Employment & contracts
    (r"\bTarifvertrag(?:s|e|es)?\b", "Tarifvertrag*", "Gesamtarbeitsvertrag (GAV)"),
    (r"\bGehalt\b", "Gehalt", "Salär"),
    (r"\bGehalts\b", "Gehalts", "Salärs"),
    (r"\bGehälter\b", "Gehälter", "Saläre"),
    (r"\bGehaltsvorstellung(?:en)?\b", "Gehaltsvorstellung*", "Salärvorstellung"),
    (r"\bGehaltserhöhung\b", "Gehaltserhöhung", "Salärerhöhung"),
    (r"\bGehaltsabrechnung\b", "Gehaltsabrechnung", "Lohnabrechnung"),
    (r"\bArbeitnehmer(?:n|s)?\b", "Arbeitnehmer*", "Arbeitnehmende"),

    # Education
    (r"\bAbitur\b", "Abitur", "Matura"),
    (r"\bAbiturient(?:in|en)?\b", "Abiturient*", "Maturand/in"),

    # Leave
    (r"\bUrlaub(?:s)?\b", "Urlaub*", "Ferien"),
    (r"\bUrlaubstage\b", "Urlaubstage", "Ferientage"),
    (r"\bUrlaubsanspruch\b", "Urlaubsanspruch", "Ferienanspruch"),

    # Benefits / social security
    (r"\bBetriebsrente\b", "Betriebsrente", "Pensionskasse (BVG)"),
    (r"\b[Bb]etriebliche Altersvorsorge\b", "betriebliche Altersvorsorge", "berufliche Vorsorge (BVG)"),
    (r"\bRentenversicherung\b", "Rentenversicherung", "AHV"),

    # Transport / misc
    (r"\bFahrrad\b", "Fahrrad", "Velo"),
    (r"\bStraßenbahn\b", "Straßenbahn", "Tram"),
    (r"\bTüte\b", "Tüte", "Sack"),
]

# Compile once for performance
_DE_DE_VIOLATION_PATTERNS = [
    (re.compile(pat), label, ch_term)
    for pat, label, ch_term in _DE_DE_VIOLATIONS
]


def check_swiss_vocab(text: str) -> tuple[bool, int, list[str]]:
    """
    Detect DE-DE vocabulary that should be CH-DE in Swiss German text.

    Returns:
        (is_clean, violation_count, violation_details)
        - is_clean: True if no DE-DE vocabulary found
        - violation_count: total number of DE-DE term occurrences
        - violation_details: list of human-readable strings like
          ``"Gehalt (→ Salär) ×2"``
    """
    details: list[str] = []
    total = 0

    for pattern, label, ch_term in _DE_DE_VIOLATION_PATTERNS:
        hits = pattern.findall(text)
        if hits:
            count = len(hits)
            total += count
            details.append(f"{label} (→ {ch_term}) ×{count}")

    return total == 0, total, details


def check_pronoun_consistency_on_list(
    items: List[str],
    formality: str,
) -> Tuple[bool, int]:
    """Run pronoun consistency check across a list of strings.

    Returns:
        (all_consistent, total_violations)
    """
    total = 0
    for item in items:
        _, count = check_pronoun_consistency(item, formality)
        total += count
    return total == 0, total
