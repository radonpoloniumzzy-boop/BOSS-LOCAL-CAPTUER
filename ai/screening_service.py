from __future__ import annotations

from collections.abc import Callable

from ai.prompt_manager import PromptManager
from ai.provider import AIProvider
from ai.schemas import ScreeningProgress
from core.models import ScreeningResult


class ScreeningService:
    def __init__(self, repository, prompt_manager: PromptManager, provider: AIProvider, logger=None) -> None:
        self.repository = repository
        self.prompt_manager = prompt_manager
        self.provider = provider
        self.logger = logger
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
    ) -> dict[str, object]:
        self._stop_requested = False
        prompt_text = self.prompt_manager.finalize_prompt(
            str(profile.get("prompt_text") or ""),
            str(profile.get("prompt_source") or "generated"),
            str(profile.get("job_title") or ""),
            str(profile.get("jd_text") or ""),
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile["id"]),
            source_job_title=source_job_title,
            batch_id=batch_id,
            provider=provider_name,
            model=model,
            total_candidates=len(candidates),
            origin=origin,
        )
        completed = 0
        failed = 0
        status = "completed"
        note = ""

        try:
            for index, candidate in enumerate(candidates, start=1):
                if self._stop_requested:
                    status = "stopped"
                    note = "用户停止了 AI 初筛。"
                    break
                candidate_id = int(candidate["id"])
                name = str(candidate.get("name") or f"候选人 #{candidate_id}")
                try:
                    decision = self.provider.screen(prompt_text, self._candidate_text(candidate))
                    result = ScreeningResult(
                        run_id=run_id,
                        candidate_id=candidate_id,
                        rating=decision.rating,
                        persona=decision.persona,
                        raw_response=decision.raw_response,
                    )
                    self.repository.save_screening_result(result)
                    completed += 1
                    message = f"{name}: {decision.rating}"
                    rating = decision.rating
                    persona = decision.persona
                except Exception as exc:
                    failed += 1
                    message = f"{name}: 失败 - {exc}"
                    rating = ""
                    persona = ""
                    self.repository.save_screening_result(
                        ScreeningResult(
                            run_id=run_id,
                            candidate_id=candidate_id,
                            rating="",
                            persona="",
                            status="failed",
                            error=str(exc),
                        )
                    )
                    self._log("exception", "Screening candidate %s failed: %s", candidate_id, exc)

                self.repository.update_screening_run_progress(run_id, completed, failed)
                if progress_callback:
                    progress_callback(
                        ScreeningProgress(
                            run_id=run_id,
                            current=index,
                            total=len(candidates),
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
            self.repository.finalize_screening_run(run_id, status, completed, failed, note)

        return {
            "run_id": run_id,
            "status": status,
            "total": len(candidates),
            "completed": completed,
            "failed": failed,
            "message": note or "AI 初筛完成。",
        }

    @staticmethod
    def _candidate_text(candidate: dict[str, object]) -> str:
        fields = [
            ("姓名", candidate.get("name")),
            ("期望薪资", candidate.get("expected_salary")),
            ("工作经历", candidate.get("work_experience_text")),
            ("教育经历", candidate.get("education_text")),
            ("标签", candidate.get("tags_text")),
            ("摘要", candidate.get("summary_text")),
            ("候选人原始信息", candidate.get("raw_card_text")),
        ]
        return "\n".join(f"{label}：{value or '-'}" for label, value in fields)

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)
