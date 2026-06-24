from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from core.models import CandidateRecord, CaptureBatch, CaptureBatchItem, ScreeningProfile, ScreeningResult
from core.utils import now_iso
from storage.db import DatabaseManager


class CandidateRepository:
    def __init__(self, db: DatabaseManager, logger=None) -> None:
        self.db = db
        self.logger = logger

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
                else:
                    candidate_id = int(existing["id"])
                    merged = self._merge_candidate(existing, candidate)
                    self._update_candidate(connection, candidate_id, merged)

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
    ) -> list[sqlite3.Row]:
        connection = self.db.get_connection()
        params: list[object] = []
        joins = ""
        filters = []

        if batch_id is not None:
            joins += " JOIN capture_batch_items bi ON bi.candidate_id = c.id "
            filters.append("bi.batch_id = ?")
            params.append(batch_id)

        if keyword:
            filters.append(
                "(c.name LIKE ? OR c.expected_salary LIKE ? OR c.work_experience_text LIKE ? OR c.raw_card_text LIKE ?)"
            )
            token = f"%{keyword}%"
            params.extend([token, token, token, token])

        if job_title:
            filters.append("c.job_title = ?")
            params.append(job_title)

        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = f"""
        SELECT
            c.*,
            COUNT(DISTINCT bi2.batch_id) AS batch_count
        FROM candidates c
        LEFT JOIN capture_batch_items bi2 ON bi2.candidate_id = c.id
        {joins}
        {where_sql}
        GROUP BY c.id
        ORDER BY c.updated_at DESC
        """
        return list(connection.execute(query, params).fetchall())

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
        return {"candidate": candidate, "appearances": appearances}

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

    def save_screening_result(self, result: ScreeningResult) -> None:
        connection = self.db.get_connection()
        timestamp = result.created_at or now_iso()
        connection.execute(
            """
            INSERT INTO screening_results(
                run_id, candidate_id, rating, persona, status, raw_response, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, candidate_id) DO UPDATE SET
                rating = excluded.rating,
                persona = excluded.persona,
                status = excluded.status,
                raw_response = excluded.raw_response,
                error = excluded.error,
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
                timestamp,
            ),
        )
        connection.commit()

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

    def get_export_rows(
        self,
        mode: str,
        batch_id: int | None = None,
        keyword: str = "",
        job_title: str = "",
    ) -> list[dict[str, object]]:
        connection = self.db.get_connection()
        if mode == "batch" and batch_id is not None:
            rows = connection.execute(
                """
                SELECT
                    bi.candidate_key,
                    bi.name,
                    bi.active_status,
                    bi.expected_salary,
                    bi.work_experience_text,
                    bi.education_text,
                    bi.tags_text,
                    bi.summary_text,
                    bi.raw_card_text,
                    bi.job_title,
                    bi.source_url,
                    bi.capture_time,
                    bi.detail_url,
                    bi.raw_text_hash
                FROM capture_batch_items bi
                WHERE bi.batch_id = ?
                ORDER BY bi.capture_time DESC
                """,
                (batch_id,),
            ).fetchall()
            return [dict(row) for row in rows]

        rows = self.list_candidates(keyword=keyword, job_title=job_title, batch_id=batch_id)
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
