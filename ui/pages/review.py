from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.pages.candidates import REASON_CODE_LABELS, RECRUITMENT_STATUS_LABELS


class ReviewPage(QWidget):
    refresh_requested = Signal()
    status_change_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict[str, object]] = []
        self._page = 1
        self._page_size = 100
        self._total = 0
        self._advance_from: tuple[int, int] | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        todo_group = QGroupBox("今日复核待办")
        todo_layout = QVBoxLayout(todo_group)
        self.todo_summary_label = QLabel(
            "待复核 0｜高优先级 0｜AI 不确定 0｜资料不完整 0｜待补充 0｜已暂缓 0｜今日已复核 0"
        )
        self.todo_summary_label.setWordWrap(True)
        todo_layout.addWidget(self.todo_summary_label)

        filter_group = QGroupBox("复核范围")
        filter_layout = QHBoxLayout(filter_group)
        self.role_combo = QComboBox()
        self.summary_label = QLabel("待复核 0")
        self.role_combo.addItem("全部岗位", None)
        self.queue_combo = QComboBox()
        for label, value in [
            ("全部待办", "all"),
            ("优先复核", "priority"),
            ("普通待复核", "pending"),
            ("待补充资料", "needs_info"),
            ("已暂缓", "deferred"),
        ]:
            self.queue_combo.addItem(label, value)
        self.refresh_button = QPushButton("刷新")
        filter_layout.addWidget(QLabel("岗位"))
        filter_layout.addWidget(self.role_combo, 2)
        filter_layout.addWidget(QLabel("队列"))
        filter_layout.addWidget(self.queue_combo)
        filter_layout.addWidget(self.refresh_button)
        filter_layout.addWidget(self.summary_label)
        filter_layout.addStretch(1)

        splitter = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["优先说明", "候选人", "岗位", "评级", "置信度", "原因", "建议动作", "招聘阶段", "更新时间"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)

        detail_group = QGroupBox("复核详情")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text)
        status_group = QGroupBox("处理结果")
        status_layout = QVBoxLayout(status_group)
        status_row = QHBoxLayout()
        self.recruitment_status_update_combo = QComboBox()
        for status, label in RECRUITMENT_STATUS_LABELS.items():
            if status in {"uncontacted", "collected"}:
                continue
            self.recruitment_status_update_combo.addItem(label, status)
        self.reason_code_combo = QComboBox()
        for code, label in REASON_CODE_LABELS.items():
            self.reason_code_combo.addItem(label, code)
        self.record_status_button = QPushButton("记录")
        self.record_and_next_button = QPushButton("保存并处理下一位")
        status_row.addWidget(QLabel("阶段"))
        status_row.addWidget(self.recruitment_status_update_combo)
        status_row.addWidget(QLabel("原因"))
        status_row.addWidget(self.reason_code_combo)
        status_row.addWidget(self.record_status_button)
        status_row.addWidget(self.record_and_next_button)
        self.status_note_input = QLineEdit()
        quick_row = QHBoxLayout()
        self.pass_review_button = QPushButton("通过并下一位")
        self.reject_review_button = QPushButton("拒绝并下一位")
        self.talent_pool_button = QPushButton("人才库并下一位")
        self.needs_info_button = QPushButton("待补充资料")
        self.defer_review_button = QPushButton("暂缓")
        quick_row.addWidget(self.pass_review_button)
        quick_row.addWidget(self.reject_review_button)
        quick_row.addWidget(self.talent_pool_button)
        quick_row.addWidget(self.needs_info_button)
        quick_row.addWidget(self.defer_review_button)
        quick_row.addStretch(1)
        self.status_note_input.setPlaceholderText("备注")
        self.review_feedback_label = QLabel("")
        self.review_feedback_label.setStyleSheet("color: #b42318;")
        self.status_note_input.textChanged.connect(self.review_feedback_label.clear)
        status_layout.addLayout(status_row)
        status_layout.addWidget(self.status_note_input)
        status_layout.addWidget(self.review_feedback_label)
        status_layout.addLayout(quick_row)
        detail_layout.addWidget(status_group)

        splitter.addWidget(self.table)
        splitter.addWidget(detail_group)
        splitter.setSizes([760, 460])

        root_layout.addWidget(todo_group)
        root_layout.addWidget(filter_group)
        root_layout.addWidget(splitter, 1)
        page_row = QHBoxLayout()
        page_row.addStretch(1)
        self.previous_page_button = QPushButton("上一页")
        self.next_page_button = QPushButton("下一页")
        self.page_label = QLabel("第 1 页 / 共 0 条")
        page_row.addWidget(self.previous_page_button)
        page_row.addWidget(self.page_label)
        page_row.addWidget(self.next_page_button)
        root_layout.addLayout(page_row)

        self.refresh_button.clicked.connect(self._request_first_page)
        self.role_combo.currentIndexChanged.connect(self._request_first_page)
        self.queue_combo.currentIndexChanged.connect(self._request_first_page)
        self.previous_page_button.clicked.connect(lambda: self._request_page(self._page - 1))
        self.next_page_button.clicked.connect(lambda: self._request_page(self._page + 1))
        self.table.itemSelectionChanged.connect(self._show_selected_detail)
        self.record_status_button.clicked.connect(self._emit_status_change)
        self.record_and_next_button.clicked.connect(lambda: self._emit_status_change(True))
        self.pass_review_button.clicked.connect(
            lambda: self._emit_quick_status_change(
                "priority_outreach",
                "manual_review_passed",
                "Manual review passed; prioritize outreach.",
            )
        )
        self.reject_review_button.clicked.connect(
            lambda: self._emit_quick_status_change(
                "rejected",
                "manual_review_rejected",
                "Manual review rejected.",
            )
        )
        self.talent_pool_button.clicked.connect(
            lambda: self._emit_quick_status_change(
                "talent_pool",
                "manual_review_passed",
                "Manual review passed; keep in talent pool.",
            )
        )
        self.needs_info_button.clicked.connect(
            lambda: self._emit_quick_status_change(
                "screened",
                "manual_review_needs_info",
                "资料不足，等待补充后重新复核。",
            )
        )
        self.defer_review_button.clicked.connect(
            lambda: self._emit_quick_status_change(
                "screened",
                "manual_review_deferred",
                "当前暂缓处理，保留在复核队列。",
            )
        )

    def current_filters(self) -> dict[str, object]:
        return {
            "role_id": self.role_combo.currentData(),
            "queue_category": self.queue_combo.currentData() or "all",
        }

    def set_workbench_summary(self, summary: dict[str, object]) -> None:
        self.todo_summary_label.setText(
            f"待复核 {summary.get('pending_total', 0)}｜"
            f"高优先级 {summary.get('high_priority', 0)}｜"
            f"AI 不确定 {summary.get('ai_uncertain', 0)}｜"
            f"资料不完整 {summary.get('incomplete_profiles', 0)}｜"
            f"待补充 {summary.get('needs_info', 0)}｜"
            f"已暂缓 {summary.get('deferred', 0)}｜"
            f"今日已复核 {summary.get('reviewed_today', 0)}"
        )

    def set_profiles(self, profiles: list[dict[str, object]]) -> None:
        current_role = self.role_combo.currentData()
        self.role_combo.blockSignals(True)
        self.role_combo.clear()
        self.role_combo.addItem("全部岗位", None)
        for profile in profiles:
            self.role_combo.addItem(str(profile["job_title"]), int(profile["id"]))
        index = self.role_combo.findData(current_role)
        self.role_combo.setCurrentIndex(max(0, index))
        self.role_combo.blockSignals(False)

    def set_rows(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.summary_label.setText(f"待复核 {self._total or len(rows)}")
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("priority_reason") or "普通待复核",
                row.get("name") or f"候选人 #{row.get('candidate_id')}",
                row.get("role_title") or "-",
                row.get("latest_rating") or "-",
                row.get("latest_confidence") or row.get("confidence") or "-",
                row.get("review_reason") or "-",
                row.get("recommended_action") or "-",
                RECRUITMENT_STATUS_LABELS.get(
                    str(row.get("recruitment_status") or ""),
                    row.get("recruitment_status") or "-",
                ),
                row.get("match_updated_at") or "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 1:
                    item.setData(Qt.UserRole, row_index)
                self.table.setItem(row_index, column, item)
        if rows:
            target_row = 0
            if self._advance_from is not None:
                next_rows = [
                    index
                    for index, row in enumerate(rows)
                    if (int(row["candidate_id"]), int(row["role_id"])) != self._advance_from
                ]
                target_row = next_rows[0] if next_rows else -1
                self._advance_from = None
            if target_row >= 0:
                self.table.selectRow(target_row)
            else:
                self.table.clearSelection()
                self.detail_text.setPlainText("当前队列没有下一位待办。")
        else:
            self._advance_from = None
            self.detail_text.setPlainText("暂无需要人工复核的候选人。")
        has_selection = self.table.currentRow() >= 0
        self.record_status_button.setEnabled(has_selection)
        self.record_and_next_button.setEnabled(has_selection)
        self.pass_review_button.setEnabled(has_selection)
        self.reject_review_button.setEnabled(has_selection)
        self.talent_pool_button.setEnabled(has_selection)
        self.needs_info_button.setEnabled(has_selection)
        self.defer_review_button.setEnabled(has_selection)

    def set_page_result(
        self,
        rows: list[dict[str, object]],
        *,
        total: int,
        page: int,
        page_size: int,
    ) -> None:
        self._total = max(0, int(total))
        self._page = max(1, int(page))
        self._page_size = max(1, int(page_size))
        page_count = max(1, (self._total + self._page_size - 1) // self._page_size)
        self.page_label.setText(f"第 {self._page} / {page_count} 页，共 {self._total} 条")
        self.previous_page_button.setEnabled(self._page > 1)
        self.next_page_button.setEnabled(self._page < page_count)
        self.set_rows(rows)

    def current_page(self) -> int:
        return self._page

    def page_size(self) -> int:
        return self._page_size

    def _request_first_page(self, *_args: object) -> None:
        self._request_page(1)

    def _request_page(self, page: int) -> None:
        self._page = max(1, int(page))
        self.refresh_requested.emit()

    def _show_selected_detail(self) -> None:
        row = self._selected_review_row()
        if row is None:
            self.record_status_button.setEnabled(False)
            self.record_and_next_button.setEnabled(False)
            self.pass_review_button.setEnabled(False)
            self.reject_review_button.setEnabled(False)
            self.talent_pool_button.setEnabled(False)
            self.needs_info_button.setEnabled(False)
            self.defer_review_button.setEnabled(False)
            return
        self.record_status_button.setEnabled(True)
        self.record_and_next_button.setEnabled(True)
        self.pass_review_button.setEnabled(True)
        self.reject_review_button.setEnabled(True)
        self.talent_pool_button.setEnabled(True)
        self.needs_info_button.setEnabled(True)
        self.defer_review_button.setEnabled(True)
        lines = [
            f"候选人：{row.get('name') or '-'}",
            f"岗位：{row.get('role_title') or '-'}",
            f"评级：{row.get('latest_rating') or '-'}",
            f"置信度：{row.get('latest_confidence') or row.get('confidence') or '-'}",
            f"复核原因：{row.get('review_reason') or '-'}",
            f"待办分类：{row.get('priority_reason') or '-'}",
            f"建议动作：{row.get('recommended_action') or '-'}",
            f"招聘阶段：{row.get('recruitment_status') or '-'}",
            f"AI失败原因：{row.get('task_error') or '-'}",
            f"重试次数：{row.get('retry_count') if row.get('retry_count') is not None else '-'} / {row.get('max_retry_count') if row.get('max_retry_count') is not None else '-'}",
            f"任务更新时间：{row.get('task_updated_at') or '-'}",
            f"城市/年限：{row.get('city') or '-'} / {row.get('years_experience') if row.get('years_experience') is not None else '-'}",
            f"岗位方向：{row.get('job_track') or row.get('job_family') or '-'}",
            "",
            "规则分流：",
            self._route_detail(row),
            "",
            "AI 人物画像：",
            str(row.get("persona") or "-"),
            "",
            "证据：",
        ]
        evidence = self._loads(row.get("evidence_json"), [])
        if evidence:
            for item in evidence:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('item') or '-'}：{item.get('evidence') or '-'}")
        else:
            lines.append("-")
        lines.extend(["", "缺口："])
        for item in self._loads(row.get("gap_json"), []) or ["-"]:
            lines.append(f"- {item}")
        lines.extend(["", "风险："])
        for item in self._loads(row.get("risk_json"), []) or ["-"]:
            lines.append(f"- {item}")
        lines.extend(["", "原始卡片：", str(row.get("raw_card_text") or "-")])
        lines.extend(["", "人工复核记录：", self._review_history_detail(row)])
        self.detail_text.setPlainText("\n".join(lines))

    def _emit_status_change(self, advance_after_save: bool = False) -> None:
        saved = self._emit_status_payload(
            self.recruitment_status_update_combo.currentData(),
            self.reason_code_combo.currentData() or "",
            self.status_note_input.text().strip(),
            advance_after_save=bool(advance_after_save),
        )
        if saved:
            self.status_note_input.clear()

    def _emit_quick_status_change(
        self,
        to_status: str,
        reason_code: str,
        default_note: str,
    ) -> None:
        entered_note = self.status_note_input.text().strip()
        note = entered_note or default_note
        saved = self._emit_status_payload(to_status, reason_code, note, note_was_entered=bool(entered_note))
        if saved:
            self.status_note_input.clear()

    def _emit_status_payload(
        self,
        to_status: object,
        reason_code: object,
        note: str,
        *,
        advance_after_save: bool = True,
        note_was_entered: bool | None = None,
    ) -> bool:
        row = self._selected_review_row()
        if row is None:
            return False
        normalized_reason = str(reason_code or "")
        has_specific_note = bool(note.strip()) if note_was_entered is None else note_was_entered
        required_note_messages = {
            "manual_review_needs_info": "请先填写需要补充的具体资料。",
            "manual_review_deferred": "请先填写暂缓原因。",
        }
        if normalized_reason in required_note_messages and not has_specific_note:
            self.review_feedback_label.setText(required_note_messages[normalized_reason])
            self.status_note_input.setFocus()
            return False
        self.review_feedback_label.clear()
        if advance_after_save:
            self._advance_from = (int(row["candidate_id"]), int(row["role_id"]))
        self.status_change_requested.emit(
            {
                "candidate_id": int(row["candidate_id"]),
                "role_id": int(row["role_id"]),
                "to_status": to_status,
                "reason_code": normalized_reason,
                "note": note,
                "advance_after_save": advance_after_save,
                "operator": "review_workbench",
            }
        )
        return True

    def _selected_review_row(self) -> dict[str, object] | None:
        current_row = self.table.currentRow()
        if current_row < 0 or current_row >= len(self._rows):
            return None
        return self._rows[current_row]

    @staticmethod
    def _review_history_detail(row: dict[str, object]) -> str:
        text = str(row.get("review_history_text") or "").strip()
        if not text:
            return "-"
        lines: list[str] = []
        for raw_line in text.splitlines():
            parts = raw_line.split("｜", 3)
            if len(parts) < 4:
                lines.append(raw_line)
                continue
            changed_at, status, reason, note = parts
            status_label = RECRUITMENT_STATUS_LABELS.get(status, status or "-")
            reason_label = REASON_CODE_LABELS.get(reason, reason or "-")
            lines.append(f"- {changed_at}｜{status_label}｜{reason_label}｜{note or '-'}")
        return "\n".join(lines)

    @staticmethod
    def _route_detail(row: dict[str, object]) -> str:
        reason = str(row.get("route_reason") or "")
        details = ReviewPage._loads(row.get("route_details_json"), {})
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
        lines = [labels.get(reason, reason)] if reason else ["-"]
        if isinstance(details, dict):
            role = details.get("role_requirements")
            if isinstance(role, dict):
                min_years = role.get("min_years")
                cities = role.get("city_terms") or []
                required = role.get("required_terms") or []
                if min_years is not None:
                    lines.append(f"- 岗位最低年限：{min_years}")
                if cities:
                    lines.append("- 岗位城市：" + "、".join(str(item) for item in cities))
                if required:
                    lines.append("- 岗位关键词：" + "、".join(str(item) for item in required))
            if details.get("candidate_years") is not None:
                lines.append(f"- 候选人年限：{details.get('candidate_years')}")
            candidate_cities = details.get("candidate_cities") or []
            if candidate_cities:
                lines.append("- 候选人城市：" + "、".join(str(item) for item in candidate_cities))
            missing = details.get("missing_required_terms") or []
            if missing:
                lines.append("- 缺失关键词：" + "、".join(str(item) for item in missing))
            evidence_policy = details.get("evidence_policy")
            if evidence_policy:
                lines.append(f"- 证据策略：{evidence_policy}")
            evidence_fields = (
                ("matched_direct_evidence", "直接证据"),
                ("matched_market_terms", "市场证据"),
                ("matched_action_terms", "动作证据"),
                ("matched_exclusion_terms", "排除证据"),
            )
            for field, label in evidence_fields:
                matches = details.get(field) or []
                if matches:
                    lines.append(f"- {label}：" + "、".join(str(item) for item in matches))
        return "\n".join(lines)

    @staticmethod
    def _loads(value: object, fallback: object) -> object:
        try:
            return json.loads(str(value or ""))
        except json.JSONDecodeError:
            return fallback
