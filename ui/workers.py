from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QObject, Signal, Slot

from automation.browser import BrowserService
from automation.collector import CaptureService
from automation.parser import CandidateParser
from automation.scroller import PageScroller
from automation.selectors import BossSelectorConfig
from ai.prompt_manager import PromptManager
from ai.provider import ProviderSettings, create_provider
from ai.screening_service import ScreeningService
from core.exceptions import BrowserNotReadyError, PlatformBlockedError
from storage.export_service import ExportService
from storage.repository import CandidateRepository


class AutomationWorker(QObject):
    browser_opened = Signal(object)
    capture_progress = Signal(object)
    capture_finished = Signal(object)
    error = Signal(str)

    def __init__(self, config_service, repository: CandidateRepository, logger_service) -> None:
        super().__init__()
        self.config_service = config_service
        self.repository = repository
        self.logger = logger_service.get_logger("ui.automation")
        self.browser_service = BrowserService(logger=logger_service.get_logger("automation.browser"))
        self.capture_service = CaptureService(
            repository=repository,
            parser=CandidateParser(logger=logger_service.get_logger("automation.parser")),
            scroller=PageScroller(logger=logger_service.get_logger("automation.scroller")),
            logger=logger_service.get_logger("automation.capture"),
        )

    @Slot(object)
    def open_browser(self, payload: object) -> None:
        config = self.config_service.load()
        url = str((payload or {}).get("url") or config.target_url)
        try:
            current_url = self.browser_service.open_browser(config, target_url=url)
            message = self.browser_service.detect_manual_intervention(self.browser_service.ensure_page(config))
            self.browser_opened.emit(
                {
                    "status": "waiting_user" if message else "ready",
                    "message": message or "Browser opened successfully.",
                    "current_url": current_url,
                }
            )
        except PlatformBlockedError as exc:
            self.browser_opened.emit(
                {
                    "status": "blocked",
                    "message": str(exc),
                    "current_url": url,
                }
            )
        except BrowserNotReadyError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.logger.exception("Failed to open browser: %s", exc)
            self.error.emit(str(exc))

    @Slot(object)
    def start_capture(self, collect_options: object) -> None:
        config = self.config_service.load()
        selectors_path = self._resolve_path(config.selectors_path)
        selector_config = BossSelectorConfig.load(selectors_path)
        try:
            result = self.capture_service.collect(
                browser_service=self.browser_service,
                selector_config=selector_config,
                options=collect_options,
                config=config,
                progress_callback=self.capture_progress.emit,
            )
            self.capture_finished.emit(result)
        except PlatformBlockedError as exc:
            self.error.emit(str(exc))
        except BrowserNotReadyError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.logger.exception("Capture crashed: %s", exc)
            self.error.emit(str(exc))

    @Slot()
    def request_stop(self) -> None:
        self.capture_service.request_stop()

    @Slot()
    def shutdown(self) -> None:
        self.browser_service.close()
        self.repository.db.close_thread_connection()

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.config_service.app_root / path


class ExportWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, export_service: ExportService, payload: dict[str, object]) -> None:
        super().__init__()
        self.export_service = export_service
        self.payload = payload

    @Slot()
    def run(self) -> None:
        try:
            result = self.export_service.export(
                export_format=str(self.payload.get("export_format") or "csv"),
                mode=str(self.payload["mode"]),
                export_dir=Path(str(self.payload["export_dir"])),
                columns=list(self.payload["columns"]),
                batch_id=self.payload.get("batch_id"),
                keyword=str(self.payload.get("keyword") or ""),
                job_title=str(self.payload.get("job_title") or ""),
                city=str(self.payload.get("city") or ""),
                years_min=self.payload.get("years_min"),
                years_max=self.payload.get("years_max"),
                profile_tag=str(self.payload.get("profile_tag") or ""),
                last_active_days=self.payload.get("last_active_days"),
                match_role_id=self.payload.get("match_role_id"),
                minimum_rating=str(self.payload.get("minimum_rating") or ""),
                match_status=str(self.payload.get("match_status") or ""),
                recruitment_status=str(self.payload.get("recruitment_status") or ""),
                latest_reason_code=str(self.payload.get("latest_reason_code") or ""),
                filename_template=str(self.payload.get("filename_template") or ""),
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.export_service.repository.db.close_thread_connection()


class CandidatePageWorker(QObject):
    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, repository: CandidateRepository) -> None:
        super().__init__()
        self.repository = repository

    @Slot(object)
    def run(self, payload: object) -> None:
        request = dict(payload or {})
        request_id = int(request["request_id"])
        kind = str(request.get("kind") or "candidates")
        filters = dict(request.get("filters") or {})
        page = int(request.get("page") or 1)
        page_size = int(request.get("page_size") or 100)
        try:
            if kind == "review":
                result = self.repository.page_manual_review_candidates(
                    role_id=(int(filters["role_id"]) if filters.get("role_id") is not None else None),
                    page=page,
                    page_size=page_size,
                )
                result["kind"] = kind
                result["rows"] = [dict(row) for row in result["rows"]]
                self.finished.emit(request_id, result)
                return
            if kind == "screening_results":
                result = self.repository.page_screening_task_results(
                    int(request["run_id"]), page=page, page_size=page_size
                )
                result["kind"] = kind
                result["run_id"] = int(request["run_id"])
                result["rows"] = [dict(row) for row in result["rows"]]
                self.finished.emit(request_id, result)
                return
            match_role_id = filters.pop("match_role_id", None)
            minimum_rating = filters.pop("minimum_rating", "")
            match_status = filters.pop("match_status", "")
            recruitment_status = filters.pop("recruitment_status", "")
            latest_reason_code = filters.pop("latest_reason_code", "")
            if match_role_id is not None or minimum_rating or match_status or recruitment_status:
                result = self.repository.page_candidate_role_matches(
                    role_id=int(match_role_id) if match_role_id is not None else None,
                    match_statuses=[str(match_status)] if match_status else None,
                    recruitment_statuses=[str(recruitment_status)] if recruitment_status else None,
                    minimum_rating=str(minimum_rating) if minimum_rating else None,
                    job_title=str(filters.get("job_title") or ""),
                    batch_id=filters.get("batch_id"),
                    city=str(filters.get("city") or ""),
                    years_min=filters.get("years_min"),
                    years_max=filters.get("years_max"),
                    profile_tag=str(filters.get("profile_tag") or ""),
                    last_active_days=filters.get("last_active_days"),
                    latest_reason_code=str(latest_reason_code or ""),
                    query=str(filters.get("keyword") or ""),
                    page=page,
                    page_size=page_size,
                )
            else:
                result = self.repository.page_candidates(
                    **filters,
                    latest_reason_code=str(latest_reason_code or ""),
                    page=page,
                    page_size=page_size,
                )
            result["rows"] = [dict(row) for row in result["rows"]]
            result["kind"] = kind
            self.finished.emit(request_id, result)
        except Exception as exc:
            self.error.emit(request_id, str(exc))
        finally:
            self.repository.db.close_thread_connection()


class ProfileRefreshWorker(QObject):
    finished = Signal(int)
    error = Signal(str)

    def __init__(self, repository: CandidateRepository, chunk_size: int = 500) -> None:
        super().__init__()
        self.repository = repository
        self.chunk_size = max(1, int(chunk_size))
        self._stop_requested = threading.Event()

    @Slot()
    def run(self) -> None:
        total = 0
        try:
            while not self._stop_requested.is_set():
                refreshed = self.repository.refresh_outdated_candidate_profiles(limit=self.chunk_size)
                total += refreshed
                if refreshed < self.chunk_size:
                    break
            self.finished.emit(total)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.repository.db.close_thread_connection()

    def request_stop(self) -> None:
        self._stop_requested.set()


class AIScreeningWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, repository: CandidateRepository, prompt_manager: PromptManager, payload: dict[str, object], logger) -> None:
        super().__init__()
        self.repository = repository
        self.prompt_manager = prompt_manager
        self.payload = payload
        provider_payload = dict(payload.get("provider") or {})
        settings = ProviderSettings(
            provider=str(provider_payload.get("provider") or "openai"),
            model=str(provider_payload.get("model") or ""),
            api_base=str(provider_payload.get("api_base") or ""),
            api_key=str(provider_payload.get("api_key") or ""),
            api_key_env=str(provider_payload.get("api_key_env") or "OPENAI_API_KEY"),
        )
        self.service = ScreeningService(
            repository=repository,
            prompt_manager=prompt_manager,
            provider=create_provider(settings, logger=logger),
            logger=logger,
        )

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.run(
                profile=dict(self.payload["profile"]),
                candidates=list(self.payload["candidates"]),
                source_job_title=str(self.payload.get("source_job_title") or ""),
                batch_id=self.payload.get("batch_id"),
                provider_name=str(dict(self.payload["provider"]).get("provider") or ""),
                model=str(dict(self.payload["provider"]).get("model") or ""),
                origin=str(self.payload.get("origin") or "manual"),
                progress_callback=self.progress.emit,
                run_id=self.payload.get("run_id"),
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.repository.db.close_thread_connection()

    def request_stop(self) -> None:
        self.service.request_stop()


class AIConnectionTestWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, logger) -> None:
        super().__init__()
        self.provider_payload: dict[str, object] = {}
        self.logger = logger
        self._cancelled = threading.Event()

    @Slot(object)
    def run(self, provider_payload: object) -> None:
        self.provider_payload = dict(provider_payload or {})
        self._cancelled.clear()
        try:
            settings = ProviderSettings(
                provider=str(self.provider_payload.get("provider") or "openai"),
                model=str(self.provider_payload.get("model") or ""),
                api_base=str(self.provider_payload.get("api_base") or ""),
                api_key=str(self.provider_payload.get("api_key") or ""),
                api_key_env=str(self.provider_payload.get("api_key_env") or "OPENAI_API_KEY"),
                timeout_seconds=15,
            )
            result = create_provider(settings, logger=self.logger).test_connection()
            if self._cancelled.is_set():
                self.error.emit("API 连接测试已取消")
            else:
                self.finished.emit(result)
        except Exception as exc:
            self.error.emit("API 连接测试已取消" if self._cancelled.is_set() else str(exc))

    def request_cancel(self) -> None:
        self._cancelled.set()
