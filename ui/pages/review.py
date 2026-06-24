from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ReviewPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel("V3 将在这里提供人工复核列表、状态流转、备注记录和历史检索。")
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)
