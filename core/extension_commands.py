from __future__ import annotations

import threading
import uuid
from collections import deque
from datetime import datetime, timezone


SUPPORTED_EXTENSION_ACTIONS = frozenset(
    {
        "automation_auto",
        "collect_current",
        "collect_auto",
        "pause_scroll",
        "stop_capture",
    }
)
INTERRUPT_EXTENSION_ACTIONS = frozenset({"pause_scroll", "stop_capture"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ExtensionCommandBroker:
    """Thread-safe in-memory command channel between desktop UI and Chrome extension."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: deque[str] = deque()
        self._commands: dict[str, dict[str, object]] = {}

    def enqueue(self, action: str, recruitment_task_id: int | None) -> dict[str, object]:
        normalized = str(action or "").strip()
        if normalized not in SUPPORTED_EXTENSION_ACTIONS:
            raise ValueError(f"不支持的插件操作：{normalized or '-'}")
        with self._lock:
            if normalized not in INTERRUPT_EXTENSION_ACTIONS and any(
                command["action"] not in INTERRUPT_EXTENSION_ACTIONS
                and command["status"] in {"queued", "running"}
                for command in self._commands.values()
            ):
                raise ValueError("已有插件采集指令正在等待或执行，请先暂停或等待完成。")
            command_id = uuid.uuid4().hex
            command: dict[str, object] = {
                "id": command_id,
                "action": normalized,
                "recruitment_task_id": recruitment_task_id,
                "status": "queued",
                "message": "等待 Chrome 插件领取",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            self._commands[command_id] = command
            self._pending.append(command_id)
        return dict(command)

    def claim_next(self) -> dict[str, object] | None:
        with self._lock:
            while self._pending:
                command_id = self._pending.popleft()
                command = self._commands.get(command_id)
                if command is None or command["status"] != "queued":
                    continue
                command["status"] = "running"
                command["message"] = "Chrome 插件正在执行"
                command["updated_at"] = _now_iso()
                return dict(command)
        return None

    def complete(self, command_id: str, *, ok: bool, message: str) -> dict[str, object]:
        with self._lock:
            command = self._commands.get(str(command_id))
            if command is None:
                raise KeyError(f"插件指令不存在：{command_id}")
            command["status"] = "completed" if ok else "failed"
            command["message"] = str(message or ("执行完成" if ok else "执行失败"))
            command["updated_at"] = _now_iso()
            return dict(command)

    def status(self, command_id: str) -> dict[str, object] | None:
        with self._lock:
            command = self._commands.get(str(command_id))
            return dict(command) if command is not None else None
