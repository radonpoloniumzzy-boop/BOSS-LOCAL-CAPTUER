from __future__ import annotations

import socket
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from core.bootstrap import BootstrapService, BootstrapStore
from web.backend.app import create_web_app


class PortUnavailableError(RuntimeError):
    pass


def uvicorn_options(port: int) -> dict[str, object]:
    return {"host": "127.0.0.1", "port": int(port), "log_level": "info"}


def ensure_port_available(port: int) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", int(port)))
    except OSError as exc:
        raise PortUnavailableError(
            f"本地网页端口 {port} 已被占用，请关闭占用该端口的程序后重试。"
        ) from exc
    finally:
        probe.close()


def _open_when_ready(url: str) -> None:
    health_url = f"{url}/api/health"
    for _ in range(50):
        try:
            with urllib.request.urlopen(health_url, timeout=0.3) as response:
                if response.status == 200:
                    webbrowser.open(url, new=2)
                    return
        except OSError:
            time.sleep(0.1)


def run_web_app(project_root: Path) -> int:
    store = BootstrapStore()
    configured = store.load()
    port = configured.web_port if configured else 17864
    ensure_port_available(port)
    bootstrap = BootstrapService(project_root=project_root, store=store)
    app = create_web_app(bootstrap)
    url = f"http://127.0.0.1:{port}"
    opener = threading.Thread(target=_open_when_ready, args=(url,), daemon=True)
    opener.start()
    try:
        uvicorn.run(app, **uvicorn_options(port))
        return 0
    finally:
        app.state.runtime.close()
