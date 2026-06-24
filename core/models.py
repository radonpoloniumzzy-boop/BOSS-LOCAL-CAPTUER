from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_CSV_COLUMNS = [
    "name",
    "active_status",
    "expected_salary",
    "work_experience_text",
    "education_text",
    "tags_text",
    "summary_text",
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
    scroll_mode: str = "page"
    scroll_step: int = 900
    scroll_wait_seconds: float = 1.5
    max_scroll_count: int = 60
    no_new_stop_rounds: int = 3
    default_job_title: str = "Boss Recommended Talent"
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
    id: int | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
