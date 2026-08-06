from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


COMPARISON_LABELS = {
    "agreement": "判断一致",
    "disagreement": "判断有差异",
    "manual_resolved": "人工定案",
}

DIFFERENCE_LABELS = {
    "consistent_recommendation": "推荐一致",
    "consistent_rejection": "拒绝一致",
    "ai_overestimated": "AI 高估",
    "ai_underestimated": "AI 低估",
    "uncertain_human_passed": "AI 不确定，人工通过",
    "uncertain_human_rejected": "AI 不确定，人工拒绝",
}

AI_DECISION_LABELS = {
    "recommended": "建议推进",
    "not_recommended": "不建议推进",
    "uncertain": "需要人工定案",
}

HUMAN_DECISION_LABELS = {
    "manual_review_passed": "人工通过",
    "manual_review_rejected": "人工拒绝",
}


class AIHumanComparisonPage(QWidget):
    refresh_requested = Signal()
    candidate_open_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict[str, object]] = []
        self._page = 1
        self._page_size = 100
        self._total = 0
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        summary_group = QGroupBox("AI 与人工判断概览")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_label = QLabel(
            "已对照 0｜一致 0｜差异 0｜人工定案 0｜人工通过 0｜人工拒绝 0｜一致率 0.0%"
        )
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)

        filter_group = QGroupBox("对照范围")
        filter_layout = QHBoxLayout(filter_group)
        self.role_combo = QComboBox()
        self.role_combo.addItem("全部岗位", None)
        self.comparison_combo = QComboBox()
        for label, value in [
            ("全部结果", "all"),
            ("判断一致", "agreement"),
            ("判断有差异", "disagreement"),
            ("人工定案", "manual_resolved"),
        ]:
            self.comparison_combo.addItem(label, value)
        self.refresh_button = QPushButton("刷新")
        filter_layout.addWidget(QLabel("岗位"))
        filter_layout.addWidget(self.role_combo, 2)
        filter_layout.addWidget(QLabel("对照结果"))
        filter_layout.addWidget(self.comparison_combo)
        filter_layout.addWidget(self.refresh_button)
        filter_layout.addStretch(1)

        splitter = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["对照结论", "候选人", "岗位", "AI评级", "AI判断", "人工结论", "置信度", "人工备注", "复核时间"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)

        detail_group = QGroupBox("对照详情")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.open_candidate_button = QPushButton("在候选人页查看完整档案")
        self.open_candidate_button.setEnabled(False)
        detail_layout.addWidget(self.detail_text, 1)
        detail_layout.addWidget(self.open_candidate_button)
        splitter.addWidget(self.table)
        splitter.addWidget(detail_group)
        splitter.setSizes([820, 460])

        pagination = QHBoxLayout()
        pagination.addStretch(1)
        self.previous_page_button = QPushButton("上一页")
        self.next_page_button = QPushButton("下一页")
        self.page_label = QLabel("第 1 页 / 共 0 条")
        pagination.addWidget(self.previous_page_button)
        pagination.addWidget(self.page_label)
        pagination.addWidget(self.next_page_button)

        root.addWidget(summary_group)
        root.addWidget(filter_group)
        root.addWidget(splitter, 1)
        root.addLayout(pagination)

        self.refresh_button.clicked.connect(self._request_first_page)
        self.role_combo.currentIndexChanged.connect(self._request_first_page)
        self.comparison_combo.currentIndexChanged.connect(self._request_first_page)
        self.previous_page_button.clicked.connect(lambda: self._request_page(self._page - 1))
        self.next_page_button.clicked.connect(lambda: self._request_page(self._page + 1))
        self.table.itemSelectionChanged.connect(self._show_selected_detail)
        self.open_candidate_button.clicked.connect(self._open_selected_candidate)

    def current_filters(self) -> dict[str, object]:
        return {
            "role_id": self.role_combo.currentData(),
            "comparison_status": self.comparison_combo.currentData() or "all",
        }

    def set_profiles(self, profiles: list[dict[str, object]]) -> None:
        current_role = self.role_combo.currentData()
        self.role_combo.blockSignals(True)
        self.role_combo.clear()
        self.role_combo.addItem("全部岗位", None)
        for profile in profiles:
            self.role_combo.addItem(str(profile["job_title"]), int(profile["id"]))
        self.role_combo.setCurrentIndex(max(0, self.role_combo.findData(current_role)))
        self.role_combo.blockSignals(False)

    def set_summary(self, summary: dict[str, object]) -> None:
        self.summary_label.setText(
            f"已对照 {summary.get('compared_total', 0)}｜"
            f"一致 {summary.get('agreement_count', 0)}｜"
            f"差异 {summary.get('disagreement_count', 0)}｜"
            f"人工定案 {summary.get('manual_resolved_count', 0)}｜"
            f"人工通过 {summary.get('human_passed_count', 0)}｜"
            f"人工拒绝 {summary.get('human_rejected_count', 0)}｜"
            f"一致率 {float(summary.get('agreement_rate', 0) or 0):.1f}%"
        )

    def set_page_result(
        self,
        rows: list[dict[str, object]],
        *,
        total: int,
        page: int,
        page_size: int,
    ) -> None:
        self._rows = rows
        self._total = max(0, int(total))
        self._page = max(1, int(page))
        self._page_size = max(1, int(page_size))
        page_count = max(1, (self._total + self._page_size - 1) // self._page_size)
        self.page_label.setText(f"第 {self._page} / {page_count} 页，共 {self._total} 条")
        self.previous_page_button.setEnabled(self._page > 1)
        self.next_page_button.setEnabled(self._page < page_count)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                DIFFERENCE_LABELS.get(str(row.get("difference_type") or ""), "-"),
                row.get("name") or f"候选人 #{row.get('candidate_id')}",
                row.get("role_title") or "-",
                row.get("latest_rating") or "-",
                AI_DECISION_LABELS.get(str(row.get("ai_decision") or ""), "-"),
                HUMAN_DECISION_LABELS.get(str(row.get("human_decision") or ""), "-"),
                row.get("latest_confidence") or "-",
                row.get("human_note") or "-",
                row.get("human_reviewed_at") or "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, row_index)
                self.table.setItem(row_index, column, item)
        if rows:
            self.table.selectRow(0)
        else:
            self.detail_text.setPlainText("暂无已形成人工结论的对照样本。")
            self.open_candidate_button.setEnabled(False)

    def current_page(self) -> int:
        return self._page

    def page_size(self) -> int:
        return self._page_size

    def _request_first_page(self, *_args: object) -> None:
        self._request_page(1)

    def _request_page(self, page: int) -> None:
        self._page = max(1, int(page))
        self.refresh_requested.emit()

    def _selected_row(self) -> dict[str, object] | None:
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= len(self._rows):
            return None
        return self._rows[row_index]

    def _show_selected_detail(self) -> None:
        row = self._selected_row()
        self.open_candidate_button.setEnabled(row is not None)
        if row is None:
            return
        lines = [
            f"候选人：{row.get('name') or '-'}",
            f"岗位：{row.get('role_title') or '-'}",
            f"对照结论：{DIFFERENCE_LABELS.get(str(row.get('difference_type') or ''), '-')}",
            "",
            "AI 判断：",
            f"- 评级：{row.get('latest_rating') or '-'}",
            f"- 置信度：{row.get('latest_confidence') or '-'}",
            f"- 建议动作：{row.get('recommended_action') or '-'}",
            f"- 判断方向：{AI_DECISION_LABELS.get(str(row.get('ai_decision') or ''), '-')}",
            f"- 人物画像：{row.get('persona') or '-'}",
            "",
            "AI 证据：",
            *self._json_lines(row.get("evidence_json"), evidence=True),
            "",
            "AI 缺口：",
            *self._json_lines(row.get("gap_json")),
            "",
            "AI 风险：",
            *self._json_lines(row.get("risk_json")),
            "",
            "人工结论：",
            f"- 结果：{HUMAN_DECISION_LABELS.get(str(row.get('human_decision') or ''), '-')}",
            f"- 备注：{row.get('human_note') or '-'}",
            f"- 时间：{row.get('human_reviewed_at') or '-'}",
        ]
        self.detail_text.setPlainText("\n".join(lines))

    @staticmethod
    def _json_lines(value: object, *, evidence: bool = False) -> list[str]:
        try:
            items = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            items = []
        if not isinstance(items, list) or not items:
            return ["-"]
        lines: list[str] = []
        for item in items:
            if evidence and isinstance(item, dict):
                lines.append(f"- {item.get('item') or '-'}：{item.get('evidence') or '-'}")
            else:
                lines.append(f"- {item}")
        return lines

    def _open_selected_candidate(self) -> None:
        row = self._selected_row()
        if row is not None:
            self.candidate_open_requested.emit(int(row["candidate_id"]))
