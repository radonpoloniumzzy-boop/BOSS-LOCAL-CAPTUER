from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta

from core.models import CandidateRecord, CaptureBatch, CaptureBatchItem, ScreeningProfile, ScreeningResult
from core.utils import now_iso
from storage.db import DatabaseManager
from talent.profile_builder import StandardProfileBuilder


RECRUITMENT_STATUSES = {
    "collected",
    "screened",
    "priority_outreach",
    "contacted",
    "replied",
    "interviewing",
    "offer",
    "hired",
    "rejected",
    "talent_pool",
}

USER_REASON_CODES = {
    "",
    "priority_candidate",
    "manual_review_passed",
    "manual_review_rejected",
    "salary_mismatch",
    "location_mismatch",
    "experience_gap",
    "skill_gap",
    "candidate_not_interested",
    "candidate_unresponsive",
    "interview_failed",
    "offer_rejected",
    "role_closed",
    "duplicate",
}

SYSTEM_REASON_CODES = {
    "task_created",
    "ai_screening_success",
    "migration_backfill",
}

REASON_CODES = USER_REASON_CODES | SYSTEM_REASON_CODES


class CandidateRepository:
    def __init__(self, db: DatabaseManager, logger=None, profile_builder=None) -> None:
        self.db = db
        self.logger = logger
        self.profile_builder = profile_builder or StandardProfileBuilder()

    def create_batch(self, job_title: str, source_url: str, note: str = "") -> CaptureBatch:
        connection = self.db.get_connection()
        timestamp = now_iso()
        cursor = connection.execute(
            """
            INSERT INTO capture_batches(
                job_title, source_url, start_time, status, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job_title, source_url, timestamp, "running", note, timestamp, timestamp),
        )
        connection.commit()
        batch = CaptureBatch(
            id=cursor.lastrowid,
            job_title=job_title,
            source_url=source_url,
            start_time=timestamp,
            status="running",
            note=note,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._log("info", "Created capture batch %s for job %s", batch.id, job_title)
        return batch

    def finalize_batch(
        self,
        batch_id: int,
        status: str,
        total_collected: int,
        total_new: int,
        note: str = "",
    ) -> None:
        connection = self.db.get_connection()
        timestamp = now_iso()
        connection.execute(
            """
            UPDATE capture_batches
            SET end_time = ?, total_collected = ?, total_new = ?, status = ?, note = ?, updated_at = ?
            WHERE id = ?
            """,
            (timestamp, total_collected, total_new, status, note, timestamp, batch_id),
        )
        connection.commit()
        self._log(
            "info",
            "Finalized batch %s with status=%s total_collected=%s total_new=%s",
            batch_id,
            status,
            total_collected,
            total_new,
        )

    def upsert_batch_candidates(self, batch_id: int, candidates: Iterable[CandidateRecord]) -> dict[str, int]:
        connection = self.db.get_connection()
        inserted_candidates = 0
        inserted_batch_items = 0
        processed = 0
        with connection:
            for candidate in candidates:
                processed += 1
                existing = connection.execute(
                    "SELECT * FROM candidates WHERE candidate_key = ?",
                    (candidate.candidate_key,),
                ).fetchone()
                if existing is None:
                    candidate_id = self._insert_candidate(connection, candidate)
                    inserted_candidates += 1
                    profile_candidate = candidate
                else:
                    candidate_id = int(existing["id"])
                    merged = self._merge_candidate(existing, candidate)
                    self._update_candidate(connection, candidate_id, merged)
                    profile_candidate = merged
                profile_candidate.id = candidate_id
                self._upsert_candidate_profile(connection, profile_candidate)

                snapshot = CaptureBatchItem(
                    batch_id=batch_id,
                    candidate_id=candidate_id,
                    candidate_key=candidate.candidate_key,
                    raw_text_hash=candidate.raw_text_hash,
                    capture_time=candidate.capture_time,
                    job_title=candidate.job_title,
                    source_url=candidate.source_url,
                    raw_card_text=candidate.raw_card_text,
                    name=candidate.name,
                    active_status=candidate.active_status,
                    expected_salary=candidate.expected_salary,
                    work_experience_text=candidate.work_experience_text,
                    education_text=candidate.education_text,
                    tags_text=candidate.tags_text,
                    summary_text=candidate.summary_text,
                    detail_url=candidate.detail_url,
                )
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO capture_batch_items(
                        batch_id, candidate_id, candidate_key, raw_text_hash, capture_time, job_title,
                        source_url, name, active_status, expected_salary, work_experience_text,
                        education_text, tags_text, summary_text, raw_card_text, detail_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.batch_id,
                        snapshot.candidate_id,
                        snapshot.candidate_key,
                        snapshot.raw_text_hash,
                        snapshot.capture_time,
                        snapshot.job_title,
                        snapshot.source_url,
                        snapshot.name,
                        snapshot.active_status,
                        snapshot.expected_salary,
                        snapshot.work_experience_text,
                        snapshot.education_text,
                        snapshot.tags_text,
                        snapshot.summary_text,
                        snapshot.raw_card_text,
                        snapshot.detail_url,
                        now_iso(),
                    ),
                )
                if cursor.rowcount > 0:
                    inserted_batch_items += 1
        self._log(
            "info",
            "Upserted %s candidates for batch=%s inserted_candidates=%s inserted_batch_items=%s",
            processed,
            batch_id,
            inserted_candidates,
            inserted_batch_items,
        )
        return {
            "processed": processed,
            "inserted_candidates": inserted_candidates,
            "inserted_batch_items": inserted_batch_items,
        }

    def list_candidates(
        self,
        keyword: str = "",
        job_title: str = "",
        batch_id: int | None = None,
        city: str = "",
        years_min: int | str | None = None,
        years_max: int | str | None = None,
        profile_tag: str = "",
        last_active_days: int | str | None = None,
        latest_reason_code: str = "",
    ) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        params: list[object] = []
        joins = " LEFT JOIN candidate_profiles cp ON cp.candidate_id = c.id "
        filters = []

        if batch_id is not None:
            joins += " JOIN capture_batch_items bi ON bi.candidate_id = c.id "
            filters.append("bi.batch_id = ?")
            params.append(batch_id)

        if keyword:
            filters.append(
                """
                (
                    c.name LIKE ?
                    OR c.active_status LIKE ?
                    OR c.expected_salary LIKE ?
                    OR c.work_experience_text LIKE ?
                    OR c.tags_text LIKE ?
                    OR c.summary_text LIKE ?
                    OR c.raw_card_text LIKE ?
                )
                """
            )
            token = f"%{keyword}%"
            params.extend([token, token, token, token, token, token, token])

        if job_title:
            filters.append("c.job_title = ?")
            params.append(job_title)
        if city:
            filters.append("cp.city = ?")
            params.append(city.strip())
        min_years = self._optional_int(years_min)
        if min_years is not None:
            filters.append("cp.years_experience >= ?")
            params.append(min_years)
        max_years = self._optional_int(years_max)
        if max_years is not None:
            filters.append("cp.years_experience <= ?")
            params.append(max_years)
        for profile_token in self._profile_tag_tokens(profile_tag):
            tag = f"%{profile_token}%"
            filters.append(
                """
                (
                    cp.industry_tags_json LIKE ?
                    OR cp.skill_tags_json LIKE ?
                    OR cp.job_family LIKE ?
                    OR cp.job_track LIKE ?
                )
                """
            )
            params.extend([tag, tag, tag, tag])
        last_active_since = self._last_active_since(last_active_days)
        if last_active_since:
            filters.append("cp.last_active_at >= ?")
            params.append(last_active_since)
        normalized_latest_reason = str(latest_reason_code or "").strip()
        if normalized_latest_reason:
            filters.append("le.reason_code = ?")
            params.append(self._normalize_reason_code(normalized_latest_reason))

        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = f"""
        SELECT
            c.*,
            lm.id AS match_id,
            lm.role_id,
            lm.latest_rating,
            lm.latest_confidence,
            lr.evidence_json,
            lr.gap_json,
            lr.risk_json,
            lr.recommended_action,
            lm.match_status,
            lm.recruitment_status,
            lm.screening_result_id,
            lm.human_decision,
            lm.updated_at AS match_updated_at,
            le.changed_at AS latest_status_changed_at,
            le.from_status AS latest_status_from,
            le.to_status AS latest_status_to,
            le.reason_code AS latest_reason_code,
            le.note AS latest_status_note,
            le.operator AS latest_status_operator,
            lp.job_title AS role_title,
            cp.city,
            cp.years_experience,
            cp.job_family,
            cp.job_track,
            cp.industry_tags_json,
            cp.skill_tags_json,
            cp.last_active_at,
            cp.profile_completeness,
            COUNT(DISTINCT bi2.batch_id) AS batch_count
        FROM candidates c
        LEFT JOIN capture_batch_items bi2 ON bi2.candidate_id = c.id
        LEFT JOIN candidate_role_matches lm ON lm.id = (
            SELECT m2.id
            FROM candidate_role_matches m2
            WHERE m2.candidate_id = c.id
            ORDER BY
                CASE m2.latest_rating
                    WHEN 'UR' THEN 1
                    WHEN 'SSR' THEN 2
                    WHEN 'SR' THEN 3
                    WHEN 'R' THEN 4
                    WHEN 'N' THEN 5
                    ELSE 6
                END,
                m2.updated_at DESC,
                m2.id DESC
            LIMIT 1
        )
        LEFT JOIN screening_results lr ON lr.id = lm.screening_result_id
        LEFT JOIN screening_profiles lp ON lp.id = lm.role_id
        LEFT JOIN candidate_role_status_events le ON le.id = (
            SELECT e2.id
            FROM candidate_role_status_events e2
            WHERE e2.candidate_id = c.id
              AND e2.role_id = lm.role_id
            ORDER BY e2.changed_at DESC, e2.id DESC
            LIMIT 1
        )
        {joins}
        {where_sql}
        GROUP BY c.id
        ORDER BY c.updated_at DESC
        """
        return list(connection.execute(query, params).fetchall())

    def _upsert_candidate_profile(self, connection: sqlite3.Connection, candidate: CandidateRecord) -> None:
        if candidate.id is None:
            return
        profile = self.profile_builder.build(candidate.to_dict())
        timestamp = now_iso()
        connection.execute(
            """
            INSERT INTO candidate_profiles(
                candidate_id,
                name_or_alias,
                city,
                current_title,
                job_family,
                job_track,
                years_experience,
                industry_tags_json,
                skill_tags_json,
                management_experience,
                salary_range,
                education,
                last_active_at,
                profile_completeness,
                parser_version,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                name_or_alias = excluded.name_or_alias,
                city = excluded.city,
                current_title = excluded.current_title,
                job_family = excluded.job_family,
                job_track = excluded.job_track,
                years_experience = excluded.years_experience,
                industry_tags_json = excluded.industry_tags_json,
                skill_tags_json = excluded.skill_tags_json,
                management_experience = excluded.management_experience,
                salary_range = excluded.salary_range,
                education = excluded.education,
                last_active_at = excluded.last_active_at,
                profile_completeness = excluded.profile_completeness,
                parser_version = excluded.parser_version,
                updated_at = excluded.updated_at
            """,
            (
                profile["candidate_id"],
                profile["name_or_alias"],
                profile["city"],
                profile["current_title"],
                profile["job_family"],
                profile["job_track"],
                profile["years_experience"],
                json.dumps(profile["industry_tags"], ensure_ascii=False),
                json.dumps(profile["skill_tags"], ensure_ascii=False),
                1 if profile["management_experience"] else 0,
                profile["salary_range"],
                profile["education"],
                profile["last_active_at"],
                profile["profile_completeness"],
                profile["parser_version"],
                timestamp,
            ),
        )

    def refresh_outdated_candidate_profiles(self, limit: int | None = None) -> int:
        connection = self.db.get_connection()
        parser_version = str(getattr(self.profile_builder, "parser_version", ""))
        where = """
            cp.candidate_id IS NULL
            OR cp.parser_version <> ?
        """
        params: list[object] = [parser_version]
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(max(1, int(limit)))
        rows = connection.execute(
            f"""
            SELECT c.*
            FROM candidates c
            LEFT JOIN candidate_profiles cp ON cp.candidate_id = c.id
            WHERE {where}
            ORDER BY c.updated_at DESC, c.id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        if not rows:
            return 0
        with connection:
            for row in rows:
                self._upsert_candidate_profile(connection, self._candidate_from_row(row))
        return len(rows)

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> CandidateRecord:
        return CandidateRecord(
            id=int(row["id"]),
            candidate_key=str(row["candidate_key"]),
            raw_text_hash=str(row["raw_text_hash"]),
            platform_uid=str(row["platform_uid"] or ""),
            job_title=str(row["job_title"] or ""),
            source_url=str(row["source_url"] or ""),
            capture_time=str(row["capture_time"] or ""),
            raw_card_text=str(row["raw_card_text"] or ""),
            name=str(row["name"] or ""),
            active_status=str(row["active_status"] or ""),
            expected_salary=str(row["expected_salary"] or ""),
            work_experience_text=str(row["work_experience_text"] or ""),
            education_text=str(row["education_text"] or ""),
            tags_text=str(row["tags_text"] or ""),
            summary_text=str(row["summary_text"] or ""),
            detail_url=str(row["detail_url"] or ""),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

    def list_batches(self) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        return list(
            connection.execute(
                """
                SELECT * FROM capture_batches
                ORDER BY start_time DESC
                """
            ).fetchall()
        )

    def list_job_titles(self) -> list[str]:
        connection = self.db.get_connection()
        rows = connection.execute(
            """
            SELECT DISTINCT job_title
            FROM capture_batches
            WHERE job_title <> ''
            ORDER BY job_title COLLATE NOCASE
            """
        ).fetchall()
        return [str(row["job_title"]) for row in rows]

    def get_candidate_detail(self, candidate_id: int) -> dict[str, object] | None:
        connection = self.db.get_connection()
        candidate = connection.execute(
            "SELECT * FROM candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if candidate is None:
            return None
        appearances = connection.execute(
            """
            SELECT bi.batch_id, bi.capture_time, bi.job_title, bi.source_url, b.status, b.start_time
            FROM capture_batch_items bi
            JOIN capture_batches b ON b.id = bi.batch_id
            WHERE bi.candidate_id = ?
            ORDER BY bi.capture_time DESC
            """,
            (candidate_id,),
        ).fetchall()
        role_matches = connection.execute(
            """
            SELECT
                m.*,
                p.job_title AS role_title,
                r.evidence_json,
                r.gap_json,
                r.risk_json,
                r.recommended_action,
                r.persona AS result_persona,
                r.created_at AS result_created_at,
                cp.city,
                cp.years_experience,
                cp.job_family,
                cp.job_track,
                cp.industry_tags_json,
                cp.skill_tags_json,
                cp.profile_completeness
            FROM candidate_role_matches m
            JOIN screening_profiles p ON p.id = m.role_id
            LEFT JOIN screening_results r ON r.id = m.screening_result_id
            LEFT JOIN candidate_profiles cp ON cp.candidate_id = m.candidate_id
            WHERE m.candidate_id = ?
            ORDER BY
                CASE m.latest_rating
                    WHEN 'UR' THEN 1 WHEN 'SSR' THEN 2 WHEN 'SR' THEN 3
                    WHEN 'R' THEN 4 WHEN 'N' THEN 5 ELSE 6
                END,
                m.updated_at DESC
            """,
            (candidate_id,),
        ).fetchall()
        standard_profile = connection.execute(
            """
            SELECT *
            FROM candidate_profiles
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
        status_events = self.list_candidate_role_status_events(candidate_id=candidate_id)
        return {
            "candidate": candidate,
            "appearances": appearances,
            "standard_profile": standard_profile,
            "role_matches": role_matches,
            "status_events": status_events,
        }

    def get_latest_batch(self) -> sqlite3.Row | None:
        connection = self.db.get_connection()
        return connection.execute(
            """
            SELECT * FROM capture_batches
            ORDER BY start_time DESC
            LIMIT 1
            """
        ).fetchone()

    def get_dashboard_stats(self) -> dict[str, int | str]:
        connection = self.db.get_connection()
        total_candidates = connection.execute("SELECT COUNT(*) AS value FROM candidates").fetchone()["value"]
        total_batches = connection.execute("SELECT COUNT(*) AS value FROM capture_batches").fetchone()["value"]
        latest_batch = self.get_latest_batch()
        return {
            "total_candidates": int(total_candidates),
            "total_batches": int(total_batches),
            "latest_batch_id": int(latest_batch["id"]) if latest_batch else 0,
            "latest_batch_status": str(latest_batch["status"]) if latest_batch else "idle",
        }

    def save_screening_profile(self, profile: ScreeningProfile) -> ScreeningProfile:
        connection = self.db.get_connection()
        timestamp = now_iso()
        existing = None
        if profile.id is not None:
            existing = connection.execute(
                "SELECT id, created_at FROM screening_profiles WHERE id = ?",
                (profile.id,),
            ).fetchone()
        if existing is None:
            existing = connection.execute(
                "SELECT id, created_at FROM screening_profiles WHERE job_title = ?",
                (profile.job_title,),
            ).fetchone()

        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO screening_profiles(
                    job_title, jd_text, prompt_text, prompt_source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (profile.job_title, profile.jd_text, profile.prompt_text, profile.prompt_source, timestamp, timestamp),
            )
            profile.id = int(cursor.lastrowid)
            profile.created_at = timestamp
        else:
            profile.id = int(existing["id"])
            profile.created_at = str(existing["created_at"])
            connection.execute(
                """
                UPDATE screening_profiles
                SET job_title = ?, jd_text = ?, prompt_text = ?, prompt_source = ?, updated_at = ?
                WHERE id = ?
                """,
                (profile.job_title, profile.jd_text, profile.prompt_text, profile.prompt_source, timestamp, profile.id),
            )
        profile.updated_at = timestamp
        connection.commit()
        return profile

    def list_screening_profiles(self) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        return list(connection.execute("SELECT * FROM screening_profiles ORDER BY updated_at DESC").fetchall())

    def get_screening_profile(self, profile_id: int) -> sqlite3.Row | None:
        return self.db.get_connection().execute(
            "SELECT * FROM screening_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()

    def delete_screening_profile(self, profile_id: int) -> None:
        connection = self.db.get_connection()
        connection.execute("DELETE FROM screening_profiles WHERE id = ?", (profile_id,))
        connection.commit()

    def create_screening_run(
        self,
        *,
        profile_id: int,
        source_job_title: str,
        batch_id: int | None,
        provider: str,
        model: str,
        total_candidates: int,
        origin: str = "manual",
    ) -> int:
        connection = self.db.get_connection()
        cursor = connection.execute(
            """
            INSERT INTO screening_runs(
                profile_id, source_job_title, batch_id, provider, model, origin, status,
                total_candidates, completed_candidates, failed_candidates, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, 0, 0, ?)
            """,
            (
                profile_id,
                source_job_title,
                batch_id,
                provider,
                model,
                origin,
                total_candidates,
                now_iso(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)

    def create_screening_tasks(
        self,
        *,
        run_id: int,
        role_id: int,
        candidates: Iterable[dict[str, object]],
        model_name: str,
        prompt_version: str,
        request_hashes: dict[int, str],
        prescreen_decisions: dict[int, dict[str, object]] | None = None,
        prompt_text: str = "",
        candidate_texts: dict[int, str] | None = None,
        max_retry_count: int = 2,
    ) -> int:
        connection = self.db.get_connection()
        timestamp = now_iso()
        inserted = 0
        decisions = prescreen_decisions or {}
        snapshots = candidate_texts or {}
        with connection:
            for index, candidate in enumerate(candidates):
                candidate_id = int(candidate["id"])
                decision = decisions.get(candidate_id, {})
                route = str(decision.get("route") or "pass_to_ai")
                if route not in {"pass_to_ai", "manual_check", "hold"}:
                    route = "manual_check"
                status = "pending" if route == "pass_to_ai" else route
                route_reason = str(decision.get("reason") or "")
                route_details = decision.get("details")
                if not isinstance(route_details, dict):
                    route_details = {}
                route_details_json = json.dumps(
                    route_details,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO screening_tasks(
                        run_id, candidate_id, role_id, status, route, route_reason,
                        route_details_json, priority, retry_count,
                        max_retry_count, model_name, prompt_version, request_payload_hash,
                        created_at, updated_at, prompt_text, candidate_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        candidate_id,
                        role_id,
                        status,
                        route,
                        route_reason,
                        route_details_json,
                        0 - index,
                        max_retry_count,
                        model_name,
                        prompt_version,
                        request_hashes[candidate_id],
                        timestamp,
                        timestamp,
                        prompt_text,
                        snapshots.get(candidate_id, ""),
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
                    match_exists = self._candidate_role_match_exists(
                        connection,
                        candidate_id=candidate_id,
                        role_id=role_id,
                    )
                    self._upsert_candidate_role_match(
                        connection,
                        candidate_id=candidate_id,
                        role_id=role_id,
                        match_status=self._match_status_for_task_status(status),
                        timestamp=timestamp,
                    )
                    if not match_exists:
                        self._record_candidate_role_status_change(
                            connection,
                            candidate_id=candidate_id,
                            role_id=role_id,
                            to_status="collected",
                            operator="system",
                            reason_code="task_created",
                            note="Candidate entered screening task queue",
                            timestamp=timestamp,
                        )
        return inserted

    def claim_next_screening_task(self, run_id: int) -> dict[str, object] | None:
        connection = self.db.get_connection()
        with connection:
            row = connection.execute(
                """
                SELECT
                    t.id AS task_id,
                    t.run_id,
                    t.candidate_id,
                    t.role_id,
                    t.status AS task_status,
                    t.route,
                    t.route_reason,
                    t.route_details_json,
                    t.retry_count,
                    t.max_retry_count,
                    t.model_name,
                    t.prompt_version,
                    t.request_payload_hash,
                    t.prompt_text,
                    t.candidate_text,
                    c.name,
                    c.active_status,
                    c.expected_salary,
                    c.work_experience_text,
                    c.education_text,
                    c.tags_text,
                    c.summary_text,
                    c.raw_card_text
                FROM screening_tasks t
                JOIN candidates c ON c.id = t.candidate_id
                WHERE t.run_id = ?
                  AND t.route = 'pass_to_ai'
                  AND t.status IN ('pending', 'retrying')
                ORDER BY t.priority DESC, t.id
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            timestamp = now_iso()
            connection.execute(
                """
                UPDATE screening_tasks
                SET status = 'running',
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?,
                    error_message = NULL
                WHERE id = ? AND route = 'pass_to_ai' AND status IN ('pending', 'retrying')
                """,
                (timestamp, timestamp, int(row["task_id"])),
            )
            self._upsert_candidate_role_match(
                connection,
                candidate_id=int(row["candidate_id"]),
                role_id=int(row["role_id"]),
                match_status="screening_running",
                timestamp=timestamp,
            )
        payload = dict(row)
        payload["status"] = "running"
        return payload

    def mark_screening_task_success(
        self,
        task_id: int,
        result_id: int,
        *,
        result_source: str = "model",
    ) -> None:
        connection = self.db.get_connection()
        timestamp = now_iso()
        with connection:
            connection.execute(
                """
                UPDATE screening_tasks
                SET status = 'success',
                    result_id = ?,
                    result_source = ?,
                    error_message = '',
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (result_id, result_source, timestamp, timestamp, task_id),
            )
            row = connection.execute(
                """
                SELECT t.candidate_id, t.role_id, r.rating, r.confidence
                FROM screening_tasks t
                LEFT JOIN screening_results r ON r.id = ?
                WHERE t.id = ?
                """,
                (result_id, task_id),
            ).fetchone()
            if row is not None:
                self._upsert_candidate_role_match(
                    connection,
                    candidate_id=int(row["candidate_id"]),
                    role_id=int(row["role_id"]),
                    latest_rating=str(row["rating"] or ""),
                    latest_confidence=str(row["confidence"] or ""),
                    match_status="ai_screened",
                    screening_result_id=result_id,
                    timestamp=timestamp,
                )
                current_status = self._get_candidate_role_recruitment_status(
                    connection,
                    candidate_id=int(row["candidate_id"]),
                    role_id=int(row["role_id"]),
                )
                if current_status in {"", "collected"}:
                    self._record_candidate_role_status_change(
                        connection,
                        candidate_id=int(row["candidate_id"]),
                        role_id=int(row["role_id"]),
                        to_status="screened",
                        operator="system",
                        reason_code="ai_screening_success",
                        note="AI screening produced a completed result",
                        timestamp=timestamp,
                    )

    def update_screening_task_request_snapshot(
        self,
        task_id: int,
        *,
        model_name: str,
        prompt_version: str,
        request_payload_hash: str,
        prompt_text: str,
        candidate_text: str,
    ) -> None:
        connection = self.db.get_connection()
        connection.execute(
            """
            UPDATE screening_tasks
            SET model_name = ?,
                prompt_version = ?,
                request_payload_hash = ?,
                prompt_text = ?,
                candidate_text = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                model_name,
                prompt_version,
                request_payload_hash,
                prompt_text,
                candidate_text,
                now_iso(),
                task_id,
            ),
        )
        connection.commit()

    def mark_screening_task_failure(self, task_id: int, error_message: str) -> str:
        connection = self.db.get_connection()
        row = connection.execute(
            "SELECT retry_count, max_retry_count, candidate_id, role_id FROM screening_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Screening task not found: {task_id}")
        retry_count = int(row["retry_count"]) + 1
        max_retry_count = int(row["max_retry_count"])
        timestamp = now_iso()
        if retry_count <= max_retry_count:
            status = "retrying"
            connection.execute(
                """
                UPDATE screening_tasks
                SET status = ?,
                    retry_count = ?,
                    error_message = ?,
                    started_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, retry_count, error_message, timestamp, task_id),
            )
        else:
            status = "failed"
            connection.execute(
                """
                UPDATE screening_tasks
                SET status = ?,
                    retry_count = ?,
                    error_message = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, retry_count, error_message, timestamp, timestamp, task_id),
            )
        connection.commit()
        self.upsert_candidate_role_match(
            candidate_id=int(row["candidate_id"]),
            role_id=int(row["role_id"]),
            match_status="screening_retrying" if status == "retrying" else "ai_failed",
            timestamp=timestamp,
        )
        return status

    def upsert_candidate_role_match(
        self,
        *,
        candidate_id: int,
        role_id: int,
        latest_rating: str = "",
        latest_confidence: str = "",
        match_status: str,
        screening_result_id: int | None = None,
        human_decision: str = "",
        recruitment_status: str = "",
        timestamp: str | None = None,
    ) -> None:
        connection = self.db.get_connection()
        with connection:
            self._upsert_candidate_role_match(
                connection,
                candidate_id=candidate_id,
                role_id=role_id,
                latest_rating=latest_rating,
                latest_confidence=latest_confidence,
                match_status=match_status,
                screening_result_id=screening_result_id,
                human_decision=human_decision,
                recruitment_status=recruitment_status,
                timestamp=timestamp,
            )

    def _upsert_candidate_role_match(
        self,
        connection: sqlite3.Connection,
        *,
        candidate_id: int,
        role_id: int,
        latest_rating: str = "",
        latest_confidence: str = "",
        match_status: str,
        screening_result_id: int | None = None,
        human_decision: str = "",
        recruitment_status: str = "",
        timestamp: str | None = None,
    ) -> None:
        timestamp = timestamp or now_iso()
        recruitment_status = self._normalize_recruitment_status(recruitment_status, allow_empty=True)
        connection.execute(
            """
            INSERT INTO candidate_role_matches(
                candidate_id,
                role_id,
                latest_rating,
                latest_confidence,
                match_status,
                recruitment_status,
                screening_result_id,
                human_decision,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, COALESCE(NULLIF(?, ''), 'collected'), ?, ?, ?, ?)
            ON CONFLICT(candidate_id, role_id) DO UPDATE SET
                latest_rating = CASE
                    WHEN excluded.latest_rating <> '' THEN excluded.latest_rating
                    ELSE candidate_role_matches.latest_rating
                END,
                latest_confidence = CASE
                    WHEN excluded.latest_confidence <> '' THEN excluded.latest_confidence
                    ELSE candidate_role_matches.latest_confidence
                END,
                match_status = excluded.match_status,
                recruitment_status = CASE
                    WHEN ? <> ''
                         AND candidate_role_matches.recruitment_status IN ('', 'collected', 'screened')
                    THEN excluded.recruitment_status
                    ELSE candidate_role_matches.recruitment_status
                END,
                screening_result_id = COALESCE(
                    excluded.screening_result_id,
                    candidate_role_matches.screening_result_id
                ),
                human_decision = CASE
                    WHEN excluded.human_decision <> '' THEN excluded.human_decision
                    ELSE candidate_role_matches.human_decision
                END,
                updated_at = excluded.updated_at
            """,
            (
                candidate_id,
                role_id,
                latest_rating,
                latest_confidence,
                match_status,
                recruitment_status,
                screening_result_id,
                human_decision,
                timestamp,
                timestamp,
                recruitment_status,
            ),
        )

    def record_candidate_role_status_change(
        self,
        *,
        candidate_id: int,
        role_id: int,
        to_status: str,
        operator: str = "user",
        reason_code: str = "",
        note: str = "",
        changed_at: str | None = None,
    ) -> int:
        connection = self.db.get_connection()
        timestamp = changed_at or now_iso()
        with connection:
            return self._record_candidate_role_status_change(
                connection,
                candidate_id=candidate_id,
                role_id=role_id,
                to_status=to_status,
                operator=operator,
                reason_code=reason_code,
                note=note,
                timestamp=timestamp,
            )

    def _record_candidate_role_status_change(
        self,
        connection: sqlite3.Connection,
        *,
        candidate_id: int,
        role_id: int,
        to_status: str,
        operator: str = "user",
        reason_code: str = "",
        note: str = "",
        timestamp: str | None = None,
    ) -> int:
        timestamp = timestamp or now_iso()
        normalized_status = self._normalize_recruitment_status(to_status)
        normalized_reason = self._normalize_reason_code(reason_code)
        current_status = self._get_candidate_role_recruitment_status(
            connection,
            candidate_id=candidate_id,
            role_id=role_id,
        )
        if current_status == "":
            self._upsert_candidate_role_match(
                connection,
                candidate_id=candidate_id,
                role_id=role_id,
                match_status="screening_pending",
                recruitment_status="collected",
                timestamp=timestamp,
            )
            current_status = "collected"
        human_decision = (
            normalized_reason
            if normalized_reason in {"manual_review_passed", "manual_review_rejected"}
            else ""
        )
        connection.execute(
            """
            UPDATE candidate_role_matches
            SET recruitment_status = ?,
                human_decision = CASE
                    WHEN ? <> '' THEN ?
                    ELSE human_decision
                END,
                updated_at = ?
            WHERE candidate_id = ? AND role_id = ?
            """,
            (
                normalized_status,
                human_decision,
                human_decision,
                timestamp,
                candidate_id,
                role_id,
            ),
        )
        cursor = connection.execute(
            """
            INSERT INTO candidate_role_status_events(
                candidate_id,
                role_id,
                from_status,
                to_status,
                operator,
                reason_code,
                note,
                changed_at,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                role_id,
                current_status,
                normalized_status,
                operator,
                normalized_reason,
                note,
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid)

    def _candidate_role_match_exists(
        self,
        connection: sqlite3.Connection,
        *,
        candidate_id: int,
        role_id: int,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM candidate_role_matches
            WHERE candidate_id = ? AND role_id = ?
            LIMIT 1
            """,
            (candidate_id, role_id),
        ).fetchone()
        return row is not None

    def _get_candidate_role_recruitment_status(
        self,
        connection: sqlite3.Connection,
        *,
        candidate_id: int,
        role_id: int,
    ) -> str:
        row = connection.execute(
            """
            SELECT recruitment_status
            FROM candidate_role_matches
            WHERE candidate_id = ? AND role_id = ?
            LIMIT 1
            """,
            (candidate_id, role_id),
        ).fetchone()
        if row is None:
            return ""
        return str(row["recruitment_status"] or "")

    @staticmethod
    def _normalize_recruitment_status(status: str, *, allow_empty: bool = False) -> str:
        normalized = status.strip()
        if allow_empty and not normalized:
            return ""
        if normalized not in RECRUITMENT_STATUSES:
            raise ValueError(f"Unsupported recruitment status: {status}")
        return normalized

    @staticmethod
    def _normalize_reason_code(reason_code: str, *, allow_empty: bool = True) -> str:
        normalized = str(reason_code or "").strip()
        if allow_empty and not normalized:
            return ""
        if normalized not in REASON_CODES:
            raise ValueError(f"Unsupported recruitment reason code: {reason_code}")
        return normalized

    def _recruitment_status_filter_values(self, statuses: Iterable[str]) -> list[str]:
        values: list[str] = []
        for status in statuses:
            normalized = str(status or "").strip()
            if not normalized:
                continue
            if normalized == "uncontacted":
                for item in ["collected", "screened", "priority_outreach"]:
                    if item not in values:
                        values.append(item)
                continue
            normalized = self._normalize_recruitment_status(normalized)
            if normalized not in values:
                values.append(normalized)
        return values

    @staticmethod
    def _match_status_for_task_status(task_status: str) -> str:
        return {
            "pending": "screening_pending",
            "running": "screening_running",
            "retrying": "screening_retrying",
            "success": "ai_screened",
            "failed": "ai_failed",
            "manual_check": "manual_check",
            "hold": "hold",
        }.get(task_status, "screening_pending")

    def get_screening_task_counts(self, run_id: int) -> dict[str, int]:
        connection = self.db.get_connection()
        rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM screening_tasks
            WHERE run_id = ?
            GROUP BY status
            """,
            (run_id,),
        ).fetchall()
        counts = {
            "pending": 0,
            "running": 0,
            "retrying": 0,
            "success": 0,
            "failed": 0,
            "manual_check": 0,
            "hold": 0,
        }
        for row in rows:
            counts[str(row["status"])] = int(row["count"])
        counts["total"] = sum(counts.values())
        return counts

    def get_screening_efficiency_summary(self, run_id: int) -> dict[str, int]:
        connection = self.db.get_connection()
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN route = 'pass_to_ai' THEN 1 ELSE 0 END) AS ai_routed,
                SUM(CASE WHEN route <> 'pass_to_ai' THEN 1 ELSE 0 END) AS avoided_by_rules,
                SUM(CASE WHEN status = 'manual_check' THEN 1 ELSE 0 END) AS manual_check,
                SUM(CASE WHEN status = 'hold' THEN 1 ELSE 0 END) AS hold,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN status IN ('pending', 'running', 'retrying') THEN 1 ELSE 0 END) AS unfinished,
                SUM(retry_count) AS retry_attempts,
                SUM(CASE WHEN result_source = 'model' THEN 1 ELSE 0 END) AS model_calls,
                SUM(CASE WHEN result_source = 'cached' THEN 1 ELSE 0 END) AS cached_reuses,
                SUM(CASE WHEN result_source = 'recovered' THEN 1 ELSE 0 END) AS recovered_results,
                SUM(CASE WHEN result_source = 'legacy' THEN 1 ELSE 0 END) AS legacy_results,
                SUM(CASE WHEN status = 'success' AND result_source = '' THEN 1 ELSE 0 END) AS unknown_successes
            FROM screening_tasks
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        keys = [
            "total",
            "ai_routed",
            "avoided_by_rules",
            "manual_check",
            "hold",
            "success",
            "failed",
            "unfinished",
            "retry_attempts",
            "model_calls",
            "cached_reuses",
            "recovered_results",
            "legacy_results",
            "unknown_successes",
        ]
        summary = {key: int(row[key] or 0) for key in keys}
        summary["handled"] = summary["success"] + summary["manual_check"] + summary["hold"]
        return summary

    def list_screening_tasks(self, run_id: int) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        return list(
            connection.execute(
                """
                SELECT *
                FROM screening_tasks
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        )

    def get_cached_screening_result(
        self,
        *,
        role_id: int,
        candidate_id: int,
        model_name: str,
        prompt_version: str,
        request_payload_hash: str,
        exclude_run_id: int | None = None,
    ) -> sqlite3.Row | None:
        connection = self.db.get_connection()
        params: list[object] = [
            role_id,
            candidate_id,
            model_name,
            prompt_version,
            request_payload_hash,
        ]
        exclude_sql = ""
        if exclude_run_id is not None:
            exclude_sql = "AND t.run_id <> ?"
            params.append(exclude_run_id)
        return connection.execute(
            f"""
            SELECT r.*
            FROM screening_tasks t
            JOIN screening_results r ON r.id = t.result_id
            WHERE t.role_id = ?
              AND t.candidate_id = ?
              AND t.model_name = ?
              AND t.prompt_version = ?
              AND t.request_payload_hash = ?
              AND t.status = 'success'
              AND t.result_id IS NOT NULL
              {exclude_sql}
            ORDER BY r.created_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()

    def get_screening_result(self, run_id: int, candidate_id: int) -> sqlite3.Row | None:
        connection = self.db.get_connection()
        return connection.execute(
            """
            SELECT *
            FROM screening_results
            WHERE run_id = ? AND candidate_id = ?
            LIMIT 1
            """,
            (run_id, candidate_id),
        ).fetchone()

    def recover_interrupted_screening_tasks(self) -> int:
        connection = self.db.get_connection()
        rows = connection.execute(
            """
            SELECT DISTINCT run_id
            FROM screening_tasks
            WHERE status IN ('running', 'retrying')
            """
        ).fetchall()
        run_ids = [int(row["run_id"]) for row in rows]
        if not run_ids:
            return 0
        task_rows = connection.execute(
            """
            SELECT candidate_id, role_id
            FROM screening_tasks
            WHERE status IN ('running', 'retrying')
            """
        ).fetchall()
        timestamp = now_iso()
        with connection:
            cursor = connection.execute(
                """
                UPDATE screening_tasks
                SET status = 'pending',
                    started_at = NULL,
                    error_message = 'Recovered after interrupted screening run',
                    updated_at = ?
                WHERE status IN ('running', 'retrying')
                """,
                (timestamp,),
            )
            for task_row in task_rows:
                self._upsert_candidate_role_match(
                    connection,
                    candidate_id=int(task_row["candidate_id"]),
                    role_id=int(task_row["role_id"]),
                    match_status="screening_pending",
                    timestamp=timestamp,
                )
            for run_id in run_ids:
                counts = self.get_screening_task_counts(run_id)
                connection.execute(
                    """
                    UPDATE screening_runs
                    SET status = 'recoverable',
                        completed_candidates = ?,
                        failed_candidates = ?,
                        completed_at = NULL,
                        note = 'Recovered after interrupted screening run'
                    WHERE id = ? AND status IN ('running', 'recoverable')
                    """,
                    (
                        counts["success"] + counts.get("manual_check", 0) + counts.get("hold", 0),
                        counts["failed"],
                        run_id,
                    ),
                )
        return int(cursor.rowcount)

    def save_screening_result(self, result: ScreeningResult) -> int:
        connection = self.db.get_connection()
        timestamp = result.created_at or now_iso()
        connection.execute(
            """
            INSERT INTO screening_results(
                run_id,
                candidate_id,
                rating,
                persona,
                status,
                raw_response,
                error,
                confidence,
                evidence_json,
                gap_json,
                risk_json,
                recommended_action,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, candidate_id) DO UPDATE SET
                rating = excluded.rating,
                persona = excluded.persona,
                status = excluded.status,
                raw_response = excluded.raw_response,
                error = excluded.error,
                confidence = excluded.confidence,
                evidence_json = excluded.evidence_json,
                gap_json = excluded.gap_json,
                risk_json = excluded.risk_json,
                recommended_action = excluded.recommended_action,
                created_at = excluded.created_at
            """,
            (
                result.run_id,
                result.candidate_id,
                result.rating,
                result.persona,
                result.status,
                result.raw_response,
                result.error,
                result.confidence,
                result.evidence_json,
                result.gap_json,
                result.risk_json,
                result.recommended_action,
                timestamp,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT id FROM screening_results WHERE run_id = ? AND candidate_id = ?",
            (result.run_id, result.candidate_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to save screening result")
        return int(row["id"])

    def update_screening_run_progress(self, run_id: int, completed: int, failed: int) -> None:
        connection = self.db.get_connection()
        connection.execute(
            """
            UPDATE screening_runs
            SET completed_candidates = ?, failed_candidates = ?
            WHERE id = ?
            """,
            (completed, failed, run_id),
        )
        connection.commit()

    def mark_screening_run_running(self, run_id: int) -> None:
        connection = self.db.get_connection()
        connection.execute(
            """
            UPDATE screening_runs
            SET status = 'running',
                completed_at = NULL,
                note = ''
            WHERE id = ?
            """,
            (run_id,),
        )
        connection.commit()

    def finalize_screening_run(self, run_id: int, status: str, completed: int, failed: int, note: str = "") -> None:
        connection = self.db.get_connection()
        connection.execute(
            """
            UPDATE screening_runs
            SET status = ?, completed_candidates = ?, failed_candidates = ?, completed_at = ?, note = ?
            WHERE id = ?
            """,
            (status, completed, failed, now_iso(), note, run_id),
        )
        connection.commit()

    def list_screening_candidates(
        self,
        *,
        job_title: str = "",
        batch_id: int | None = None,
        limit: int = 0,
    ) -> list[dict[str, object]]:
        rows = self.list_candidates(job_title=job_title, batch_id=batch_id)
        candidates = [dict(row) for row in rows]
        return candidates[:limit] if limit > 0 else candidates

    def list_screening_runs(self, limit: int = 50, origin: str = "") -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        where_sql = "WHERE sr.origin = ?" if origin else ""
        params: tuple[object, ...] = (origin, limit) if origin else (limit,)
        return list(
            connection.execute(
                f"""
                SELECT sr.*, sp.job_title AS profile_job_title
                FROM screening_runs sr
                JOIN screening_profiles sp ON sp.id = sr.profile_id
                {where_sql}
                ORDER BY sr.started_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        )

    def get_screening_run(self, run_id: int) -> sqlite3.Row | None:
        connection = self.db.get_connection()
        return connection.execute(
            """
            SELECT sr.*, sp.job_title AS profile_job_title
            FROM screening_runs sr
            JOIN screening_profiles sp ON sp.id = sr.profile_id
            WHERE sr.id = ?
            """,
            (run_id,),
        ).fetchone()

    def list_screening_run_candidates(self, run_id: int) -> list[dict[str, object]]:
        connection = self.db.get_connection()
        rows = connection.execute(
            """
            SELECT c.*
            FROM screening_tasks t
            JOIN candidates c ON c.id = t.candidate_id
            WHERE t.run_id = ?
            ORDER BY t.id
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def reset_failed_screening_tasks(self, run_id: int) -> int:
        connection = self.db.get_connection()
        task_rows = connection.execute(
            """
            SELECT candidate_id, role_id
            FROM screening_tasks
            WHERE run_id = ? AND status = 'failed'
            """,
            (run_id,),
        ).fetchall()
        timestamp = now_iso()
        with connection:
            cursor = connection.execute(
                """
                UPDATE screening_tasks
                SET status = 'pending',
                    retry_count = 0,
                    result_id = NULL,
                    error_message = '',
                    started_at = NULL,
                    finished_at = NULL,
                    updated_at = ?
                WHERE run_id = ? AND status = 'failed'
                """,
                (timestamp, run_id),
            )
            for task_row in task_rows:
                self._upsert_candidate_role_match(
                    connection,
                    candidate_id=int(task_row["candidate_id"]),
                    role_id=int(task_row["role_id"]),
                    match_status="screening_pending",
                    timestamp=timestamp,
                )
            if cursor.rowcount > 0:
                counts = self.get_screening_task_counts(run_id)
                connection.execute(
                    """
                    UPDATE screening_runs
                    SET status = 'recoverable',
                        completed_candidates = ?,
                        failed_candidates = ?,
                        completed_at = NULL,
                        note = 'Failed tasks reset for retry'
                    WHERE id = ?
                    """,
                    (
                        counts["success"] + counts.get("manual_check", 0) + counts.get("hold", 0),
                        counts["failed"],
                        run_id,
                    ),
                )
        return int(cursor.rowcount)

    def reset_failed_screening_task(self, task_id: int) -> int | None:
        connection = self.db.get_connection()
        task_row = connection.execute(
            """
            SELECT run_id, candidate_id, role_id
            FROM screening_tasks
            WHERE id = ? AND status = 'failed'
            """,
            (task_id,),
        ).fetchone()
        if task_row is None:
            return None
        run_id = int(task_row["run_id"])
        timestamp = now_iso()
        with connection:
            cursor = connection.execute(
                """
                UPDATE screening_tasks
                SET status = 'pending',
                    retry_count = 0,
                    result_id = NULL,
                    result_source = '',
                    error_message = '',
                    started_at = NULL,
                    finished_at = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'failed'
                """,
                (timestamp, task_id),
            )
            if cursor.rowcount <= 0:
                return None
            self._upsert_candidate_role_match(
                connection,
                candidate_id=int(task_row["candidate_id"]),
                role_id=int(task_row["role_id"]),
                match_status="screening_pending",
                timestamp=timestamp,
            )
            counts = self.get_screening_task_counts(run_id)
            connection.execute(
                """
                UPDATE screening_runs
                SET status = 'recoverable',
                    completed_candidates = ?,
                    failed_candidates = ?,
                    completed_at = NULL,
                    note = 'Selected failed task reset for retry'
                WHERE id = ?
                """,
                (
                    counts["success"] + counts.get("manual_check", 0) + counts.get("hold", 0),
                    counts["failed"],
                    run_id,
                ),
            )
        return run_id

    def list_screening_results(self, run_id: int) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        return list(
            connection.execute(
                """
                SELECT r.*, c.name, c.job_title, c.raw_card_text
                FROM screening_results r
                JOIN candidates c ON c.id = r.candidate_id
                WHERE r.run_id = ?
                ORDER BY
                    CASE r.rating
                        WHEN 'UR' THEN 1 WHEN 'SSR' THEN 2 WHEN 'SR' THEN 3
                        WHEN 'R' THEN 4 WHEN 'N' THEN 5 ELSE 6
                    END,
                    c.name COLLATE NOCASE
                """,
                (run_id,),
            ).fetchall()
        )

    def list_screening_task_results(self, run_id: int) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        return list(
            connection.execute(
                """
                SELECT
                    t.id AS task_id,
                    t.run_id,
                    t.candidate_id,
                    t.status AS task_status,
                    t.route,
                    t.route_reason,
                    t.route_details_json,
                    t.retry_count,
                    t.max_retry_count,
                    t.result_source,
                    t.error_message AS task_error,
                    t.created_at AS task_created_at,
                    t.started_at AS task_started_at,
                    t.finished_at AS task_finished_at,
                    t.updated_at AS task_updated_at,
                    r.id AS result_id,
                    r.rating,
                    r.persona,
                    r.confidence,
                    r.recommended_action,
                    r.evidence_json,
                    r.gap_json,
                    r.risk_json,
                    r.status AS result_status,
                    r.raw_response,
                    r.error,
                    r.created_at AS result_created_at,
                    c.name,
                    c.job_title,
                    c.raw_card_text
                FROM screening_tasks t
                JOIN candidates c ON c.id = t.candidate_id
                LEFT JOIN screening_results r ON r.id = t.result_id
                WHERE t.run_id = ?
                ORDER BY
                    CASE t.status
                        WHEN 'running' THEN 1
                        WHEN 'retrying' THEN 2
                        WHEN 'pending' THEN 3
                        WHEN 'manual_check' THEN 4
                        WHEN 'hold' THEN 5
                        WHEN 'failed' THEN 6
                        WHEN 'success' THEN 7
                        ELSE 8
                    END,
                    CASE r.rating
                        WHEN 'UR' THEN 1 WHEN 'SSR' THEN 2 WHEN 'SR' THEN 3
                        WHEN 'R' THEN 4 WHEN 'N' THEN 5 ELSE 6
                    END,
                    t.id
                """,
                (run_id,),
            ).fetchall()
        )

    def list_candidate_role_matches(
        self,
        *,
        role_id: int | None = None,
        match_statuses: Iterable[str] | None = None,
        recruitment_statuses: Iterable[str] | None = None,
        minimum_rating: str | None = None,
        job_title: str = "",
        batch_id: int | None = None,
        city: str = "",
        years_min: int | str | None = None,
        years_max: int | str | None = None,
        profile_tag: str = "",
        last_active_days: int | str | None = None,
        latest_reason_code: str = "",
        query: str = "",
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        joins = ""
        where = []
        params: list[object] = []
        if batch_id is not None:
            joins += " JOIN capture_batch_items bi ON bi.candidate_id = c.id "
            where.append("bi.batch_id = ?")
            params.append(batch_id)
        if role_id is not None:
            where.append("m.role_id = ?")
            params.append(role_id)
        if job_title:
            where.append("c.job_title = ?")
            params.append(job_title)
        if city:
            where.append("cp.city = ?")
            params.append(city.strip())
        min_years = self._optional_int(years_min)
        if min_years is not None:
            where.append("cp.years_experience >= ?")
            params.append(min_years)
        max_years = self._optional_int(years_max)
        if max_years is not None:
            where.append("cp.years_experience <= ?")
            params.append(max_years)
        for profile_token in self._profile_tag_tokens(profile_tag):
            tag = f"%{profile_token}%"
            where.append(
                """
                (
                    cp.industry_tags_json LIKE ?
                    OR cp.skill_tags_json LIKE ?
                    OR cp.job_family LIKE ?
                    OR cp.job_track LIKE ?
                )
                """
            )
            params.extend([tag, tag, tag, tag])
        last_active_since = self._last_active_since(last_active_days)
        if last_active_since:
            where.append("cp.last_active_at >= ?")
            params.append(last_active_since)
        normalized_latest_reason = str(latest_reason_code or "").strip()
        if normalized_latest_reason:
            where.append("le.reason_code = ?")
            params.append(self._normalize_reason_code(normalized_latest_reason))
        statuses = list(match_statuses or [])
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where.append(f"m.match_status IN ({placeholders})")
            params.extend(statuses)
        recruitment_status_values = self._recruitment_status_filter_values(recruitment_statuses or [])
        if recruitment_status_values:
            placeholders = ",".join("?" for _ in recruitment_status_values)
            where.append(f"m.recruitment_status IN ({placeholders})")
            params.extend(recruitment_status_values)
        if minimum_rating:
            where.append(
                """
                CASE m.latest_rating
                    WHEN 'UR' THEN 5
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 3
                    WHEN 'R' THEN 2
                    WHEN 'N' THEN 1
                    ELSE 0
                END >= ?
                """
            )
            params.append(self._rating_score(minimum_rating))
        normalized_query = query.strip()
        if normalized_query:
            like = f"%{normalized_query}%"
            where.append(
                """
                (
                    c.name LIKE ?
                    OR c.active_status LIKE ?
                    OR c.job_title LIKE ?
                    OR c.work_experience_text LIKE ?
                    OR c.tags_text LIKE ?
                    OR c.summary_text LIKE ?
                    OR c.raw_card_text LIKE ?
                )
                """
            )
            params.extend([like, like, like, like, like, like, like])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, min(int(limit), 1000)))
        return list(
            connection.execute(
                f"""
                SELECT
                    c.id AS id,
                    m.id AS match_id,
                    m.candidate_id,
                    m.role_id,
                    m.latest_rating,
                    m.latest_confidence,
                    r.evidence_json,
                    r.gap_json,
                    r.risk_json,
                    r.recommended_action,
                    m.match_status,
                    m.recruitment_status,
                    m.screening_result_id,
                    m.human_decision,
                    m.created_at AS match_created_at,
                    m.updated_at AS match_updated_at,
                    le.changed_at AS latest_status_changed_at,
                    le.from_status AS latest_status_from,
                    le.to_status AS latest_status_to,
                    le.reason_code AS latest_reason_code,
                    le.note AS latest_status_note,
                    le.operator AS latest_status_operator,
                    c.name,
                    c.job_title,
                    c.active_status,
                    c.expected_salary,
                    c.work_experience_text,
                    c.education_text,
                    c.tags_text,
                    c.summary_text,
                    c.raw_card_text,
                    cp.city,
                    cp.years_experience,
                    cp.job_family,
                    cp.job_track,
                    cp.industry_tags_json,
                    cp.skill_tags_json,
                    cp.last_active_at,
                    cp.profile_completeness,
                    p.job_title AS role_title
                FROM candidate_role_matches m
                JOIN candidates c ON c.id = m.candidate_id
                JOIN screening_profiles p ON p.id = m.role_id
                LEFT JOIN screening_results r ON r.id = m.screening_result_id
                LEFT JOIN candidate_profiles cp ON cp.candidate_id = m.candidate_id
                LEFT JOIN candidate_role_status_events le ON le.id = (
                    SELECT e2.id
                    FROM candidate_role_status_events e2
                    WHERE e2.candidate_id = m.candidate_id
                      AND e2.role_id = m.role_id
                    ORDER BY e2.changed_at DESC, e2.id DESC
                    LIMIT 1
                )
                {joins}
                {where_sql}
                ORDER BY
                    CASE m.latest_rating
                        WHEN 'UR' THEN 1 WHEN 'SSR' THEN 2 WHEN 'SR' THEN 3
                        WHEN 'R' THEN 4 WHEN 'N' THEN 5 ELSE 6
                    END,
                    m.updated_at DESC,
                    c.name COLLATE NOCASE
                LIMIT ?
                """,
                params,
            ).fetchall()
        )

    def list_manual_review_candidates(
        self,
        *,
        role_id: int | None = None,
        limit: int = 300,
    ) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        where = [
            """
            (
                m.match_status IN ('manual_check', 'hold', 'ai_failed')
                OR m.latest_confidence = 'low'
                OR r.recommended_action IN ('manual_check', 'hold')
                OR TRIM(COALESCE(r.risk_json, '')) NOT IN ('', '[]')
            )
            AND m.recruitment_status IN ('collected', 'screened')
            """
        ]
        params: list[object] = []
        if role_id is not None:
            where.append("m.role_id = ?")
            params.append(role_id)
        where_sql = "WHERE " + " AND ".join(where)
        params.append(max(1, min(int(limit), 1000)))
        return list(
            connection.execute(
                f"""
                SELECT
                    c.id AS id,
                    m.id AS match_id,
                    m.candidate_id,
                    m.role_id,
                    m.latest_rating,
                    m.latest_confidence,
                    m.match_status,
                    m.recruitment_status,
                    m.screening_result_id,
                    m.updated_at AS match_updated_at,
                    c.name,
                    c.active_status,
                    c.expected_salary,
                    c.work_experience_text,
                    c.education_text,
                    c.tags_text,
                    c.summary_text,
                    c.raw_card_text,
                    cp.city,
                    cp.years_experience,
                    cp.job_family,
                    cp.job_track,
                    cp.industry_tags_json,
                    cp.skill_tags_json,
                    p.job_title AS role_title,
                    r.persona,
                    r.confidence,
                    r.evidence_json,
                    r.gap_json,
                    r.risk_json,
                    r.recommended_action,
                    t.route_reason,
                    t.route_details_json,
                    t.error_message AS task_error,
                    t.retry_count,
                    t.max_retry_count,
                    t.updated_at AS task_updated_at,
                    CASE
                        WHEN m.match_status = 'manual_check' THEN '规则分流：人工确认'
                        WHEN m.match_status = 'hold' THEN '规则分流：暂缓'
                        WHEN m.match_status = 'ai_failed' THEN 'AI筛选失败'
                        WHEN m.latest_confidence = 'low' THEN '模型置信度低'
                        WHEN r.recommended_action = 'manual_check' THEN '模型建议人工确认'
                        WHEN r.recommended_action = 'hold' THEN '模型建议暂缓'
                        WHEN TRIM(COALESCE(r.risk_json, '')) NOT IN ('', '[]') THEN '模型识别到风险'
                        ELSE '需要复核'
                    END AS review_reason
                FROM candidate_role_matches m
                JOIN candidates c ON c.id = m.candidate_id
                JOIN screening_profiles p ON p.id = m.role_id
                LEFT JOIN candidate_profiles cp ON cp.candidate_id = m.candidate_id
                LEFT JOIN screening_results r ON r.id = m.screening_result_id
                LEFT JOIN screening_tasks t
                  ON t.id = (
                    SELECT t2.id
                    FROM screening_tasks t2
                    WHERE t2.candidate_id = m.candidate_id
                      AND t2.role_id = m.role_id
                    ORDER BY t2.updated_at DESC, t2.id DESC
                    LIMIT 1
                  )
                {where_sql}
                ORDER BY
                    CASE
                        WHEN m.match_status = 'manual_check' THEN 1
                        WHEN m.match_status = 'ai_failed' THEN 2
                        WHEN m.latest_confidence = 'low' THEN 3
                        WHEN TRIM(COALESCE(r.risk_json, '')) NOT IN ('', '[]') THEN 4
                        WHEN m.match_status = 'hold' THEN 5
                        ELSE 6
                    END,
                    m.updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        )

    def get_manual_review_quality_summary(
        self,
        *,
        role_id: int | None = None,
        minimum_rating: str | None = None,
        screened_since: str | None = None,
    ) -> dict[str, int]:
        connection = self.db.get_connection()
        pair_key = "m.candidate_id || ':' || m.role_id"
        review_condition = """
            (
                m.match_status IN ('manual_check', 'hold', 'ai_failed')
                OR m.latest_confidence = 'low'
                OR r.recommended_action IN ('manual_check', 'hold')
                OR TRIM(COALESCE(r.risk_json, '')) NOT IN ('', '[]')
            )
        """
        where = ["m.recruitment_status IN ('collected', 'screened')"]
        params: list[object] = []
        if role_id is not None:
            where.append("m.role_id = ?")
            params.append(role_id)
        if minimum_rating:
            where.append(
                """
                CASE m.latest_rating
                    WHEN 'UR' THEN 5
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 3
                    WHEN 'R' THEN 2
                    WHEN 'N' THEN 1
                    ELSE 0
                END >= ?
                """
            )
            params.append(self._rating_score(minimum_rating))
        if screened_since:
            where.append("COALESCE(r.created_at, m.updated_at) >= ?")
            params.append(screened_since)
        row = connection.execute(
            f"""
            SELECT
                COUNT(DISTINCT {pair_key}) AS active_total,
                COUNT(DISTINCT CASE WHEN {review_condition} THEN {pair_key} END) AS manual_review_total,
                COUNT(DISTINCT CASE WHEN m.match_status = 'manual_check' THEN {pair_key} END) AS rule_manual_check,
                COUNT(DISTINCT CASE WHEN m.match_status = 'hold' THEN {pair_key} END) AS rule_hold,
                COUNT(DISTINCT CASE WHEN m.match_status = 'ai_failed' THEN {pair_key} END) AS ai_failed,
                COUNT(DISTINCT CASE WHEN m.latest_confidence = 'low' THEN {pair_key} END) AS low_confidence,
                COUNT(DISTINCT CASE WHEN r.recommended_action IN ('manual_check', 'hold') THEN {pair_key} END) AS model_manual_action,
                COUNT(DISTINCT CASE WHEN TRIM(COALESCE(r.risk_json, '')) NOT IN ('', '[]') THEN {pair_key} END) AS risky
            FROM candidate_role_matches m
            LEFT JOIN screening_results r ON r.id = m.screening_result_id
            WHERE {' AND '.join(where)}
            """,
            params,
        ).fetchone()
        return {
            "active_total": int(row["active_total"] or 0),
            "manual_review_total": int(row["manual_review_total"] or 0),
            "rule_manual_check": int(row["rule_manual_check"] or 0),
            "rule_hold": int(row["rule_hold"] or 0),
            "ai_failed": int(row["ai_failed"] or 0),
            "low_confidence": int(row["low_confidence"] or 0),
            "model_manual_action": int(row["model_manual_action"] or 0),
            "risky": int(row["risky"] or 0),
        }

    def list_candidate_role_status_events(
        self,
        *,
        candidate_id: int | None = None,
        role_id: int | None = None,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        where = []
        params: list[object] = []
        if candidate_id is not None:
            where.append("e.candidate_id = ?")
            params.append(candidate_id)
        if role_id is not None:
            where.append("e.role_id = ?")
            params.append(role_id)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, min(int(limit), 1000)))
        return list(
            connection.execute(
                f"""
                SELECT
                    e.*,
                    c.name,
                    p.job_title AS role_title
                FROM candidate_role_status_events e
                JOIN candidates c ON c.id = e.candidate_id
                JOIN screening_profiles p ON p.id = e.role_id
                {where_sql}
                ORDER BY e.changed_at DESC, e.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        )

    def get_recruitment_funnel_counts(
        self,
        *,
        role_id: int | None = None,
        minimum_rating: str | None = None,
        screened_since: str | None = None,
    ) -> dict[str, int]:
        connection = self.db.get_connection()
        where = []
        params: list[object] = []
        if role_id is not None:
            where.append("e.role_id = ?")
            params.append(role_id)
        if minimum_rating:
            where.append(
                """
                CASE m.latest_rating
                    WHEN 'UR' THEN 5
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 3
                    WHEN 'R' THEN 2
                    WHEN 'N' THEN 1
                    ELSE 0
                END >= ?
                """
            )
            params.append(self._rating_score(minimum_rating))
        if screened_since:
            where.append("COALESCE(r.created_at, m.updated_at) >= ?")
            params.append(screened_since)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = connection.execute(
            f"""
            SELECT
                e.to_status,
                COUNT(DISTINCT e.candidate_id || ':' || e.role_id) AS count
            FROM candidate_role_status_events e
            JOIN candidate_role_matches m
              ON m.candidate_id = e.candidate_id
             AND m.role_id = e.role_id
            LEFT JOIN screening_results r ON r.id = m.screening_result_id
            {where_sql}
            GROUP BY e.to_status
            """,
            params,
        ).fetchall()
        counts = {status: 0 for status in sorted(RECRUITMENT_STATUSES)}
        for row in rows:
            counts[str(row["to_status"])] = int(row["count"])
        return counts

    def list_recruitment_funnel_candidates(
        self,
        *,
        role_id: int | None = None,
        status: str | None = None,
        rating: str | None = None,
        minimum_rating: str | None = None,
        screened_since: str | None = None,
        limit: int = 300,
    ) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        params: list[object] = []
        normalized_status = ""
        if status:
            normalized_status = self._normalize_recruitment_status(status)
            event_join = """
            JOIN (
                SELECT candidate_id, role_id, MAX(changed_at) AS reached_at
                FROM candidate_role_status_events
                WHERE to_status = ?
                GROUP BY candidate_id, role_id
            ) e ON e.candidate_id = m.candidate_id AND e.role_id = m.role_id
            """
            params.append(normalized_status)
            funnel_status_sql = f"'{normalized_status}' AS funnel_status"
        else:
            event_join = """
            LEFT JOIN (
                SELECT candidate_id, role_id, MAX(changed_at) AS reached_at
                FROM candidate_role_status_events
                GROUP BY candidate_id, role_id
            ) e ON e.candidate_id = m.candidate_id AND e.role_id = m.role_id
            """
            funnel_status_sql = "m.recruitment_status AS funnel_status"
        where = [
            "m.screening_result_id IS NOT NULL",
            "m.latest_rating <> ''",
        ]
        if role_id is not None:
            where.append("m.role_id = ?")
            params.append(role_id)
        if rating:
            where.append("m.latest_rating = ?")
            params.append(str(rating).upper())
        elif minimum_rating:
            where.append(
                """
                CASE m.latest_rating
                    WHEN 'UR' THEN 5
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 3
                    WHEN 'R' THEN 2
                    WHEN 'N' THEN 1
                    ELSE 0
                END >= ?
                """
            )
            params.append(self._rating_score(minimum_rating))
        if screened_since:
            where.append("COALESCE(r.created_at, m.updated_at) >= ?")
            params.append(screened_since)
        params.append(max(1, min(int(limit), 1000)))
        return list(
            connection.execute(
                f"""
                SELECT
                    c.id AS id,
                    m.id AS match_id,
                    m.candidate_id,
                    m.role_id,
                    {funnel_status_sql},
                    e.reached_at,
                    m.latest_rating,
                    m.latest_confidence,
                    m.match_status,
                    m.recruitment_status,
                    m.screening_result_id,
                    m.human_decision,
                    m.updated_at AS match_updated_at,
                    r.created_at AS screened_at,
                    r.recommended_action,
                    r.risk_json,
                    c.name,
                    c.job_title,
                    c.active_status,
                    c.expected_salary,
                    c.work_experience_text,
                    c.education_text,
                    c.tags_text,
                    c.summary_text,
                    cp.city,
                    cp.years_experience,
                    cp.job_family,
                    cp.job_track,
                    cp.industry_tags_json,
                    cp.skill_tags_json,
                    p.job_title AS role_title
                FROM candidate_role_matches m
                JOIN candidates c ON c.id = m.candidate_id
                JOIN screening_profiles p ON p.id = m.role_id
                JOIN screening_results r ON r.id = m.screening_result_id
                LEFT JOIN candidate_profiles cp ON cp.candidate_id = m.candidate_id
                {event_join}
                WHERE {' AND '.join(where)}
                ORDER BY
                    CASE m.latest_rating
                        WHEN 'UR' THEN 1
                        WHEN 'SSR' THEN 2
                        WHEN 'SR' THEN 3
                        WHEN 'R' THEN 4
                        WHEN 'N' THEN 5
                        ELSE 6
                    END,
                    COALESCE(e.reached_at, m.updated_at) DESC,
                    c.name COLLATE NOCASE
                LIMIT ?
                """,
                params,
            ).fetchall()
        )

    def get_recruitment_reason_counts(
        self,
        *,
        role_id: int | None = None,
        minimum_rating: str | None = None,
        screened_since: str | None = None,
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        system_reasons = sorted(SYSTEM_REASON_CODES)
        where = [
            "e.reason_code <> ''",
            f"e.reason_code NOT IN ({', '.join('?' for _ in system_reasons)})",
        ]
        params: list[object] = [*system_reasons]
        if role_id is not None:
            where.append("e.role_id = ?")
            params.append(role_id)
        if minimum_rating:
            where.append(
                """
                CASE m.latest_rating
                    WHEN 'UR' THEN 5
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 3
                    WHEN 'R' THEN 2
                    WHEN 'N' THEN 1
                    ELSE 0
                END >= ?
                """
            )
            params.append(self._rating_score(minimum_rating))
        if screened_since:
            where.append("COALESCE(r.created_at, m.updated_at) >= ?")
            params.append(screened_since)
        params.append(max(1, int(limit)))
        return connection.execute(
            f"""
            SELECT
                e.reason_code,
                COUNT(DISTINCT e.candidate_id || ':' || e.role_id) AS count,
                MAX(e.changed_at) AS latest_changed_at
            FROM candidate_role_status_events e
            JOIN candidate_role_matches m
              ON m.candidate_id = e.candidate_id
             AND m.role_id = e.role_id
            LEFT JOIN screening_results r ON r.id = m.screening_result_id
            WHERE {' AND '.join(where)}
            GROUP BY e.reason_code
            ORDER BY count DESC, latest_changed_at DESC, e.reason_code ASC
            LIMIT ?
            """,
            params,
        ).fetchall()

    def get_ai_rating_conversion_counts(
        self,
        *,
        role_id: int | None = None,
        minimum_rating: str | None = None,
        screened_since: str | None = None,
    ) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        pair_key = "m.candidate_id || ':' || m.role_id"
        where = [
            "m.screening_result_id IS NOT NULL",
            "m.latest_rating <> ''",
        ]
        params: list[object] = []
        if role_id is not None:
            where.append("m.role_id = ?")
            params.append(role_id)
        if minimum_rating:
            where.append(
                """
                CASE m.latest_rating
                    WHEN 'UR' THEN 5
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 3
                    WHEN 'R' THEN 2
                    WHEN 'N' THEN 1
                    ELSE 0
                END >= ?
                """
            )
            params.append(self._rating_score(minimum_rating))
        if screened_since:
            where.append("COALESCE(r.created_at, m.updated_at) >= ?")
            params.append(screened_since)
        return connection.execute(
            f"""
            SELECT
                m.latest_rating AS rating,
                COUNT(DISTINCT {pair_key}) AS screened_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'contacted' THEN {pair_key} END) AS contacted_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'replied' THEN {pair_key} END) AS replied_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'interviewing' THEN {pair_key} END) AS interviewing_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'offer' THEN {pair_key} END) AS offer_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'hired' THEN {pair_key} END) AS hired_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'rejected' THEN {pair_key} END) AS rejected_count,
                MAX(COALESCE(r.created_at, m.updated_at)) AS latest_screened_at
            FROM candidate_role_matches m
            LEFT JOIN screening_results r ON r.id = m.screening_result_id
            LEFT JOIN candidate_role_status_events e
              ON e.candidate_id = m.candidate_id
             AND e.role_id = m.role_id
            WHERE {' AND '.join(where)}
            GROUP BY m.latest_rating
            ORDER BY
                CASE m.latest_rating
                    WHEN 'UR' THEN 1
                    WHEN 'SSR' THEN 2
                    WHEN 'SR' THEN 3
                    WHEN 'R' THEN 4
                    WHEN 'N' THEN 5
                    ELSE 6
                END
            """,
            params,
        ).fetchall()

    def get_ai_rating_cohort_summary(
        self,
        *,
        role_id: int | None = None,
        minimum_rating: str | None = None,
        screened_since: str | None = None,
    ) -> dict[str, int | str]:
        connection = self.db.get_connection()
        pair_key = "m.candidate_id || ':' || m.role_id"
        where = [
            "m.screening_result_id IS NOT NULL",
            "m.latest_rating <> ''",
        ]
        params: list[object] = []
        if role_id is not None:
            where.append("m.role_id = ?")
            params.append(role_id)
        if minimum_rating:
            where.append(
                """
                CASE m.latest_rating
                    WHEN 'UR' THEN 5
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 3
                    WHEN 'R' THEN 2
                    WHEN 'N' THEN 1
                    ELSE 0
                END >= ?
                """
            )
            params.append(self._rating_score(minimum_rating))
        if screened_since:
            where.append("COALESCE(r.created_at, m.updated_at) >= ?")
            params.append(screened_since)
        row = connection.execute(
            f"""
            SELECT
                COUNT(DISTINCT {pair_key}) AS screened_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'priority_outreach' THEN {pair_key} END) AS priority_outreach_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'contacted' THEN {pair_key} END) AS contacted_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'replied' THEN {pair_key} END) AS replied_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'interviewing' THEN {pair_key} END) AS interviewing_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'offer' THEN {pair_key} END) AS offer_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'hired' THEN {pair_key} END) AS hired_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'rejected' THEN {pair_key} END) AS rejected_count,
                COUNT(DISTINCT CASE WHEN e.to_status = 'talent_pool' THEN {pair_key} END) AS talent_pool_count,
                MAX(COALESCE(r.created_at, m.updated_at)) AS latest_screened_at
            FROM candidate_role_matches m
            LEFT JOIN screening_results r ON r.id = m.screening_result_id
            LEFT JOIN candidate_role_status_events e
              ON e.candidate_id = m.candidate_id
             AND e.role_id = m.role_id
            WHERE {' AND '.join(where)}
            """,
            params,
        ).fetchone()
        keys = [
            "screened_count",
            "priority_outreach_count",
            "contacted_count",
            "replied_count",
            "interviewing_count",
            "offer_count",
            "hired_count",
            "rejected_count",
            "talent_pool_count",
        ]
        summary: dict[str, int | str] = {key: int(row[key] or 0) for key in keys}
        summary["latest_screened_at"] = str(row["latest_screened_at"] or "")
        return summary

    @staticmethod
    def _rating_score(rating: str) -> int:
        return {
            "UR": 5,
            "SSR": 4,
            "SR": 3,
            "R": 2,
            "N": 1,
        }.get(rating.upper(), 0)

    @staticmethod
    def _optional_int(value: int | str | None) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _last_active_since(cls, days: int | str | None) -> str | None:
        normalized_days = cls._optional_int(days)
        if normalized_days is None or normalized_days <= 0:
            return None
        return (datetime.now() - timedelta(days=normalized_days)).isoformat(timespec="seconds")

    @staticmethod
    def _profile_tag_tokens(value: str) -> list[str]:
        tokens = [
            token.strip()
            for token in re.split(r"[\s,，、|/]+", value or "")
            if token.strip()
        ]
        deduped: list[str] = []
        for token in tokens:
            if token not in deduped:
                deduped.append(token)
        return deduped

    def get_export_rows(
        self,
        mode: str,
        batch_id: int | None = None,
        keyword: str = "",
        job_title: str = "",
        city: str = "",
        years_min: int | str | None = None,
        years_max: int | str | None = None,
        profile_tag: str = "",
        last_active_days: int | str | None = None,
        match_role_id: int | str | None = None,
        minimum_rating: str = "",
        match_status: str = "",
        recruitment_status: str = "",
        latest_reason_code: str = "",
    ) -> list[dict[str, object]]:
        role_id = self._optional_int(match_role_id)
        scoped_batch_id = batch_id if mode in {"batch", "filtered"} else None
        if role_id is not None or minimum_rating or match_status or recruitment_status:
            rows = self.list_candidate_role_matches(
                role_id=role_id,
                match_statuses=[match_status] if match_status else None,
                recruitment_statuses=[recruitment_status] if recruitment_status else None,
                minimum_rating=minimum_rating or None,
                job_title=job_title,
                batch_id=scoped_batch_id,
                city=city,
                years_min=years_min,
                years_max=years_max,
                profile_tag=profile_tag,
                last_active_days=last_active_days,
                latest_reason_code=latest_reason_code,
                query=keyword,
                limit=1000,
            )
            return [dict(row) for row in rows]

        rows = self.list_candidates(
            keyword=keyword,
            job_title=job_title,
            batch_id=scoped_batch_id,
            city=city,
            years_min=years_min,
            years_max=years_max,
            profile_tag=profile_tag,
            last_active_days=last_active_days,
            latest_reason_code=latest_reason_code,
        )
        return [dict(row) for row in rows]

    def _insert_candidate(self, connection, candidate: CandidateRecord) -> int:
        timestamp = now_iso()
        cursor = connection.execute(
            """
            INSERT INTO candidates(
                candidate_key, raw_text_hash, platform_uid, job_title, source_url, capture_time, name,
                active_status, expected_salary, work_experience_text, education_text, tags_text,
                summary_text, raw_card_text, detail_url, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_key,
                candidate.raw_text_hash,
                candidate.platform_uid,
                candidate.job_title,
                candidate.source_url,
                candidate.capture_time,
                candidate.name,
                candidate.active_status,
                candidate.expected_salary,
                candidate.work_experience_text,
                candidate.education_text,
                candidate.tags_text,
                candidate.summary_text,
                candidate.raw_card_text,
                candidate.detail_url,
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid)

    def _update_candidate(self, connection, candidate_id: int, candidate: CandidateRecord) -> None:
        connection.execute(
            """
            UPDATE candidates
            SET raw_text_hash = ?, platform_uid = ?, job_title = ?, source_url = ?, capture_time = ?,
                name = ?, active_status = ?, expected_salary = ?, work_experience_text = ?, education_text = ?,
                tags_text = ?, summary_text = ?, raw_card_text = ?, detail_url = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                candidate.raw_text_hash,
                candidate.platform_uid,
                candidate.job_title,
                candidate.source_url,
                candidate.capture_time,
                candidate.name,
                candidate.active_status,
                candidate.expected_salary,
                candidate.work_experience_text,
                candidate.education_text,
                candidate.tags_text,
                candidate.summary_text,
                candidate.raw_card_text,
                candidate.detail_url,
                now_iso(),
                candidate_id,
            ),
        )

    def _merge_candidate(self, existing, candidate: CandidateRecord) -> CandidateRecord:
        def prefer(new_value: str, old_value: str) -> str:
            return new_value if str(new_value).strip() else str(old_value or "")

        return CandidateRecord(
            id=int(existing["id"]),
            candidate_key=candidate.candidate_key,
            raw_text_hash=prefer(candidate.raw_text_hash, existing["raw_text_hash"]),
            platform_uid=prefer(candidate.platform_uid, existing["platform_uid"]),
            job_title=prefer(candidate.job_title, existing["job_title"]),
            source_url=prefer(candidate.source_url, existing["source_url"]),
            capture_time=prefer(candidate.capture_time, existing["capture_time"]),
            name=prefer(candidate.name, existing["name"]),
            active_status=prefer(candidate.active_status, existing["active_status"]),
            expected_salary=prefer(candidate.expected_salary, existing["expected_salary"]),
            work_experience_text=prefer(candidate.work_experience_text, existing["work_experience_text"]),
            education_text=prefer(candidate.education_text, existing["education_text"]),
            tags_text=prefer(candidate.tags_text, existing["tags_text"]),
            summary_text=prefer(candidate.summary_text, existing["summary_text"]),
            raw_card_text=prefer(candidate.raw_card_text, existing["raw_card_text"]),
            detail_url=prefer(candidate.detail_url, existing["detail_url"]),
            created_at=str(existing["created_at"]),
            updated_at=now_iso(),
        )

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)
