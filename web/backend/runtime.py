from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from automation.importer import CardImportService
from automation.parser import CandidateParser
from core.app_lock import ApplicationLockError, DatabaseApplicationLock
from core.bootstrap import BootstrapService, DATABASE_NAME, DataDirectoryError
from core.config import ConfigService
from storage.db import (
    DatabaseCorruptError,
    DatabaseManager,
    DatabaseMissingError,
    DatabaseUpgradeError,
    UnsupportedSchemaError,
)
from storage.repository import CandidateRepository


@dataclass(frozen=True)
class DatabaseFault:
    code: str
    message: str


DATABASE_FAULTS = {
    "configured_database_missing": "已配置的人才库文件不存在，请检查磁盘、数据目录，或从备份恢复。",
    "database_corrupt": "人才库文件损坏或无法读取，请停止操作并从可用备份恢复。",
    "unsupported_schema": "人才库版本高于当前程序支持版本，请升级程序后再试。",
    "database_upgrade_failed": "人才库升级失败，原文件未被切换；请查看本地日志并从备份恢复。",
    "database_in_use": "人才库正在被另一个程序实例使用，请关闭其他实例后重试。",
}


def write_runtime_log(
    log_dir: Path, level: int, message: str, *, exc_info: bool = False
) -> None:
    logger = logging.getLogger(f"boss_local_tool.web_runtime.{uuid.uuid4().hex}")
    logger.propagate = False
    handler: RotatingFileHandler | None = None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "web-runtime.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.log(level, message, exc_info=exc_info)
    finally:
        logger.removeHandler(handler)
        handler.close()


class WebRuntime:
    def __init__(
        self,
        bootstrap: BootstrapService,
        lock_root: Path | None = None,
    ) -> None:
        self.bootstrap = bootstrap
        self.lock_root = lock_root
        self.log_dir = bootstrap.store.path.parent / "logs"
        self.data_dir: Path | None = None
        self.config_service: ConfigService | None = None
        self.import_service: CardImportService | None = None
        self.database: DatabaseManager | None = None
        self.repository: CandidateRepository | None = None
        self.lock: DatabaseApplicationLock | None = None
        self.database_fault: DatabaseFault | None = None
        self._state_lock = threading.RLock()
        configured = bootstrap.store.load()
        if configured is not None:
            self._connect_configured(Path(configured.data_dir))
        elif (bootstrap.project_data_dir / DATABASE_NAME).is_file():
            self.reserve(bootstrap.project_data_dir)

    def _connect_configured(self, data_dir: Path) -> None:
        database_path = data_dir / DATABASE_NAME
        if not database_path.is_file():
            self.database_fault = self._fault("configured_database_missing")
            write_runtime_log(
                self.log_dir,
                logging.ERROR,
                f"Configured database is missing at {database_path}",
            )
            return
        try:
            self.connect(data_dir, existing_only=True)
        except DatabaseMissingError:
            self.database_fault = self._fault("configured_database_missing")
            write_runtime_log(
                self.log_dir,
                logging.ERROR,
                "Configured database disappeared before it could be opened",
                exc_info=True,
            )
        except ApplicationLockError:
            self.database_fault = self._fault("database_in_use")
            write_runtime_log(
                self.log_dir,
                logging.ERROR,
                "Configured database lock acquisition failed",
                exc_info=True,
            )
        except DatabaseCorruptError:
            self.database_fault = self._fault("database_corrupt")
            write_runtime_log(
                self.log_dir,
                logging.ERROR,
                "Configured database integrity check failed",
                exc_info=True,
            )
        except UnsupportedSchemaError:
            self.database_fault = self._fault("unsupported_schema")
            write_runtime_log(
                self.log_dir,
                logging.ERROR,
                "Configured database schema is unsupported",
                exc_info=True,
            )
        except DatabaseUpgradeError:
            self.database_fault = self._fault("database_upgrade_failed")
            write_runtime_log(
                self.log_dir,
                logging.ERROR,
                "Configured database upgrade failed",
                exc_info=True,
            )
        except Exception:
            self.database_fault = self._fault("database_upgrade_failed")
            write_runtime_log(
                self.log_dir,
                logging.ERROR,
                "Configured database initialization failed",
                exc_info=True,
            )

    @staticmethod
    def _fault(code: str) -> DatabaseFault:
        return DatabaseFault(code=code, message=DATABASE_FAULTS[code])

    def reserve(self, data_dir: Path) -> None:
        with self._state_lock:
            lock = DatabaseApplicationLock(data_dir / DATABASE_NAME, lock_root=self.lock_root)
            lock.acquire()
            self.lock = lock

    def connect(self, data_dir: Path, *, existing_only: bool) -> None:
        with self._state_lock:
            database_path = data_dir / DATABASE_NAME
            lock = DatabaseApplicationLock(database_path, lock_root=self.lock_root)
            lock.acquire()
            database = DatabaseManager(database_path)
            try:
                if existing_only:
                    database.initialize_existing()
                else:
                    database.initialize()
                self.lock = lock
                self.data_dir = data_dir
                self.database = database
                self.repository = CandidateRepository(database)
                self.config_service = ConfigService(data_dir=data_dir)
                self.import_service = CardImportService(
                    self.repository,
                    CandidateParser(),
                )
                self.database_fault = None
            except Exception:
                database.close_all_connections()
                lock.release()
                raise

    def setup(self, data_dir: str) -> dict[str, object]:
        with self._state_lock:
            if self.bootstrap.store.load() is not None:
                raise DataDirectoryError("首次设置已经完成，运行中不能更换数据目录。")
            selected = self.bootstrap.validate_data_dir(data_dir)
            selected_database = (selected / DATABASE_NAME).resolve()
            if self.lock is not None and self.lock.database_path != selected_database:
                self.close()
            if self.lock is None:
                self.reserve(selected)
            try:
                result = self.bootstrap.setup(selected)
                self.database = DatabaseManager(selected_database)
                self.repository = CandidateRepository(self.database)
                self.data_dir = selected
                self.config_service = ConfigService(data_dir=selected)
                self.import_service = CardImportService(
                    self.repository,
                    CandidateParser(),
                )
                self.database_fault = None
                return result
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        with self._state_lock:
            if self.database is not None:
                self.database.close_all_connections()
            if self.lock is not None:
                self.lock.release()
            self.database = None
            self.repository = None
            self.data_dir = None
            self.config_service = None
            self.import_service = None
            self.lock = None
