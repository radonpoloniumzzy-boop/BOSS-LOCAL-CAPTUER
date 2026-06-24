from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.importer import CardImportService
from automation.parser import CandidateParser
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class CardImportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.service = CardImportService(self.repository, CandidateParser())

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_import_cards_creates_batch_and_candidates(self) -> None:
        result = self.service.import_cards(
            {
                "job_title": "Recruiting Intern",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {
                        "raw_card_text": "Alice recruiting 10k bachelor",
                        "name": "Alice",
                        "expected_salary": "10k-12k",
                        "work_experience_text": "1 year recruiting",
                        "education_text": "Bachelor",
                        "detail_url": "https://www.zhipin.com/geek/1",
                    },
                    {
                        "raw_card_text": "Alice recruiting 10k bachelor",
                        "name": "Alice",
                        "expected_salary": "10k-12k",
                        "work_experience_text": "1 year recruiting",
                        "education_text": "Bachelor",
                        "detail_url": "https://www.zhipin.com/geek/1",
                    },
                ],
                "meta": {
                    "rounds_completed": 5,
                    "unique_cards": 1,
                    "automation_requested": True,
                },
            }
        )
        self.assertEqual(result["parsed_cards"], 1)
        self.assertEqual(result["total_batch_items"], 1)
        self.assertEqual(result["job_title"], "Recruiting Intern")
        self.assertEqual(result["source_url"], "https://www.zhipin.com/web/geek/recommend")
        self.assertTrue(result["automation_requested"])
        self.assertEqual(len(self.repository.list_candidates()), 1)

    def test_import_liepin_cards_reuses_existing_candidate_model(self) -> None:
        result = self.service.import_cards(
            {
                "job_title": "猎聘推荐人才",
                "source_url": "https://lpt.liepin.com/recommend",
                "cards": [
                    {
                        "platform": "liepin",
                        "raw_card_text": "张三\nJava开发工程师\n20-35k\n5年经验\n本科\nSpring Cloud",
                        "name": "张三",
                        "expected_salary": "20-35k",
                        "work_experience_text": "5年经验",
                        "education_text": "本科",
                        "tags_text": ["Java", "Spring Cloud"],
                        "detail_url": "https://lpt.liepin.com/resume/resume-1",
                        "platform_uid": "liepin:resume-1",
                    },
                    {
                        "platform": "liepin",
                        "raw_card_text": "张三\nJava开发工程师\n20-35k\n5年经验\n本科\nSpring Cloud",
                        "name": "张三",
                        "expected_salary": "20-35k",
                        "work_experience_text": "5年经验",
                        "education_text": "本科",
                        "tags_text": ["Java", "Spring Cloud"],
                        "detail_url": "https://lpt.liepin.com/resume/resume-1",
                        "platform_uid": "liepin:resume-1",
                    },
                ],
                "meta": {"platform": "liepin", "rounds_completed": 3, "unique_cards": 1},
            }
        )
        candidates = self.repository.list_candidates()
        self.assertEqual(result["parsed_cards"], 1)
        self.assertEqual(result["total_batch_items"], 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_url"], "https://lpt.liepin.com/recommend")
        self.assertEqual(candidates[0]["candidate_key"], "platform:liepin:resume-1")


if __name__ == "__main__":
    unittest.main()
