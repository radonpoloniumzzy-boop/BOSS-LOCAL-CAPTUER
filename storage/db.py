from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from storage.migrations import LATEST_SCHEMA_VERSION, apply_migrations


class DatabaseCorruptError(RuntimeError):
    pass


class DatabaseMissingError(FileNotFoundError):
    pass


class UnsupportedSchemaError(RuntimeError):
    pass


class DatabaseUpgradeError(RuntimeError):
    pass


class DatabaseManager:
    def __init__(self, db_path: Path, logger=None) -> None:
        self.db_path = db_path
        self.logger = logger
        self._existing_only = False
        self._local = threading.local()
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self.last_backup_path: Path | None = None

    def initialize(self) -> None:
        self._existing_only = False
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._open_connection(check_same_thread=True)
        self._initialize_connection(connection)

    def initialize_existing(self) -> None:
        self._existing_only = True
        connection = self._open_connection(check_same_thread=True)
        self._initialize_connection(connection, require_schema=True)

    def _open_connection(self, *, check_same_thread: bool) -> sqlite3.Connection:
        if not self._existing_only:
            return sqlite3.connect(str(self.db_path), check_same_thread=check_same_thread)
        uri = f"{self.db_path.resolve().as_uri()}?mode=rw"
        try:
            return sqlite3.connect(uri, uri=True, check_same_thread=check_same_thread)
        except sqlite3.OperationalError as exc:
            if not self.db_path.is_file():
                raise DatabaseMissingError(self.db_path) from exc
            raise DatabaseCorruptError("无法打开已配置的人才库。") from exc
        except sqlite3.DatabaseError as exc:
            if not self.db_path.is_file():
                raise DatabaseMissingError(self.db_path) from exc
            raise DatabaseCorruptError("无法打开已配置的人才库。") from exc

    def _initialize_connection(
        self, connection: sqlite3.Connection, *, require_schema: bool = False
    ) -> None:
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                raise DatabaseCorruptError("人才库完整性检查失败。")
            try:
                version = self._schema_version(connection)
            except sqlite3.DatabaseError as exc:
                raise DatabaseCorruptError("无法读取人才库结构。") from exc
            if require_schema and version is None:
                raise DatabaseCorruptError("已配置文件不是可识别的人才库。")
            if version is not None and version > LATEST_SCHEMA_VERSION:
                raise UnsupportedSchemaError("人才库版本高于当前程序支持版本。")
            if version is not None and version < LATEST_SCHEMA_VERSION:
                try:
                    self.last_backup_path = self._create_upgrade_backup(connection, LATEST_SCHEMA_VERSION)
                    apply_migrations(connection)
                except DatabaseUpgradeError:
                    raise
                except Exception as exc:
                    connection.rollback()
                    raise DatabaseUpgradeError("人才库升级失败，原数据库未切换。") from exc
            else:
                apply_migrations(connection)
        except sqlite3.DatabaseError as exc:
            raise DatabaseCorruptError("人才库文件损坏或无法读取。") from exc
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
            connection = self._open_connection(check_same_thread=False)
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
        temporary_path = backup_path.with_name(f"{backup_path.name}.tmp-{uuid.uuid4().hex}")
        backup = None
        try:
            backup = sqlite3.connect(str(temporary_path))
            connection.backup(backup)
            backup.close()
            backup = None
            validation = sqlite3.connect(str(temporary_path))
            try:
                quick_check = validation.execute("PRAGMA quick_check").fetchone()
                if quick_check is None or str(quick_check[0]).lower() != "ok":
                    raise DatabaseUpgradeError("升级备份完整性检查失败，已停止升级。")
            finally:
                validation.close()
            temporary_path.replace(backup_path)
            return backup_path
        except Exception as exc:
            original = exc
            if backup is not None:
                try:
                    backup.close()
                except Exception:
                    pass
                backup = None
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(original, DatabaseUpgradeError):
                raise
            raise DatabaseUpgradeError(f"数据库升级前备份失败，已停止升级：{original}") from original
        finally:
            if backup is not None:
                backup.close()

