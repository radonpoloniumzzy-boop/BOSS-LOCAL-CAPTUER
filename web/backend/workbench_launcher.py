from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable


RECOVERY_MESSAGES = {
    "port_in_use": "本地端口 17864 已被其他程序占用。请关闭占用程序后重新启动网页工作台。",
    "configured_database_missing": "已配置的人才库文件不存在。请检查 D 盘、移动盘或数据库文件位置，恢复后重新启动。",
    "database_corrupt": "人才库文件损坏或无法读取。请停止操作并从可用备份恢复。",
    "database_in_use": "人才库正在被其他实例使用。请关闭桌面端或另一个网页工作台后重试。",
    "unsupported_schema": "人才库版本高于当前程序支持版本，请升级程序后再试。",
    "database_upgrade_failed": "人才库升级失败。原数据库未被切换，请查看本地日志并从备份恢复。",
    "service_start_failed": "本地服务未能启动。请确认项目运行环境完整后重试。",
}


class LaunchFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(RECOVERY_MESSAGES.get(code, RECOVERY_MESSAGES["service_start_failed"]))


def _request_json(url: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError):
            return None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _port_in_use(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.2)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()


class WorkbenchLauncher:
    def __init__(
        self,
        *,
        service_probe: Callable[[str], dict[str, object] | None],
        status_probe: Callable[[str], dict[str, object] | None],
        port_in_use: Callable[[int], bool],
        process_start: Callable[[], object],
        browser_open: Callable[[str], object],
        wait: Callable[[float], None],
        progress: Callable[[str], None] | None = None,
        attempts: int = 50,
    ) -> None:
        self.service_probe = service_probe
        self.status_probe = status_probe
        self.port_in_use = port_in_use
        self.process_start = process_start
        self.browser_open = browser_open
        self.wait = wait
        self.progress = progress or (lambda _message: None)
        self.attempts = attempts
        self.url = "http://127.0.0.1:17864/"

    @staticmethod
    def _is_workbench_service(payload: dict[str, object] | None) -> bool:
        return bool(
            payload
            and payload.get("status") == "ok"
            and payload.get("service") == "recruiting-talent-workbench"
        )

    def launch(self) -> str:
        self.progress("正在检查运行环境")
        if self._is_workbench_service(self.service_probe(f"{self.url}api/health")):
            status = self.status_probe(f"{self.url}api/app/status")
            if status is None:
                raise LaunchFailure("service_start_failed")
            fault = status.get("error") if isinstance(status, dict) else None
            code = str(fault.get("code") or "") if isinstance(fault, dict) else ""
            if code and code != "database_not_ready":
                raise LaunchFailure(code)
            self.progress("网页工作台已经运行，正在打开浏览器")
            self.browser_open(self.url)
            return "already_running"
        if self.port_in_use(17864):
            raise LaunchFailure("port_in_use")
        self.progress("正在读取人才库配置")
        self.progress("正在检查数据库")
        self.progress("正在启动本地服务")
        process = self.process_start()
        self.progress("正在等待网页工作台")
        for _ in range(self.attempts):
            if getattr(process, "poll", lambda: None)() is not None:
                raise LaunchFailure("service_start_failed")
            if self._is_workbench_service(self.service_probe(f"{self.url}api/health")):
                status = self.status_probe(f"{self.url}api/app/status")
                if status is None:
                    self.wait(0.2)
                    continue
                fault = status.get("error") if isinstance(status, dict) else None
                code = str(fault.get("code") or "") if isinstance(fault, dict) else ""
                if code and code != "database_not_ready":
                    getattr(process, "terminate", lambda: None)()
                    raise LaunchFailure(code)
                self.progress("启动成功，正在打开浏览器")
                self.browser_open(self.url)
                return "started"
            self.wait(0.2)
        getattr(process, "terminate", lambda: None)()
        raise LaunchFailure("service_start_failed")


def create_default_launcher(project_root: Path, progress: Callable[[str], None]) -> WorkbenchLauncher:
    pythonw = project_root / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
        raise LaunchFailure("service_start_failed")

    def start_process():
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            [str(pythonw), str(project_root / "web_app.py")],
            cwd=project_root,
            creationflags=creation_flags,
        )

    return WorkbenchLauncher(
        service_probe=_request_json,
        status_probe=_request_json,
        port_in_use=_port_in_use,
        process_start=start_process,
        browser_open=lambda url: webbrowser.open(url, new=2),
        wait=time.sleep,
        progress=progress,
    )
