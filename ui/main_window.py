from __future__ import annotations

import threading
from datetime import datetime, timedelta
from types import SimpleNamespace

from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from automation.importer import CardImportService
from automation.parser import CandidateParser
from ai.prompt_manager import PromptManager
from ai.provider import AIProviderError, ProviderSettings, validate_provider_settings
from core.config import ConfigService
from core.credentials import CredentialStore
from core.local_api import LocalApiServer
from core.logger import LoggingService
from core.models import AutomationFlowConfig, ScreeningProfile
from storage.db import DatabaseManager
from storage.export_service import ExportService
from storage.repository import CandidateRepository
from ui.pages.ai_screen import AIScreenPage
from ui.pages.automation_flow import AutomationFlowPage
from ui.pages.candidates import CandidatesPage
from ui.pages.dashboard import DashboardPage
from ui.pages.review import ReviewPage
from ui.pages.settings import SettingsPage
from ui.workers import (
    AIConnectionTestWorker,
    AIScreeningWorker,
    AutomationWorker,
    CandidatePageWorker,
    ExportWorker,
    ProfileRefreshWorker,
)


class _LogBridge(QObject):
    message = Signal(str)


class _ImportBridge(QObject):
    imported = Signal(object)
    error = Signal(str)


class MainWindow(QMainWindow):
    open_browser_requested = Signal(object)
    start_capture_requested = Signal(object)
    stop_capture_requested = Signal()
    shutdown_requested = Signal()
    candidate_query_requested = Signal(object)
    ai_connection_test_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("招聘候选人采集与 AI 初筛工具")
        self.resize(920, 720)
        self.setMinimumSize(720, 560)

        self.config_service = ConfigService()
        self.logging_service = LoggingService(self.config_service.logs_dir, level="INFO")
        self.config_service.logger = self.logging_service.get_logger("core")
        self.config = self.config_service.load()
        self.ui_settings = QSettings(
            str(self.config_service.data_dir / "ui_state.ini"),
            QSettings.IniFormat,
        )
        self.credential_store = CredentialStore()
        self.logging_service.configure(self.config.log_level)
        self.logger = self.logging_service.get_logger("ui.main_window")

        self.database = DatabaseManager(
            self.config_service.database_path,
            logger=self.logging_service.get_logger("storage.db"),
        )
        self.database.initialize()
        self.repository = CandidateRepository(
            self.database,
            logger=self.logging_service.get_logger("storage.repository"),
        )
        self._refreshed_candidate_profiles = 0
        self._recovered_screening_tasks = self.repository.recover_interrupted_screening_tasks()
        self.export_service = ExportService(
            self.repository,
            logger=self.logging_service.get_logger("storage.export"),
        )
        self.import_service = CardImportService(
            repository=self.repository,
            parser=CandidateParser(logger=self.logging_service.get_logger("automation.parser")),
            logger=self.logging_service.get_logger("automation.importer"),
        )
        self.prompt_manager = PromptManager(self.config_service.app_root / "assets" / "prompts")
        self._ensure_builtin_screening_profiles()

        self.local_api_server: LocalApiServer | None = None
        self.import_bridge = _ImportBridge()
        self._export_threads: list[tuple[QThread, ExportWorker]] = []
        self._candidate_request_id = 0
        self._page_request_kind: dict[int, str] = {}
        self._latest_page_request: dict[str, int] = {}
        self._ai_screening_thread: tuple[QThread, AIScreeningWorker] | None = None
        self._ai_screening_origin = "manual"
        self._ai_test_running = False
        self._ai_test_context: dict[str, object] = {}
        self._automation_armed = False
        self._queued_automation_batches: list[dict[str, object]] = []
        self._automation_config_lock = threading.RLock()
        self._capture_running = False

        self._build_ui()
        self._setup_logging_panel()
        self._restore_ui_state()
        self._setup_automation_worker()
        self._setup_candidate_query_worker()
        self._setup_ai_connection_test_worker()
        self._setup_profile_refresh_worker()
        self._connect_signals()
        self._load_config_into_pages()
        self._start_local_api_server()
        self.refresh_candidates()
        self.refresh_dashboard_stats()
        self.refresh_automation_flow()
        self.dashboard_page.set_running(False)
        if self._refreshed_candidate_profiles:
            self.statusBar().showMessage(
                f"Refreshed {self._refreshed_candidate_profiles} outdated candidate profiles."
            )
            self.logger.info(
                "Refreshed %s outdated candidate profiles",
                self._refreshed_candidate_profiles,
            )
        if self._recovered_screening_tasks:
            self.statusBar().showMessage(
                f"Recovered {self._recovered_screening_tasks} interrupted AI screening tasks."
            )
            self.logger.warning(
                "Recovered %s interrupted AI screening tasks",
                self._recovered_screening_tasks,
            )
        self.logger.info("Application started")

    def _build_ui(self) -> None:
        central = QWidget()
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.navigation = QListWidget()
        self.navigation.setFixedWidth(112)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for label in ["仪表盘", "自动化流程", "候选人", "AI 初筛", "人工复核", "设置"]:
            QListWidgetItem(label, self.navigation)
        self.navigation.setCurrentRow(0)

        self.stack = QStackedWidget()
        self.stack.setMinimumSize(0, 0)
        self.stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.dashboard_page = DashboardPage()
        self.automation_flow_page = AutomationFlowPage()
        self.candidates_page = CandidatesPage()
        self.ai_page = AIScreenPage(self.prompt_manager)
        self.review_page = ReviewPage()
        self.settings_page = SettingsPage()

        self._page_scroll_areas: list[QScrollArea] = []
        for page in [
            self.dashboard_page,
            self.automation_flow_page,
            self.candidates_page,
            self.ai_page,
            self.review_page,
            self.settings_page,
        ]:
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QScrollArea.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll_area.setWidget(page)
            scroll_area.setMinimumSize(0, 0)
            scroll_area.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            self._page_scroll_areas.append(scroll_area)
            self.stack.addWidget(scroll_area)

        content_wrapper = QWidget()
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.stack)

        self._navigation_full_labels = [
            self.navigation.item(index).text() for index in range(self.navigation.count())
        ]
        self._navigation_compact_labels = ["概", "流", "人", "AI", "核", "设"]
        self.navigation_container = QWidget()
        navigation_layout = QVBoxLayout(self.navigation_container)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(0)
        self.navigation_toggle = QToolButton()
        self.navigation_toggle.setToolTip("展开导航")
        self.navigation_toggle.clicked.connect(self._toggle_navigation)
        navigation_layout.addWidget(self.navigation_toggle)
        navigation_layout.addWidget(self.navigation, 1)
        self._navigation_collapsed = False
        self._set_navigation_collapsed(True)

        central_layout.addWidget(self.navigation_container)
        central_layout.addWidget(content_wrapper, 1)
        self.setCentralWidget(central)
        self._build_toolbar()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        self.open_browser_action = QAction("打开招聘页面", self)
        self.start_capture_action = QAction("开始采集", self)
        self.stop_capture_action = QAction("停止任务", self)
        self.export_csv_action = QAction("导出 CSV", self)
        self.export_jsonl_action = QAction("导出 JSONL", self)
        self.export_markdown_action = QAction("导出 Markdown", self)
        self.refresh_action = QAction("刷新列表", self)

        toolbar.addAction(self.open_browser_action)
        toolbar.addAction(self.start_capture_action)
        toolbar.addAction(self.stop_capture_action)
        toolbar.addSeparator()
        toolbar.addAction(self.export_csv_action)
        toolbar.addAction(self.export_jsonl_action)
        toolbar.addAction(self.export_markdown_action)
        toolbar.addSeparator()
        toolbar.addAction(self.refresh_action)
        self.main_toolbar = toolbar
        toolbar.hide()

    def _setup_logging_panel(self) -> None:
        self.log_bridge = _LogBridge()
        self.logging_service.subscribe(self.log_bridge.message.emit)
        self.log_bridge.message.connect(self._append_log_line)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        dock = QDockWidget("运行日志", self)
        dock.setWidget(self.log_view)
        dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.log_dock = dock
        self.log_dock.hide()
        self.log_toggle_button = QToolButton()
        self.log_toggle_button.setText("日志")
        self.log_toggle_button.setToolTip("显示或隐藏运行日志")
        self.log_toggle_button.setCheckable(True)
        self.log_toggle_button.toggled.connect(self.log_dock.setVisible)
        self.log_dock.visibilityChanged.connect(self.log_toggle_button.setChecked)
        self.statusBar().addPermanentWidget(self.log_toggle_button)
        self.statusBar().showMessage("就绪")

    def _restore_ui_state(self) -> None:
        geometry = self.ui_settings.value("window_geometry")
        state = self.ui_settings.value("window_state")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
        self.log_dock.hide()
        self.log_toggle_button.setChecked(False)

    def _set_navigation_collapsed(self, collapsed: bool) -> None:
        self._navigation_collapsed = collapsed
        width = 52 if collapsed else 132
        self.navigation_container.setFixedWidth(width)
        self.navigation.setFixedWidth(width)
        labels = self._navigation_compact_labels if collapsed else self._navigation_full_labels
        for index, label in enumerate(labels):
            self.navigation.item(index).setText(label)
            self.navigation.item(index).setToolTip(self._navigation_full_labels[index])
        icon = QStyle.SP_ArrowRight if collapsed else QStyle.SP_ArrowLeft
        self.navigation_toggle.setIcon(self.style().standardIcon(icon))
        self.navigation_toggle.setToolTip("展开导航" if collapsed else "收起导航")

    def _toggle_navigation(self) -> None:
        self._set_navigation_collapsed(not self._navigation_collapsed)

    def _setup_automation_worker(self) -> None:
        self.automation_thread = QThread(self)
        self.automation_worker = AutomationWorker(
            config_service=self.config_service,
            repository=self.repository,
            logger_service=self.logging_service,
        )
        self.automation_worker.moveToThread(self.automation_thread)
        self.open_browser_requested.connect(self.automation_worker.open_browser)
        self.start_capture_requested.connect(self.automation_worker.start_capture)
        self.stop_capture_requested.connect(self.automation_worker.request_stop)
        self.shutdown_requested.connect(self.automation_worker.shutdown)
        self.automation_worker.browser_opened.connect(self._on_browser_opened)
        self.automation_worker.capture_progress.connect(self._on_capture_progress)
        self.automation_worker.capture_finished.connect(self._on_capture_finished)
        self.automation_worker.error.connect(self._on_worker_error)
        self.automation_thread.start()

    def _setup_candidate_query_worker(self) -> None:
        self.candidate_query_thread = QThread(self)
        self.candidate_query_worker = CandidatePageWorker(self.repository)
        self.candidate_query_worker.moveToThread(self.candidate_query_thread)
        self.candidate_query_requested.connect(self.candidate_query_worker.run)
        self.candidate_query_worker.finished.connect(self._on_candidate_page_loaded)
        self.candidate_query_worker.error.connect(self._on_candidate_page_failed)
        self.candidate_query_thread.start()

    def _setup_ai_connection_test_worker(self) -> None:
        self.ai_test_thread = QThread(self)
        self.ai_test_worker = AIConnectionTestWorker(
            logger=self.logging_service.get_logger("ai.connection_test")
        )
        self.ai_test_worker.moveToThread(self.ai_test_thread)
        self.ai_connection_test_requested.connect(self.ai_test_worker.run)
        self.ai_test_worker.finished.connect(self._on_ai_connection_test_finished)
        self.ai_test_worker.error.connect(self._on_ai_connection_test_error)
        self.ai_test_thread.start()

    def _setup_profile_refresh_worker(self) -> None:
        self.profile_refresh_thread = QThread(self)
        self.profile_refresh_worker = ProfileRefreshWorker(self.repository)
        self.profile_refresh_worker.moveToThread(self.profile_refresh_thread)
        self.profile_refresh_thread.started.connect(self.profile_refresh_worker.run)
        self.profile_refresh_worker.finished.connect(self._on_profile_refresh_finished)
        self.profile_refresh_worker.error.connect(self._on_profile_refresh_failed)
        self.profile_refresh_worker.finished.connect(self.profile_refresh_thread.quit)
        self.profile_refresh_worker.error.connect(self.profile_refresh_thread.quit)
        self._profile_refresh_started = False

    def _on_profile_refresh_finished(self, count: int) -> None:
        self._refreshed_candidate_profiles = int(count)
        if count:
            self.logger.info("Refreshed %s outdated candidate profiles in background", count)

    def _on_profile_refresh_failed(self, message: str) -> None:
        self.logger.warning("Background candidate profile refresh failed: %s", message)

    def _connect_signals(self) -> None:
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.navigation.currentRowChanged.connect(self._on_page_changed)

        self.open_browser_action.triggered.connect(lambda _checked=False: self.handle_open_browser())
        self.start_capture_action.triggered.connect(lambda _checked=False: self.handle_start_capture())
        self.stop_capture_action.triggered.connect(lambda _checked=False: self.handle_stop_capture())
        self.export_csv_action.triggered.connect(lambda _checked=False: self.handle_export("csv"))
        self.export_jsonl_action.triggered.connect(lambda _checked=False: self.handle_export("jsonl"))
        self.export_markdown_action.triggered.connect(lambda _checked=False: self.handle_export("markdown"))
        self.refresh_action.triggered.connect(lambda _checked=False: self.refresh_candidates())

        self.dashboard_page.open_browser_requested.connect(lambda _url: self.handle_open_browser())
        self.dashboard_page.start_capture_requested.connect(self._start_capture_from_dashboard)
        self.dashboard_page.stop_requested.connect(self.handle_stop_capture)
        self.dashboard_page.export_requested.connect(self.handle_export_latest_batch)
        self.dashboard_page.funnel_refresh_requested.connect(self.refresh_dashboard_stats)

        self.candidates_page.refresh_requested.connect(self.refresh_candidates)
        self.candidates_page.export_requested.connect(self._export_candidates_view)
        self.candidates_page.candidate_selected.connect(self._load_candidate_detail)
        self.candidates_page.status_change_requested.connect(self._record_recruitment_status_change)

        self.review_page.refresh_requested.connect(self.refresh_review_queue)
        self.review_page.status_change_requested.connect(self._record_recruitment_status_change)

        self.ai_page.profile_selected.connect(self._load_screening_profile)
        self.ai_page.save_profile_requested.connect(self._save_screening_profile)
        self.ai_page.clone_profile_requested.connect(self._clone_screening_profile)
        self.ai_page.delete_profile_requested.connect(self._delete_screening_profile)
        self.ai_page.run_requested.connect(self._start_ai_screening)
        self.ai_page.stop_requested.connect(self._stop_ai_screening)
        self.ai_page.test_connection_requested.connect(self._test_ai_connection)
        self.ai_page.cancel_connection_test_requested.connect(self._cancel_ai_connection_test)
        self.ai_page.delete_credential_requested.connect(self._delete_ai_credential)
        self.ai_page.run_selected.connect(self._load_screening_results)
        self.ai_page.resume_run_requested.connect(self._resume_ai_screening_run)
        self.ai_page.retry_task_requested.connect(self._retry_ai_screening_task)

        self.automation_flow_page.save_requested.connect(self._save_automation_flow)
        self.automation_flow_page.arm_requested.connect(self._arm_automation_flow)
        self.automation_flow_page.cancel_requested.connect(self._cancel_automation_flow)
        self.automation_flow_page.stop_requested.connect(self._stop_ai_screening)
        self.automation_flow_page.test_connection_requested.connect(
            lambda payload: self._test_ai_connection(payload, target="automation")
        )
        self.automation_flow_page.run_selected.connect(self._load_automation_results)

        self.settings_page.save_requested.connect(self._save_settings)
        self.import_bridge.imported.connect(self._on_extension_imported)
        self.import_bridge.error.connect(self._on_extension_import_error)

    def _load_config_into_pages(self) -> None:
        self.dashboard_page.load_config(self.config)
        self.settings_page.load_config(self.config)
        self.ai_page.load_config(self.config)
        self.automation_flow_page.load_config(self.config)

    def _start_local_api_server(self) -> None:
        if self.local_api_server is not None:
            self.local_api_server.stop()

        self.local_api_server = LocalApiServer(
            host="127.0.0.1",
            port=self.config.local_api_port,
            import_service=self.import_service,
            logger=self.logging_service.get_logger("local_api"),
            on_import=self.import_bridge.imported.emit,
            on_error=self.import_bridge.error.emit,
            get_automation_status=self._automation_status_payload,
            start_automation=self._start_automation_from_extension,
            get_extension_config=self._extension_config_payload,
            auth_token=self.config.local_api_token,
        )
        try:
            self.local_api_server.start()
            self.dashboard_page.set_local_api_status(self.local_api_server.endpoint)
            self.logger.info("Extension ingest endpoint ready at %s", self.local_api_server.endpoint)
        except Exception as exc:
            self.dashboard_page.set_local_api_status("不可用")
            self.logger.exception("Failed to start local API server: %s", exc)
            QMessageBox.critical(self, "本地接口异常", f"扩展接收接口启动失败。\n{exc}")

    def _extension_config_payload(self) -> dict[str, object]:
        with self._automation_config_lock:
            self.config = self.config_service.load()
        return {
            "resume_filename_template": self.config.resume_filename_template,
            "job_title": self.config.default_job_title,
        }

    def handle_open_browser(self) -> None:
        url = self.dashboard_page.source_url_input.text().strip() or self.config.target_url
        self.statusBar().showMessage("正在打开浏览器...")
        self.open_browser_requested.emit({"url": url})

    def handle_start_capture(self) -> None:
        self._start_capture_from_dashboard(self.dashboard_page.build_collect_options())

    def _start_capture_from_dashboard(self, collect_options) -> None:
        if "zhipin.com" in (collect_options.source_url or "").lower():
            endpoint = f"http://127.0.0.1:{self.config.local_api_port}"
            message = (
                "Boss 采集请使用 Chrome 扩展模式。\n\n"
                f"1. 保持本程序运行，确保本地接口可用：{endpoint}\n"
                "2. 在普通 Chrome 页面中手动登录 Boss\n"
                "3. 使用扩展弹窗执行“自动滚动到底后采集”，把卡片发回本程序"
            )
            self.dashboard_page.set_message(message)
            QMessageBox.information(self, "请使用 Chrome 扩展", message)
            return

        if self._capture_running:
            QMessageBox.information(self, "任务进行中", "已有采集任务正在运行。")
            return
        if not collect_options.source_url:
            QMessageBox.warning(self, "缺少链接", "请先填写目标链接。")
            return

        self._capture_running = True
        self.dashboard_page.set_running(True)
        self.dashboard_page.set_status("running")
        self.statusBar().showMessage("正在开始采集...")
        self.start_capture_requested.emit(collect_options)

    def handle_stop_capture(self) -> None:
        if not self._capture_running:
            return
        result = QMessageBox.question(self, "停止任务", "确认停止当前采集任务吗？")
        if result == QMessageBox.Yes:
            self.stop_capture_requested.emit()
            self.statusBar().showMessage("已发送停止请求")

    def handle_export(self, export_format: str = "csv") -> None:
        if self.stack.currentWidget() is self.candidates_page:
            payload = self.candidates_page.current_filters()
            payload["export_format"] = export_format
            self._export_candidates_view(payload)
            return
        self.handle_export_latest_batch(export_format)

    def handle_export_latest_batch(self, export_format: str = "csv") -> None:
        latest_batch = self.repository.get_latest_batch()
        if latest_batch is None:
            self._start_export(
                {
                    "mode": "all",
                    "job_title": self.dashboard_page.job_title_input.text().strip() or self.config.default_job_title,
                    "export_format": export_format,
                }
            )
            return
        self._start_export(
            {
                "mode": "batch",
                "batch_id": int(latest_batch["id"]),
                "job_title": str(latest_batch["job_title"]),
                "export_format": export_format,
            }
        )

    def _export_candidates_view(self, payload: dict[str, object]) -> None:
        export_payload = {
            "mode": "filtered",
            "keyword": payload.get("keyword") or "",
            "job_title": payload.get("job_title") or "",
            "batch_id": payload.get("batch_id"),
            "city": payload.get("city") or "",
            "years_min": payload.get("years_min") or "",
            "years_max": payload.get("years_max") or "",
            "profile_tag": payload.get("profile_tag") or "",
            "last_active_days": payload.get("last_active_days") or "",
            "match_role_id": payload.get("match_role_id"),
            "minimum_rating": payload.get("minimum_rating") or "",
            "match_status": payload.get("match_status") or "",
            "recruitment_status": payload.get("recruitment_status") or "",
            "latest_reason_code": payload.get("latest_reason_code") or "",
            "export_format": payload.get("export_format") or "csv",
        }
        self._start_export(export_payload)

    def _start_export(self, payload: dict[str, object]) -> None:
        export_payload = {
            "export_format": payload.get("export_format", "csv"),
            "mode": payload.get("mode", "all"),
            "batch_id": payload.get("batch_id"),
            "keyword": payload.get("keyword", ""),
            "job_title": payload.get("job_title", ""),
            "city": payload.get("city", ""),
            "years_min": payload.get("years_min", ""),
            "years_max": payload.get("years_max", ""),
            "profile_tag": payload.get("profile_tag", ""),
            "last_active_days": payload.get("last_active_days", ""),
            "match_role_id": payload.get("match_role_id"),
            "minimum_rating": payload.get("minimum_rating", ""),
            "match_status": payload.get("match_status", ""),
            "recruitment_status": payload.get("recruitment_status", ""),
            "latest_reason_code": payload.get("latest_reason_code", ""),
            "export_dir": self.config.default_export_dir,
            "columns": list(self.config.csv_columns),
            "filename_template": self.config.export_filename_template,
        }
        thread = QThread(self)
        worker = ExportWorker(self.export_service, export_payload)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_export_finished)
        worker.error.connect(self._on_export_failed)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        self._export_threads.append((thread, worker))
        thread.start()
        self.statusBar().showMessage(f"正在导出 {str(export_payload['export_format']).upper()}...")

    def refresh_candidates(self) -> None:
        self.candidates_page.set_filter_options(
            self.repository.list_job_titles(),
            [dict(batch) for batch in self.repository.list_batches()],
            [dict(profile) for profile in self.repository.list_screening_profiles()],
        )
        self._candidate_request_id += 1
        request_id = self._candidate_request_id
        self._page_request_kind[request_id] = "candidates"
        self._latest_page_request["candidates"] = request_id
        self.candidate_query_requested.emit(
            {
                "request_id": request_id,
                "filters": self.candidates_page.current_filters(),
                "page": self.candidates_page.current_page(),
                "page_size": self.candidates_page.page_size(),
            }
        )
        self.statusBar().showMessage("正在加载候选人...")

    def _on_candidate_page_loaded(self, request_id: int, result: dict[str, object]) -> None:
        kind = str(result.get("kind") or "candidates")
        if self._page_request_kind.pop(request_id, "") != kind:
            return
        if self._latest_page_request.get(kind) != request_id:
            return
        rows = list(result["rows"])
        if kind == "review":
            self.review_page.set_page_result(
                rows,
                total=int(result["total"]),
                page=int(result["page"]),
                page_size=int(result["page_size"]),
            )
            self.statusBar().showMessage(f"人工复核：当前 {len(rows)} 条，共 {result['total']} 条")
            return
        if kind == "screening_results":
            self.ai_page.set_result_page(
                rows,
                total=int(result["total"]),
                page=int(result["page"]),
                page_size=int(result["page_size"]),
            )
            self.ai_page.show_efficiency_summary(
                self.repository.get_screening_efficiency_summary(int(result["run_id"]))
            )
            return
        self.candidates_page.set_page_result(
            rows,
            total=int(result["total"]),
            page=int(result["page"]),
            page_size=int(result["page_size"]),
        )
        self.statusBar().showMessage(
            f"候选人已加载：当前 {len(rows)} 条，共 {result['total']} 条"
        )
        if not self._profile_refresh_started:
            self._profile_refresh_started = True
            self.profile_refresh_thread.start()

    def _on_candidate_page_failed(self, request_id: int, message: str) -> None:
        kind = self._page_request_kind.pop(request_id, "")
        if not kind or self._latest_page_request.get(kind) != request_id:
            return
        if kind == "candidates":
            self.statusBar().showMessage(f"候选人加载失败：{message}")
        else:
            self.statusBar().showMessage(f"{kind} 加载失败：{message}")

    def refresh_dashboard_stats(self) -> None:
        stats = self.repository.get_dashboard_stats()
        self.dashboard_page.batch_id_value.setText(str(stats["latest_batch_id"] or "-"))
        self.dashboard_page.status_value.setText(
            DashboardPage.translate_status(str(stats["latest_batch_status"]))
        )
        self.dashboard_page.inserted_value.setText(str(stats["total_candidates"]))
        if self.local_api_server is not None:
            self.dashboard_page.set_local_api_status(self.local_api_server.endpoint)
        else:
            self.dashboard_page.set_local_api_status(f"http://127.0.0.1:{self.config.local_api_port}")
        self.dashboard_page.set_funnel_profiles(
            [dict(profile) for profile in self.repository.list_screening_profiles()]
        )
        funnel_filters = self.dashboard_page.current_funnel_filters()
        role_id = (
            int(funnel_filters["role_id"])
            if funnel_filters.get("role_id") is not None
            else None
        )
        minimum_rating = str(funnel_filters.get("minimum_rating") or "SSR")
        screened_since = self._funnel_screened_since(funnel_filters)
        self.dashboard_page.set_funnel_counts(
            self.repository.get_recruitment_funnel_counts(
                role_id=role_id,
                minimum_rating=minimum_rating,
                screened_since=screened_since,
            )
        )
        self.dashboard_page.set_manual_review_quality_summary(
            self.repository.get_manual_review_quality_summary(
                role_id=role_id,
                minimum_rating=minimum_rating,
                screened_since=screened_since,
            )
        )
        self.dashboard_page.set_ai_rating_cohort_summary(
            self.repository.get_ai_rating_cohort_summary(
                role_id=role_id,
                minimum_rating=minimum_rating,
                screened_since=screened_since,
            ),
            minimum_rating,
        )
        self.dashboard_page.set_rating_conversion_counts(
            [
                dict(row)
                for row in self.repository.get_ai_rating_conversion_counts(
                    role_id=role_id,
                    minimum_rating=minimum_rating,
                    screened_since=screened_since,
                )
            ]
        )
        detail_status = str(funnel_filters.get("detail_status") or "replied")
        detail_rating = str(funnel_filters.get("detail_rating") or "")
        self.dashboard_page.set_funnel_detail_candidates(
            [
                dict(row)
                for row in self.repository.list_recruitment_funnel_candidates(
                    role_id=role_id,
                    status=detail_status,
                    rating=detail_rating or None,
                    minimum_rating=None if detail_rating else minimum_rating,
                    screened_since=screened_since,
                )
            ]
        )
        self.dashboard_page.set_reason_counts(
            [
                dict(row)
                for row in self.repository.get_recruitment_reason_counts(
                    role_id=role_id,
                    minimum_rating=minimum_rating,
                    screened_since=screened_since,
                )
            ]
        )

    @staticmethod
    def _funnel_screened_since(filters: dict[str, object]) -> str | None:
        window_days = filters.get("window_days")
        if window_days is None or window_days == "":
            return None
        try:
            days = int(window_days)
        except (TypeError, ValueError):
            return None
        return (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")

    def refresh_review_queue(self) -> None:
        self.review_page.set_profiles(
            [dict(profile) for profile in self.repository.list_screening_profiles()]
        )
        filters = self.review_page.current_filters()
        self._candidate_request_id += 1
        request_id = self._candidate_request_id
        self._page_request_kind[request_id] = "review"
        self._latest_page_request["review"] = request_id
        self.candidate_query_requested.emit(
            {
                "request_id": request_id,
                "kind": "review",
                "filters": filters,
                "page": self.review_page.current_page(),
                "page_size": self.review_page.page_size(),
            }
        )
        self.statusBar().showMessage("正在加载人工复核队列...")

    def _save_settings(self, config) -> None:
        config.automation_flow = self.config.automation_flow
        self.config_service.save(config)
        self.config = config
        self.logging_service.configure(self.config.log_level)
        self.dashboard_page.load_config(self.config)
        self.settings_page.load_config(self.config)
        self._start_local_api_server()
        self.statusBar().showMessage("设置已保存")
        self.logger.info("Settings updated")

    def refresh_automation_flow(self, selected_run_id: int | None = None) -> None:
        profiles = [dict(row) for row in self.repository.list_screening_profiles()]
        runs = [dict(row) for row in self.repository.list_screening_runs(origin="automation")]
        self.automation_flow_page.set_profiles(
            profiles,
            selected_profile_id=self.config.automation_flow.profile_id,
        )
        self.automation_flow_page.set_runs(runs, selected_run_id=selected_run_id)
        run_id = selected_run_id or (int(runs[0]["id"]) if runs else None)
        if run_id is not None:
            self._load_automation_results(run_id)
        else:
            self.automation_flow_page.show_results([])

    def _automation_status_payload(self) -> dict[str, object]:
        with self._automation_config_lock:
            config = self.config_service.load()
            flow = config.automation_flow
            profile = (
                self.repository.get_screening_profile(int(flow.profile_id))
                if flow.profile_id is not None
                else None
            )
            ready = profile is not None and bool(flow.model and flow.provider)
            return {
                "ready": ready,
                "enabled": bool(flow.enabled),
                "profile_id": flow.profile_id,
                "profile_job_title": str(profile["job_title"]) if profile else "",
                "job_title": flow.job_title or (str(profile["job_title"]) if profile else ""),
                "source_url": flow.source_url,
                "provider": flow.provider,
                "model": flow.model,
                "max_candidates": flow.max_candidates,
            }

    def _start_automation_from_extension(self, _payload: dict[str, object]) -> dict[str, object]:
        with self._automation_config_lock:
            config = self.config_service.load()
            flow = config.automation_flow
            if flow.profile_id is None:
                raise ValueError("请先在桌面端“自动化流程”页面选择并保存筛选方案。")
            profile = self.repository.get_screening_profile(int(flow.profile_id))
            if profile is None:
                raise ValueError("自动化筛选方案不存在，请在桌面端重新选择并保存。")
            if not flow.provider or not flow.model:
                raise ValueError("自动化流程缺少 AI 服务商或模型配置。")
            flow.enabled = True
            if not flow.job_title:
                flow.job_title = str(profile["job_title"])
            config.automation_flow = flow
            self.config_service.save(config)
            self.config = config
            self._automation_armed = True
            result = self._automation_status_payload()
            result["message"] = "自动化流程已启动，等待插件完成滚动采集。"
            self.logger.info(
                "Automation started from extension profile=%s job=%s model=%s",
                flow.profile_id,
                flow.job_title,
                flow.model,
            )
            return result

    def _save_automation_flow(self, payload: dict[str, object]) -> bool:
        profile_id = payload.get("profile_id")
        if profile_id is None or self.repository.get_screening_profile(int(profile_id)) is None:
            self.automation_flow_page.set_status("请先选择一个已保存的筛选方案。")
            return False
        provider = dict(payload.get("provider") or {})
        model = str(provider.get("model") or "").strip()
        source_url = str(payload.get("source_url") or "").strip()
        if not model:
            self.automation_flow_page.set_status("请填写 AI 模型名称。")
            return False
        if not source_url:
            self.automation_flow_page.set_status("请填写采集页面。")
            return False

        self.config.automation_flow = AutomationFlowConfig(
            enabled=bool(payload.get("enabled")),
            profile_id=int(profile_id),
            job_title=str(payload.get("job_title") or "").strip(),
            source_url=source_url,
            max_candidates=int(payload.get("limit") or 0),
            provider=str(provider.get("provider") or "openai"),
            model=model,
            api_base=str(provider.get("api_base") or "").strip(),
            api_key_env=str(provider.get("api_key_env") or "").strip(),
        )
        self.config_service.save(self.config)
        self.automation_flow_page.set_status(
            "设置已保存，等待下一次采集。"
            if self.config.automation_flow.enabled
            else "设置已保存，自动衔接未启用。"
        )
        self.statusBar().showMessage("自动化流程设置已保存")
        return True

    def _arm_automation_flow(self, payload: dict[str, object]) -> None:
        payload = dict(payload)
        payload["enabled"] = True
        if not self._save_automation_flow(payload):
            return
        self._automation_armed = True
        self.automation_flow_page.set_waiting(True)
        flow = self.config.automation_flow
        self.dashboard_page.job_title_input.setText(flow.job_title)
        self.dashboard_page.source_url_input.setText(flow.source_url)
        self.statusBar().showMessage("自动化流程已启用，请在 Chrome 扩展中点击 AUTO")

    def _cancel_automation_flow(self) -> None:
        self._automation_armed = False
        self._queued_automation_batches.clear()
        self.config.automation_flow.enabled = False
        self.config_service.save(self.config)
        self.automation_flow_page.enabled_checkbox.setChecked(False)
        self.automation_flow_page.set_waiting(False)
        self.automation_flow_page.set_status("自动衔接已停用。")
        self.statusBar().showMessage("自动化流程已停用")

    def _load_candidate_detail(self, candidate_id: int) -> None:
        detail = self.repository.get_candidate_detail(candidate_id)
        self.candidates_page.show_candidate_detail(detail)

    def _record_recruitment_status_change(self, payload: dict[str, object]) -> None:
        try:
            candidate_id = int(payload["candidate_id"])
            self.repository.record_candidate_role_status_change(
                candidate_id=candidate_id,
                role_id=int(payload["role_id"]),
                to_status=str(payload["to_status"]),
                operator="user",
                reason_code=str(payload.get("reason_code") or ""),
                note=str(payload.get("note") or ""),
            )
            self._load_candidate_detail(candidate_id)
            self.refresh_candidates()
            self.refresh_review_queue()
            self.refresh_dashboard_stats()
            self.statusBar().showMessage("招聘进展已记录")
        except Exception as exc:
            self.logger.exception("Failed to record recruitment status change: %s", exc)
            QMessageBox.critical(self, "记录失败", str(exc))

    def refresh_ai_screen(self, selected_run_id: int | None = None) -> None:
        profiles = [dict(row) for row in self.repository.list_screening_profiles()]
        runs = [dict(row) for row in self.repository.list_screening_runs()]
        self.ai_page.set_profiles(profiles)
        self.ai_page.set_source_options(
            self.repository.list_job_titles(),
            [dict(batch) for batch in self.repository.list_batches()],
        )
        self.ai_page.set_runs(runs, selected_run_id=selected_run_id)
        run_id = selected_run_id or (int(runs[0]["id"]) if runs else None)
        if run_id is not None:
            self._load_screening_results(run_id)
        else:
            self.ai_page.show_results([])
            self.ai_page.show_efficiency_summary({})

    def _load_screening_profile(self, profile_id: int) -> None:
        row = self.repository.get_screening_profile(profile_id)
        self.ai_page.show_profile(dict(row) if row else None)

    def _ensure_builtin_screening_profiles(self) -> None:
        if any(str(row.get("job_title") or "") == "证券交易员" for row in self.repository.list_screening_profiles()):
            return
        profile = ScreeningProfile(
            job_title="证券交易员",
            jd_text="负责证券交易执行、交易风险控制、交易记录复盘与异常处理。",
            prompt_text="",
            must_have=["候选人资料中存在明确的证券或金融产品交易证据"],
            nice_to_have=["实盘权限、交易规模、收益或风险控制结果有明确证据"],
            risk_flags=["只出现‘交易’字样但未说明交易品种、职责、权限或结果"],
            exclusions=["仅有模拟盘、课程作业或与证券无关的泛交易描述"],
            interview_checks=["核验交易品种、账户权限、独立决策范围与风控边界"],
            evidence_policy={
                "explicit_evidence_required": True,
                "generic_trading_requires_manual_review": True,
            },
        )
        profile.prompt_text = self.prompt_manager.build_structured(profile)
        self.repository.save_screening_profile(profile)

    def _save_screening_profile(self, payload: dict[str, object]) -> ScreeningProfile | None:
        try:
            evidence_policy = dict(payload.get("evidence_policy") or {})
            if "_invalid" in evidence_policy:
                raise ValueError("证据策略必须是有效 JSON")
            structured_profile = ScreeningProfile(
                id=int(payload["id"]) if payload.get("id") is not None else None,
                job_title=str(payload.get("job_title") or "").strip(),
                jd_text=str(payload.get("jd_text") or "").strip(),
                prompt_text=str(payload.get("prompt_text") or ""),
                prompt_source=str(payload.get("prompt_source") or "generated"),
                must_have=list(payload.get("must_have") or []),
                nice_to_have=list(payload.get("nice_to_have") or []),
                risk_flags=list(payload.get("risk_flags") or []),
                exclusions=list(payload.get("exclusions") or []),
                interview_checks=list(payload.get("interview_checks") or []),
                evidence_policy=evidence_policy,
            )
            prompt_text = str(payload.get("prompt_text") or "")
            prompt_source = str(payload.get("prompt_source") or "generated")
            if not prompt_text:
                prompt_text = (
                    self.prompt_manager.build_structured(structured_profile)
                    if any(
                        [
                            structured_profile.must_have,
                            structured_profile.nice_to_have,
                            structured_profile.risk_flags,
                            structured_profile.exclusions,
                            structured_profile.interview_checks,
                            structured_profile.evidence_policy,
                        ]
                    )
                    else self.prompt_manager.build_from_jd(
                        structured_profile.job_title,
                        structured_profile.jd_text,
                    )
                )
                prompt_source = "generated"
            errors = self.prompt_manager.validate_screening_criteria(prompt_text)
            if errors:
                raise ValueError("筛选条件包含不能用于自动招聘评级的条件：" + "、".join(errors))
            structured_profile.prompt_text = prompt_text
            structured_profile.prompt_source = prompt_source
            profile = self.repository.save_screening_profile(structured_profile)
            self.ai_page.current_profile_id = profile.id
            self.refresh_ai_screen()
            self.refresh_automation_flow()
            self._load_screening_profile(int(profile.id))
            self.statusBar().showMessage(f"已保存筛选方案：{profile.job_title}")
            return profile
        except Exception as exc:
            QMessageBox.warning(self, "无法保存筛选方案", str(exc))
            return None

    def _clone_screening_profile(self, profile_id: int, new_job_title: str) -> None:
        try:
            profile = self.repository.clone_screening_profile(profile_id, new_job_title)
            self.ai_page.current_profile_id = profile.id
            self.refresh_ai_screen()
            self._load_screening_profile(int(profile.id))
            self.statusBar().showMessage(f"已复制筛选方案：{new_job_title}")
        except Exception as exc:
            QMessageBox.warning(self, "无法复制筛选方案", str(exc))

    def _delete_screening_profile(self, profile_id: int) -> None:
        self.repository.delete_screening_profile(profile_id)
        if self.config.automation_flow.profile_id == profile_id:
            self.config.automation_flow.enabled = False
            self.config.automation_flow.profile_id = None
            self.config_service.save(self.config)
            self.automation_flow_page.enabled_checkbox.setChecked(False)
        self.ai_page.clear_profile()
        self.refresh_ai_screen()
        self.refresh_automation_flow()
        self.statusBar().showMessage("筛选方案已删除")

    def _start_ai_screening(self, payload: dict[str, object]) -> None:
        if self._ai_screening_thread is not None:
            QMessageBox.information(self, "任务进行中", "已有 AI 初筛任务正在运行。")
            return

        profile_payload = dict(payload.get("profile") or {})
        profile = self._save_screening_profile(profile_payload)
        if profile is None:
            return
        candidates = self.repository.list_screening_candidates(
            job_title=str(payload.get("source_job_title") or ""),
            batch_id=payload.get("batch_id"),
            limit=int(payload.get("limit") or 0),
        )
        if not candidates:
            QMessageBox.information(self, "没有候选人", "当前岗位或批次没有可用于筛选的候选人。")
            return

        worker_payload = dict(payload)
        worker_payload["profile"] = profile.to_dict()
        worker_payload["candidates"] = candidates
        worker_payload["origin"] = "manual"
        self._launch_ai_screening(worker_payload, origin="manual")

    def _resume_ai_screening_run(self, run_id: int, *, reset_failed: bool = True) -> None:
        if self._ai_screening_thread is not None:
            QMessageBox.information(self, "Task running", "An AI screening task is already running.")
            return
        run = self.repository.get_screening_run(run_id)
        if run is None:
            QMessageBox.warning(self, "Run not found", f"Screening run #{run_id} was not found.")
            return
        profile = self.repository.get_screening_profile(int(run["profile_id"]))
        if profile is None:
            QMessageBox.warning(self, "Profile missing", "The screening profile for this run no longer exists.")
            return
        candidates = self.repository.list_screening_run_candidates(run_id)
        if not candidates:
            QMessageBox.information(self, "No tasks", "This run has no persisted screening tasks to resume.")
            return

        self.repository.recover_interrupted_screening_tasks()
        counts = self.repository.get_screening_task_counts(run_id)
        reset_count = 0
        if reset_failed and counts["failed"] > 0:
            reset_count = self.repository.reset_failed_screening_tasks(run_id)
            counts = self.repository.get_screening_task_counts(run_id)
        unfinished = counts["pending"] + counts["running"] + counts["retrying"]
        if unfinished == 0:
            self.ai_page.set_status("Selected screening run has no unfinished or failed tasks.")
            return
        if reset_count:
            self.ai_page.set_status(f"Reset {reset_count} failed tasks for retry.")

        page_provider = self.ai_page.provider_payload()
        provider = {
            "provider": str(run["provider"] or page_provider.get("provider") or "openai"),
            "model": str(run["model"] or page_provider.get("model") or ""),
            "api_base": str(page_provider.get("api_base") or ""),
            "api_key": str(page_provider.get("api_key") or ""),
            "api_key_env": str(page_provider.get("api_key_env") or "OPENAI_API_KEY"),
        }
        worker_payload = {
            "run_id": run_id,
            "profile": dict(profile),
            "provider": provider,
            "source_job_title": str(run["source_job_title"] or ""),
            "batch_id": run["batch_id"],
            "candidates": candidates,
            "origin": "manual",
        }
        self._launch_ai_screening(worker_payload, origin="manual")

    def _retry_ai_screening_task(self, task_id: int) -> None:
        if self._ai_screening_thread is not None:
            QMessageBox.information(self, "Task running", "An AI screening task is already running.")
            return
        run_id = self.repository.reset_failed_screening_task(task_id)
        if run_id is None:
            QMessageBox.information(self, "无法重试", "请选择状态为失败的 AI 筛选任务。")
            return
        self.ai_page.set_status(f"已重置任务 #{task_id}，准备继续筛选。")
        self.refresh_ai_screen(selected_run_id=run_id)
        self._resume_ai_screening_run(run_id, reset_failed=False)

    def _launch_ai_screening(self, worker_payload: dict[str, object], origin: str) -> None:
        worker_payload["provider"] = self._prepare_provider_payload(
            dict(worker_payload.get("provider") or {})
        )
        provider_error = self._validate_ai_provider_payload(dict(worker_payload["provider"]))
        if provider_error:
            if origin == "automation":
                self.automation_flow_page.set_running(False)
                self.automation_flow_page.set_status(f"AI 配置不完整：{provider_error}")
            else:
                self.ai_page.set_running(False)
                self.ai_page.set_status(f"AI 配置不完整：{provider_error}")
                QMessageBox.warning(self, "AI 配置不完整", provider_error)
            self.statusBar().showMessage("AI 配置不完整")
            return
        candidates = list(worker_payload["candidates"])
        thread = QThread(self)
        worker = AIScreeningWorker(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            payload=worker_payload,
            logger=self.logging_service.get_logger("ai.screening"),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(lambda progress: self._on_ai_screening_progress(progress, origin))
        worker.progress.connect(lambda progress: self.statusBar().showMessage(progress.message))
        worker.finished.connect(self._on_ai_screening_finished)
        worker.error.connect(self._on_ai_screening_failed)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_ai_screening_thread)
        self._ai_screening_thread = (thread, worker)
        self._ai_screening_origin = origin
        if origin == "automation":
            self.automation_flow_page.set_waiting(False)
            self.automation_flow_page.set_running(True, total=len(candidates))
            self.automation_flow_page.set_status(f"已收到采集批次，准备筛选 {len(candidates)} 位候选人...")
            self.statusBar().showMessage("自动化 AI 初筛已启动")
        else:
            self.ai_page.set_running(True, total=len(candidates))
            self.ai_page.set_status(f"准备筛选 {len(candidates)} 位候选人...")
            self.statusBar().showMessage("AI 初筛已启动")
        thread.start()

    def _validate_ai_provider_payload(self, provider_payload: dict[str, object]) -> str:
        try:
            validate_provider_settings(
                ProviderSettings(
                    provider=str(provider_payload.get("provider") or "openai"),
                    model=str(provider_payload.get("model") or ""),
                    api_base=str(provider_payload.get("api_base") or ""),
                    api_key=str(provider_payload.get("api_key") or ""),
                    api_key_env=str(provider_payload.get("api_key_env") or "OPENAI_API_KEY"),
                )
            )
        except AIProviderError as exc:
            return str(exc)
        return ""

    def _prepare_provider_payload(self, provider_payload: dict[str, object]) -> dict[str, object]:
        payload = dict(provider_payload)
        provider = str(payload.get("provider") or "openai")
        api_base = str(payload.get("api_base") or "")
        if api_base:
            payload["api_key"] = self.credential_store.resolve(
                provider,
                api_base,
                str(payload.get("api_key") or ""),
                str(payload.get("api_key_env") or ""),
            )
        return payload

    def _queue_automation_screening(self, capture_result: dict[str, object]) -> None:
        with self._automation_config_lock:
            self.config = self.config_service.load()
        if not self.config.automation_flow.enabled:
            return
        batch_id = capture_result.get("batch_id")
        total_items = int(
            capture_result.get("total_batch_items")
            or capture_result.get("parsed_cards")
            or capture_result.get("total_unique")
            or 0
        )
        if batch_id is None or total_items <= 0:
            self.automation_flow_page.set_status("采集结束，但本批次没有可用于初筛的候选人。")
            return
        payload = {
            "batch_id": int(batch_id),
            "job_title": str(capture_result.get("job_title") or self.config.automation_flow.job_title),
            "source_url": str(capture_result.get("source_url") or self.config.automation_flow.source_url),
        }
        if self._ai_screening_thread is not None:
            queued_ids = {int(item["batch_id"]) for item in self._queued_automation_batches}
            if int(payload["batch_id"]) not in queued_ids:
                self._queued_automation_batches.append(payload)
            self.automation_flow_page.set_status(
                f"采集批次 #{batch_id} 已完成，当前有 {len(self._queued_automation_batches)} 个批次等待初筛。"
            )
            return
        self._start_automation_screening(payload)

    def _start_automation_screening(self, capture_result: dict[str, object]) -> None:
        flow = self.config.automation_flow
        if not flow.enabled or flow.profile_id is None:
            return
        profile_row = self.repository.get_screening_profile(int(flow.profile_id))
        if profile_row is None:
            self.automation_flow_page.set_status("自动化筛选方案已不存在，请重新选择并保存。")
            return
        batch_id = int(capture_result["batch_id"])
        candidates = self.repository.list_screening_candidates(
            batch_id=batch_id,
            limit=flow.max_candidates,
        )
        if not candidates:
            self.automation_flow_page.set_status(f"批次 #{batch_id} 没有可用于初筛的候选人。")
            return
        page_provider = self.automation_flow_page.provider_payload()
        api_key = str(page_provider.get("api_key") or "")
        ai_page_provider = self.ai_page.provider_payload()
        if not api_key and str(ai_page_provider.get("provider") or "") == flow.provider:
            api_key = str(ai_page_provider.get("api_key") or "")
        provider = {
            "provider": flow.provider,
            "model": flow.model,
            "api_base": flow.api_base,
            "api_key": api_key,
            "api_key_env": flow.api_key_env,
        }
        worker_payload = {
            "profile": dict(profile_row),
            "provider": provider,
            "source_job_title": str(capture_result.get("job_title") or flow.job_title),
            "batch_id": batch_id,
            "limit": flow.max_candidates,
            "candidates": candidates,
            "origin": "automation",
        }
        self._automation_armed = False
        self._launch_ai_screening(worker_payload, origin="automation")

    def _on_ai_screening_progress(self, progress, origin: str) -> None:
        if origin == "automation":
            self.automation_flow_page.update_progress(progress)
        else:
            self.ai_page.update_progress(progress)

    def _stop_ai_screening(self) -> None:
        if self._ai_screening_thread is None:
            return
        self._ai_screening_thread[1].request_stop()
        if self._ai_screening_origin == "automation":
            self.automation_flow_page.set_status("已发送停止请求，当前候选人处理完成后停止。")
        else:
            self.ai_page.set_status("已发送停止请求，当前候选人处理完成后停止。")

    def _on_ai_screening_finished(self, result: dict[str, object]) -> None:
        run_id = int(result["run_id"])
        if self._ai_screening_origin == "automation":
            self.automation_flow_page.set_running(False)
            self.automation_flow_page.set_status(str(result.get("message") or "自动化 AI 初筛完成。"))
            self.refresh_automation_flow(selected_run_id=run_id)
        else:
            self.ai_page.set_running(False)
            self.ai_page.set_status(str(result.get("message") or "AI 初筛完成。"))
            self.refresh_ai_screen(selected_run_id=run_id)
        self.statusBar().showMessage(
            f"AI 初筛结束：完成 {result.get('completed', 0)}，失败 {result.get('failed', 0)}"
        )

    def _on_ai_screening_failed(self, message: str) -> None:
        if self._ai_screening_origin == "automation":
            self.automation_flow_page.set_running(False)
            self.automation_flow_page.set_status(f"自动化 AI 初筛失败：{message}")
        else:
            self.ai_page.set_running(False)
            self.ai_page.set_status(f"AI 初筛失败：{message}")
            QMessageBox.critical(self, "AI 初筛失败", message)
        self.statusBar().showMessage("AI 初筛失败")

    def _clear_ai_screening_thread(self) -> None:
        self._ai_screening_thread = None
        self._ai_screening_origin = "manual"
        if self._queued_automation_batches:
            queued = self._queued_automation_batches.pop(0)
            self._start_automation_screening(queued)

    def _test_ai_connection(self, provider_payload: dict[str, object], target: str = "ai") -> None:
        status_page = self.automation_flow_page if target == "automation" else self.ai_page
        if self._ai_test_running:
            status_page.set_status("API 连接测试正在进行，请等待当前测试完成。")
            return
        typed_key = str(provider_payload.get("api_key") or "").strip()
        provider_payload = self._prepare_provider_payload(provider_payload)
        provider_error = self._validate_ai_provider_payload(provider_payload)
        if provider_error:
            status_page.set_status(f"API 配置无效：{provider_error}")
            return
        self._ai_test_context = {
            "target": target,
            "provider_payload": provider_payload,
            "typed_key": typed_key,
        }
        self._ai_test_running = True
        status_page.set_status("正在测试 AI API 连接...")
        self.ai_connection_test_requested.emit(provider_payload)

    def _on_ai_connection_test_finished(self, result: object) -> None:
        self._ai_test_running = False
        target = str(self._ai_test_context.get("target") or "ai")
        status_page = self.automation_flow_page if target == "automation" else self.ai_page
        status_page.set_status(f"API 连接成功：{getattr(result, 'persona', '')}")
        self.statusBar().showMessage("AI API 连接成功")
        typed_key = str(self._ai_test_context.get("typed_key") or "")
        if typed_key:
            self._save_test_credential(
                dict(self._ai_test_context.get("provider_payload") or {}), typed_key
            )

    def _on_ai_connection_test_error(self, message: str) -> None:
        self._ai_test_running = False
        target = str(self._ai_test_context.get("target") or "ai")
        status_page = self.automation_flow_page if target == "automation" else self.ai_page
        status_page.set_status(f"API 连接失败：{message}")
        self.statusBar().showMessage("AI API 连接失败")

    def _cancel_ai_connection_test(self) -> None:
        if self._ai_test_running:
            self.ai_test_worker.request_cancel()
        self.ai_page.set_status("已请求取消 API 连接测试。")

    def _delete_ai_credential(self, payload: dict[str, object]) -> None:
        try:
            deleted = self.credential_store.delete(
                str(payload.get("provider") or "openai"),
                str(payload.get("api_base") or ""),
            )
            message = "已删除保存的 API Key。" if deleted else "没有找到已保存的 API Key。"
            self.ai_page.set_status(message)
        except Exception as exc:
            self.ai_page.set_status(f"删除 API Key 失败：{exc}")

    def _save_test_credential(self, provider_payload: dict[str, object], api_key: str) -> None:
        try:
            self.credential_store.save(
                str(provider_payload.get("provider") or "openai"),
                str(provider_payload.get("api_base") or ""),
                api_key,
            )
        except Exception as exc:
            self.logger.warning("Could not save API credential: %s", exc)

    def _load_screening_results(self, run_id: int) -> None:
        self._candidate_request_id += 1
        request_id = self._candidate_request_id
        self._page_request_kind[request_id] = "screening_results"
        self._latest_page_request["screening_results"] = request_id
        self.candidate_query_requested.emit(
            {
                "request_id": request_id,
                "kind": "screening_results",
                "run_id": run_id,
                "page": self.ai_page.result_page(),
                "page_size": self.ai_page.result_page_size(),
            }
        )

    def _load_automation_results(self, run_id: int) -> None:
        rows = [dict(row) for row in self.repository.list_screening_results(run_id)]
        self.automation_flow_page.show_results(rows)

    def _on_browser_opened(self, payload: dict[str, object]) -> None:
        message = str(payload.get("message") or "浏览器已打开")
        self.dashboard_page.set_message(message)
        self.dashboard_page.source_url_input.setText(str(payload.get("current_url") or self.config.target_url))
        self.statusBar().showMessage(message)
        if payload.get("status") == "waiting_user":
            QMessageBox.information(self, "需要手动处理", message)
        elif payload.get("status") == "blocked":
            QMessageBox.information(self, "已切换普通浏览器", message)

    def _on_capture_progress(self, progress) -> None:
        self.dashboard_page.update_progress(progress)
        self.statusBar().showMessage(progress.message or "任务执行中")

    def _on_capture_finished(self, result) -> None:
        self._capture_running = False
        self.dashboard_page.set_running(False)
        self.dashboard_page.update_result(result)
        self.refresh_candidates()
        self.refresh_dashboard_stats()
        self.statusBar().showMessage(result.message or f"采集结束：{result.status}")
        if result.status in {"completed", "stopped"}:
            self._queue_automation_screening(result.to_dict())
        if result.status == "waiting_user":
            QMessageBox.information(self, "需要手动处理", result.message or "请完成登录或验证后再继续。")

    def _on_extension_imported(self, result: dict[str, object]) -> None:
        self.refresh_candidates()
        self.refresh_dashboard_stats()
        self.dashboard_page.update_result(SimpleNamespace(**result))
        self.dashboard_page.set_message(
            f"扩展已导入 {result.get('parsed_cards', 0)} 张卡片，当前批次 #{result.get('batch_id')}。"
        )
        self.statusBar().showMessage(f"扩展导入完成：批次 #{result.get('batch_id')}")
        self._queue_automation_screening(result)

    def _on_extension_import_error(self, message: str) -> None:
        self.dashboard_page.set_message(message)
        if self.config.automation_flow.enabled:
            self.automation_flow_page.set_status(f"采集导入失败：{message}")
        self.statusBar().showMessage("扩展导入失败")

    def _on_worker_error(self, message: str) -> None:
        self._capture_running = False
        self.dashboard_page.set_running(False)
        self.dashboard_page.set_message(message)
        if self._automation_armed:
            self.automation_flow_page.set_status(f"自动化采集失败：{message}")
        self.statusBar().showMessage("任务失败")
        QMessageBox.critical(self, "任务失败", message)

    def _on_export_finished(self, result) -> None:
        export_label = result.export_format.upper()
        self.statusBar().showMessage(f"{export_label} 导出完成：{result.file_path}")
        QMessageBox.information(
            self,
            "导出完成",
            f"已导出 {result.row_count} 行 {export_label} 数据。\n{result.file_path}",
        )

    def _on_export_failed(self, message: str) -> None:
        self.statusBar().showMessage("导出失败")
        QMessageBox.critical(self, "导出失败", message)

    def _on_page_changed(self, index: int) -> None:
        page = self._page_scroll_areas[index].widget()
        if page is self.automation_flow_page:
            self.refresh_automation_flow()
        elif page is self.candidates_page:
            self.refresh_candidates()
        elif page is self.ai_page:
            self.refresh_ai_screen()
        elif page is self.review_page:
            self.refresh_review_queue()

    def _append_log_line(self, message: str) -> None:
        self.log_view.appendPlainText(message)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def closeEvent(self, event: QCloseEvent) -> None:
        self.ui_settings.setValue("window_geometry", self.saveGeometry())
        self.ui_settings.setValue("window_state", self.saveState())
        self.ui_settings.sync()
        if self.local_api_server is not None:
            self.local_api_server.stop()
        if self._ai_screening_thread is not None:
            self._ai_screening_thread[1].request_stop()
            self._ai_screening_thread[0].quit()
            self._ai_screening_thread[0].wait(2_000)
        self.ai_test_worker.request_cancel()
        self.ai_test_thread.quit()
        self.ai_test_thread.wait(16_000)
        self.shutdown_requested.emit()
        self.automation_thread.quit()
        self.automation_thread.wait(5_000)
        for thread, _worker in list(self._export_threads):
            if thread.isRunning():
                thread.quit()
                thread.wait(2_000)
        self.candidate_query_thread.quit()
        self.candidate_query_thread.wait(2_000)
        self.profile_refresh_worker.request_stop()
        self.profile_refresh_thread.quit()
        self.profile_refresh_thread.wait(5_000)
        self.logging_service.unsubscribe(self.log_bridge.message.emit)
        self.logging_service.close()
        self.database.close_thread_connection()
        super().closeEvent(event)
