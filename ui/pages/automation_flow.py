from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


PROVIDER_DEFAULTS = {
    "openai": {
        "base": "https://api.openai.com/v1",
        "models": ["gpt-5.4-mini", "gpt-5.5", "gpt-5.4"],
        "key_env": "OPENAI_API_KEY",
    },
    "deepseek": {
        "base": "https://api.deepseek.com",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "key_env": "DEEPSEEK_API_KEY",
    },
    "custom": {
        "base": "",
        "models": [],
        "key_env": "AI_API_KEY",
    },
}

RATING_RANK = {"UR": 0, "SSR": 1, "SR": 2, "R": 3, "N": 4, "": 5}


class AutomationFlowPage(QWidget):
    save_requested = Signal(object)
    arm_requested = Signal(object)
    cancel_requested = Signal()
    stop_requested = Signal()
    test_connection_requested = Signal(object)
    run_selected = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._result_rows: list[dict[str, object]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        settings_group = QGroupBox("自动采集与 AI 初筛设置")
        settings_form = QFormLayout(settings_group)

        self.enabled_checkbox = QCheckBox("每次采集完成后，自动初筛刚采集的批次")
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("请选择筛选方案", None)
        self.job_title_input = QLineEdit()
        self.job_title_input.setPlaceholderText("本次采集岗位名称")
        self.source_url_input = QLineEdit()
        self.source_url_input.setPlaceholderText("Boss 或猎聘推荐人才页面")
        self.max_candidates_input = QSpinBox()
        self.max_candidates_input.setRange(0, 10000)
        self.max_candidates_input.setSpecialValueText("全部")

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("OpenAI", "openai")
        self.provider_combo.addItem("DeepSeek", "deepseek")
        self.provider_combo.addItem("自定义 OpenAI 兼容接口", "custom")
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.api_base_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("仅保存在当前程序内存，不写入配置文件")
        self.api_key_env_input = QLineEdit()

        settings_form.addRow(self.enabled_checkbox)
        settings_form.addRow("筛选方案", self.profile_combo)
        settings_form.addRow("采集岗位", self.job_title_input)
        settings_form.addRow("采集页面", self.source_url_input)
        settings_form.addRow("最多筛选人数", self.max_candidates_input)
        settings_form.addRow("AI 服务商", self.provider_combo)
        settings_form.addRow("模型", self.model_combo)
        settings_form.addRow("API Base", self.api_base_input)
        settings_form.addRow("API Key", self.api_key_input)
        settings_form.addRow("Key 环境变量", self.api_key_env_input)

        self.hint_label = QLabel(
            "先在这里选择岗位筛选方案并保存。实际启动统一在 Chrome 扩展中点击 AUTO；"
            "插件会自动滚动采集，卡片送回桌面端后立即对该批次进行 AI 初筛。"
        )
        self.hint_label.setWordWrap(True)
        settings_form.addRow(self.hint_label)

        action_row = QHBoxLayout()
        self.test_button = QPushButton("测试 AI 连接")
        self.save_button = QPushButton("保存设置")
        self.arm_button = QPushButton("保存并启用插件 AUTO")
        self.cancel_button = QPushButton("停用自动衔接")
        self.stop_button = QPushButton("停止 AI 初筛")
        self.stop_button.setEnabled(False)
        action_row.addStretch(1)
        action_row.addWidget(self.test_button)
        action_row.addWidget(self.save_button)
        action_row.addWidget(self.arm_button)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.stop_button)
        settings_form.addRow(action_row)

        result_group = QGroupBox("自动化筛选结果")
        result_layout = QVBoxLayout(result_group)
        result_head = QHBoxLayout()
        self.run_combo = QComboBox()
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("评级从高到低", "best")
        self.sort_combo.addItem("评级从低到高", "worst")
        self.sort_combo.addItem("候选人姓名", "name")
        self.summary_label = QLabel("尚无自动化结果")
        result_head.addWidget(QLabel("自动化批次"))
        result_head.addWidget(self.run_combo, 1)
        result_head.addWidget(QLabel("排序"))
        result_head.addWidget(self.sort_combo)
        result_head.addWidget(self.summary_label)
        result_layout.addLayout(result_head)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status_label = QLabel("未启用")
        self.status_label.setWordWrap(True)
        result_layout.addWidget(self.progress)
        result_layout.addWidget(self.status_label)

        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["候选人", "评级", "一句话人物画像", "状态"])
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        result_layout.addWidget(self.result_table, 1)

        root.addWidget(settings_group)
        root.addWidget(result_group, 1)

        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.test_button.clicked.connect(
            lambda: self.test_connection_requested.emit(self.provider_payload())
        )
        self.save_button.clicked.connect(lambda: self.save_requested.emit(self.workflow_payload()))
        self.arm_button.clicked.connect(self._emit_arm)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.run_combo.currentIndexChanged.connect(self._emit_run_selected)
        self.sort_combo.currentIndexChanged.connect(self._render_results)
        self._provider_changed()

    def load_config(self, config) -> None:
        flow = config.automation_flow
        self.enabled_checkbox.setChecked(bool(flow.enabled))
        self.job_title_input.setText(flow.job_title or config.default_job_title)
        self.source_url_input.setText(flow.source_url or config.target_url)
        self.max_candidates_input.setValue(int(flow.max_candidates))
        provider_index = self.provider_combo.findData(flow.provider)
        self.provider_combo.setCurrentIndex(max(0, provider_index))
        self._provider_changed()
        if flow.model:
            self.model_combo.setCurrentText(flow.model)
        if flow.api_base:
            self.api_base_input.setText(flow.api_base)
        if flow.api_key_env:
            self.api_key_env_input.setText(flow.api_key_env)
        profile_index = self.profile_combo.findData(flow.profile_id)
        if profile_index >= 0:
            self.profile_combo.setCurrentIndex(profile_index)
        self.status_label.setText("已启用，等待下一次采集" if flow.enabled else "未启用")

    def set_profiles(self, rows: list[dict[str, object]], selected_profile_id: int | None = None) -> None:
        current = selected_profile_id
        if current is None:
            current = self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("请选择筛选方案", None)
        for row in rows:
            self.profile_combo.addItem(str(row.get("job_title") or "未命名岗位"), int(row["id"]))
        index = self.profile_combo.findData(current)
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)

    def set_runs(self, rows: list[dict[str, object]], selected_run_id: int | None = None) -> None:
        current = selected_run_id or self.run_combo.currentData()
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        for row in rows:
            label = (
                f"#{row['id']} | 批次 {row.get('batch_id') or '-'} | "
                f"{row['profile_job_title']} | {row['completed_candidates']}/{row['total_candidates']}"
            )
            self.run_combo.addItem(label, int(row["id"]))
        index = self.run_combo.findData(current)
        self.run_combo.setCurrentIndex(max(0, index))
        self.run_combo.blockSignals(False)

    def show_results(self, rows: list[dict[str, object]]) -> None:
        self._result_rows = [dict(row) for row in rows]
        self._render_results()

    def workflow_payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled_checkbox.isChecked(),
            "profile_id": self.profile_combo.currentData(),
            "job_title": self.job_title_input.text().strip(),
            "source_url": self.source_url_input.text().strip(),
            "limit": self.max_candidates_input.value(),
            "provider": self.provider_payload(),
        }

    def provider_payload(self) -> dict[str, object]:
        return {
            "provider": str(self.provider_combo.currentData() or "openai"),
            "model": self.model_combo.currentText().strip(),
            "api_base": self.api_base_input.text().strip(),
            "api_key": self.api_key_input.text().strip(),
            "api_key_env": self.api_key_env_input.text().strip(),
        }

    def set_waiting(self, waiting: bool) -> None:
        self.arm_button.setEnabled(not waiting)
        if waiting:
            self.status_label.setText("已启用。请在招聘页面打开 Chrome 扩展并点击 AUTO。")

    def set_running(self, running: bool, total: int = 0) -> None:
        self.arm_button.setEnabled(not running)
        self.test_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.progress.setRange(0, max(total, 1))
        if running:
            self.progress.setValue(0)

    def update_progress(self, progress) -> None:
        self.progress.setRange(0, max(int(progress.total), 1))
        self.progress.setValue(int(progress.current))
        self.status_label.setText(
            f"AI 初筛 {progress.current}/{progress.total} | 完成 {progress.completed} | "
            f"失败 {progress.failed} | {progress.message}"
        )

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _emit_arm(self) -> None:
        payload = self.workflow_payload()
        if payload["profile_id"] is None:
            self.set_status("请先选择筛选方案。")
            return
        if not payload["source_url"]:
            self.set_status("请填写采集页面。")
            return
        provider = dict(payload["provider"])
        if not provider.get("model"):
            self.set_status("请填写 AI 模型名称。")
            return
        self.enabled_checkbox.setChecked(True)
        payload["enabled"] = True
        self.arm_requested.emit(payload)

    def _profile_changed(self) -> None:
        if self.profile_combo.currentData() is None:
            return
        self.job_title_input.setText(self.profile_combo.currentText())

    def _provider_changed(self) -> None:
        provider = str(self.provider_combo.currentData() or "openai")
        defaults = PROVIDER_DEFAULTS[provider]
        current_model = self.model_combo.currentText().strip()
        self.model_combo.clear()
        self.model_combo.addItems(defaults["models"])
        if current_model and provider == "custom":
            self.model_combo.setCurrentText(current_model)
        self.api_base_input.setText(defaults["base"])
        self.api_key_env_input.setText(defaults["key_env"])

    def _emit_run_selected(self) -> None:
        run_id = self.run_combo.currentData()
        if run_id is not None:
            self.run_selected.emit(int(run_id))

    def _render_results(self) -> None:
        mode = str(self.sort_combo.currentData() or "best")
        if mode == "name":
            rows = sorted(self._result_rows, key=lambda row: str(row.get("name") or "").lower())
        elif mode == "worst":
            rows = sorted(
                self._result_rows,
                key=lambda row: (
                    -RATING_RANK.get(str(row.get("rating") or ""), -99)
                    if row.get("rating")
                    else 99,
                    str(row.get("name") or "").lower(),
                ),
            )
        else:
            rows = sorted(
                self._result_rows,
                key=lambda row: (
                    RATING_RANK.get(str(row.get("rating") or ""), 5),
                    str(row.get("name") or "").lower(),
                ),
            )

        self.result_table.setRowCount(len(rows))
        counts = {rating: 0 for rating in ["UR", "SSR", "SR", "R", "N"]}
        failures = 0
        for row_index, row in enumerate(rows):
            rating = str(row.get("rating") or "")
            if rating in counts:
                counts[rating] += 1
            if row.get("status") == "failed":
                failures += 1
            values = [
                row.get("name") or f"候选人 #{row.get('candidate_id')}",
                rating or "-",
                row.get("persona") or row.get("error") or "-",
                "完成" if row.get("status") == "completed" else "失败",
            ]
            for column, value in enumerate(values):
                self.result_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        self.result_table.resizeColumnsToContents()
        self.result_table.setColumnWidth(2, 680)
        summary = " / ".join(f"{rating}:{count}" for rating, count in counts.items())
        self.summary_label.setText(f"{summary} / 失败:{failures}")
