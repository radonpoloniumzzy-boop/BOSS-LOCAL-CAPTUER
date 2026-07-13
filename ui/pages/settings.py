from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.models import DEFAULT_CSV_COLUMNS, AIProviderConfig, AppConfig


class SettingsPage(QWidget):
    save_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        base_group = QGroupBox("基础设置")
        base_form = QFormLayout(base_group)
        self.browser_path_input = self._create_path_row(base_form, "浏览器路径", "file")
        self.user_data_dir_input = self._create_path_row(base_form, "用户数据目录", "dir")
        self.export_dir_input = self._create_path_row(base_form, "导出目录", "dir")
        self.selectors_path_input = self._create_path_row(base_form, "选择器文件", "file")
        self.target_url_input = QLineEdit()
        self.job_title_input = QLineEdit()
        self.export_filename_template_input = QLineEdit()
        self.resume_filename_template_input = QLineEdit()
        self.local_api_port_input = QSpinBox()
        self.local_api_port_input.setRange(1024, 65535)
        self.local_api_token_input = QLineEdit()
        self.local_api_token_input.setReadOnly(True)
        self.copy_pairing_code_button = QPushButton("复制扩展连接码")
        token_row = QHBoxLayout()
        token_row.addWidget(self.local_api_token_input, 1)
        token_row.addWidget(self.copy_pairing_code_button)
        token_wrapper = QWidget()
        token_wrapper.setLayout(token_row)
        self.scroll_mode_combo = QComboBox()
        self.scroll_mode_combo.addItem("整页滚动", "page")
        self.scroll_mode_combo.addItem("固定步长", "fixed")
        self.scroll_step_input = QSpinBox()
        self.scroll_step_input.setRange(100, 5000)
        self.scroll_wait_input = QDoubleSpinBox()
        self.scroll_wait_input.setRange(0.2, 10.0)
        self.scroll_wait_input.setSingleStep(0.1)
        self.max_scroll_input = QSpinBox()
        self.max_scroll_input.setRange(1, 1000)
        self.no_new_stop_input = QSpinBox()
        self.no_new_stop_input.setRange(1, 30)
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.csv_columns_input = QLineEdit()

        base_form.addRow("目标链接", self.target_url_input)
        base_form.addRow("默认岗位名称", self.job_title_input)
        base_form.addRow("导出文件命名模板", self.export_filename_template_input)
        base_form.addRow("简历文件命名模板", self.resume_filename_template_input)
        base_form.addRow("本地接口端口", self.local_api_port_input)
        base_form.addRow("扩展连接", token_wrapper)
        base_form.addRow("滚动模式", self.scroll_mode_combo)
        base_form.addRow("滚动步长", self.scroll_step_input)
        base_form.addRow("滚动等待秒数", self.scroll_wait_input)
        base_form.addRow("最大滚动次数", self.max_scroll_input)
        base_form.addRow("无新增停止轮次", self.no_new_stop_input)
        base_form.addRow("日志级别", self.log_level_combo)
        base_form.addRow("CSV 列顺序", self.csv_columns_input)

        ai_group = QGroupBox("AI 默认配置")
        ai_form = QFormLayout(ai_group)
        self.ai_provider_input = QLineEdit()
        self.ai_model_input = QLineEdit()
        self.ai_api_base_input = QLineEdit()
        self.ai_api_key_env_input = QLineEdit()
        ai_form.addRow("服务商", self.ai_provider_input)
        ai_form.addRow("模型", self.ai_model_input)
        ai_form.addRow("API Base", self.ai_api_base_input)
        ai_form.addRow("API Key 环境变量", self.ai_api_key_env_input)

        self.save_button = QPushButton("保存设置")

        root_layout.addWidget(base_group)
        root_layout.addWidget(ai_group)
        root_layout.addWidget(self.save_button)
        root_layout.addStretch(1)

        self.save_button.clicked.connect(self._emit_save)
        self.copy_pairing_code_button.clicked.connect(self._copy_pairing_code)

    def load_config(self, config: AppConfig) -> None:
        default_job_title = config.default_job_title
        if default_job_title == "Boss Recommended Talent":
            default_job_title = "Boss 推荐牛人"

        self.browser_path_input.setText(config.browser_path)
        self.user_data_dir_input.setText(config.user_data_dir)
        self.export_dir_input.setText(config.default_export_dir)
        self.selectors_path_input.setText(config.selectors_path)
        self.target_url_input.setText(config.target_url)
        self.job_title_input.setText(default_job_title)
        self.export_filename_template_input.setText(config.export_filename_template)
        self.resume_filename_template_input.setText(config.resume_filename_template)
        self.local_api_port_input.setValue(config.local_api_port)
        self.local_api_token_input.setText(config.local_api_token)
        self.copy_pairing_code_button.setText("复制扩展连接码")
        self._set_combo_data(self.scroll_mode_combo, config.scroll_mode)
        self.scroll_step_input.setValue(config.scroll_step)
        self.scroll_wait_input.setValue(config.scroll_wait_seconds)
        self.max_scroll_input.setValue(config.max_scroll_count)
        self.no_new_stop_input.setValue(config.no_new_stop_rounds)
        self.log_level_combo.setCurrentText(config.log_level)
        self.csv_columns_input.setText(", ".join(config.csv_columns))
        self.ai_provider_input.setText(config.ai_provider.provider)
        self.ai_model_input.setText(config.ai_provider.model)
        self.ai_api_base_input.setText(config.ai_provider.api_base)
        self.ai_api_key_env_input.setText(config.ai_provider.api_key_env)

    def build_config(self) -> AppConfig:
        columns = [value.strip() for value in self.csv_columns_input.text().split(",") if value.strip()]
        return AppConfig(
            browser_path=self.browser_path_input.text().strip(),
            user_data_dir=self.user_data_dir_input.text().strip(),
            default_export_dir=self.export_dir_input.text().strip(),
            target_url=self.target_url_input.text().strip(),
            local_api_port=self.local_api_port_input.value(),
            local_api_token=self.local_api_token_input.text().strip(),
            scroll_mode=str(self.scroll_mode_combo.currentData() or "page"),
            scroll_step=self.scroll_step_input.value(),
            scroll_wait_seconds=self.scroll_wait_input.value(),
            max_scroll_count=self.max_scroll_input.value(),
            no_new_stop_rounds=self.no_new_stop_input.value(),
            default_job_title=self.job_title_input.text().strip() or "Boss 推荐牛人",
            export_filename_template=self.export_filename_template_input.text().strip()
            or "{job_title}_{date}_{time}_batch{batch_id}_{type}",
            resume_filename_template=self.resume_filename_template_input.text().strip()
            or "{candidate_name}_{job_title}_{date}_{original_name}",
            log_level=self.log_level_combo.currentText(),
            selectors_path=self.selectors_path_input.text().strip(),
            csv_columns=columns or list(DEFAULT_CSV_COLUMNS),
            ai_provider=AIProviderConfig(
                provider=self.ai_provider_input.text().strip() or "openai",
                model=self.ai_model_input.text().strip(),
                api_base=self.ai_api_base_input.text().strip(),
                api_key_env=self.ai_api_key_env_input.text().strip() or "OPENAI_API_KEY",
            ),
        )

    def _emit_save(self) -> None:
        config = self.build_config()
        if not Path(config.user_data_dir).parent.exists():
            QMessageBox.warning(self, "路径无效", "用户数据目录的上级目录不存在。")
            return
        self.save_requested.emit(config)

    def _copy_pairing_code(self) -> None:
        query = urlencode(
            {
                "apiBase": f"http://127.0.0.1:{self.local_api_port_input.value()}",
                "apiToken": self.local_api_token_input.text().strip(),
            }
        )
        QApplication.clipboard().setText(f"boss-local://pair?{query}")
        self.copy_pairing_code_button.setText("已复制连接码")

    def _create_path_row(self, form: QFormLayout, label: str, mode: str) -> QLineEdit:
        line_edit = QLineEdit()
        browse_button = QPushButton("浏览")
        row = QHBoxLayout()
        row.addWidget(line_edit, 1)
        row.addWidget(browse_button)
        wrapper = QWidget()
        wrapper.setLayout(row)
        form.addRow(label, wrapper)

        if mode == "file":
            browse_button.clicked.connect(lambda: self._pick_file(line_edit))
        else:
            browse_button.clicked.connect(lambda: self._pick_dir(line_edit))
        return line_edit

    def _pick_file(self, line_edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", line_edit.text() or str(Path.home()))
        if path:
            line_edit.setText(path)

    def _pick_dir(self, line_edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择目录", line_edit.text() or str(Path.home()))
        if path:
            line_edit.setText(path)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(0 if index < 0 else index)
