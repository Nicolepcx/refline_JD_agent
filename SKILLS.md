# SKILLS.md — Style Profile Scoring by Company & Role Type

> This file documents how the **Style Router** maps job configuration signals
> to Motivkompass color profiles.  It serves as the reference for tuning
> weights and understanding routing decisions.
>
> See `AGENTS.md` for the full taxonomy and workflow contracts.
> See `services/style_router.py` for the implementation.

---

## §1  Scoring Overview

The Style Router accumulates weights from **four dimensions**:
1. Industry
2. Company type
3. Formality
4. Seniority

Plus a **default bias of +0.10 for Blue** (safer for job ads).

The color with the highest total score becomes the **primary profile**.
If the runner-up is within **MARGIN = 0.15** of the primary, it becomes
the **secondary profile**.

---

## §2  Industry Signals

| Industry        | 🔴 Red | 🟡 Yellow | 🔵 Blue | 🟢 Green | Rationale |
|----------------|--------|-----------|---------|----------|-----------|
| `finance`       | —      | —         | **0.40** | 0.20    | Regulated, credibility-driven, evidence matters |
| `healthcare`    | —      | —         | 0.20    | **0.40** | Trust, safety, patient care, ethics-first |
| `social_care`   | —      | **0.20** | —       | **0.40** | Warmth, empathy, team belonging, people-oriented |
| `public_it`     | —      | —         | **0.30** | **0.30** | Structure + stability, public accountability |
| `ai_startup`    | 0.20   | **0.30** | —       | —        | Innovation, speed, creativity, disruption |
| `ecommerce`     | **0.30** | 0.20   | —       | —        | Growth-driven, competitive, conversion focus |
| `manufacturing` | —      | —         | **0.30** | 0.20    | Process quality, safety standards, precision |
| `generic`       | —      | —         | 0.10    | —        | Minimal signal — blue bias carries it |

---

## §3  Company Type Signals

| Company Type    | 🔴 Red | 🟡 Yellow | 🔵 Blue | 🟢 Green | Rationale |
|----------------|--------|-----------|---------|----------|-----------|
| `startup`       | 0.20   | **0.30** | —       | —        | Move fast, creative culture, flat hierarchy |
| `scaleup`       | **0.20** | —       | **0.20** | —       | Growth + structure balance |
| `sme`           | —      | —         | **0.20** | **0.20** | Pragmatic, close-knit teams, balanced culture |
| `corporate`     | —      | —         | **0.30** | 0.20    | Established processes, brand reputation |
| `public_sector` | —      | —         | **0.30** | **0.30** | Compliance, public trust, stability |
| `social_sector` | —      | —         | 0.20    | **0.40** | Mission-driven, trust, belonging, purpose |
| `agency`        | 0.20   | **0.30** | —       | —        | Client variety, creative output, fast delivery |
| `consulting`    | **0.30** | —       | 0.20    | —        | Results-driven, expert positioning |
| `hospitality`   | —      | **0.30** | —       | 0.20     | Team spirit, approachable, people-first |
| `retail`        | **0.20** | **0.20** | —       | —       | Dynamic, customer-facing, action-oriented |

---

## §4  Formality Signals

| Formality  | 🔴 Red | 🟡 Yellow | 🔵 Blue | 🟢 Green | Rationale |
|-----------|--------|-----------|---------|----------|-----------|
| `casual`   | 0.10   | **0.30** | —       | —        | Approachable, energetic, conversational |
| `neutral`  | —      | —         | **0.20** | —       | Professional baseline |
| `formal`   | —      | —         | **0.30** | 0.20    | Conservative, evidence-based, institutional |

---

## §5  Seniority Signals

| Seniority   | 🔴 Red | 🟡 Yellow | 🔵 Blue | 🟢 Green | Rationale |
|------------|--------|-----------|---------|----------|-----------|
| `intern`    | —      | 0.20      | —       | **0.30** | Welcoming, supportive, low-pressure |
| `junior`    | —      | **0.20** | —       | 0.10     | Growth-oriented, approachable |
| `mid`       | —      | —         | 0.10    | —        | Balanced, factual baseline |
| `senior`    | 0.10   | —         | **0.20** | —       | Expertise, autonomy, quality focus |
| `lead`      | **0.30** | —       | 0.20    | —        | Impact, decision-making, strategic |
| `principal` | 0.20   | —         | **0.30** | —       | Deep expertise, thought leadership |

---

## §6  Common Composite Scenarios

These examples show how signals combine in practice:

### Scenario A: "Senior Backend Engineer at a regulated Finance company, formal tone"
```
Industry  = finance     → blue +0.40, green +0.20
Company   = corporate   → blue +0.30, green +0.20
Formality = formal      → blue +0.30, green +0.20
Seniority = senior      → blue +0.20, red +0.10
Default                 → blue +0.10

Totals: blue=1.30  green=0.60  red=0.10  yellow=0.00
Result: Primary=blue, no secondary (gap > 0.15)
Mode: reaktiv, objektbezug
```

### Scenario B: "Junior Marketing Manager at an AI startup, casual tone"
```
Industry  = ai_startup  → yellow +0.30, red +0.20
Company   = startup     → yellow +0.30, red +0.20
Formality = casual      → yellow +0.30, red +0.10
Seniority = junior      → yellow +0.20, green +0.10
Default                 → blue +0.10

Totals: yellow=1.10  red=0.50  blue=0.10  green=0.10
Result: Primary=yellow, no secondary (gap > 0.15)
Mode: proaktiv, personenbezug
```

### Scenario C: "Lead Sales Director at a consulting firm, neutral tone"
```
Industry  = generic     → blue +0.10
Company   = consulting  → red +0.30, blue +0.20
Formality = neutral     → blue +0.20
Seniority = lead        → red +0.30, blue +0.20
Default                 → blue +0.10

Totals: blue=0.80  red=0.60  yellow=0.00  green=0.00
Result: Primary=blue, secondary=red (gap 0.20 > 0.15 → no secondary)
Mode: reaktiv, objektbezug
```

### Scenario D: "Intern Nursing Assistant at a healthcare organization, formal tone"
```
Industry  = healthcare  → green +0.40, blue +0.20
Company   = public_sec  → blue +0.30, green +0.30
Formality = formal      → blue +0.30, green +0.20
Seniority = intern      → green +0.30, yellow +0.20
Default                 → blue +0.10

Totals: green=1.20  blue=0.90  yellow=0.20  red=0.00
Result: Primary=green, no secondary (gap > 0.15)
Mode: reaktiv, personenbezug
```

---

## §7  Tuning Guide

### When to adjust weights

- If job ads for a specific industry consistently feel "off", increase/decrease
  the industry signal weights in `services/style_router.py`
- If users report tone drift between primary and secondary, tighten `_MARGIN`
- If a company has a strong brand personality, add it as a hard constraint
  in `StyleProfile.constraints` (future: UI field)

### Testing routing decisions

Use `explain_style_routing(cfg)` for a human-readable breakdown:

```python
from services.style_router import explain_style_routing
from models.job_models import JobGenerationConfig

cfg = JobGenerationConfig(
    language="de",
    industry="finance",
    company_type="corporate",
    formality="formal",
    seniority_label="senior",
)
print(explain_style_routing(cfg))
```

Output:
```
industry='finance' => blue+0.40, green+0.20
company_type='corporate' => blue+0.30, green+0.20
formality='formal' => blue+0.30, green+0.20
seniority='senior' => blue+0.20, red+0.10
Default blue bias => blue+0.10

Final scores: blue: 1.30 | green: 0.60 | red: 0.10 | yellow: 0.00
Primary: blue (1.30)
No secondary — gap 0.70 > margin 0.15
```

---

## §8  Next Steps: PDF-Sourced Profiles

Once the Motivkompass PDFs are ingested into RAG (see `AGENTS.md §5`),
the hardcoded defaults in `services/style_retriever.py` will be
supplemented (and eventually replaced) by retrieved chunks:

| Source PDF                          | Chunk Types              |
|-------------------------------------|--------------------------|
| Hooks-für-Stellenanzeigen           | Hook templates per color |
| Adjektive-Listen                    | Adjective lists per color |
| Satzstruktur (motivkompassansprache)| Syntax constraints       |
| Psychologische Faktoren            | Do/Don't rules, visual cues |

Each chunk is stored with metadata (`profile_color`, `dimension`, `language`,
`use_case`) for surgical retrieval.  See `services/style_retriever.py`
for the RAG query implementation.
