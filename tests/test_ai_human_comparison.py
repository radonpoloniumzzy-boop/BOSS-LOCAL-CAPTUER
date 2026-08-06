from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.models import CandidateRecord, JobProfile, ScreeningResult
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class AIHumanComparisonRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "ai-human-comparison.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.profile = self.repository.save_job_profile(
            JobProfile(
                job_title="产品经理",
                jd_text="负责企业软件产品",
                prompt_text="筛选企业软件产品经验",
                status="active",
            )
        )
        batch = self.repository.create_batch(
            "产品经理", "https://example.com/candidates", role_id=int(self.profile.id)
        )
        candidates = [
            CandidateRecord(
                candidate_key=f"comparison:{index}",
                raw_text_hash=f"comparison-hash-{index}",
                job_title="产品经理",
                source_url="https://example.com/candidates",
                capture_time=f"2026-08-06T10:00:0{index}",
                raw_card_text=f"候选人 {index} 企业软件产品经验",
                name=f"候选人 {index}",
            )
            for index in range(6)
        ]
        self.repository.upsert_batch_candidates(int(batch.id), candidates)
        self.candidate_ids = [
            int(row["id"])
            for row in sorted(self.repository.list_candidates(), key=lambda row: str(row["name"]))
        ]
        run_id = self.repository.create_screening_run(
            profile_id=int(self.profile.id),
            source_job_title="产品经理",
            batch_id=int(batch.id),
            provider="fake",
            model="comparison-model",
            total_candidates=6,
        )
        ai_results = [
            ("SSR", "high", "priority_outreach"),
            ("SR", "high", "normal_review"),
            ("N", "medium", ""),
            ("N", "high", ""),
            ("R", "low", "manual_check"),
            ("SSR", "high", "priority_outreach"),
        ]
        for candidate_id, (rating, confidence, action) in zip(self.candidate_ids, ai_results):
            result_id = self.repository.save_screening_result(
                ScreeningResult(
                    run_id=run_id,
                    candidate_id=candidate_id,
                    rating=rating,
                    persona="企业软件产品候选人",
                    confidence=confidence,
                    evidence_json='[{"item":"产品经验","evidence":"企业软件"}]',
                    gap_json='["团队规模待确认"]',
                    risk_json='[]',
                    recommended_action=action,
                )
            )
            self.repository.upsert_candidate_role_match(
                candidate_id=candidate_id,
                role_id=int(self.profile.id),
                latest_rating=rating,
                latest_confidence=confidence,
                match_status="ai_screened",
                recruitment_status="screened",
                screening_result_id=result_id,
            )

        human_results = [
            ("manual_review_passed", "priority_outreach", "证据充分"),
            ("manual_review_rejected", "rejected", "核心经历不匹配"),
            ("manual_review_passed", "priority_outreach", "补充材料后通过"),
            ("manual_review_rejected", "rejected", "经验不足"),
            ("manual_review_passed", "talent_pool", "人工判断可入人才库"),
        ]
        for candidate_id, (reason, status, note) in zip(self.candidate_ids, human_results):
            self.repository.record_candidate_role_status_change(
                candidate_id=candidate_id,
                role_id=int(self.profile.id),
                to_status=status,
                operator="review_workbench",
                reason_code=reason,
                note=note,
            )

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_lists_and_summarizes_ai_human_comparison_samples(self) -> None:
        page = self.repository.page_ai_human_comparisons(
            role_id=int(self.profile.id), page=1, page_size=20
        )
        differences = self.repository.page_ai_human_comparisons(
            role_id=int(self.profile.id), comparison_status="disagreement", page=1, page_size=20
        )
        summary = self.repository.get_ai_human_comparison_summary(role_id=int(self.profile.id))

        self.assertEqual(page["total"], 5)
        self.assertEqual(len(page["rows"]), 5)
        self.assertEqual({row["comparison_status"] for row in page["rows"]}, {
            "agreement", "disagreement", "manual_resolved"
        })
        self.assertEqual(
            {row["difference_type"] for row in differences["rows"]},
            {"ai_overestimated", "ai_underestimated"},
        )
        self.assertTrue(all(row["human_note"] for row in page["rows"]))
        self.assertEqual(summary["compared_total"], 5)
        self.assertEqual(summary["agreement_count"], 2)
        self.assertEqual(summary["disagreement_count"], 2)
        self.assertEqual(summary["manual_resolved_count"], 1)
        self.assertEqual(summary["human_passed_count"], 3)
        self.assertEqual(summary["human_rejected_count"], 2)
        self.assertEqual(summary["agreement_rate"], 50.0)

    def test_ai_rerun_after_review_does_not_rewrite_existing_comparison(self) -> None:
        candidate_id = self.candidate_ids[0]
        before = self.repository.page_ai_human_comparisons(
            role_id=int(self.profile.id), page=1, page_size=20
        )
        before_row = next(row for row in before["rows"] if row["candidate_id"] == candidate_id)
        self.assertEqual(before_row["difference_type"], "consistent_recommendation")

        rerun_id = self.repository.create_screening_run(
            profile_id=int(self.profile.id),
            source_job_title="产品经理",
            batch_id=None,
            provider="fake",
            model="new-model",
            total_candidates=1,
        )
        new_result_id = self.repository.save_screening_result(
            ScreeningResult(
                run_id=rerun_id,
                candidate_id=candidate_id,
                rating="N",
                persona="复核后的新模型结果",
                confidence="high",
                recommended_action="",
                created_at="2026-08-07T12:00:00",
            )
        )
        self.repository.upsert_candidate_role_match(
            candidate_id=candidate_id,
            role_id=int(self.profile.id),
            latest_rating="N",
            latest_confidence="high",
            match_status="ai_screened",
            recruitment_status="priority_outreach",
            screening_result_id=new_result_id,
        )

        after = self.repository.page_ai_human_comparisons(
            role_id=int(self.profile.id), page=1, page_size=20
        )
        after_row = next(row for row in after["rows"] if row["candidate_id"] == candidate_id)

        self.assertEqual(after_row["latest_rating"], "SSR")
        self.assertEqual(after_row["difference_type"], "consistent_recommendation")


if __name__ == "__main__":
    unittest.main()
