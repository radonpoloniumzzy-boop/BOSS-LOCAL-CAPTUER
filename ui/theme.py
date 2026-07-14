from __future__ import annotations

from PySide6.QtWidgets import QApplication


APP_STYLESHEET = """
QWidget {
    color: #20242a;
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #f5f6f8;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #dfe3e8;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: #38404a;
}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #cfd5dc;
    border-radius: 4px;
    padding: 4px 7px;
    selection-background-color: #0b7a5a;
    selection-color: #ffffff;
}
QLineEdit, QComboBox, QSpinBox {
    min-height: 24px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus,
QTableWidget:focus, QListWidget:focus {
    border: 2px solid #0b7a5a;
}
QPushButton, QToolButton {
    background: #ffffff;
    border: 1px solid #c9d0d8;
    border-radius: 4px;
    min-height: 28px;
    padding: 0 9px;
}
QPushButton:hover, QToolButton:hover {
    background: #eef2f4;
    border-color: #aeb7c1;
}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {
    background: #e1e8e8;
}
QPushButton:disabled, QToolButton:disabled {
    color: #9199a3;
    background: #eceff2;
    border-color: #dfe3e8;
}
QPushButton[primary="true"], QToolButton[primary="true"] {
    color: #ffffff;
    background: #0b7a5a;
    border-color: #0b7a5a;
    font-weight: 600;
}
QPushButton[primary="true"]:hover, QToolButton[primary="true"]:hover {
    background: #09684d;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafb;
    border: 1px solid #dfe3e8;
    gridline-color: #e7eaee;
    selection-background-color: #dcefe8;
    selection-color: #17201d;
}
QHeaderView::section {
    background: #edf0f3;
    color: #3a424b;
    border: 0;
    border-right: 1px solid #d9dee4;
    border-bottom: 1px solid #d3d9df;
    padding: 6px 7px;
    font-weight: 600;
}
QListWidget {
    background: #20252b;
    color: #d8dde3;
    border: 0;
    outline: 0;
    padding: 6px;
}
QListWidget::item {
    min-height: 36px;
    border-radius: 4px;
    padding: 0 7px;
}
QListWidget::item:hover {
    background: #303740;
}
QListWidget::item:selected {
    color: #ffffff;
    background: #0b7a5a;
}
QStatusBar {
    background: #eef1f4;
    color: #4d5661;
    border-top: 1px solid #d9dee4;
}
QSplitter::handle {
    background: #dfe3e8;
}
QSplitter::handle:horizontal {
    width: 4px;
}
QSplitter::handle:vertical {
    height: 4px;
}
QToolTip {
    color: #ffffff;
    background: #22272d;
    border: 1px solid #4b535d;
    padding: 4px;
}
"""


def apply_application_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
