from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core.app_lock import ApplicationLockError, DatabaseApplicationLock
from core.bootstrap import BootstrapService, DATABASE_NAME, DataDirectoryError
from core.version import APP_VERSION
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


SERVICE_NAME = "recruiting-talent-workbench"


class ApiError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class SetupRequest(BaseModel):
    data_dir: str


class WebRuntime:
    def __init__(self, bootstrap: BootstrapService, lock_root: Path | None = None) -> None:
        self.bootstrap = bootstrap
        self.lock_root = lock_root
        self.database: DatabaseManager | None = None
        self.repository: CandidateRepository | None = None
        self.lock: DatabaseApplicationLock | None = None
        self.database_error = ""
        self._state_lock = threading.RLock()
        configured = bootstrap.store.load()
        if configured is not None:
            try:
                self.connect(Path(configured.data_dir), initialize=True)
            except ApplicationLockError:
                raise
            except Exception:
                self.database_error = "数据库初始化失败。"
        elif (bootstrap.project_data_dir / DATABASE_NAME).is_file():
            self.reserve(bootstrap.project_data_dir)

    def reserve(self, data_dir: Path) -> None:
        with self._state_lock:
            lock = DatabaseApplicationLock(data_dir / DATABASE_NAME, lock_root=self.lock_root)
            lock.acquire()
            self.lock = lock

    def connect(self, data_dir: Path, *, initialize: bool) -> None:
        with self._state_lock:
            database_path = data_dir / DATABASE_NAME
            lock = DatabaseApplicationLock(database_path, lock_root=self.lock_root)
            lock.acquire()
            database = DatabaseManager(database_path)
            try:
                if initialize:
                    database.initialize()
                self.lock = lock
                self.database = database
                self.repository = CandidateRepository(database)
                self.database_error = ""
            except Exception:
                database.close_all_connections()
                lock.release()
                raise

    def setup(self, data_dir: str) -> dict[str, object]:
        with self._state_lock:
            if self.bootstrap.store.load() is not None:
                raise DataDirectoryError("首次设置已经完成，运行中不能更换数据目录。")
            selected = self.bootstrap.validate_data_dir(data_dir)
            selected_database = (selected / DATABASE_NAME).resolve()
            if self.lock is not None and self.lock.database_path != selected_database:
                self.close()
            if self.lock is None:
                self.reserve(selected)
            try:
                result = self.bootstrap.setup(selected)
                self.database = DatabaseManager(selected / DATABASE_NAME)
                self.repository = CandidateRepository(self.database)
                self.database_error = ""
                return result
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        with self._state_lock:
            if self.database is not None:
                self.database.close_all_connections()
            if self.lock is not None:
                self.lock.release()
            self.database = None
            self.repository = None
            self.lock = None


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
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/"):
            expected = f"http://127.0.0.1:{web_port}"
            if request.headers.get("origin") != expected:
                return error_response(403, "same_origin_required", "请求来源无效，请从本地工作台页面操作。")
        return await call_next(request)

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
    def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME, "version": APP_VERSION}

    @app.get("/api/setup/status")
    def setup_status() -> dict[str, object]:
        return bootstrap.status()

    @app.post("/api/setup")
    def setup(payload: SetupRequest) -> dict[str, object]:
        return runtime.setup(payload.data_dir)

    @app.get("/api/app/status")
    def app_status() -> dict[str, object]:
        if runtime.repository is None:
            raise ApiError(503, "database_not_ready", "数据库尚未就绪，请先完成首次设置。")
        stats = runtime.repository.get_dashboard_stats()
        configured = bootstrap.store.load()
        return {
            "version": APP_VERSION,
            "database_ready": True,
            "data_dir": configured.data_dir if configured else "",
            "candidate_count": int(stats["total_candidates"]),
            "batch_count": int(stats["total_batches"]),
            "latest_batch_id": int(stats["latest_batch_id"]),
            "latest_batch_status": str(stats["latest_batch_status"]),
        }

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
