from __future__ import annotations

import json

from core.models import BOSS_TRUSTED_PLATFORM_UID_ATTRIBUTES, SCREENING_RATINGS
from core.platform import is_boss_recommendation_url


class NativeFavoriteQueuePublisher:
    def __init__(self, repository) -> None:
        self.repository = repository

    def publish(self, run_id: int) -> int | None:
        run = self.repository.get_screening_run(run_id)
        if run is None:
            raise ValueError(f"Screening run not found: {run_id}")
        if str(run["status"]) != "completed":
            raise ValueError("Native Favorite queue requires a completed Initial Screening run")
        snapshot = self._decode_snapshot(run["automation_snapshot_json"])
        if str(snapshot.get("post_screen_action") or "screen_only") == "screen_only":
            return None
        if str(snapshot.get("post_screen_action")) != "screen_and_favorite":
            raise ValueError("Invalid post-screen action in automation snapshot")
        if int(snapshot.get("profile_id") or 0) != int(run["profile_id"]):
            raise ValueError("Automation snapshot does not match the Screening Profile")
        if int(snapshot.get("profile_version") or 0) <= 0:
            raise ValueError("Automation snapshot is missing the Screening Profile version")
        interval_seconds = int(snapshot.get("favorite_interval_seconds") or 0)
        max_candidates = int(snapshot.get("favorite_max_candidates") or 0)
        if interval_seconds < 3 or interval_seconds > 8:
            raise ValueError("Favorite interval must be between 3 and 8 seconds")
        if max_candidates < 1 or max_candidates > 50:
            raise ValueError("Favorite batch limit must be between 1 and 50")
        eligible_ratings = self._eligible_ratings(snapshot)
        if not eligible_ratings:
            raise ValueError("Favorite Eligibility Policy is not configured")
        capture_batch_id = int(run["batch_id"] or 0)
        source_context = snapshot.get("source_page_context")
        if not isinstance(source_context, dict):
            raise ValueError("Source Page Context is missing")
        if int(source_context.get("capture_batch_id") or 0) != capture_batch_id:
            raise ValueError("Source Page Context does not match the Capture Batch")
        if int(source_context.get("tab_id") or 0) <= 0:
            raise ValueError("Source Page Context is missing the Chrome tab")
        if str(source_context.get("platform") or "").strip().lower() != "boss":
            raise ValueError("Source Page Context does not identify BOSS")
        source_url = str(source_context.get("source_url") or "").strip()
        if not is_boss_recommendation_url(source_url):
            raise ValueError("Native Favorite is only available for BOSS recommendation pages")

        tasks = []
        for priority, row in enumerate(
            self.repository.list_native_favorite_queue_candidates(run_id, eligible_ratings)
        ):
            platform_identity = self._platform_identity(row)
            tasks.append(
                {
                    "candidate_id": int(row["candidate_id"]),
                    "platform_identity": platform_identity,
                    "priority": 0 - priority,
                }
            )
        return self.repository.create_native_favorite_batch(
            capture_batch_id=capture_batch_id,
            screening_run_id=run_id,
            role_id=int(run["profile_id"]),
            source_page_url=source_url,
            source_page_context=dict(source_context),
            config_snapshot=snapshot,
            tasks=tasks,
        )

    @staticmethod
    def _decode_snapshot(value: object) -> dict[str, object]:
        try:
            decoded = json.loads(str(value or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("Automation snapshot is invalid") from exc
        if not isinstance(decoded, dict):
            raise ValueError("Automation snapshot is invalid")
        return decoded

    @staticmethod
    def _eligible_ratings(snapshot: dict[str, object]) -> list[str]:
        supplied = snapshot.get("favorite_eligible_ratings")
        if not isinstance(supplied, list):
            return []
        selected = {str(value or "").strip().upper() for value in supplied}
        return [rating for rating in SCREENING_RATINGS if rating in selected]

    @staticmethod
    def _platform_identity(row) -> dict[str, str] | None:
        platform_uid = str(row["platform_uid"] or "").strip()
        if str(row["platform"] or "").lower() != "boss" or not platform_uid:
            return None
        try:
            evidence = json.loads(str(row["raw_identity_json"] or "{}"))
        except json.JSONDecodeError:
            return None
        if not isinstance(evidence, dict):
            return None
        for attribute in BOSS_TRUSTED_PLATFORM_UID_ATTRIBUTES:
            if str(evidence.get(attribute) or "").strip() == platform_uid:
                return {"attribute": attribute, "value": platform_uid}
        return None
