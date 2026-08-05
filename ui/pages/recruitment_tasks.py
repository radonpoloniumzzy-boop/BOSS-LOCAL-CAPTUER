from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


STATUS_LABELS = {
    "ready": "待启动",
    "running": "执行中",
    "waiting_user": "等待人工",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


class RecruitmentTasksPage(QWidget):
    save_requested = Signal(object)
    task_selected = Signal(int)
    start_requested = Signal(int)
    status_requested = Signal(int, str)
    open_platform_requested = Signal(int)
    open_export_requested = Signal(str)
    open_export_folder_requested = Signal()
    extension_action_requested = Signal(str, int)

    def __init__(self) -> None:
        super().__init__()
        self.current_task_id: int | None = None
        self._tasks: list[dict[str, object]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        self.workbench_hint = QLabel(
            "双窗口工作台：日常只保留“招聘平台 + HR 工作台”。插件只在启动采集时点击一次，"
            "AI 初筛、任务进度和导出记录都留在本页。"
        )
        self.workbench_hint.setWordWrap(True)
        root.addWidget(self.workbench_hint)

        splitter = QSplitter()
        list_group = QGroupBox("招聘任务")
        list_layout = QVBoxLayout(list_group)
        self.task_table = QTableWidget(0, 5)
        self.task_table.setHorizontalHeaderLabels(["任务", "岗位", "平台", "状态", "当前步骤"])
        self.task_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.task_table.horizontalHeader().setStretchLastSection(True)
        self.new_button = QPushButton("新建任务")
        list_layout.addWidget(self.task_table, 1)
        list_layout.addWidget(self.new_button)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        form_group = QGroupBox("任务目标与资源")
        form = QFormLayout(form_group)
        self.name_input = QLineEdit()
        self.profile_combo = QComboBox()
        self.platform_combo = QComboBox()
        self.platform_combo.addItem("BOSS 直聘", "boss")
        self.platform_combo.addItem("猎聘", "liepin")
        self.source_url_input = QLineEdit("https://www.zhipin.com/web/geek/recommend")
        self.target_candidates_input = QSpinBox()
        self.target_candidates_input.setRange(0, 100000)
        self.target_ssr_input = QSpinBox()
        self.target_ssr_input.setRange(0, 10000)
        self.minimum_rating_combo = QComboBox()
        for rating in ["SSR", "SR", "R"]:
            self.minimum_rating_combo.addItem(rating, rating)
        self.view_quota_input = QSpinBox()
        self.view_quota_input.setRange(0, 100000)
        self.greeting_quota_input = QSpinBox()
        self.greeting_quota_input.setRange(0, 100000)
        form.addRow("任务名称", self.name_input)
        form.addRow("岗位档案", self.profile_combo)
        form.addRow("招聘平台", self.platform_combo)
        form.addRow("来源页面", self.source_url_input)
        form.addRow("目标候选人数", self.target_candidates_input)
        form.addRow("SSR 目标", self.target_ssr_input)
        form.addRow("最低目标评级", self.minimum_rating_combo)
        form.addRow("查看额度", self.view_quota_input)
        form.addRow("打招呼额度", self.greeting_quota_input)

        actions = QHBoxLayout()
        self.save_button = QPushButton("保存任务")
        self.start_button = QPushButton("启动任务")
        self.pause_button = QPushButton("暂停")
        self.complete_button = QPushButton("完成")
        self.cancel_button = QPushButton("取消任务")
        self.open_platform_button = QPushButton("打开招聘平台")
        for button in [self.save_button, self.start_button, self.pause_button, self.complete_button, self.cancel_button, self.open_platform_button]:
            actions.addWidget(button)
        editor_layout.addWidget(form_group)
        editor_layout.addLayout(actions)

        self.summary_label = QLabel("尚未选择任务")
        self.summary_label.setWordWrap(True)
        editor_layout.addWidget(self.summary_label)

        plugin_group = QGroupBox("插件远程控制｜试用")
        plugin_layout = QVBoxLayout(plugin_group)
        self.plugin_control_hint = QLabel(
            "在这里向 Chrome 插件发送采集指令；插件原按钮仍可使用，两边互不删除。"
        )
        self.plugin_control_hint.setWordWrap(True)
        plugin_layout.addWidget(self.plugin_control_hint)
        plugin_actions = QGridLayout()
        self.plugin_auto_button = QPushButton("AUTO 采集 + AI 初筛")
        self.plugin_collect_current_button = QPushButton("采集当前已加载")
        self.plugin_collect_auto_button = QPushButton("自动滚动采集")
        self.plugin_pause_button = QPushButton("暂停滚动")
        self.plugin_stop_button = QPushButton("停止采集")
        self._plugin_buttons = [
            self.plugin_auto_button,
            self.plugin_collect_current_button,
            self.plugin_collect_auto_button,
            self.plugin_pause_button,
            self.plugin_stop_button,
        ]
        for index, button in enumerate(self._plugin_buttons):
            plugin_actions.addWidget(button, index // 3, index % 3)
        plugin_layout.addLayout(plugin_actions)
        self.plugin_status_label = QLabel("等待选择招聘任务")
        self.plugin_status_label.setWordWrap(True)
        plugin_layout.addWidget(self.plugin_status_label)
        editor_layout.addWidget(plugin_group)

        export_group = QGroupBox("最近导出｜无需常驻文件夹窗口")
        export_layout = QVBoxLayout(export_group)
        self.export_table = QTableWidget(0, 4)
        self.export_table.setHorizontalHeaderLabels(["时间", "格式", "人数", "文件"])
        self.export_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.export_table.horizontalHeader().setStretchLastSection(True)
        export_actions = QHBoxLayout()
        self.open_export_button = QPushButton("打开选中导出")
        self.open_export_folder_button = QPushButton("打开导出文件夹")
        export_actions.addWidget(self.open_export_button)
        export_actions.addWidget(self.open_export_folder_button)
        export_actions.addStretch(1)
        export_layout.addWidget(self.export_table)
        export_layout.addLayout(export_actions)
        editor_layout.addWidget(export_group, 1)

        splitter.addWidget(list_group)
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        self.new_button.clicked.connect(self.clear_task)
        self.save_button.clicked.connect(self._emit_save)
        self.start_button.clicked.connect(lambda: self.current_task_id is not None and self.start_requested.emit(self.current_task_id))
        self.pause_button.clicked.connect(lambda: self.current_task_id is not None and self.status_requested.emit(self.current_task_id, "paused"))
        self.complete_button.clicked.connect(lambda: self.current_task_id is not None and self.status_requested.emit(self.current_task_id, "completed"))
        self.cancel_button.clicked.connect(lambda: self.current_task_id is not None and self.status_requested.emit(self.current_task_id, "cancelled"))
        self.open_platform_button.clicked.connect(lambda: self.current_task_id is not None and self.open_platform_requested.emit(self.current_task_id))
        self.open_export_button.clicked.connect(self._emit_open_export)
        self.open_export_folder_button.clicked.connect(self.open_export_folder_requested.emit)
        self.plugin_auto_button.clicked.connect(
            lambda: self._emit_extension_action("automation_auto")
        )
        self.plugin_collect_current_button.clicked.connect(
            lambda: self._emit_extension_action("collect_current")
        )
        self.plugin_collect_auto_button.clicked.connect(
            lambda: self._emit_extension_action("collect_auto")
        )
        self.plugin_pause_button.clicked.connect(
            lambda: self._emit_extension_action("pause_scroll")
        )
        self.plugin_stop_button.clicked.connect(
            lambda: self._emit_extension_action("stop_capture")
        )
        self.task_table.itemSelectionChanged.connect(self._emit_selected)
        self.platform_combo.currentIndexChanged.connect(self._platform_changed)
        self.clear_task()

    def set_job_profiles(self, rows: list[dict[str, object]]) -> None:
        current = self.profile_combo.currentData()
        self.profile_combo.clear()
        for row in rows:
            self.profile_combo.addItem(f"{row['job_title']} · V{row.get('version', 1)}", int(row["id"]))
        index = self.profile_combo.findData(current)
        self.profile_combo.setCurrentIndex(max(0, index))

    def set_tasks(self, rows: list[dict[str, object]]) -> None:
        self._tasks = [dict(row) for row in rows]
        self.task_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                row.get("name"), row.get("role_title"), row.get("platform"),
                STATUS_LABELS.get(str(row.get("status")), row.get("status")), row.get("current_step"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or "-"))
                if column == 0:
                    item.setData(256, int(row["id"]))
                self.task_table.setItem(index, column, item)

    def show_task(self, row: dict[str, object], summary: dict[str, object], exports: list[dict[str, object]]) -> None:
        self.current_task_id = int(row["id"])
        self.name_input.setText(str(row.get("name") or ""))
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(int(row["role_id"]))))
        self.profile_combo.setEnabled(False)
        self.platform_combo.setCurrentIndex(max(0, self.platform_combo.findData(str(row.get("platform") or "boss"))))
        self.source_url_input.setText(str(row.get("source_url") or ""))
        self.target_candidates_input.setValue(int(row.get("target_candidates") or 0))
        self.target_ssr_input.setValue(int(row.get("target_ssr") or 0))
        self.minimum_rating_combo.setCurrentIndex(max(0, self.minimum_rating_combo.findData(str(row.get("minimum_rating") or "SR"))))
        self.view_quota_input.setValue(int(row.get("view_quota") or 0))
        self.greeting_quota_input.setValue(int(row.get("greeting_quota") or 0))
        self.summary_label.setText(
            f"岗位版本 V{row['profile_version']}｜批次 {summary.get('batch_count', 0)}｜"
            f"候选人 {summary.get('candidate_count', 0)}/{row.get('target_candidates', 0)}｜"
            f"AI 运行 {summary.get('run_count', 0)}｜导出 {summary.get('export_count', 0)}"
        )
        self._set_exports(exports)
        editable = str(row.get("status") or "ready") == "ready"
        controls_enabled = str(row.get("status") or "ready") == "running"
        for button in self._plugin_buttons:
            button.setEnabled(controls_enabled)
        self.plugin_status_label.setText(
            "插件控制已就绪" if controls_enabled else "请先启动招聘任务"
        )
        self.save_button.setEnabled(editable)
        for widget in [
            self.name_input, self.platform_combo, self.source_url_input,
            self.target_candidates_input, self.target_ssr_input,
            self.minimum_rating_combo, self.view_quota_input, self.greeting_quota_input,
        ]:
            widget.setEnabled(editable)

    def clear_task(self) -> None:
        self.current_task_id = None
        self.profile_combo.setEnabled(True)
        self.save_button.setEnabled(True)
        for widget in [
            self.name_input, self.platform_combo, self.source_url_input,
            self.target_candidates_input, self.target_ssr_input,
            self.minimum_rating_combo, self.view_quota_input, self.greeting_quota_input,
        ]:
            widget.setEnabled(True)
        self.name_input.clear()
        self.target_candidates_input.setValue(0)
        self.target_ssr_input.setValue(0)
        self.view_quota_input.setValue(0)
        self.greeting_quota_input.setValue(0)
        self.summary_label.setText("新任务会固定当前岗位版本。")
        for button in self._plugin_buttons:
            button.setEnabled(False)
        self.plugin_status_label.setText("等待选择招聘任务")
        self.export_table.setRowCount(0)

    def show_extension_command_status(self, message: str) -> None:
        self.plugin_status_label.setText(str(message or "等待插件响应"))

    def _emit_extension_action(self, action: str) -> None:
        if self.current_task_id is None:
            self.plugin_status_label.setText("请先选择并启动招聘任务")
            return
        self.extension_action_requested.emit(action, self.current_task_id)

    def _emit_save(self) -> None:
        if not self.name_input.text().strip() or self.profile_combo.currentData() is None:
            self.summary_label.setText("请填写任务名称并选择岗位。")
            return
        self.save_requested.emit({
            "id": self.current_task_id,
            "name": self.name_input.text().strip(),
            "role_id": int(self.profile_combo.currentData()),
            "platform": str(self.platform_combo.currentData()),
            "source_url": self.source_url_input.text().strip(),
            "target_candidates": self.target_candidates_input.value(),
            "target_ssr": self.target_ssr_input.value(),
            "minimum_rating": str(self.minimum_rating_combo.currentData()),
            "view_quota": self.view_quota_input.value(),
            "greeting_quota": self.greeting_quota_input.value(),
        })

    def _emit_selected(self) -> None:
        row = self.task_table.currentRow()
        if row >= 0 and self.task_table.item(row, 0):
            self.task_selected.emit(int(self.task_table.item(row, 0).data(256)))

    def _set_exports(self, rows: list[dict[str, object]]) -> None:
        self.export_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [row.get("created_at"), row.get("export_format"), row.get("row_count"), row.get("file_path")]
            for column, value in enumerate(values):
                self.export_table.setItem(row_index, column, QTableWidgetItem(str(value or "-")))

    def _emit_open_export(self) -> None:
        row = self.export_table.currentRow()
        if row >= 0 and self.export_table.item(row, 3):
            self.open_export_requested.emit(self.export_table.item(row, 3).text())

    def _platform_changed(self) -> None:
        if self.platform_combo.currentData() == "liepin":
            self.source_url_input.setText("https://lpt.liepin.com/recommend")
        elif not self.source_url_input.text() or "liepin.com" in self.source_url_input.text():
            self.source_url_input.setText("https://www.zhipin.com/web/geek/recommend")
