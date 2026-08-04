from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.importer import CardImportService
from automation.parser import CandidateParser
from core.models import JobProfile
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
        profile = self.repository.save_job_profile(
            JobProfile(
                job_title="Recruiting Intern",
                jd_text="Recruiting support",
                prompt_text="Screen recruiting experience",
                status="active",
            )
        )
        result = self.service.import_cards(
            {
                "job_profile_id": profile.id,
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
        profile = self.repository.save_job_profile(
            JobProfile(
                job_title="猎聘推荐人才",
                jd_text="猎聘人才采集",
                prompt_text="筛选人才",
                status="active",
            )
        )
        result = self.service.import_cards(
            {
                "job_profile_id": profile.id,
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

    def test_import_batch_links_matching_job_profile_without_changing_candidate_identity(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(
                job_title="招聘实习生",
                jd_text="负责招聘支持",
                prompt_text="筛选招聘经历",
                status="active",
            )
        )

        result = self.service.import_cards(
            {
                "job_title": "招聘实习生",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [{"raw_card_text": "李四 招聘实习 本科", "name": "李四"}],
            }
        )
        batch = next(
            row for row in self.repository.list_batches() if int(row["id"]) == int(result["batch_id"])
        )

        self.assertEqual(batch["role_id"], profile.id)

    def test_explicit_job_profile_id_survives_renamed_source_title(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="当前统一名称", jd_text="", prompt_text="", status="active")
        )

        result = self.service.import_cards(
            {
                "job_profile_id": profile.id,
                "job_title": "插件缓存的旧名称",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [{"raw_card_text": "王五 五年招聘经验", "name": "王五"}],
            }
        )
        batch = next(
            row for row in self.repository.list_batches() if int(row["id"]) == int(result["batch_id"])
        )

        self.assertEqual(batch["role_id"], profile.id)
        self.assertEqual(result["job_profile_id"], profile.id)
        self.assertEqual(batch["job_title"], "插件缓存的旧名称")

    def test_import_rejects_inactive_explicit_job_profile(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="暂停岗位", jd_text="", prompt_text="", status="active")
        )
        self.repository.set_job_profile_status(int(profile.id), "paused")

        with self.assertRaisesRegex(ValueError, "不是招聘中"):
            self.service.import_cards(
                {
                    "job_profile_id": profile.id,
                    "job_title": "暂停岗位",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "cards": [{"raw_card_text": "赵六 招聘经验", "name": "赵六"}],
                }
            )

        with self.assertRaisesRegex(ValueError, "不是招聘中"):
            self.service.import_cards(
                {
                    "job_title": "暂停岗位",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "cards": [{"raw_card_text": "钱七 招聘经验", "name": "钱七"}],
                }
            )


if __name__ == "__main__":
    unittest.main()
