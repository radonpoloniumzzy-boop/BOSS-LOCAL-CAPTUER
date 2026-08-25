from __future__ import annotations

import csv
import io
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from automation.parser import CandidateParser
from core.app_lock import ApplicationLockError
from core.bootstrap import BootstrapService, DataDirectoryError
from core.version import APP_VERSION
from core.models import RecruitmentTask, ScreeningProfile
from storage.repository import (
    CandidateDetailEnrichmentError,
    IdempotencyConflictError,
    InvalidJobProfileStatusTransitionError,
    InvalidRecruitmentTaskStatusTransitionError,
    JobProfileVersionConflictError,
)
from web.backend.batch_markdown import BatchMarkdownExporter
from web.backend.pairing import PairingCodeError
from web.backend.runtime import WebRuntime


SERVICE_NAME = "recruiting-talent-workbench"
WEB_CAPABILITIES = [
    "phase2c_pairing",
    "batch_markdown_export",
    "m2a_job_task_foundation",
    "m2b_external_rating_badges",
    "m2c_keyword_filter_highlights",
]


class ApiError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class SetupRequest(BaseModel):
    data_dir: str


class IntakeCandidatesRequest(BaseModel):
    source_platform: str = ""
    source_url: str = ""
    source_job_title: str = ""
    job_profile_id: int | None = None
    recruitment_task_id: int | None = None
    idempotency_key: str = ""
    candidates: list[dict[str, object]]


class PairingRequest(BaseModel):
    model_config = {"extra": "forbid"}

    pairing_code: str


class JobProfilePayload(BaseModel):
    model_config = {"extra": "forbid"}

    job_title: str
    department: str = ""
    hiring_manager: str = ""
    location: str = ""
    employment_type: str = ""
    experience_requirement: str = ""
    education_requirement: str = ""
    target_hires: int = 1
    recruitment_deadline: str = ""
    priority: str = "normal"
    status: str = "draft"
    jd_text: str = ""
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    interview_checks: list[str] = Field(default_factory=list)
    evidence_policy: dict[str, object] = Field(default_factory=dict)


class JobProfileUpdatePayload(JobProfilePayload):
    expected_version: int


class StatusPayload(BaseModel):
    model_config = {"extra": "forbid"}

    status: str


class JobProfileStatusPayload(StatusPayload):
    expected_version: int


class RecruitmentTaskPayload(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    role_id: int
    profile_version: int
    platform: str = "boss"
    source_url: str = ""
    target_candidates: int = 0


class PluginContextPayload(BaseModel):
    model_config = {"extra": "forbid"}

    recruitment_task_id: int | None = None


class KeywordRulesPayload(BaseModel):
    model_config = {"extra": "forbid"}

    expected_version: int
    keyword_rules: dict[str, object] = Field(default_factory=dict)


class ExternalRatingsImportRequest(BaseModel):
    model_config = {"extra": "forbid"}

    text: str = ""
    rows: list[dict[str, object]] = Field(default_factory=list)
    source_note: str = ""


class CandidateDetailEnrichmentRequest(BaseModel):
    model_config = {"extra": "forbid"}

    source_platform: str = ""
    platform_uid: str = ""
    source_url: str = ""
    detail_url: str = ""
    capture_time: str = ""
    recruitment_task_id: int | None = None
    job_profile_id: int | None = None
    raw_card_text: str = ""
    active_status: str = ""
    expected_salary: str = ""
    work_experience_text: str = ""
    education_text: str = ""
    tags_text: str = ""
    summary_text: str = ""
    city: str = ""
    years_experience: int | None = None
    job_family: str = ""
    job_track: str = ""


_CANDIDATE_LIST_FIELDS = (
    "id",
    "name",
    "source_platform",
    "latest_source_platform",
    "latest_source_job_title",
    "latest_batch_id",
    "latest_capture_time",
    "latest_ingest_status",
    "latest_rating",
    "latest_batch_role_id",
    "has_role_binding",
    "batch_count",
)

_CANDIDATE_DETAIL_FIELDS = (
    "id",
    "name",
    "source_platform",
    "latest_source_platform",
    "latest_source_job_title",
    "latest_batch_id",
    "latest_capture_time",
    "latest_ingest_status",
    "latest_rating",
    "latest_batch_role_id",
    "has_role_binding",
    "batch_count",
    "job_title",
    "source_url",
    "capture_time",
    "raw_card_text",
    "active_status",
    "expected_salary",
    "work_experience_text",
    "education_text",
    "tags_text",
    "summary_text",
    "detail_url",
    "latest_raw_card_text",
    "latest_source_url",
    "latest_detail_url",
    "city",
    "years_experience",
    "job_family",
    "job_track",
)

_CANDIDATE_APPEARANCE_FIELDS = (
    "batch_id",
    "source_platform",
    "source_job_title",
    "capture_time",
    "ingest_status",
)

_JOB_PROFILE_LIST_FIELDS = (
    "id",
    "job_title",
    "department",
    "location",
    "employment_type",
    "target_hires",
    "priority",
    "status",
    "version",
    "updated_at",
)

_JOB_PROFILE_DETAIL_FIELDS = (
    *_JOB_PROFILE_LIST_FIELDS,
    "hiring_manager",
    "experience_requirement",
    "education_requirement",
    "recruitment_deadline",
    "jd_text",
    "must_have",
    "nice_to_have",
    "risk_flags",
    "exclusions",
    "interview_checks",
    "evidence_policy",
    "created_at",
)

_RECRUITMENT_TASK_FIELDS = (
    "id",
    "name",
    "role_id",
    "role_title",
    "profile_version",
    "platform",
    "source_url",
    "target_candidates",
    "status",
    "current_step",
    "latest_message",
    "batch_count",
    "candidate_count",
    "run_count",
    "export_count",
    "created_at",
    "updated_at",
)

_RECRUITMENT_TASK_PROGRESS_FIELDS = (
    "task_id",
    "task_name",
    "task_status",
    "job_profile_id",
    "job_profile_version",
    "job_title",
    "target_count",
    "is_plugin_context",
    "batch_count",
    "batch_item_count",
    "unique_candidate_count",
    "total_received",
    "total_added",
    "total_updated",
    "total_skipped",
    "total_failed",
    "rated_candidate_count",
    "unrated_candidate_count",
    "rating_counts",
    "first_capture_time",
    "latest_capture_time",
    "recent_batches",
)

_RECENT_BATCH_FIELDS = (
    "batch_id",
    "source_platform",
    "status",
    "start_time",
    "received",
    "added",
    "updated",
    "skipped",
    "failed",
)


def _project_candidate_list_row(row: dict[str, object]) -> dict[str, object]:
    return {field: row.get(field) for field in _CANDIDATE_LIST_FIELDS}


def _project_candidate_detail(detail: dict[str, object]) -> dict[str, object]:
    candidate = dict(detail["candidate"])
    standard_profile = detail.get("standard_profile")
    if isinstance(standard_profile, dict):
        candidate.update(
            {
                "city": standard_profile.get("city"),
                "years_experience": standard_profile.get("years_experience"),
                "job_family": standard_profile.get("job_family"),
                "job_track": standard_profile.get("job_track"),
            }
        )
    return {field: candidate.get(field) for field in _CANDIDATE_DETAIL_FIELDS}


def _project_candidate_appearance(row: dict[str, object]) -> dict[str, object]:
    return {field: row.get(field) for field in _CANDIDATE_APPEARANCE_FIELDS}


def _project_job_profile(row: dict[str, object], *, detail: bool = False) -> dict[str, object]:
    fields = _JOB_PROFILE_DETAIL_FIELDS if detail else _JOB_PROFILE_LIST_FIELDS
    return {field: row.get(field) for field in fields}


def _project_job_version(row: dict[str, object]) -> dict[str, object]:
    snapshot = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
    return {
        "version": row.get("version"),
        "created_at": row.get("created_at"),
        "snapshot": _project_job_profile(snapshot, detail=True),
    }


def _project_recruitment_task(row: dict[str, object]) -> dict[str, object]:
    return {field: row.get(field) for field in _RECRUITMENT_TASK_FIELDS}


def _project_recruitment_task_progress(row: dict[str, object]) -> dict[str, object]:
    projected = {field: row.get(field) for field in _RECRUITMENT_TASK_PROGRESS_FIELDS}
    projected["rating_counts"] = {
        rating: int((row.get("rating_counts") or {}).get(rating, 0))  # type: ignore[union-attr]
        for rating in _STANDARD_RATINGS
    }
    projected["recent_batches"] = [
        {field: batch.get(field) for field in _RECENT_BATCH_FIELDS}
        for batch in row.get("recent_batches", [])
        if isinstance(batch, dict)
    ]
    return projected


_STANDARD_RATINGS = ("UR", "SSR", "SR", "R", "N")
_HEADER_ALIASES = {
    "candidate_id": {"candidate_id", "id"},
    "name": {"name", "candidate_name", "candidate name", "candidate", "姓名", "候选人", "候选人姓名"},
    "rating": {"rating", "current rating", "current_rating", "grade", "评级", "当前评级", "外部评级", "候选人评级", "等级", "当前等级"},
    "track": {"track", "category", "direction", "方向", "推荐方向", "最值得看的方向", "适合方向", "定位"},
    "reason": {"reason", "note", "rationale", "comment", "assessment", "判断", "理由", "说明", "摘要", "评价", "评语", "结论"},
    "batch_id": {"batch_id"},
    "source_platform": {"source_platform"},
    "source_job_title": {"source_job_title", "job_title"},
}
_IGNORED_EXTERNAL_HEADERS = {"排名", "序号", "编号", "rank", "no", "number", "#"}


def _clean_external_cell(value: object) -> str:
    text = str(value or "").strip()
    changed = True
    while changed:
        changed = False
        for marker in ("**", "__"):
            if text.startswith(marker) and text.endswith(marker) and len(text) >= len(marker) * 2:
                text = text[len(marker) : -len(marker)].strip()
                changed = True
    return text


def _normalize_external_header(value: object) -> str:
    text = _clean_external_cell(value).strip().lower()
    return re.sub(r"[\s_-]+", "_", text)


def _canonical_external_field(header: object) -> str | None:
    normalized = _normalize_external_header(header)
    if normalized in {_normalize_external_header(alias) for alias in _IGNORED_EXTERNAL_HEADERS}:
        return None
    for field, aliases in _HEADER_ALIASES.items():
        if normalized in {_normalize_external_header(alias) for alias in aliases}:
            return field
    return None


def _is_markdown_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    non_empty = [cell.strip().replace(" ", "") for cell in cells if cell.strip()]
    if not non_empty:
        return False
    return all(bool(re.fullmatch(r":?-{2,}:?", cell)) for cell in non_empty)


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [_clean_external_cell(cell) for cell in stripped.split("|")]


def _normalize_external_rating(value: object) -> tuple[str, str, str]:
    original = _clean_external_cell(value)
    compact = re.sub(r"\s+", "", original.upper())
    if not compact:
        return "", original, "invalid"
    if compact in _STANDARD_RATINGS:
        return compact, original, "exact"
    found = re.findall(r"(?<![A-Z])(SSR|UR|SR|R|N)(?![A-Z])", compact)
    for token in re.findall(r"强(SSR|UR|SR|R|N)", compact):
        found.append(token)
    unique: list[str] = []
    for rating in found:
        if rating not in unique:
            unique.append(rating)
    if len(unique) > 1:
        return "", original, "needs_confirmation"
    if len(unique) == 1:
        rating = unique[0]
        if compact in {f"强{rating}", f"{rating}+", f"{rating}-"}:
            return rating, original, "normalized"
    return "", original, "invalid"


def _finalize_external_rating_row(row: dict[str, object], *, line: int) -> dict[str, object]:
    normalized, original, status = _normalize_external_rating(row.get("rating") or row.get("original_rating") or "")
    explicit_rating = _clean_external_cell(row.get("rating"))
    if explicit_rating.upper() in _STANDARD_RATINGS:
        normalized = explicit_rating.upper()
        status = "exact" if _clean_external_cell(row.get("original_rating")) in {"", normalized} else "normalized"
    return {
        "line": int(row.get("line") or line),
        "candidate_id": _clean_external_cell(row.get("candidate_id")),
        "name": _clean_external_cell(row.get("name") or row.get("candidate_name")),
        "rating": normalized,
        "original_rating": _clean_external_cell(row.get("original_rating")) or original or explicit_rating,
        "rating_status": status,
        "track": _clean_external_cell(row.get("track") or row.get("category")),
        "reason": _clean_external_cell(row.get("reason") or row.get("note") or row.get("rationale")),
        "batch_id": _clean_external_cell(row.get("batch_id")),
        "source_platform": _clean_external_cell(row.get("source_platform")),
        "source_job_title": _clean_external_cell(row.get("source_job_title") or row.get("job_title")),
    }


def _rows_from_delimited_text(text: str) -> list[list[str]]:
    sample = text[:4096]
    delimiter = "\t" if "\t" in sample else ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[_clean_external_cell(cell) for cell in row] for row in reader if any(str(cell).strip() for cell in row)]


def _parse_external_rating_rows(payload: ExternalRatingsImportRequest) -> list[dict[str, object]]:
    if payload.rows:
        return [_finalize_external_rating_row(dict(row), line=index) for index, row in enumerate(payload.rows, start=1)]
    text = payload.text.strip()
    if not text:
        return []
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    if non_empty_lines and non_empty_lines[0].strip().startswith("|"):
        raw_rows = [_split_markdown_row(line) for line in non_empty_lines if "|" in line]
        raw_rows = [row for row in raw_rows if not _is_markdown_separator_row(row)]
    else:
        raw_rows = _rows_from_delimited_text(text)
    if not raw_rows:
        return []
    headers = [_canonical_external_field(cell) for cell in raw_rows[0]]
    has_header = "name" in headers and "rating" in headers
    body = raw_rows[1:] if has_header else raw_rows
    rows: list[dict[str, object]] = []
    for line_number, raw in enumerate(body, start=2 if has_header else 1):
        if has_header:
            mapped = {field: raw[index] for index, field in enumerate(headers) if field and index < len(raw)}
            mapped["line"] = line_number
            rows.append(_finalize_external_rating_row(mapped, line=line_number))
        else:
            rows.append(_finalize_external_rating_row({"name": raw[0] if len(raw) > 0 else "", "rating": raw[1] if len(raw) > 1 else ""}, line=line_number))
    return rows


def _job_payload_to_profile(payload: JobProfilePayload, *, profile_id: int | None = None) -> ScreeningProfile:
    return ScreeningProfile(
        id=profile_id,
        job_title=payload.job_title.strip(),
        department=payload.department.strip(),
        hiring_manager=payload.hiring_manager.strip(),
        location=payload.location.strip(),
        employment_type=payload.employment_type.strip(),
        experience_requirement=payload.experience_requirement.strip(),
        education_requirement=payload.education_requirement.strip(),
        target_hires=max(1, int(payload.target_hires or 1)),
        recruitment_deadline=payload.recruitment_deadline.strip(),
        priority=payload.priority.strip() or "normal",
        status=payload.status.strip() or "draft",
        jd_text=payload.jd_text,
        prompt_text="",
        prompt_source="generated",
        must_have=[str(value).strip() for value in payload.must_have if str(value).strip()],
        nice_to_have=[str(value).strip() for value in payload.nice_to_have if str(value).strip()],
        risk_flags=[str(value).strip() for value in payload.risk_flags if str(value).strip()],
        exclusions=[str(value).strip() for value in payload.exclusions if str(value).strip()],
        interview_checks=[str(value).strip() for value in payload.interview_checks if str(value).strip()],
        evidence_policy=dict(payload.evidence_policy or {}),
    )


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_web_app(
    bootstrap: BootstrapService,
    *,
    lock_root: Path | None = None,
    frontend_dist: Path | None = None,
) -> FastAPI:
    runtime = WebRuntime(bootstrap, lock_root=lock_root)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            runtime.close()

    app = FastAPI(title="招聘人才 Mapping 工作台", version=APP_VERSION, lifespan=lifespan)
    app.state.runtime = runtime
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])

    @app.middleware("http")
    async def protect_state_changes(request: Request, call_next):
        configured = bootstrap.store.load()
        web_port = configured.web_port if configured else 17864
        if request.headers.get("host") != f"127.0.0.1:{web_port}":
            return error_response(400, "invalid_host", "本地工作台只接受配置端口上的本机请求。")
        expected = f"http://127.0.0.1:{web_port}"
        origin = str(request.headers.get("origin") or "")
        extension_paths = {
            "/api/intake/candidates",
            "/api/plugin/pair",
            "/api/plugin/connection/check",
            "/api/plugin/context",
            "/api/plugin/ratings/badges",
            "/api/plugin/keyword-rules",
            "/api/plugin/candidate-detail/enrich",
        }
        extension_allowed = request.url.path in extension_paths or (
            request.url.path.startswith("/api/capture-batches/")
            and request.url.path.endswith("/export.md")
        )
        is_extension = origin.startswith("chrome-extension://")
        if request.method == "OPTIONS" and is_extension:
            if not extension_allowed:
                return error_response(403, "same_origin_required", "请求来源无效，请从本地工作台页面操作。")
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, X-Boss-Local-Token",
                    "Vary": "Origin",
                },
            )
        if is_extension and not extension_allowed:
            return error_response(403, "same_origin_required", "请求来源无效，请从本地工作台页面操作。")
        if origin and origin != expected and not (is_extension and extension_allowed):
            return error_response(403, "same_origin_required", "请求来源无效，请从本地工作台页面操作。")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.url.path.startswith("/api/")
            and origin != expected
            and not (is_extension and extension_allowed)
        ):
            return error_response(403, "same_origin_required", "请求来源无效，请从本地工作台页面操作。")
        response = await call_next(request)
        if is_extension and extension_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    @app.exception_handler(DataDirectoryError)
    async def handle_data_directory_error(_request: Request, exc: DataDirectoryError):
        status = 409 if bootstrap.store.load() is not None else 400
        return error_response(status, "invalid_data_directory", str(exc))

    @app.exception_handler(ApplicationLockError)
    async def handle_lock_error(_request: Request, exc: ApplicationLockError):
        return error_response(409, "database_in_use", str(exc))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, _exc: RequestValidationError):
        return error_response(422, "invalid_request", "请求内容不完整或格式不正确。")

    @app.exception_handler(HTTPException)
    async def handle_http_error(_request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败。"
        return error_response(exc.status_code, "request_failed", detail)

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError):
        return error_response(exc.status_code, exc.code, str(exc))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, _exc: Exception):
        return error_response(500, "internal_error", "本地服务处理请求时发生错误。")

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": APP_VERSION,
            "capabilities": WEB_CAPABILITIES,
        }

    @app.get("/api/setup/status")
    def setup_status() -> dict[str, object]:
        return bootstrap.status()

    @app.post("/api/setup")
    def setup(payload: SetupRequest) -> dict[str, object]:
        return runtime.setup(payload.data_dir)

    @app.get("/api/app/status")
    def app_status() -> dict[str, object]:
        if runtime.repository is None:
            if runtime.database_fault is not None:
                raise ApiError(
                    503,
                    runtime.database_fault.code,
                    runtime.database_fault.message,
                )
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        stats = runtime.repository.get_dashboard_stats()
        configured = bootstrap.store.load()
        return {
            "status": "ready",
            "version": APP_VERSION,
            "database_ready": True,
            "data_dir": configured.data_dir if configured else "",
            "candidate_count": int(stats["total_candidates"]),
            "batch_count": int(stats["total_batches"]),
            "latest_batch_id": int(stats["latest_batch_id"]),
            "latest_batch_status": str(stats["latest_batch_status"]),
        }

    def require_local_api_token(x_boss_local_token: str = Header(default="")) -> None:
        try:
            runtime.authenticate_plugin_token(str(x_boss_local_token or ""))
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc
        except PermissionError as exc:
            raise ApiError(401, "unauthorized", "本地写入鉴权失败。")

    @app.get("/api/plugin-connection/status")
    def plugin_connection_status() -> dict[str, object]:
        configured = bootstrap.store.load()
        return {
            "service_ok": True,
            "api_base": f"http://127.0.0.1:{configured.web_port if configured else 17864}",
            "last_verified_at": runtime.pairing.last_verified_at,
            "connected": bool(runtime.pairing.last_verified_at),
            "data_dir": configured.data_dir if configured else "",
        }

    @app.post("/api/plugin-connection/pairing-code")
    def create_pairing_code() -> dict[str, object]:
        if runtime.config_service is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        pairing = runtime.pairing.create_code(ttl_seconds=300)
        configured = bootstrap.store.load()
        api_base = f"http://127.0.0.1:{configured.web_port if configured else 17864}"
        return {
            "pairing_code": pairing.code,
            "pairing_uri": f"boss-local://web-pair?{urlencode({'apiBase': api_base, 'pairingCode': pairing.code})}",
            "expires_at": pairing.expires_at.isoformat(timespec="seconds"),
            "expires_in_seconds": 300,
        }

    @app.post("/api/plugin/pair")
    def pair_plugin(payload: PairingRequest) -> dict[str, object]:
        if runtime.config_service is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        configured = bootstrap.store.load()
        try:
            api_token, verified_at = runtime.pair_plugin(payload.pairing_code)
        except PairingCodeError as exc:
            status = 410 if exc.code in {"pairing_code_expired", "pairing_code_used"} else 400
            raise ApiError(status, exc.code, str(exc)) from exc
        return {
            "api_base": f"http://127.0.0.1:{configured.web_port if configured else 17864}",
            "api_token": api_token,
            "verified_at": verified_at,
            "remember_connection": True,
        }

    @app.get("/api/plugin/connection/check")
    def check_plugin_connection(x_boss_local_token: str = Header(default="")) -> dict[str, object]:
        try:
            verified_at = runtime.verify_plugin_connection(str(x_boss_local_token or ""))
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc
        except PermissionError as exc:
            raise ApiError(401, "unauthorized", "本地写入鉴权失败。") from exc
        return {"ok": True, "verified_at": verified_at}

    @app.post("/api/plugin-connection/revoke")
    def revoke_plugin_connection() -> dict[str, object]:
        if runtime.config_service is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        runtime.revoke_plugin_connection()
        return {"revoked": True, "message": "现有插件连接已撤销，请重新配对。"}

    @app.put("/api/plugin-context")
    def set_plugin_context(payload: PluginContextPayload) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            context = runtime.set_plugin_context(payload.recruitment_task_id)
        except ValueError as exc:
            raise ApiError(409, "plugin_context_unavailable", str(exc)) from exc
        return {
            "ok": True,
            "context": context,
            "message": "已更新插件当前任务。" if context else "已清除插件当前任务。",
        }

    @app.get("/api/plugin-context")
    def get_web_plugin_context() -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            return {"context": runtime.get_plugin_context()}
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc

    @app.get("/api/plugin/context")
    def get_plugin_context(_auth: None = Depends(require_local_api_token)) -> dict[str, object]:
        try:
            context = runtime.get_plugin_context()
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc
        if context is None:
            raise ApiError(409, "context_unavailable", "当前未选择可用招聘任务。")
        return context

    @app.get("/api/plugin/keyword-rules")
    def get_plugin_keyword_rules(_auth: None = Depends(require_local_api_token)) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            context = runtime.get_plugin_context()
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc
        if context is None:
            raise ApiError(409, "context_unavailable", "当前未选择可用招聘任务。")
        rules = runtime.repository.get_task_keyword_rules(int(context["recruitment_task_id"]))
        return {
            "task_id": rules["task_id"],
            "job_profile_id": rules["job_profile_id"],
            "job_profile_version": rules["job_profile_version"],
            "task_status": rules["task_status"],
            "keyword_rules": rules["keyword_rules"],
        }

    @app.post("/api/intake/candidates")
    def intake_candidates(
        payload: IntakeCandidatesRequest,
        _auth: None = Depends(require_local_api_token),
    ) -> dict[str, object]:
        if runtime.import_service is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            return runtime.import_service.import_candidates(payload.model_dump())
        except IdempotencyConflictError as exc:
            raise ApiError(409, "idempotency_conflict", str(exc)) from exc
        except ValueError as exc:
            raise ApiError(400, "invalid_request", str(exc)) from exc

    @app.post("/api/plugin/candidate-detail/enrich")
    def enrich_candidate_detail(
        payload: CandidateDetailEnrichmentRequest,
        _auth: None = Depends(require_local_api_token),
    ) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            context = runtime.get_plugin_context()
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc
        if context is None:
            raise ApiError(409, "context_unavailable", "当前未选择可用招聘任务。")

        source_platform = CandidateParser.normalize_source_platform(
            payload.source_platform,
            payload.source_url or payload.detail_url,
        )
        platform_uid = CandidateParser.canonicalize_platform_uid(
            source_platform,
            payload.platform_uid,
        )
        try:
            return runtime.repository.enrich_existing_candidate_detail(
                task_id=int(context["recruitment_task_id"]),
                job_profile_id=payload.job_profile_id,
                recruitment_task_id=payload.recruitment_task_id,
                source_platform=source_platform,
                platform_uid=platform_uid,
                source_url=payload.source_url,
                detail_url=payload.detail_url,
                capture_time=payload.capture_time,
                raw_card_text=payload.raw_card_text,
                active_status=payload.active_status,
                expected_salary=payload.expected_salary,
                work_experience_text=payload.work_experience_text,
                education_text=payload.education_text,
                tags_text=payload.tags_text,
                summary_text=payload.summary_text,
                city=payload.city,
                years_experience=payload.years_experience,
                job_family=payload.job_family,
                job_track=payload.job_track,
            )
        except CandidateDetailEnrichmentError as exc:
            status = 400
            if exc.code in {"context_unavailable", "detail_context_mismatch"}:
                status = 409
            raise ApiError(status, exc.code, str(exc)) from exc
        except sqlite3.DatabaseError as exc:
            raise ApiError(500, "detail_enrichment_failed", "候选人详情写入失败，已回滚本次更新。") from exc
        except ValueError as exc:
            raise ApiError(400, "invalid_request", str(exc)) from exc

    @app.get("/api/job-profiles")
    def list_job_profiles() -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        return {"rows": [_project_job_profile(row) for row in runtime.repository.list_job_profiles()]}

    @app.post("/api/job-profiles")
    def create_job_profile(payload: JobProfilePayload) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            profile, _changed = runtime.repository.save_web_job_profile(_job_payload_to_profile(payload))
        except InvalidJobProfileStatusTransitionError as exc:
            raise ApiError(409, "invalid_job_profile_status_transition", str(exc)) from exc
        except ValueError as exc:
            raise ApiError(400, "invalid_request", str(exc)) from exc
        return _project_job_profile(profile.to_dict(), detail=True)

    @app.get("/api/job-profiles/{profile_id}")
    def get_job_profile(profile_id: int) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        profile = runtime.repository.get_job_profile(profile_id)
        if profile is None:
            raise ApiError(404, "job_profile_not_found", "岗位档案不存在。")
        return _project_job_profile(profile, detail=True)

    @app.put("/api/job-profiles/{profile_id}")
    def update_job_profile(profile_id: int, payload: JobProfileUpdatePayload) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            profile, changed = runtime.repository.save_web_job_profile(
                _job_payload_to_profile(payload, profile_id=profile_id),
                expected_version=payload.expected_version,
            )
        except JobProfileVersionConflictError as exc:
            raise ApiError(409, "job_profile_version_conflict", str(exc)) from exc
        except InvalidJobProfileStatusTransitionError as exc:
            raise ApiError(409, "invalid_job_profile_status_transition", str(exc)) from exc
        except ValueError as exc:
            raise ApiError(400, "invalid_request", str(exc)) from exc
        return {**_project_job_profile(profile.to_dict(), detail=True), "changed": changed}

    @app.get("/api/job-profiles/{profile_id}/versions")
    def list_job_profile_versions(profile_id: int) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        if runtime.repository.get_job_profile(profile_id) is None:
            raise ApiError(404, "job_profile_not_found", "岗位档案不存在。")
        return {
            "rows": [
                _project_job_version(row)
                for row in runtime.repository.list_job_profile_versions(profile_id)
            ]
        }

    @app.post("/api/job-profiles/{profile_id}/status")
    def set_job_profile_status(profile_id: int, payload: JobProfileStatusPayload) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            profile = runtime.set_job_profile_status(
                profile_id,
                payload.status,
                expected_version=payload.expected_version,
            )
        except JobProfileVersionConflictError as exc:
            raise ApiError(409, "job_profile_version_conflict", str(exc)) from exc
        except InvalidJobProfileStatusTransitionError as exc:
            raise ApiError(409, "invalid_job_profile_status_transition", str(exc)) from exc
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc
        except ValueError as exc:
            code = "job_profile_not_found" if "不存在" in str(exc) else "invalid_request"
            raise ApiError(404 if code == "job_profile_not_found" else 400, code, str(exc)) from exc
        return _project_job_profile(profile.to_dict(), detail=True)

    @app.get("/api/recruitment-tasks")
    def list_recruitment_tasks(role_id: int | None = None) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        rows = runtime.repository.list_recruitment_tasks(role_id=role_id)
        summaries = []
        for row in rows:
            summaries.append(_project_recruitment_task(runtime.repository.get_recruitment_task_summary(int(row["id"]))))
        return {"rows": summaries}

    @app.post("/api/recruitment-tasks")
    def create_recruitment_task(payload: RecruitmentTaskPayload) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        task = RecruitmentTask(
            name=payload.name.strip(),
            role_id=payload.role_id,
            profile_version=payload.profile_version,
            platform=payload.platform,
            source_url=payload.source_url.strip(),
            target_candidates=max(0, int(payload.target_candidates or 0)),
            target_ssr=0,
            minimum_rating="SR",
            view_quota=0,
            greeting_quota=0,
            current_step="待启动",
            latest_message="",
        )
        try:
            saved = runtime.repository.save_recruitment_task(task)
            return _project_recruitment_task(runtime.repository.get_recruitment_task_summary(int(saved.id)))
        except ValueError as exc:
            raise ApiError(400, "invalid_request", str(exc)) from exc

    @app.get("/api/recruitment-tasks/{task_id}")
    def get_recruitment_task(task_id: int) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            return _project_recruitment_task(runtime.repository.get_recruitment_task_summary(task_id))
        except ValueError as exc:
            raise ApiError(404, "recruitment_task_not_found", str(exc)) from exc

    @app.get("/api/recruitment-tasks/{task_id}/progress")
    def get_recruitment_task_progress(task_id: int) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            context = runtime.get_plugin_context()
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc
        is_context = bool(context and int(context["recruitment_task_id"]) == int(task_id))
        try:
            progress = runtime.repository.get_recruitment_task_progress(
                task_id,
                is_plugin_context=is_context,
            )
        except ValueError as exc:
            raise ApiError(404, "task_not_found", "招聘任务不存在。") from exc
        return _project_recruitment_task_progress(progress)

    @app.post("/api/recruitment-tasks/{task_id}/status")
    def set_recruitment_task_status(task_id: int, payload: StatusPayload) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            saved = runtime.set_recruitment_task_status(task_id, payload.status)
        except InvalidRecruitmentTaskStatusTransitionError as exc:
            raise ApiError(409, "invalid_recruitment_task_status_transition", str(exc)) from exc
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc
        except ValueError as exc:
            raise ApiError(400, "invalid_request", str(exc)) from exc
        return _project_recruitment_task(runtime.repository.get_recruitment_task_summary(int(saved.id)))

    @app.get("/api/recruitment-tasks/{task_id}/keyword-rules")
    def get_task_keyword_rules(task_id: int) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            return runtime.repository.get_task_keyword_rules(task_id)
        except InvalidRecruitmentTaskStatusTransitionError as exc:
            raise ApiError(409, "keyword_rules_task_not_running", str(exc)) from exc
        except ValueError as exc:
            raise ApiError(404, "recruitment_task_not_found", str(exc)) from exc

    @app.put("/api/recruitment-tasks/{task_id}/keyword-rules")
    def set_task_keyword_rules(task_id: int, payload: KeywordRulesPayload) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            return runtime.repository.set_task_keyword_rules(
                task_id,
                payload.keyword_rules,
                expected_version=payload.expected_version,
            )
        except JobProfileVersionConflictError as exc:
            raise ApiError(409, "job_profile_version_conflict", str(exc)) from exc
        except InvalidRecruitmentTaskStatusTransitionError as exc:
            raise ApiError(409, "keyword_rules_task_not_running", str(exc)) from exc
        except ValueError as exc:
            raise ApiError(404, "recruitment_task_not_found", str(exc)) from exc

    @app.post("/api/recruitment-tasks/{task_id}/external-ratings/preview")
    def preview_external_ratings(task_id: int, payload: ExternalRatingsImportRequest) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        task = runtime.repository.get_recruitment_task(task_id)
        if task is None:
            raise ApiError(404, "recruitment_task_not_found", "招聘任务不存在")
        if str(task["status"]) != "running":
            raise ApiError(409, "external_rating_task_not_running", "只有执行中的招聘任务可以导入外部评级")
        rows = _parse_external_rating_rows(payload)
        return {
            "task_id": task_id,
            "received": len(rows),
            "rows": [
                {
                    "line": row.get("line"),
                    "candidate_id": row.get("candidate_id"),
                    "name": row.get("name"),
                    "rating": row.get("rating"),
                    "original_rating": row.get("original_rating"),
                    "rating_status": row.get("rating_status"),
                    "track": row.get("track"),
                    "reason": row.get("reason"),
                    "batch_id": row.get("batch_id"),
                    "source_platform": row.get("source_platform"),
                    "source_job_title": row.get("source_job_title"),
                }
                for row in rows
            ],
        }

    @app.post("/api/recruitment-tasks/{task_id}/external-ratings/import")
    def import_external_ratings(task_id: int, payload: ExternalRatingsImportRequest) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        rows = _parse_external_rating_rows(payload)
        if not rows:
            raise ApiError(400, "external_rating_empty", "请粘贴至少一条候选人姓名和外部评级。")
        try:
            return runtime.repository.import_external_ratings(
                task_id,
                rows,
                source_note=payload.source_note,
            )
        except InvalidRecruitmentTaskStatusTransitionError as exc:
            raise ApiError(409, "external_rating_task_not_running", str(exc)) from exc
        except ValueError as exc:
            raise ApiError(404, "recruitment_task_not_found", str(exc)) from exc

    @app.get("/api/recruitment-tasks/{task_id}/external-ratings/latest")
    def get_latest_external_ratings(task_id: int) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        latest = runtime.repository.get_latest_external_rating_import(task_id)
        if latest is None:
            return {"run": None, "rows": []}
        run = latest["run"] if isinstance(latest.get("run"), dict) else {}
        return {
            "run": {
                "id": run.get("id"),
                "task_id": run.get("task_id"),
                "profile_id": run.get("profile_id"),
                "profile_version": run.get("profile_version"),
                "status": run.get("status"),
                "total_candidates": run.get("total_candidates"),
                "completed_candidates": run.get("completed_candidates"),
                "failed_candidates": run.get("failed_candidates"),
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
                "origin": run.get("origin"),
            },
            "rows": [
                {
                    "candidate_id": row.get("candidate_id"),
                    "name": row.get("name"),
                    "rating": row.get("rating"),
                    "original_rating": row.get("original_rating"),
                    "track": row.get("track"),
                    "reason": row.get("reason"),
                    "status": row.get("status"),
                    "created_at": row.get("created_at"),
                }
                for row in latest.get("rows", [])
                if isinstance(row, dict)
            ],
        }

    @app.get("/api/plugin/ratings/badges")
    def get_plugin_rating_badges(_auth: None = Depends(require_local_api_token)) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        try:
            context = runtime.get_plugin_context()
        except RuntimeError as exc:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。") from exc
        if context is None:
            raise ApiError(409, "context_unavailable", "当前未选择可用招聘任务。")
        task_id = int(context["recruitment_task_id"])
        return {
            "task_id": task_id,
            "job_profile_id": context["job_profile_id"],
            "job_profile_version": context["job_profile_version"],
            "badges": runtime.repository.list_plugin_rating_badges(task_id),
        }

    @app.get("/api/candidates")
    def list_candidates(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
        keyword: str = "",
        source_platform: str = "",
        unbound_only: bool = False,
        rating: str = "",
        task_id: int | None = None,
        sort: str = "latest_capture_desc",
    ) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        result = runtime.repository.page_candidates(
            page=page,
            page_size=page_size,
            keyword=keyword,
            source_platform=source_platform,
            unbound_only=unbound_only,
            rating=rating,
            task_id=task_id,
            sort=sort,
        )
        result["rows"] = [_project_candidate_list_row(dict(row)) for row in result["rows"]]
        return result

    @app.get("/api/candidates/{candidate_id}")
    def get_candidate_detail(candidate_id: int) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        detail = runtime.repository.get_candidate_detail(candidate_id)
        if detail is None:
            raise ApiError(404, "candidate_not_found", "候选人不存在。")
        return _project_candidate_detail(detail)

    @app.get("/api/candidates/{candidate_id}/appearances")
    def list_candidate_appearances(candidate_id: int) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        if not runtime.repository.candidate_exists(candidate_id):
            raise ApiError(404, "candidate_not_found", "候选人不存在。")
        rows = runtime.repository.list_candidate_appearances(candidate_id)
        return {"rows": [_project_candidate_appearance(row) for row in rows]}

    @app.get("/api/capture-batches")
    def list_capture_batches(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=200),
        source_platform: str = "",
        status: str = "",
        failed_only: bool = False,
        today_only: bool = False,
        task_id: int | None = None,
    ) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        return runtime.repository.page_capture_batches(
            source_platform=source_platform,
            status=status,
            failed_only=failed_only,
            today_only=today_only,
            task_id=task_id,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/capture-batches/{batch_id}")
    def get_capture_batch(batch_id: int) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        batch = runtime.repository.get_capture_batch(batch_id)
        if batch is None:
            raise ApiError(404, "batch_not_found", "采集批次不存在。")
        return batch

    @app.get("/api/capture-batches/{batch_id}/candidates")
    def list_capture_batch_candidates(
        batch_id: int,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        batch = runtime.repository.get_capture_batch(batch_id)
        if batch is None:
            raise ApiError(404, "batch_not_found", "采集批次不存在。")
        return runtime.repository.page_capture_batch_candidates(
            batch_id,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/capture-batches/{batch_id}/export.md")
    def export_capture_batch_markdown(
        batch_id: int,
        request: Request,
        x_boss_local_token: str = Header(default=""),
    ) -> Response:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        if str(request.headers.get("origin") or "").startswith("chrome-extension://"):
            require_local_api_token(x_boss_local_token)
        download = BatchMarkdownExporter(runtime.repository).build(batch_id)
        if download is None:
            raise ApiError(404, "batch_not_found", "采集批次不存在。")
        return Response(
            content=download.content.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(download.filename)}"},
        )

    dist = frontend_dist or bootstrap.project_root / "web" / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{page_path:path}", include_in_schema=False)
    def frontend(page_path: str):
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return error_response(503, "frontend_not_built", "网页前端尚未构建，请先运行 npm.cmd run build。")

    return app
