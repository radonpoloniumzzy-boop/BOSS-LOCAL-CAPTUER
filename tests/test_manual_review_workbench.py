from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.models import CandidateRecord, JobProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class ManualReviewWorkbenchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "manual-review.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.profile = self.repository.save_job_profile(
            JobProfile(
                job_title="招聘顾问",
                jd_text="负责招聘交付",
                prompt_text="筛选招聘经验",
                status="active",
            )
        )
        batch = self.repository.create_batch(
            "招聘顾问", "https://www.zhipin.com/web/geek/recommend", role_id=int(self.profile.id)
        )
        candidates = [
            CandidateRecord(
                candidate_key=f"boss:review:{index}",
                raw_text_hash=f"review-hash-{index}",
                job_title="招聘顾问",
                source_url="https://www.zhipin.com/web/geek/recommend",
                capture_time=f"2026-08-06T10:00:0{index}",
                raw_card_text=f"候选人 {index}，招聘经验",
                name=f"候选人 {index}",
                work_experience_text="五年招聘经验",
                education_text="本科",
            )
            for index in range(5)
        ]
        self.repository.upsert_batch_candidates(int(batch.id), candidates)
        self.candidate_ids = [
            int(row["id"])
            for row in sorted(self.repository.list_candidates(), key=lambda row: str(row["name"]))
        ]
        match_settings = [
            ("SSR", "high", "ai_screened"),
            ("R", "low", "ai_screened"),
            ("R", "high", "manual_check"),
            ("R", "high", "manual_check"),
            ("R", "high", "ai_screened"),
        ]
        for candidate_id, (rating, confidence, match_status) in zip(
            self.candidate_ids, match_settings
        ):
            self.repository.upsert_candidate_role_match(
                candidate_id=candidate_id,
                role_id=int(self.profile.id),
                latest_rating=rating,
                latest_confidence=confidence,
                match_status=match_status,
                recruitment_status="screened",
            )

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_queue_classifies_prioritizes_filters_and_summarizes_review_work(self) -> None:
        self.repository.record_candidate_role_status_change(
            candidate_id=self.candidate_ids[2],
            role_id=int(self.profile.id),
            to_status="screened",
            operator="tester",
            reason_code="manual_review_needs_info",
            note="缺少最近一段工作经历",
        )
        self.repository.record_candidate_role_status_change(
            candidate_id=self.candidate_ids[3],
            role_id=int(self.profile.id),
            to_status="screened",
            operator="tester",
            reason_code="manual_review_deferred",
            note="本周暂缓处理",
        )
        self.repository.record_candidate_role_status_change(
            candidate_id=self.candidate_ids[2],
            role_id=int(self.profile.id),
            to_status="screened",
            operator="system",
            reason_code="task_created",
            note="后续系统事件不应抹掉人工待补充分类",
        )

        rows = self.repository.list_manual_review_candidates(role_id=int(self.profile.id))
        priority_rows = self.repository.list_manual_review_candidates(
            role_id=int(self.profile.id), queue_category="priority"
        )
        needs_info_rows = self.repository.list_manual_review_candidates(
            role_id=int(self.profile.id), queue_category="needs_info"
        )
        deferred_rows = self.repository.list_manual_review_candidates(
            role_id=int(self.profile.id), queue_category="deferred"
        )
        summary = self.repository.get_manual_review_workbench_summary(
            role_id=int(self.profile.id)
        )

        self.assertEqual(len(rows), 5)
        self.assertEqual([row["review_bucket"] for row in rows[:2]], ["priority", "priority"])
        self.assertEqual({row["latest_rating"] for row in priority_rows}, {"SSR", "R"})
        self.assertEqual([row["candidate_id"] for row in needs_info_rows], [self.candidate_ids[2]])
        self.assertEqual([row["candidate_id"] for row in deferred_rows], [self.candidate_ids[3]])
        self.assertIn("缺少最近一段工作经历", needs_info_rows[0]["review_history_text"])
        self.assertEqual(summary["pending_total"], 5)
        self.assertEqual(summary["high_priority"], 2)
        self.assertEqual(summary["needs_info"], 1)
        self.assertEqual(summary["deferred"], 1)
        self.assertEqual(summary["reviewed_today"], 2)

    def test_paging_recovers_to_last_valid_page_after_queue_shrinks(self) -> None:
        first_page = self.repository.page_manual_review_candidates(
            role_id=int(self.profile.id), page=3, page_size=2
        )
        self.assertEqual(first_page["page"], 3)
        self.assertEqual(first_page["total"], 5)
        self.assertEqual(len(first_page["rows"]), 1)

        last_candidate = int(first_page["rows"][0]["candidate_id"])
        self.repository.record_candidate_role_status_change(
            candidate_id=last_candidate,
            role_id=int(self.profile.id),
            to_status="rejected",
            operator="review_workbench",
            reason_code="manual_review_rejected",
            note="复核不通过",
        )

        recovered_page = self.repository.page_manual_review_candidates(
            role_id=int(self.profile.id), page=3, page_size=2
        )

        self.assertEqual(recovered_page["page"], 2)
        self.assertEqual(recovered_page["total"], 4)
        self.assertEqual(len(recovered_page["rows"]), 2)


if __name__ == "__main__":
    unittest.main()
