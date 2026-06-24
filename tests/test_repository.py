from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.models import CandidateRecord, ScreeningProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class CandidateRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def _candidate(self, candidate_key: str, name: str) -> CandidateRecord:
        return CandidateRecord(
            candidate_key=candidate_key,
            raw_text_hash=f"hash-{candidate_key}",
            job_title="招聘实习生",
            source_url="https://example.com",
            capture_time="2026-04-07T10:00:00",
            raw_card_text=f"{name} 原始文本",
            name=name,
            expected_salary="10k-12k",
            work_experience_text="1年招聘",
            education_text="本科",
        )

    def test_upsert_deduplicates_candidates_and_preserves_batch_history(self) -> None:
        batch_one = self.repository.create_batch("招聘实习生", "https://example.com/page1")
        first = self._candidate("platform:1", "张三")
        second = self._candidate("platform:1", "张三")
        result_one = self.repository.upsert_batch_candidates(batch_one.id, [first, second])
        self.assertEqual(result_one["inserted_candidates"], 1)
        self.assertEqual(result_one["inserted_batch_items"], 1)

        batch_two = self.repository.create_batch("招聘实习生", "https://example.com/page2")
        result_two = self.repository.upsert_batch_candidates(batch_two.id, [first])
        self.assertEqual(result_two["inserted_candidates"], 0)
        self.assertEqual(result_two["inserted_batch_items"], 1)

        candidates = self.repository.list_candidates()
        self.assertEqual(len(candidates), 1)
        detail = self.repository.get_candidate_detail(int(candidates[0]["id"]))
        assert detail is not None
        self.assertEqual(len(detail["appearances"]), 2)

    def test_screening_profile_is_upserted_by_job_title(self) -> None:
        first = self.repository.save_screening_profile(
            ScreeningProfile(job_title="招聘实习生", jd_text="本科", prompt_text="第一版")
        )
        second = self.repository.save_screening_profile(
            ScreeningProfile(job_title="招聘实习生", jd_text="本科，招聘经验", prompt_text="第二版")
        )
        rows = self.repository.list_screening_profiles()
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prompt_text"], "第二版")

    def test_screening_runs_can_be_filtered_by_automation_origin(self) -> None:
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Java工程师", jd_text="Java", prompt_text="筛选 Java")
        )
        self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Java工程师",
            batch_id=None,
            provider="fake",
            model="manual-model",
            total_candidates=1,
        )
        automation_run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Java工程师",
            batch_id=None,
            provider="fake",
            model="automation-model",
            total_candidates=1,
            origin="automation",
        )

        automation_runs = self.repository.list_screening_runs(origin="automation")

        self.assertEqual(len(automation_runs), 1)
        self.assertEqual(automation_runs[0]["id"], automation_run_id)
        self.assertEqual(automation_runs[0]["origin"], "automation")
        version = self.db.get_connection().execute("SELECT version FROM schema_version").fetchone()
        self.assertEqual(version["version"], 3)


if __name__ == "__main__":
    unittest.main()
