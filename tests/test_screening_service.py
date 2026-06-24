from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai.prompt_manager import PromptManager
from ai.schemas import ScreeningDecision
from ai.screening_service import ScreeningService
from core.models import CandidateRecord, ScreeningProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class FakeProvider:
    def screen(self, system_prompt: str, candidate_text: str) -> ScreeningDecision:
        self.last_prompt = system_prompt
        self.last_candidate = candidate_text
        return ScreeningDecision(
            rating="SR",
            persona="张三｜本科背景，有 5 年 Java 项目经历；独立交付范围和业务结果尚未验证。",
            raw_response='{"rating":"SR","persona":"ok"}',
        )


class ScreeningServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "test.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        batch = self.repository.create_batch("Java工程师", "https://example.com")
        self.repository.upsert_batch_candidates(
            batch.id,
            [
                CandidateRecord(
                    candidate_key="platform:test-1",
                    raw_text_hash="hash-1",
                    job_title="Java工程师",
                    source_url="https://example.com",
                    capture_time="2026-06-12T10:00:00",
                    raw_card_text="张三 5年Java开发 本科 Spring Cloud",
                    name="张三",
                    work_experience_text="5年Java开发",
                    education_text="本科",
                    tags_text="Java | Spring Cloud",
                )
            ],
        )
        self.prompt_manager = PromptManager(Path("assets/prompts"))
        prompt = self.prompt_manager.build_from_jd("Java工程师", "本科；5年以上 Java；熟悉 Spring Cloud。")
        self.profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Java工程师",
                jd_text="本科；5年以上 Java；熟悉 Spring Cloud。",
                prompt_text=prompt,
                prompt_source="generated",
            )
        )

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_screening_run_saves_rating_and_persona(self) -> None:
        candidates = self.repository.list_screening_candidates(job_title="Java工程师")
        service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=FakeProvider(),
        )
        result = service.run(
            profile=self.profile.to_dict(),
            candidates=candidates,
            source_job_title="Java工程师",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
            origin="automation",
        )
        rows = self.repository.list_screening_results(int(result["run_id"]))
        automation_runs = self.repository.list_screening_runs(origin="automation")
        self.assertEqual(result["completed"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(automation_runs), 1)
        self.assertEqual(rows[0]["rating"], "SR")
        self.assertIn("独立交付范围", rows[0]["persona"])


if __name__ == "__main__":
    unittest.main()
