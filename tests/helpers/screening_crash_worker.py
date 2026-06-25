from __future__ import annotations

import os
import sys
from pathlib import Path

from ai.prompt_manager import PromptManager
from ai.schemas import ScreeningDecision
from ai.screening_service import ScreeningService
from core.models import CandidateRecord, ScreeningProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class CrashAfterProvider:
    def __init__(self, call_log_path: Path, crash_after: int) -> None:
        self.call_log_path = call_log_path
        self.crash_after = crash_after
        self.calls = 0

    def screen(self, _system_prompt: str, _candidate_text: str) -> ScreeningDecision:
        self.calls += 1
        self.call_log_path.write_text(str(self.calls), encoding="utf-8")
        if self.calls > self.crash_after:
            os._exit(87)
        return ScreeningDecision(
            rating="SR",
            persona="Crash worker completed this candidate.",
            raw_response='{"rating":"SR","persona":"ok"}',
            confidence="medium",
        )


def main() -> int:
    if len(sys.argv) != 6:
        print(
            "usage: screening_crash_worker.py <db_path> <run_id_path> "
            "<call_log_path> <total_candidates> <crash_after>",
            file=sys.stderr,
        )
        return 2
    db_path = Path(sys.argv[1])
    run_id_path = Path(sys.argv[2])
    call_log_path = Path(sys.argv[3])
    total_candidates = int(sys.argv[4])
    crash_after = int(sys.argv[5])

    db = DatabaseManager(db_path)
    db.initialize()
    repository = CandidateRepository(db)
    batch = repository.create_batch("Java Engineer", "https://example.com/pressure")
    repository.upsert_batch_candidates(
        batch.id,
        [
            CandidateRecord(
                candidate_key=f"platform:pressure-{index}",
                raw_text_hash=f"hash-pressure-{index}",
                job_title="Java Engineer",
                source_url="https://example.com/pressure",
                capture_time="2026-06-12T12:00:00",
                raw_card_text=f"Candidate {index} 5 years Java Spring Cloud",
                name=f"Candidate {index}",
                work_experience_text="5 years Java development",
                education_text="Bachelor",
                tags_text="Java | Spring Cloud",
            )
            for index in range(total_candidates)
        ],
    )
    prompt_manager = PromptManager(Path("assets/prompts"))
    prompt = prompt_manager.build_from_jd(
        "Java Engineer",
        "Bachelor, 5+ years Java, familiar with Spring Cloud.",
    )
    profile = repository.save_screening_profile(
        ScreeningProfile(
            job_title="Java Engineer",
            jd_text="Bachelor, 5+ years Java, familiar with Spring Cloud.",
            prompt_text=prompt,
            prompt_source="generated",
        )
    )
    run_id = repository.create_screening_run(
        profile_id=int(profile.id or 0),
        source_job_title="Java Engineer",
        batch_id=batch.id,
        provider="fake",
        model="fake-model",
        total_candidates=total_candidates,
        origin="pressure",
    )
    run_id_path.write_text(str(run_id), encoding="utf-8")
    service = ScreeningService(
        repository=repository,
        prompt_manager=prompt_manager,
        provider=CrashAfterProvider(call_log_path, crash_after),
        retry_backoff_base_seconds=0,
        worker_id="crash-worker",
        task_lock_timeout_seconds=60,
    )
    service.run(
        profile=profile.to_dict(),
        candidates=repository.list_screening_candidates(batch_id=batch.id),
        source_job_title="Java Engineer",
        batch_id=batch.id,
        provider_name="fake",
        model="fake-model",
        run_id=run_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
