from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation.collector import CaptureService
from automation.parser import CandidateParser
from automation.scroller import PageScroller
from core.models import AppConfig, CollectOptions
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class _DummyBrowserService:
    def ensure_page(self, _config, _target_url=None):
        return object()

    def detect_manual_intervention(self, _page) -> str:
        return ""


class CaptureServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.options = CollectOptions(job_title="招聘实习生", source_url="https://example.com")
        self.config = AppConfig(
            user_data_dir=str(Path(self.temp_dir.name) / "profile"),
            default_export_dir=str(Path(self.temp_dir.name) / "exports"),
            selectors_path=str(Path(self.temp_dir.name) / "selectors.json"),
            scroll_wait_seconds=0,
            max_scroll_count=10,
            no_new_stop_rounds=2,
        )

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_collect_stops_after_consecutive_rounds_without_new_cards(self) -> None:
        class NoopScroller(PageScroller):
            def scroll_once(self, page, mode: str, step: int, wait_seconds: float) -> int:
                return 0

        service = CaptureService(self.repository, CandidateParser(), NoopScroller())
        fake_collector = MagicMock()
        card = {
            "raw_card_text": "张三 招聘实习生 10k",
            "name": "张三",
            "expected_salary": "10k-12k",
        }
        fake_collector.wait_for_page_ready.return_value = True
        fake_collector.extract_loaded_cards.side_effect = [[card], [card], [card]]

        with patch("automation.collector.BossCardCollector", return_value=fake_collector):
            result = service.collect(
                browser_service=_DummyBrowserService(),
                selector_config=MagicMock(),
                options=self.options,
                config=self.config,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.total_unique, 1)
        self.assertEqual(result.rounds_completed, 3)

    def test_collect_can_be_stopped_by_user(self) -> None:
        service = CaptureService(self.repository, CandidateParser(), PageScroller())

        class StopScroller(PageScroller):
            def scroll_once(self, page, mode: str, step: int, wait_seconds: float) -> int:
                service.request_stop()
                return 0

        service.scroller = StopScroller()
        fake_collector = MagicMock()
        card = {
            "raw_card_text": "李四 招聘实习生 11k",
            "name": "李四",
            "expected_salary": "11k-13k",
        }
        fake_collector.wait_for_page_ready.return_value = True
        fake_collector.extract_loaded_cards.side_effect = [[card], [card]]

        with patch("automation.collector.BossCardCollector", return_value=fake_collector):
            result = service.collect(
                browser_service=_DummyBrowserService(),
                selector_config=MagicMock(),
                options=self.options,
                config=self.config,
            )

        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.total_unique, 1)


if __name__ == "__main__":
    unittest.main()
