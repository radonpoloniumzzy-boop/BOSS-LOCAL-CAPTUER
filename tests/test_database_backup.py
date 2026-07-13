from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from storage.db import DatabaseManager


class DatabaseBackupTest(unittest.TestCase):
    def test_existing_database_is_backed_up_before_schema_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "existing.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO schema_version(version) VALUES (12)")
            connection.execute("CREATE TABLE sentinel(value TEXT)")
            connection.execute("INSERT INTO sentinel(value) VALUES ('keep-me')")
            connection.commit()
            connection.close()

            database = DatabaseManager(path)
            database.initialize()

            self.assertIsNotNone(database.last_backup_path)
            assert database.last_backup_path is not None
            self.assertTrue(database.last_backup_path.exists())
            backup = sqlite3.connect(database.last_backup_path)
            try:
                value = backup.execute("SELECT value FROM sentinel").fetchone()[0]
            finally:
                backup.close()
            self.assertEqual(value, "keep-me")


if __name__ == "__main__":
    unittest.main()
