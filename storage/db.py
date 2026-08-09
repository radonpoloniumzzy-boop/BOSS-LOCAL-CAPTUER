from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from storage.migrations import LATEST_SCHEMA_VERSION, apply_migrations


class DatabaseManager:
    def __init__(self, db_path: Path, logger=None) -> None:
        self.db_path = db_path
        self.logger = logger
        self._local = threading.local()
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self.last_backup_path: Path | None = None

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path))
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            version = self._schema_version(connection)
            if version is not None and version < LATEST_SCHEMA_VERSION:
                self.last_backup_path = self._create_upgrade_backup(connection, LATEST_SCHEMA_VERSION)
            apply_migrations(connection)
        finally:
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
            connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._local.connection = connection
            with self._connections_lock:
                self._connections.add(connection)
        return connection

    def close_thread_connection(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            with self._connections_lock:
                self._connections.discard(connection)
            self._local.connection = None

    def close_all_connections(self) -> None:
        with self._connections_lock:
            connections = list(self._connections)
            self._connections.clear()
        for connection in connections:
            connection.close()
        self._local.connection = None

    def _create_upgrade_backup(
        self, connection: sqlite3.Connection, target_version: int
    ) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = self.db_path.with_name(
            f"{self.db_path.stem}.before_v{target_version}_{stamp}{self.db_path.suffix}.bak"
        )
        backup = None
        try:
            backup = sqlite3.connect(str(backup_path))
            connection.backup(backup)
            return backup_path
        except Exception as exc:
            if backup_path.exists():
                backup_path.unlink(missing_ok=True)
            raise RuntimeError(f"数据库升级前备份失败，已停止升级：{exc}") from exc
        finally:
            if backup is not None:
                backup.close()

