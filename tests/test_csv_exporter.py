from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from core.models import DEFAULT_CSV_COLUMNS, CandidateRecord, ScreeningProfile, ScreeningResult
from storage.csv_exporter import CsvExporter
from storage.db import DatabaseManager
from storage.export_service import ExportService
from storage.repository import CandidateRepository


class ExportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.export_service = ExportService(self.repository)
        self.csv_exporter = CsvExporter(self.repository)

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_csv_export_batch_uses_requested_column_order(self) -> None:
        batch = self._insert_sample_candidate()
        export_dir = Path(self.temp_dir.name) / "exports"

        result = self.csv_exporter.export(
            mode="batch",
            export_dir=export_dir,
            columns=["name", "expected_salary", "raw_card_text"],
            batch_id=batch.id,
            job_title="校招 C++ 工程师",
        )

        self.assertEqual(result.export_format, "csv")
        self.assertTrue(Path(result.file_path).exists())
        with Path(result.file_path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        self.assertEqual(rows[0], ["name", "expected_salary", "raw_card_text"])
        self.assertEqual(rows[1][0], "张三")

    def test_jsonl_export_keeps_structured_fields(self) -> None:
        batch = self._insert_sample_candidate()
        export_dir = Path(self.temp_dir.name) / "exports"

        result = self.export_service.export(
            export_format="jsonl",
            mode="batch",
            export_dir=export_dir,
            columns=["name", "expected_salary", "raw_card_text"],
            batch_id=batch.id,
            job_title="校招 C++ 工程师",
        )

        self.assertEqual(result.export_format, "jsonl")
        lines = Path(result.file_path).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["name"], "张三")
        self.assertEqual(payload["raw_card_text"], "张三 原始文本")
        self.assertEqual(payload["batch_id"], batch.id)

    def test_default_csv_export_includes_reusable_recruitment_fields(self) -> None:
        batch = self._insert_sample_candidate()
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="SaaS Sales",
                jd_text="B2B SaaS sales",
                prompt_text="Rate sales candidates",
            )
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="SaaS Sales",
            batch_id=batch.id,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        result_id = self.repository.save_screening_result(
            ScreeningResult(
                run_id=run_id,
                candidate_id=int(candidate["id"]),
                rating="SSR",
                persona="Strong SaaS sales evidence.",
                confidence="high",
                evidence_json='[{"item":"SaaS","evidence":"5 years"}]',
                gap_json='["quota not verified"]',
                risk_json='["frequent job changes"]',
                recommended_action="priority_outreach",
            )
        )
        self.repository.upsert_candidate_role_match(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            latest_rating="SSR",
            latest_confidence="high",
            match_status="ai_screened",
            screening_result_id=result_id,
            human_decision="manual_review_passed",
            recruitment_status="screened",
        )
        self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            to_status="screened",
            operator="tester",
            reason_code="priority_candidate",
            note="Good fit for sales outreach.",
        )
        export_dir = Path(self.temp_dir.name) / "exports"

        result = self.export_service.export(
            export_format="csv",
            mode="batch",
            export_dir=export_dir,
            columns=list(DEFAULT_CSV_COLUMNS),
            batch_id=batch.id,
            latest_reason_code="priority_candidate",
            job_title="",
        )

        with Path(result.file_path).open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(result.row_count, 1)
        self.assertEqual(rows[0]["name"], "张三")
        self.assertEqual(rows[0]["role_title"], "SaaS Sales")
        self.assertEqual(rows[0]["latest_rating"], "SSR")
        self.assertEqual(rows[0]["latest_confidence"], "high")
        self.assertEqual(rows[0]["recommended_action"], "priority_outreach")
        self.assertIn("SaaS", rows[0]["evidence_json"])
        self.assertIn("quota not verified", rows[0]["gap_json"])
        self.assertIn("frequent job changes", rows[0]["risk_json"])
        self.assertEqual(rows[0]["match_status"], "ai_screened")
        self.assertEqual(rows[0]["recruitment_status"], "screened")
        self.assertEqual(rows[0]["human_decision"], "manual_review_passed")
        self.assertEqual(rows[0]["latest_status_to"], "screened")
        self.assertEqual(rows[0]["latest_reason_code"], "priority_candidate")
        self.assertEqual(rows[0]["latest_status_note"], "Good fit for sales outreach.")
        self.assertIn("city", rows[0])
        self.assertIn("years_experience", rows[0])
        self.assertIn("job_track", rows[0])

    def test_markdown_export_contains_summary_sections(self) -> None:
        batch = self._insert_sample_candidate()
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="SaaS Sales",
                jd_text="B2B SaaS sales",
                prompt_text="Rate sales candidates",
            )
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="SaaS Sales",
            batch_id=batch.id,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        result_id = self.repository.save_screening_result(
            ScreeningResult(
                run_id=run_id,
                candidate_id=int(candidate["id"]),
                rating="SSR",
                persona="Strong SaaS sales evidence.",
                confidence="high",
                evidence_json='[{"item":"SaaS","evidence":"5 years"}]',
                gap_json='["quota not verified"]',
                risk_json='[]',
                recommended_action="priority_outreach",
            )
        )
        self.repository.upsert_candidate_role_match(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            latest_rating="SSR",
            latest_confidence="high",
            match_status="ai_screened",
            screening_result_id=result_id,
            human_decision="manual_review_passed",
            recruitment_status="screened",
        )
        self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            to_status="screened",
            operator="tester",
            reason_code="priority_candidate",
            note="Good fit for sales outreach.",
        )
        export_dir = Path(self.temp_dir.name) / "exports"

        result = self.export_service.export(
            export_format="markdown",
            mode="batch",
            export_dir=export_dir,
            columns=["name", "expected_salary", "raw_card_text"],
            batch_id=batch.id,
            job_title="校招 C++ 工程师",
        )

        self.assertEqual(result.export_format, "markdown")
        content = Path(result.file_path).read_text(encoding="utf-8")
        self.assertIn("# 候选人导出摘要", content)
        self.assertIn("## 1. 张三", content)
        self.assertIn("- AI匹配岗位：SaaS Sales", content)
        self.assertIn("- AI评级：SSR", content)
        self.assertIn("- AI置信度：high", content)
        self.assertIn("- AI建议：priority_outreach", content)
        self.assertIn("SaaS", content)
        self.assertIn("quota not verified", content)
        self.assertIn("- 招聘阶段：screened", content)
        self.assertIn("- 人工复核：manual_review_passed", content)
        self.assertIn("- 最近原因：priority_candidate", content)
        self.assertIn("- 最近备注：Good fit for sales outreach.", content)
        self.assertIn("- 岗位方向：", content)
        self.assertIn("### 原始卡片文本", content)
        self.assertIn("张三 原始文本", content)

    def test_batch_export_filename_identifies_raw_capture_batch_job_and_time(self) -> None:
        batch = self._insert_sample_candidate()
        result = self.export_service.export(
            export_format="csv",
            mode="batch",
            export_dir=Path(self.temp_dir.name) / "exports",
            columns=["name"],
            batch_id=batch.id,
            job_title="Securities Trader",
        )

        self.assertRegex(
            Path(result.file_path).name,
            rf"^采集批次{batch.id}_Securities Trader_原始采集_\d{{8}}-\d{{6}}\.csv$",
        )

    def test_screened_batch_export_filename_identifies_screening_run(self) -> None:
        batch = self._insert_sample_candidate()
        profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Securities Trader",
                jd_text="Trading execution",
                prompt_text="Rate candidates",
            )
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Securities Trader",
            batch_id=batch.id,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        self.repository.finalize_screening_run(run_id, "completed", 1, 0)

        result = self.export_service.export(
            export_format="csv",
            mode="batch",
            export_dir=Path(self.temp_dir.name) / "exports",
            columns=["name"],
            batch_id=batch.id,
            job_title="Securities Trader",
            screening_run_id=run_id,
        )

        self.assertRegex(
            Path(result.file_path).name,
            rf"^采集批次{batch.id}_Securities Trader_初筛任务{run_id}_\d{{8}}-\d{{6}}\.csv$",
        )

    def test_exact_screening_run_export_does_not_use_a_later_rating(self) -> None:
        batch = self._insert_sample_candidate()
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Trader", jd_text="Trading", prompt_text="Rate")
        )
        first_run = self.repository.create_screening_run(
            profile_id=int(profile.id), source_job_title="Trader", batch_id=batch.id,
            provider="fake", model="m1", total_candidates=1,
        )
        self.repository.save_screening_result(
            ScreeningResult(
                run_id=first_run, candidate_id=int(candidate["id"]), rating="SR",
                persona="first run", confidence="high",
            )
        )
        self.repository.finalize_screening_run(first_run, "completed", 1, 0)
        second_run = self.repository.create_screening_run(
            profile_id=int(profile.id), source_job_title="Trader", batch_id=batch.id,
            provider="fake", model="m2", total_candidates=1,
        )
        second_result = self.repository.save_screening_result(
            ScreeningResult(
                run_id=second_run, candidate_id=int(candidate["id"]), rating="N",
                persona="later run", confidence="medium",
            )
        )
        self.repository.finalize_screening_run(second_run, "completed", 1, 0)
        self.repository.upsert_candidate_role_match(
            candidate_id=int(candidate["id"]), role_id=int(profile.id),
            latest_rating="N", latest_confidence="medium", match_status="ai_screened",
            screening_result_id=second_result,
        )

        result = self.export_service.export(
            export_format="csv", mode="batch",
            export_dir=Path(self.temp_dir.name) / "exports",
            columns=["name", "latest_rating", "persona"],
            batch_id=batch.id, job_title="Trader", screening_run_id=first_run,
        )

        with Path(result.file_path).open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["latest_rating"], "SR")
        self.assertEqual(rows[0]["persona"], "first run")
        self.assertIn(f"初筛任务{first_run}", Path(result.file_path).name)

    def _insert_sample_candidate(self):
        batch = self.repository.create_batch("校招 C++ 工程师", "https://example.com")
        candidate = CandidateRecord(
            candidate_key="platform:1",
            raw_text_hash="hash-1",
            job_title="校招 C++ 工程师",
            source_url="https://example.com",
            capture_time="2026-04-07T10:00:00",
            raw_card_text="张三 原始文本",
            name="张三",
            active_status="今日活跃",
            expected_salary="10k-12k",
            work_experience_text="1 年 C++ 开发",
            education_text="本科",
            tags_text="C++, Linux",
            summary_text="做过编译器和基础库。",
            detail_url="https://example.com/detail/1",
        )
        self.repository.upsert_batch_candidates(batch.id, [candidate])
        return batch


if __name__ == "__main__":
    unittest.main()
