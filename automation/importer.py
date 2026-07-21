from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from automation.parser import CandidateParser
from core.models import CandidateRecord, CaptureRunResult
from core.utils import normalize_text
from storage.repository import CandidateRepository


class CardImportService:
    def __init__(self, repository: CandidateRepository, parser: CandidateParser, logger=None) -> None:
        self.repository = repository
        self.parser = parser
        self.logger = logger

    def import_cards(self, payload: dict[str, object]) -> dict[str, object]:
        job_title = normalize_text(str(payload.get("job_title") or "")) or "Boss 推荐牛人"
        source_url = (
            normalize_text(str(payload.get("source_url") or ""))
            or "https://www.zhipin.com/web/geek/recommend"
        )
        cards = payload.get("cards") or []
        if not isinstance(cards, list) or not cards:
            raise ValueError("扩展没有传回任何候选人卡片。")

        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        parsed_records = self._parse_cards(cards, job_title, source_url)
        if not parsed_records:
            raise ValueError("扩展传回的卡片均无法解析。")

        collection_run_id = normalize_text(str(meta.get("collection_run_id") or ""))
        content_fingerprint = self._content_fingerprint(parsed_records)
        try:
            existing_run = self.repository.get_batch_by_collection_run_id(collection_run_id)
            if existing_run is not None:
                if str(existing_run["content_fingerprint"] or "") != content_fingerprint:
                    raise ValueError(
                        "同一采集任务 ID 被用于不同内容，已拒绝覆盖原批次。"
                    )
                return self._existing_batch_response(
                    existing_run,
                    payload=payload,
                    meta=meta,
                    content_fingerprint=content_fingerprint,
                    idempotent_replay=True,
                    duplicate_content=False,
                )

            duplicate_batch = None
            if collection_run_id and bool(meta.get("automation_requested")):
                latest_batch = self.repository.get_latest_batch()
                if (
                    latest_batch is not None
                    and str(latest_batch["status"] or "") == "completed"
                    and str(latest_batch["job_title"] or "") == job_title
                    and str(latest_batch["source_url"] or "") == source_url
                    and str(latest_batch["content_fingerprint"] or "") == content_fingerprint
                ):
                    duplicate_batch = latest_batch
            if duplicate_batch is not None:
                return self._existing_batch_response(
                    duplicate_batch,
                    payload=payload,
                    meta=meta,
                    content_fingerprint=content_fingerprint,
                    idempotent_replay=False,
                    duplicate_content=True,
                )

            note_parts = ["extension_import"]
            if meta.get("rounds_completed") is not None:
                note_parts.append(f"rounds={meta['rounds_completed']}")
            if meta.get("unique_cards") is not None:
                note_parts.append(f"unique_cards={meta['unique_cards']}")
            if meta.get("automation_requested"):
                note_parts.append("automation_requested=true")

            batch = self.repository.create_batch(
                job_title,
                source_url,
                note="; ".join(note_parts),
                collection_run_id=collection_run_id,
                content_fingerprint=content_fingerprint,
                source_document_id=normalize_text(str(meta.get("source_document_id") or "")),
                source_frame_id=(
                    int(meta["source_frame_id"])
                    if meta.get("source_frame_id") is not None
                    else None
                ),
                source_frame_url=normalize_text(str(meta.get("source_frame_url") or "")),
                collection_metadata_json=json.dumps(meta, ensure_ascii=False, sort_keys=True),
            )
            try:
                repo_result = self.repository.upsert_batch_candidates(batch.id, parsed_records)
                message = "已从 Chrome 扩展导入候选人卡片。"
                result = CaptureRunResult(
                    batch_id=batch.id,
                    status="completed",
                    total_unique=len(parsed_records),
                    total_inserted_candidates=repo_result["inserted_candidates"],
                    total_batch_items=repo_result["inserted_batch_items"],
                    rounds_completed=int(meta.get("rounds_completed") or 0),
                    message=message,
                )
                self.repository.finalize_batch(
                    batch_id=batch.id,
                    status="completed",
                    total_collected=len(parsed_records),
                    total_new=repo_result["inserted_batch_items"],
                    note="; ".join([*note_parts, message]),
                )
            except Exception as exc:
                self.repository.finalize_batch(
                    batch_id=batch.id,
                    status="failed",
                    total_collected=len(parsed_records),
                    total_new=0,
                    note=str(exc),
                )
                self._log("exception", "Failed to import extension batch=%s: %s", batch.id, exc)
                raise

            response = result.to_dict()
            response.update(
                self._response_metadata(
                    batch_id=int(batch.id),
                    job_title=job_title,
                    source_url=source_url,
                    meta=meta,
                    content_fingerprint=content_fingerprint,
                )
            )
            inserted_batch_items = int(repo_result["inserted_batch_items"])
            expected_unique_cards = int(meta.get("unique_cards") or len(cards))
            count_matches = (
                len(cards)
                == expected_unique_cards
                == len(parsed_records)
                == inserted_batch_items
            )
            response.update(
                {
                    "received_cards": len(cards),
                    "parsed_cards": len(parsed_records),
                    "automation_allowed": count_matches,
                    "validation_error": "" if count_matches else "import_count_mismatch",
                    "idempotent_replay": False,
                    "duplicate_content": False,
                    "duplicate_of_batch_id": None,
                }
            )
            self._log(
                "info",
                "Imported extension batch=%s run=%s received=%s parsed=%s fingerprint=%s",
                batch.id,
                collection_run_id,
                len(cards),
                len(parsed_records),
                content_fingerprint,
            )
            return response
        finally:
            self.repository.db.close_thread_connection()

    def _parse_cards(
        self,
        cards: list[object],
        job_title: str,
        source_url: str,
    ) -> list[CandidateRecord]:
        seen_keys: set[str] = set()
        parsed_records: list[CandidateRecord] = []
        for raw_card in cards:
            if not isinstance(raw_card, dict):
                continue
            try:
                record = self.parser.parse_card(raw_card, job_title, source_url)
            except Exception as exc:
                self._log("exception", "Failed to parse extension card: %s", exc)
                continue
            if record is None or record.candidate_key in seen_keys:
                continue
            seen_keys.add(record.candidate_key)
            parsed_records.append(record)
        return parsed_records

    @staticmethod
    def _content_fingerprint(records: Iterable[CandidateRecord]) -> str:
        digest = hashlib.sha256()
        for record in sorted(records, key=lambda item: (item.candidate_key, item.raw_text_hash)):
            digest.update(record.job_title.encode("utf-8"))
            digest.update(b"\0")
            digest.update(record.candidate_key.encode("utf-8"))
            digest.update(b"\0")
            digest.update(record.raw_text_hash.encode("ascii", errors="ignore"))
            digest.update(b"\n")
        return f"sha256:{digest.hexdigest()}"

    def _existing_batch_response(
        self,
        batch,
        *,
        payload: dict[str, object],
        meta: dict[str, object],
        content_fingerprint: str,
        idempotent_replay: bool,
        duplicate_content: bool,
    ) -> dict[str, object]:
        batch_id = int(batch["id"])
        total_items = self.repository.count_batch_items(batch_id)
        source_url = normalize_text(str(payload.get("source_url") or batch["source_url"]))
        response = {
            "batch_id": batch_id,
            "status": str(batch["status"]),
            "total_unique": total_items,
            "total_inserted_candidates": 0,
            "total_batch_items": total_items,
            "rounds_completed": int(meta.get("rounds_completed") or 0),
            "message": (
                "采集内容与上一批完全相同，未启动 AI 初筛。"
                if duplicate_content
                else "该采集任务已经导入，已忽略重复请求。"
            ),
            "received_cards": len(payload.get("cards") or []),
            "parsed_cards": total_items,
            "automation_allowed": False,
            "idempotent_replay": idempotent_replay,
            "duplicate_content": duplicate_content,
            "duplicate_of_batch_id": batch_id if duplicate_content else None,
        }
        response.update(
            self._response_metadata(
                batch_id=batch_id,
                job_title=str(batch["job_title"]),
                source_url=source_url,
                meta=meta,
                content_fingerprint=content_fingerprint,
            )
        )
        return response

    @staticmethod
    def _response_metadata(
        *,
        batch_id: int,
        job_title: str,
        source_url: str,
        meta: dict[str, object],
        content_fingerprint: str,
    ) -> dict[str, object]:
        return {
            "source": "chrome_extension",
            "job_title": job_title,
            "source_url": source_url,
            "automation_requested": bool(meta.get("automation_requested")),
            "collection_run_id": str(meta.get("collection_run_id") or ""),
            "content_fingerprint": content_fingerprint,
            "source_page_context": {
                "capture_batch_id": batch_id,
                "platform": str(meta.get("platform") or "").strip().lower(),
                "source_url": source_url,
                "tab_id": int(meta.get("source_tab_id") or 0),
                "document_id": str(meta.get("source_document_id") or "").strip(),
                "candidate_documents": [
                    {
                        "frame_id": int(item.get("frame_id") or 0),
                        "document_id": str(item.get("document_id") or "").strip(),
                        "frame_url": str(item.get("frame_url") or "").strip(),
                    }
                    for item in (meta.get("source_candidate_documents") or [])
                    if isinstance(item, dict)
                ],
            },
        }

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)
