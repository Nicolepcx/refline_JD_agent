# AGENTS.md — Multi-Agent System Contracts

> This file defines the **workflow contracts**, **taxonomy**, and **hard rules**
> for the JD Writer Multi-Agent System (MAS).  Every agent in the graph MUST
> follow these rules.  The raw phrase banks and style data live in RAG —
> this file is the rulebook, not the library.

---

## §1  Motivkompass Taxonomy

The system uses a **4-color persuasion model** (Motivkompass) mapped to two axes:

|            | **Objektbezug** (fact-oriented) | **Personenbezug** (people-oriented) |
|------------|----------------------------------|--------------------------------------|
| **Proaktiv** (active) | 🔴 **Red — Macher**            | 🟡 **Yellow — Entertainer**          |
| **Reaktiv** (reflective) | 🔵 **Blue — Denker**           | 🟢 **Green — Bewahrer**             |

### Profiles at a glance

| Color  | Archetype    | Prefers                                         | Avoids                              |
|--------|-------------|--------------------------------------------------|---------------------------------------|
| Red    | Macher       | Speed, power, status, direct benefit, results    | Passive voice, committee-speak        |
| Yellow | Entertainer  | Freedom, fun, creativity, variety, team spirit   | Rigidity, formality, bureaucracy      |
| Blue   | Denker       | Facts, structure, statistics, quality, evidence  | Vague superlatives, hype, filler      |
| Green  | Bewahrer     | Harmony, trust, relationships, safety, belonging | Pressure, aggression, over-promising  |

### Axis semantics

- **Proaktiv** → short declarative sentences, active voice, imperatives allowed
- **Reaktiv** → longer connected sentences, conditional/inclusive phrasing
- **Personenbezug** → "you/we" framing, emotional cues, community language
- **Objektbezug** → third-person, evidence, data, process-oriented language

---

## §2  Style as a First-Class Artifact

Style is **NOT** an agent's personality.  It is a **parameter of the writing task**.

### Agent character vs. task style

| Dimension      | Scope          | Example                                         |
|----------------|----------------|--------------------------------------------------|
| **Character**  | Local to agent | Concise, reliable, non-theatrical                |
| **Style**      | Global/injectable | "Write in Blue voice with proaktiv sentence structure" |

Every generation agent has a **fixed operating character** (worker persona).
The **StyleKit** is injected as a structured prompt section and can change
from task to task.

### Data model

```
StyleProfile:
  primary_color:    red | yellow | green | blue
  secondary_color:  optional (within margin of primary)
  interaction_mode: proaktiv | reaktiv
  reference_frame:  personenbezug | objektbezug
  constraints:      list[str]   # hard overrides

StyleKit:
  profile:             StyleProfile
  do_and_dont:         list[str]   # 6-10 bullets
  preferred_adjectives: list[str]  # 10-20 words
  hook_templates:      list[str]   # 3-6 openers
  syntax_constraints:  list[str]   # 2-4 sentence rules
```

Agents consume `StyleKit.to_prompt_block(lang)` — a compact, ready-to-inject
text block.  They never see raw PDF chunks or full phrase banks.

---

## §3  Workflow Contracts

### Rule 1: Always call the Style Router before drafting public-facing copy

```
START ──→ style_router ──→ generator ──→ ...
```

The `style_router` node MUST execute before `generator`.  It places a
`StyleKit` on the blackboard.  If no signals are available, it defaults to
**blue-leaning** (safer, more credible, evidence-based).

### Rule 2: Always retrieve a style kit matching the chosen profile

The Style Router calls `retrieve_style_kit()` which:
1. Queries RAG (vector store) for atomic style chunks matching the profile color
2. Falls back to hardcoded defaults if RAG is empty or unavailable

The result is a compact StyleKit — never raw PDF content.

### Rule 3: Maximum two profiles per task

If multiple profiles score within the margin threshold:
- Pick **one primary** (argmax) and **one secondary** (runner-up)
- Generate copy **primarily in the primary voice**
- Optionally sprinkle secondary elements (max 2 adjectives + 1 hook)
- **Never blend more than two profiles** — it causes tone drift

### Rule 4: Conflict precedence order

When constraints from different sources conflict, resolve in this order:

1. **Legal & ethics** (always wins)
2. **Brand voice** (company-specific overrides)
3. **Role requirements** (seniority, industry norms)
4. **Persuasion profile** (Motivkompass style)

Example: if the persuasion profile says "use pressure language" but legal
constraints say "no pressure", legal wins.

### Rule 5: Sentence-start variety in bullet lists

Every bullet-point list (duties, requirements, benefits) MUST vary sentence
openings.  Repetitive patterns destroy readability and feel templated.

**Banned patterns:**

| Language | Anti-pattern | Why it fails |
|----------|-------------|--------------|
| DE | Every bullet starts with *«Sie …»* or *«Du …»* | Monotone, reads like a checklist |
| EN | Every bullet starts with *"As a [Role], you will…"* | Generic, no personality |
| EN | More than 2 bullets with *"be responsible for…"* | Passive, vague |
| DE | More than 2 bullets with *«…verantwortlich für»* | Same problem in German |

**Required variety techniques** (use at least 3 of these across any list of 5+ items):

1. **Lead with the object / topic area** — *"Cloud infrastructure: design and maintain…"* / *«Cloud-Infrastruktur: Entwurf und Wartung…»*
2. **Start with an action verb (imperative or infinitive)** — *"Design scalable APIs…"* / *«Skalierbare APIs entwerfen…»*
3. **Open with a context / situation** — *"In close collaboration with the data team, you…"* / *«In enger Zusammenarbeit mit dem Data-Team…»*
4. **Use a noun phrase or gerund** — *"Ownership of the CI/CD pipeline…"* / *«Verantwortung für die CI/CD-Pipeline…»*
5. **Vary the subject** — swap between *you/we/the team/this role* (EN) or *Sie/Wir/Das Team/Diese Rolle* (DE)

This rule applies to **all generation agents** that produce list content.

---

## §4  Style Routing Rubric

The Style Router uses a **scoring rubric**, not hard-mapping.

### Scoring signals

| Signal Dimension | Red Weight | Yellow Weight | Blue Weight | Green Weight |
|------------------|-----------|---------------|-------------|--------------|
| Safety/compliance industry | 0.0 | 0.0 | 0.4 | 0.2 |
| Growth/sales/outbound role | 0.3 | 0.0 | 0.0 | 0.0 |
| Creative/flexible startup  | 0.0 | 0.3 | 0.0 | 0.0 |
| Belonging/care/harmony EVP | 0.0 | 0.0 | 0.0 | 0.4 |
| Default bias (job ads)     | 0.0 | 0.0 | 0.10| 0.0 |

The full scoring table is implemented in `services/style_router.py` with
weights accumulated from `industry`, `company_type`, `formality`, and
`seniority_label`.

### Decision rule

```
primary = argmax(scores)
secondary = runner_up IF (primary_score - runner_up_score) < MARGIN
```

`MARGIN = 0.15` — prevents weak secondary colors from diluting the voice.

---

## §5  PDF Ingestion Rules

### Storage format

PDFs are ingested as **atomic knowledge units** (not full-page dumps) with:

| Chunk Type        | Example Content                            | Metadata Fields                           |
|-------------------|--------------------------------------------|-------------------------------------------|
| Hook templates    | "Lead. Build. Deliver."                    | profile_color, dimension=hooks, language   |
| Adjective lists   | "ambitious, driven, high-impact"           | profile_color, dimension=adjectives, lang  |
| Style constraints | "Short declarative sentences — SVO"         | profile_color, dimension=syntax, mode     |
| Do/Don't rules    | "DO: Use facts and evidence"               | profile_color, dimension=do_dont, lang     |
| Visual cues       | "Red + black imagery, bold fonts"          | profile_color, dimension=visuals, lang     |

### Metadata schema

```
profile_color:  red | yellow | green | blue | any
dimension:      hooks | adjectives | syntax | do_dont | visuals
language:        de | en
use_case:        job_ads | landing_pages | general_marketing
mode:            proaktiv | reaktiv  (optional, for syntax chunks)
```

### Retrieval contract

Retrieval is scoped by `profile_color` + `dimension`.  The retriever assembles
a StyleKit from matching chunks.  If fewer than 3 chunks are found for any
dimension, the retriever backfills from hardcoded defaults.

---

## §6  Agent Inventory

| Node Name          | Role               | Uses Style? | Has Store Access? |
|--------------------|---------------------|-------------|-------------------|
| `style_router`     | Profile selector    | Produces it | No                |
| `scrape_company`   | Company context     | No          | No                |
| `generator`        | Initial drafter     | Consumes it | Yes (gold stds)   |
| `ruler_scorer`     | Quality scorer      | No          | No                |
| `style_expert`     | HITL/RULER refiner  | Consumes it | Yes (gripes)      |
| `curator`          | Final selector      | No          | No                |
| `persist`          | Feedback storage    | No          | Yes (write)       |

---

## §7  Future Extensions

- [ ] **RAG ingestion pipeline** for Motivkompass PDFs (hooks, adjectives, syntax)
- [ ] **LLM-hybrid Style Router** for ambiguous cases (currently rules-only)
- [ ] **Channel-aware routing** (LinkedIn post vs. job ad vs. landing page)
- [ ] **Employer brand personality** input from UI config
- [ ] **Visual cue metadata** for creative generation
- [ ] **A/B test framework** for comparing style profiles on job ad performance
