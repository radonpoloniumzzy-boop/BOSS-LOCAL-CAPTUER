from __future__ import annotations

import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import quote, urlsplit


class LocalApiServer:
    def __init__(
        self,
        host: str,
        port: int,
        import_service,
        logger=None,
        on_import: Callable[[dict[str, object]], None] | None = None,
        on_error: Callable[[dict[str, object]], None] | None = None,
        get_automation_status: Callable[[], dict[str, object]] | None = None,
        start_automation: Callable[[dict[str, object]], dict[str, object]] | None = None,
        get_extension_config: Callable[[], dict[str, object]] | None = None,
        extension_command_broker=None,
        download_batch_csv: Callable[[int], tuple[str, bytes]] | None = None,
        auth_token: str = "",
        max_body_bytes: int = 25_000_000,
    ) -> None:
        self.host = host
        self.port = port
        self.import_service = import_service
        self.logger = logger
        self.on_import = on_import
        self.on_error = on_error
        self.get_automation_status = get_automation_status
        self.start_automation = start_automation
        self.get_extension_config = get_extension_config
        self.extension_command_broker = extension_command_broker
        self.download_batch_csv = download_batch_csv
        self.auth_token = str(auth_token or "")
        self.max_body_bytes = max_body_bytes
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self._server is not None:
            return

        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_OPTIONS(self) -> None:
                self._send_json(204, {})

            def do_GET(self) -> None:
                request_path = urlsplit(self.path).path
                batch_download_match = re.fullmatch(
                    r"/api/export/batches/([1-9][0-9]*)\.csv",
                    request_path,
                )
                if batch_download_match:
                    if not self._is_authorized():
                        self._send_json(401, {"ok": False, "error": "Unauthorized"})
                        return
                    if parent.download_batch_csv is None:
                        self._send_json(503, {"ok": False, "error": "Batch export is unavailable"})
                        return
                    try:
                        filename, content = parent.download_batch_csv(
                            int(batch_download_match.group(1))
                        )
                    except ValueError as exc:
                        self._send_json(404, {"ok": False, "error": str(exc)})
                        return
                    except Exception as exc:
                        parent._log("exception", "Local API batch export failed: %s", exc)
                        self._send_json(400, {"ok": False, "error": str(exc)})
                        return
                    self._send_csv(filename, content)
                    return
                if self.path == "/":
                    self._send_json(
                        200,
                        {
                            "status": "ok",
                            "service": "Boss Local Capture API",
                            "endpoint": parent.endpoint,
                            "health": "/health",
                            "connection_check": "/api/connection/check",
                        },
                    )
                    return
                if self.path == "/health":
                    self._send_json(200, {"status": "ok", "endpoint": parent.endpoint})
                    return
                if self.path == "/api/connection/check":
                    if not self._is_authorized():
                        self._send_json(401, {"ok": False, "error": "Unauthorized"})
                        return
                    self._send_json(
                        200,
                        {"ok": True, "status": "connected", "auth": "ok", "endpoint": parent.endpoint},
                    )
                    return
                if self.path == "/api/automation/status":
                    if not self._is_authorized():
                        self._send_json(401, {"ok": False, "error": "Unauthorized"})
                        return
                    if parent.get_automation_status is None:
                        self._send_json(503, {"ok": False, "error": "Automation is unavailable"})
                        return
                    try:
                        self._send_json(200, {"ok": True, "result": parent.get_automation_status()})
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return
                if self.path == "/api/extension/config":
                    if not self._is_authorized():
                        self._send_json(401, {"ok": False, "error": "Unauthorized"})
                        return
                    result = parent.get_extension_config() if parent.get_extension_config else {}
                    self._send_json(200, {"ok": True, "result": result})
                    return
                if self.path == "/api/extension/commands/next":
                    if not self._is_authorized():
                        self._send_json(401, {"ok": False, "error": "Unauthorized"})
                        return
                    if parent.extension_command_broker is None:
                        self._send_json(503, {"ok": False, "error": "Extension control is unavailable"})
                        return
                    self._send_json(
                        200,
                        {"ok": True, "result": parent.extension_command_broker.claim_next()},
                    )
                    return
                self._send_json(404, {"error": "Not found"})

            def do_POST(self) -> None:
                payload: dict[str, object] = {}
                is_command_completion = (
                    self.path.startswith("/api/extension/commands/")
                    and self.path.endswith("/complete")
                )
                is_command_heartbeat = (
                    self.path.startswith("/api/extension/commands/")
                    and self.path.endswith("/heartbeat")
                )
                if (
                    self.path not in {"/api/import/cards", "/api/automation/start"}
                    and not is_command_completion
                    and not is_command_heartbeat
                ):
                    self._send_json(404, {"error": "Not found"})
                    return
                if not self._is_authorized():
                    self._discard_request_body()
                    self._send_json(401, {"ok": False, "error": "Unauthorized"})
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                    if content_length > parent.max_body_bytes:
                        self._send_json(413, {"ok": False, "error": "Request body is too large"})
                        return
                    body = self.rfile.read(content_length).decode("utf-8")
                    payload = json.loads(body or "{}")
                    if is_command_completion or is_command_heartbeat:
                        if parent.extension_command_broker is None:
                            self._send_json(503, {"ok": False, "error": "Extension control is unavailable"})
                            return
                        command_id = self.path.removeprefix("/api/extension/commands/")
                        command_id = command_id.removesuffix(
                            "/complete" if is_command_completion else "/heartbeat"
                        )
                        if is_command_completion:
                            result = parent.extension_command_broker.complete(
                                command_id,
                                claim_token=str(payload.get("claim_token") or ""),
                                ok=bool(payload.get("ok")),
                                message=str(payload.get("message") or ""),
                            )
                        else:
                            result = parent.extension_command_broker.heartbeat(
                                command_id,
                                claim_token=str(payload.get("claim_token") or ""),
                            )
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    if self.path == "/api/automation/start":
                        if parent.start_automation is None:
                            self._send_json(503, {"ok": False, "error": "Automation is unavailable"})
                            return
                        result = parent.start_automation(payload)
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    result = parent.import_service.import_cards(payload)
                    if parent.on_import:
                        parent.on_import(result)
                    self._send_json(200, {"ok": True, "result": result})
                except Exception as exc:
                    message = str(exc)
                    parent._log("exception", "Local API import failed: %s", exc)
                    if self.path == "/api/import/cards" and parent.on_error:
                        parent.on_error(
                            {
                                "message": message,
                                "recruitment_task_id": (
                                    payload.get("recruitment_task_id")
                                    if isinstance(payload, dict)
                                    else None
                                ),
                            }
                        )
                    self._send_json(400, {"ok": False, "error": message})

            def log_message(self, format: str, *args) -> None:
                parent._log("debug", "Local API: " + format, *args)

            def _send_json(self, status_code: int, payload: dict[str, object]) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Boss-Local-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.end_headers()
                if status_code != 204:
                    self.wfile.write(data)

            def _send_csv(self, filename: str, content: bytes) -> None:
                safe_filename = str(filename).replace("\r", "").replace("\n", "")
                ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_filename).strip("_.")
                ascii_fallback = ascii_stem or "batch_export.csv"
                disposition = (
                    f'attachment; filename="{ascii_fallback}"; '
                    f"filename*=UTF-8''{quote(safe_filename)}"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", disposition)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Boss-Local-Token")
                self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.end_headers()
                self.wfile.write(content)

            def _is_authorized(self) -> bool:
                if not parent.auth_token:
                    return False
                supplied = self.headers.get("X-Boss-Local-Token", "")
                return secrets.compare_digest(str(supplied), parent.auth_token)

            def _discard_request_body(self) -> None:
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return
                if not 0 < content_length <= min(parent.max_body_bytes, 64_000):
                    return
                previous_timeout = self.connection.gettimeout()
                try:
                    self.connection.settimeout(0.25)
                    self.rfile.read(content_length)
                except OSError:
                    pass
                finally:
                    self.connection.settimeout(previous_timeout)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, name="boss-local-api", daemon=True)
        self._thread.start()
        self._log("info", "Local API server started at %s", self.endpoint)

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self._log("info", "Local API server stopped")

    def restart(self, port: int) -> None:
        if port == self.port and self._server is not None:
            return
        self.stop()
        self.port = port
        self.start()

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)
