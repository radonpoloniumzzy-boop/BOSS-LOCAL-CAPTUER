from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from core.bootstrap import BootstrapConfigurationError, BootstrapStore


REQUIRED_CAPABILITIES = frozenset({"phase2c_pairing", "batch_markdown_export"})
STEP_READ_CONFIG = "read_config"
STEP_CHECK_RUNTIME = "check_runtime"
STEP_CHECK_FRONTEND = "check_frontend"
STEP_CHECK_PORT = "check_port"
STEP_CONNECT_DATABASE = "connect_database"
STEP_CONFIRM_DATABASE = "confirm_database"
STEP_OPEN_BROWSER = "open_browser"
STEP_LABELS = {
    STEP_READ_CONFIG: "正在读取本机配置",
    STEP_CHECK_RUNTIME: "正在检查运行环境",
    STEP_CHECK_FRONTEND: "正在检查网页资源",
    STEP_CHECK_PORT: "正在检查端口和已有服务",
    STEP_CONNECT_DATABASE: "正在连接人才库",
    STEP_CONFIRM_DATABASE: "正在确认数据库状态",
    STEP_OPEN_BROWSER: "正在打开浏览器",
}


class _FrontendAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"src", "href"} and value:
                path = urlsplit(value).path
                if path.startswith("/assets/") or path.startswith("assets/"):
                    self.references.append(path.lstrip("/"))


RECOVERY_MESSAGES = {
    "port_in_use": "本地端口 {port} 已被其他程序占用。请关闭占用程序后重新启动网页工作台。",
    "stale_service": "检测到旧版网页工作台仍在运行，请关闭旧实例后重新启动。",
    "frontend_missing": "网页工作台前端资源不完整，请重新安装完整版本后再启动。",
    "bootstrap_invalid": "网页工作台启动配置损坏或无法读取，请检查 bootstrap.json 后重新启动。",
    "configured_database_missing": "已配置的人才库文件不存在。请检查 D 盘、移动盘或数据库文件位置，恢复后重新启动。",
    "database_corrupt": "人才库文件损坏或无法读取。请停止操作并从可用备份恢复。",
    "database_in_use": "桌面端正在使用人才库。请关闭桌面端或另一个网页工作台后重试。",
    "unsupported_schema": "人才库版本高于当前程序支持版本，请升级程序后再试。",
    "database_upgrade_failed": "人才库升级失败。原数据库未被切换，请查看本地日志并从备份恢复。",
    "service_start_failed": "本地服务未能启动。请确认项目运行环境完整后重试。",
}

RECOVERY_GUIDES = {
    "port_in_use": "恢复说明：请确认 127.0.0.1 对应端口没有被其他程序占用，关闭占用程序后点击“重新检查”。",
    "stale_service": "恢复说明：当前端口上仍有旧版网页工作台。请先关闭旧实例，再重新检查。",
    "frontend_missing": "恢复说明：请确认 web/frontend/dist 下存在 index.html 和 assets 产物，再重新启动。",
    "bootstrap_invalid": "恢复说明：请检查本机启动配置和数据目录是否仍然指向原人才库，修复后重新检查。",
    "configured_database_missing": "恢复说明：请检查已配置数据目录中的人才库文件是否被移动、改名或丢失，恢复原文件后再启动。",
    "database_corrupt": "恢复说明：请停止写入操作，并从可用备份恢复人才库后再重试。",
    "database_in_use": "恢复说明：请先关闭桌面端，再点击“重新检查”。网页端和桌面端不能同时占用同一人才库。",
    "unsupported_schema": "恢复说明：请升级到支持当前人才库版本的程序后再重新启动。",
    "database_upgrade_failed": "恢复说明：请查看本机启动日志，确认升级失败原因后从备份恢复。",
    "service_start_failed": "恢复说明：请检查 Python 环境、前端资源和本机日志，再点击“重新检查”。",
}


class LaunchFailure(RuntimeError):
    def __init__(self, code: str, *, port: int = 17864, step: str | None = None) -> None:
        self.code = code
        self.step = step
        self.recovery = RECOVERY_GUIDES.get(code, RECOVERY_GUIDES["service_start_failed"])
        template = RECOVERY_MESSAGES.get(code, RECOVERY_MESSAGES["service_start_failed"])
        super().__init__(template.format(port=port))


class LaunchCancelled(RuntimeError):
    def __init__(self, *, step: str | None = None) -> None:
        self.step = step
        super().__init__("启动已取消")


def progress_event(step: str, state: str, detail: str | None = None) -> dict[str, str]:
    return {
        "step": step,
        "state": state,
        "detail": detail or STEP_LABELS[step],
    }


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
        progress: Callable[[dict[str, str]], None] | None = None,
        attempts: int = 50,
        port: int = 17864,
        frontend_ready: Callable[[], bool] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> None:
        self.service_probe = service_probe
        self.status_probe = status_probe
        self.port_in_use = port_in_use
        self.process_start = process_start
        self.browser_open = browser_open
        self.wait = wait
        self.progress = progress or (lambda _event: None)
        self.attempts = attempts
        self.port = int(port)
        self.url = f"http://127.0.0.1:{self.port}/"
        self.frontend_ready = frontend_ready or (lambda: True)
        self.cancel_requested = cancel_requested or (lambda: False)
        self._started_process: object | None = None
        self._browser_open_committed = False
        self._on_browser_open_committed: Callable[[], None] | None = None

    def _emit(self, step: str, state: str, detail: str | None = None) -> None:
        self.progress(progress_event(step, state, detail))

    @staticmethod
    def _service_kind(payload: dict[str, object] | None) -> str:
        if not payload or payload.get("status") != "ok":
            return "none"
        if payload.get("service") != "recruiting-talent-workbench":
            return "other"
        capabilities = payload.get("capabilities")
        available = {str(value) for value in capabilities} if isinstance(capabilities, list) else set()
        return "current" if REQUIRED_CAPABILITIES.issubset(available) else "stale"

    @staticmethod
    def _stop_process(process: object) -> None:
        try:
            getattr(process, "terminate", lambda: None)()
        except (OSError, subprocess.SubprocessError):
            return
        try:
            getattr(process, "wait", lambda timeout=None: None)(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                getattr(process, "kill", lambda: None)()
            except (OSError, subprocess.SubprocessError):
                return
            try:
                getattr(process, "wait", lambda timeout=None: None)(timeout=3)
            except (OSError, subprocess.SubprocessError):
                pass
        except (OSError, subprocess.SubprocessError):
            pass

    @staticmethod
    def _reap_exited_process(process: object) -> None:
        try:
            getattr(process, "wait", lambda timeout=None: None)(timeout=0)
        except (OSError, subprocess.SubprocessError):
            pass

    def _cancel_if_requested(self, *, step: str) -> None:
        if self._browser_open_committed:
            return
        if not self.cancel_requested():
            return
        if self._started_process is not None:
            self._stop_process(self._started_process)
            self._started_process = None
        raise LaunchCancelled(step=step)

    @staticmethod
    def _database_result(status: dict[str, object] | None) -> tuple[str, str | None]:
        if status is None:
            return ("unavailable", None)
        fault = status.get("error") if isinstance(status, dict) else None
        code = str(fault.get("code") or "") if isinstance(fault, dict) else ""
        if code:
            return ("not_ready", code) if code == "database_not_ready" else ("error", code)
        if status.get("status") == "ready" and status.get("database_ready") is True:
            return ("ready", None)
        if status.get("database_ready") is False or status.get("status") == "database_not_ready":
            return ("not_ready", "database_not_ready")
        return ("unavailable", None)

    def _open_browser(self) -> None:
        self._cancel_if_requested(step=STEP_OPEN_BROWSER)
        self._browser_open_committed = True
        if self._on_browser_open_committed is not None:
            self._on_browser_open_committed()
        self._emit(STEP_OPEN_BROWSER, "running", "正在提交打开浏览器")
        opened = self.browser_open(self.url)
        if opened is False:
            raise LaunchFailure("service_start_failed", port=self.port, step=STEP_OPEN_BROWSER)
        self._emit(STEP_OPEN_BROWSER, "completed", "浏览器已打开网页工作台")

    def launch(self) -> str:
        self._cancel_if_requested(step=STEP_CHECK_PORT)
        self._emit(STEP_CHECK_PORT, "running")
        service_kind = self._service_kind(self.service_probe(f"{self.url}api/health"))
        if service_kind == "stale":
            raise LaunchFailure("stale_service", port=self.port, step=STEP_CHECK_PORT)
        if service_kind == "current":
            self._emit(STEP_CHECK_PORT, "completed", "网页工作台已经运行")
            self._cancel_if_requested(step=STEP_CONFIRM_DATABASE)
            self._emit(STEP_CONNECT_DATABASE, "running", "本地服务可访问，正在确认人才库状态")
            self._emit(STEP_CONFIRM_DATABASE, "running")
            status = self.status_probe(f"{self.url}api/app/status")
            result, code = self._database_result(status)
            if result == "unavailable":
                raise LaunchFailure("service_start_failed", port=self.port, step=STEP_CONFIRM_DATABASE)
            if result == "error" and code is not None:
                raise LaunchFailure(code, port=self.port, step=STEP_CONFIRM_DATABASE)
            if result == "not_ready":
                self._emit(STEP_CONNECT_DATABASE, "completed", "本地服务可访问，尚未配置人才库，将进入首次设置")
                self._emit(STEP_CONFIRM_DATABASE, "completed", "人才库状态已确认，将进入首次设置")
            else:
                self._emit(STEP_CONNECT_DATABASE, "completed", "人才库已连接")
                self._emit(STEP_CONFIRM_DATABASE, "completed", "人才库状态已确认")
            self._open_browser()
            return "already_running"

        self._cancel_if_requested(step=STEP_CHECK_FRONTEND)
        self._emit(STEP_CHECK_FRONTEND, "running")
        if not self.frontend_ready():
            raise LaunchFailure("frontend_missing", port=self.port, step=STEP_CHECK_FRONTEND)
        self._emit(STEP_CHECK_FRONTEND, "completed", "网页资源检查通过")
        if self.port_in_use(self.port):
            raise LaunchFailure("port_in_use", port=self.port, step=STEP_CHECK_PORT)
        self._emit(STEP_CHECK_PORT, "completed", "端口和已有服务检查完成")

        self._cancel_if_requested(step=STEP_CONNECT_DATABASE)
        process = self.process_start()
        self._started_process = process
        self._emit(STEP_CONNECT_DATABASE, "running", "本地服务已启动，正在确认人才库状态")
        confirm_started = False
        for _ in range(self.attempts):
            self._cancel_if_requested(step=STEP_CONNECT_DATABASE if not confirm_started else STEP_CONFIRM_DATABASE)
            if getattr(process, "poll", lambda: None)() is not None:
                self._reap_exited_process(process)
                self._started_process = None
                raise LaunchFailure("service_start_failed", port=self.port, step=STEP_CONNECT_DATABASE)
            service_kind = self._service_kind(self.service_probe(f"{self.url}api/health"))
            if service_kind == "stale":
                self._stop_process(process)
                self._started_process = None
                raise LaunchFailure("stale_service", port=self.port, step=STEP_CHECK_PORT)
            if service_kind == "current":
                if not confirm_started:
                    self._emit(STEP_CONFIRM_DATABASE, "running")
                    confirm_started = True
                status = self.status_probe(f"{self.url}api/app/status")
                result, code = self._database_result(status)
                if result == "unavailable":
                    self.wait(0.2)
                    continue
                if result == "error" and code is not None:
                    self._stop_process(process)
                    self._started_process = None
                    raise LaunchFailure(code, port=self.port, step=STEP_CONFIRM_DATABASE)
                if result == "not_ready":
                    self._emit(STEP_CONNECT_DATABASE, "completed", "本地服务可访问，尚未配置人才库，将进入首次设置")
                    self._emit(STEP_CONFIRM_DATABASE, "completed", "人才库状态已确认，将进入首次设置")
                else:
                    self._emit(STEP_CONNECT_DATABASE, "completed", "人才库已连接")
                    self._emit(STEP_CONFIRM_DATABASE, "completed", "人才库状态已确认")
                self._open_browser()
                return "started"
            self.wait(0.2)
        self._stop_process(process)
        self._started_process = None
        raise LaunchFailure(
            "service_start_failed",
            port=self.port,
            step=STEP_CONFIRM_DATABASE if confirm_started else STEP_CONNECT_DATABASE,
        )


def _frontend_assets_ready(project_root: Path) -> bool:
    dist = project_root / "web" / "frontend" / "dist"
    index = dist / "index.html"
    try:
        parser = _FrontendAssetParser()
        parser.feed(index.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return False
    referenced = [dist / path for path in parser.references]
    return bool(
        referenced
        and any(path.suffix == ".js" for path in referenced)
        and any(path.suffix == ".css" for path in referenced)
        and all(path.is_file() for path in referenced)
    )


def create_default_launcher(
    project_root: Path,
    progress: Callable[[dict[str, str]], None],
    *,
    bootstrap_store: BootstrapStore | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> WorkbenchLauncher:
    cancel = cancel_requested or (lambda: False)

    def cancel_if_requested(step: str) -> None:
        if cancel():
            raise LaunchCancelled(step=step)

    cancel_if_requested(STEP_READ_CONFIG)
    progress(progress_event(STEP_READ_CONFIG, "running"))
    cancel_if_requested(STEP_READ_CONFIG)
    try:
        configured = (bootstrap_store or BootstrapStore()).load()
    except BootstrapConfigurationError as exc:
        raise LaunchFailure("bootstrap_invalid", step=STEP_READ_CONFIG) from exc
    port = configured.web_port if configured else 17864
    cancel_if_requested(STEP_READ_CONFIG)
    progress(progress_event(STEP_READ_CONFIG, "completed", "本机配置读取完成"))

    cancel_if_requested(STEP_CHECK_RUNTIME)
    progress(progress_event(STEP_CHECK_RUNTIME, "running"))
    cancel_if_requested(STEP_CHECK_RUNTIME)
    pythonw = project_root / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
        raise LaunchFailure("service_start_failed", step=STEP_CHECK_RUNTIME)
    cancel_if_requested(STEP_CHECK_RUNTIME)
    progress(progress_event(STEP_CHECK_RUNTIME, "completed", "运行环境检查完成"))

    def start_process():
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            [str(pythonw), str(project_root / "web_app.py")],
            cwd=project_root,
            creationflags=creation_flags,
        )

    cancel_if_requested(STEP_CHECK_RUNTIME)
    return WorkbenchLauncher(
        service_probe=_request_json,
        status_probe=_request_json,
        port_in_use=_port_in_use,
        process_start=start_process,
        browser_open=lambda url: webbrowser.open(url, new=2),
        wait=time.sleep,
        progress=progress,
        port=port,
        frontend_ready=lambda: _frontend_assets_ready(project_root),
        cancel_requested=cancel_requested,
    )
