from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.config import LEGACY_CSV_COLUMNS, REVIEW_CSV_COLUMNS_V1, REVIEW_CSV_COLUMNS_V2, ConfigService
from core.models import DEFAULT_CSV_COLUMNS, AutomationFlowConfig


class ConfigServiceTest(unittest.TestCase):
    def test_load_creates_default_config_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            config = service.load()
            self.assertTrue(service.config_path.exists())
            self.assertEqual(config.default_job_title, "Boss Recommended Talent")
            self.assertTrue(config.local_api_token)
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

    def test_load_backfills_missing_local_api_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            config = service.default_config()
            payload = config.to_dict()
            payload.pop("local_api_token")
            service.config_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = service.load()

            raw = json.loads(service.config_path.read_text(encoding="utf-8"))
            self.assertTrue(loaded.local_api_token)
            self.assertEqual(raw["local_api_token"], loaded.local_api_token)

    def test_load_migrates_legacy_default_csv_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            payload = service.default_config().to_dict()
            payload["csv_columns"] = list(LEGACY_CSV_COLUMNS)
            service.config_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = service.load()

            raw = json.loads(service.config_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded.csv_columns, list(DEFAULT_CSV_COLUMNS))
            self.assertEqual(raw["csv_columns"], list(DEFAULT_CSV_COLUMNS))
            self.assertIn("latest_rating", loaded.csv_columns)
            self.assertIn("recruitment_status", loaded.csv_columns)

    def test_load_migrates_review_v1_default_csv_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            payload = service.default_config().to_dict()
            payload["csv_columns"] = list(REVIEW_CSV_COLUMNS_V1)
            service.config_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = service.load()

            self.assertEqual(loaded.csv_columns, list(DEFAULT_CSV_COLUMNS))
            self.assertIn("latest_reason_code", loaded.csv_columns)
            self.assertIn("latest_status_note", loaded.csv_columns)

    def test_load_migrates_review_v2_default_csv_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            payload = service.default_config().to_dict()
            payload["csv_columns"] = list(REVIEW_CSV_COLUMNS_V2)
            service.config_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = service.load()

            self.assertEqual(loaded.csv_columns, list(DEFAULT_CSV_COLUMNS))
            self.assertIn("recommended_action", loaded.csv_columns)
            self.assertIn("evidence_json", loaded.csv_columns)

    def test_load_preserves_custom_csv_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            payload = service.default_config().to_dict()
            payload["csv_columns"] = ["name", "raw_card_text"]
            service.config_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = service.load()

            self.assertEqual(loaded.csv_columns, ["name", "raw_card_text"])

    def test_load_removes_legacy_plaintext_api_keys_without_resetting_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ConfigService(app_root=Path(tmp_dir))
            payload = service.default_config().to_dict()
            payload["default_job_title"] = "Keep this role"
            payload["ai_provider"]["api_key"] = "legacy-secret"
            payload["automation_flow"]["api_key"] = "legacy-automation-secret"
            service.config_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = service.load()
            raw = json.loads(service.config_path.read_text(encoding="utf-8"))

            self.assertEqual(loaded.default_job_title, "Keep this role")
            self.assertNotIn("api_key", raw["ai_provider"])
            self.assertNotIn("api_key", raw["automation_flow"])


if __name__ == "__main__":
    unittest.main()
