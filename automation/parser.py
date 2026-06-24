from __future__ import annotations

from core.models import CandidateRecord
from core.utils import coalesce, normalize_multiline_text, normalize_text, now_iso, short_hash


class CandidateParser:
    def __init__(self, logger=None) -> None:
        self.logger = logger

    def parse_card(
        self,
        raw_card: dict[str, object],
        job_title: str,
        source_url: str,
        capture_time: str | None = None,
    ) -> CandidateRecord | None:
        raw_text = normalize_multiline_text(str(raw_card.get("raw_card_text") or ""))
        if not raw_text:
            self._log("warning", "Skipped card because raw text is empty")
            return None

        capture_time = capture_time or now_iso()
        name = normalize_text(str(raw_card.get("name") or ""))
        active_status = normalize_text(str(raw_card.get("active_status") or ""))
        expected_salary = normalize_text(str(raw_card.get("expected_salary") or ""))
        work_experience_text = normalize_text(str(raw_card.get("work_experience_text") or ""))
        education_text = normalize_text(str(raw_card.get("education_text") or ""))
        summary_text = normalize_text(str(raw_card.get("summary_text") or ""))
        detail_url = normalize_text(str(raw_card.get("detail_url") or ""))
        platform_uid = normalize_text(str(raw_card.get("platform_uid") or ""))
        tags = raw_card.get("tags_text") or []
        if isinstance(tags, list):
            tags_text = " | ".join(filter(None, [normalize_text(str(item)) for item in tags]))
        else:
            tags_text = normalize_text(str(tags))

        raw_text_hash = short_hash(raw_text)
        candidate_key = self.build_candidate_key(
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
            job_title=normalize_text(job_title),
            source_url=normalize_text(source_url),
            capture_time=capture_time,
            raw_card_text=raw_text,
            name=name,
            active_status=active_status,
            expected_salary=expected_salary,
            work_experience_text=work_experience_text,
            education_text=education_text,
            tags_text=tags_text,
            summary_text=summary_text,
            detail_url=detail_url,
            platform_uid=platform_uid,
        )

    @staticmethod
    def build_candidate_key(
        *,
        platform_uid: str,
        detail_url: str,
        name: str,
        expected_salary: str,
        work_experience_text: str,
        education_text: str,
        raw_text_hash: str,
    ) -> str:
        stable_key = coalesce(platform_uid, detail_url)
        if stable_key:
            return f"platform:{stable_key}"
        fingerprint = "||".join(
            [
                normalize_text(name).lower(),
                normalize_text(expected_salary).lower(),
                normalize_text(work_experience_text).lower(),
                normalize_text(education_text).lower(),
            ]
        )
        if fingerprint.strip("|"):
            return f"fingerprint:{short_hash(fingerprint)}"
        return f"raw:{raw_text_hash}"

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)

