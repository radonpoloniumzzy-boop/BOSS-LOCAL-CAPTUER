from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PromptTemplate:
    template_name: str
    template_text: str
    job_type: str = ""
    version: str = "v1"


@dataclass(slots=True)
class JobDescription:
    job_title: str
    jd_text: str
    version: str = "v1"


@dataclass(slots=True)
class ScreeningDecision:
    rating: str
    persona: str
    raw_response: str = ""
    confidence: str = ""
    evidence: list[dict[str, str]] | None = None
    gaps: list[str] | None = None
    risks: list[str] | None = None
    recommended_action: str = ""


@dataclass(slots=True)
class ScreeningProgress:
    run_id: int
    current: int
    total: int
    completed: int
    failed: int
    candidate_name: str
    rating: str = ""
    persona: str = ""
    message: str = ""
