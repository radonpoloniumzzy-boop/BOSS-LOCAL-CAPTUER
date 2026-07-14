from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.config import ConfigService
from ui.main_window import MainWindow
from ui.pages.candidates import CandidatesPage


class CompactCandidatesPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_advanced_filters_are_progressively_disclosed(self) -> None:
        page = CandidatesPage()

        self.assertTrue(page.advanced_filters_container.isHidden())
        page.advanced_filters_button.click()
        self.assertFalse(page.advanced_filters_container.isHidden())
        page.advanced_filters_button.click()
        self.assertTrue(page.advanced_filters_container.isHidden())

    def test_default_table_only_shows_decision_columns(self) -> None:
        page = CandidatesPage()

        visible_columns = [
            index for index in range(page.table.columnCount()) if not page.table.isColumnHidden(index)
        ]

        self.assertEqual(visible_columns, [0, 1, 2, 3, 7, 8, 10])

    def test_compact_export_menu_keeps_all_export_commands(self) -> None:
        page = CandidatesPage()
        exports: list[str] = []
        page.export_requested.connect(lambda payload: exports.append(str(payload["export_format"])))

        for action in page.export_button.menu().actions():
            action.trigger()

        self.assertEqual(exports, ["csv", "jsonl", "markdown"])

    def test_narrow_page_opens_candidate_detail_on_demand(self) -> None:
        page = CandidatesPage()
        page.resize(780, 600)
        page.show()
        self.app.processEvents()

        self.assertTrue(page.detail_group.isHidden())
        page.detail_toggle_button.click()
        self.app.processEvents()
        self.assertFalse(page.detail_group.isHidden())
        self.assertLessEqual(page.minimumSizeHint().width(), 780)


class CompactMainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_fits_a_760_by_640_split_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_service = ConfigService(Path(tmp_dir))
            config = config_service.default_config()
            config.local_api_port = 0
            config_service.save(config)

            with patch("ui.main_window.ConfigService", return_value=config_service):
                window = MainWindow()
                try:
                    window.resize(760, 640)
                    window.show()
                    self.app.processEvents()

                    self.assertLessEqual(window.width(), 760)
                    self.assertLessEqual(window.height(), 640)
                    self.assertLessEqual(window.minimumSize().width(), 720)
                    self.assertLessEqual(window.minimumSize().height(), 560)
                    self.assertTrue(window.log_dock.isHidden())
                    self.assertEqual(window.navigation_container.width(), 52)
                    window.navigation_toggle.click()
                    self.app.processEvents()
                    self.assertEqual(window.navigation_container.width(), 132)
                    window._set_navigation_collapsed(True)
                    window.navigation.setCurrentRow(2)
                    self.app.processEvents()
                    candidate_scroll = window._page_scroll_areas[2]
                    self.assertLessEqual(
                        window.candidates_page.width(), candidate_scroll.viewport().width()
                    )
                    self.assertEqual(candidate_scroll.horizontalScrollBar().maximum(), 0)
                finally:
                    window.close()
                    self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
