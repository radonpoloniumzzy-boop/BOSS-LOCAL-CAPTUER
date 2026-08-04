from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.pages.recruitment_tasks import RecruitmentTasksPage


class RecruitmentTasksPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_page_builds_task_and_exposes_two_window_workbench_actions(self) -> None:
        page = RecruitmentTasksPage()
        page.set_job_profiles([{"id": 7, "job_title": "高级招聘顾问", "version": 3}])
        emitted: list[dict[str, object]] = []
        page.save_requested.connect(emitted.append)
        page.name_input.setText("BOSS 第一轮 Mapping")
        page.target_candidates_input.setValue(80)
        page.target_ssr_input.setValue(5)
        page.save_button.click()

        self.assertEqual(emitted[0]["role_id"], 7)
        self.assertEqual(emitted[0]["target_candidates"], 80)
        self.assertIn("招聘平台 + HR 工作台", page.workbench_hint.text())
        self.assertTrue(page.open_platform_button.text().startswith("打开招聘平台"))
        self.assertTrue(page.open_export_button.text().startswith("打开选中导出"))


if __name__ == "__main__":
    unittest.main()
