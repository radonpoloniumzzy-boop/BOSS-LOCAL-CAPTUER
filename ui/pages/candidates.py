from __future__ import annotations

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


class CandidatesPage(QWidget):
    refresh_requested = Signal()
    export_requested = Signal(object)
    candidate_selected = Signal(int)

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
        filter_layout.addWidget(self.refresh_button)
        filter_layout.addWidget(self.export_csv_button)
        filter_layout.addWidget(self.export_jsonl_button)
        filter_layout.addWidget(self.export_markdown_button)

        splitter = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["姓名", "活跃状态", "期望薪资", "岗位", "更新时间", "出现批次"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)

        detail_group = QGroupBox("候选人详情")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text)
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
        self.job_title_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.batch_combo.currentIndexChanged.connect(self.refresh_requested.emit)
        self.table.itemSelectionChanged.connect(self._emit_selection)

    def current_filters(self) -> dict[str, object]:
        return {
            "keyword": self.search_input.text().strip(),
            "job_title": self.job_title_combo.currentData(),
            "batch_id": self.batch_combo.currentData(),
        }

    def set_candidates(self, rows: list[dict[str, object]]) -> None:
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("name", ""),
                row.get("active_status", ""),
                row.get("expected_salary", ""),
                row.get("job_title", ""),
                row.get("updated_at", ""),
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

    def set_filter_options(self, job_titles: list[str], batches: list[dict[str, object]]) -> None:
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

    def show_candidate_detail(self, detail: dict[str, object] | None) -> None:
        if not detail:
            self.detail_text.setPlainText("未找到候选人详情。")
            return

        candidate = detail["candidate"]
        appearances = detail["appearances"]
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
            "",
            "批次出现记录：",
        ]
        for appearance in appearances:
            lines.append(
                f"- 批次 #{appearance['batch_id']} | {appearance['job_title']} | "
                f"{appearance['capture_time']} | {self.translate_status(str(appearance['status']))}"
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

    @staticmethod
    def translate_status(status: str) -> str:
        return STATUS_LABELS.get(status, status)
