from __future__ import annotations

import os
import unittest
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.pages.next_actions import NextActionsPage


class NextActionsPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_prefills_candidate_saves_filters_completes_and_opens_subject(self) -> None:
        page = NextActionsPage()
        self.addCleanup(page.deleteLater)
        page.set_profiles([{"id": 3, "job_title": "产品经理"}])
        page.prefill_candidate(
            candidate_id=17,
            role_id=3,
            candidate_name="目标候选人",
            role_title="产品经理",
        )
        page.title_input.setText("明天跟进候选人")
        page.owner_input.setText("招聘负责人")
        saved: list[dict[str, object]] = []
        page.save_requested.connect(lambda payload: saved.append(dict(payload)))

        page.save_button.click()

        self.assertEqual(saved[0]["subject_type"], "candidate_role")
        self.assertEqual(saved[0]["candidate_id"], 17)
        self.assertEqual(saved[0]["role_id"], 3)
        self.assertEqual(saved[0]["title"], "明天跟进候选人")
        self.assertEqual(saved[0]["owner"], "招聘负责人")

        page.view_combo.setCurrentIndex(page.view_combo.findData("overdue"))
        self.assertEqual(page.current_filters()["view"], "overdue")
        page.set_summary(
            {
                "pending_total": 8,
                "today": 2,
                "overdue": 1,
                "next_7_days": 3,
                "completed_today": 4,
            }
        )
        page.set_page_result(
            [
                {
                    "id": 9,
                    "subject_type": "candidate_role",
                    "candidate_id": 17,
                    "role_id": 3,
                    "task_id": None,
                    "action_type": "follow_up",
                    "title": "跟进回复",
                    "owner": "招聘负责人",
                    "due_at": datetime.now().isoformat(timespec="seconds"),
                    "priority": "high",
                    "status": "pending",
                    "note": "确认意向",
                    "candidate_name": "目标候选人",
                    "role_title": "产品经理",
                    "task_name": None,
                }
            ],
            total=1,
            page=1,
            page_size=100,
        )
        statuses: list[tuple[int, str]] = []
        opened: list[dict[str, object]] = []
        page.status_requested.connect(lambda action_id, status: statuses.append((action_id, status)))
        page.subject_open_requested.connect(lambda payload: opened.append(dict(payload)))

        page.complete_button.click()
        page.open_subject_button.click()

        self.assertIn("待处理 8", page.summary_label.text())
        self.assertIn("逾期 1", page.summary_label.text())
        self.assertEqual(statuses, [(9, "completed")])
        self.assertEqual(opened[0]["candidate_id"], 17)


if __name__ == "__main__":
    unittest.main()
