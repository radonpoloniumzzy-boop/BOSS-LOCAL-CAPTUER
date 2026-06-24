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
            version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
            self.assertIn("origin", columns)
            self.assertEqual(version, 3)
            connection.close()


if __name__ == "__main__":
    unittest.main()
