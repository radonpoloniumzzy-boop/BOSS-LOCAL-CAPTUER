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

    def test_product_development_page_is_available_from_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_service = ConfigService(Path(tmp_dir))
            assets_dir = config_service.app_root / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            source_plan = Path(__file__).parents[1] / "assets" / "product_development_plan.json"
            (assets_dir / "product_development_plan.json").write_text(
                source_plan.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            config = config_service.default_config()
            config.local_api_port = 0
            config_service.save(config)

            with patch("ui.main_window.ConfigService", return_value=config_service):
                window = MainWindow()
                try:
                    self.assertIn("产品建设", window._navigation_full_labels)
                    product_index = window._navigation_full_labels.index("产品建设")
                    window.navigation.setCurrentRow(product_index)
                    QTest.qWait(20)
                    self.assertIs(
                        window._page_scroll_areas[product_index].widget(),
                        window.product_development_page,
                    )
                    self.assertIn("0.4.0-dev", window.product_development_page.version_value.text())
                    version_statuses = {
                        window.product_development_page.version_table.item(row, 2).text()
                        for row in range(window.product_development_page.version_table.rowCount())
                    }
                    self.assertIn("暂无稳定版", version_statuses)
                    window.product_development_page.feedback_description_input.setPlainText(
                        "测试环境反馈"
                    )
                    window.product_development_page.feedback_submit_button.click()
                    self.assertTrue((config_service.data_dir / "product_feedback.json").exists())
                    self.assertEqual(window.product_development_page.feedback_table.rowCount(), 1)
                finally:
                    window.close()
                    QTest.qWait(50)

    def test_job_center_is_the_single_editor_and_feeds_operational_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_service = ConfigService(Path(tmp_dir))
            assets_dir = config_service.app_root / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            source_plan = Path(__file__).parents[1] / "assets" / "product_development_plan.json"
            (assets_dir / "product_development_plan.json").write_text(
                source_plan.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            config = config_service.default_config()
            config.local_api_port = 0
            config_service.save(config)

            with patch("ui.main_window.ConfigService", return_value=config_service):
                window = MainWindow()
                try:
                    QTest.qWait(500)
                    self.assertIn("岗位中心", window._navigation_full_labels)
                    self.assertGreaterEqual(window.job_profiles_page.profile_table.rowCount(), 1)
                    self.assertTrue(window.ai_page.job_title_input.isReadOnly())
                    self.assertTrue(window.ai_page.save_profile_button.isHidden())
                    self.assertGreaterEqual(window.dashboard_page.job_profile_combo.count(), 1)

                    window.job_profiles_page.new_button.click()
                    window.job_profiles_page.job_title_input.setText("数据分析师")
                    window.job_profiles_page.jd_input.setPlainText("负责招聘数据分析")
                    active_index = window.job_profiles_page.status_combo.findData("active")
                    window.job_profiles_page.status_combo.setCurrentIndex(active_index)
                    window.job_profiles_page.save_button.click()

                    titles = {
                        row["job_title"] for row in window.repository.list_job_profiles()
                    }
                    self.assertIn("数据分析师", titles)
                    dashboard_titles = {
                        window.dashboard_page.job_profile_combo.itemText(index)
                        for index in range(window.dashboard_page.job_profile_combo.count())
                    }
                    self.assertIn("数据分析师", dashboard_titles)
                finally:
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
