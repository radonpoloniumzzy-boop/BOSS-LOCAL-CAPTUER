from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class PairingCode:
    code: str
    expires_at: datetime


class PairingCodeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PluginPairingService:
    def __init__(self) -> None:
        self._codes: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()
        self.last_verified_at = ""

    def create_code(self, *, ttl_seconds: int = 300) -> PairingCode:
        now = datetime.now()
        code = f"{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}"
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._lock:
            self._codes[code] = {"expires_at": expires_at, "used": False}
        return PairingCode(code=code, expires_at=expires_at)

    def consume(self, code: str) -> None:
        normalized = str(code or "").strip().upper()
        with self._lock:
            record = self._codes.get(normalized)
            if record is None:
                raise PairingCodeError("invalid_pairing_code", "连接码无效，请在网页设置中重新生成。")
            if bool(record["used"]):
                raise PairingCodeError("pairing_code_used", "连接码已经使用，请重新生成。")
            if datetime.now() >= record["expires_at"]:
                raise PairingCodeError("pairing_code_expired", "连接码已过期，请重新生成。")
            record["used"] = True
            self.last_verified_at = datetime.now().isoformat(timespec="seconds")

    def mark_verified(self) -> None:
        with self._lock:
            self.last_verified_at = datetime.now().isoformat(timespec="seconds")

    def revoke(self) -> None:
        with self._lock:
            self._codes.clear()
            self.last_verified_at = ""
