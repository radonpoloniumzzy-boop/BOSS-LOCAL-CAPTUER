from __future__ import annotations

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
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


ACTION_TYPE_LABELS = {
    "outreach": "待触达",
    "follow_up": "待跟进",
    "collect_info": "待补资料",
    "manual_review": "待复核",
    "interview": "待约面",
    "interview_feedback": "待收面试反馈",
    "offer_follow_up": "Offer 跟进",
    "revisit": "暂缓后复查",
    "other": "其他",
}

PRIORITY_LABELS = {
    "low": "低",
    "normal": "普通",
    "high": "高",
    "urgent": "紧急",
}

STATUS_LABELS = {"pending": "待处理", "completed": "已完成", "cancelled": "已取消"}


class NextActionsPage(QWidget):
    refresh_requested = Signal()
    save_requested = Signal(object)
    status_requested = Signal(int, str)
    subject_open_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict[str, object]] = []
        self._subject: dict[str, object] | None = None
        self._current_action_id: int | None = None
        self._preserve_draft = False
        self._page = 1
        self._page_size = 100
        self._total = 0
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        summary_group = QGroupBox("行动提醒概览")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_label = QLabel("待处理 0｜今日 0｜逾期 0｜未来七天 0｜今日完成 0")
        summary_layout.addWidget(self.summary_label)

        filter_group = QGroupBox("待办范围")
        filter_layout = QHBoxLayout(filter_group)
        self.role_combo = QComboBox()
        self.role_combo.addItem("全部岗位", None)
        self.view_combo = QComboBox()
        for label, value in [
            ("全部待办", "pending"),
            ("今日", "today"),
            ("逾期", "overdue"),
            ("未来七天", "next_7_days"),
            ("已完成", "completed"),
            ("全部记录", "all"),
        ]:
            self.view_combo.addItem(label, value)
        self.owner_filter_input = QLineEdit()
        self.owner_filter_input.setPlaceholderText("负责人（精确匹配）")
        self.refresh_button = QPushButton("刷新")
        filter_layout.addWidget(QLabel("岗位"))
        filter_layout.addWidget(self.role_combo, 2)
        filter_layout.addWidget(QLabel("时间视图"))
        filter_layout.addWidget(self.view_combo)
        filter_layout.addWidget(self.owner_filter_input)
        filter_layout.addWidget(self.refresh_button)

        splitter = QSplitter(Qt.Horizontal)
        list_group = QGroupBox("行动待办")
        list_layout = QVBoxLayout(list_group)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["优先级", "截止时间", "动作", "事项", "关联对象", "岗位", "负责人", "状态"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        list_layout.addWidget(self.table)

        editor_group = QGroupBox("待办详情")
        editor_layout = QVBoxLayout(editor_group)
        self.subject_label = QLabel("请从候选人页或招聘任务页创建待办。")
        self.subject_label.setWordWrap(True)
        form = QFormLayout()
        self.action_type_combo = QComboBox()
        for value, label in ACTION_TYPE_LABELS.items():
            self.action_type_combo.addItem(label, value)
        self.title_input = QLineEdit()
        self.owner_input = QLineEdit()
        self.due_input = QDateTimeEdit()
        self.due_input.setCalendarPopup(True)
        self.due_input.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.due_input.setDateTime(QDateTime.currentDateTime().addDays(1))
        self.priority_combo = QComboBox()
        for value, label in PRIORITY_LABELS.items():
            self.priority_combo.addItem(label, value)
        self.note_input = QPlainTextEdit()
        self.note_input.setMaximumHeight(90)
        form.addRow("动作类型", self.action_type_combo)
        form.addRow("事项标题", self.title_input)
        form.addRow("负责人", self.owner_input)
        form.addRow("截止时间", self.due_input)
        form.addRow("优先级", self.priority_combo)
        form.addRow("备注", self.note_input)
        self.feedback_label = QLabel("")
        self.feedback_label.setStyleSheet("color: #b42318;")
        actions = QHBoxLayout()
        self.new_button = QPushButton("新建")
        self.save_button = QPushButton("保存")
        self.complete_button = QPushButton("完成")
        self.cancel_button = QPushButton("取消待办")
        self.open_subject_button = QPushButton("打开关联对象")
        for button in [
            self.new_button, self.save_button, self.complete_button,
            self.cancel_button, self.open_subject_button,
        ]:
            actions.addWidget(button)
        editor_layout.addWidget(self.subject_label)
        editor_layout.addLayout(form)
        editor_layout.addWidget(self.feedback_label)
        editor_layout.addLayout(actions)
        editor_layout.addStretch(1)

        splitter.addWidget(list_group)
        splitter.addWidget(editor_group)
        splitter.setSizes([820, 440])

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
        self.view_combo.currentIndexChanged.connect(self._request_first_page)
        self.owner_filter_input.returnPressed.connect(self._request_first_page)
        self.previous_page_button.clicked.connect(lambda: self._request_page(self._page - 1))
        self.next_page_button.clicked.connect(lambda: self._request_page(self._page + 1))
        self.table.itemSelectionChanged.connect(self._load_selected_row)
        self.new_button.clicked.connect(self.clear_editor)
        self.save_button.clicked.connect(self._emit_save)
        self.complete_button.clicked.connect(lambda: self._emit_status("completed"))
        self.cancel_button.clicked.connect(lambda: self._emit_status("cancelled"))
        self.open_subject_button.clicked.connect(self._emit_open_subject)
        self._update_buttons()

    def current_filters(self) -> dict[str, object]:
        return {
            "view": self.view_combo.currentData() or "pending",
            "role_id": self.role_combo.currentData(),
            "owner": self.owner_filter_input.text().strip(),
        }

    def set_profiles(self, profiles: list[dict[str, object]]) -> None:
        current = self.role_combo.currentData()
        self.role_combo.blockSignals(True)
        self.role_combo.clear()
        self.role_combo.addItem("全部岗位", None)
        for profile in profiles:
            self.role_combo.addItem(str(profile["job_title"]), int(profile["id"]))
        self.role_combo.setCurrentIndex(max(0, self.role_combo.findData(current)))
        self.role_combo.blockSignals(False)

    def set_summary(self, summary: dict[str, object]) -> None:
        self.summary_label.setText(
            f"待处理 {summary.get('pending_total', 0)}｜今日 {summary.get('today', 0)}｜"
            f"逾期 {summary.get('overdue', 0)}｜未来七天 {summary.get('next_7_days', 0)}｜"
            f"今日完成 {summary.get('completed_today', 0)}"
        )

    def prefill_candidate(
        self, *, candidate_id: int, role_id: int, candidate_name: str, role_title: str
    ) -> None:
        self.clear_editor()
        self._subject = {
            "subject_type": "candidate_role", "candidate_id": candidate_id,
            "role_id": role_id, "task_id": None,
            "subject_label": f"候选人：{candidate_name}｜岗位：{role_title}",
        }
        self._preserve_draft = True
        self.action_type_combo.setCurrentIndex(self.action_type_combo.findData("follow_up"))
        self.subject_label.setText(str(self._subject["subject_label"]))
        self._update_buttons()

    def prefill_task(self, *, task_id: int, role_id: int, task_name: str, role_title: str) -> None:
        self.clear_editor()
        self._subject = {
            "subject_type": "recruitment_task", "candidate_id": None,
            "role_id": role_id, "task_id": task_id,
            "subject_label": f"招聘任务：{task_name}｜岗位：{role_title}",
        }
        self._preserve_draft = True
        self.action_type_combo.setCurrentIndex(self.action_type_combo.findData("manual_review"))
        self.subject_label.setText(str(self._subject["subject_label"]))
        self._update_buttons()

    def set_page_result(
        self, rows: list[dict[str, object]], *, total: int, page: int, page_size: int
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
            subject = row.get("candidate_name") or row.get("task_name") or "-"
            values = [
                PRIORITY_LABELS.get(str(row.get("priority") or ""), "-"),
                row.get("due_at") or "-",
                ACTION_TYPE_LABELS.get(str(row.get("action_type") or ""), "-"),
                row.get("title") or "-", subject, row.get("role_title") or "-",
                row.get("owner") or "-", STATUS_LABELS.get(str(row.get("status") or ""), "-"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, row_index)
                self.table.setItem(row_index, column, item)
        if rows and not self._preserve_draft:
            self.table.selectRow(0)
        elif not rows and not self._preserve_draft:
            self.clear_editor()

    def current_page(self) -> int:
        return self._page

    def page_size(self) -> int:
        return self._page_size

    def clear_editor(self) -> None:
        self._current_action_id = None
        self._preserve_draft = False
        self._subject = None
        self.subject_label.setText("请从候选人页或招聘任务页创建待办。")
        self.title_input.clear()
        self.owner_input.clear()
        self.note_input.clear()
        self.due_input.setDateTime(QDateTime.currentDateTime().addDays(1))
        self.priority_combo.setCurrentIndex(self.priority_combo.findData("normal"))
        self.feedback_label.clear()
        self._update_buttons()

    def _load_selected_row(self) -> None:
        index = self.table.currentRow()
        if index < 0 or index >= len(self._rows):
            return
        row = self._rows[index]
        self._preserve_draft = False
        self._current_action_id = int(row["id"])
        self._subject = {
            "subject_type": row["subject_type"], "candidate_id": row.get("candidate_id"),
            "role_id": int(row["role_id"]), "task_id": row.get("task_id"),
            "subject_label": (
                f"候选人：{row.get('candidate_name')}｜岗位：{row.get('role_title')}"
                if row["subject_type"] == "candidate_role"
                else f"招聘任务：{row.get('task_name')}｜岗位：{row.get('role_title')}"
            ),
        }
        self.subject_label.setText(str(self._subject["subject_label"]))
        self.action_type_combo.setCurrentIndex(self.action_type_combo.findData(row["action_type"]))
        self.title_input.setText(str(row.get("title") or ""))
        self.owner_input.setText(str(row.get("owner") or ""))
        self.due_input.setDateTime(QDateTime.fromString(str(row["due_at"]), Qt.ISODate))
        self.priority_combo.setCurrentIndex(self.priority_combo.findData(row["priority"]))
        self.note_input.setPlainText(str(row.get("note") or ""))
        self._update_buttons(status=str(row.get("status") or "pending"))

    def _emit_save(self) -> None:
        if self._subject is None:
            self.feedback_label.setText("请先从候选人页或招聘任务页选择关联对象。")
            return
        if not self.title_input.text().strip():
            self.feedback_label.setText("请填写事项标题。")
            return
        self.feedback_label.clear()
        self._preserve_draft = False
        self.save_requested.emit(
            {
                "id": self._current_action_id,
                **{key: self._subject.get(key) for key in ["subject_type", "candidate_id", "role_id", "task_id"]},
                "action_type": self.action_type_combo.currentData(),
                "title": self.title_input.text().strip(),
                "owner": self.owner_input.text().strip(),
                "due_at": self.due_input.dateTime().toString(Qt.ISODate),
                "priority": self.priority_combo.currentData(),
                "note": self.note_input.toPlainText().strip(),
            }
        )

    def _emit_status(self, status: str) -> None:
        if self._current_action_id is not None:
            self.status_requested.emit(self._current_action_id, status)

    def _emit_open_subject(self) -> None:
        if self._subject is not None:
            self.subject_open_requested.emit(dict(self._subject))

    def _update_buttons(self, *, status: str = "pending") -> None:
        has_subject = self._subject is not None
        editable = has_subject and status == "pending"
        self.save_button.setEnabled(editable)
        self.complete_button.setEnabled(self._current_action_id is not None and editable)
        self.cancel_button.setEnabled(self._current_action_id is not None and editable)
        self.open_subject_button.setEnabled(has_subject)

    def _request_first_page(self, *_args: object) -> None:
        self._request_page(1)

    def _request_page(self, page: int) -> None:
        self._page = max(1, int(page))
        self.refresh_requested.emit()
