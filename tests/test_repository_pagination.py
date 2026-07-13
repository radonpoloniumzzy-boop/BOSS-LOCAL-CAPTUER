from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.models import CandidateRecord, ScreeningProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class RepositoryPaginationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "pagination.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def _seed_candidates(self, count: int) -> None:
        connection = self.db.get_connection()
        rows = [
            (
                f"candidate:{index}",
                f"hash:{index}",
                "Securities Trader",
                "https://example.com",
                f"2026-07-13T12:{index % 60:02d}:00",
                f"Candidate {index} Shanghai securities trading",
                f"Candidate {index:05d}",
                "active",
                "20k-30k",
                "5 years securities trading",
                "Bachelor",
                "securities,trading",
                "summary",
                "",
                "",
                "2026-07-13T12:00:00",
                f"2026-07-13T12:{index % 60:02d}:00",
            )
            for index in range(count)
        ]
        with connection:
            connection.executemany(
                """
                INSERT INTO candidates(
                    candidate_key, raw_text_hash, job_title, source_url, capture_time,
                    raw_card_text, name, active_status, expected_salary,
                    work_experience_text, education_text, tags_text, summary_text,
                    detail_url, platform_uid, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def test_candidate_page_returns_rows_total_and_clamps_page_size(self) -> None:
        self._seed_candidates(235)

        page = self.repository.page_candidates(page=2, page_size=100)

        self.assertEqual(set(page), {"rows", "total", "page", "page_size"})
        self.assertEqual(page["total"], 235)
        self.assertEqual(page["page"], 2)
        self.assertEqual(page["page_size"], 100)
        self.assertEqual(len(page["rows"]), 100)
        self.assertNotEqual(page["rows"][0]["id"], page["rows"][-1]["id"])

        oversized = self.repository.page_candidates(page=1, page_size=9999)
        self.assertEqual(oversized["page_size"], 200)

    def test_candidate_page_filters_before_counting(self) -> None:
        self._seed_candidates(120)

        page = self.repository.page_candidates(keyword="Candidate 0001", page=1, page_size=10)

        self.assertEqual(page["total"], 10)
        self.assertEqual(len(page["rows"]), 10)

    def test_role_match_manual_review_and_task_results_share_page_contract(self) -> None:
        batch = self.repository.create_batch("Securities Trader", "https://example.com")
        candidates = [
            CandidateRecord(
                candidate_key=f"role:{index}",
                raw_text_hash=f"role-hash:{index}",
                job_title="Securities Trader",
                source_url="https://example.com",
                capture_time="2026-07-13T12:00:00",
                raw_card_text=f"Candidate {index} securities trading",
                name=f"Role Candidate {index}",
            )
            for index in range(23)
        ]
        self.repository.upsert_batch_candidates(batch.id, candidates)
        profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Securities Trader",
                jd_text="Securities trading",
                prompt_text="Evaluate trading evidence",
            )
        )
        rows = [dict(row) for row in self.repository.list_candidates()]
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Securities Trader",
            batch_id=batch.id,
            provider="openai",
            model="test-model",
            total_candidates=len(rows),
        )
        decisions = {
            int(row["id"]): {"route": "manual_check", "reason": "needs evidence"}
            for row in rows
        }
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=rows,
            model_name="test-model",
            prompt_version="v1",
            request_hashes={int(row["id"]): f"request:{row['id']}" for row in rows},
            prescreen_decisions=decisions,
        )

        pages = [
            self.repository.page_candidate_role_matches(role_id=int(profile.id), page=2, page_size=10),
            self.repository.page_manual_review_candidates(role_id=int(profile.id), page=2, page_size=10),
            self.repository.page_screening_task_results(run_id, page=2, page_size=10),
        ]

        for page in pages:
            self.assertEqual(set(page), {"rows", "total", "page", "page_size"})
            self.assertEqual(page["total"], 23)
            self.assertEqual(page["page"], 2)
            self.assertEqual(len(page["rows"]), 10)

    def test_ten_thousand_candidate_page_query_stays_within_database_budget(self) -> None:
        self._seed_candidates(10_000)

        started = time.perf_counter()
        page = self.repository.page_candidates(page=1, page_size=100)
        elapsed = time.perf_counter() - started

        self.assertEqual(page["total"], 10_000)
        self.assertEqual(len(page["rows"]), 100)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
