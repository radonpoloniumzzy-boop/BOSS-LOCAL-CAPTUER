from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


JOB_STATUS_LABELS = {
    "draft": "草稿",
    "active": "招聘中",
    "paused": "已暂停",
    "closed": "已结束",
}

JOB_STATUS_CHOICES = {
    "draft": ("draft", "active", "closed"),
    "active": ("active", "paused", "closed"),
    "paused": ("paused", "active", "closed"),
    "closed": ("closed",),
}

PRIORITY_LABELS = {"high": "高", "normal": "普通", "low": "低"}


class JobProfilesPage(QWidget):
    profile_selected = Signal(int)
    save_requested = Signal(object)
    clone_requested = Signal(int, str)
    status_change_requested = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.current_profile_id: int | None = None
        self._profiles: list[dict[str, object]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("岗位中心")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self.new_button = QPushButton("新建岗位")
        self.clone_button = QPushButton("复制岗位")
        self.save_button = QPushButton("保存岗位档案")
        self.save_button.setProperty("primary", True)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.new_button)
        title_row.addWidget(self.clone_button)
        title_row.addWidget(self.save_button)
        root.addLayout(title_row)

        hint = QLabel(
            "岗位档案是采集、AI 初筛、人工复核和人才 Mapping 的统一入口；"
            "保存会产生新版本，暂停或结束不会删除历史结果。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        splitter = QSplitter()
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        filter_row = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("全部状态", "")
        for status, label in JOB_STATUS_LABELS.items():
            self.status_filter.addItem(label, status)
        filter_row.addWidget(QLabel("状态"))
        filter_row.addWidget(self.status_filter)
        list_layout.addLayout(filter_row)
        self.profile_table = QTableWidget(0, 4)
        self.profile_table.setHorizontalHeaderLabels(["岗位", "状态", "目标", "负责人"])
        self.profile_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.profile_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.profile_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.profile_table.setAlternatingRowColors(True)
        self.profile_table.verticalHeader().setVisible(False)
        self.profile_table.horizontalHeader().setStretchLastSection(True)
        list_layout.addWidget(self.profile_table, 1)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_head = QHBoxLayout()
        self.current_title_label = QLabel("新建岗位")
        self.current_title_label.setStyleSheet("font-size: 17px; font-weight: 650;")
        self.version_label = QLabel("V1")
        self.status_combo = QComboBox()
        for status, label in JOB_STATUS_LABELS.items():
            self.status_combo.addItem(label, status)
        self.apply_status_button = QPushButton("更新状态")
        editor_head.addWidget(self.current_title_label)
        editor_head.addWidget(self.version_label)
        editor_head.addStretch(1)
        editor_head.addWidget(self.status_combo)
        editor_head.addWidget(self.apply_status_button)
        editor_layout.addLayout(editor_head)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), "基本信息")
        self.tabs.addTab(self._build_screening_tab(), "筛选规则")
        self.tabs.addTab(self._build_versions_tab(), "版本历史")
        editor_layout.addWidget(self.tabs, 1)
        self.message_label = QLabel("请选择岗位，或新建岗位档案。")
        self.message_label.setWordWrap(True)
        editor_layout.addWidget(self.message_label)

        splitter.addWidget(list_panel)
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        root.addWidget(splitter, 1)

        self.new_button.clicked.connect(self.clear_profile)
        self.save_button.clicked.connect(self._emit_save)
        self.clone_button.clicked.connect(self._emit_clone)
        self.apply_status_button.clicked.connect(self._emit_status_change)
        self.status_filter.currentIndexChanged.connect(self._render_profiles)
        self.profile_table.itemSelectionChanged.connect(self._emit_selected)
        self.clear_profile()

    def _build_basic_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form_group = QGroupBox("岗位信息与招聘目标")
        grid = QGridLayout(form_group)
        self.job_title_input = QLineEdit()
        self.department_input = QLineEdit()
        self.hiring_manager_input = QLineEdit()
        self.location_input = QLineEdit()
        self.employment_type_input = QLineEdit()
        self.experience_input = QLineEdit()
        self.education_input = QLineEdit()
        self.target_hires_input = QSpinBox()
        self.target_hires_input.setRange(1, 999)
        self.deadline_input = QLineEdit()
        self.deadline_input.setPlaceholderText("YYYY-MM-DD，可暂不填写")
        self.priority_combo = QComboBox()
        for priority, label in PRIORITY_LABELS.items():
            self.priority_combo.addItem(label, priority)
        fields = [
            ("岗位名称", self.job_title_input),
            ("部门", self.department_input),
            ("招聘负责人", self.hiring_manager_input),
            ("工作地点", self.location_input),
            ("用工类型", self.employment_type_input),
            ("经验要求", self.experience_input),
            ("学历要求", self.education_input),
            ("目标招聘人数", self.target_hires_input),
            ("招聘截止日期", self.deadline_input),
            ("优先级", self.priority_combo),
        ]
        for index, (label, widget) in enumerate(fields):
            row = index // 2
            column = (index % 2) * 2
            grid.addWidget(QLabel(label), row, column)
            grid.addWidget(widget, row, column + 1)
        self.jd_input = QPlainTextEdit()
        self.jd_input.setPlaceholderText("岗位职责、工作内容及完整 JD")
        layout.addWidget(form_group)
        layout.addWidget(QLabel("岗位说明 JD"))
        layout.addWidget(self.jd_input, 1)
        return tab

    def _build_screening_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        rules = QGroupBox("结构化筛选条件")
        form = QFormLayout(rules)
        self.must_have_input = QLineEdit()
        self.nice_to_have_input = QLineEdit()
        self.risk_flags_input = QLineEdit()
        self.exclusions_input = QLineEdit()
        self.interview_checks_input = QLineEdit()
        self.evidence_policy_input = QLineEdit()
        for widget in [
            self.must_have_input,
            self.nice_to_have_input,
            self.risk_flags_input,
            self.exclusions_input,
            self.interview_checks_input,
        ]:
            widget.setPlaceholderText("多项内容请用中文分号分隔")
        self.evidence_policy_input.setPlaceholderText("JSON，可暂不填写")
        form.addRow("必须条件", self.must_have_input)
        form.addRow("加分项", self.nice_to_have_input)
        form.addRow("风险提示", self.risk_flags_input)
        form.addRow("排除项", self.exclusions_input)
        form.addRow("面试核验", self.interview_checks_input)
        form.addRow("证据策略", self.evidence_policy_input)
        self.prompt_input = QPlainTextEdit()
        self.prompt_input.setPlaceholderText("留空时根据岗位说明和结构化规则自动生成")
        layout.addWidget(rules)
        layout.addWidget(QLabel("AI 初筛提示词"))
        layout.addWidget(self.prompt_input, 1)
        return tab

    def _build_versions_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        hint = QLabel("每次保存或状态变更都会形成版本快照；历史筛选批次继续指向启动时版本。")
        hint.setWordWrap(True)
        self.version_table = QTableWidget(0, 5)
        self.version_table.setHorizontalHeaderLabels(
            ["版本", "保存时间", "状态", "目标人数", "岗位说明摘要"]
        )
        self.version_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.version_table.setAlternatingRowColors(True)
        self.version_table.verticalHeader().setVisible(False)
        self.version_table.horizontalHeader().setStretchLastSection(True)
        self.version_detail = QPlainTextEdit()
        self.version_detail.setReadOnly(True)
        self.version_detail.setPlaceholderText("选择一个版本查看完整快照。")
        self.version_detail.setMaximumHeight(170)
        self.version_table.itemSelectionChanged.connect(self._show_version_detail)
        layout.addWidget(hint)
        layout.addWidget(self.version_table, 1)
        layout.addWidget(QLabel("版本快照"))
        layout.addWidget(self.version_detail)
        return tab

    def set_profiles(self, profiles: list[dict[str, object]]) -> None:
        self._profiles = [dict(profile) for profile in profiles]
        self._render_profiles()

    def _render_profiles(self) -> None:
        status = str(self.status_filter.currentData() or "")
        profiles = [p for p in self._profiles if not status or p.get("status") == status]
        self.profile_table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            title = QTableWidgetItem(str(profile.get("job_title") or "未命名岗位"))
            title.setData(Qt.UserRole, int(profile["id"]))
            values = [
                title,
                QTableWidgetItem(JOB_STATUS_LABELS.get(str(profile.get("status")), "未标记")),
                QTableWidgetItem(str(profile.get("target_hires") or 1)),
                QTableWidgetItem(str(profile.get("hiring_manager") or "-")),
            ]
            for column, item in enumerate(values):
                self.profile_table.setItem(row, column, item)
        self.profile_table.resizeRowsToContents()

    def show_profile(self, profile: dict[str, object] | None) -> None:
        if not profile:
            self.clear_profile()
            return
        self.current_profile_id = int(profile["id"])
        self.current_title_label.setText(str(profile.get("job_title") or "未命名岗位"))
        self.version_label.setText(f"V{int(profile.get('version') or 1)}")
        self.job_title_input.setText(str(profile.get("job_title") or ""))
        self.department_input.setText(str(profile.get("department") or ""))
        self.hiring_manager_input.setText(str(profile.get("hiring_manager") or ""))
        self.location_input.setText(str(profile.get("location") or ""))
        self.employment_type_input.setText(str(profile.get("employment_type") or ""))
        self.experience_input.setText(str(profile.get("experience_requirement") or ""))
        self.education_input.setText(str(profile.get("education_requirement") or ""))
        self.target_hires_input.setValue(int(profile.get("target_hires") or 1))
        self.deadline_input.setText(str(profile.get("recruitment_deadline") or ""))
        self.priority_combo.setCurrentIndex(
            max(0, self.priority_combo.findData(str(profile.get("priority") or "normal")))
        )
        self._set_status_choices(str(profile.get("status") or "draft"))
        self.jd_input.setPlainText(str(profile.get("jd_text") or ""))
        self.must_have_input.setText(self._join(profile.get("must_have")))
        self.nice_to_have_input.setText(self._join(profile.get("nice_to_have")))
        self.risk_flags_input.setText(self._join(profile.get("risk_flags")))
        self.exclusions_input.setText(self._join(profile.get("exclusions")))
        self.interview_checks_input.setText(self._join(profile.get("interview_checks")))
        self.evidence_policy_input.setText(
            json.dumps(profile.get("evidence_policy") or {}, ensure_ascii=False, sort_keys=True)
        )
        self.prompt_input.setPlainText(str(profile.get("prompt_text") or ""))
        self.clone_button.setEnabled(True)
        self.apply_status_button.setEnabled(True)
        self.message_label.setText("编辑后保存会创建新的岗位版本。")

    def clear_profile(self) -> None:
        self.current_profile_id = None
        self.current_title_label.setText("新建岗位")
        self.version_label.setText("V1")
        for widget in [
            self.job_title_input,
            self.department_input,
            self.hiring_manager_input,
            self.location_input,
            self.employment_type_input,
            self.experience_input,
            self.education_input,
            self.deadline_input,
            self.must_have_input,
            self.nice_to_have_input,
            self.risk_flags_input,
            self.exclusions_input,
            self.interview_checks_input,
            self.evidence_policy_input,
        ]:
            widget.clear()
        self.target_hires_input.setValue(1)
        self.priority_combo.setCurrentIndex(max(0, self.priority_combo.findData("normal")))
        self.status_combo.clear()
        for status in ("draft", "active"):
            self.status_combo.addItem(JOB_STATUS_LABELS[status], status)
        self.status_combo.setCurrentIndex(max(0, self.status_combo.findData("draft")))
        self.jd_input.clear()
        self.prompt_input.clear()
        self.version_table.setRowCount(0)
        self.version_detail.clear()
        self.clone_button.setEnabled(False)
        self.apply_status_button.setEnabled(False)
        self.message_label.setText("新岗位先以草稿保存，确认规则后再切换为招聘中。")

    def set_versions(self, versions: list[dict[str, object]]) -> None:
        self.version_table.setRowCount(len(versions))
        for row, version in enumerate(versions):
            snapshot = dict(version.get("snapshot") or {})
            jd = str(snapshot.get("jd_text") or "").replace("\n", " ")
            values = [
                f"V{version.get('version')}",
                str(version.get("created_at") or "-"),
                JOB_STATUS_LABELS.get(str(snapshot.get("status")), "未标记"),
                str(snapshot.get("target_hires") or 1),
                jd[:80] or "-",
            ]
            for column, value in enumerate(values):
                self.version_table.setItem(row, column, QTableWidgetItem(value))
            self.version_table.item(row, 0).setData(Qt.UserRole, snapshot)
        self.version_table.resizeRowsToContents()
        if versions:
            self.version_table.selectRow(0)

    def _show_version_detail(self) -> None:
        row = self.version_table.currentRow()
        if row < 0 or self.version_table.item(row, 0) is None:
            self.version_detail.clear()
            return
        snapshot = self.version_table.item(row, 0).data(Qt.UserRole)
        if not isinstance(snapshot, dict):
            self.version_detail.clear()
            return
        lines = [
            f"岗位：{snapshot.get('job_title') or '-'}",
            f"部门：{snapshot.get('department') or '-'}",
            f"负责人：{snapshot.get('hiring_manager') or '-'}",
            f"地点：{snapshot.get('location') or '-'}",
            f"目标人数：{snapshot.get('target_hires') or 1}",
            f"截止日期：{snapshot.get('recruitment_deadline') or '-'}",
            f"岗位说明：{snapshot.get('jd_text') or '-'}",
            f"必须条件：{self._join(snapshot.get('must_have')) or '-'}",
            f"加分项：{self._join(snapshot.get('nice_to_have')) or '-'}",
            f"风险提示：{self._join(snapshot.get('risk_flags')) or '-'}",
            f"排除项：{self._join(snapshot.get('exclusions')) or '-'}",
            f"面试核验：{self._join(snapshot.get('interview_checks')) or '-'}",
        ]
        self.version_detail.setPlainText("\n".join(lines))

    def profile_payload(self) -> dict[str, object]:
        try:
            evidence_policy = json.loads(self.evidence_policy_input.text().strip() or "{}")
        except json.JSONDecodeError:
            evidence_policy = {"_invalid": self.evidence_policy_input.text().strip()}
        return {
            "id": self.current_profile_id,
            "job_title": self.job_title_input.text().strip(),
            "department": self.department_input.text().strip(),
            "hiring_manager": self.hiring_manager_input.text().strip(),
            "location": self.location_input.text().strip(),
            "employment_type": self.employment_type_input.text().strip(),
            "experience_requirement": self.experience_input.text().strip(),
            "education_requirement": self.education_input.text().strip(),
            "target_hires": self.target_hires_input.value(),
            "recruitment_deadline": self.deadline_input.text().strip(),
            "priority": str(self.priority_combo.currentData() or "normal"),
            "status": str(self.status_combo.currentData() or "draft"),
            "jd_text": self.jd_input.toPlainText().strip(),
            "prompt_text": self.prompt_input.toPlainText().strip(),
            "prompt_source": "custom" if self.prompt_input.toPlainText().strip() else "generated",
            "must_have": self._items(self.must_have_input.text()),
            "nice_to_have": self._items(self.nice_to_have_input.text()),
            "risk_flags": self._items(self.risk_flags_input.text()),
            "exclusions": self._items(self.exclusions_input.text()),
            "interview_checks": self._items(self.interview_checks_input.text()),
            "evidence_policy": evidence_policy,
        }

    def _emit_save(self) -> None:
        payload = self.profile_payload()
        if not payload["job_title"] or not payload["jd_text"]:
            self.message_label.setText("岗位名称和岗位说明 JD 为必填项。")
            return
        if "_invalid" in dict(payload["evidence_policy"]):
            self.message_label.setText("证据策略必须是有效 JSON。")
            return
        self.save_requested.emit(payload)

    def _emit_selected(self) -> None:
        row = self.profile_table.currentRow()
        if row < 0 or self.profile_table.item(row, 0) is None:
            return
        profile_id = self.profile_table.item(row, 0).data(Qt.UserRole)
        if profile_id is not None:
            self.profile_selected.emit(int(profile_id))

    def _emit_clone(self) -> None:
        if self.current_profile_id is None:
            return
        title, accepted = QInputDialog.getText(
            self,
            "复制岗位档案",
            "新岗位名称",
            text=f"{self.job_title_input.text().strip()} - 副本",
        )
        if accepted and title.strip():
            self.clone_requested.emit(self.current_profile_id, title.strip())

    def _emit_status_change(self) -> None:
        if self.current_profile_id is not None:
            self.status_change_requested.emit(
                self.current_profile_id,
                str(self.status_combo.currentData() or "draft"),
            )

    def _set_status_choices(self, current: str) -> None:
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        for status in JOB_STATUS_CHOICES.get(current, (current,)):
            self.status_combo.addItem(JOB_STATUS_LABELS.get(status, status), status)
        self.status_combo.setCurrentIndex(max(0, self.status_combo.findData(current)))
        self.status_combo.blockSignals(False)

    @staticmethod
    def _items(text: str) -> list[str]:
        return [item.strip() for item in text.replace(";", "；").split("；") if item.strip()]

    @staticmethod
    def _join(value: object) -> str:
        return "；".join(str(item) for item in value) if isinstance(value, list) else ""
