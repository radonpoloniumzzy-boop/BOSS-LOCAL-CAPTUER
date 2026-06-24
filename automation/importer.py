from __future__ import annotations

from automation.parser import CandidateParser
from core.models import CaptureRunResult
from core.utils import normalize_text
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

        batch = self.repository.create_batch(job_title, source_url, note="; ".join(note_parts))
        seen_keys: set[str] = set()
        parsed_records = []
        status = "completed"
        message = "已从 Chrome 扩展导入候选人卡片。"

        try:
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

            repo_result = self.repository.upsert_batch_candidates(batch.id, parsed_records)
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
                total_collected=len(parsed_records),
                total_new=repo_result["inserted_batch_items"],
                note=message,
            )
            response = result.to_dict()
            response.update(
                {
                    "received_cards": len(cards),
                    "parsed_cards": len(parsed_records),
                    "source": "chrome_extension",
                    "job_title": job_title,
                    "source_url": source_url,
                    "automation_requested": bool(meta.get("automation_requested")),
                }
            )
            self._log(
                "info",
                "Imported extension batch=%s received=%s parsed=%s inserted_candidates=%s inserted_batch_items=%s",
                batch.id,
                len(cards),
                len(parsed_records),
                repo_result["inserted_candidates"],
                repo_result["inserted_batch_items"],
            )
            return response
        except Exception as exc:
            status = "failed"
            message = str(exc)
            self.repository.finalize_batch(
                batch_id=batch.id,
                status=status,
                total_collected=len(parsed_records),
                total_new=0,
                note=message,
            )
            self._log("exception", "Failed to import extension batch=%s: %s", batch.id, exc)
            raise
        finally:
            self.repository.db.close_thread_connection()

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)
