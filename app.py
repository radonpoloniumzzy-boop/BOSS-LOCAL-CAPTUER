from __future__ import annotations

import sys

try:
    from PySide6.QtWidgets import QApplication
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Boss 本地候选人采集工具")
    apply_application_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
