from __future__ import annotations

from pathlib import Path

from core.app_lock import ApplicationLockError
from web.backend.launcher import PortUnavailableError, run_web_app


def main() -> int:
    try:
        return run_web_app(Path(__file__).resolve().parent)
    except (ApplicationLockError, PortUnavailableError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
