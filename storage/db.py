from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from storage.migrations import apply_migrations


class DatabaseManager:
    def __init__(self, db_path: Path, logger=None) -> None:
        self.db_path = db_path
        self.logger = logger
        self._local = threading.local()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(connection)
        connection.close()
        if self.logger:
            self.logger.info("Initialized database at %s", self.db_path)

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

