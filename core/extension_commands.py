from __future__ import annotations

import threading
import time
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

    def __init__(self, *, clock=time.monotonic, lease_seconds: float = 60.0) -> None:
        self._lock = threading.RLock()
        self._clock = clock
        self._lease_seconds = max(float(lease_seconds), 5.0)
        self._pending: deque[str] = deque()
        self._commands: dict[str, dict[str, object]] = {}
        self._lease_deadlines: dict[str, float] = {}

    def enqueue(
        self,
        action: str,
        recruitment_task_id: int | None,
        *,
        platform: str,
        source_url: str,
    ) -> dict[str, object]:
        normalized = str(action or "").strip()
        if normalized not in SUPPORTED_EXTENSION_ACTIONS:
            raise ValueError(f"不支持的插件操作：{normalized or '-'}")
        normalized_platform = str(platform or "").strip().lower()
        if normalized_platform not in {"boss", "liepin"}:
            raise ValueError(f"不支持的招聘平台：{normalized_platform or '-'}")
        normalized_source_url = str(source_url or "").strip()
        if not normalized_source_url:
            raise ValueError("插件操作缺少招聘任务来源页面。")
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
                "platform": normalized_platform,
                "source_url": normalized_source_url,
                "status": "queued",
                "attempt": 0,
                "claim_token": "",
                "message": "等待 Chrome 插件领取",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            self._commands[command_id] = command
            self._pending.append(command_id)
        return dict(command)

    def claim_next(self) -> dict[str, object] | None:
        with self._lock:
            now = self._clock()
            for command_id, deadline in list(self._lease_deadlines.items()):
                command = self._commands.get(command_id)
                if command is not None and command["status"] == "running" and deadline <= now:
                    command["status"] = "queued"
                    command["message"] = "插件执行中断，等待重新领取"
                    command["updated_at"] = _now_iso()
                    command["claim_token"] = ""
                    self._pending.append(command_id)
                    self._lease_deadlines.pop(command_id, None)
            while self._pending:
                command_id = self._pending.popleft()
                command = self._commands.get(command_id)
                if command is None or command["status"] != "queued":
                    continue
                command["status"] = "running"
                command["message"] = "Chrome 插件正在执行"
                command["attempt"] = int(command.get("attempt") or 0) + 1
                command["claim_token"] = uuid.uuid4().hex
                command["updated_at"] = _now_iso()
                self._lease_deadlines[command_id] = self._clock() + self._lease_seconds
                return dict(command)
        return None

    def heartbeat(self, command_id: str, claim_token: str = "") -> dict[str, object]:
        with self._lock:
            command = self._commands.get(str(command_id))
            if command is None:
                raise KeyError(f"插件指令不存在：{command_id}")
            if command["status"] != "running" or command.get("claim_token") != claim_token:
                raise ValueError("插件指令租约已经失效。")
            self._lease_deadlines[str(command_id)] = self._clock() + self._lease_seconds
            command["updated_at"] = _now_iso()
            return dict(command)

    def complete(
        self,
        command_id: str,
        *,
        claim_token: str = "",
        ok: bool,
        message: str,
    ) -> dict[str, object]:
        with self._lock:
            command = self._commands.get(str(command_id))
            if command is None:
                raise KeyError(f"插件指令不存在：{command_id}")
            if command["status"] in {"completed", "failed"} and command.get("claim_token") == claim_token:
                return dict(command)
            if command["status"] != "running" or command.get("claim_token") != claim_token:
                raise ValueError("插件指令租约已经失效。")
            command["status"] = "completed" if ok else "failed"
            command["message"] = str(message or ("执行完成" if ok else "执行失败"))
            command["updated_at"] = _now_iso()
            self._lease_deadlines.pop(str(command_id), None)
            return dict(command)

    def status(self, command_id: str) -> dict[str, object] | None:
        with self._lock:
            command = self._commands.get(str(command_id))
            return dict(command) if command is not None else None
