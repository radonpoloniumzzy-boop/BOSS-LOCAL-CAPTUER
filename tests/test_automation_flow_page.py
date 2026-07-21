from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.pages.automation_flow import AutomationFlowPage


class AutomationFlowPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_workflow_payload_exposes_single_batch_favorite_controls(self) -> None:
        page = AutomationFlowPage()
        self.addCleanup(page.deleteLater)
        page.set_profiles(
            [
                {
                    "id": 7,
                    "job_title": "Quant Researcher",
                    "favorite_eligible_ratings": ["SSR", "SR"],
                }
            ],
            selected_profile_id=7,
        )
        page.post_screen_action_combo.setCurrentIndex(
            page.post_screen_action_combo.findData("screen_and_favorite")
        )
        page.favorite_interval_input.setValue(6)
        page.favorite_max_candidates_input.setValue(18)
        page.screening_concurrency_input.setValue(6)

        payload = page.workflow_payload()

        self.assertEqual(payload["post_screen_action"], "screen_and_favorite")
        self.assertEqual(payload["favorite_interval_seconds"], 6)
        self.assertEqual(payload["favorite_max_candidates"], 18)
        self.assertEqual(payload["screening_concurrency"], 6)
        self.assertIn("SSR", page.favorite_policy_label.text())
        self.assertEqual(page.favorite_interval_input.minimum(), 3)
        self.assertEqual(page.favorite_interval_input.maximum(), 8)
        self.assertEqual(page.favorite_max_candidates_input.maximum(), 50)
        self.assertEqual(page.screening_concurrency_input.minimum(), 1)
        self.assertEqual(page.screening_concurrency_input.maximum(), 8)

    def test_pipeline_status_shows_stage_batch_and_screening_trace(self) -> None:
        page = AutomationFlowPage()
        self.addCleanup(page.deleteLater)

        page.update_pipeline_status(
            {
                "stage": "screening",
                "collection_run_id": "collect-12345678",
                "batch_id": 149,
                "screening_run_id": 65,
                "current": 216,
                "total": 448,
                "message": "AI 初筛进行中",
            }
        )

        text = page.pipeline_status_label.text()
        self.assertIn("采集任务 collect-1", text)
        self.assertIn("采集批次 #149", text)
        self.assertIn("初筛任务 #65", text)
        self.assertIn("216/448", text)

    def test_duplicate_capture_marks_ai_as_skipped_not_completed(self) -> None:
        page = AutomationFlowPage()
        self.addCleanup(page.deleteLater)

        page.update_pipeline_status(
            {
                "stage": "duplicate",
                "batch_id": 149,
                "message": "与上一批完全相同",
            }
        )

        text = page.pipeline_status_label.text()
        self.assertIn("④ 导入批次 ✓", text)
        self.assertIn("⑤ AI 初筛 跳过", text)

    def test_failed_capture_marks_the_real_failed_stage(self) -> None:
        page = AutomationFlowPage()
        self.addCleanup(page.deleteLater)
        page.update_pipeline_status(
            {
                "stage": "failed",
                "failed_stage": "scrolling",
                "message": "candidate_content_not_stable",
            }
        )

        text = page.pipeline_status_label.text()
        self.assertIn("① 页面确认 ✓", text)
        self.assertIn("② 滚动采集 失败", text)
        self.assertIn("③ 内容稳定 ○", text)

    def test_load_config_defaults_to_screen_only_without_hidden_policy(self) -> None:
        page = AutomationFlowPage()
        self.addCleanup(page.deleteLater)
        config = SimpleNamespace(
            default_job_title="Boss Recommended Talent",
            target_url="https://www.zhipin.com/web/geek/recommend",
            automation_flow=SimpleNamespace(
                enabled=False,
                profile_id=None,
                job_title="",
                source_url="https://www.zhipin.com/web/geek/recommend",
                max_candidates=0,
                provider="openai",
                model="test-model",
                api_base="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                post_screen_action="screen_only",
                screening_concurrency=4,
                favorite_interval_seconds=5,
                favorite_max_candidates=20,
            ),
        )

        page.load_config(config)

        self.assertEqual(page.post_screen_action_combo.currentData(), "screen_only")
        self.assertEqual(page.screening_concurrency_input.value(), 4)
        self.assertEqual(page.favorite_interval_input.value(), 5)
        self.assertEqual(page.favorite_max_candidates_input.value(), 20)

    def test_saved_credential_status_explains_that_api_key_can_be_left_blank(self) -> None:
        page = AutomationFlowPage()
        self.addCleanup(page.deleteLater)

        page.set_credential_status(True)

        self.assertEqual(page.api_key_input.text(), "")
        self.assertIn("Windows 凭据管理器", page.credential_status_label.text())
        self.assertIn("可留空", page.credential_status_label.text())


if __name__ == "__main__":
    unittest.main()
