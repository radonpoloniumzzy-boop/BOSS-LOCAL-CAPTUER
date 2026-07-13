from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.config import ConfigService
from ui.main_window import MainWindow


class MainWindowSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_startup_candidate_query_and_close_do_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_service = ConfigService(Path(tmp_dir))
            config = config_service.default_config()
            config.local_api_port = 0
            config_service.save(config)

            with patch("ui.main_window.ConfigService", return_value=config_service):
                window = MainWindow()
                QTest.qWait(500)
                self.assertEqual(window.candidates_page.table.rowCount(), 0)
                self.assertTrue(window.candidate_query_thread.isRunning())
                window.close()
                QTest.qWait(50)

    def test_repeated_api_connection_tests_finish_without_thread_crash(self) -> None:
        class FakeProvider:
            def test_connection(self):
                return SimpleNamespace(persona="ok")

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_service = ConfigService(Path(tmp_dir))
            config = config_service.default_config()
            config.local_api_port = 0
            config_service.save(config)
            payload = {
                "provider": "custom",
                "model": "test-model",
                "api_base": "https://example.com/v1",
                "api_key": "",
                "api_key_env": "TEST_API_KEY",
            }

            with (
                patch("ui.main_window.ConfigService", return_value=config_service),
                patch("ui.workers.create_provider", return_value=FakeProvider()),
                patch.dict("os.environ", {"TEST_API_KEY": "test-key"}),
            ):
                window = MainWindow()
                try:
                    for _ in range(5):
                        window._test_ai_connection(payload)
                        for _attempt in range(20):
                            QTest.qWait(50)
                            if not window._ai_test_running:
                                break
                        self.assertFalse(window._ai_test_running)
                finally:
                    window.close()
                    QTest.qWait(50)

    def test_ten_thousand_candidate_first_page_appears_within_two_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_service = ConfigService(Path(tmp_dir))
            config = config_service.default_config()
            config.local_api_port = 0
            config_service.save(config)
            from storage.db import DatabaseManager

            database = DatabaseManager(config_service.database_path)
            database.initialize()
            connection = database.get_connection()
            timestamp = "2026-07-13T12:00:00"
            with connection:
                connection.executemany(
                    """
                    INSERT INTO candidates(
                        candidate_key, raw_text_hash, job_title, source_url, capture_time,
                        raw_card_text, name, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            f"bench:{index}", f"hash:{index}", "证券交易员",
                            "https://example.com", timestamp, f"Candidate {index}",
                            f"Candidate {index:05d}", timestamp, timestamp,
                        )
                        for index in range(10_000)
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO candidate_profiles(candidate_id, parser_version, updated_at)
                    SELECT id, 'rule:v2', ? FROM candidates
                    """,
                    (timestamp,),
                )
            database.close_thread_connection()

            with patch("ui.main_window.ConfigService", return_value=config_service):
                window = MainWindow()
                try:
                    started = time.perf_counter()
                    while window.candidates_page.table.rowCount() < 100:
                        time.sleep(0.01)
                        self.app.processEvents()
                        if time.perf_counter() - started > 8.0:
                            break
                    elapsed = time.perf_counter() - started
                    self.assertEqual(
                        window.candidates_page.table.rowCount(),
                        100,
                        window.statusBar().currentMessage(),
                    )
                    self.assertLess(elapsed, 2.0)
                    self.assertIn("10000", window.candidates_page.page_label.text())
                finally:
                    window.close()
                    QTest.qWait(50)


if __name__ == "__main__":
    unittest.main()
