from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.app_lock import DatabaseApplicationLock


lock = DatabaseApplicationLock(Path(sys.argv[1]), lock_root=Path(sys.argv[2]))
lock.acquire()
print("locked", flush=True)
time.sleep(30)
