from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.pages.job_profiles import JobProfilesPage


class JobProfilesPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_user_can_edit_one_profile_and_submit_all_job_and_screening_fields(self) -> None:
        page = JobProfilesPage()
        profile = {
            "id": 7,
            "job_title": "高级招聘顾问",
            "department": "人才招聘部",
            "hiring_manager": "钟女士",
            "location": "上海",
            "employment_type": "全职",
            "experience_requirement": "5 年以上",
            "education_requirement": "本科及以上",
            "target_hires": 2,
            "recruitment_deadline": "2026-10-31",
            "priority": "high",
            "status": "active",
            "jd_text": "负责关键岗位招聘",
            "prompt_text": "按岗位规则筛选",
            "prompt_source": "custom",
            "must_have": ["完整招聘经验"],
            "nice_to_have": ["猎头经验"],
            "risk_flags": ["经历描述模糊"],
            "exclusions": ["无招聘经验"],
            "interview_checks": ["核验招聘闭环"],
            "evidence_policy": {"explicit_evidence_required": True},
            "version": 3,
        }
        page.set_profiles([profile])
        page.show_profile(profile)
        page.set_versions(
            [
                {"version": 3, "created_at": "2026-08-04T12:00:00", "snapshot": profile},
                {"version": 2, "created_at": "2026-08-03T12:00:00", "snapshot": profile},
            ]
        )

        self.assertEqual(page.tabs.tabText(0), "基本信息")
        self.assertEqual(page.tabs.tabText(1), "筛选规则")
        self.assertEqual(page.tabs.tabText(2), "版本历史")
        self.assertEqual(page.profile_table.rowCount(), 1)
        self.assertEqual(page.version_table.rowCount(), 2)
        self.assertEqual(page.version_label.text(), "V3")
        self.assertIn("完整招聘经验", page.version_detail.toPlainText())

        emitted: list[dict[str, object]] = []
        page.save_requested.connect(emitted.append)
        page.target_hires_input.setValue(3)
        page.must_have_input.setText("完整招聘经验；Mapping 项目经验")
        page.save_button.click()

        self.assertEqual(emitted[0]["id"], 7)
        self.assertEqual(emitted[0]["target_hires"], 3)
        self.assertEqual(emitted[0]["must_have"], ["完整招聘经验", "Mapping 项目经验"])
        self.assertEqual(emitted[0]["status"], "active")

    def test_new_job_starts_as_draft_and_requires_title_and_jd(self) -> None:
        page = JobProfilesPage()
        emitted: list[dict[str, object]] = []
        page.save_requested.connect(emitted.append)

        page.new_button.click()
        page.save_button.click()
        self.assertEqual(emitted, [])
        self.assertIn("岗位名称", page.message_label.text())

        page.job_title_input.setText("数据分析师")
        page.jd_input.setPlainText("负责招聘数据分析")
        page.save_button.click()
        self.assertEqual(emitted[0]["status"], "draft")


if __name__ == "__main__":
    unittest.main()
