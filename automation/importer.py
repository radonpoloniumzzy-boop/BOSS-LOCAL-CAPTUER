from __future__ import annotations

import json

from automation.parser import CandidateParser
from core.models import CandidateRecord, CaptureRunResult
from core.utils import normalize_text, now_iso, short_hash
from storage.repository import CandidateRepository


class CardImportService:
    def __init__(self, repository: CandidateRepository, parser: CandidateParser, logger=None) -> None:
        self.repository = repository
        self.parser = parser
        self.logger = logger

    def import_cards(self, payload: dict[str, object]) -> dict[str, object]:
        job_title = normalize_text(str(payload.get("job_title") or "")) or "Boss 推荐牛人"
        source_url = normalize_text(str(payload.get("source_url") or "")) or "https://www.zhipin.com/web/geek/recommend"
        cards = payload.get("cards") or []
        if not isinstance(cards, list) or not cards:
            raise ValueError("扩展没有传回任何候选人卡片。")

        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        note_parts = ["extension_import"]
        if meta:
            rounds = meta.get("rounds_completed")
            unique_cards = meta.get("unique_cards")
            if rounds is not None:
                note_parts.append(f"rounds={rounds}")
            if unique_cards is not None:
                note_parts.append(f"unique_cards={unique_cards}")
            if meta.get("automation_requested"):
                note_parts.append("automation_requested=true")

        source_platform = self.parser.normalize_source_platform(
            str(meta.get("platform") or ""),
            source_url,
        )
        job_profile = self._resolve_job_profile(payload, job_title)
        explicit_job_profile = payload.get("job_profile_id") not in (None, "")
        request_id = normalize_text(str(payload.get("idempotency_key") or ""))
        request_payload_hash = self._payload_hash(payload)
        task_id = self._optional_int(payload.get("recruitment_task_id"))

        batch = None
        parsed_records: list[CandidateRecord] = []
        parse_failures = 0
        status = "completed"
        message = "已从 Chrome 扩展导入候选人卡片。"

        try:
            batch, reused = self.repository.claim_intake_batch(
                job_title,
                source_url,
                note="; ".join(note_parts),
                source_platform=source_platform,
                request_id=request_id,
                request_payload_hash=request_payload_hash,
                role_id=(int(job_profile["id"]) if job_profile is not None else None),
                task_id=task_id,
            )
            if reused:
                return self._batch_result(
                    self.repository.get_capture_batch(int(batch.id)) or batch.to_dict(),
                    {
                        "source": "chrome_extension",
                        "job_profile_id": batch.role_id,
                    },
                )

            for raw_card in cards:
                if not isinstance(raw_card, dict):
                    parse_failures += 1
                    continue
                try:
                    record = self.parser.parse_card(raw_card, job_title, source_url)
                except Exception as exc:  # pragma: no cover - defensive parser boundary
                    parse_failures += 1
                    self._log("exception", "Failed to parse extension card: %s", exc)
                    continue
                if record is None:
                    parse_failures += 1
                    continue
                if not record.source_platform:
                    record.source_platform = source_platform
                parsed_records.append(record)

            repo_result = self.repository.upsert_batch_candidates(
                batch.id,
                parsed_records,
                role_id=(int(job_profile["id"]) if explicit_job_profile and job_profile is not None else None),
            )
            failed_candidates = parse_failures + int(repo_result["failed_candidates"])
            result = CaptureRunResult(
                batch_id=batch.id,
                status=status,
                total_unique=len(parsed_records),
                total_inserted_candidates=repo_result["inserted_candidates"],
                total_batch_items=repo_result["inserted_batch_items"],
                rounds_completed=int(meta.get("rounds_completed") or 0),
                message=message,
            )
            self.repository.finalize_batch(
                batch_id=batch.id,
                status=status,
                total_collected=len(cards),
                total_new=repo_result["inserted_candidates"],
                total_updated=repo_result["updated_candidates"],
                total_skipped=repo_result["skipped_candidates"],
                total_failed=failed_candidates,
                note=message,
            )
            response = result.to_dict()
            response.update(
                {
                    "received_cards": len(cards),
                    "parsed_cards": len(parsed_records),
                    "inserted_candidates": repo_result["inserted_candidates"],
                    "source": "chrome_extension",
                    "source_platform": source_platform,
                    "job_title": job_title,
                    "job_profile_id": int(job_profile["id"]) if job_profile is not None else None,
                    "recruitment_task_id": batch.task_id,
                    "source_url": source_url,
                    "automation_requested": bool(meta.get("automation_requested")),
                    "updated_candidates": repo_result["updated_candidates"],
                    "skipped_candidates": repo_result["skipped_candidates"],
                    "failed_candidates": failed_candidates,
                }
            )
            return response
        except Exception as exc:
            status = "failed"
            message = str(exc)
            if batch is not None:
                self.repository.finalize_batch(
                    batch_id=batch.id,
                    status=status,
                    total_collected=len(cards),
                    total_new=0,
                    total_updated=0,
                    total_skipped=0,
                    total_failed=len(cards),
                    note=message,
                )
            self._log(
                "exception",
                "Failed to import extension batch=%s: %s",
                getattr(batch, "id", "unclaimed"),
                exc,
            )
            raise
        finally:
            self.repository.db.close_thread_connection()

    def import_candidates(self, payload: dict[str, object]) -> dict[str, object]:
        candidates = payload.get("candidates") or []
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("没有收到可入库的候选人。")

        source_url = normalize_text(str(payload.get("source_url") or ""))
        job_title = normalize_text(str(payload.get("source_job_title") or payload.get("job_title") or ""))
        source_platform = self.parser.normalize_source_platform(
            str(payload.get("source_platform") or ""),
            source_url,
        )
        request_id = normalize_text(str(payload.get("idempotency_key") or ""))
        request_payload_hash = self._payload_hash(payload)
        role_id = self._optional_int(payload.get("job_profile_id"))
        task_id = self._optional_int(payload.get("recruitment_task_id"))
        job_profile = self.repository.get_job_profile(role_id) if role_id is not None else None
        if role_id is not None and job_profile is None:
            raise ValueError("岗位档案不存在。")
        if job_profile is not None and str(job_profile.get("status") or "") != "active":
            raise ValueError("所选岗位档案不是招聘中状态，不能用于自动入库。")

        batch = None
        records: list[CandidateRecord] = []
        failures: list[dict[str, object]] = []

        try:
            batch, reused = self.repository.claim_intake_batch(
                job_title,
                source_url,
                note="web_candidate_intake",
                source_platform=source_platform,
                request_id=request_id,
                request_payload_hash=request_payload_hash,
                role_id=role_id,
                task_id=task_id,
            )
            if reused:
                return self._batch_result(
                    self.repository.get_capture_batch(int(batch.id)) or batch.to_dict(),
                    {
                        "source": "web_intake",
                        "job_profile_id": batch.role_id,
                    },
                )

            for index, item in enumerate(candidates):
                if not isinstance(item, dict):
                    failures.append(
                        {
                            "index": index,
                            "code": "invalid_item",
                            "message": "候选人记录格式无效。",
                        }
                    )
                    continue
                try:
                    records.append(
                        self._build_structured_candidate(
                            item,
                            default_job_title=job_title,
                            default_source_url=source_url,
                            default_source_platform=source_platform,
                        )
                    )
                except ValueError as exc:
                    failures.append(
                        {
                            "index": index,
                            "code": "invalid_candidate",
                            "message": str(exc),
                        }
                    )

            repo_result = self.repository.upsert_batch_candidates(
                batch.id,
                records,
                role_id=role_id,
            )
            failed_candidates = len(failures) + int(repo_result["failed_candidates"])
            batch_status = "completed" if failed_candidates == 0 else "partial"
            self.repository.finalize_batch(
                batch_id=batch.id,
                status=batch_status,
                total_collected=len(candidates),
                total_new=repo_result["inserted_candidates"],
                total_updated=repo_result["updated_candidates"],
                total_skipped=repo_result["skipped_candidates"],
                total_failed=failed_candidates,
                note="web_candidate_intake",
            )
            batch_row = self.repository.get_capture_batch(batch.id)
            assert batch_row is not None
            return self._batch_result(
                batch_row,
                {
                    "source": "web_intake",
                    "job_profile_id": role_id,
                    "received_count": len(candidates),
                    "failures": failures,
                },
            )
        except Exception:
            if batch is not None:
                self.repository.finalize_batch(
                    batch_id=batch.id,
                    status="failed",
                    total_collected=len(candidates),
                    total_new=0,
                    total_updated=0,
                    total_skipped=0,
                    total_failed=len(candidates),
                    note="web_candidate_intake",
                )
            raise
        finally:
            self.repository.db.close_thread_connection()

    def _resolve_job_profile(self, payload: dict[str, object], job_title: str) -> dict[str, object] | None:
        profile_id_value = payload.get("job_profile_id")
        if profile_id_value not in (None, ""):
            try:
                job_profile = self.repository.get_job_profile(int(profile_id_value))
            except (TypeError, ValueError) as exc:
                raise ValueError("岗位档案 ID 无效。") from exc
            if job_profile is None:
                raise ValueError("岗位档案不存在。")
            if str(job_profile.get("status") or "") != "active":
                raise ValueError("所选岗位档案不是招聘中状态，已停止导入。")
            return job_profile
        active_profile = self.repository.find_job_profile_by_title(job_title, active_only=True)
        if active_profile is not None:
            return active_profile
        matched_profile = self.repository.find_job_profile_by_title(job_title, active_only=False)
        if matched_profile is not None and str(matched_profile.get("status") or "") != "active":
            raise ValueError("所选岗位档案不是招聘中状态，已停止导入。")
        return None

    def _build_structured_candidate(
        self,
        item: dict[str, object],
        *,
        default_job_title: str,
        default_source_url: str,
        default_source_platform: str,
    ) -> CandidateRecord:
        raw_card_text = normalize_text(str(item.get("raw_card_text") or ""))
        if not raw_card_text:
            raise ValueError("候选人原始卡片内容不能为空。")
        source_url = normalize_text(str(item.get("source_url") or default_source_url))
        source_platform = self.parser.normalize_source_platform(
            str(item.get("source_platform") or default_source_platform),
            source_url,
        )
        source_candidate_id = normalize_text(str(item.get("source_candidate_id") or ""))
        detail_url = normalize_text(str(item.get("detail_url") or ""))
        platform_uid = self.parser.canonicalize_source_candidate_id(
            source_platform,
            source_candidate_id,
        )
        name = normalize_text(str(item.get("name") or ""))
        expected_salary = normalize_text(str(item.get("expected_salary") or ""))
        work_experience_text = normalize_text(str(item.get("work_experience_text") or ""))
        education_text = normalize_text(str(item.get("education_text") or ""))
        capture_time = normalize_text(str(item.get("capture_time") or "")) or now_iso()
        raw_text_hash = short_hash(raw_card_text)
        candidate_key = self.parser.build_candidate_key(
            platform_uid=platform_uid,
            detail_url=detail_url,
            name=name,
            expected_salary=expected_salary,
            work_experience_text=work_experience_text,
            education_text=education_text,
            raw_text_hash=raw_text_hash,
        )
        return CandidateRecord(
            candidate_key=candidate_key,
            raw_text_hash=raw_text_hash,
            job_title=normalize_text(str(item.get("source_job_title") or default_job_title)),
            source_url=source_url,
            capture_time=capture_time,
            raw_card_text=raw_card_text,
            source_platform=source_platform,
            name=name,
            active_status=normalize_text(str(item.get("active_status") or "")),
            expected_salary=expected_salary,
            work_experience_text=work_experience_text,
            education_text=education_text,
            tags_text=self._tags_text(item.get("tags_text")),
            summary_text=normalize_text(str(item.get("summary_text") or "")),
            detail_url=detail_url,
            platform_uid=platform_uid,
        )

    @staticmethod
    def _tags_text(value: object) -> str:
        if isinstance(value, list):
            return " | ".join(
                normalize_text(str(item)) for item in value if normalize_text(str(item))
            )
        return normalize_text(str(value or ""))

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    @staticmethod
    def _payload_hash(payload: dict[str, object]) -> str:
        return short_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))

    @staticmethod
    def _batch_result(batch: dict[str, object], extra: dict[str, object] | None = None) -> dict[str, object]:
        payload = {
            "batch_id": int(batch["id"]),
            "status": str(batch.get("status") or ""),
            "received_count": int(batch.get("total_collected") or 0),
            "inserted_candidates": int(batch.get("total_new") or 0),
            "updated_candidates": int(batch.get("total_updated") or 0),
            "skipped_candidates": int(batch.get("total_skipped") or 0),
            "failed_candidates": int(batch.get("total_failed") or 0),
            "source_platform": str(batch.get("source_platform") or ""),
            "job_title": str(batch.get("job_title") or ""),
            "source_url": str(batch.get("source_url") or ""),
            "job_profile_id": batch.get("role_id"),
            "recruitment_task_id": batch.get("task_id"),
            "failures": [],
        }
        if extra:
            payload.update(extra)
        return payload

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)
