from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from core.version import APP_VERSION
from storage.db import DatabaseManager
from storage.migrations import LATEST_SCHEMA_VERSION


DATABASE_NAME = "boss_local_tool.db"
BOOTSTRAP_DIR_NAME = "RecruitingTalentWorkbench"


class DataDirectoryError(ValueError):
    pass


class BootstrapConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BootstrapSettings:
    data_dir: str
    web_port: int = 17864
    setup_completed: bool = True
    app_version: str = APP_VERSION


class BootstrapStore:
    def __init__(self, path: Path | None = None) -> None:
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        self.path = path or local_app_data / BOOTSTRAP_DIR_NAME / "bootstrap.json"

    def load(self) -> BootstrapSettings | None:
        try:
            exists = self.path.exists()
        except OSError as exc:
            raise BootstrapConfigurationError(self._recovery_message("无法访问配置文件")) from exc
        if not exists:
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise BootstrapConfigurationError(self._recovery_message("无法读取配置文件")) from exc
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BootstrapConfigurationError(self._recovery_message("配置文件不是有效 JSON")) from exc
        if not isinstance(raw, dict):
            raise BootstrapConfigurationError(self._recovery_message("配置内容格式不正确"))
        missing = {"data_dir", "web_port", "setup_completed"} - raw.keys()
        if missing:
            raise BootstrapConfigurationError(
                self._recovery_message(f"配置缺少字段：{', '.join(sorted(missing))}")
            )
        data_dir = raw["data_dir"]
        if not isinstance(data_dir, str) or not data_dir.strip() or not Path(data_dir).is_absolute():
            raise BootstrapConfigurationError(self._recovery_message("data_dir 必须是非空绝对路径"))
        web_port = raw["web_port"]
        if isinstance(web_port, bool) or not isinstance(web_port, int) or not 1024 <= web_port <= 65535:
            raise BootstrapConfigurationError(
                self._recovery_message("web_port 必须是 1024–65535 之间的整数")
            )
        if raw["setup_completed"] is not True:
            raise BootstrapConfigurationError(self._recovery_message("setup_completed 必须明确为 true"))
        return BootstrapSettings(
            data_dir=data_dir.strip(),
            web_port=web_port,
            setup_completed=True,
            app_version=str(raw.get("app_version") or APP_VERSION),
        )

    def _recovery_message(self, reason: str) -> str:
        return (
            f"本地工作台启动配置损坏或不可用：{reason}。\n"
            f"配置文件：{self.path}\n"
            "请检查该文件以及其中的数据目录是否仍指向原有人才库；修复或从备份恢复后再启动。"
        )

    def save(self, settings: BootstrapSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


class BootstrapService:
    def __init__(
        self,
        *,
        project_root: Path,
        store: BootstrapStore | None = None,
        d_drive: Path = Path("D:/"),
        documents_dir: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.store = store or BootstrapStore()
        self.d_drive = d_drive
        self.documents_dir = documents_dir or Path.home() / "Documents"

    @property
    def project_data_dir(self) -> Path:
        return self.project_root / "data"

    def status(self) -> dict[str, object]:
        configured = self.store.load()
        project_database = self.project_data_dir / DATABASE_NAME
        suggested = self._suggested_data_dir(project_database.exists())
        return {
            "setup_required": configured is None,
            "suggested_data_dir": str(suggested),
            "configured_data_dir": configured.data_dir if configured else None,
            "existing_database_detected": project_database.exists(),
        }

    def setup(self, data_dir: str | Path) -> dict[str, object]:
        if self.store.load() is not None:
            raise DataDirectoryError("首次设置已经完成，运行中不能更换数据目录。")
        selected = self.validate_data_dir(data_dir)
        selected.mkdir(parents=True, exist_ok=True)
        database_path = selected / DATABASE_NAME
        DatabaseManager(database_path).initialize()
        settings = BootstrapSettings(data_dir=str(selected))
        self.store.save(settings)
        return {
            "setup_completed": True,
            "data_dir": str(selected),
            "database_path": str(database_path),
        }

    def validate_data_dir(self, raw_path: str | Path) -> Path:
        candidate = Path(str(raw_path).strip()).expanduser()
        if not candidate.is_absolute():
            raise DataDirectoryError("数据目录必须使用绝对路径。")
        candidate = candidate.resolve()
        if candidate == Path(candidate.anchor):
            raise DataDirectoryError("不能把磁盘根目录作为数据目录。")
        if self._is_same_or_within(candidate, self.project_root):
            project_database = self.project_data_dir.resolve() / DATABASE_NAME
            if candidate != self.project_data_dir.resolve() or not project_database.is_file():
                raise DataDirectoryError("不能把项目源码目录作为数据目录。")
        for system_path in self._system_directories():
            if self._is_same_or_within(candidate, system_path):
                raise DataDirectoryError("不能把 Windows 系统目录作为数据目录。")
        if candidate.exists() and not candidate.is_dir():
            raise DataDirectoryError("所选路径不是文件夹。")
        if candidate.exists():
            entries = list(candidate.iterdir())
            if entries and not (candidate / DATABASE_NAME).is_file():
                raise DataDirectoryError("所选目录非空，但不是可识别的工作台数据目录。")
            if (candidate / DATABASE_NAME).is_file():
                self._validate_existing_database(candidate / DATABASE_NAME)
        self._verify_writable(candidate)
        return candidate

    def _suggested_data_dir(self, existing_project_database: bool) -> Path:
        if existing_project_database:
            return self.project_data_dir.resolve()
        if self.d_drive.exists():
            return (self.d_drive / "HR-Workbench-Data").resolve()
        return (self.documents_dir / BOOTSTRAP_DIR_NAME).resolve()

    @staticmethod
    def _is_same_or_within(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def _system_directories() -> list[Path]:
        values = [
            os.environ.get("SystemRoot", "C:/Windows"),
            os.environ.get("ProgramFiles", "C:/Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"),
        ]
        return [Path(value).resolve() for value in values if value]

    @staticmethod
    def _verify_writable(path: Path) -> None:
        probe_parent = path if path.exists() else path.parent
        while not probe_parent.exists() and probe_parent != probe_parent.parent:
            probe_parent = probe_parent.parent
        if not probe_parent.is_dir() or not os.access(probe_parent, os.W_OK):
            raise DataDirectoryError("所选数据目录不可写。")
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write-test"
            probe.write_text("ok", encoding="ascii")
            probe.unlink()
        except OSError as exc:
            raise DataDirectoryError(f"所选数据目录不可写：{exc}") from exc

    @staticmethod
    def _validate_existing_database(database_path: Path) -> None:
        connection = None
        try:
            uri = f"{database_path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                raise DataDirectoryError("现有数据库结构不符合工作台要求。")
            required_tables = {
                "schema_version",
                "candidates",
                "capture_batches",
                "capture_batch_items",
            }
            existing_tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not required_tables.issubset(existing_tables):
                raise DataDirectoryError("现有数据库结构不符合工作台要求。")
            row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            version = int(row[0]) if row is not None else 0
            if version < 1 or version > LATEST_SCHEMA_VERSION:
                raise DataDirectoryError("现有数据库结构版本不受当前程序支持。")
        except (OSError, ValueError, sqlite3.DatabaseError) as exc:
            raise DataDirectoryError("现有数据库结构不符合工作台要求。") from exc
        finally:
            if connection is not None:
                connection.close()
