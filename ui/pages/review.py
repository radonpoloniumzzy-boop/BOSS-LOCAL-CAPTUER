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
        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        filter_group = QGroupBox("复核范围")
        filter_layout = QHBoxLayout(filter_group)
        self.role_combo = QComboBox()
        self.summary_label = QLabel("待复核 0")
        self.role_combo.addItem("全部岗位", None)
        self.refresh_button = QPushButton("刷新")
        filter_layout.addWidget(QLabel("岗位"))
        filter_layout.addWidget(self.role_combo, 2)
        filter_layout.addWidget(self.refresh_button)
        filter_layout.addWidget(self.summary_label)
        filter_layout.addStretch(1)

        splitter = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["候选人", "岗位", "评级", "置信度", "原因", "建议动作", "招聘阶段", "更新时间"]
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
        status_row.addWidget(QLabel("阶段"))
        status_row.addWidget(self.recruitment_status_update_combo)
        status_row.addWidget(QLabel("原因"))
        status_row.addWidget(self.reason_code_combo)
        status_row.addWidget(self.record_status_button)
        self.status_note_input = QLineEdit()
        quick_row = QHBoxLayout()
        self.pass_review_button = QPushButton("人工通过")
        self.reject_review_button = QPushButton("人工拒绝")
        self.talent_pool_button = QPushButton("放入人才库")
        quick_row.addWidget(self.pass_review_button)
        quick_row.addWidget(self.reject_review_button)
        quick_row.addWidget(self.talent_pool_button)
        quick_row.addStretch(1)
        self.status_note_input.setPlaceholderText("备注")
        status_layout.addLayout(status_row)
        status_layout.addWidget(self.status_note_input)
        status_layout.addLayout(quick_row)
        detail_layout.addWidget(status_group)

        splitter.addWidget(self.table)
        splitter.addWidget(detail_group)
        splitter.setSizes([760, 460])

        root_layout.addWidget(filter_group)
        root_layout.addWidget(splitter, 1)

        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.role_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.table.itemSelectionChanged.connect(self._show_selected_detail)
        self.record_status_button.clicked.connect(self._emit_status_change)
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

    def current_filters(self) -> dict[str, object]:
        return {"role_id": self.role_combo.currentData()}

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
        self.summary_label.setText(f"待复核 {len(rows)}")
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
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
                if column == 0:
                    item.setData(Qt.UserRole, row_index)
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()
        if rows:
            self.table.selectRow(0)
        else:
            self.detail_text.setPlainText("暂无需要人工复核的候选人。")
        self.record_status_button.setEnabled(bool(rows))
        self.pass_review_button.setEnabled(bool(rows))
        self.reject_review_button.setEnabled(bool(rows))
        self.talent_pool_button.setEnabled(bool(rows))

    def _show_selected_detail(self) -> None:
        row = self._selected_review_row()
        if row is None:
            self.record_status_button.setEnabled(False)
            self.pass_review_button.setEnabled(False)
            self.reject_review_button.setEnabled(False)
            self.talent_pool_button.setEnabled(False)
            return
        self.record_status_button.setEnabled(True)
        self.pass_review_button.setEnabled(True)
        self.reject_review_button.setEnabled(True)
        self.talent_pool_button.setEnabled(True)
        lines = [
            f"候选人：{row.get('name') or '-'}",
            f"岗位：{row.get('role_title') or '-'}",
            f"评级：{row.get('latest_rating') or '-'}",
            f"置信度：{row.get('latest_confidence') or row.get('confidence') or '-'}",
            f"复核原因：{row.get('review_reason') or '-'}",
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
        self.detail_text.setPlainText("\n".join(lines))

    def _emit_status_change(self) -> None:
        self._emit_status_payload(
            self.recruitment_status_update_combo.currentData(),
            self.reason_code_combo.currentData() or "",
            self.status_note_input.text().strip(),
        )
        self.status_note_input.clear()

    def _emit_quick_status_change(
        self,
        to_status: str,
        reason_code: str,
        default_note: str,
    ) -> None:
        note = self.status_note_input.text().strip() or default_note
        self._emit_status_payload(to_status, reason_code, note)
        self.status_note_input.clear()

    def _emit_status_payload(
        self,
        to_status: object,
        reason_code: object,
        note: str,
    ) -> None:
        row = self._selected_review_row()
        if row is None:
            return
        self.status_change_requested.emit(
            {
                "candidate_id": int(row["candidate_id"]),
                "role_id": int(row["role_id"]),
                "to_status": to_status,
                "reason_code": reason_code or "",
                "note": note,
            }
        )

    def _selected_review_row(self) -> dict[str, object] | None:
        current_row = self.table.currentRow()
        if current_row < 0 or current_row >= len(self._rows):
            return None
        return self._rows[current_row]

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
        return "\n".join(lines)

    @staticmethod
    def _loads(value: object, fallback: object) -> object:
        try:
            return json.loads(str(value or ""))
        except json.JSONDecodeError:
            return fallback
