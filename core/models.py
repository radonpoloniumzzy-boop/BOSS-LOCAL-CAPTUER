from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_CSV_COLUMNS = [
    "name",
    "city",
    "years_experience",
    "job_family",
    "job_track",
    "role_title",
    "latest_rating",
    "latest_confidence",
    "recommended_action",
    "evidence_json",
    "gap_json",
    "risk_json",
    "match_status",
    "recruitment_status",
    "latest_status_changed_at",
    "latest_status_from",
    "latest_status_to",
    "latest_reason_code",
    "latest_status_note",
    "latest_status_operator",
    "human_decision",
    "active_status",
    "expected_salary",
    "work_experience_text",
    "education_text",
    "tags_text",
    "summary_text",
    "industry_tags_json",
    "skill_tags_json",
    "profile_completeness",
    "last_active_at",
    "raw_card_text",
    "job_title",
    "source_url",
    "capture_time",
    "detail_url",
    "candidate_key",
]


@dataclass(slots=True)
class AIProviderConfig:
    provider: str = "openai"
    model: str = "gpt-5.4-mini"
    api_base: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AutomationFlowConfig:
    enabled: bool = False
    profile_id: int | None = None
    job_title: str = ""
    source_url: str = "https://www.zhipin.com/web/geek/recommend"
    max_candidates: int = 0
    provider: str = "openai"
    model: str = "gpt-5.4-mini"
    api_base: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AppConfig:
    browser_path: str = ""
    user_data_dir: str = ""
    default_export_dir: str = ""
    target_url: str = "https://www.zhipin.com/web/geek/recommend"
    local_api_port: int = 17863
    local_api_token: str = ""
    scroll_mode: str = "page"
    scroll_step: int = 900
    scroll_wait_seconds: float = 1.5
    max_scroll_count: int = 60
    no_new_stop_rounds: int = 3
    default_job_title: str = "Boss Recommended Talent"
    export_filename_template: str = "{job_title}_{date}_{time}_batch{batch_id}_{type}"
    resume_filename_template: str = "{candidate_name}_{job_title}_{date}_{original_name}"
    log_level: str = "INFO"
    selectors_path: str = ""
    csv_columns: list[str] = field(default_factory=lambda: list(DEFAULT_CSV_COLUMNS))
    ai_provider: AIProviderConfig = field(default_factory=AIProviderConfig)
    automation_flow: AutomationFlowConfig = field(default_factory=AutomationFlowConfig)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ai_provider"] = self.ai_provider.to_dict()
        payload["automation_flow"] = self.automation_flow.to_dict()
        return payload


@dataclass(slots=True)
class CollectOptions:
    job_title: str
    source_url: str
    note: str = ""
    auto_export: bool = False


@dataclass(slots=True)
class CandidateRecord:
    candidate_key: str
    raw_text_hash: str
    job_title: str
    source_url: str
    capture_time: str
    raw_card_text: str
    name: str = ""
    active_status: str = ""
    expected_salary: str = ""
    work_experience_text: str = ""
    education_text: str = ""
    tags_text: str = ""
    summary_text: str = ""
    detail_url: str = ""
    platform_uid: str = ""
    id: int | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CaptureBatch:
    job_title: str
    source_url: str
    start_time: str
    status: str
    note: str = ""
    id: int | None = None
    end_time: str = ""
    total_collected: int = 0
    total_new: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CaptureBatchItem:
    batch_id: int
    candidate_id: int
    candidate_key: str
    capture_time: str
    raw_text_hash: str
    job_title: str
    source_url: str
    raw_card_text: str
    name: str = ""
    active_status: str = ""
    expected_salary: str = ""
    work_experience_text: str = ""
    education_text: str = ""
    tags_text: str = ""
    summary_text: str = ""
    detail_url: str = ""
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CaptureProgress:
    batch_id: int | None
    status: str
    round_index: int
    loaded_cards: int
    total_unique: int
    total_inserted_candidates: int
    total_batch_items: int
    last_round_new: int
    consecutive_no_new: int
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CaptureRunResult:
    batch_id: int | None
    status: str
    total_unique: int
    total_inserted_candidates: int
    total_batch_items: int
    rounds_completed: int
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExportResult:
    file_path: str
    row_count: int
    mode: str
    export_format: str = "csv"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScreeningProfile:
    job_title: str
    jd_text: str
    prompt_text: str
    prompt_source: str = "generated"
    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    interview_checks: list[str] = field(default_factory=list)
    evidence_policy: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    parent_profile_id: int | None = None
    id: int | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScreeningResult:
    run_id: int
    candidate_id: int
    rating: str
    persona: str
    status: str = "completed"
    raw_response: str = ""
    error: str = ""
    confidence: str = ""
    evidence_json: str = "[]"
    gap_json: str = "[]"
    risk_json: str = "[]"
    recommended_action: str = ""
    id: int | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
