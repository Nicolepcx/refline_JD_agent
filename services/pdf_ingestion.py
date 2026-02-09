"""
PDF Ingestion Pipeline — Motivkompass PDFs → Atomic Style Chunks

Extracts text from the selling-psychology PDFs, splits into atomic knowledge
units, and tags each chunk with structured metadata for RAG retrieval.

Chunk dimensions:
  hooks       – Job-ad openers / headline templates (per color)
  adjectives  – Persuasion adjectives (per color)
  syntax      – Sentence-structure rules (per mode: proaktiv / reaktiv)
  do_dont     – Marketing approach / style rules (per color)
  visuals     – Visual & color cues (per color)

Metadata:
  profile_color   red | yellow | green | blue | any
  dimension       hooks | adjectives | syntax | do_dont | visuals
  language        de  (all source PDFs are German)
  use_case        job_ads | general_marketing
  mode            proaktiv | reaktiv  (optional, for syntax chunks)
  source_file     originating PDF filename

See AGENTS.md §5 for the metadata schema contract.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from pdfminer.high_level import extract_text

from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data model for a style chunk
# ---------------------------------------------------------------------------

@dataclass
class StyleChunk:
    """One atomic knowledge unit extracted from a Motivkompass PDF."""
    content: str
    profile_color: str          # red | yellow | green | blue | any
    dimension: str              # hooks | adjectives | syntax | do_dont | visuals
    language: str = "de"
    use_case: str = "job_ads"   # job_ads | general_marketing
    mode: Optional[str] = None  # proaktiv | reaktiv (syntax chunks only)
    source_file: str = ""


# ---------------------------------------------------------------------------
# Noise removal helpers
# ---------------------------------------------------------------------------

_NOISE_PATTERNS = [
    re.compile(r"^\s*INSTITUT FÜR VERKAUFSPSYCHOLOGIE\s*$", re.I),
    re.compile(r"^\s*www\.\S+\s*$", re.I),
    re.compile(r"^\s*\d+\s*$"),               # bare page numbers
    re.compile(r"^\s*©.*Fotolia\.com\s*$"),    # photo credits
    re.compile(r"^\s*[•§●\-]\s*$"),            # empty bullets
]


def _is_noise(line: str) -> bool:
    """Return True if the line is boilerplate / noise."""
    stripped = line.strip()
    if not stripped:
        return True
    if len(stripped) <= 2 and not stripped.isalpha():
        return True
    # Single characters that are vertical text artifacts
    if len(stripped) == 1:
        return True
    for pat in _NOISE_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def _clean_bullet(text: str) -> str:
    """Strip leading bullet chars and normalize whitespace."""
    text = re.sub(r"^[\s•§●\-üü✓]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _join_wrapped_bullets(lines: list[str]) -> list[str]:
    """
    Merge continuation lines (no bullet prefix) back into the previous bullet.
    This handles multi-line hooks/bullets from PDF extraction.
    """
    merged: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        # Line starts with a bullet marker → new item
        if re.match(r"^[•§●\-ü✓]", stripped):
            merged.append(_clean_bullet(stripped))
        elif merged:
            # Continuation of previous bullet
            merged[-1] = merged[-1].rstrip() + " " + stripped.strip()
        else:
            merged.append(stripped)
    return [m.strip() for m in merged if m.strip()]


# ---------------------------------------------------------------------------
# Extractors for each PDF type
# ---------------------------------------------------------------------------

def _extract_adjective_pdf(path: Path, color: str) -> list[StyleChunk]:
    """Extract adjectives from a single-color adjective PDF."""
    text = extract_text(str(path))
    lines = text.split("\n")
    adjectives: list[str] = []

    for line in lines:
        word = line.strip()
        if _is_noise(word):
            continue
        word_nfc = unicodedata.normalize("NFC", word.lower())
        # Skip the title line
        if word_nfc.startswith("passende adjektive"):
            continue
        # Skip color/archetype labels in the title
        if re.match(r"^(blauen|gelben|gr.nen|roten)\s+motivfeld", word_nfc, re.I):
            continue
        # Each remaining line should be a single adjective
        # Some might be title fragments like "(Denker)" — skip those
        if word.startswith("(") or len(word) > 40:
            continue
        adjectives.append(word)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for adj in adjectives:
        low = adj.lower()
        if low not in seen:
            seen.add(low)
            unique.append(adj)

    if not unique:
        return []

    # Store as ONE chunk with comma-separated adjectives (compact for embedding)
    chunk = StyleChunk(
        content=", ".join(unique),
        profile_color=color,
        dimension="adjectives",
        language="de",
        use_case="job_ads",
        source_file=path.name,
    )
    return [chunk]


def _extract_hooks_pdf(path: Path) -> list[StyleChunk]:
    """Extract hook templates from the Botschaften/Hooks PDF, sectioned by color."""
    text = extract_text(str(path))
    lines = text.split("\n")

    # Section markers → profile_color  (NFC-normalized for macOS compat)
    section_map = {
        unicodedata.normalize("NFC", k): v
        for k, v in {
            "GRÜN": "green",
            "GELB": "yellow",
            "ROT": "red",
            "BLAU": "blue",
        }.items()
    }

    chunks: list[StyleChunk] = []
    current_color: Optional[str] = None
    current_lines: list[str] = []

    def _flush():
        nonlocal current_lines
        if current_color and current_lines:
            # Merge wrapped bullets into complete sentences
            hooks = _join_wrapped_bullets(current_lines)
            for hook in hooks:
                # Skip the "WICHTIG" disclaimer at the end
                if "WICHTIG" in hook.upper():
                    continue
                # Skip tiny fragments that are just leftovers from wrapping
                if len(hook) < 10:
                    continue
                # Clean up hyphenated line-breaks from PDF ("Routi-\nnetätigkeiten")
                hook = re.sub(r"(\w)-\s+(\w)", r"\1\2", hook)
                chunks.append(StyleChunk(
                    content=hook,
                    profile_color=current_color,
                    dimension="hooks",
                    language="de",
                    use_case="job_ads",
                    source_file=path.name,
                ))
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Normalize for section header matching
        upper = unicodedata.normalize("NFC", stripped.upper())
        if upper in section_map:
            _flush()
            current_color = section_map[upper]
            continue

        # Check for the title line
        if "BOTSCHAFTEN" in upper or "HOOKS" in upper:
            continue

        if _is_noise(stripped):
            continue

        if current_color:
            current_lines.append(stripped)

    _flush()
    return chunks


def _extract_satzstruktur_pdf(path: Path) -> list[StyleChunk]:
    """
    Extract sentence-structure rules from the Satzstruktur PDF.
    Produces syntax chunks tagged with mode (proaktiv/reaktiv) and
    reference frame (personenbezug/objektbezug).
    """
    text = extract_text(str(path))
    lines = text.split("\n")

    chunks: list[StyleChunk] = []

    # We manually parse known sections from the content we inspected.
    # The PDF has clear section headers for each axis.

    # --- Proaktive Satzstruktur (lines 0-8) ---
    chunks.append(StyleChunk(
        content=(
            "Proaktive Satzstruktur: Kurze, klare Sätze. "
            "Die Person spricht, als hätte sie Kontrolle über ihre Umgebung. "
            "Direkt. Im Extremfall rollt sie wie eine Dampfwalze über alles hinweg."
        ),
        profile_color="any",
        dimension="syntax",
        language="de",
        use_case="job_ads",
        mode="proaktiv",
        source_file=path.name,
    ))

    # --- Reaktive Satzstruktur (lines 18-31) ---
    chunks.append(StyleChunk(
        content=(
            "Reaktive Satzstruktur: Lange, verschachtelte Sätze. "
            "Die Person spricht, als würde sie von der Welt kontrolliert, "
            "als würden ihr die Dinge zustoßen, sie glaubt an Glück oder Schicksal. "
            "Häufige Erwähnung von nachdenken, analysieren, verstehen, warten "
            "oder prinzipiellen Fragen. Konditionalformen: würde, könnte, sollte."
        ),
        profile_color="any",
        dimension="syntax",
        language="de",
        use_case="job_ads",
        mode="reaktiv",
        source_file=path.name,
    ))

    # --- Objektbezogene Satzstruktur (lines 38-46) ---
    chunks.append(StyleChunk(
        content=(
            "Objektbezogene Satzstruktur: Spricht über Prozesse, Systeme, Werkzeuge, "
            "Ideen, Aufgaben, Ziele. Wird Menschen nicht oft erwähnen, außer in Form von "
            "unpersönlichen Pronomen wie 'sie' oder 'man'. "
            "Personen werden zu Objekten oder Bestandteilen von Prozessen. "
            "Sprechen Sie über Prozesse, Systeme, Werkzeuge, Ideen, Aufgaben und Ziele. "
            "Erwähnen Sie Menschen nur selten und möglichst in Form von unpersönlichen Pronomen."
        ),
        profile_color="any",
        dimension="syntax",
        language="de",
        use_case="general_marketing",
        mode=None,
        source_file=path.name,
    ))

    # --- Personenbezogene Satzstruktur (lines 61-80) ---
    chunks.append(StyleChunk(
        content=(
            "Personenbezogene Satzstruktur: Spricht über Menschen und Gefühle. "
            "Nennt Menschen beim Namen, verwendet persönliche Pronomen. "
            "Personen kommen in ihren Sätzen vor. "
            "Sprechen Sie über Gefühle, Gedanken und Erlebnisse mit Menschen. "
            "Nennen Sie Personen beim Namen."
        ),
        profile_color="any",
        dimension="syntax",
        language="de",
        use_case="general_marketing",
        mode=None,
        source_file=path.name,
    ))

    # --- Proaktive Sprachmuster (lines 163-173) ---
    chunks.append(StyleChunk(
        content=(
            "Proaktive Sprachmuster: machen, loslegen, erledigen; nicht warten, nicht zögern. "
            "Beispiele: 'Genau jetzt ist der richtige Zeitpunkt…', "
            "'Je schneller Sie damit beginnen, desto früher…', "
            "'Legen wir gleich los…', 'Wozu warten…', 'Sie können jederzeit…'"
        ),
        profile_color="any",
        dimension="syntax",
        language="de",
        use_case="job_ads",
        mode="proaktiv",
        source_file=path.name,
    ))

    # --- Reaktive Sprachmuster (lines 175-187) ---
    chunks.append(StyleChunk(
        content=(
            "Reaktive Sprachmuster: verstehen, nachdenken, warten; analysieren, berücksichtigen. "
            "Konditionalformen: könnte, würde, sollte. "
            "Beispiele: 'Nachdem wir es nun analysiert haben…', "
            "'Lassen Sie uns mal gemeinsam darüber nachdenken…', "
            "'Das wird Ihnen deutlich machen, warum…', "
            "'…und wenn Sie sich dann überlegt haben…'"
        ),
        profile_color="any",
        dimension="syntax",
        language="de",
        use_case="job_ads",
        mode="reaktiv",
        source_file=path.name,
    ))

    # --- Motivationsrichtung: Hin-zu (lines 107-114) ---
    chunks.append(StyleChunk(
        content=(
            "Hin-zu-Satzstruktur (proaktiv): Spricht davon, was gewonnen und erreicht werden wird. "
            "Einbeziehung erwünschter Situationen und Dinge. "
            "Sagt, was sie möchte, benennt Ziele."
        ),
        profile_color="any",
        dimension="syntax",
        language="de",
        use_case="general_marketing",
        mode="proaktiv",
        source_file=path.name,
    ))

    # --- Motivationsrichtung: Weg-von (lines 89-96) ---
    chunks.append(StyleChunk(
        content=(
            "Weg-von-Satzstruktur (reaktiv): Erwähnt Situationen, die vermieden, "
            "oder Probleme, die behoben werden müssen. Ausgrenzung unerwünschter "
            "Situationen und Dinge. Sagt, was sie nicht möchte, benennt Probleme."
        ),
        profile_color="any",
        dimension="syntax",
        language="de",
        use_case="general_marketing",
        mode="reaktiv",
        source_file=path.name,
    ))

    return chunks


def _extract_motivkompass_uebersicht(path: Path) -> list[StyleChunk]:
    """
    Extract do/don't marketing-approach rules from Motivkompass Übersicht.
    This is a dense overview PDF combining all 4 quadrants.
    """
    chunks: list[StyleChunk] = []

    # --- YELLOW (Entertainer) — marketing approach (lines 0-46) ---
    chunks.append(StyleChunk(
        content=(
            "Gelb (Entertainer) – Marketing-Ansatz: Lockeres Marketing. "
            "Verknappung mit lockerer und direkter Ansprache. "
            "Emoticons (Social Media) nutzen. Viele Farben und Bilder. "
            "Mit einer Prise Humor. Freiheit, Spaß/Freude, Kreativität. "
            "Individualität, Gesehen werden, Was Besonderes sein. "
            "Auswahl überlassen. Fokus auf Möglichkeiten. Schnelligkeit."
        ),
        profile_color="yellow",
        dimension="do_dont",
        language="de",
        use_case="job_ads",
        source_file=path.name,
    ))

    # Hin-zu phrases for yellow
    chunks.append(StyleChunk(
        content=(
            "Gelb (Entertainer) – Hin-zu Formulierungen: "
            "Sprich davon, was gewonnen und erreicht werden wird. "
            "Einbeziehung erwünschter Situationen und Dinge. "
            "Machen, loslegen, erledigen; nicht warten, nicht zögern. "
            "Beispiele: 'Das bringt Ihnen...', 'Das erhöht Ihre...', "
            "'Das sorgt für…', 'Das ermöglicht Ihnen…', 'Das steigert…'"
        ),
        profile_color="yellow",
        dimension="do_dont",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    # --- RED (Macher) — marketing approach (lines 47-89) ---
    chunks.append(StyleChunk(
        content=(
            "Rot (Macher) – Marketing-Ansatz: Hartes Marketing. "
            "Verknappung mit klarer und direkter Ansprache. "
            "Status, Geld, Sei besser, mehr Leistung, höher–schneller–weiter. "
            "Wettbewerb/Konkurrenz, Erster sein, Verbessern. "
            "Schnelle Umsetzung, Ergebnisse zählen, Wirkung, sich durchsetzen. "
            "Auswahl überlassen (Pakete). Fokus auf Ergebnisse und Benefits. Schnelligkeit."
        ),
        profile_color="red",
        dimension="do_dont",
        language="de",
        use_case="job_ads",
        source_file=path.name,
    ))

    # Hin-zu phrases for red
    chunks.append(StyleChunk(
        content=(
            "Rot (Macher) – Hin-zu Formulierungen: "
            "Sprich davon, was gewonnen und erreicht werden wird. "
            "Machen, loslegen, erledigen; nicht warten, nicht zögern. "
            "Beispiele: 'Das bringt Ihnen...', 'Das erhöht Ihre...', "
            "'Das sorgt für…', 'Das ermöglicht Ihnen…', "
            "'Das steigert…', 'Das maximiert Ihre…'"
        ),
        profile_color="red",
        dimension="do_dont",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    # --- GREEN (Bewahrer) — marketing approach (lines 232-275) ---
    chunks.append(StyleChunk(
        content=(
            "Grün (Bewahrer) – Marketing-Ansatz: Sanftes Marketing. "
            "Kein Druck und Angst aufbauen. Persönlich ansprechen. "
            "Harmonie und Sinn triggern. Langsam vorgehen – 7-Kontakte-Regel. "
            "Vertrauen aufbauen über Chat/Gespräch. "
            "Anschluss, höherer Sinn. Menschen helfen, Sanft. "
            "Ruhe, Harmonie. Gemeinsam, Sei dabei. "
            "Lösung vorgeben. Fokus auf Beziehung."
        ),
        profile_color="green",
        dimension="do_dont",
        language="de",
        use_case="job_ads",
        source_file=path.name,
    ))

    # Weg-von phrases for green
    chunks.append(StyleChunk(
        content=(
            "Grün (Bewahrer) – Weg-von Formulierungen: "
            "Erwähne Situationen, die vermieden, oder Probleme, die behoben werden müssen. "
            "Ausgrenzung unerwünschter Situationen und Dinge. "
            "Verstehen, nachdenken, warten; analysieren, berücksichtigen. "
            "Könnte, würde, sollte. "
            "Beispiele: 'Das schützt Sie vor…', 'Das erspart Ihnen…', "
            "'Das verhindert…', 'Das senkt Ihre…', 'Das vermeidet…', 'Das sichert Ihnen…'"
        ),
        profile_color="green",
        dimension="do_dont",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    # --- BLUE (Denker) — marketing approach (lines 277-312) ---
    chunks.append(StyleChunk(
        content=(
            "Blau (Denker) – Marketing-Ansatz: Seriöses Marketing. "
            "Normale Ansprache – Fokus auf Qualität. "
            "ZDF nutzen – Belege zeigen (Testimonials, Zertifikate). "
            "Garantien nutzen. Langsam vorgehen. "
            "Längere Texte, gehobenere Sprache. "
            "Sicherheit, Qualität, Zuverlässigkeit, Bewährtheit. "
            "Zahlen/Daten, Autorität. Vernunft, Wissenschaftlichkeit. "
            "Autoritäten, Experten. Lösung vorgeben. Fokus auf Sicherheit."
        ),
        profile_color="blue",
        dimension="do_dont",
        language="de",
        use_case="job_ads",
        source_file=path.name,
    ))

    # Weg-von phrases for blue
    chunks.append(StyleChunk(
        content=(
            "Blau (Denker) – Weg-von Formulierungen: "
            "Erwähne Situationen, die vermieden, oder Probleme, die behoben werden müssen. "
            "Ausgrenzung unerwünschter Situationen und Dinge. "
            "Verstehen, nachdenken, warten; analysieren, berücksichtigen. "
            "Könnte, würde, sollte. "
            "Beispiele: 'Nachdem wir es nun analysiert haben…', "
            "'Lassen Sie uns mal gemeinsam darüber nachdenken…', "
            "'Das wird Ihnen deutlich machen, warum…'"
        ),
        profile_color="blue",
        dimension="do_dont",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    return chunks


def _extract_farb_bildwahrnehmung(path: Path) -> list[StyleChunk]:
    """
    Extract visual cues per color from the Psychologische Farb- und Bildwahrnehmung PDF.
    """
    chunks: list[StyleChunk] = []

    # Red visual cues (lines 7-18)
    chunks.append(StyleChunk(
        content=(
            "Rotes Motivfeld – Visuelle Hinweise: "
            "Präferiert Bilder, die mit Geschwindigkeit und Kraft assoziiert werden: "
            "Autos, Rolex / Luxusartikel, Feuer, schicke Häuser (Villa), "
            "Anzüge, Auszeichnungen, Kraft, Muskeln, Leistungssport. "
            "Präferierte Farben: ROT und SCHWARZ."
        ),
        profile_color="red",
        dimension="visuals",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    # Yellow visual cues (lines 26-34)
    chunks.append(StyleChunk(
        content=(
            "Gelbes Motivfeld – Visuelle Hinweise: "
            "Präferiert Bilder, die mit Freiheit assoziiert werden: "
            "Meer, Felder, Bunte Kleidung, Menschen die sich freuen, "
            "Tanzende Menschen, Übliche Freiheitssymbole. "
            "Präferierte Farben: GELB und BUNT."
        ),
        profile_color="yellow",
        dimension="visuals",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    # Blue visual cues (lines 42-48)
    chunks.append(StyleChunk(
        content=(
            "Blaues Motivfeld – Visuelle Hinweise: "
            "Präferiert eher Bilder mit Fokus auf Objektbezug: "
            "Ordner, Bücher, Seriöse Personen (Ärzte in Kittel etc.), "
            "Grafiken / Statistiken. "
            "Präferierte Farben: BLAU und GRAU."
        ),
        profile_color="blue",
        dimension="visuals",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    # Green visual cues (lines 56-62)
    chunks.append(StyleChunk(
        content=(
            "Grünes Motivfeld – Visuelle Hinweise: "
            "Präferiert eher weniger Bilder, die Emotionen hervorrufen: "
            "Familie, Natur, Fröhlich lächelnde Menschen, "
            "Handgeben als Gestik. "
            "Präferierte Farben: GRÜN und LILA."
        ),
        profile_color="green",
        dimension="visuals",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    return chunks


def _extract_allgemeine_tipps(path: Path) -> list[StyleChunk]:
    """
    Extract general axis-level tips from the Allgemeine Tipps PDF.
    This PDF maps the 4 quadrants onto the proaktiv/reaktiv ×
    personenbezug/objektbezug axes.
    """
    chunks: list[StyleChunk] = []

    # Yellow quadrant (proaktiv + personenbezug)
    chunks.append(StyleChunk(
        content=(
            "Gelb (proaktiv + Personenbezug): 'Wie kommt es bei anderen an?' – "
            "Neue Trends, 'Mittelpunkt'. Maßgeschneiderte Lösung. "
            "Kurze Präsentationen / Small Talk. Fokus Möglichkeiten."
        ),
        profile_color="yellow",
        dimension="do_dont",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    # Red quadrant (proaktiv + objektbezug)
    chunks.append(StyleChunk(
        content=(
            "Rot (proaktiv + Objektbezug): 'Was meine ich dazu?' – "
            "Cleverness, (VIP-)Status. Informationen zum Entscheiden. "
            "Alternativen aufzeigen. Fokus Ergebnisse."
        ),
        profile_color="red",
        dimension="do_dont",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    # Green quadrant (reaktiv + personenbezug)
    chunks.append(StyleChunk(
        content=(
            "Grün (reaktiv + Personenbezug): 'Was meinen andere dazu?' – "
            "Sicherheit, Vertrauen. Prüft alles sehr genau. "
            "Langsam, Bestätigung einholen. Fokus Beziehung."
        ),
        profile_color="green",
        dimension="do_dont",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    # Blue quadrant (reaktiv + objektbezug)
    chunks.append(StyleChunk(
        content=(
            "Blau (reaktiv + Objektbezug): 'Wo steht das? Wer sagt das?' – "
            "Garantie, Qualität. Zahlen, Daten, Fakten. "
            "Funktion im Vordergrund. Fokus Sicherheit."
        ),
        profile_color="blue",
        dimension="do_dont",
        language="de",
        use_case="general_marketing",
        source_file=path.name,
    ))

    return chunks


# ---------------------------------------------------------------------------
# Master extraction pipeline
# ---------------------------------------------------------------------------

# Map filenames (or substrings) → extractor functions
_ADJECTIVE_FILES = {
    "roten Motivfeld (Macher)": "red",
    "gelben Motivfeld (Entertainer)": "yellow",
    "grünen Motivfeld (Bewahrer)": "green",
    "blauen Motivfeld (Denker)": "blue",
}


def extract_all_chunks(pdf_dir: str | Path) -> list[StyleChunk]:
    """
    Run all extractors on every PDF in ``pdf_dir``.

    Returns a flat list of StyleChunks ready for embedding.
    """
    pdf_dir = Path(pdf_dir)
    if not pdf_dir.is_dir():
        raise FileNotFoundError(f"PDF directory not found: {pdf_dir}")

    all_chunks: list[StyleChunk] = []

    # Pre-normalize adjective file keys for macOS NFD compatibility
    adjective_files_nfc = {
        unicodedata.normalize("NFC", k): v
        for k, v in _ADJECTIVE_FILES.items()
    }

    for fname in sorted(os.listdir(pdf_dir)):
        if not fname.lower().endswith(".pdf"):
            continue

        fpath = pdf_dir / fname
        # Normalize filename to NFC so umlauts match consistently
        fname_nfc = unicodedata.normalize("NFC", fname)
        logger.info(f"[PDF Ingestion] Processing: {fname}")

        try:
            # --- Adjective PDFs ---
            matched_adjective = False
            for substr, color in adjective_files_nfc.items():
                if substr in fname_nfc:
                    chunks = _extract_adjective_pdf(fpath, color)
                    all_chunks.extend(chunks)
                    logger.info(f"  → {len(chunks)} adjective chunk(s) [{color}]")
                    matched_adjective = True
                    break

            if not matched_adjective:
                # --- Hooks PDF ---
                if "Botschaften" in fname_nfc or "Hooks" in fname_nfc:
                    chunks = _extract_hooks_pdf(fpath)
                    all_chunks.extend(chunks)
                    logger.info(f"  → {len(chunks)} hook chunk(s)")

                # --- Satzstruktur PDF ---
                elif "Satzstruktur" in fname_nfc or "motivkompassansprache" in fname_nfc:
                    chunks = _extract_satzstruktur_pdf(fpath)
                    all_chunks.extend(chunks)
                    logger.info(f"  → {len(chunks)} syntax chunk(s)")

                # --- Motivkompass Übersicht ---
                elif "Motivkompass" in fname_nfc and unicodedata.normalize("NFC", "Übersicht") in fname_nfc:
                    chunks = _extract_motivkompass_uebersicht(fpath)
                    all_chunks.extend(chunks)
                    logger.info(f"  → {len(chunks)} do_dont/marketing chunk(s)")

                # --- Psychologische Farb- und Bildwahrnehmung ---
                elif "Psychologische" in fname_nfc and "Farb" in fname_nfc:
                    chunks = _extract_farb_bildwahrnehmung(fpath)
                    all_chunks.extend(chunks)
                    logger.info(f"  → {len(chunks)} visual chunk(s)")

                # --- Allgemeine Tipps ---
                elif "Allgemeine Tipps" in fname_nfc:
                    chunks = _extract_allgemeine_tipps(fpath)
                    all_chunks.extend(chunks)
                    logger.info(f"  → {len(chunks)} general tip chunk(s)")

                else:
                    logger.warning(f"  ⚠ No extractor matched for: {fname}")

        except Exception as e:
            logger.error(f"  ✗ Error processing {fname}: {e}", exc_info=True)

    logger.info(
        f"[PDF Ingestion] Total: {len(all_chunks)} chunks from "
        f"{len([f for f in os.listdir(pdf_dir) if f.endswith('.pdf')])} PDFs"
    )
    return all_chunks


# ---------------------------------------------------------------------------
# Export to JSONL (for human review / debugging)
# ---------------------------------------------------------------------------

def chunks_to_jsonl(chunks: list[StyleChunk], output_path: str | Path) -> Path:
    """Write chunks to a JSONL file for inspection."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    logger.info(f"[PDF Ingestion] Wrote {len(chunks)} chunks → {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Load chunks into VectorStoreManager
# ---------------------------------------------------------------------------

def load_chunks_into_vector_store(
    chunks: list[StyleChunk],
    persist_directory: str = "vector_store",
) -> bool:
    """
    Embed all StyleChunks and store them in the FAISS vector store.

    Each chunk is stored as a LangChain Document with full metadata.
    The ``company_name`` field uses ``style_{color}`` for color-specific chunks
    or ``style_syntax`` for mode-specific chunks — matching the retrieval
    pattern in ``style_retriever._fill_from_rag``.
    """
    from langchain_core.documents import Document
    from services.vector_store import VectorStoreManager

    vs = VectorStoreManager(
        store_type="faiss",
        persist_directory=persist_directory,
    )

    if not vs.embeddings:
        logger.error("[PDF Ingestion] Embeddings not available – cannot vectorize.")
        return False

    documents: list[Document] = []
    for chunk in chunks:
        # Determine the company_name key for retrieval
        if chunk.dimension == "syntax" and chunk.profile_color == "any":
            company_name = "style_syntax"
        else:
            company_name = f"style_{chunk.profile_color}"

        metadata = {
            "company_name": company_name,
            "profile_color": chunk.profile_color,
            "dimension": chunk.dimension,
            "language": chunk.language,
            "use_case": chunk.use_case,
            "source_file": chunk.source_file,
        }
        if chunk.mode:
            metadata["mode"] = chunk.mode

        documents.append(Document(
            page_content=chunk.content,
            metadata=metadata,
        ))

    if not documents:
        logger.warning("[PDF Ingestion] No documents to embed.")
        return False

    try:
        from langchain_community.vectorstores import FAISS as FAISSStore

        if vs.store is None:
            vs.store = FAISSStore.from_documents(documents, vs.embeddings)
        else:
            vs.store.add_documents(documents)

        faiss_path = vs.persist_directory / "faiss_index"
        vs.store.save_local(str(faiss_path))
        logger.info(
            f"[PDF Ingestion] ✓ Embedded {len(documents)} chunks into FAISS "
            f"at {faiss_path}"
        )
        return True
    except Exception as e:
        logger.error(f"[PDF Ingestion] ✗ Failed to embed: {e}", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Run full extraction → JSONL + optional vector store ingestion."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract Motivkompass PDFs into atomic style chunks"
    )
    parser.add_argument(
        "--pdf-dir",
        default="PDFs_selling_psychology",
        help="Path to the PDF directory",
    )
    parser.add_argument(
        "--output",
        default="style_chunks.jsonl",
        help="Output JSONL path for review",
    )
    parser.add_argument(
        "--embed",
        action="store_true",
        help="Also embed into FAISS vector store",
    )
    parser.add_argument(
        "--store-dir",
        default="vector_store",
        help="Directory for FAISS persistence",
    )
    args = parser.parse_args()

    # 1. Extract
    chunks = extract_all_chunks(args.pdf_dir)

    # 2. Write JSONL for review
    chunks_to_jsonl(chunks, args.output)

    # 3. Summary
    from collections import Counter
    dim_counts = Counter(c.dimension for c in chunks)
    color_counts = Counter(c.profile_color for c in chunks)
    print(f"\n{'='*50}")
    print(f"Extracted {len(chunks)} total chunks")
    print(f"  By dimension: {dict(dim_counts)}")
    print(f"  By color:     {dict(color_counts)}")
    print(f"  Output:       {args.output}")

    # 4. Optionally embed
    if args.embed:
        print(f"\nEmbedding into FAISS at {args.store_dir}...")
        ok = load_chunks_into_vector_store(chunks, persist_directory=args.store_dir)
        print("  ✓ Done!" if ok else "  ✗ Failed — check logs.")


if __name__ == "__main__":
    main()
