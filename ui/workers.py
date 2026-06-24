from __future__ import annotations

from pathlib import Path

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
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.export_service.repository.db.close_thread_connection()


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

    def __init__(self, provider_payload: dict[str, object], logger) -> None:
        super().__init__()
        self.provider_payload = provider_payload
        self.logger = logger

    @Slot()
    def run(self) -> None:
        try:
            settings = ProviderSettings(
                provider=str(self.provider_payload.get("provider") or "openai"),
                model=str(self.provider_payload.get("model") or ""),
                api_base=str(self.provider_payload.get("api_base") or ""),
                api_key=str(self.provider_payload.get("api_key") or ""),
                api_key_env=str(self.provider_payload.get("api_key_env") or "OPENAI_API_KEY"),
            )
            result = create_provider(settings, logger=self.logger).test_connection()
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
