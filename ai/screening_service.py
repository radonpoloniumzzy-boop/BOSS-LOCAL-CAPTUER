from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable

from ai.prompt_manager import PromptManager
from ai.prescreen import RulePrescreener
from ai.provider import AIProvider
from ai.schemas import ScreeningProgress
from core.models import ScreeningResult
from core.utils import short_hash


class ProviderRateLimiter:
    _guard = threading.Lock()
    _locks: dict[str, threading.Lock] = {}
    _last_call_at: dict[str, float] = {}

    @classmethod
    def wait(cls, key: str, min_interval_seconds: float) -> None:
        interval = max(float(min_interval_seconds or 0.0), 0.0)
        if interval <= 0:
            return
        with cls._guard:
            lock = cls._locks.setdefault(key, threading.Lock())
        with lock:
            now = time.monotonic()
            last_call_at = cls._last_call_at.get(key, 0.0)
            wait_seconds = interval - (now - last_call_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            cls._last_call_at[key] = time.monotonic()


class ScreeningService:
    def __init__(
        self,
        repository,
        prompt_manager: PromptManager,
        provider: AIProvider,
        logger=None,
        prescreener: RulePrescreener | None = None,
        max_retry_count: int = 2,
        retry_backoff_base_seconds: float = 1.0,
        worker_id: str = "",
        task_lock_timeout_seconds: float = 600.0,
        provider_min_interval_seconds: float = 0.0,
    ) -> None:
        self.repository = repository
        self.prompt_manager = prompt_manager
        self.provider = provider
        self.logger = logger
        self.prescreener = prescreener or RulePrescreener()
        self.max_retry_count = max_retry_count
        self.retry_backoff_base_seconds = retry_backoff_base_seconds
        self.worker_id = worker_id or f"screening-{id(self):x}"
        self.task_lock_timeout_seconds = task_lock_timeout_seconds
        self.provider_min_interval_seconds = provider_min_interval_seconds
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(
        self,
        *,
        profile: dict[str, object],
        candidates: list[dict[str, object]],
        source_job_title: str,
        batch_id: int | None,
        provider_name: str,
        model: str,
        origin: str = "manual",
        progress_callback: Callable[[ScreeningProgress], None] | None = None,
        run_id: int | None = None,
    ) -> dict[str, object]:
        self._stop_requested = False
        prompt_text = self.prompt_manager.finalize_prompt(
            str(profile.get("prompt_text") or ""),
            str(profile.get("prompt_source") or "generated"),
            str(profile.get("job_title") or ""),
            str(profile.get("jd_text") or ""),
        )
        role_id = int(profile["id"])
        prompt_version = self._prompt_version(profile)
        candidate_texts = {
            int(candidate["id"]): self._candidate_text(candidate)
            for candidate in candidates
        }
        request_hashes = {
            candidate_id: self._request_payload_hash(
                provider_name=provider_name,
                model=model,
                prompt_version=prompt_version,
                prompt_text=prompt_text,
                candidate_text=candidate_text,
            )
            for candidate_id, candidate_text in candidate_texts.items()
        }
        prescreen_decisions = {
            int(candidate["id"]): self.prescreener.evaluate(candidate, profile).to_dict()
            for candidate in candidates
        }

        if run_id is None:
            run_id = self.repository.create_screening_run(
                profile_id=role_id,
                source_job_title=source_job_title,
                batch_id=batch_id,
                provider=provider_name,
                model=model,
                total_candidates=len(candidates),
                origin=origin,
            )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=role_id,
            candidates=candidates,
            model_name=model,
            prompt_version=prompt_version,
            request_hashes=request_hashes,
            prescreen_decisions=prescreen_decisions,
            prompt_text=prompt_text,
            candidate_texts=candidate_texts,
            max_retry_count=self.max_retry_count,
        )
        self.repository.mark_screening_run_running(run_id)

        status = "completed"
        note = ""
        counts = self.repository.get_screening_task_counts(run_id)

        try:
            while True:
                if self._stop_requested:
                    status = "stopped"
                    note = "User stopped AI screening."
                    break

                task = self.repository.claim_next_screening_task(
                    run_id,
                    worker_id=self.worker_id,
                    lock_timeout_seconds=self.task_lock_timeout_seconds,
                )
                if task is None:
                    break

                task_id = int(task["task_id"])
                candidate_id = int(task["candidate_id"])
                name = str(task.get("name") or f"Candidate #{candidate_id}")
                task_model = str(task.get("model_name") or model)
                task_prompt_version = str(task.get("prompt_version") or prompt_version)
                task_request_hash = str(
                    task.get("request_payload_hash") or request_hashes[candidate_id]
                )
                stored_prompt_text = str(task.get("prompt_text") or "")
                stored_candidate_text = str(task.get("candidate_text") or "")
                has_request_snapshot = bool(stored_prompt_text and stored_candidate_text)
                task_prompt_text = stored_prompt_text or prompt_text
                task_candidate_text = stored_candidate_text or candidate_texts[candidate_id]
                rating = ""
                persona = ""

                try:
                    result_source = "model"
                    existing_result = self.repository.get_screening_result(run_id, candidate_id)
                    if existing_result is not None and str(existing_result["status"]) == "completed":
                        result_id = int(existing_result["id"])
                        rating = str(existing_result["rating"] or "")
                        persona = str(existing_result["persona"] or "")
                        message = f"{name}: {rating} (recovered)"
                        result_source = "recovered"
                    else:
                        cached = self.repository.get_cached_screening_result(
                            role_id=role_id,
                            candidate_id=candidate_id,
                            model_name=task_model,
                            prompt_version=task_prompt_version,
                            request_payload_hash=task_request_hash,
                        )
                        if cached is not None:
                            result_id = self.repository.save_screening_result(
                                ScreeningResult(
                                    run_id=run_id,
                                    candidate_id=candidate_id,
                                    rating=str(cached["rating"] or ""),
                                    persona=str(cached["persona"] or ""),
                                    status=str(cached["status"] or "completed"),
                                    raw_response=str(cached["raw_response"] or ""),
                                    error=str(cached["error"] or ""),
                                    confidence=str(cached["confidence"] or ""),
                                    evidence_json=str(cached["evidence_json"] or "[]"),
                                    gap_json=str(cached["gap_json"] or "[]"),
                                    risk_json=str(cached["risk_json"] or "[]"),
                                    recommended_action=str(cached["recommended_action"] or ""),
                                )
                            )
                            rating = str(cached["rating"] or "")
                            persona = str(cached["persona"] or "")
                            message = f"{name}: {rating} (cached)"
                            result_source = "cached"
                        else:
                            if not has_request_snapshot:
                                task_model = model
                                task_prompt_version = prompt_version
                                task_request_hash = request_hashes[candidate_id]
                                task_prompt_text = prompt_text
                                task_candidate_text = candidate_texts[candidate_id]
                                self.repository.update_screening_task_request_snapshot(
                                    task_id,
                                    model_name=task_model,
                                    prompt_version=task_prompt_version,
                                    request_payload_hash=task_request_hash,
                                    prompt_text=task_prompt_text,
                                    candidate_text=task_candidate_text,
                                )
                            ProviderRateLimiter.wait(
                                f"{provider_name}:{task_model}",
                                self.provider_min_interval_seconds,
                            )
                            decision = self.provider.screen(task_prompt_text, task_candidate_text)
                            result_id = self.repository.save_screening_result(
                                ScreeningResult(
                                    run_id=run_id,
                                    candidate_id=candidate_id,
                                    rating=decision.rating,
                                    persona=decision.persona,
                                    raw_response=decision.raw_response,
                                    confidence=decision.confidence,
                                    evidence_json=json.dumps(decision.evidence or [], ensure_ascii=False),
                                    gap_json=json.dumps(decision.gaps or [], ensure_ascii=False),
                                    risk_json=json.dumps(decision.risks or [], ensure_ascii=False),
                                    recommended_action=decision.recommended_action,
                                )
                            )
                            rating = decision.rating
                            persona = decision.persona
                            message = f"{name}: {decision.rating}"
                    self.repository.mark_screening_task_success(
                        task_id,
                        result_id,
                        result_source=result_source,
                    )
                except Exception as exc:
                    failure_category = self._failure_category(exc)
                    retry_after_seconds = self._retry_delay_seconds(task)
                    next_status = self.repository.mark_screening_task_failure(
                        task_id,
                        str(exc),
                        failure_category=failure_category,
                        retry_after_seconds=retry_after_seconds,
                    )
                    message = f"{name}: failed - {exc}"
                    if next_status == "failed":
                        self.repository.save_screening_result(
                            ScreeningResult(
                                run_id=run_id,
                                candidate_id=candidate_id,
                                rating="",
                                persona="",
                                status="failed",
                                error=f"{failure_category}: {exc}",
                            )
                        )
                    else:
                        message = f"{name}: retrying after {failure_category} - {exc}"
                        self._sleep_before_retry(task)
                    self._log("exception", "Screening candidate %s failed: %s", candidate_id, exc)

                counts = self.repository.get_screening_task_counts(run_id)
                completed = self._handled_count(counts)
                failed = counts["failed"]
                self.repository.update_screening_run_progress(run_id, completed, failed)
                if progress_callback:
                    progress_callback(
                        ScreeningProgress(
                            run_id=run_id,
                            current=min(completed + failed, counts["total"]),
                            total=counts["total"],
                            completed=completed,
                            failed=failed,
                            candidate_name=name,
                            rating=rating,
                            persona=persona,
                            message=message,
                        )
                    )
        except Exception as exc:
            status = "failed"
            note = str(exc)
            raise
        finally:
            counts = self.repository.get_screening_task_counts(run_id)
            completed = self._handled_count(counts)
            failed = counts["failed"]
            unfinished = counts["pending"] + counts["running"] + counts["retrying"]
            if status == "completed" and unfinished > 0:
                status = "stopped"
                note = "Screening stopped with unfinished tasks."
            self.repository.finalize_screening_run(run_id, status, completed, failed, note)

        return {
            "run_id": run_id,
            "status": status,
            "total": counts["total"],
            "completed": completed,
            "failed": failed,
            "manual_check": counts.get("manual_check", 0),
            "hold": counts.get("hold", 0),
            "message": note or "AI screening completed.",
        }

    @staticmethod
    def _handled_count(counts: dict[str, int]) -> int:
        return counts["success"] + counts.get("manual_check", 0) + counts.get("hold", 0)

    @staticmethod
    def _candidate_text(candidate: dict[str, object]) -> str:
        fields = [
            ("name", candidate.get("name")),
            ("expected_salary", candidate.get("expected_salary")),
            ("work_experience", candidate.get("work_experience_text")),
            ("education", candidate.get("education_text")),
            ("tags", candidate.get("tags_text")),
            ("summary", candidate.get("summary_text")),
            ("raw_card", candidate.get("raw_card_text")),
        ]
        return "\n".join(f"{label}: {value or '-'}" for label, value in fields)

    @staticmethod
    def _prompt_version(profile: dict[str, object]) -> str:
        profile_id = str(profile.get("id") or "new")
        updated_at = str(profile.get("updated_at") or "")
        source = str(profile.get("prompt_source") or "generated")
        return short_hash(f"{profile_id}|{updated_at}|{source}")[:16]

    @staticmethod
    def _request_payload_hash(
        *,
        provider_name: str,
        model: str,
        prompt_version: str,
        prompt_text: str,
        candidate_text: str,
    ) -> str:
        payload = {
            "provider": provider_name,
            "model": model,
            "prompt_version": prompt_version,
            "prompt_text": prompt_text,
            "candidate_text": candidate_text,
        }
        return short_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))

    def _sleep_before_retry(self, task: dict[str, object]) -> None:
        delay = self._retry_delay_seconds(task)
        if delay <= 0:
            return
        time.sleep(delay)

    def _retry_delay_seconds(self, task: dict[str, object]) -> float:
        if self.retry_backoff_base_seconds <= 0:
            return 0.0
        retry_count = int(task.get("retry_count") or 0) + 1
        return min(self.retry_backoff_base_seconds * (2 ** max(retry_count - 1, 0)), 30.0)

    @staticmethod
    def _failure_category(exc: Exception) -> str:
        message = str(exc).lower()
        if "rate limit" in message or "too many requests" in message or "429" in message:
            return "rate_limit"
        if "timeout" in message or "timed out" in message:
            return "timeout"
        if "json" in message or "parse" in message or "schema" in message:
            return "parse_error"
        if "unauthorized" in message or "401" in message or "403" in message or "api key" in message:
            return "auth_error"
        if "connection" in message or "network" in message or "dns" in message:
            return "network_error"
        return "provider_error"

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)
