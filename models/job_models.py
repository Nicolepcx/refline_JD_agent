from typing import List, Optional, Literal
from pydantic import BaseModel, Field


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

