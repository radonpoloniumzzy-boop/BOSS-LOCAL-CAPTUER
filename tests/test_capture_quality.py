from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.capture_quality import CaptureQualityService
from automation.importer import CardImportService
from automation.parser import CandidateParser
from core.models import CandidateRecord, JobProfile, RecruitmentTask
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class CaptureQualityServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "capture-quality.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.profile = self.repository.save_job_profile(
            JobProfile(
                job_title="高级招聘顾问",
                jd_text="负责关键岗位招聘",
                prompt_text="筛选招聘经验",
                status="active",
            )
        )
        self.task = self.repository.save_recruitment_task(
            RecruitmentTask(
                name="BOSS 第一轮",
                role_id=int(self.profile.id),
                platform="boss",
                source_url="https://www.zhipin.com/web/geek/recommend",
                target_candidates=5,
            )
        )
        self.repository.set_recruitment_task_status(int(self.task.id), "running")
        self.service = CaptureQualityService(self.repository)

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_task_without_capture_batch_requires_collection(self) -> None:
        report = self.service.check_task(int(self.task.id))

        self.assertEqual(report["decision"], "needs_collection")
        self.assertEqual(report["decision_label"], "尚未采集")
        self.assertEqual(report["batch_id"], None)
        self.assertEqual(report["target_candidates"], 5)
        self.assertEqual(report["target_gap"], 5)
        self.assertIn("还没有采集批次", report["issues"])

    def test_complete_batch_with_consistent_candidates_is_ready_for_screening(self) -> None:
        batch = self.repository.create_batch(
            "高级招聘顾问",
            self.task.source_url,
            role_id=int(self.profile.id),
            task_id=int(self.task.id),
        )
        candidates = [
            CandidateRecord(
                candidate_key=f"boss:{index}",
                raw_text_hash=f"hash-{index}",
                job_title="高级招聘顾问",
                source_url=self.task.source_url,
                capture_time=f"2026-08-06T10:00:0{index}",
                raw_card_text=f"候选人 {index}，5 年招聘经验，本科",
                name=f"候选人 {index}",
                work_experience_text="5 年招聘经验",
                education_text="本科",
            )
            for index in range(5)
        ]
        self.repository.upsert_batch_candidates(int(batch.id), candidates)
        self.repository.finalize_batch(int(batch.id), "completed", 5, 5)

        report = self.service.check_task(int(self.task.id))

        self.assertEqual(report["decision"], "ready")
        self.assertEqual(report["decision_label"], "可进入 AI 初筛")
        self.assertEqual(report["batch_id"], batch.id)
        self.assertEqual(report["unique_candidates"], 5)
        self.assertEqual(report["duplicate_rate"], 0)
        self.assertEqual(report["core_completeness"], 100)
        self.assertEqual(report["source_consistency"], 100)
        self.assertEqual(report["target_gap"], 0)
        self.assertEqual(report["issues"], [])

    def test_incomplete_inconsistent_batch_requires_manual_review(self) -> None:
        earlier_batch = self.repository.create_batch(
            "高级招聘顾问",
            self.task.source_url,
            role_id=int(self.profile.id),
        )
        existing_candidate = CandidateRecord(
            candidate_key="boss:bad",
            raw_text_hash="hash-bad-old",
            job_title="高级招聘顾问",
            source_url=self.task.source_url,
            capture_time="2026-08-05T10:00:00",
            raw_card_text="此前已经采集",
            name="此前姓名",
        )
        earlier_result = self.repository.upsert_batch_candidates(
            int(earlier_batch.id), [existing_candidate]
        )
        self.repository.finalize_batch(
            int(earlier_batch.id), "completed", 1, earlier_result["inserted_candidates"]
        )
        batch = self.repository.create_batch(
            "高级招聘顾问",
            self.task.source_url,
            role_id=int(self.profile.id),
            task_id=int(self.task.id),
        )
        result = self.repository.upsert_batch_candidates(
            int(batch.id),
            [
                CandidateRecord(
                    candidate_key="boss:good",
                    raw_text_hash="hash-good",
                    job_title="高级招聘顾问",
                    source_url=self.task.source_url,
                    capture_time="2026-08-06T10:00:00",
                    raw_card_text="完整候选人卡片",
                    name="完整候选人",
                ),
                CandidateRecord(
                    candidate_key="boss:bad",
                    raw_text_hash="hash-bad",
                    job_title="高级招聘顾问",
                    source_url="https://unexpected.example.com/list",
                    capture_time="2026-08-06T10:00:01",
                    raw_card_text="字段不完整且来源异常",
                    name="",
                ),
            ],
        )
        self.repository.finalize_batch(
            int(batch.id), "completed", 2, result["inserted_candidates"]
        )

        report = self.service.check_task(int(self.task.id))

        self.assertEqual(report["decision"], "needs_review")
        self.assertEqual(report["decision_label"], "需要人工检查")
        self.assertEqual(report["duplicate_rate"], 50)
        self.assertEqual(report["core_completeness"], 50)
        self.assertEqual(report["source_consistency"], 50)
        self.assertEqual(report["target_gap"], 3)
        self.assertIn("核心字段完整度仅 50%", report["issues"])
        self.assertIn("来源一致率仅 50%", report["issues"])
        self.assertIn("重复率达到 50%", report["issues"])
        self.assertIn("距离任务目标还差 3 人", report["issues"])

    def test_thresholds_use_exact_counts_even_when_display_percentage_rounds_up(self) -> None:
        batch = self.repository.create_batch(
            "高级招聘顾问",
            self.task.source_url,
            role_id=int(self.profile.id),
            task_id=int(self.task.id),
        )
        candidates = []
        for index in range(200):
            candidates.append(
                CandidateRecord(
                    candidate_key=f"boss:boundary:{index}",
                    raw_text_hash=f"hash-boundary-{index}",
                    job_title="高级招聘顾问",
                    source_url=(
                        "https://unexpected.example.com/list"
                        if index == 199
                        else self.task.source_url
                    ),
                    capture_time="2026-08-06T11:00:00",
                    raw_card_text="候选人卡片",
                    name="" if index >= 159 else f"候选人 {index}",
                )
            )
        result = self.repository.upsert_batch_candidates(int(batch.id), candidates)
        self.repository.finalize_batch(
            int(batch.id), "completed", 200, result["inserted_candidates"]
        )

        report = self.service.check_task(int(self.task.id))

        self.assertEqual(report["core_completeness"], 79.5)
        self.assertEqual(report["source_consistency"], 99.5)
        self.assertIn("核心字段完整度仅 79.5%", report["issues"])
        self.assertIn("来源一致率仅 99.5%", report["issues"])
        self.assertEqual(report["decision"], "needs_review")

    def test_extension_import_reports_candidate_seen_in_earlier_batch_as_duplicate(self) -> None:
        importer = CardImportService(self.repository, CandidateParser())
        card = {
            "raw_card_text": "张三 五年招聘经验 本科",
            "name": "张三",
            "detail_url": "https://www.zhipin.com/geek/duplicate-1",
        }
        importer.import_cards(
            {
                "job_profile_id": self.profile.id,
                "job_title": "高级招聘顾问",
                "source_url": self.task.source_url,
                "cards": [card],
            }
        )
        importer.import_cards(
            {
                "job_profile_id": self.profile.id,
                "recruitment_task_id": self.task.id,
                "job_title": "高级招聘顾问",
                "source_url": self.task.source_url,
                "cards": [card],
            }
        )

        report = self.service.check_task(int(self.task.id))

        self.assertEqual(report["unique_candidates"], 1)
        self.assertEqual(report["new_candidates"], 0)
        self.assertEqual(report["duplicate_rate"], 100)
        self.assertIn("重复率达到 100%", report["issues"])


if __name__ == "__main__":
    unittest.main()
