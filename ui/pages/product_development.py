from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class ProductDevelopmentPage(QWidget):
    feedback_submit_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._plan: dict[str, object] = {}
        self._modules: list[dict[str, object]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        title = QLabel("产品建设")
        title.setObjectName("pageTitle")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        subtitle = QLabel("把当前能力、目标形态、开发路径和使用反馈放在同一张地图上。")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        summary_row = QHBoxLayout()
        self.version_value = self._summary_card(summary_row, "当前版本")
        self.phase_value = self._summary_card(summary_row, "当前阶段")
        self.updated_value = self._summary_card(summary_row, "方案更新")
        self.readiness_value = self._summary_card(summary_row, "模块状态")
        root.addLayout(summary_row)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_roadmap_tab(), "产品路线")
        self.tabs.addTab(self._build_modules_tab(), "功能模块")
        self.tabs.addTab(self._build_versions_tab(), "版本记录")
        self.tabs.addTab(self._build_feedback_tab(), "使用反馈")
        root.addWidget(self.tabs, 1)

    @staticmethod
    def _summary_card(layout: QHBoxLayout, label: str) -> QLabel:
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        caption = QLabel(label)
        caption.setStyleSheet("color: #64748b;")
        value = QLabel("-")
        value.setWordWrap(True)
        value.setStyleSheet("font-size: 16px; font-weight: 650;")
        card_layout.addWidget(caption)
        card_layout.addWidget(value)
        layout.addWidget(card, 1)
        return value

    def _build_roadmap_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 10, 0, 0)
        hint = QLabel("路线按可验证的产品阶段排列；状态只描述成熟度，不使用虚假的完成百分比。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.roadmap_table = self._table(["阶段", "目标结果", "状态", "验收信号"])
        layout.addWidget(self.roadmap_table, 1)
        return container

    def _build_modules_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 10, 0, 0)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("成熟度"))
        self.module_status_filter = QComboBox()
        self.module_status_filter.addItem("全部状态", "")
        filter_row.addWidget(self.module_status_filter)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        splitter = QSplitter()
        self.module_table = self._table(["功能模块", "状态", "下一步"])
        self.module_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.module_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.module_detail = QTextBrowser()
        self.module_detail.setOpenExternalLinks(False)
        self.module_detail.setPlaceholderText("选择一个功能模块查看当前能力、理想形态和开发流程。")
        splitter.addWidget(self.module_table)
        splitter.addWidget(self.module_detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.module_status_filter.currentIndexChanged.connect(self._render_modules)
        self.module_table.itemSelectionChanged.connect(self._show_selected_module)
        return container

    def _build_versions_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 10, 0, 0)
        hint = QLabel("记录已经进入产品的变化、验证状态和边界，避免把方案设想误当成现成功能。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.version_table = self._table(["版本", "日期", "状态", "主要变化"])
        layout.addWidget(self.version_table, 1)
        return container

    def _build_feedback_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 10, 0, 0)

        form_group = QGroupBox("提交使用反馈")
        form = QFormLayout(form_group)
        self.feedback_type_combo = QComboBox()
        self.feedback_type_combo.addItems(["功能建议", "使用问题", "数据问题", "流程改进"])
        self.feedback_module_combo = QComboBox()
        self.feedback_module_combo.addItem("整体产品")
        self.feedback_impact_combo = QComboBox()
        self.feedback_impact_combo.addItems(["阻碍主要流程", "影响效率", "一般影响", "体验建议"])
        self.feedback_description_input = QPlainTextEdit()
        self.feedback_description_input.setPlaceholderText("请描述发生了什么、在哪一步遇到问题。")
        self.feedback_description_input.setMaximumHeight(90)
        self.feedback_expected_input = QPlainTextEdit()
        self.feedback_expected_input.setPlaceholderText("你希望产品怎样处理或呈现？")
        self.feedback_expected_input.setMaximumHeight(70)
        form.addRow("反馈类型", self.feedback_type_combo)
        form.addRow("相关模块", self.feedback_module_combo)
        form.addRow("影响程度", self.feedback_impact_combo)
        form.addRow("反馈内容", self.feedback_description_input)
        form.addRow("期望结果", self.feedback_expected_input)

        action_row = QHBoxLayout()
        self.feedback_status_label = QLabel("反馈保存在当前电脑的项目数据目录中。")
        self.feedback_status_label.setWordWrap(True)
        self.feedback_submit_button = QPushButton("提交反馈")
        self.feedback_submit_button.setProperty("primary", True)
        action_row.addWidget(self.feedback_status_label, 1)
        action_row.addWidget(self.feedback_submit_button)

        self.feedback_table = self._table(
            ["编号", "时间", "类型", "模块", "影响", "状态", "内容", "期望结果"]
        )
        layout.addWidget(form_group)
        layout.addLayout(action_row)
        layout.addWidget(QLabel("反馈记录"))
        layout.addWidget(self.feedback_table, 1)
        self.feedback_submit_button.clicked.connect(self._emit_feedback)
        return container

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def set_snapshot(self, snapshot: dict[str, object]) -> None:
        self._plan = dict(snapshot.get("plan") or {})
        self._modules = [dict(item) for item in self._plan.get("modules", [])]
        product = dict(self._plan.get("product") or {})
        self.version_value.setText(str(product.get("current_version") or "未标记"))
        self.phase_value.setText(str(product.get("phase") or "未标记"))
        self.updated_value.setText(str(product.get("updated_at") or "未标记"))
        self.summary_label.setText(str(product.get("summary") or ""))

        status_counts: dict[str, int] = {}
        for module in self._modules:
            status = str(module.get("status") or "未标记")
            status_counts[status] = status_counts.get(status, 0) + 1
        self.readiness_value.setText(
            " · ".join(f"{status} {count}" for status, count in status_counts.items()) or "暂无模块"
        )

        selected_status = self.module_status_filter.currentData()
        self.module_status_filter.blockSignals(True)
        self.module_status_filter.clear()
        self.module_status_filter.addItem("全部状态", "")
        for status in self._plan.get("status_options", []):
            self.module_status_filter.addItem(str(status), str(status))
        selected_index = self.module_status_filter.findData(selected_status)
        self.module_status_filter.setCurrentIndex(max(0, selected_index))
        self.module_status_filter.blockSignals(False)

        self.feedback_module_combo.clear()
        self.feedback_module_combo.addItem("整体产品")
        self.feedback_module_combo.addItems([str(item.get("name") or "未命名模块") for item in self._modules])
        if self._modules:
            self.feedback_module_combo.setCurrentIndex(1)

        self._render_roadmap()
        self._render_modules()
        self._render_versions()
        self.set_feedback([dict(item) for item in snapshot.get("feedback", [])])

    def _render_roadmap(self) -> None:
        items = [dict(item) for item in self._plan.get("roadmap", [])]
        self.roadmap_table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = [
                item.get("stage"),
                item.get("goal"),
                item.get("status"),
                self._join_lines(item.get("acceptance")),
            ]
            for column, value in enumerate(values):
                self.roadmap_table.setItem(row, column, QTableWidgetItem(str(value or "-")))
        self.roadmap_table.resizeRowsToContents()

    def _render_modules(self) -> None:
        status_filter = str(self.module_status_filter.currentData() or "")
        modules = [
            item for item in self._modules if not status_filter or item.get("status") == status_filter
        ]
        self.module_table.setRowCount(len(modules))
        for row, item in enumerate(modules):
            name_item = QTableWidgetItem(str(item.get("name") or "未命名模块"))
            name_item.setData(Qt.UserRole, str(item.get("id") or ""))
            self.module_table.setItem(row, 0, name_item)
            self.module_table.setItem(row, 1, QTableWidgetItem(str(item.get("status") or "-")))
            self.module_table.setItem(row, 2, QTableWidgetItem(str(item.get("next_step") or "-")))
        self.module_table.resizeRowsToContents()
        if modules:
            self.module_table.selectRow(0)
        else:
            self.module_detail.clear()

    def _show_selected_module(self) -> None:
        row = self.module_table.currentRow()
        if row < 0 or self.module_table.item(row, 0) is None:
            return
        module_id = str(self.module_table.item(row, 0).data(Qt.UserRole) or "")
        module = next((item for item in self._modules if str(item.get("id") or "") == module_id), None)
        if module is None:
            return
        sections = [
            ("当前能力", module.get("current")),
            ("理想形态", module.get("ideal")),
            ("已知边界", module.get("limitations")),
            ("下一步", module.get("next_step")),
            ("功能流程", module.get("flow")),
            ("验收标准", module.get("acceptance")),
        ]
        body = "".join(
            f"<h3>{escape(label)}</h3><p>{self._html_value(value)}</p>" for label, value in sections
        )
        self.module_detail.setHtml(
            f"<h2>{escape(str(module.get('name') or '未命名模块'))}</h2>"
            f"<p><b>成熟度：</b>{escape(str(module.get('status') or '-'))}</p>{body}"
        )

    def _render_versions(self) -> None:
        items = [dict(item) for item in self._plan.get("versions", [])]
        self.version_table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = [
                item.get("version"),
                item.get("date"),
                item.get("status"),
                self._join_lines(item.get("changes")),
            ]
            for column, value in enumerate(values):
                self.version_table.setItem(row, column, QTableWidgetItem(str(value or "-")))
        self.version_table.resizeRowsToContents()

    def set_feedback(self, items: list[dict[str, object]]) -> None:
        self.feedback_table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = [
                item.get("id"),
                item.get("created_at"),
                item.get("type"),
                item.get("module"),
                item.get("impact"),
                item.get("status"),
                item.get("description"),
                item.get("expected"),
            ]
            for column, value in enumerate(values):
                self.feedback_table.setItem(row, column, QTableWidgetItem(str(value or "-")))
        self.feedback_table.resizeRowsToContents()

    def feedback_saved(self, items: list[dict[str, object]]) -> None:
        self.set_feedback(items)
        self.feedback_description_input.clear()
        self.feedback_expected_input.clear()
        self.feedback_status_label.setText("反馈已保存，可以继续提交新的使用记录。")

    def show_feedback_error(self, message: str) -> None:
        self.feedback_status_label.setText(message)

    def _emit_feedback(self) -> None:
        description = self.feedback_description_input.toPlainText().strip()
        if not description:
            self.show_feedback_error("请先填写反馈内容。")
            return
        self.feedback_submit_requested.emit(
            {
                "type": self.feedback_type_combo.currentText(),
                "module": self.feedback_module_combo.currentText(),
                "impact": self.feedback_impact_combo.currentText(),
                "description": description,
                "expected": self.feedback_expected_input.toPlainText().strip(),
            }
        )

    @staticmethod
    def _join_lines(value: object) -> str:
        if isinstance(value, list):
            return "\n".join(f"• {item}" for item in value)
        return str(value or "")

    @classmethod
    def _html_value(cls, value: object) -> str:
        if isinstance(value, list):
            return "<br>".join(f"• {escape(str(item))}" for item in value)
        return escape(str(value or "-"))
