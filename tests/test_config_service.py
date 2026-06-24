from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.config import ConfigService
from core.models import AutomationFlowConfig


class ConfigServiceTest(unittest.TestCase):
    def test_load_creates_default_config_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            config = service.load()
            self.assertTrue(service.config_path.exists())
            self.assertEqual(config.default_job_title, "Boss Recommended Talent")
            self.assertTrue(Path(config.user_data_dir).exists())

    def test_load_returns_defaults_when_json_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            service.config_path.write_text("{invalid json", encoding="utf-8")
            config = service.load()
            self.assertEqual(config.scroll_mode, "page")
            self.assertTrue(service.config_path.exists())

    def test_automation_flow_settings_are_persisted_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            config = service.default_config()
            config.automation_flow = AutomationFlowConfig(
                enabled=True,
                profile_id=12,
                job_title="Java工程师",
                source_url="https://www.zhipin.com/web/geek/recommend",
                max_candidates=80,
                provider="openai",
                model="gpt-5.4-mini",
                api_base="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
            )
            service.save(config)

            loaded = service.load()

            self.assertTrue(loaded.automation_flow.enabled)
            self.assertEqual(loaded.automation_flow.profile_id, 12)
            self.assertEqual(loaded.automation_flow.job_title, "Java工程师")
            self.assertEqual(loaded.automation_flow.max_candidates, 80)
            raw = json.loads(service.config_path.read_text(encoding="utf-8"))
            self.assertNotIn("api_key", raw["automation_flow"])


if __name__ == "__main__":
    unittest.main()
