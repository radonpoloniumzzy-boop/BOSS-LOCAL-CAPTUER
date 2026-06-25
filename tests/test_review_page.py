from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.pages.review import ReviewPage


class ReviewPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_quick_pass_records_standard_manual_review_reason(self) -> None:
        page = ReviewPage()
        self.addCleanup(page.deleteLater)
        emitted: list[dict[str, object]] = []
        page.status_change_requested.connect(lambda payload: emitted.append(dict(payload)))
        page.set_rows(
            [
                {
                    "candidate_id": 7,
                    "role_id": 3,
                    "name": "Manual Candidate",
                    "role_title": "Java Engineer",
                    "latest_rating": "SSR",
                    "latest_confidence": "low",
                    "review_reason": "low_confidence",
                    "recommended_action": "manual_review",
                    "recruitment_status": "screened",
                }
            ]
        )

        page.table.selectRow(0)
        page.pass_review_button.click()

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["candidate_id"], 7)
        self.assertEqual(emitted[0]["role_id"], 3)
        self.assertEqual(emitted[0]["to_status"], "priority_outreach")
        self.assertEqual(emitted[0]["reason_code"], "manual_review_passed")
        self.assertIn("Manual review passed", emitted[0]["note"])
        self.assertEqual(page.summary_label.text(), "待复核 1")


if __name__ == "__main__":
    unittest.main()
