from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.pages.dashboard import DashboardPage


class DashboardPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_funnel_detail_shows_manual_review_decision(self) -> None:
        page = DashboardPage()
        self.addCleanup(page.deleteLater)

        page.set_funnel_detail_candidates(
            [
                {
                    "name": "Dana",
                    "latest_rating": "SSR",
                    "funnel_status": "replied",
                    "human_decision": "manual_review_passed",
                    "job_track": "SaaS销售",
                    "city": "深圳",
                    "years_experience": 5,
                    "recruitment_status": "replied",
                    "reached_at": "2026-06-25T10:00:00",
                }
            ]
        )

        self.assertEqual(page.funnel_detail_table.columnCount(), 9)
        self.assertEqual(page.funnel_detail_table.horizontalHeaderItem(3).text(), "复核结论")
        self.assertEqual(page.funnel_detail_table.item(0, 3).text(), "人工复核通过")


if __name__ == "__main__":
    unittest.main()
