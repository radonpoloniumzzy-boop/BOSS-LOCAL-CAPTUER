from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from storage.migrations import apply_migrations


class DatabaseManager:
    def __init__(self, db_path: Path, logger=None) -> None:
        self.db_path = db_path
        self.logger = logger
        self._local = threading.local()
        self.last_backup_path: Path | None = None

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        version = self._schema_version(connection)
        if version is not None and version < 13:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.db_path.with_name(
                f"{self.db_path.stem}.before_v13_{stamp}{self.db_path.suffix}.bak"
            )
            backup = sqlite3.connect(str(backup_path))
            try:
                connection.backup(backup)
            finally:
                backup.close()
            self.last_backup_path = backup_path
        apply_migrations(connection)
        connection.close()
        if self.logger:
            self.logger.info("Initialized database at %s", self.db_path)

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int | None:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
        ).fetchone()
        if table is None:
            return None
        row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        return int(row[0]) if row is not None else None

    def get_connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(str(self.db_path))
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._local.connection = connection
        return connection

    def close_thread_connection(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

