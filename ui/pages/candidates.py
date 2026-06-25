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


STATUS_LABELS = {
    "idle": "空闲",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "stopped": "已停止",
    "waiting_user": "等待人工处理",
}

MATCH_STATUS_LABELS = {
    "screening_pending": "待 AI 筛选",
    "screening_running": "AI 筛选中",
    "screening_retrying": "等待重试",
    "ai_screened": "AI 已筛",
    "ai_failed": "AI 失败",
    "manual_check": "人工确认",
    "hold": "暂缓",
}

RECRUITMENT_STATUS_LABELS = {
    "uncontacted": "未触达",
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

REASON_CODE_LABELS = {
    "": "无原因",
    "priority_candidate": "优先候选人",
    "manual_review_passed": "人工复核通过",
    "manual_review_rejected": "人工复核拒绝",
    "salary_mismatch": "薪资不匹配",
    "location_mismatch": "地点不匹配",
    "experience_gap": "经验不足",
    "skill_gap": "技能缺口",
    "candidate_not_interested": "候选人无意向",
    "candidate_unresponsive": "候选人未回复",
    "interview_failed": "面试未通过",
    "offer_rejected": "Offer 被拒",
    "role_closed": "岗位关闭",
    "duplicate": "重复候选人",
}


class CandidatesPage(QWidget):
    refresh_requested = Signal()
    export_requested = Signal(object)
    candidate_selected = Signal(int)
    status_change_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        filter_group = QGroupBox("筛选条件")
        filter_layout = QHBoxLayout(filter_group)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索姓名、薪资、经历、标签或原始文本")
        self.job_title_combo = QComboBox()
        self.job_title_combo.addItem("全部岗位", "")
        self.batch_combo = QComboBox()
        self.batch_combo.addItem("全部批次", None)
        self.city_input = QLineEdit()
        self.city_input.setPlaceholderText("城市")
        self.city_input.setFixedWidth(72)
        self.years_min_input = QLineEdit()
        self.years_min_input.setPlaceholderText("年限起")
        self.years_min_input.setFixedWidth(64)
        self.years_max_input = QLineEdit()
        self.years_max_input.setPlaceholderText("年限止")
        self.years_max_input.setFixedWidth(64)
        self.profile_tag_input = QLineEdit()
        self.profile_tag_input.setPlaceholderText("企业服务 SaaS 销售")
        self.profile_tag_input.setFixedWidth(96)
        self.last_active_combo = QComboBox()
        self.last_active_combo.addItem("全部活跃", "")
        self.last_active_combo.addItem("近7天", 7)
        self.last_active_combo.addItem("近30天", 30)
        self.last_active_combo.addItem("近90天", 90)
        self.last_active_combo.addItem("近180天", 180)
        self.last_active_combo.addItem("近365天", 365)
        self.match_role_combo = QComboBox()
        self.match_role_combo.addItem("全部匹配岗位", None)
        self.rating_combo = QComboBox()
        self.rating_combo.addItem("不限评级", "")
        for rating in ["UR", "SSR", "SR", "R", "N"]:
            self.rating_combo.addItem(f"{rating} 及以上", rating)
        self.match_status_combo = QComboBox()
        self.match_status_combo.addItem("全部匹配状态", "")
        for status, label in MATCH_STATUS_LABELS.items():
            self.match_status_combo.addItem(label, status)
        self.recruitment_status_filter_combo = QComboBox()
        self.recruitment_status_filter_combo.addItem("全部招聘阶段", "")
        for status, label in RECRUITMENT_STATUS_LABELS.items():
            self.recruitment_status_filter_combo.addItem(label, status)
        self.latest_reason_filter_combo = QComboBox()
        self.latest_reason_filter_combo.addItem("全部原因", "")
        for code, label in REASON_CODE_LABELS.items():
            if code:
                self.latest_reason_filter_combo.addItem(label, code)
        self.refresh_button = QPushButton("刷新")
        self.export_csv_button = QPushButton("导出 CSV")
        self.export_jsonl_button = QPushButton("导出 JSONL")
        self.export_markdown_button = QPushButton("导出 Markdown")
        filter_layout.addWidget(QLabel("关键词"))
        filter_layout.addWidget(self.search_input, 2)
        filter_layout.addWidget(QLabel("岗位"))
        filter_layout.addWidget(self.job_title_combo, 1)
        filter_layout.addWidget(QLabel("批次"))
        filter_layout.addWidget(self.batch_combo, 1)
        filter_layout.addWidget(QLabel("城市"))
        filter_layout.addWidget(self.city_input)
        filter_layout.addWidget(QLabel("年限"))
        filter_layout.addWidget(self.years_min_input)
        filter_layout.addWidget(self.years_max_input)
        filter_layout.addWidget(QLabel("标签"))
        filter_layout.addWidget(self.profile_tag_input)
        filter_layout.addWidget(QLabel("活跃"))
        filter_layout.addWidget(self.last_active_combo)
        filter_layout.addWidget(QLabel("匹配岗位"))
        filter_layout.addWidget(self.match_role_combo, 1)
        filter_layout.addWidget(QLabel("评级"))
        filter_layout.addWidget(self.rating_combo)
        filter_layout.addWidget(QLabel("状态"))
        filter_layout.addWidget(self.match_status_combo)
        filter_layout.addWidget(QLabel("阶段"))
        filter_layout.addWidget(self.recruitment_status_filter_combo)
        filter_layout.addWidget(QLabel("原因"))
        filter_layout.addWidget(self.latest_reason_filter_combo)
        filter_layout.addWidget(self.refresh_button)
        filter_layout.addWidget(self.export_csv_button)
        filter_layout.addWidget(self.export_jsonl_button)
        filter_layout.addWidget(self.export_markdown_button)

        splitter = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 15)
        self.table.setHorizontalHeaderLabels(
            [
                "姓名",
                "城市",
                "年限",
                "岗位方向",
                "活跃状态",
                "期望薪资",
                "来源岗位",
                "匹配岗位",
                "评级",
                "匹配状态",
                "招聘阶段",
                "最近原因",
                "最近备注",
                "更新时间",
                "出现批次",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)

        detail_group = QGroupBox("候选人详情")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text)
        status_group = QGroupBox("招聘进展")
        status_layout = QVBoxLayout(status_group)
        status_row = QHBoxLayout()
        self.status_role_combo = QComboBox()
        self.recruitment_status_update_combo = QComboBox()
        for status, label in RECRUITMENT_STATUS_LABELS.items():
            if status == "uncontacted":
                continue
            self.recruitment_status_update_combo.addItem(label, status)
        self.reason_code_combo = QComboBox()
        for code, label in REASON_CODE_LABELS.items():
            self.reason_code_combo.addItem(label, code)
        self.record_status_button = QPushButton("记录")
        status_row.addWidget(QLabel("岗位"))
        status_row.addWidget(self.status_role_combo, 2)
        status_row.addWidget(QLabel("阶段"))
        status_row.addWidget(self.recruitment_status_update_combo)
        status_row.addWidget(QLabel("原因"))
        status_row.addWidget(self.reason_code_combo)
        status_row.addWidget(self.record_status_button)
        self.status_note_input = QLineEdit()
        self.status_note_input.setPlaceholderText("备注")
        status_layout.addLayout(status_row)
        status_layout.addWidget(self.status_note_input)
        detail_layout.addWidget(status_group)
        splitter.addWidget(self.table)
        splitter.addWidget(detail_group)
        splitter.setSizes([700, 420])

        root_layout.addWidget(filter_group)
        root_layout.addWidget(splitter, 1)

        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.export_csv_button.clicked.connect(lambda: self._emit_export("csv"))
        self.export_jsonl_button.clicked.connect(lambda: self._emit_export("jsonl"))
        self.export_markdown_button.clicked.connect(lambda: self._emit_export("markdown"))
        self.search_input.returnPressed.connect(self.refresh_requested.emit)
        self.city_input.returnPressed.connect(self.refresh_requested.emit)
        self.years_min_input.returnPressed.connect(self.refresh_requested.emit)
        self.years_max_input.returnPressed.connect(self.refresh_requested.emit)
        self.profile_tag_input.returnPressed.connect(self.refresh_requested.emit)
        self.last_active_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.job_title_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.batch_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.match_role_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.rating_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.match_status_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.recruitment_status_filter_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.latest_reason_filter_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.table.itemSelectionChanged.connect(self._emit_selection)
        self.record_status_button.clicked.connect(self._emit_status_change)

    def current_filters(self) -> dict[str, object]:
        return {
            "keyword": self.search_input.text().strip(),
            "job_title": self.job_title_combo.currentData(),
            "batch_id": self.batch_combo.currentData(),
            "city": self.city_input.text().strip(),
            "years_min": self.years_min_input.text().strip(),
            "years_max": self.years_max_input.text().strip(),
            "profile_tag": self.profile_tag_input.text().strip(),
            "last_active_days": self.last_active_combo.currentData(),
            "match_role_id": self.match_role_combo.currentData(),
            "minimum_rating": self.rating_combo.currentData(),
            "match_status": self.match_status_combo.currentData(),
            "recruitment_status": self.recruitment_status_filter_combo.currentData(),
            "latest_reason_code": self.latest_reason_filter_combo.currentData(),
        }

    def set_candidates(self, rows: list[dict[str, object]]) -> None:
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("name", ""),
                row.get("city", ""),
                row.get("years_experience", ""),
                row.get("job_track") or row.get("job_family", ""),
                row.get("active_status", ""),
                row.get("expected_salary", ""),
                row.get("job_title", ""),
                row.get("role_title", ""),
                row.get("latest_rating", ""),
                self.translate_match_status(str(row.get("match_status") or "")),
                self.translate_recruitment_status(str(row.get("recruitment_status") or "")),
                REASON_CODE_LABELS.get(
                    str(row.get("latest_reason_code") or ""),
                    row.get("latest_reason_code") or "",
                ),
                row.get("latest_status_note", ""),
                row.get("match_updated_at") or row.get("updated_at", ""),
                str(row.get("batch_count", 0)),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if col_index == 0:
                    item.setData(Qt.UserRole, int(row["id"]))
                self.table.setItem(row_index, col_index, item)
        self.table.resizeColumnsToContents()
        if rows:
            self.table.selectRow(0)
        else:
            self.detail_text.setPlainText("暂无数据。")

    def set_filter_options(
        self,
        job_titles: list[str],
        batches: list[dict[str, object]],
        screening_profiles: list[dict[str, object]] | None = None,
    ) -> None:
        current_job = self.job_title_combo.currentData()
        self.job_title_combo.blockSignals(True)
        self.job_title_combo.clear()
        self.job_title_combo.addItem("全部岗位", "")
        for job_title in job_titles:
            self.job_title_combo.addItem(job_title, job_title)
        index = max(0, self.job_title_combo.findData(current_job))
        self.job_title_combo.setCurrentIndex(index)
        self.job_title_combo.blockSignals(False)

        current_batch = self.batch_combo.currentData()
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self.batch_combo.addItem("全部批次", None)
        for batch in batches:
            label = f"#{batch['id']} | {batch['job_title']} | {self.translate_status(str(batch['status']))}"
            self.batch_combo.addItem(label, int(batch["id"]))
        index = max(0, self.batch_combo.findData(current_batch))
        self.batch_combo.setCurrentIndex(index)
        self.batch_combo.blockSignals(False)

        current_role = self.match_role_combo.currentData()
        self.match_role_combo.blockSignals(True)
        self.match_role_combo.clear()
        self.match_role_combo.addItem("全部匹配岗位", None)
        for profile in screening_profiles or []:
            self.match_role_combo.addItem(str(profile["job_title"]), int(profile["id"]))
        index = max(0, self.match_role_combo.findData(current_role))
        self.match_role_combo.setCurrentIndex(index)
        self.match_role_combo.blockSignals(False)

    def show_candidate_detail(self, detail: dict[str, object] | None) -> None:
        if not detail:
            self._set_status_role_options([])
            self.detail_text.setPlainText("未找到候选人详情。")
            return

        candidate = detail["candidate"]
        appearances = detail["appearances"]
        standard_profile = detail.get("standard_profile")
        role_matches = detail.get("role_matches") or []
        status_events = detail.get("status_events") or []
        self._set_status_role_options(role_matches)
        lines = [
            f"姓名：{candidate['name'] or '-'}",
            f"活跃状态：{candidate['active_status'] or '-'}",
            f"期望薪资：{candidate['expected_salary'] or '-'}",
            f"工作经历：{candidate['work_experience_text'] or '-'}",
            f"教育经历：{candidate['education_text'] or '-'}",
            f"标签：{candidate['tags_text'] or '-'}",
            f"摘要：{candidate['summary_text'] or '-'}",
            f"详情链接：{candidate['detail_url'] or '-'}",
            f"来源岗位：{candidate['job_title'] or '-'}",
            f"来源链接：{candidate['source_url'] or '-'}",
            f"抓取时间：{candidate['capture_time'] or '-'}",
        ]
        if standard_profile:
            lines.extend(
                [
                    "",
                    "标准画像：",
                    f"- 城市：{standard_profile['city'] or '-'}",
                    f"- 年限：{standard_profile['years_experience'] if standard_profile['years_experience'] is not None else '-'}",
                    f"- 岗位族：{standard_profile['job_family'] or '-'}",
                    f"- 岗位方向：{standard_profile['job_track'] or '-'}",
                    f"- 行业标签：{self._json_tags(str(standard_profile['industry_tags_json'] or '[]'))}",
                    f"- 技能标签：{self._json_tags(str(standard_profile['skill_tags_json'] or '[]'))}",
                    f"- 完整度：{standard_profile['profile_completeness']}%",
                ]
            )
        lines.extend(["", "批次出现记录："])
        for appearance in appearances:
            lines.append(
                f"- 批次 #{appearance['batch_id']} | {appearance['job_title']} | "
                f"{appearance['capture_time']} | {self.translate_status(str(appearance['status']))}"
            )
        if role_matches:
            lines.extend(["", "岗位匹配："])
            for match in role_matches:
                lines.append(
                    f"- {match['role_title']} | {match['latest_rating'] or '-'} | "
                    f"{match['latest_confidence'] or '-'} | "
                    f"{self.translate_match_status(str(match['match_status']))} | "
                    f"{self.translate_recruitment_status(str(match['recruitment_status']))} | "
                    f"{match['updated_at']}"
                )
                lines.append(
                    f"  - AI建议：{match['recommended_action'] or '-'} | "
                    f"画像：{match['result_persona'] or '-'}"
                )
                lines.append(
                    f"  - 人工复核：{REASON_CODE_LABELS.get(str(match['human_decision'] or ''), match['human_decision'] or '-')}"
                )
                lines.append(f"  - 证据：{self._json_summary(str(match['evidence_json'] or '[]'))}")
                lines.append(f"  - 缺口：{self._json_summary(str(match['gap_json'] or '[]'))}")
                lines.append(f"  - 风险：{self._json_summary(str(match['risk_json'] or '[]'))}")
        if status_events:
            lines.extend(["", "招聘进展历史："])
            for event in status_events[:20]:
                reason = str(event["reason_code"] or "")
                note = str(event["note"] or "")
                suffix = ""
                if reason:
                    suffix += f" | {REASON_CODE_LABELS.get(reason, reason)}"
                if note:
                    suffix += f" | {note}"
                lines.append(
                    f"- {event['changed_at']} | {event['role_title']} | "
                    f"{self.translate_recruitment_status(str(event['from_status']))} -> "
                    f"{self.translate_recruitment_status(str(event['to_status']))}{suffix}"
                )
        lines.extend(["", "原始卡片文本：", str(candidate["raw_card_text"] or "-")])
        self.detail_text.setPlainText("\n".join(lines))

    def selected_candidate_id(self) -> int | None:
        current_row = self.table.currentRow()
        if current_row < 0:
            return None
        item = self.table.item(current_row, 0)
        if item is None:
            return None
        return int(item.data(Qt.UserRole))

    def _emit_export(self, export_format: str) -> None:
        payload = self.current_filters()
        payload["export_format"] = export_format
        self.export_requested.emit(payload)

    def _emit_selection(self) -> None:
        candidate_id = self.selected_candidate_id()
        if candidate_id is not None:
            self.candidate_selected.emit(candidate_id)

    def _set_status_role_options(self, role_matches: list[object]) -> None:
        self.status_role_combo.blockSignals(True)
        self.status_role_combo.clear()
        for match in role_matches:
            label = (
                f"{match['role_title']} | {match['latest_rating'] or '-'} | "
                f"{match['latest_confidence'] or '-'} | "
                f"{self.translate_recruitment_status(str(match['recruitment_status']))}"
            )
            self.status_role_combo.addItem(
                label,
                {
                    "candidate_id": int(match["candidate_id"]),
                    "role_id": int(match["role_id"]),
                },
            )
        self.status_role_combo.blockSignals(False)
        self.record_status_button.setEnabled(bool(role_matches))

    def _emit_status_change(self) -> None:
        role_data = self.status_role_combo.currentData()
        if not isinstance(role_data, dict):
            return
        self.status_change_requested.emit(
            {
                "candidate_id": int(role_data["candidate_id"]),
                "role_id": int(role_data["role_id"]),
                "to_status": self.recruitment_status_update_combo.currentData(),
                "reason_code": self.reason_code_combo.currentData() or "",
                "note": self.status_note_input.text().strip(),
            }
        )

    @staticmethod
    def _json_tags(value: str) -> str:
        try:
            tags = json.loads(value)
        except json.JSONDecodeError:
            return value or "-"
        if not isinstance(tags, list) or not tags:
            return "-"
        return "、".join(str(tag) for tag in tags)

    @staticmethod
    def _json_summary(value: str) -> str:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            return value or "-"
        if not parsed:
            return "-"
        if isinstance(parsed, list):
            parts: list[str] = []
            for item in parsed[:5]:
                if isinstance(item, dict):
                    text = "；".join(
                        f"{key}:{val}" for key, val in item.items() if val not in (None, "")
                    )
                    if text:
                        parts.append(text)
                else:
                    parts.append(str(item))
            return " / ".join(parts) or "-"
        if isinstance(parsed, dict):
            return "；".join(
                f"{key}:{val}" for key, val in parsed.items() if val not in (None, "")
            ) or "-"
        return str(parsed)

    @staticmethod
    def translate_status(status: str) -> str:
        return STATUS_LABELS.get(status, status)

    @staticmethod
    def translate_match_status(status: str) -> str:
        return MATCH_STATUS_LABELS.get(status, status)

    @staticmethod
    def translate_recruitment_status(status: str) -> str:
        return RECRUITMENT_STATUS_LABELS.get(status, status or "-")
