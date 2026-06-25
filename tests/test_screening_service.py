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
            persona="Java background with Spring Cloud evidence.",
            raw_response='{"rating":"SR","persona":"ok"}',
            confidence="medium",
            evidence=[{"item": "Java", "evidence": "5 years Java development"}],
            gaps=["production scale not shown"],
            risks=[],
            recommended_action="normal_review",
        )


class FlakyProvider:
    def __init__(self) -> None:
        self.calls = 0

    def screen(self, _system_prompt: str, _candidate_text: str) -> ScreeningDecision:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary outage")
        return ScreeningDecision(
            rating="SSR",
            persona="Recovered after retry.",
            raw_response='{"rating":"SSR","persona":"retry ok"}',
        )


class AlwaysFailProvider:
    def __init__(self) -> None:
        self.calls = 0

    def screen(self, _system_prompt: str, _candidate_text: str) -> ScreeningDecision:
        self.calls += 1
        raise RuntimeError("provider down")


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def screen(self, _system_prompt: str, _candidate_text: str) -> ScreeningDecision:
        self.calls += 1
        return ScreeningDecision(
            rating="UR",
            persona="Cached source result.",
            raw_response='{"rating":"UR","persona":"cached"}',
        )


class ScreeningServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "test.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        batch = self.repository.create_batch("Java Engineer", "https://example.com")
        self.repository.upsert_batch_candidates(
            batch.id,
            [
                CandidateRecord(
                    candidate_key="platform:test-1",
                    raw_text_hash="hash-1",
                    job_title="Java Engineer",
                    source_url="https://example.com",
                    capture_time="2026-06-12T10:00:00",
                    raw_card_text="Alice 5 years Java development Bachelor Spring Cloud",
                    name="Alice",
                    work_experience_text="5 years Java development",
                    education_text="Bachelor",
                    tags_text="Java | Spring Cloud",
                )
            ],
        )
        self.prompt_manager = PromptManager(Path("assets/prompts"))
        prompt = self.prompt_manager.build_from_jd(
            "Java Engineer",
            "Bachelor, 5+ years Java, familiar with Spring Cloud.",
        )
        self.profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Java Engineer",
                jd_text="Bachelor, 5+ years Java, familiar with Spring Cloud.",
                prompt_text=prompt,
                prompt_source="generated",
            )
        )

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_screening_run_saves_rating_and_persona(self) -> None:
        candidates = self.repository.list_screening_candidates(job_title="Java Engineer")
        service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=FakeProvider(),
            retry_backoff_base_seconds=0,
        )
        result = service.run(
            profile=self.profile.to_dict(),
            candidates=candidates,
            source_job_title="Java Engineer",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
            origin="automation",
        )
        rows = self.repository.list_screening_results(int(result["run_id"]))
        automation_runs = self.repository.list_screening_runs(origin="automation")
        tasks = self.repository.list_screening_tasks(int(result["run_id"]))
        self.assertEqual(result["completed"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(len(automation_runs), 1)
        self.assertEqual(rows[0]["rating"], "SR")
        self.assertEqual(rows[0]["confidence"], "medium")
        self.assertEqual(rows[0]["recommended_action"], "normal_review")
        self.assertIn("production scale", rows[0]["gap_json"])
        self.assertEqual(tasks[0]["status"], "success")
        self.assertEqual(tasks[0]["result_source"], "model")
        self.assertIn("Java background", rows[0]["persona"])

    def test_screening_task_retries_transient_failure(self) -> None:
        candidates = self.repository.list_screening_candidates(job_title="Java Engineer")
        provider = FlakyProvider()
        service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=provider,
            max_retry_count=1,
            retry_backoff_base_seconds=0,
        )

        result = service.run(
            profile=self.profile.to_dict(),
            candidates=candidates,
            source_job_title="Java Engineer",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
        )

        tasks = self.repository.list_screening_tasks(int(result["run_id"]))
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(tasks[0]["status"], "success")
        self.assertEqual(tasks[0]["retry_count"], 1)

    def test_screening_task_records_terminal_failure(self) -> None:
        candidates = self.repository.list_screening_candidates(job_title="Java Engineer")
        provider = AlwaysFailProvider()
        service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=provider,
            max_retry_count=1,
            retry_backoff_base_seconds=0,
        )

        result = service.run(
            profile=self.profile.to_dict(),
            candidates=candidates,
            source_job_title="Java Engineer",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
        )

        tasks = self.repository.list_screening_tasks(int(result["run_id"]))
        rows = self.repository.list_screening_results(int(result["run_id"]))
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(tasks[0]["status"], "failed")
        self.assertEqual(tasks[0]["retry_count"], 2)
        self.assertEqual(rows[0]["status"], "failed")

    def test_same_request_reuses_cached_result_without_model_call(self) -> None:
        candidates = self.repository.list_screening_candidates(job_title="Java Engineer")
        first_provider = CountingProvider()
        first_service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=first_provider,
            retry_backoff_base_seconds=0,
        )
        first = first_service.run(
            profile=self.profile.to_dict(),
            candidates=candidates,
            source_job_title="Java Engineer",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
        )

        second_provider = AlwaysFailProvider()
        second_service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=second_provider,
            retry_backoff_base_seconds=0,
        )
        second = second_service.run(
            profile=self.profile.to_dict(),
            candidates=candidates,
            source_job_title="Java Engineer",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
        )

        rows = self.repository.list_screening_results(int(second["run_id"]))
        first_summary = self.repository.get_screening_efficiency_summary(int(first["run_id"]))
        second_tasks = self.repository.list_screening_tasks(int(second["run_id"]))
        second_summary = self.repository.get_screening_efficiency_summary(int(second["run_id"]))
        self.assertEqual(first_provider.calls, 1)
        self.assertEqual(second_provider.calls, 0)
        self.assertEqual(second["completed"], 1)
        self.assertEqual(rows[0]["rating"], "UR")
        self.assertEqual(first_summary["model_calls"], 1)
        self.assertEqual(second_tasks[0]["result_source"], "cached")
        self.assertEqual(second_summary["model_calls"], 0)
        self.assertEqual(second_summary["cached_reuses"], 1)

    def test_resumed_run_uses_task_snapshot_for_cache_after_profile_edit(self) -> None:
        candidates = self.repository.list_screening_candidates(job_title="Java Engineer")
        candidate_id = int(candidates[0]["id"])
        original_profile = self.profile.to_dict()
        prompt_text = self.prompt_manager.finalize_prompt(
            str(original_profile["prompt_text"]),
            str(original_profile["prompt_source"]),
            str(original_profile["job_title"]),
            str(original_profile["jd_text"]),
        )
        prompt_version = ScreeningService._prompt_version(original_profile)
        candidate_text = ScreeningService._candidate_text(candidates[0])
        request_hash = ScreeningService._request_payload_hash(
            provider_name="fake",
            model="fake-model",
            prompt_version=prompt_version,
            prompt_text=prompt_text,
            candidate_text=candidate_text,
        )
        first_provider = CountingProvider()
        first_service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=first_provider,
            retry_backoff_base_seconds=0,
        )
        first_service.run(
            profile=original_profile,
            candidates=candidates,
            source_job_title="Java Engineer",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(self.profile.id or 0),
            source_job_title="Java Engineer",
            batch_id=None,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(self.profile.id or 0),
            candidates=candidates,
            model_name="fake-model",
            prompt_version=prompt_version,
            request_hashes={candidate_id: request_hash},
            prompt_text=prompt_text,
            candidate_texts={candidate_id: candidate_text},
        )
        edited_prompt = self.prompt_manager.build_from_jd(
            "Java Engineer",
            "Bachelor, 8+ years Java, distributed systems, and mentoring.",
        )
        edited_profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Java Engineer",
                jd_text="Bachelor, 8+ years Java, distributed systems, and mentoring.",
                prompt_text=edited_prompt,
                prompt_source="generated",
            )
        )

        fail_provider = AlwaysFailProvider()
        resumed_service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=fail_provider,
            retry_backoff_base_seconds=0,
        )
        resumed = resumed_service.run(
            profile=edited_profile.to_dict(),
            candidates=self.repository.list_screening_run_candidates(run_id),
            source_job_title="Java Engineer",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
            run_id=run_id,
        )

        tasks = self.repository.list_screening_tasks(run_id)
        rows = self.repository.list_screening_results(run_id)
        self.assertEqual(first_provider.calls, 1)
        self.assertEqual(fail_provider.calls, 0)
        self.assertEqual(resumed["completed"], 1)
        self.assertEqual(rows[0]["rating"], "UR")
        self.assertEqual(tasks[0]["result_source"], "cached")
        self.assertEqual(tasks[0]["prompt_text"], prompt_text)
        self.assertEqual(tasks[0]["candidate_text"], candidate_text)

    def test_legacy_pending_task_refreshes_snapshot_before_model_call(self) -> None:
        candidates = self.repository.list_screening_candidates(job_title="Java Engineer")
        candidate_id = int(candidates[0]["id"])
        original_profile = self.profile.to_dict()
        original_prompt = self.prompt_manager.finalize_prompt(
            str(original_profile["prompt_text"]),
            str(original_profile["prompt_source"]),
            str(original_profile["job_title"]),
            str(original_profile["jd_text"]),
        )
        original_prompt_version = ScreeningService._prompt_version(original_profile)
        candidate_text = ScreeningService._candidate_text(candidates[0])
        original_hash = ScreeningService._request_payload_hash(
            provider_name="fake",
            model="fake-model",
            prompt_version=original_prompt_version,
            prompt_text=original_prompt,
            candidate_text=candidate_text,
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(self.profile.id or 0),
            source_job_title="Java Engineer",
            batch_id=None,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(self.profile.id or 0),
            candidates=candidates,
            model_name="fake-model",
            prompt_version=original_prompt_version,
            request_hashes={candidate_id: original_hash},
        )
        edited_prompt = self.prompt_manager.build_from_jd(
            "Java Engineer",
            "Bachelor, 8+ years Java, distributed systems, and mentoring.",
        )
        edited_profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Java Engineer",
                jd_text="Bachelor, 8+ years Java, distributed systems, and mentoring.",
                prompt_text=edited_prompt,
                prompt_source="generated",
            )
        )
        edited_profile_dict = edited_profile.to_dict()
        current_prompt = self.prompt_manager.finalize_prompt(
            str(edited_profile_dict["prompt_text"]),
            str(edited_profile_dict["prompt_source"]),
            str(edited_profile_dict["job_title"]),
            str(edited_profile_dict["jd_text"]),
        )
        current_prompt_version = ScreeningService._prompt_version(edited_profile_dict)
        current_hash = ScreeningService._request_payload_hash(
            provider_name="fake",
            model="fake-model",
            prompt_version=current_prompt_version,
            prompt_text=current_prompt,
            candidate_text=candidate_text,
        )
        provider = FakeProvider()
        service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=provider,
            retry_backoff_base_seconds=0,
        )

        resumed = service.run(
            profile=edited_profile_dict,
            candidates=self.repository.list_screening_run_candidates(run_id),
            source_job_title="Java Engineer",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
            run_id=run_id,
        )

        tasks = self.repository.list_screening_tasks(run_id)
        self.assertEqual(resumed["completed"], 1)
        self.assertEqual(provider.last_prompt, current_prompt)
        self.assertEqual(tasks[0]["result_source"], "model")
        self.assertEqual(tasks[0]["prompt_text"], current_prompt)
        self.assertEqual(tasks[0]["candidate_text"], candidate_text)
        self.assertEqual(tasks[0]["request_payload_hash"], current_hash)

    def test_sparse_candidates_are_routed_without_model_call(self) -> None:
        sparse_batch = self.repository.create_batch("Java Engineer", "https://example.com/sparse")
        self.repository.upsert_batch_candidates(
            sparse_batch.id,
            [
                CandidateRecord(
                    candidate_key="platform:sparse-1",
                    raw_text_hash="hash-sparse-1",
                    job_title="Java Engineer",
                    source_url="https://example.com/sparse",
                    capture_time="2026-06-12T11:00:00",
                    raw_card_text="Mentions Java only, no resume details.",
                    name="",
                )
            ],
        )
        candidates = self.repository.list_screening_candidates(job_title="Java Engineer")
        provider = CountingProvider()
        service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=provider,
            retry_backoff_base_seconds=0,
        )

        result = service.run(
            profile=self.profile.to_dict(),
            candidates=candidates,
            source_job_title="Java Engineer",
            batch_id=None,
            provider_name="fake",
            model="fake-model",
        )

        tasks = self.repository.list_screening_tasks(int(result["run_id"]))
        task_rows = self.repository.list_screening_task_results(int(result["run_id"]))
        result_rows = self.repository.list_screening_results(int(result["run_id"]))
        statuses = {str(task["status"]) for task in tasks}
        sparse_row = next(row for row in task_rows if row["task_status"] == "manual_check")

        self.assertEqual(provider.calls, 1)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["manual_check"], 1)
        self.assertEqual(len(result_rows), 1)
        self.assertEqual(statuses, {"success", "manual_check"})
        self.assertEqual(sparse_row["route"], "manual_check")
        self.assertIsNone(sparse_row["rating"])
        summary = self.repository.get_screening_efficiency_summary(int(result["run_id"]))
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["ai_routed"], 1)
        self.assertEqual(summary["avoided_by_rules"], 1)
        self.assertEqual(summary["manual_check"], 1)
        self.assertEqual(summary["model_calls"], 1)
        self.assertEqual(summary["cached_reuses"], 0)

    def test_thousand_candidate_run_can_resume_without_duplicate_model_calls(self) -> None:
        batch = self.repository.create_batch("Java Engineer", "https://example.com/scale")
        self.repository.upsert_batch_candidates(
            batch.id,
            [
                CandidateRecord(
                    candidate_key=f"platform:scale-{index}",
                    raw_text_hash=f"hash-scale-{index}",
                    job_title="Java Engineer",
                    source_url="https://example.com/scale",
                    capture_time="2026-06-12T12:00:00",
                    raw_card_text=f"Candidate {index} 5 years Java Spring Cloud",
                    name=f"Candidate {index}",
                    work_experience_text="5 years Java development",
                    education_text="Bachelor",
                    tags_text="Java | Spring Cloud",
                )
                for index in range(1000)
            ],
        )
        candidates = self.repository.list_screening_candidates(batch_id=batch.id)
        stop_after = 137
        first_provider = CountingProvider()
        first_service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=first_provider,
            retry_backoff_base_seconds=0,
        )

        def stop_after_partial_run(progress) -> None:
            if progress.completed >= stop_after:
                first_service.request_stop()

        first = first_service.run(
            profile=self.profile.to_dict(),
            candidates=candidates,
            source_job_title="Java Engineer",
            batch_id=batch.id,
            provider_name="fake",
            model="fake-model",
            progress_callback=stop_after_partial_run,
        )
        run_id = int(first["run_id"])
        interrupted_counts = self.repository.get_screening_task_counts(run_id)

        self.assertEqual(first["status"], "stopped")
        self.assertEqual(first["completed"], stop_after)
        self.assertEqual(first_provider.calls, stop_after)
        self.assertEqual(interrupted_counts["success"], stop_after)
        self.assertEqual(interrupted_counts["pending"], 1000 - stop_after)

        claimed_before_shutdown = self.repository.claim_next_screening_task(run_id)
        self.assertIsNotNone(claimed_before_shutdown)
        claimed_counts = self.repository.get_screening_task_counts(run_id)
        self.assertEqual(claimed_counts["running"], 1)
        self.assertEqual(claimed_counts["pending"], 1000 - stop_after - 1)
        recovered = self.repository.recover_interrupted_screening_tasks()
        recovered_counts = self.repository.get_screening_task_counts(run_id)
        self.assertEqual(recovered, 1)
        self.assertEqual(recovered_counts["running"], 0)
        self.assertEqual(recovered_counts["pending"], 1000 - stop_after)

        resumed_candidates = self.repository.list_screening_run_candidates(run_id)
        second_provider = CountingProvider()
        second_service = ScreeningService(
            repository=self.repository,
            prompt_manager=self.prompt_manager,
            provider=second_provider,
            retry_backoff_base_seconds=0,
        )
        resumed = second_service.run(
            profile=self.profile.to_dict(),
            candidates=resumed_candidates,
            source_job_title="Java Engineer",
            batch_id=batch.id,
            provider_name="fake",
            model="fake-model",
            run_id=run_id,
        )

        final_counts = self.repository.get_screening_task_counts(run_id)
        result_rows = self.repository.list_screening_results(run_id)

        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["completed"], 1000)
        self.assertEqual(second_provider.calls, 1000 - stop_after)
        self.assertEqual(final_counts["success"], 1000)
        self.assertEqual(final_counts["pending"], 0)
        self.assertEqual(len(result_rows), 1000)
        self.assertEqual(first_provider.calls + second_provider.calls, 1000)


if __name__ == "__main__":
    unittest.main()
