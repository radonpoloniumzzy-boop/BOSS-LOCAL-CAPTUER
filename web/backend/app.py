from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core.app_lock import ApplicationLockError
from core.bootstrap import BootstrapService, DataDirectoryError
from core.version import APP_VERSION
from storage.repository import IdempotencyConflictError
from web.backend.batch_markdown import BatchMarkdownExporter
from web.backend.pairing import PairingCodeError
from web.backend.runtime import WebRuntime


SERVICE_NAME = "recruiting-talent-workbench"
WEB_CAPABILITIES = ["phase2c_pairing", "batch_markdown_export"]


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
    pairing_code: str


_CANDIDATE_LIST_FIELDS = (
    "id",
    "name",
    "source_platform",
    "latest_source_platform",
    "latest_source_job_title",
    "latest_batch_id",
    "latest_capture_time",
    "latest_ingest_status",
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

    @app.get("/api/candidates")
    def list_candidates(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
        keyword: str = "",
        source_platform: str = "",
        unbound_only: bool = False,
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
        detail = runtime.repository.get_candidate_detail(candidate_id)
        if detail is None:
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
    ) -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        return runtime.repository.page_capture_batches(
            source_platform=source_platform,
            status=status,
            failed_only=failed_only,
            today_only=today_only,
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
