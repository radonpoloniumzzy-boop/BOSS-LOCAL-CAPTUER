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


if __name__ == "__main__":
    unittest.main()
