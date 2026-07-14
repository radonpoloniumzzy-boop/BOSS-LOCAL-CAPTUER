from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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
    clone_profile_requested = Signal(int, str)
    delete_profile_requested = Signal(int)
    run_requested = Signal(object)
    stop_requested = Signal()
    test_connection_requested = Signal(object)
    cancel_connection_test_requested = Signal()
    delete_credential_requested = Signal(object)
    run_selected = Signal(int)
    resume_run_requested = Signal(int)
    retry_task_requested = Signal(int)

    def __init__(self, prompt_manager: PromptManager) -> None:
        super().__init__()
        self.prompt_manager = prompt_manager
        self.current_profile_id: int | None = None
        self.prompt_source = "generated"
        self._setting_prompt = False
        self._result_rows: list[dict[str, object]] = []
        self._result_page = 1
        self._result_page_size = 100
        self._result_total = 0
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
        self.clone_profile_button = QPushButton("复制")
        profile_row.addWidget(self.new_profile_button)
        profile_row.addWidget(self.save_profile_button)
        profile_row.addWidget(self.clone_profile_button)
        profile_row.addWidget(self.delete_profile_button)
        profile_layout.addLayout(profile_row)

        self.job_title_input = QLineEdit()
        self.job_title_input.setPlaceholderText("例如：私募基金市场销售")
        profile_layout.addWidget(QLabel("筛选岗位名称"))
        profile_layout.addWidget(self.job_title_input)
        self.must_have_input = QLineEdit()
        self.nice_to_have_input = QLineEdit()
        self.risk_flags_input = QLineEdit()
        self.exclusions_input = QLineEdit()
        self.interview_checks_input = QLineEdit()
        self.evidence_policy_input = QLineEdit()
        self.evidence_policy_input.setPlaceholderText('{"explicit_evidence_required":true}')
        for label, widget in [
            ("必须项（用分号分隔）", self.must_have_input),
            ("加分项（用分号分隔）", self.nice_to_have_input),
            ("风险项（用分号分隔）", self.risk_flags_input),
            ("排除项（用分号分隔）", self.exclusions_input),
            ("面试核验项（用分号分隔）", self.interview_checks_input),
            ("证据策略 JSON", self.evidence_policy_input),
        ]:
            profile_layout.addWidget(QLabel(label))
            profile_layout.addWidget(widget)

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
        self.start_button.setProperty("primary", True)
        self.stop_button = QPushButton("停止")
        self.cancel_test_button = QPushButton("取消测试")
        self.delete_credential_button = QPushButton("删除已保存密钥")
        self.stop_button.setEnabled(False)
        action_row.addStretch(1)
        action_row.addWidget(self.test_button)
        action_row.addWidget(self.cancel_test_button)
        action_row.addWidget(self.delete_credential_button)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        run_form.addRow(action_row)
        editor_layout.addWidget(run_group, 2)

        result_group = QGroupBox("评级结果")
        result_layout = QVBoxLayout(result_group)
        result_head = QHBoxLayout()
        self.run_combo = QComboBox()
        self.result_status_filter_combo = QComboBox()
        self.result_status_filter_combo.addItem("全部状态", "")
        for label, status in [
            ("待处理", "pending"),
            ("处理中", "running"),
            ("等待重试", "retrying"),
            ("失败", "failed"),
            ("人工确认", "manual_check"),
            ("暂缓", "hold"),
            ("完成", "success"),
        ]:
            self.result_status_filter_combo.addItem(label, status)
        self.resume_run_button = QPushButton("继续/重试")
        self.retry_task_button = QPushButton("重试所选失败")
        self.summary_label = QLabel("尚未运行")
        result_head.addWidget(QLabel("筛选批次"))
        result_head.addWidget(self.run_combo, 1)
        result_head.addWidget(QLabel("状态"))
        result_head.addWidget(self.result_status_filter_combo)
        result_head.addWidget(self.resume_run_button)
        result_head.addWidget(self.retry_task_button)
        result_head.addWidget(self.summary_label)
        self.previous_result_page_button = QPushButton("上一页")
        self.next_result_page_button = QPushButton("下一页")
        self.result_page_label = QLabel("第 1 页 / 共 0 条")
        result_head.addWidget(self.previous_result_page_button)
        result_head.addWidget(self.result_page_label)
        result_head.addWidget(self.next_result_page_button)
        result_layout.addLayout(result_head)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.efficiency_label = QLabel("效率摘要：暂无")
        self.efficiency_label.setWordWrap(True)
        self.status_label = QLabel("就绪")
        result_layout.addWidget(self.progress)
        result_layout.addWidget(self.status_label)
        result_layout.addWidget(self.efficiency_label)

        self.result_table = QTableWidget(0, 6)
        self.result_table.setHorizontalHeaderLabels(
            ["候选人", "评级", "状态", "重试", "最后更新", "依据/失败原因"]
        )
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setSelectionMode(QTableWidget.SingleSelection)
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
        self.clone_profile_button.clicked.connect(self._emit_clone_profile)
        self.delete_profile_button.clicked.connect(self._emit_delete_profile)
        self.upload_jd_button.clicked.connect(self._upload_jd)
        self.upload_prompt_button.clicked.connect(self._upload_prompt)
        self.generate_prompt_button.clicked.connect(self.generate_prompt)
        self.prompt_text.textChanged.connect(self._mark_prompt_custom)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.test_button.clicked.connect(lambda: self.test_connection_requested.emit(self.provider_payload()))
        self.cancel_test_button.clicked.connect(self.cancel_connection_test_requested.emit)
        self.delete_credential_button.clicked.connect(
            lambda: self.delete_credential_requested.emit(self.provider_payload())
        )
        self.start_button.clicked.connect(self._emit_run)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.run_combo.currentIndexChanged.connect(self._emit_run_selected)
        self.result_status_filter_combo.currentIndexChanged.connect(self._render_filtered_results)
        self.resume_run_button.clicked.connect(self._emit_resume_run)
        self.retry_task_button.clicked.connect(self._emit_retry_task)
        self.previous_result_page_button.clicked.connect(
            lambda: self._request_result_page(self._result_page - 1)
        )
        self.next_result_page_button.clicked.connect(
            lambda: self._request_result_page(self._result_page + 1)
        )
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
        self.must_have_input.setText("；".join(row.get("must_have") or []))
        self.nice_to_have_input.setText("；".join(row.get("nice_to_have") or []))
        self.risk_flags_input.setText("；".join(row.get("risk_flags") or []))
        self.exclusions_input.setText("；".join(row.get("exclusions") or []))
        self.interview_checks_input.setText("；".join(row.get("interview_checks") or []))
        self.evidence_policy_input.setText(
            json.dumps(row.get("evidence_policy") or {}, ensure_ascii=False, sort_keys=True)
        )
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
        for widget in [
            self.must_have_input,
            self.nice_to_have_input,
            self.risk_flags_input,
            self.exclusions_input,
            self.interview_checks_input,
            self.evidence_policy_input,
        ]:
            widget.clear()

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
        self._result_rows = [dict(row) for row in rows]
        self._render_filtered_results()

    def set_result_page(
        self,
        rows: list[dict[str, object]],
        *,
        total: int,
        page: int,
        page_size: int,
    ) -> None:
        self._result_total = max(0, int(total))
        self._result_page = max(1, int(page))
        self._result_page_size = max(1, int(page_size))
        page_count = max(1, (self._result_total + self._result_page_size - 1) // self._result_page_size)
        self.result_page_label.setText(
            f"第 {self._result_page} / {page_count} 页，共 {self._result_total} 条"
        )
        self.previous_result_page_button.setEnabled(self._result_page > 1)
        self.next_result_page_button.setEnabled(self._result_page < page_count)
        self.show_results(rows)

    def result_page(self) -> int:
        return self._result_page

    def result_page_size(self) -> int:
        return self._result_page_size

    def _request_result_page(self, page: int) -> None:
        self._result_page = max(1, int(page))
        run_id = self.run_combo.currentData()
        if run_id is not None:
            self.run_selected.emit(int(run_id))

    def _render_filtered_results(self, *_args: object) -> None:
        status_filter = str(self.result_status_filter_combo.currentData() or "")
        rows = [
            row
            for row in self._result_rows
            if not status_filter or self._task_status(row) == status_filter
        ]
        self.result_table.setRowCount(len(rows))
        counts = {rating: 0 for rating in ["UR", "SSR", "SR", "R", "N"]}
        task_counts = {
            "pending": 0,
            "running": 0,
            "retrying": 0,
            "success": 0,
            "failed": 0,
            "manual_check": 0,
            "hold": 0,
        }
        for row in self._result_rows:
            rating = str(row.get("rating") or "")
            if rating in counts:
                counts[rating] += 1
            task_status = self._task_status(row)
            if task_status in task_counts:
                task_counts[task_status] += 1
        for row_index, row in enumerate(rows):
            rating = str(row.get("rating") or "")
            task_status = self._task_status(row)
            values = [
                row.get("name") or f"候选人 #{row.get('candidate_id')}",
                rating or "-",
                self._display_task_status(task_status, row),
                self._retry_summary(row),
                self._task_last_time(row),
                self._result_detail(row),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0 and row.get("task_id") is not None:
                    item.setData(Qt.UserRole, int(row["task_id"]))
                self.result_table.setItem(row_index, column, item)
        self.result_table.setColumnWidth(4, 180)
        self.result_table.setColumnWidth(5, 720)
        rating_summary = " / ".join(f"{key}:{value}" for key, value in counts.items())
        task_summary = " / ".join(
            f"{key}:{value}"
            for key, value in task_counts.items()
            if value or key in {"pending", "running", "retrying", "failed"}
        )
        visible_summary = ""
        if status_filter:
            visible_summary = f" / 显示 {len(rows)}/{len(self._result_rows)}"
        self.summary_label.setText(f"{rating_summary} / {task_summary}{visible_summary}")

    def show_efficiency_summary(self, summary: dict[str, int]) -> None:
        total = int(summary.get("total", 0))
        if total <= 0:
            self.efficiency_label.setText("效率摘要：暂无")
            return
        avoided = int(summary.get("avoided_by_rules", 0))
        recovered = int(summary.get("recovered_results", 0))
        legacy = int(summary.get("legacy_results", 0))
        unknown = int(summary.get("unknown_successes", 0))
        parts = [
            f"总任务 {total}",
            f"进 AI {summary.get('ai_routed', 0)}",
            f"规则节省 {avoided} ({self._percent(avoided, total)})",
            f"人工确认 {summary.get('manual_check', 0)}",
            f"暂缓 {summary.get('hold', 0)}",
            f"模型调用 {summary.get('model_calls', 0)}",
            f"缓存复用 {summary.get('cached_reuses', 0)}",
        ]
        if recovered:
            parts.append(f"恢复已有 {recovered}")
        if legacy:
            parts.append(f"旧数据 {legacy}")
        if unknown:
            parts.append(f"来源未知 {unknown}")
        parts.extend(
            [
                f"失败 {summary.get('failed', 0)}",
                f"待处理 {summary.get('unfinished', 0)}",
                f"重试 {summary.get('retry_attempts', 0)}",
            ]
        )
        self.efficiency_label.setText("效率摘要：" + " / ".join(parts))

    @staticmethod
    def _result_detail(row: dict[str, object]) -> str:
        persona = row.get("persona") or row.get("error") or row.get("task_error") or row.get("route_reason")
        parts = [str(persona)] if persona else []
        confidence = str(row.get("confidence") or "")
        if confidence:
            parts.append(f"confidence={confidence}")
        action = str(row.get("recommended_action") or "")
        if action:
            parts.append(f"action={action}")
        failure_category = str(row.get("failure_category") or "")
        if failure_category:
            parts.append(f"failure={failure_category}")
        next_attempt_at = str(row.get("next_attempt_at") or "")
        if next_attempt_at:
            parts.append(f"next_retry={next_attempt_at}")
        locked_by = str(row.get("locked_by") or "")
        if locked_by and AIScreenPage._task_status(row) == "running":
            parts.append(f"worker={locked_by}")
        route_summary = AIScreenPage._route_detail(row)
        if route_summary:
            parts.append(route_summary)
        return " | ".join(parts) if parts else "-"

    @staticmethod
    def _task_status(row: dict[str, object]) -> str:
        task_status = str(row.get("task_status") or row.get("status") or "")
        result_status = str(row.get("result_status") or row.get("status") or "")
        if not task_status and result_status == "failed":
            return "failed"
        return task_status

    @staticmethod
    def _retry_summary(row: dict[str, object]) -> str:
        retry_count = row.get("retry_count")
        max_retry_count = row.get("max_retry_count")
        if retry_count is None and max_retry_count is None:
            return "-"
        return f"{retry_count if retry_count is not None else 0}/{max_retry_count if max_retry_count is not None else 0}"

    @staticmethod
    def _task_last_time(row: dict[str, object]) -> str:
        for key in [
            "task_updated_at",
            "task_finished_at",
            "task_started_at",
            "result_created_at",
            "task_created_at",
        ]:
            value = row.get(key)
            if value:
                return str(value)
        return "-"

    @staticmethod
    def _route_detail(row: dict[str, object]) -> str:
        reason = str(row.get("route_reason") or "")
        details_text = str(row.get("route_details_json") or "")
        if not reason and not details_text:
            return ""
        labels = {
            "no_meaningful_candidate_text": "资料过少",
            "insufficient_candidate_evidence": "证据不足",
            "missing_role_city": "缺少岗位城市信息",
            "role_city_mismatch": "城市不匹配",
            "missing_role_years": "缺少年限信息",
            "role_years_below_minimum": "年限低于要求",
            "missing_role_keywords": "岗位关键词缺失",
            "sufficient_candidate_evidence": "资料足够",
            "matched_securities_trading_evidence": "证券交易证据匹配",
            "generic_transaction_without_market_context": "泛交易描述，缺少证券市场证据",
        }
        parts = [f"rule={labels.get(reason, reason)}"] if reason else []
        try:
            details = json.loads(details_text) if details_text else {}
        except json.JSONDecodeError:
            details = {}
        if isinstance(details, dict):
            role = details.get("role_requirements")
            if isinstance(role, dict):
                min_years = role.get("min_years")
                cities = role.get("city_terms") or []
                required = role.get("required_terms") or []
                if min_years is not None:
                    parts.append(f"role_min_years={min_years}")
                if cities:
                    parts.append("role_city=" + ",".join(str(item) for item in cities))
                if required:
                    parts.append("role_keywords=" + ",".join(str(item) for item in required))
            if details.get("candidate_years") is not None:
                parts.append(f"candidate_years={details.get('candidate_years')}")
            candidate_cities = details.get("candidate_cities") or []
            if candidate_cities:
                parts.append("candidate_city=" + ",".join(str(item) for item in candidate_cities))
            missing = details.get("missing_required_terms") or []
            if missing:
                parts.append("missing=" + ",".join(str(item) for item in missing))
            evidence_policy = details.get("evidence_policy")
            if evidence_policy:
                parts.append(f"policy={evidence_policy}")
            evidence_fields = (
                ("matched_direct_evidence", "direct"),
                ("matched_market_terms", "market"),
                ("matched_action_terms", "action"),
                ("matched_exclusion_terms", "exclusion"),
            )
            for field, label in evidence_fields:
                matches = details.get(field) or []
                if matches:
                    parts.append(f"{label}=" + ",".join(str(item) for item in matches))
        return " / ".join(parts)

    @staticmethod
    def _display_task_status(status: str, row: dict[str, object]) -> str:
        labels = {
            "pending": "待处理",
            "running": "处理中",
            "retrying": "等待重试",
            "success": "完成",
            "failed": "失败",
            "manual_check": "人工确认",
            "hold": "暂缓",
            "completed": "完成",
        }
        label = labels.get(status, status or "-")
        if status in {"retrying", "failed"}:
            retry_count = row.get("retry_count")
            max_retry_count = row.get("max_retry_count")
            if retry_count is not None and max_retry_count is not None:
                label = f"{label} ({retry_count}/{max_retry_count})"
        return label

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
        def items(widget: QLineEdit) -> list[str]:
            text = widget.text().replace(";", "；")
            return [value.strip() for value in text.split("；") if value.strip()]

        try:
            evidence_policy = json.loads(self.evidence_policy_input.text().strip() or "{}")
        except json.JSONDecodeError:
            evidence_policy = {"_invalid": self.evidence_policy_input.text().strip()}
        return {
            "id": self.current_profile_id,
            "job_title": self.job_title_input.text().strip(),
            "jd_text": self.jd_text.toPlainText().strip(),
            "prompt_text": self.prompt_text.toPlainText().strip(),
            "prompt_source": self.prompt_source,
            "must_have": items(self.must_have_input),
            "nice_to_have": items(self.nice_to_have_input),
            "risk_flags": items(self.risk_flags_input),
            "exclusions": items(self.exclusions_input),
            "interview_checks": items(self.interview_checks_input),
            "evidence_policy": evidence_policy,
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

    def _emit_clone_profile(self) -> None:
        if self.current_profile_id is None:
            return
        title, accepted = QInputDialog.getText(
            self,
            "复制筛选方案",
            "新方案名称",
            text=f"{self.job_title_input.text().strip()} - 副本",
        )
        if accepted and title.strip():
            self.clone_profile_requested.emit(self.current_profile_id, title.strip())

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
        self._result_page = 1
        run_id = self.run_combo.currentData()
        if run_id is not None:
            self.run_selected.emit(int(run_id))

    def _emit_resume_run(self) -> None:
        run_id = self.run_combo.currentData()
        if run_id is not None:
            self.resume_run_requested.emit(int(run_id))

    def selected_task_id(self) -> int | None:
        row = self.result_table.currentRow()
        if row < 0:
            return None
        item = self.result_table.item(row, 0)
        if item is None:
            return None
        task_id = item.data(Qt.UserRole)
        return int(task_id) if task_id is not None else None

    def _emit_retry_task(self) -> None:
        task_id = self.selected_task_id()
        if task_id is None:
            QMessageBox.information(self, "未选择任务", "请先在结果表中选择一条失败任务。")
            return
        self.retry_task_requested.emit(task_id)

    @staticmethod
    def _percent(value: int, total: int) -> str:
        if total <= 0:
            return "0%"
        return f"{value / total:.0%}"
