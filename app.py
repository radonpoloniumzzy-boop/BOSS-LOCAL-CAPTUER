from __future__ import annotations

import sys
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
from core.utils import get_app_root


def resolve_desktop_data_dir(project_root: Path, store: BootstrapStore | None = None) -> Path:
    configured = (store or BootstrapStore()).load()
    if configured is not None:
        return Path(configured.data_dir).resolve()
    return project_root / "data"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Boss 本地候选人采集工具")
    apply_application_theme(app)
    try:
        data_dir = resolve_desktop_data_dir(get_app_root())
    except BootstrapConfigurationError as exc:
        QMessageBox.critical(None, "启动配置需要恢复", str(exc))
        return 1
    database_path = data_dir / "boss_local_tool.db"
    lock = DatabaseApplicationLock(database_path)
    try:
        lock.acquire()
    except ApplicationLockError as exc:
        QMessageBox.critical(None, "无法启动", str(exc))
        return 1
    try:
        window = MainWindow(data_dir=data_dir)
        window.show()
        return app.exec()
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
