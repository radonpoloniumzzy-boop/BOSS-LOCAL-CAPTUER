from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


class LocalApiServer:
    def __init__(
        self,
        host: str,
        port: int,
        import_service,
        logger=None,
        on_import: Callable[[dict[str, object]], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        get_automation_status: Callable[[], dict[str, object]] | None = None,
        start_automation: Callable[[dict[str, object]], dict[str, object]] | None = None,
        on_automation_progress: Callable[[dict[str, object]], None] | None = None,
        get_extension_config: Callable[[], dict[str, object]] | None = None,
        claim_favorite_task: Callable[[dict[str, object]], dict[str, object] | None] | None = None,
        report_favorite_result: Callable[[dict[str, object]], dict[str, object]] | None = None,
        retry_favorite_task: Callable[[dict[str, object]], dict[str, object]] | None = None,
        reconcile_favorite_batch: Callable[[dict[str, object]], dict[str, object]] | None = None,
        claim_favorite_verification: Callable[[dict[str, object]], dict[str, object] | None] | None = None,
        report_favorite_verification: Callable[[dict[str, object]], dict[str, object]] | None = None,
        get_favorite_batch_status: Callable[[dict[str, object]], dict[str, object]] | None = None,
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
        self.on_automation_progress = on_automation_progress
        self.get_extension_config = get_extension_config
        self.claim_favorite_task = claim_favorite_task
        self.report_favorite_result = report_favorite_result
        self.retry_favorite_task = retry_favorite_task
        self.reconcile_favorite_batch = reconcile_favorite_batch
        self.claim_favorite_verification = claim_favorite_verification
        self.report_favorite_verification = report_favorite_verification
        self.get_favorite_batch_status = get_favorite_batch_status
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
                self._send_json(404, {"error": "Not found"})

            def do_POST(self) -> None:
                if self.path not in {
                    "/api/import/cards",
                    "/api/automation/start",
                    "/api/automation/progress",
                    "/api/favorites/claim",
                    "/api/favorites/result",
                    "/api/favorites/retry",
                    "/api/favorites/reconcile",
                    "/api/favorites/verification/claim",
                    "/api/favorites/verification/result",
                    "/api/favorites/status",
                }:
                    self._send_json(404, {"error": "Not found"})
                    return
                if not self._is_authorized():
                    self._send_json(401, {"ok": False, "error": "Unauthorized"})
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                    if content_length > parent.max_body_bytes:
                        self._send_json(413, {"ok": False, "error": "Request body is too large"})
                        return
                    body = self.rfile.read(content_length).decode("utf-8")
                    payload = json.loads(body or "{}")
                    if self.path == "/api/favorites/claim":
                        if parent.claim_favorite_task is None:
                            self._send_json(503, {"ok": False, "error": "Native Favorite is unavailable"})
                            return
                        result = parent.claim_favorite_task(payload)
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    if self.path == "/api/favorites/result":
                        if parent.report_favorite_result is None:
                            self._send_json(503, {"ok": False, "error": "Native Favorite is unavailable"})
                            return
                        result = parent.report_favorite_result(payload)
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    if self.path == "/api/favorites/retry":
                        if parent.retry_favorite_task is None:
                            self._send_json(503, {"ok": False, "error": "Native Favorite is unavailable"})
                            return
                        result = parent.retry_favorite_task(payload)
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    if self.path == "/api/favorites/reconcile":
                        if parent.reconcile_favorite_batch is None:
                            self._send_json(503, {"ok": False, "error": "Native Favorite is unavailable"})
                            return
                        result = parent.reconcile_favorite_batch(payload)
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    if self.path == "/api/favorites/verification/claim":
                        if parent.claim_favorite_verification is None:
                            self._send_json(503, {"ok": False, "error": "Native Favorite verification is unavailable"})
                            return
                        result = parent.claim_favorite_verification(payload)
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    if self.path == "/api/favorites/verification/result":
                        if parent.report_favorite_verification is None:
                            self._send_json(503, {"ok": False, "error": "Native Favorite verification is unavailable"})
                            return
                        result = parent.report_favorite_verification(payload)
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    if self.path == "/api/favorites/status":
                        if parent.get_favorite_batch_status is None:
                            self._send_json(503, {"ok": False, "error": "Native Favorite status is unavailable"})
                            return
                        result = parent.get_favorite_batch_status(payload)
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    if self.path == "/api/automation/start":
                        if parent.start_automation is None:
                            self._send_json(503, {"ok": False, "error": "Automation is unavailable"})
                            return
                        result = parent.start_automation(payload)
                        self._send_json(200, {"ok": True, "result": result})
                        return
                    if self.path == "/api/automation/progress":
                        if parent.on_automation_progress is not None:
                            parent.on_automation_progress(payload)
                        self._send_json(200, {"ok": True})
                        return
                    result = parent.import_service.import_cards(payload)
                    if parent.on_import:
                        parent.on_import(result)
                    self._send_json(200, {"ok": True, "result": result})
                except Exception as exc:
                    message = str(exc)
                    parent._log("exception", "Local API import failed: %s", exc)
                    if self.path == "/api/import/cards" and parent.on_error:
                        parent.on_error(message)
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

            def _is_authorized(self) -> bool:
                if not parent.auth_token:
                    return False
                supplied = self.headers.get("X-Boss-Local-Token", "")
                return secrets.compare_digest(str(supplied), parent.auth_token)

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
