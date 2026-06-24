from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.models import CollectOptions


STATUS_LABELS = {
    "idle": "空闲",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "stopped": "已停止",
    "waiting_user": "等待人工处理",
}


class DashboardPage(QWidget):
    open_browser_requested = Signal(str)
    start_capture_requested = Signal(object)
    stop_requested = Signal()
    export_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        form_group = QGroupBox("采集控制")
        form_layout = QFormLayout(form_group)
        self.job_title_input = QLineEdit()
        self.source_url_input = QLineEdit()
        self.note_input = QLineEdit()
        form_layout.addRow("岗位名称", self.job_title_input)
        form_layout.addRow("目标链接", self.source_url_input)
        form_layout.addRow("批次备注", self.note_input)

        action_row = QHBoxLayout()
        self.open_browser_button = QPushButton("打开 Boss 页面")
        self.start_capture_button = QPushButton("开始采集")
        self.stop_button = QPushButton("停止任务")
        action_row.addWidget(self.open_browser_button)
        action_row.addWidget(self.start_capture_button)
        action_row.addWidget(self.stop_button)
        action_row.addStretch(1)

        export_group = QGroupBox("导出当前批次")
        export_layout = QHBoxLayout(export_group)
        self.export_csv_button = QPushButton("导出 CSV")
        self.export_jsonl_button = QPushButton("导出 JSONL")
        self.export_markdown_button = QPushButton("导出 Markdown")
        export_layout.addWidget(self.export_csv_button)
        export_layout.addWidget(self.export_jsonl_button)
        export_layout.addWidget(self.export_markdown_button)
        export_layout.addStretch(1)

        stats_group = QGroupBox("运行状态")
        stats_layout = QGridLayout(stats_group)
        self.status_value = QLabel("空闲")
        self.batch_id_value = QLabel("-")
        self.round_value = QLabel("0")
        self.loaded_cards_value = QLabel("0")
        self.unique_value = QLabel("0")
        self.inserted_value = QLabel("0")
        self.local_api_value = QLabel("-")
        self.capture_mode_value = QLabel("Chrome 扩展")
        stats_layout.addWidget(QLabel("当前状态"), 0, 0)
        stats_layout.addWidget(self.status_value, 0, 1)
        stats_layout.addWidget(QLabel("批次 ID"), 0, 2)
        stats_layout.addWidget(self.batch_id_value, 0, 3)
        stats_layout.addWidget(QLabel("滚动轮次"), 1, 0)
        stats_layout.addWidget(self.round_value, 1, 1)
        stats_layout.addWidget(QLabel("当前已加载"), 1, 2)
        stats_layout.addWidget(self.loaded_cards_value, 1, 3)
        stats_layout.addWidget(QLabel("本次去重后"), 2, 0)
        stats_layout.addWidget(self.unique_value, 2, 1)
        stats_layout.addWidget(QLabel("累计入库"), 2, 2)
        stats_layout.addWidget(self.inserted_value, 2, 3)
        stats_layout.addWidget(QLabel("本地接口"), 3, 0)
        stats_layout.addWidget(self.local_api_value, 3, 1)
        stats_layout.addWidget(QLabel("采集模式"), 3, 2)
        stats_layout.addWidget(self.capture_mode_value, 3, 3)

        self.hint_label = QLabel(
            "Boss 采集已切换为 Chrome 扩展模式。请在普通 Chrome 页面中手动登录 Boss，"
            "再通过扩展执行“自动滚动到底后采集”。如果要给 AI 做批量初筛，优先导出 JSONL。"
        )
        self.hint_label.setWordWrap(True)

        self.message_label = QLabel("就绪")
        self.message_label.setWordWrap(True)

        root_layout.addWidget(form_group)
        root_layout.addLayout(action_row)
        root_layout.addWidget(export_group)
        root_layout.addWidget(stats_group)
        root_layout.addWidget(self.hint_label)
        root_layout.addWidget(self.message_label)
        root_layout.addStretch(1)

        self.open_browser_button.clicked.connect(self._emit_open_browser)
        self.start_capture_button.clicked.connect(self._emit_start_capture)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.export_csv_button.clicked.connect(lambda: self.export_requested.emit("csv"))
        self.export_jsonl_button.clicked.connect(lambda: self.export_requested.emit("jsonl"))
        self.export_markdown_button.clicked.connect(lambda: self.export_requested.emit("markdown"))

    def load_config(self, config) -> None:
        default_job_title = config.default_job_title or ""
        if default_job_title == "Boss Recommended Talent":
            default_job_title = "Boss 推荐牛人"
        self.job_title_input.setText(default_job_title)
        self.source_url_input.setText(config.target_url)
        self.local_api_value.setText(f"http://127.0.0.1:{config.local_api_port}")

    def build_collect_options(self) -> CollectOptions:
        return CollectOptions(
            job_title=self.job_title_input.text().strip() or "Boss 推荐牛人",
            source_url=self.source_url_input.text().strip(),
            note=self.note_input.text().strip(),
        )

    def set_running(self, running: bool) -> None:
        self.start_capture_button.setEnabled(not running)
        self.open_browser_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def update_progress(self, progress) -> None:
        self.status_value.setText(self.translate_status(progress.status))
        self.batch_id_value.setText(str(progress.batch_id or "-"))
        self.round_value.setText(str(progress.round_index))
        self.loaded_cards_value.setText(str(progress.loaded_cards))
        self.unique_value.setText(str(progress.total_unique))
        self.inserted_value.setText(str(progress.total_inserted_candidates))
        self.message_label.setText(progress.message or "任务执行中。")

    def update_result(self, result) -> None:
        self.status_value.setText(self.translate_status(result.status))
        self.batch_id_value.setText(str(result.batch_id or "-"))
        self.round_value.setText(str(getattr(result, "rounds_completed", 0)))
        received_cards = getattr(result, "received_cards", 0) or getattr(result, "total_unique", 0)
        self.loaded_cards_value.setText(str(received_cards))
        self.unique_value.setText(str(result.total_unique))
        self.inserted_value.setText(str(result.total_inserted_candidates))
        self.message_label.setText(result.message or "任务已完成。")

    def set_message(self, message: str) -> None:
        self.message_label.setText(message)

    def set_status(self, status: str) -> None:
        self.status_value.setText(self.translate_status(status))

    def set_local_api_status(self, endpoint: str) -> None:
        self.local_api_value.setText(endpoint)

    def _emit_open_browser(self) -> None:
        self.open_browser_requested.emit(self.source_url_input.text().strip())

    def _emit_start_capture(self) -> None:
        self.start_capture_requested.emit(self.build_collect_options())

    @staticmethod
    def translate_status(status: str) -> str:
        return STATUS_LABELS.get(status, status)
