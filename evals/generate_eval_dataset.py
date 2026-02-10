#!/usr/bin/env python3
"""
Step 1 — Generate the evaluation dataset from duty_chunks.jsonl.

Sampling strategy
─────────────────
1. Load all duty chunks (376 lines, ~183 unique category codes).
2. Deduplicate to one chunk per (category_code, seniority) pair.
3. Randomly sample ~50 unique category codes.
4. For each selected category, pick one seniority chunk (prefer the one whose
   seniority naturally matches a random app-level label).
5. Create TWO scenarios per category: one DE, one EN.
   → ~100 EvalScenario records total.
6. Each scenario gets a randomized company_type and formality.

Usage
─────
    python -m evals.generate_eval_dataset                # defaults
    python -m evals.generate_eval_dataset --num 60       # 60 categories → 120 scenarios
    python -m evals.generate_eval_dataset --seed 123     # custom seed
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# Static EN translations for common Swiss job-category names.
# Only needs to cover the categories likely to be sampled.
# For anything missing, a simple rule-based fallback is applied.
# ---------------------------------------------------------------------------

_DE_EN_TITLE_MAP: Dict[str, str] = {
    "Geschäftsführung / CEO / VR": "CEO / Managing Director",
    "Betriebsleitung": "Operations Manager",
    "Finanzleitung": "Head of Finance",
    "Technische Leitung": "Technical Director",
    "Leiter Informationstechnologie": "Head of IT",
    "Filialleiter": "Branch Manager",
    "Abteilungsleiter": "Department Manager",
    "Research & Analyse": "Research & Analysis",
    "Firmenkundenberatung / Relationship Management": "Corporate Client Advisory / Relationship Management",
    "Private Banking / Client Management": "Private Banking / Client Management",
    "Asset- / Fonds- / Portfolio Management": "Asset / Fund / Portfolio Management",
    "Investment Banking": "Investment Banking",
    "Zahlungsverkehr / Operations": "Payments / Operations",
    "Kredit / Hypotheken": "Credit / Mortgages",
    "Finanzen / Handel / Verkauf": "Finance / Trading / Sales",
    "Compliance / Risk / Legal (Bank)": "Compliance / Risk / Legal (Banking)",
    "Kundenberatung Privat / Retail Banking": "Retail Banking Advisor",
    "Betriebsbuchhaltung / Finanzbuchhaltung": "Accounting / Financial Accounting",
    "Controlling / Reporting": "Controlling / Reporting",
    "Revision / Audit": "Internal Audit",
    "Treuhand / Wirtschaftsprüfung": "Trust / Auditing",
    "Steuerberatung": "Tax Advisory",
    "Unternehmensberatung": "Management Consulting",
    "Beratung / Consulting": "Consulting",
    "Rechtsberatung / Notariat": "Legal Advisory / Notary",
    "Anwaltssekretariat": "Legal Secretary",
    "Softwareentwicklung / Applikationsentwicklung": "Software / Application Development",
    "Systemadministration / IT-Betrieb": "System Administration / IT Operations",
    "Netzwerk / Infrastruktur / Cloud": "Network / Infrastructure / Cloud",
    "IT-Sicherheit / Cyber Security": "IT Security / Cybersecurity",
    "Datenanalyse / Business Intelligence": "Data Analysis / Business Intelligence",
    "Data Engineering / Data Science": "Data Engineering / Data Science",
    "IT-Projektleitung": "IT Project Management",
    "UX / UI Design": "UX / UI Design",
    "IT-Support / Helpdesk": "IT Support / Helpdesk",
    "Telekommunikation / Netzwerktechnik": "Telecommunications / Network Engineering",
    "Qualitätsmanagement / Testing": "Quality Management / Testing",
    "ERP / CRM Beratung": "ERP / CRM Consulting",
    "HR-Leitung / HR-Management": "HR Management",
    "HR-Administration / Payroll": "HR Administration / Payroll",
    "Recruiting / Talent Acquisition": "Recruiting / Talent Acquisition",
    "Personalentwicklung / Training": "People Development / Training",
    "Sachbearbeitung / Administration": "Administration / Office Clerk",
    "Empfang / Assistenz / Sekretariat": "Reception / Assistant / Secretary",
    "Einkauf / Beschaffung": "Procurement / Purchasing",
    "Logistik / Supply Chain": "Logistics / Supply Chain",
    "Kundendienst / Customer Service": "Customer Service",
    "Verkauf / Innendienst": "Sales / Inside Sales",
    "Marketing / Kommunikation": "Marketing / Communications",
    "Immobilienverwaltung": "Property Management",
    "Immobilienbewertung": "Real Estate Valuation",
    "Facilitymanagement": "Facility Management",
    "Bauingenieur / Bauleitung": "Civil Engineer / Construction Management",
    "Architektur / Innenarchitektur": "Architecture / Interior Architecture",
    "Elektrotechnik / Elektronik": "Electrical Engineering / Electronics",
    "Maschinenbau / Mechanik": "Mechanical Engineering",
    "Automation / Verfahrenstechnik": "Automation / Process Engineering",
    "Pflege / Betreuung": "Nursing / Care",
    "Medizin / Therapie": "Medicine / Therapy",
    "Apotheker / Drogisten": "Pharmacist / Drugstore",
    "Lehrperson / Schulleitung": "Teacher / School Management",
    "Sozialarbeit / Sozialpädagogik": "Social Work / Social Pedagogy",
    "Wissenschaft / Forschung": "Science / Research",
    "Gastronomie / Küche": "Gastronomy / Kitchen",
    "Hotellerie / Tourismus": "Hospitality / Tourism",
    "Landwirtschaft": "Agriculture",
    "Ackerbau": "Crop Farming",
    "Tierhaltung": "Animal Husbandry",
    "Analyse": "Analysis",
    "Analyst": "Analyst",
    "Versicherungsberatung / Aussendienst": "Insurance Advisory / Field Sales",
    "Underwriting / Risikoprüfung": "Underwriting / Risk Assessment",
    "Schadenmanagement / Claims": "Claims Management",
    "Leistungsmanagement (Krankenkasse)": "Benefits Management (Health Insurance)",
    "Versicherungsadministration / Innendienst": "Insurance Administration / Back Office",
    "Compliance / Risk / Legal (Versicherung)": "Compliance / Risk / Legal (Insurance)",
    "Produktmanagement / Aktuariat": "Product Management / Actuarial",
    "Agenturleiter / Generalagent": "Agency Director / General Agent",
    "Agrar / Lebensmittel": "Agriculture / Food",
    "Anlagenbau / Apparatebau": "Plant Engineering",
    "Automechanik / Autoelektrik / Carrosserie / Lack": "Auto Mechanics / Body & Paint",
    "Bademeister / Eismeister": "Pool / Ice Rink Attendant",
    "Bauleitung / Bauplanung / Gartenbau": "Construction Management / Landscaping",
    "Betriebstechnik / Betriebsingenieur": "Operations Engineering",
    "Chemie / Pharma / Biotech": "Chemistry / Pharma / Biotech",
    "Coiffeur / Kosmetik": "Hairdressing / Cosmetics",
    "Druck / Packaging / Papier": "Printing / Packaging / Paper",
    "Fahrzeuge / Velo / Motorrad": "Vehicles / Bicycle / Motorcycle",
    "Gebäudetechnik / HLKS": "Building Services / HVAC",
    "Hauswart / Reinigung": "Caretaker / Cleaning",
    "Holzbau / Schreinerei / Möbel": "Timber Construction / Carpentry",
    "Hörgeräteakustik / Optik": "Hearing Aids / Optics",
    "Kunst / Kultur / Theater / Museum": "Art / Culture / Theatre / Museum",
    "Lebensmittelproduktion / Bäckerei": "Food Production / Bakery",
    "Maler / Gipser / Isolierer": "Painter / Plasterer / Insulator",
    "Metallbau / Metallverarbeitung": "Metal Construction / Metalworking",
    "Medien / Journalismus": "Media / Journalism",
    "Mode / Textil / Leder": "Fashion / Textiles / Leather",
    "Sanitär / Heizung": "Plumbing / Heating",
    "Sicherheit / Polizei / Armee": "Security / Police / Military",
    "Sport / Freizeit / Wellness": "Sport / Leisure / Wellness",
    "Transport / Spedition / Kurier": "Transport / Freight / Courier",
    "Uhren / Schmuck / Edelsteine": "Watches / Jewellery / Gemstones",
    "Umwelt / Energie / Entsorgung": "Environment / Energy / Waste Management",
    "Verkehr / Bahn / Schifffahrt / Aviatik": "Transport / Rail / Shipping / Aviation",
    "Zahntechnik / Dentalhygiene": "Dental Technology / Dental Hygiene",
}

# ---------------------------------------------------------------------------
# Company types and formality levels (matching JobGenerationConfig literals)
# ---------------------------------------------------------------------------

COMPANY_TYPES = [
    "startup", "scaleup", "sme", "corporate",
    "public_sector", "social_sector", "agency",
    "consulting", "hospitality", "retail",
]

FORMALITIES = ["casual", "neutral", "formal"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _translate_title(de_name: str) -> str:
    """Return an English job title. Uses static map with passthrough fallback."""
    return _DE_EN_TITLE_MAP.get(de_name, de_name)


def _deduplicate_chunks(raw_chunks: List[dict]) -> Dict[str, Dict[str, dict]]:
    """
    Build mapping:  category_code → {"junior": chunk, "senior": chunk}.
    If duplicates exist (5 codes have 4 rows), keep the first seen.
    """
    by_code: Dict[str, Dict[str, dict]] = {}
    for chunk in raw_chunks:
        code = chunk["category_code"]
        sen = chunk["seniority"]
        if code not in by_code:
            by_code[code] = {}
        if sen not in by_code[code]:
            by_code[code][sen] = chunk
    return by_code


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def generate_dataset(
    duty_chunks_path: str,
    num_categories: int = 50,
    seed: int = 42,
) -> List[dict]:
    """
    Sample `num_categories` categories and build ~2*num_categories scenarios
    (one DE + one EN per category).

    Returns a list of EvalScenario dicts.
    """
    random.seed(seed)

    # Load all duty chunks
    raw_chunks: List[dict] = []
    with open(duty_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw_chunks.append(json.loads(line))

    if not raw_chunks:
        raise RuntimeError(f"No duty chunks found in {duty_chunks_path}")

    # Deduplicate
    by_code = _deduplicate_chunks(raw_chunks)
    all_codes = sorted(by_code.keys())

    # Clamp sample size
    num_categories = min(num_categories, len(all_codes))
    sampled_codes = random.sample(all_codes, num_categories)

    scenarios: List[dict] = []
    idx = 0

    for code in sampled_codes:
        code_chunks = by_code[code]

        # Randomly pick one seniority level for this category
        available_seniorities = sorted(code_chunks.keys())
        chosen_seniority = random.choice(available_seniorities)
        chunk = code_chunks[chosen_seniority]

        # Randomize config axes (same for both DE and EN of this category)
        company_type = random.choice(COMPANY_TYPES)
        formality = random.choice(FORMALITIES)

        for lang in ("de", "en"):
            idx += 1
            scenario_id = f"eval_{idx:04d}"

            if lang == "de":
                job_title = chunk["category_name"]
            else:
                job_title = _translate_title(chunk["category_name"])

            scenario = {
                "scenario_id": scenario_id,
                "job_title": job_title,
                "language": lang,
                "category_code": chunk["category_code"],
                "category_name": chunk["category_name"],
                "block_name": chunk["block_name"],
                "formality": formality,
                "company_type": company_type,
                "seniority_label": chosen_seniority,
                "duty_bullets": chunk["duties"],
                "duty_source": "category",
            }
            scenarios.append(scenario)

    return scenarios


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the JD Writer evaluation dataset from duty chunks."
    )
    parser.add_argument(
        "--chunks",
        default=str(Path(__file__).resolve().parent.parent / "duty_chunks.jsonl"),
        help="Path to duty_chunks.jsonl (default: project root)",
    )
    parser.add_argument(
        "--num", type=int, default=50,
        help="Number of categories to sample (default: 50 → ~100 scenarios)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent / "eval_dataset.json"),
        help="Output path for the generated dataset (default: evals/eval_dataset.json)",
    )
    args = parser.parse_args()

    print(f"[eval-dataset] Loading duty chunks from {args.chunks}")
    scenarios = generate_dataset(
        duty_chunks_path=args.chunks,
        num_categories=args.num,
        seed=args.seed,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(scenarios, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Stats
    de_count = sum(1 for s in scenarios if s["language"] == "de")
    en_count = sum(1 for s in scenarios if s["language"] == "en")
    print(f"[eval-dataset] Generated {len(scenarios)} scenarios ({de_count} DE, {en_count} EN)")
    print(f"[eval-dataset] Saved to {output_path}")

    # Show a sample
    print("\n[eval-dataset] Sample scenarios:")
    for s in scenarios[:4]:
        print(
            f"  {s['scenario_id']}  {s['language'].upper()}  "
            f"{s['seniority_label']:>6s}  {s['formality']:>7s}  "
            f"{s['company_type']:>14s}  {s['job_title'][:50]}"
        )
    if len(scenarios) > 4:
        print(f"  ... and {len(scenarios) - 4} more")


if __name__ == "__main__":
    main()
