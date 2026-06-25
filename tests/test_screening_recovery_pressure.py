from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import os
from pathlib import Path

from ai.prompt_manager import PromptManager
from ai.schemas import ScreeningDecision
from ai.screening_service import ScreeningService
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class ResumeCountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def screen(self, _system_prompt: str, _candidate_text: str) -> ScreeningDecision:
        self.calls += 1
        return ScreeningDecision(
            rating="SR",
            persona="Resume worker completed this candidate.",
            raw_response='{"rating":"SR","persona":"resumed"}',
            confidence="medium",
        )


class ScreeningRecoveryPressureTest(unittest.TestCase):
    def test_real_process_crash_recovers_200_and_1000_candidate_runs(self) -> None:
        for total_candidates, crash_after in [(200, 50), (1000, 137)]:
            with self.subTest(total_candidates=total_candidates, crash_after=crash_after):
                self._run_crash_recovery_case(total_candidates, crash_after)

    def _run_crash_recovery_case(self, total_candidates: int, crash_after: int) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "pressure.db"
            run_id_path = tmp_path / "run_id.txt"
            call_log_path = tmp_path / "calls.txt"
            helper = Path(__file__).parent / "helpers" / "screening_crash_worker.py"
            project_root = Path(__file__).resolve().parents[1]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(project_root)
            crashed = subprocess.run(
                [
                    sys.executable,
                    str(helper),
                    str(db_path),
                    str(run_id_path),
                    str(call_log_path),
                    str(total_candidates),
                    str(crash_after),
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(
                crashed.returncode,
                87,
                msg=f"stdout={crashed.stdout}\nstderr={crashed.stderr}",
            )
            self.assertEqual(int(call_log_path.read_text(encoding="utf-8")), crash_after + 1)
            run_id = int(run_id_path.read_text(encoding="utf-8"))

            db = DatabaseManager(db_path)
            db.initialize()
            repository = CandidateRepository(db)
            interrupted_counts = repository.get_screening_task_counts(run_id)
            self.assertEqual(interrupted_counts["success"], crash_after)
            self.assertEqual(interrupted_counts["running"], 1)

            recovered = repository.recover_interrupted_screening_tasks()
            recovered_counts = repository.get_screening_task_counts(run_id)
            self.assertEqual(recovered, 1)
            self.assertEqual(recovered_counts["running"], 0)
            self.assertEqual(recovered_counts["pending"], total_candidates - crash_after)

            run = repository.get_screening_run(run_id)
            self.assertIsNotNone(run)
            assert run is not None
            profile_row = repository.get_screening_profile(int(run["profile_id"]))
            self.assertIsNotNone(profile_row)
            assert profile_row is not None
            profile = dict(profile_row)
            provider = ResumeCountingProvider()
            service = ScreeningService(
                repository=repository,
                prompt_manager=PromptManager(Path("assets/prompts")),
                provider=provider,
                retry_backoff_base_seconds=0,
                worker_id="resume-worker",
                task_lock_timeout_seconds=60,
            )
            resumed = service.run(
                profile=profile,
                candidates=repository.list_screening_run_candidates(run_id),
                source_job_title=str(run["source_job_title"] or ""),
                batch_id=int(run["batch_id"]) if run["batch_id"] is not None else None,
                provider_name=str(run["provider"] or "fake"),
                model=str(run["model"] or "fake-model"),
                run_id=run_id,
            )

            final_counts = repository.get_screening_task_counts(run_id)
            result_rows = repository.list_screening_results(run_id)
            self.assertEqual(provider.calls, total_candidates - crash_after)
            self.assertEqual(resumed["status"], "completed")
            self.assertEqual(resumed["completed"], total_candidates)
            self.assertEqual(final_counts["success"], total_candidates)
            self.assertEqual(final_counts["failed"], 0)
            self.assertEqual(len(result_rows), total_candidates)
            db.close_thread_connection()


if __name__ == "__main__":
    unittest.main()
