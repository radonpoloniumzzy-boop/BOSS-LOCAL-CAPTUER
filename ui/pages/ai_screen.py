from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ai.prompt_manager import PromptManager


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


class AIScreenPage(QWidget):
    profile_selected = Signal(int)
    save_profile_requested = Signal(object)
    delete_profile_requested = Signal(int)
    run_requested = Signal(object)
    stop_requested = Signal()
    test_connection_requested = Signal(object)
    run_selected = Signal(int)

    def __init__(self, prompt_manager: PromptManager) -> None:
        super().__init__()
        self.prompt_manager = prompt_manager
        self.current_profile_id: int | None = None
        self.prompt_source = "generated"
        self._setting_prompt = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Vertical)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(10)

        profile_group = QGroupBox("岗位筛选方案")
        profile_layout = QVBoxLayout(profile_group)
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.new_profile_button = QPushButton("新建")
        self.save_profile_button = QPushButton("保存方案")
        self.delete_profile_button = QPushButton("删除")
        profile_row.addWidget(QLabel("方案"))
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(self.new_profile_button)
        profile_row.addWidget(self.save_profile_button)
        profile_row.addWidget(self.delete_profile_button)
        profile_layout.addLayout(profile_row)

        self.job_title_input = QLineEdit()
        self.job_title_input.setPlaceholderText("例如：私募基金市场销售")
        profile_layout.addWidget(QLabel("筛选岗位名称"))
        profile_layout.addWidget(self.job_title_input)

        text_splitter = QSplitter(Qt.Horizontal)
        jd_group = QGroupBox("岗位 JD（必填）")
        jd_layout = QVBoxLayout(jd_group)
        self.jd_text = QPlainTextEdit()
        self.jd_text.setPlaceholderText("粘贴 JD，或上传 TXT / Markdown / DOCX / PDF 文件。")
        self.upload_jd_button = QPushButton("上传 JD")
        jd_layout.addWidget(self.jd_text, 1)
        jd_layout.addWidget(self.upload_jd_button)

        prompt_group = QGroupBox("筛选 Prompt（可选，可编辑）")
        prompt_layout = QVBoxLayout(prompt_group)
        self.prompt_text = QPlainTextEdit()
        self.prompt_text.setPlaceholderText("留空时会根据 JD 生成默认筛选协议；也可以上传自定义 Prompt。")
        prompt_actions = QHBoxLayout()
        self.generate_prompt_button = QPushButton("根据 JD 生成")
        self.upload_prompt_button = QPushButton("上传 Prompt")
        prompt_actions.addWidget(self.generate_prompt_button)
        prompt_actions.addWidget(self.upload_prompt_button)
        prompt_layout.addWidget(self.prompt_text, 1)
        prompt_layout.addLayout(prompt_actions)
        text_splitter.addWidget(jd_group)
        text_splitter.addWidget(prompt_group)
        text_splitter.setSizes([520, 620])
        profile_layout.addWidget(text_splitter, 1)

        self.compliance_label = QLabel(
            "AI 评级仅用于人工复核排序；禁止按年龄、性别、婚育、健康、照片、外貌或形象气质筛选。"
        )
        self.compliance_label.setWordWrap(True)
        self.compliance_label.setStyleSheet("color: #a33; font-weight: 600;")
        profile_layout.addWidget(self.compliance_label)
        editor_layout.addWidget(profile_group, 3)

        run_group = QGroupBox("候选人范围与模型")
        run_form = QFormLayout(run_group)
        source_row = QHBoxLayout()
        self.source_job_combo = QComboBox()
        self.source_job_combo.addItem("全部采集岗位", "")
        self.source_batch_combo = QComboBox()
        self.source_batch_combo.addItem("全部批次", None)
        source_row.addWidget(self.source_job_combo, 1)
        source_row.addWidget(self.source_batch_combo, 1)
        source_wrapper = QWidget()
        source_wrapper.setLayout(source_row)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("OpenAI", "openai")
        self.provider_combo.addItem("DeepSeek", "deepseek")
        self.provider_combo.addItem("自定义 OpenAI 兼容接口", "custom")
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.api_base_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("仅保存在当前程序内存，不写入数据库或配置文件")
        self.api_key_env_input = QLineEdit()
        self.max_candidates_input = QSpinBox()
        self.max_candidates_input.setRange(0, 10000)
        self.max_candidates_input.setSpecialValueText("全部")
        self.max_candidates_input.setValue(0)

        run_form.addRow("候选人来源", source_wrapper)
        run_form.addRow("最多筛选人数", self.max_candidates_input)
        run_form.addRow("AI 服务商", self.provider_combo)
        run_form.addRow("模型", self.model_combo)
        run_form.addRow("API Base", self.api_base_input)
        run_form.addRow("API Key", self.api_key_input)
        run_form.addRow("Key 环境变量", self.api_key_env_input)

        action_row = QHBoxLayout()
        self.test_button = QPushButton("测试连接")
        self.start_button = QPushButton("开始 AI 初筛")
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        action_row.addStretch(1)
        action_row.addWidget(self.test_button)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        run_form.addRow(action_row)
        editor_layout.addWidget(run_group, 2)

        result_group = QGroupBox("评级结果")
        result_layout = QVBoxLayout(result_group)
        result_head = QHBoxLayout()
        self.run_combo = QComboBox()
        self.summary_label = QLabel("尚未运行")
        result_head.addWidget(QLabel("筛选批次"))
        result_head.addWidget(self.run_combo, 1)
        result_head.addWidget(self.summary_label)
        result_layout.addLayout(result_head)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status_label = QLabel("就绪")
        result_layout.addWidget(self.progress)
        result_layout.addWidget(self.status_label)

        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["候选人", "评级", "一句话人物画像", "状态"])
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        result_layout.addWidget(self.result_table, 1)

        splitter.addWidget(editor)
        splitter.addWidget(result_group)
        splitter.setSizes([560, 300])
        root.addWidget(splitter, 1)

        self.profile_combo.currentIndexChanged.connect(self._emit_profile_selected)
        self.new_profile_button.clicked.connect(self.clear_profile)
        self.save_profile_button.clicked.connect(self._emit_save_profile)
        self.delete_profile_button.clicked.connect(self._emit_delete_profile)
        self.upload_jd_button.clicked.connect(self._upload_jd)
        self.upload_prompt_button.clicked.connect(self._upload_prompt)
        self.generate_prompt_button.clicked.connect(self.generate_prompt)
        self.prompt_text.textChanged.connect(self._mark_prompt_custom)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.test_button.clicked.connect(lambda: self.test_connection_requested.emit(self.provider_payload()))
        self.start_button.clicked.connect(self._emit_run)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.run_combo.currentIndexChanged.connect(self._emit_run_selected)
        self._provider_changed()

    def load_config(self, config) -> None:
        provider = str(config.ai_provider.provider or "openai")
        index = self.provider_combo.findData(provider)
        self.provider_combo.setCurrentIndex(max(0, index))
        self._provider_changed()
        if config.ai_provider.model:
            self.model_combo.setCurrentText(config.ai_provider.model)
        if config.ai_provider.api_base:
            self.api_base_input.setText(config.ai_provider.api_base)
        self.api_key_env_input.setText(config.ai_provider.api_key_env)

    def set_profiles(self, rows: list[dict[str, object]]) -> None:
        current_id = self.current_profile_id
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("新建筛选方案", None)
        for row in rows:
            self.profile_combo.addItem(str(row.get("job_title") or "未命名岗位"), int(row["id"]))
        index = self.profile_combo.findData(current_id)
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)

    def show_profile(self, row: dict[str, object] | None) -> None:
        if not row:
            self.clear_profile()
            return
        self.current_profile_id = int(row["id"])
        job_title = str(row.get("job_title") or "")
        self.job_title_input.setText(job_title)
        self.jd_text.setPlainText(str(row.get("jd_text") or ""))
        self.prompt_source = str(row.get("prompt_source") or "generated")
        self._setting_prompt = True
        self.prompt_text.setPlainText(str(row.get("prompt_text") or ""))
        self._setting_prompt = False
        source_index = self.source_job_combo.findData(job_title)
        if source_index >= 0:
            self.source_job_combo.setCurrentIndex(source_index)

    def clear_profile(self) -> None:
        self.current_profile_id = None
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)
        self.job_title_input.clear()
        self.jd_text.clear()
        self._setting_prompt = True
        self.prompt_text.clear()
        self._setting_prompt = False
        self.prompt_source = "generated"

    def set_source_options(self, job_titles: list[str], batches: list[dict[str, object]]) -> None:
        current_job = self.source_job_combo.currentData()
        self.source_job_combo.clear()
        self.source_job_combo.addItem("全部采集岗位", "")
        for job_title in job_titles:
            self.source_job_combo.addItem(job_title, job_title)
        self.source_job_combo.setCurrentIndex(max(0, self.source_job_combo.findData(current_job)))

        current_batch = self.source_batch_combo.currentData()
        self.source_batch_combo.clear()
        self.source_batch_combo.addItem("全部批次", None)
        for batch in batches:
            self.source_batch_combo.addItem(
                f"#{batch['id']} | {batch['job_title']} | {batch['total_collected']}人",
                int(batch["id"]),
            )
        self.source_batch_combo.setCurrentIndex(max(0, self.source_batch_combo.findData(current_batch)))

    def set_runs(self, rows: list[dict[str, object]], selected_run_id: int | None = None) -> None:
        current = selected_run_id or self.run_combo.currentData()
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        for row in rows:
            label = (
                f"#{row['id']} | {row['profile_job_title']} | {row['model']} | "
                f"{row['completed_candidates']}/{row['total_candidates']}"
            )
            self.run_combo.addItem(label, int(row["id"]))
        index = self.run_combo.findData(current)
        self.run_combo.setCurrentIndex(max(0, index))
        self.run_combo.blockSignals(False)

    def show_results(self, rows: list[dict[str, object]]) -> None:
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
        summary = " / ".join(f"{key}:{value}" for key, value in counts.items())
        self.summary_label.setText(f"{summary} / 失败:{failures}")

    def set_running(self, running: bool, total: int = 0) -> None:
        self.start_button.setEnabled(not running)
        self.test_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.progress.setRange(0, max(total, 1))
        if running:
            self.progress.setValue(0)

    def update_progress(self, progress) -> None:
        self.progress.setRange(0, max(int(progress.total), 1))
        self.progress.setValue(int(progress.current))
        self.status_label.setText(
            f"{progress.current}/{progress.total} | 完成 {progress.completed} | 失败 {progress.failed} | {progress.message}"
        )

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def profile_payload(self) -> dict[str, object]:
        return {
            "id": self.current_profile_id,
            "job_title": self.job_title_input.text().strip(),
            "jd_text": self.jd_text.toPlainText().strip(),
            "prompt_text": self.prompt_text.toPlainText().strip(),
            "prompt_source": self.prompt_source,
        }

    def provider_payload(self) -> dict[str, object]:
        return {
            "provider": str(self.provider_combo.currentData() or "openai"),
            "model": self.model_combo.currentText().strip(),
            "api_base": self.api_base_input.text().strip(),
            "api_key": self.api_key_input.text().strip(),
            "api_key_env": self.api_key_env_input.text().strip(),
        }

    def run_payload(self) -> dict[str, object]:
        return {
            "profile": self.profile_payload(),
            "provider": self.provider_payload(),
            "source_job_title": str(self.source_job_combo.currentData() or ""),
            "batch_id": self.source_batch_combo.currentData(),
            "limit": self.max_candidates_input.value(),
        }

    def generate_prompt(self) -> None:
        try:
            prompt = self.prompt_manager.build_from_jd(
                self.job_title_input.text().strip(),
                self.jd_text.toPlainText(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "无法生成 Prompt", str(exc))
            return
        self.prompt_source = "generated"
        self._setting_prompt = True
        self.prompt_text.setPlainText(prompt)
        self._setting_prompt = False

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

    def _upload_text(self, target: QPlainTextEdit, label: str) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"上传 {label}",
            str(Path.home()),
            "支持的文档 (*.txt *.md *.markdown *.docx *.pdf);;所有文件 (*)",
        )
        if not path:
            return False
        try:
            target.setPlainText(self.prompt_manager.read_uploaded_text(Path(path)))
            return True
        except Exception as exc:
            QMessageBox.critical(self, f"读取 {label} 失败", str(exc))
            return False

    def _upload_jd(self) -> None:
        if self._upload_text(self.jd_text, "JD"):
            self.generate_prompt()

    def _upload_prompt(self) -> None:
        if self._upload_text(self.prompt_text, "Prompt"):
            self.prompt_source = "custom"

    def _mark_prompt_custom(self) -> None:
        if not self._setting_prompt:
            self.prompt_source = "custom"

    def _emit_profile_selected(self) -> None:
        profile_id = self.profile_combo.currentData()
        if profile_id is not None:
            self.profile_selected.emit(int(profile_id))

    def _emit_save_profile(self) -> None:
        payload = self.profile_payload()
        if not payload["job_title"] or not payload["jd_text"]:
            QMessageBox.warning(self, "缺少岗位信息", "岗位名称和 JD 均为必填项。")
            return
        self.save_profile_requested.emit(payload)

    def _emit_delete_profile(self) -> None:
        if self.current_profile_id is None:
            return
        if QMessageBox.question(self, "删除筛选方案", "确认删除当前岗位筛选方案及其历史结果吗？") == QMessageBox.Yes:
            self.delete_profile_requested.emit(self.current_profile_id)

    def _emit_run(self) -> None:
        payload = self.run_payload()
        profile = payload["profile"]
        provider = payload["provider"]
        if not profile["job_title"] or not profile["jd_text"]:
            QMessageBox.warning(self, "缺少岗位信息", "开始筛选前必须填写岗位名称并上传或粘贴 JD。")
            return
        if not provider["model"]:
            QMessageBox.warning(self, "缺少模型", "请填写模型名称。")
            return
        self.run_requested.emit(payload)

    def _emit_run_selected(self) -> None:
        run_id = self.run_combo.currentData()
        if run_id is not None:
            self.run_selected.emit(int(run_id))
