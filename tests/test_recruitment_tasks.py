from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.models import JobProfile, RecruitmentTask
from storage.db import DatabaseManager
from storage.export_service import ExportService
from storage.repository import CandidateRepository


class RecruitmentTaskRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "tasks.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.profile = self.repository.save_job_profile(
            JobProfile(
                job_title="高级招聘顾问",
                jd_text="负责关键岗位招聘与人才 Mapping",
                prompt_text="筛选完整招聘闭环经验",
                status="active",
            )
        )

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_task_locks_job_version_and_aggregates_work_outputs(self) -> None:
        task = self.repository.save_recruitment_task(
            RecruitmentTask(
                name="BOSS 第一轮 Mapping",
                role_id=int(self.profile.id),
                platform="boss",
                source_url="https://www.zhipin.com/web/geek/recommend",
                target_candidates=80,
                target_ssr=5,
                minimum_rating="SR",
                view_quota=120,
                greeting_quota=30,
            )
        )
        self.profile.jd_text = "后来修改的 JD"
        self.repository.save_job_profile(self.profile)

        self.assertEqual(task.profile_version, 1)
        self.assertEqual(self.repository.get_recruitment_task(int(task.id))["profile_version"], 1)

        running = self.repository.set_recruitment_task_status(int(task.id), "running")
        task.target_candidates = 999
        with self.assertRaisesRegex(ValueError, "启动后不能修改"):
            self.repository.save_recruitment_task(task)
        batch = self.repository.create_batch(
            "高级招聘顾问",
            task.source_url,
            role_id=int(self.profile.id),
            task_id=int(task.id),
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(self.profile.id),
            source_job_title="高级招聘顾问",
            batch_id=int(batch.id),
            provider="fake",
            model="fake-model",
            total_candidates=0,
            task_id=int(task.id),
        )
        recorded_task_id = self.repository.record_export(
            file_path=str(Path(self.temp_dir.name) / "result.csv"),
            export_format="csv",
            row_count=0,
            batch_id=int(batch.id),
            role_id=int(self.profile.id),
        )
        summary = self.repository.get_recruitment_task_summary(int(task.id))

        self.assertEqual(running.status, "running")
        self.assertEqual(batch.task_id, task.id)
        self.assertEqual(summary["batch_count"], 1)
        self.assertEqual(summary["run_count"], 1)
        self.assertEqual(summary["export_count"], 1)
        self.assertEqual(recorded_task_id, task.id)
        self.assertEqual(self.repository.get_screening_run(run_id)["profile_version"], 1)
        self.assertEqual(summary["target_candidates"], 80)

    def test_task_rejects_role_mismatch_and_terminal_reopen(self) -> None:
        task = self.repository.save_recruitment_task(
            RecruitmentTask(
                name="猎聘补充",
                role_id=int(self.profile.id),
                platform="liepin",
                source_url="https://lpt.liepin.com/recommend",
            )
        )
        other = self.repository.save_job_profile(
            JobProfile(job_title="另一岗位", jd_text="JD", prompt_text="Prompt", status="active")
        )

        with self.assertRaisesRegex(ValueError, "岗位不一致"):
            self.repository.create_batch(
                "另一岗位", "https://example.com", role_id=int(other.id), task_id=int(task.id)
            )

        self.repository.set_recruitment_task_status(int(task.id), "cancelled")
        with self.assertRaisesRegex(ValueError, "终态"):
            self.repository.set_recruitment_task_status(int(task.id), "running")

    def test_task_report_export_contains_configuration_progress_and_outputs(self) -> None:
        task = self.repository.save_recruitment_task(
            RecruitmentTask(
                name="BOSS 第一轮 Mapping",
                role_id=int(self.profile.id),
                platform="boss",
                source_url="https://www.zhipin.com/web/geek/recommend",
                target_candidates=80,
                target_ssr=5,
                minimum_rating="SR",
                view_quota=120,
                greeting_quota=30,
            )
        )
        self.repository.set_recruitment_task_status(int(task.id), "running")
        batch = self.repository.create_batch(
            "高级招聘顾问",
            task.source_url,
            role_id=int(self.profile.id),
            task_id=int(task.id),
        )
        output_path = Path(self.temp_dir.name) / "candidate-list.csv"
        output_path.write_text("name\n", encoding="utf-8")
        self.repository.record_export(
            file_path=str(output_path),
            export_format="csv",
            row_count=0,
            batch_id=int(batch.id),
            role_id=int(self.profile.id),
        )
        for index in range(50):
            extra_path = Path(self.temp_dir.name) / f"candidate-list-{index}.csv"
            extra_path.write_text("name\n", encoding="utf-8")
            self.repository.record_export(
                file_path=str(extra_path),
                export_format="csv",
                row_count=0,
                batch_id=int(batch.id),
                role_id=int(self.profile.id),
            )
        self.profile.job_title = "后来改名的岗位"
        self.repository.save_job_profile(self.profile)
        service = ExportService(self.repository)

        result = service.export_recruitment_task_report(
            int(task.id), Path(self.temp_dir.name) / "exports"
        )

        report = Path(result.file_path).read_text(encoding="utf-8")
        self.assertEqual(result.export_format, "task_markdown")
        self.assertIn("# 招聘任务报告｜BOSS 第一轮 Mapping", report)
        self.assertIn("岗位：高级招聘顾问", report)
        self.assertNotIn("岗位：后来改名的岗位", report)
        self.assertIn("岗位版本：V1", report)
        self.assertIn("目标候选人：80", report)
        self.assertIn("SSR 目标：5", report)
        self.assertIn("采集批次：1", report)
        self.assertIn("candidate-list.csv", report)


if __name__ == "__main__":
    unittest.main()
