from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.main_window import MainWindow


class OpenExportFolderTest(unittest.TestCase):
    def test_handler_creates_and_opens_configured_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_dir = Path(tmp_dir) / "custom" / "exports"
            status_bar = Mock()
            window = SimpleNamespace(
                config=SimpleNamespace(default_export_dir=str(export_dir)),
                config_service=SimpleNamespace(default_export_dir=Path(tmp_dir) / "fallback"),
                logger=Mock(),
                statusBar=Mock(return_value=status_bar),
            )

            with patch("ui.main_window.open_local_folder", return_value=True) as open_folder:
                MainWindow.handle_open_export_folder(window)

            self.assertTrue(export_dir.is_dir())
            open_folder.assert_called_once_with(export_dir)
            status_bar.showMessage.assert_called_once_with(
                f"已打开导出文件夹：{export_dir}"
            )

    def test_handler_reports_system_open_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_dir = Path(tmp_dir) / "exports"
            window = SimpleNamespace(
                config=SimpleNamespace(default_export_dir=str(export_dir)),
                config_service=SimpleNamespace(default_export_dir=Path(tmp_dir) / "fallback"),
                logger=Mock(),
                statusBar=Mock(),
            )

            with (
                patch("ui.main_window.open_local_folder", return_value=False),
                patch("ui.main_window.QMessageBox.warning") as warning,
            ):
                MainWindow.handle_open_export_folder(window)

            warning.assert_called_once()
            self.assertEqual(warning.call_args.args[1], "无法打开导出文件夹")
            self.assertIn(str(export_dir), warning.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
