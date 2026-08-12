from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError as exc:
    print("Failed to import PySide6.QtWidgets.")
    print(f"Python executable: {sys.executable}")
    print(f"Python base prefix: {sys.base_prefix}")
    print("")
    print("This project is best run with an official CPython 3.12 installation.")
    print("The current virtual environment appears to inherit from Anaconda,")
    print("and the PySide6 wheel could not load its Qt runtime DLLs.")
    print("")
    print("Recommended fix:")
    print("1. Install official Python 3.12 from python.org.")
    print("2. Recreate the virtual environment with that interpreter.")
    print("3. Reinstall requirements and run `playwright install chromium` again.")
    print("")
    print(f"Original import error: {exc}")
    raise SystemExit(1)

from ui.main_window import MainWindow
from ui.theme import apply_application_theme
from core.app_lock import ApplicationLockError, DatabaseApplicationLock
from core.bootstrap import BootstrapConfigurationError, BootstrapStore
from core.config import DataDirectoryAccessError
from core.utils import get_app_root
from storage.db import DatabaseMissingError


@dataclass(frozen=True)
class DesktopStartupConfiguration:
    data_dir: Path
    require_existing_database: bool


def resolve_desktop_startup(
    project_root: Path, store: BootstrapStore | None = None
) -> DesktopStartupConfiguration:
    configured = (store or BootstrapStore()).load()
    if configured is not None:
        return DesktopStartupConfiguration(
            data_dir=Path(configured.data_dir).resolve(),
            require_existing_database=True,
        )
    return DesktopStartupConfiguration(
        data_dir=project_root / "data",
        require_existing_database=False,
    )


def resolve_desktop_data_dir(project_root: Path, store: BootstrapStore | None = None) -> Path:
    return resolve_desktop_startup(project_root, store).data_dir


def _show_configured_database_recovery_message(title: str, message: str) -> None:
    QMessageBox.critical(None, title, message)


def _show_startup_data_directory_message(*, configured: bool) -> None:
    if configured:
        _show_configured_database_recovery_message(
            "数据目录需要恢复",
            "已配置的数据目录无法访问。\n"
            "请检查 D 盘、移动盘和目录权限。\n"
            "系统不会创建或切换空人才库。\n"
            "恢复目录后重新启动。",
        )
        return
    QMessageBox.critical(
        None,
        "启动失败",
        "本地数据目录当前无法访问。\n"
        "请检查磁盘和目录权限后重新启动。\n"
        "系统不会创建或切换空人才库。",
    )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Boss 本地候选人采集工具")
    apply_application_theme(app)
    try:
        startup = resolve_desktop_startup(get_app_root())
    except BootstrapConfigurationError as exc:
        QMessageBox.critical(None, "启动配置需要恢复", str(exc))
        return 1
    database_path = startup.data_dir / "boss_local_tool.db"
    lock = DatabaseApplicationLock(database_path)
    try:
        lock.acquire()
    except ApplicationLockError as exc:
        QMessageBox.critical(None, "无法启动", str(exc))
        return 1
    try:
        try:
            window = MainWindow(
                data_dir=startup.data_dir,
                require_existing_database=startup.require_existing_database,
            )
        except DatabaseMissingError:
            _show_configured_database_recovery_message(
                "人才库文件不存在",
                f"已配置的人才库文件不存在：{database_path}\n"
                "系统不会自动创建空数据库。\n"
                "请检查 D 盘或移动盘是否已连接，以及数据库文件是否被移动或改名。\n"
                "恢复原数据库文件后再启动。",
            )
            return 1
        except DataDirectoryAccessError:
            _show_startup_data_directory_message(
                configured=startup.require_existing_database
            )
            return 1
        window.show()
        return app.exec()
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
