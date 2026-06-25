from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from storage.migrations import apply_migrations


class MigrationTest(unittest.TestCase):
    def test_existing_screening_runs_table_gets_origin_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            connection = sqlite3.connect(str(Path(tmp_dir) / "old.db"))
            connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY)")
            connection.execute("INSERT INTO schema_version(version) VALUES (2)")
            connection.execute(
                """
                CREATE TABLE screening_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    source_job_title TEXT,
                    batch_id INTEGER,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_candidates INTEGER NOT NULL DEFAULT 0,
                    completed_candidates INTEGER NOT NULL DEFAULT 0,
                    failed_candidates INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    note TEXT
                )
                """
            )

            apply_migrations(connection)

            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(screening_runs)").fetchall()
            }
            task_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(screening_tasks)").fetchall()
            }
            result_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(screening_results)").fetchall()
            }
            match_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(candidate_role_matches)").fetchall()
            }
            event_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(candidate_role_status_events)"
                ).fetchall()
            }
            profile_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(candidate_profiles)").fetchall()
            }
            version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
            self.assertIn("origin", columns)
            self.assertIn("request_payload_hash", task_columns)
            self.assertIn("route", task_columns)
            self.assertIn("route_reason", task_columns)
            self.assertIn("route_details_json", task_columns)
            self.assertIn("result_source", task_columns)
            self.assertIn("prompt_text", task_columns)
            self.assertIn("candidate_text", task_columns)
            self.assertIn("locked_at", task_columns)
            self.assertIn("locked_by", task_columns)
            self.assertIn("next_attempt_at", task_columns)
            self.assertIn("failure_category", task_columns)
            self.assertIn("confidence", result_columns)
            self.assertIn("evidence_json", result_columns)
            self.assertIn("gap_json", result_columns)
            self.assertIn("risk_json", result_columns)
            self.assertIn("recommended_action", result_columns)
            self.assertIn("candidate_id", match_columns)
            self.assertIn("role_id", match_columns)
            self.assertIn("latest_rating", match_columns)
            self.assertIn("match_status", match_columns)
            self.assertIn("recruitment_status", match_columns)
            self.assertIn("human_decision", match_columns)
            self.assertIn("from_status", event_columns)
            self.assertIn("to_status", event_columns)
            self.assertIn("reason_code", event_columns)
            self.assertIn("city", profile_columns)
            self.assertIn("years_experience", profile_columns)
            self.assertIn("industry_tags_json", profile_columns)
            self.assertIn("skill_tags_json", profile_columns)
            self.assertIn("profile_completeness", profile_columns)
            self.assertEqual(version, 12)
            connection.close()

    def test_existing_screening_results_are_backfilled_as_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            connection = sqlite3.connect(str(Path(tmp_dir) / "old_results.db"))
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY);
                INSERT INTO schema_version(version) VALUES (3);

                CREATE TABLE candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_key TEXT NOT NULL UNIQUE,
                    raw_text_hash TEXT NOT NULL,
                    platform_uid TEXT,
                    job_title TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    capture_time TEXT NOT NULL,
                    name TEXT,
                    active_status TEXT,
                    expected_salary TEXT,
                    work_experience_text TEXT,
                    education_text TEXT,
                    tags_text TEXT,
                    summary_text TEXT,
                    raw_card_text TEXT NOT NULL,
                    detail_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO candidates(
                    candidate_key, raw_text_hash, job_title, source_url, capture_time,
                    name, raw_card_text, created_at, updated_at
                ) VALUES (
                    'platform:legacy', 'hash', 'Sales', 'https://example.com',
                    '2026-01-01T00:00:00', 'Legacy Candidate', 'raw',
                    '2026-01-01T00:00:00', '2026-01-01T00:00:00'
                );

                CREATE TABLE screening_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_title TEXT NOT NULL UNIQUE,
                    jd_text TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    prompt_source TEXT NOT NULL DEFAULT 'generated',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO screening_profiles(
                    job_title, jd_text, prompt_text, created_at, updated_at
                ) VALUES (
                    'Sales', 'SaaS', 'screen', '2026-01-01T00:00:00', '2026-01-01T00:00:00'
                );

                CREATE TABLE screening_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    source_job_title TEXT,
                    batch_id INTEGER,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    origin TEXT NOT NULL DEFAULT 'manual',
                    status TEXT NOT NULL,
                    total_candidates INTEGER NOT NULL DEFAULT 0,
                    completed_candidates INTEGER NOT NULL DEFAULT 0,
                    failed_candidates INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    note TEXT
                );
                INSERT INTO screening_runs(
                    profile_id, source_job_title, provider, model, status,
                    total_candidates, completed_candidates, failed_candidates, started_at
                ) VALUES (
                    1, 'Sales', 'fake', 'fake-model', 'completed',
                    1, 1, 0, '2026-01-01T00:00:00'
                );

                CREATE TABLE screening_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    candidate_id INTEGER NOT NULL,
                    rating TEXT,
                    persona TEXT,
                    status TEXT NOT NULL,
                    raw_response TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, candidate_id)
                );
                INSERT INTO screening_results(
                    run_id, candidate_id, rating, persona, status, raw_response, created_at
                ) VALUES (
                    1, 1, 'SSR', 'Legacy result', 'completed', '{}', '2026-01-01T00:00:01'
                );
                """
            )

            apply_migrations(connection)

            row = connection.execute(
                """
                SELECT
                    role_id,
                    status,
                    route,
                    route_reason,
                    request_payload_hash,
                    result_id,
                    result_source,
                    prompt_text,
                    candidate_text,
                    locked_by,
                    failure_category
                FROM screening_tasks
                """
            ).fetchone()
            match_row = connection.execute(
                """
                SELECT
                    candidate_id,
                    role_id,
                    latest_rating,
                    match_status,
                    recruitment_status,
                    screening_result_id
                FROM candidate_role_matches
                """
            ).fetchone()
            event_row = connection.execute(
                """
                SELECT candidate_id, role_id, from_status, to_status, reason_code
                FROM candidate_role_status_events
                """
            ).fetchone()
            profile_row = connection.execute(
                """
                SELECT candidate_id, name_or_alias, current_title, salary_range, education
                FROM candidate_profiles
                """
            ).fetchone()
            result_row = connection.execute(
                """
                SELECT confidence, evidence_json, gap_json, risk_json, recommended_action
                FROM screening_results
                """
            ).fetchone()
            version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
            self.assertIsNotNone(row)
            self.assertEqual(tuple(row), (
                1,
                "success",
                "pass_to_ai",
                "legacy_screening_result",
                "legacy:1:1",
                1,
                "legacy",
                "",
                "",
                "",
                "",
            ))
            self.assertEqual(tuple(match_row), (1, 1, "SSR", "ai_screened", "screened", 1))
            self.assertEqual(tuple(event_row), (1, 1, "", "screened", "migration_backfill"))
            self.assertEqual(tuple(profile_row), (1, "Legacy Candidate", "Sales", "", ""))
            self.assertEqual(tuple(result_row), ("", "[]", "[]", "[]", ""))
            self.assertEqual(version, 12)
            connection.close()


if __name__ == "__main__":
    unittest.main()
