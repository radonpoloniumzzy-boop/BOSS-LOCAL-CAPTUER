from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.models import CandidateRecord, JobProfile, NextAction, RecruitmentTask
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class NextActionRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "next-actions.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.profile = self.repository.save_job_profile(
            JobProfile(
                job_title="产品经理",
                jd_text="企业软件产品",
                prompt_text="筛选产品经验",
                status="active",
            )
        )
        batch = self.repository.create_batch("产品经理", "https://example.com")
        self.repository.upsert_batch_candidates(
            int(batch.id),
            [
                CandidateRecord(
                    candidate_key="next-action:candidate",
                    raw_text_hash="next-action-hash",
                    job_title="产品经理",
                    source_url="https://example.com",
                    capture_time="2026-08-06T10:00:00",
                    raw_card_text="候选人",
                    name="行动候选人",
                )
            ],
        )
        self.candidate_id = int(self.repository.list_candidates()[0]["id"])
        self.repository.upsert_candidate_role_match(
            candidate_id=self.candidate_id,
            role_id=int(self.profile.id),
            match_status="ai_screened",
            recruitment_status="screened",
        )
        self.task = self.repository.save_recruitment_task(
            RecruitmentTask(
                name="产品经理首轮招聘",
                role_id=int(self.profile.id),
                source_url="https://example.com",
            )
        )

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_creates_filters_completes_and_summarizes_actions(self) -> None:
        today_anchor = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        overdue = self.repository.save_next_action(
            NextAction(
                subject_type="candidate_role",
                candidate_id=self.candidate_id,
                role_id=int(self.profile.id),
                action_type="follow_up",
                title="跟进候选人回复",
                owner="招聘负责人",
                due_at=(today_anchor - timedelta(days=1)).isoformat(),
                priority="high",
                note="确认意向",
            )
        )
        today = self.repository.save_next_action(
            NextAction(
                subject_type="recruitment_task",
                task_id=int(self.task.id),
                role_id=int(self.profile.id),
                action_type="manual_review",
                title="检查本轮筛选结果",
                owner="招聘负责人",
                due_at=today_anchor.isoformat(),
                priority="urgent",
            )
        )
        future = self.repository.save_next_action(
            NextAction(
                subject_type="candidate_role",
                candidate_id=self.candidate_id,
                role_id=int(self.profile.id),
                action_type="interview",
                title="安排业务面试",
                due_at=(today_anchor + timedelta(days=3)).isoformat(),
            )
        )

        overdue_rows = self.repository.page_next_actions(view="overdue", page=1, page_size=20)
        today_rows = self.repository.page_next_actions(view="today", page=1, page_size=20)
        upcoming_rows = self.repository.page_next_actions(view="next_7_days", page=1, page_size=20)
        summary = self.repository.get_next_action_summary()

        self.assertEqual([row["id"] for row in overdue_rows["rows"]], [overdue.id])
        self.assertEqual([row["id"] for row in today_rows["rows"]], [today.id])
        self.assertEqual([row["id"] for row in upcoming_rows["rows"]], [future.id])
        self.assertEqual(summary["pending_total"], 3)
        self.assertEqual(summary["overdue"], 1)
        self.assertEqual(summary["today"], 1)
        self.assertEqual(summary["next_7_days"], 1)

        completed = self.repository.set_next_action_status(int(today.id), "completed")
        completed_rows = self.repository.page_next_actions(
            view="completed", page=1, page_size=20
        )
        summary_after = self.repository.get_next_action_summary()

        self.assertEqual(completed.status, "completed")
        self.assertTrue(completed.completed_at)
        self.assertIn(int(today.id), {int(row["id"]) for row in completed_rows["rows"]})
        self.assertEqual(summary_after["pending_total"], 2)
        self.assertEqual(summary_after["completed_today"], 1)

    def test_rejects_subject_mismatch_and_updates_existing_action(self) -> None:
        with self.assertRaisesRegex(ValueError, "候选人岗位关系"):
            self.repository.save_next_action(
                NextAction(
                    subject_type="candidate_role",
                    candidate_id=99999,
                    role_id=int(self.profile.id),
                    action_type="follow_up",
                    title="无效对象",
                    due_at=datetime.now().isoformat(),
                )
            )

        action = self.repository.save_next_action(
            NextAction(
                subject_type="recruitment_task",
                task_id=int(self.task.id),
                role_id=int(self.profile.id),
                action_type="manual_review",
                title="初始标题",
                due_at=datetime.now().isoformat(),
            )
        )
        action.title = "更新后的标题"
        action.owner = "新负责人"
        updated = self.repository.save_next_action(action)

        self.assertEqual(updated.id, action.id)
        self.assertEqual(updated.title, "更新后的标题")
        self.assertEqual(updated.owner, "新负责人")

    def test_normalizes_timezone_aware_due_time_to_local_seconds(self) -> None:
        aware_due = datetime.now().astimezone().replace(microsecond=0) + timedelta(hours=2)

        action = self.repository.save_next_action(
            NextAction(
                subject_type="recruitment_task",
                task_id=int(self.task.id),
                role_id=int(self.profile.id),
                action_type="follow_up",
                title="跨时区截止时间",
                due_at=aware_due.isoformat(),
            )
        )

        expected = aware_due.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
        self.assertEqual(action.due_at, expected)
        self.assertEqual(self.repository.get_next_action(int(action.id))["due_at"], expected)


if __name__ == "__main__":
    unittest.main()
