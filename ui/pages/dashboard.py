from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.models import CollectOptions
from ui.pages.candidates import REASON_CODE_LABELS


STATUS_LABELS = {
    "idle": "空闲",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "stopped": "已停止",
    "waiting_user": "等待人工处理",
}

RECRUITMENT_STATUS_LABELS = {
    "collected": "已采集",
    "screened": "已筛选",
    "priority_outreach": "优先触达",
    "contacted": "已联系",
    "replied": "已回复",
    "interviewing": "面试中",
    "offer": "Offer",
    "hired": "已入职",
    "rejected": "已拒绝",
    "talent_pool": "人才库",
}

FUNNEL_STATUS_ORDER = [
    "screened",
    "priority_outreach",
    "contacted",
    "replied",
    "interviewing",
    "offer",
    "hired",
    "rejected",
    "talent_pool",
    "collected",
]


class DashboardPage(QWidget):
    open_browser_requested = Signal(str)
    start_capture_requested = Signal(object)
    stop_requested = Signal()
    export_requested = Signal(str)
    funnel_refresh_requested = Signal()

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

        funnel_group = QGroupBox("招聘漏斗")
        funnel_layout = QVBoxLayout(funnel_group)
        funnel_filter_row = QHBoxLayout()
        self.funnel_role_combo = QComboBox()
        self.funnel_role_combo.addItem("全部岗位", None)
        self.funnel_rating_combo = QComboBox()
        self.funnel_rating_combo.addItem("UR 及以上", "UR")
        self.funnel_rating_combo.addItem("SSR 及以上", "SSR")
        self.funnel_rating_combo.addItem("SR 及以上", "SR")
        self.funnel_rating_combo.addItem("R 及以上", "R")
        self.funnel_rating_combo.addItem("N 及以上", "N")
        self.funnel_rating_combo.setCurrentIndex(1)
        self.funnel_window_combo = QComboBox()
        self.funnel_window_combo.addItem("近90天", 90)
        self.funnel_window_combo.addItem("近30天", 30)
        self.funnel_window_combo.addItem("近180天", 180)
        self.funnel_window_combo.addItem("近365天", 365)
        self.funnel_window_combo.addItem("全部时间", None)
        self.funnel_refresh_button = QPushButton("刷新")
        funnel_filter_row.addWidget(QLabel("岗位"))
        funnel_filter_row.addWidget(self.funnel_role_combo, 2)
        funnel_filter_row.addWidget(QLabel("最低评级"))
        funnel_filter_row.addWidget(self.funnel_rating_combo)
        funnel_filter_row.addWidget(QLabel("AI筛选时间"))
        funnel_filter_row.addWidget(self.funnel_window_combo)
        funnel_filter_row.addWidget(self.funnel_refresh_button)
        funnel_filter_row.addStretch(1)
        self.funnel_table = QTableWidget(0, 2)
        self.funnel_table.setHorizontalHeaderLabels(["阶段", "人数"])
        self.funnel_table.setSelectionMode(QTableWidget.NoSelection)
        self.funnel_table.setAlternatingRowColors(True)
        self.funnel_table.horizontalHeader().setStretchLastSection(True)
        self.rating_conversion_table = QTableWidget(0, 8)
        self.rating_conversion_table.setHorizontalHeaderLabels(
            ["评级", "已筛选", "已联系", "已回复", "面试", "Offer", "入职", "拒绝"]
        )
        self.rating_conversion_table.setSelectionMode(QTableWidget.NoSelection)
        self.rating_conversion_table.setAlternatingRowColors(True)
        self.rating_conversion_table.horizontalHeader().setStretchLastSection(True)
        self.reason_table = QTableWidget(0, 2)
        self.reason_table.setHorizontalHeaderLabels(["原因", "人数"])
        self.reason_table.setSelectionMode(QTableWidget.NoSelection)
        self.reason_table.setAlternatingRowColors(True)
        self.reason_table.horizontalHeader().setStretchLastSection(True)
        self.funnel_detail_status_combo = QComboBox()
        for label, value in [
            ("已回复", "replied"),
            ("已联系", "contacted"),
            ("面试中", "interviewing"),
            ("Offer", "offer"),
            ("已入职", "hired"),
            ("已拒绝", "rejected"),
            ("人才库", "talent_pool"),
            ("已筛选", "screened"),
        ]:
            self.funnel_detail_status_combo.addItem(label, value)
        self.funnel_detail_rating_combo = QComboBox()
        for label, value in [
            ("全部评级", ""),
            ("UR", "UR"),
            ("SSR", "SSR"),
            ("SR", "SR"),
            ("R", "R"),
            ("N", "N"),
        ]:
            self.funnel_detail_rating_combo.addItem(label, value)
        self.funnel_detail_rating_combo.setCurrentIndex(2)
        detail_filter_row = QHBoxLayout()
        detail_filter_row.addWidget(QLabel("明细阶段"))
        detail_filter_row.addWidget(self.funnel_detail_status_combo)
        detail_filter_row.addWidget(QLabel("精确评级"))
        detail_filter_row.addWidget(self.funnel_detail_rating_combo)
        detail_filter_row.addStretch(1)
        self.funnel_detail_table = QTableWidget(0, 9)
        self.funnel_detail_table.setHorizontalHeaderLabels(
            ["候选人", "评级", "阶段", "复核结论", "岗位方向", "城市", "年限", "当前状态", "到达时间"]
        )
        self.funnel_detail_table.setSelectionMode(QTableWidget.NoSelection)
        self.funnel_detail_table.setAlternatingRowColors(True)
        self.funnel_detail_table.horizontalHeader().setStretchLastSection(True)
        self.review_quality_label = QLabel("人工池占比：暂无")
        self.review_quality_label.setWordWrap(True)
        self.cohort_summary_label = QLabel("高评级复盘：暂无")
        self.cohort_summary_label.setWordWrap(True)
        funnel_layout.addLayout(funnel_filter_row)
        funnel_layout.addWidget(self.review_quality_label)
        funnel_layout.addWidget(self.cohort_summary_label)
        funnel_layout.addWidget(self.funnel_table)
        funnel_layout.addWidget(QLabel("按 AI 评级转化"))
        funnel_layout.addWidget(self.rating_conversion_table)
        funnel_layout.addWidget(QLabel("漏斗明细"))
        funnel_layout.addLayout(detail_filter_row)
        funnel_layout.addWidget(self.funnel_detail_table)
        funnel_layout.addWidget(QLabel("原因分布"))
        funnel_layout.addWidget(self.reason_table)

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
        root_layout.addWidget(funnel_group)
        root_layout.addWidget(self.hint_label)
        root_layout.addWidget(self.message_label)
        root_layout.addStretch(1)

        self.open_browser_button.clicked.connect(self._emit_open_browser)
        self.start_capture_button.clicked.connect(self._emit_start_capture)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.export_csv_button.clicked.connect(lambda: self.export_requested.emit("csv"))
        self.export_jsonl_button.clicked.connect(lambda: self.export_requested.emit("jsonl"))
        self.export_markdown_button.clicked.connect(lambda: self.export_requested.emit("markdown"))
        self.funnel_refresh_button.clicked.connect(self.funnel_refresh_requested.emit)
        self.funnel_role_combo.currentIndexChanged.connect(self.funnel_refresh_requested.emit)
        self.funnel_rating_combo.currentIndexChanged.connect(self.funnel_refresh_requested.emit)
        self.funnel_window_combo.currentIndexChanged.connect(self.funnel_refresh_requested.emit)
        self.funnel_detail_status_combo.currentIndexChanged.connect(self.funnel_refresh_requested.emit)
        self.funnel_detail_rating_combo.currentIndexChanged.connect(self.funnel_refresh_requested.emit)

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

    def current_funnel_filters(self) -> dict[str, object]:
        return {
            "role_id": self.funnel_role_combo.currentData(),
            "minimum_rating": self.funnel_rating_combo.currentData() or "SSR",
            "window_days": self.funnel_window_combo.currentData(),
            "detail_status": self.funnel_detail_status_combo.currentData() or "replied",
            "detail_rating": self.funnel_detail_rating_combo.currentData() or "",
        }

    def set_funnel_profiles(self, profiles: list[dict[str, object]]) -> None:
        current_role = self.funnel_role_combo.currentData()
        self.funnel_role_combo.blockSignals(True)
        self.funnel_role_combo.clear()
        self.funnel_role_combo.addItem("全部岗位", None)
        for profile in profiles:
            self.funnel_role_combo.addItem(str(profile["job_title"]), int(profile["id"]))
        index = self.funnel_role_combo.findData(current_role)
        self.funnel_role_combo.setCurrentIndex(max(0, index))
        self.funnel_role_combo.blockSignals(False)

    def set_funnel_counts(self, counts: dict[str, int]) -> None:
        self.funnel_table.setRowCount(len(FUNNEL_STATUS_ORDER))
        for row_index, status in enumerate(FUNNEL_STATUS_ORDER):
            label_item = QTableWidgetItem(RECRUITMENT_STATUS_LABELS.get(status, status))
            count_item = QTableWidgetItem(str(counts.get(status, 0)))
            self.funnel_table.setItem(row_index, 0, label_item)
            self.funnel_table.setItem(row_index, 1, count_item)
        self.funnel_table.resizeColumnsToContents()

    def set_manual_review_quality_summary(self, summary: dict[str, int]) -> None:
        total = int(summary.get("active_total", 0))
        manual = int(summary.get("manual_review_total", 0))
        if total <= 0:
            self.review_quality_label.setText("人工池占比：暂无待处理候选人")
            return
        ratio = manual / total
        if ratio < 0.1:
            band = "偏低，留意是否漏掉低置信或风险候选人"
        elif ratio <= 0.3:
            band = "正常，接近 10% 到 30% 目标区间"
        else:
            band = "偏高，规则或 Prompt 可能过于保守"
        parts = [
            f"人工池 {manual}/{total} ({ratio:.0%})",
            band,
            f"规则人工 {summary.get('rule_manual_check', 0)}",
            f"暂缓 {summary.get('rule_hold', 0)}",
            f"AI失败 {summary.get('ai_failed', 0)}",
            f"低置信 {summary.get('low_confidence', 0)}",
            f"模型人工 {summary.get('model_manual_action', 0)}",
            f"风险 {summary.get('risky', 0)}",
        ]
        self.review_quality_label.setText("人工池占比：" + " / ".join(parts))

    def set_ai_rating_cohort_summary(self, summary: dict[str, object], minimum_rating: str) -> None:
        screened = int(summary.get("screened_count") or 0)
        if screened <= 0:
            self.cohort_summary_label.setText(f"高评级复盘：暂无 {minimum_rating} 及以上候选人")
            return
        parts = [
            f"{minimum_rating}及以上 {screened}",
            f"优先触达 {self._format_count_with_rate(int(summary.get('priority_outreach_count') or 0), screened)}",
            f"已联系 {self._format_count_with_rate(int(summary.get('contacted_count') or 0), screened)}",
            f"已回复 {self._format_count_with_rate(int(summary.get('replied_count') or 0), screened)}",
            f"面试 {self._format_count_with_rate(int(summary.get('interviewing_count') or 0), screened)}",
            f"Offer {self._format_count_with_rate(int(summary.get('offer_count') or 0), screened)}",
            f"入职 {self._format_count_with_rate(int(summary.get('hired_count') or 0), screened)}",
            f"拒绝 {self._format_count_with_rate(int(summary.get('rejected_count') or 0), screened)}",
            f"人才库 {self._format_count_with_rate(int(summary.get('talent_pool_count') or 0), screened)}",
        ]
        self.cohort_summary_label.setText("高评级复盘：" + " / ".join(parts))

    def set_rating_conversion_counts(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            self.rating_conversion_table.setRowCount(1)
            self.rating_conversion_table.setItem(0, 0, QTableWidgetItem("暂无 AI 评级记录"))
            for column in range(1, 8):
                self.rating_conversion_table.setItem(0, column, QTableWidgetItem("0"))
            self.rating_conversion_table.resizeColumnsToContents()
            return
        self.rating_conversion_table.setRowCount(len(rows))
        columns = [
            ("rating", False),
            ("screened_count", False),
            ("contacted_count", True),
            ("replied_count", True),
            ("interviewing_count", True),
            ("offer_count", True),
            ("hired_count", True),
            ("rejected_count", True),
        ]
        for row_index, row in enumerate(rows):
            total = int(row.get("screened_count") or 0)
            for column_index, (key, with_rate) in enumerate(columns):
                if key == "rating":
                    text = str(row.get(key) or "")
                else:
                    count = int(row.get(key) or 0)
                    text = self._format_count_with_rate(count, total) if with_rate else str(count)
                self.rating_conversion_table.setItem(row_index, column_index, QTableWidgetItem(text))
        self.rating_conversion_table.resizeColumnsToContents()

    def set_reason_counts(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            self.reason_table.setRowCount(1)
            self.reason_table.setItem(0, 0, QTableWidgetItem("暂无原因记录"))
            self.reason_table.setItem(0, 1, QTableWidgetItem("0"))
            self.reason_table.resizeColumnsToContents()
            return
        self.reason_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            reason_code = str(row.get("reason_code") or "")
            label_item = QTableWidgetItem(REASON_CODE_LABELS.get(reason_code, reason_code))
            count_item = QTableWidgetItem(str(row.get("count", 0)))
            self.reason_table.setItem(row_index, 0, label_item)
            self.reason_table.setItem(row_index, 1, count_item)
        self.reason_table.resizeColumnsToContents()

    def set_funnel_detail_candidates(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            self.funnel_detail_table.setRowCount(1)
            self.funnel_detail_table.setItem(0, 0, QTableWidgetItem("暂无明细"))
            for column in range(1, 9):
                self.funnel_detail_table.setItem(0, column, QTableWidgetItem(""))
            self.funnel_detail_table.resizeColumnsToContents()
            return

        self.funnel_detail_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            candidate_name = str(row.get("name") or f"#{row.get('candidate_id') or row.get('id')}")
            funnel_status = str(row.get("funnel_status") or row.get("recruitment_status") or "")
            current_status = str(row.get("recruitment_status") or "")
            role_text = str(
                row.get("job_track")
                or row.get("job_family")
                or row.get("role_title")
                or row.get("job_title")
                or ""
            )
            years = row.get("years_experience")
            years_text = "" if years is None or years == "" else str(years)
            values = [
                candidate_name,
                str(row.get("latest_rating") or ""),
                RECRUITMENT_STATUS_LABELS.get(funnel_status, funnel_status),
                REASON_CODE_LABELS.get(str(row.get("human_decision") or ""), str(row.get("human_decision") or "")),
                role_text,
                str(row.get("city") or ""),
                years_text,
                RECRUITMENT_STATUS_LABELS.get(current_status, current_status),
                str(row.get("reached_at") or row.get("match_updated_at") or row.get("screened_at") or ""),
            ]
            for column, value in enumerate(values):
                self.funnel_detail_table.setItem(row_index, column, QTableWidgetItem(value))
        self.funnel_detail_table.resizeColumnsToContents()

    def _emit_open_browser(self) -> None:
        self.open_browser_requested.emit(self.source_url_input.text().strip())

    def _emit_start_capture(self) -> None:
        self.start_capture_requested.emit(self.build_collect_options())

    @staticmethod
    def translate_status(status: str) -> str:
        return STATUS_LABELS.get(status, status)

    @staticmethod
    def _format_count_with_rate(count: int, total: int) -> str:
        if total <= 0:
            return str(count)
        return f"{count} ({count / total:.0%})"
