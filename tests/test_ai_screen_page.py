from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ai.prompt_manager import PromptManager
from ui.pages.ai_screen import AIScreenPage


class AIScreenPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_status_filter_keeps_failed_task_id_and_failure_detail(self) -> None:
        page = AIScreenPage(PromptManager(Path("assets/prompts")))
        self.addCleanup(page.deleteLater)
        page.show_results(
            [
                {
                    "task_id": 101,
                    "candidate_id": 1,
                    "name": "Failed Candidate",
                    "task_status": "failed",
                    "task_error": "network down",
                    "retry_count": 2,
                    "max_retry_count": 2,
                    "task_updated_at": "2026-06-25T10:00:00",
                },
                {
                    "task_id": 102,
                    "candidate_id": 2,
                    "name": "Completed Candidate",
                    "task_status": "success",
                    "rating": "SSR",
                    "persona": "Strong match",
                    "retry_count": 0,
                    "max_retry_count": 2,
                    "task_updated_at": "2026-06-25T10:01:00",
                },
            ]
        )

        self.assertEqual(page.result_table.rowCount(), 2)

        failed_index = page.result_status_filter_combo.findData("failed")
        page.result_status_filter_combo.setCurrentIndex(failed_index)

        self.assertEqual(page.result_table.rowCount(), 1)
        page.result_table.selectRow(0)
        self.assertEqual(page.selected_task_id(), 101)
        self.assertEqual(page.result_table.item(0, 3).text(), "2/2")
        self.assertEqual(page.result_table.item(0, 4).text(), "2026-06-25T10:00:00")
        self.assertIn("network down", page.result_table.item(0, 5).text())
        self.assertEqual(page.result_table.item(0, 0).data(Qt.UserRole), 101)


if __name__ == "__main__":
    unittest.main()
