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

        cancelled: list[tuple[int, str]] = []
        page.status_requested.connect(lambda task_id, status: cancelled.append((task_id, status)))
        page.show_task(
            {
                **emitted[0],
                "id": 11,
                "profile_version": 3,
                "status": "ready",
            },
            {},
            [],
        )
        page.cancel_button.click()
        self.assertEqual(cancelled, [(11, "cancelled")])

    def test_historical_task_keeps_its_inactive_job_visible(self) -> None:
        page = RecruitmentTasksPage()
        page.set_job_profiles([
            {"id": 7, "job_title": "已暂停岗位", "version": 2, "status": "paused"},
            {"id": 8, "job_title": "其他岗位", "version": 1, "status": "active"},
        ])
        row = {
            "id": 11, "name": "历史任务", "role_id": 7, "profile_version": 2,
            "platform": "boss", "source_url": "https://example.com", "status": "paused",
        }
        page.show_task(row, {}, [])

        self.assertEqual(page.profile_combo.currentData(), 7)

    def test_frontend_plugin_buttons_emit_selected_task_actions(self) -> None:
        page = RecruitmentTasksPage()
        page.set_job_profiles([{"id": 7, "job_title": "招聘顾问", "version": 1}])
        page.show_task(
            {
                "id": 11,
                "name": "招聘任务",
                "role_id": 7,
                "profile_version": 1,
                "platform": "boss",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "status": "running",
            },
            {},
            [],
        )
        emitted: list[tuple[str, int]] = []
        page.extension_action_requested.connect(
            lambda action, task_id: emitted.append((action, task_id))
        )

        page.plugin_auto_button.click()
        page.plugin_collect_current_button.click()
        page.plugin_collect_auto_button.click()
        page.plugin_pause_button.click()
        page.plugin_stop_button.click()

        self.assertEqual(
            emitted,
            [
                ("automation_auto", 11),
                ("collect_current", 11),
                ("collect_auto", 11),
                ("pause_scroll", 11),
                ("stop_capture", 11),
            ],
        )
        self.assertIn("插件原按钮仍可使用", page.plugin_control_hint.text())


if __name__ == "__main__":
    unittest.main()
