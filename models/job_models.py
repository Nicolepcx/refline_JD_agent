from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Motivkompass Style Profile & Style Kit
# ---------------------------------------------------------------------------

class StyleProfile(BaseModel):
    """
    Motivkompass-based audience profile for copy generation.

    The 4-color model maps to two axes:
      proaktiv / reaktiv  ×  personenbezug / objektbezug

    Red   = Macher      (proaktiv  + objektbezug)
    Yellow = Entertainer (proaktiv  + personenbezug)
    Green  = Bewahrer    (reaktiv   + personenbezug)
    Blue   = Denker      (reaktiv   + objektbezug)
    """

    # Primary profile (always set)
    primary_color: Literal["red", "yellow", "green", "blue"] = "blue"
    # Secondary (only if within scoring margin of primary)
    secondary_color: Optional[Literal["red", "yellow", "green", "blue"]] = None

    # Two control axes derived from the PDFs
    interaction_mode: Literal["proaktiv", "reaktiv"] = "proaktiv"
    reference_frame: Literal["personenbezug", "objektbezug"] = "objektbezug"

    # Hard constraints – precedence: legal > brand > role > persuasion
    constraints: List[str] = Field(
        default_factory=list,
        description="e.g. 'no pressure language', 'use evidence', 'avoid hype', 'no emojis'",
    )

    # Scoring rationale (for transparency / debugging in UI / logs)
    scoring_rationale: Optional[str] = None


class StyleKit(BaseModel):
    """
    Compact style instruction set assembled from RAG or defaults.

    This is the ONLY style input to generation prompts.
    Agents consume this object — never raw PDF chunks.
    """

    profile: StyleProfile

    # Retrieved from RAG, scoped to profile color(s)
    do_and_dont: List[str] = Field(
        default_factory=list,
        description="6-10 bullets of do / don't rules",
    )
    preferred_adjectives: List[str] = Field(
        default_factory=list,
        description="10-20 adjectives matching the profile",
    )
    hook_templates: List[str] = Field(
        default_factory=list,
        description="3-6 hook / opening templates",
    )
    syntax_constraints: List[str] = Field(
        default_factory=list,
        description="2-4 sentence structure rules (proaktiv / reaktiv)",
    )

    def to_prompt_block(self, lang: str = "en") -> str:
        """Render as a compact prompt section for injection into any agent."""
        lines: List[str] = []

        header = "## Style Kit" if lang == "en" else "## Stil-Vorgaben"
        lines.append(header)
        lines.append(
            f"Primary style: {self.profile.primary_color}"
            + (f" + secondary: {self.profile.secondary_color}" if self.profile.secondary_color else "")
        )
        lines.append(
            f"Mode: {self.profile.interaction_mode} | Frame: {self.profile.reference_frame}"
        )

        if self.do_and_dont:
            lines.append("\n### Do / Don't:" if lang == "en" else "\n### Regeln:")
            lines.extend(f"- {item}" for item in self.do_and_dont)

        if self.preferred_adjectives:
            adj_label = "Preferred adjectives" if lang == "en" else "Bevorzugte Adjektive"
            lines.append(f"\n### {adj_label}: {', '.join(self.preferred_adjectives)}")

        if self.hook_templates:
            lines.append("\n### Hook templates:" if lang == "en" else "\n### Hook-Vorlagen:")
            lines.extend(f"- {h}" for h in self.hook_templates)

        if self.syntax_constraints:
            lines.append("\n### Sentence structure:" if lang == "en" else "\n### Satzstruktur:")
            lines.extend(f"- {c}" for c in self.syntax_constraints)

        if self.profile.constraints:
            lines.append("\n### Hard constraints (override all above):")
            lines.extend(f"- ⚠️ {c}" for c in self.profile.constraints)

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skill / Job models
# ---------------------------------------------------------------------------

class SkillItem(BaseModel):
    name: str = Field(..., description="Example: Java, Django, Kubernetes")
    category: Optional[str] = Field(
        default=None,
        description="Example: frontend, backend, cloud, database, devops, data",
    )
    level: Optional[str] = Field(
        default=None,
        description="Example: basic, intermediate, advanced, expert",
    )


class JobBody(BaseModel):
    job_description: str
    requirements: List[str]
    benefits: List[str]
    duties: List[str]
    summary: Optional[str] = None


class JobGenerationConfig(BaseModel):
    language: Literal["en", "de"] = "en"

    formality: Literal["casual", "neutral", "formal"] = "neutral"
    company_type: Literal[
        "startup",
        "scaleup",
        "corporate",
        "public_sector",
        "agency",
        "consulting",
    ] = "scaleup"

    industry: Literal[
        "generic",
        "finance",
        "healthcare",
        "public_it",
        "ai_startup",
        "ecommerce",
        "manufacturing",
    ] = "generic"

    seniority_label: Optional[Literal["intern", "junior", "mid", "senior", "lead", "principal"]] = None
    min_years_experience: Optional[int] = None
    max_years_experience: Optional[int] = None

    skills: List[SkillItem] = Field(default_factory=list)
    benefit_keywords: List[str] = Field(default_factory=list)

    @property
    def temperature(self) -> float:
        base = {
            "formal": 0.2,
            "neutral": 0.35,
            "casual": 0.55,
        }[self.formality]

        if self.company_type == "startup":
            base += 0.05
        elif self.company_type == "public_sector":
            base -= 0.05

        if self.seniority_label in ["senior", "lead", "principal"]:
            base -= 0.05
        elif self.seniority_label in ["intern", "junior"]:
            base += 0.05

        if self.industry in ["finance", "healthcare", "public_it"]:
            base -= 0.05
        elif self.industry in ["ai_startup", "ecommerce"]:
            base += 0.05

        base = max(0.1, min(base, 0.75))
        return base

    def with_industry_defaults(self) -> "JobGenerationConfig":
        cfg = self.model_copy(deep=True)

        if cfg.industry == "finance":
            if not cfg.benefit_keywords:
                cfg.benefit_keywords = [
                    "betriebliche Altersvorsorge",
                    "Weiterbildung im Bereich Finanzmarkt",
                    "Bonusregelung",
                    "hybrides Arbeiten",
                ]

        if cfg.industry == "healthcare":
            if not cfg.benefit_keywords:
                cfg.benefit_keywords = [
                    "Work Life Balance",
                    "betriebliche Gesundheitsförderung",
                    "sicherer Arbeitsplatz",
                ]

        if cfg.industry == "public_it":
            cfg.company_type = "public_sector"
            if not cfg.benefit_keywords:
                cfg.benefit_keywords = [
                    "Vereinbarkeit von Beruf und Familie",
                    "attraktive Sozialleistungen",
                    "sicheres Arbeitsumfeld im öffentlichen Dienst",
                ]

        if cfg.industry == "ai_startup":
            cfg.company_type = "startup"
            if not cfg.benefit_keywords:
                cfg.benefit_keywords = [
                    "remote friendly",
                    "stock options",
                    "Weiterbildungsbudget für Konferenzen",
                    "modernes Büro im Stadtzentrum",
                ]

        if cfg.industry == "ecommerce" and not cfg.benefit_keywords:
            cfg.benefit_keywords = [
                "Mitarbeiterrabatte",
                "flexible Arbeitszeiten",
                "hybrides Arbeiten",
            ]

        if cfg.industry == "manufacturing" and not cfg.benefit_keywords:
            cfg.benefit_keywords = [
                "attraktive Schichtmodelle",
                "Zuschuss zu Fahrtkosten",
                "betriebliche Altersvorsorge",
            ]

        return cfg

