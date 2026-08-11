from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from launch_web_workbench import LaunchWindow

from core.bootstrap import BootstrapService, BootstrapSettings, BootstrapStore
from core.config import ConfigService
from web.backend.app import WEB_CAPABILITIES, create_web_app
from web.backend.pairing import PairingCodeError, PluginPairingService
from web.backend.workbench_launcher import (
    LaunchCancelled,
    LaunchFailure,
    STEP_CHECK_FRONTEND,
    STEP_CHECK_PORT,
    STEP_CHECK_RUNTIME,
    STEP_CONFIRM_DATABASE,
    STEP_CONNECT_DATABASE,
    STEP_OPEN_BROWSER,
    STEP_READ_CONFIG,
    StartupCancellationGate,
    WorkbenchLauncher,
    _frontend_assets_ready,
    _request_json,
    create_default_launcher,
)


class Phase2CWebApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = BootstrapStore(self.root / "local" / "bootstrap.json")
        self.bootstrap = BootstrapService(
            project_root=self.project,
            store=self.store,
            d_drive=self.root / "missing-drive",
            documents_dir=self.root / "Documents",
        )
        self.data_dir = self.root / "data"
        self.bootstrap.setup(self.data_dir)
        self.frontend_dist = Path(__file__).resolve().parents[1] / "web" / "frontend" / "dist"
        self.app = create_web_app(
            self.bootstrap,
            lock_root=self.root / "locks",
            frontend_dist=self.frontend_dist,
        )
        self.client = TestClient(self.app, base_url="http://127.0.0.1:17864")
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    @property
    def same_origin(self) -> dict[str, str]:
        return {"Origin": "http://127.0.0.1:17864"}

    @property
    def extension_origin(self) -> dict[str, str]:
        return {"Origin": "chrome-extension://phase2c-test"}

    def test_pairing_code_is_one_time_and_returns_remembered_connection(self) -> None:
        created = self.client.post("/api/plugin-connection/pairing-code", headers=self.same_origin)
        self.assertEqual(created.status_code, 200, created.text)
        code = created.json()["pairing_code"]
        self.assertNotIn("token", created.text.lower())

        paired = self.client.post(
            "/api/plugin/pair",
            json={"pairing_code": code},
            headers=self.extension_origin,
        )
        self.assertEqual(paired.status_code, 200, paired.text)
        self.assertEqual(paired.json()["api_base"], "http://127.0.0.1:17864")
        token = paired.json()["api_token"]
        self.assertTrue(token)

        reused = self.client.post(
            "/api/plugin/pair",
            json={"pairing_code": code},
            headers=self.extension_origin,
        )
        self.assertEqual(reused.status_code, 410)
        self.assertEqual(reused.json()["error"]["code"], "pairing_code_used")

        verified = self.client.get(
            "/api/plugin/connection/check",
            headers={**self.extension_origin, "X-Boss-Local-Token": token},
        )
        self.assertEqual(verified.status_code, 200)
        self.assertNotIn(token, verified.text)

    def test_health_exposes_phase2c_capabilities(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(set(WEB_CAPABILITIES).issubset(set(health.json()["capabilities"])))

    def test_pairing_code_serializes_configured_port_without_token(self) -> None:
        configured = self.store.load()
        self.store.save(BootstrapSettings(data_dir=configured.data_dir, web_port=19064))
        response = self.client.post(
            "/api/plugin-connection/pairing-code",
            headers={"Origin": "http://127.0.0.1:19064", "Host": "127.0.0.1:19064"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(
            payload["pairing_uri"],
            "boss-local://web-pair?apiBase=http%3A%2F%2F127.0.0.1%3A19064&pairingCode="
            + payload["pairing_code"],
        )
        self.assertNotIn("token", payload["pairing_uri"].lower())

    def test_tracked_production_frontend_opens_without_node_modules(self) -> None:
        self.assertTrue(_frontend_assets_ready(Path(__file__).resolve().parents[1]))
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        asset_paths = re.findall(r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"', root.text)
        self.assertGreaterEqual(len(asset_paths), 2)
        for asset_path in asset_paths:
            with self.subTest(asset_path=asset_path):
                asset = self.client.get(asset_path)
                self.assertEqual(asset.status_code, 200)
                self.assertTrue(asset.content)

    def test_new_pairing_code_immediately_invalidates_previous_code(self) -> None:
        first = self.client.post("/api/plugin-connection/pairing-code", headers=self.same_origin).json()
        second = self.client.post("/api/plugin-connection/pairing-code", headers=self.same_origin).json()
        rejected = self.client.post(
            "/api/plugin/pair",
            json={"pairing_code": first["pairing_code"]},
            headers=self.extension_origin,
        )
        self.assertEqual(rejected.status_code, 400)
        accepted = self.client.post(
            "/api/plugin/pair",
            json={"pairing_code": second["pairing_code"]},
            headers=self.extension_origin,
        )
        self.assertEqual(accepted.status_code, 200)

    def test_concurrent_pairing_code_consumption_succeeds_once(self) -> None:
        pairing = PluginPairingService()
        code = pairing.create_code().code
        barrier = threading.Barrier(3)
        outcomes: list[str] = []

        def consume() -> None:
            barrier.wait()
            try:
                pairing.consume(code)
                outcomes.append("success")
            except PairingCodeError as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=consume) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["success", "pairing_code_used"])

    def test_pairing_and_verification_state_wait_for_durable_config_write(self) -> None:
        runtime = self.app.state.runtime
        code = runtime.pairing.create_code().code
        with patch.object(runtime.config_service, "update", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                runtime.pair_plugin(code)
        self.assertEqual(runtime.pairing.last_verified_at, "")
        token, verified_at = runtime.pair_plugin(code)
        self.assertTrue(token)
        self.assertEqual(runtime.pairing.last_verified_at, verified_at)

        runtime.pairing.restore_last_verified("previous-verification")
        with patch.object(runtime.config_service, "update", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                runtime.verify_plugin_connection(token)
        self.assertEqual(runtime.pairing.last_verified_at, "previous-verification")

    def test_last_plugin_verification_survives_service_restart(self) -> None:
        created = self.client.post("/api/plugin-connection/pairing-code", headers=self.same_origin)
        paired = self.client.post(
            "/api/plugin/pair",
            json={"pairing_code": created.json()["pairing_code"]},
            headers=self.extension_origin,
        )
        token = paired.json()["api_token"]
        self.client.get(
            "/api/plugin/connection/check",
            headers={**self.extension_origin, "X-Boss-Local-Token": token},
        )
        saved = ConfigService(data_dir=self.data_dir).load().web_plugin_last_verified_at
        self.assertTrue(saved)

        self.client.__exit__(None, None, None)
        self.app = create_web_app(self.bootstrap, lock_root=self.root / "locks")
        self.client = TestClient(self.app, base_url="http://127.0.0.1:17864")
        self.client.__enter__()
        status = self.client.get("/api/plugin-connection/status").json()
        self.assertTrue(status["connected"])
        self.assertEqual(status["last_verified_at"], saved)

    def test_pairing_code_expiry_and_wrong_code_have_stable_errors(self) -> None:
        created = self.app.state.runtime.pairing.create_code(ttl_seconds=-1)
        expired = self.client.post(
            "/api/plugin/pair",
            json={"pairing_code": created.code},
            headers=self.extension_origin,
        )
        self.assertEqual(expired.status_code, 410)
        self.assertEqual(expired.json()["error"]["code"], "pairing_code_expired")

        wrong = self.client.post(
            "/api/plugin/pair",
            json={"pairing_code": "WRONG-CODE"},
            headers=self.extension_origin,
        )
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json()["error"]["code"], "invalid_pairing_code")

    def test_revoke_rotates_credential_without_exposing_it(self) -> None:
        old_token = ConfigService(data_dir=self.data_dir).load().local_api_token
        revoked = self.client.post("/api/plugin-connection/revoke", headers=self.same_origin)
        self.assertEqual(revoked.status_code, 200)
        self.assertNotIn(old_token, revoked.text)
        rejected = self.client.get(
            "/api/plugin/connection/check",
            headers={**self.extension_origin, "X-Boss-Local-Token": old_token},
        )
        self.assertEqual(rejected.status_code, 401)

    def test_check_and_pair_cannot_restore_token_after_concurrent_revoke(self) -> None:
        runtime = self.app.state.runtime

        def race(*operations) -> None:
            barrier = threading.Barrier(len(operations) + 1)
            threads = []
            for operation in operations:
                def run(current=operation) -> None:
                    barrier.wait()
                    try:
                        current()
                    except (PairingCodeError, PermissionError):
                        pass

                threads.append(threading.Thread(target=run))
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()

        old_token = ConfigService(data_dir=self.data_dir).load().local_api_token
        race(lambda: runtime.verify_plugin_connection(old_token), runtime.revoke_plugin_connection)
        after_check_race = ConfigService(data_dir=self.data_dir).load().local_api_token
        self.assertNotEqual(after_check_race, old_token)
        rejected = self.client.get(
            "/api/plugin/connection/check",
            headers={**self.extension_origin, "X-Boss-Local-Token": old_token},
        )
        self.assertEqual(rejected.status_code, 401)

        code = runtime.pairing.create_code().code
        before_pair_race = ConfigService(data_dir=self.data_dir).load().local_api_token
        race(lambda: runtime.pair_plugin(code), runtime.revoke_plugin_connection)
        after_pair_race = ConfigService(data_dir=self.data_dir).load().local_api_token
        self.assertNotEqual(after_pair_race, before_pair_race)
        rejected_again = self.client.get(
            "/api/plugin/connection/check",
            headers={**self.extension_origin, "X-Boss-Local-Token": before_pair_race},
        )
        self.assertEqual(rejected_again.status_code, 401)

    def test_extension_origin_is_limited_to_plugin_endpoints(self) -> None:
        blocked = self.client.post(
            "/api/plugin-connection/pairing-code",
            headers=self.extension_origin,
        )
        self.assertEqual(blocked.status_code, 403)
        outside = self.client.post(
            "/api/plugin/pair",
            json={"pairing_code": "x"},
            headers={"Origin": "https://example.com"},
        )
        self.assertEqual(outside.status_code, 403)

    def _intake(
        self,
        key: str,
        name: str,
        raw: str,
        *,
        source_candidate_id: str | None = None,
    ) -> dict[str, object]:
        token = ConfigService(data_dir=self.data_dir).load().local_api_token
        response = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "source_job_title": "证券交易员",
                "idempotency_key": key,
                "candidates": [
                    {
                        "source_candidate_id": source_candidate_id or key,
                        "name": name,
                        "raw_card_text": raw,
                    }
                ],
            },
            headers={**self.extension_origin, "X-Boss-Local-Token": token},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_batches_are_newest_first_and_markdown_uses_immutable_snapshot(self) -> None:
        first = self._intake("first", "Alice", "original snapshot")
        second = self._intake("second", "Bob", "newer snapshot")
        page = self.client.get("/api/capture-batches?page=1&page_size=20").json()
        self.assertEqual([row["id"] for row in page["rows"][:2]], [second["batch_id"], first["batch_id"]])

        token = ConfigService(data_dir=self.data_dir).load().local_api_token
        exported = self.client.get(
            f"/api/capture-batches/{first['batch_id']}/export.md",
            headers={**self.extension_origin, "X-Boss-Local-Token": token},
        )
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("original snapshot", exported.text)
        self.assertIn("filename*=UTF-8''boss-", exported.headers["content-disposition"])
        self.assertIn("text/markdown", exported.headers["content-type"])

        self._intake(
            "update",
            "Alice changed",
            "changed current profile",
            source_candidate_id="first",
        )
        repeated = self.client.get(
            f"/api/capture-batches/{first['batch_id']}/export.md",
            headers={**self.extension_origin, "X-Boss-Local-Token": token},
        )
        self.assertEqual(repeated.text, exported.text)
        self.assertNotIn("changed current profile", repeated.text)

        missing = self.client.get(
            "/api/capture-batches/999999/export.md",
            headers={**self.extension_origin, "X-Boss-Local-Token": token},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "batch_not_found")

    def test_today_batch_summary_counts_beyond_the_first_page(self) -> None:
        for index in range(25):
            self._intake(f"summary-{index}", f"Candidate {index}", f"snapshot {index}")
        page = self.client.get("/api/capture-batches?page=1&page_size=20").json()
        self.assertEqual(len(page["rows"]), 20)
        self.assertEqual(page["today_summary"], {"batch_count": 25, "received": 25, "added": 25})

        oldest_id = page["rows"][-1]["id"] - 5
        direct = self.client.get(f"/api/capture-batches/{oldest_id}")
        self.assertEqual(direct.status_code, 200)
        self.assertEqual(direct.json()["id"], oldest_id)

    def test_state_change_without_origin_is_rejected(self) -> None:
        response = self.client.post("/api/plugin-connection/pairing-code")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "same_origin_required")


class WorkbenchLauncherBehaviorTest(unittest.TestCase):
    class FakeStringVar:
        def __init__(self, value: str = "") -> None:
            self.value = value

        def set(self, value: str) -> None:
            self.value = value

        def get(self) -> str:
            return self.value

    class FakeWidget:
        def __init__(self, master=None, **kwargs) -> None:
            self.master = master
            self.options = dict(kwargs)
            self.textvariable = kwargs.get("textvariable")
            self.command = kwargs.get("command")

        def pack(self, *args, **kwargs) -> None:
            return None

        def configure(self, **kwargs) -> None:
            self.options.update(kwargs)
            if "command" in kwargs:
                self.command = kwargs["command"]

        def __getitem__(self, key: str):
            return self.options[key]

    class FakeText(FakeWidget):
        def __init__(self, master=None, **kwargs) -> None:
            super().__init__(master, **kwargs)
            self.value = ""

        def insert(self, _index: str, text: str) -> None:
            self.value += text

        def delete(self, _start: str, _end: str) -> None:
            self.value = ""

        def see(self, _index: str) -> None:
            return None

    class FakeRoot:
        def __init__(self) -> None:
            self.queue: list[callable] = []
            self.destroyed = False

        def title(self, _value: str) -> None:
            return None

        def geometry(self, _value: str) -> None:
            return None

        def resizable(self, _x: bool, _y: bool) -> None:
            return None

        def configure(self, **_kwargs) -> None:
            return None

        def protocol(self, _name: str, _callback) -> None:
            return None

        def after(self, _ms: int, callback) -> None:
            self.queue.append(callback)

        def update(self) -> None:
            callbacks = list(self.queue)
            self.queue.clear()
            for callback in callbacks:
                callback()

        def destroy(self) -> None:
            self.destroyed = True

        def withdraw(self) -> None:
            return None

    @staticmethod
    def current_health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "recruiting-talent-workbench",
            "capabilities": WEB_CAPABILITIES,
        }

    def build_fake_launch_window(self, launcher_factory):
        root = self.FakeRoot()
        patches = [
            patch("launch_web_workbench.tk.Frame", self.FakeWidget),
            patch("launch_web_workbench.tk.Label", self.FakeWidget),
            patch("launch_web_workbench.tk.Text", self.FakeText),
            patch("launch_web_workbench.tk.Button", self.FakeWidget),
            patch("launch_web_workbench.tk.StringVar", self.FakeStringVar),
        ]
        for current in patches:
            current.start()
        self.addCleanup(lambda: [current.stop() for current in reversed(patches)])
        return LaunchWindow(Path.cwd(), launcher_factory=launcher_factory, root=root), root

    def test_http_503_database_fault_body_remains_available_to_launcher(self) -> None:
        class FaultHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b'{"error":{"code":"database_corrupt"}}'
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), FaultHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            payload = _request_json(f"http://127.0.0.1:{server.server_port}/api/app/status")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(payload, {"error": {"code": "database_corrupt"}})

    def test_running_service_is_opened_without_starting_second_process(self) -> None:
        opened: list[str] = []
        started: list[bool] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: self.current_health(),
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: True,
            process_start=lambda: started.append(True),
            browser_open=opened.append,
            wait=lambda _seconds: None,
        )
        self.assertEqual(launcher.launch(), "already_running")
        self.assertEqual(started, [])
        self.assertEqual(opened, ["http://127.0.0.1:17864/"])

    def test_running_service_with_database_fault_is_not_opened(self) -> None:
        opened: list[str] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: self.current_health(),
            status_probe=lambda _url: {"error": {"code": "database_corrupt"}},
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=opened.append,
            wait=lambda _seconds: None,
        )
        with self.assertRaises(LaunchFailure) as caught:
            launcher.launch()
        self.assertEqual(caught.exception.code, "database_corrupt")
        self.assertEqual(opened, [])

    def test_stopped_service_is_started_checked_and_opened(self) -> None:
        health_calls = 0
        opened: list[str] = []

        class Process:
            def poll(self):
                return None

        def health(_url):
            nonlocal health_calls
            health_calls += 1
            if health_calls == 1:
                return None
            return self.current_health()

        launcher = WorkbenchLauncher(
            service_probe=health,
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: False,
            process_start=Process,
            browser_open=opened.append,
            wait=lambda _seconds: None,
        )
        self.assertEqual(launcher.launch(), "started")
        self.assertEqual(opened, ["http://127.0.0.1:17864/"])

    def test_unknown_port_owner_has_specific_recovery_message(self) -> None:
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: None,
            status_probe=lambda _url: None,
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=lambda _url: None,
            wait=lambda _seconds: None,
        )
        with self.assertRaises(LaunchFailure) as caught:
            launcher.launch()
        self.assertEqual(caught.exception.code, "port_in_use")
        self.assertIn("17864", str(caught.exception))

    def test_different_service_on_port_is_not_treated_as_workbench(self) -> None:
        opened: list[str] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: {"status": "ok", "service": "another-program"},
            status_probe=lambda _url: None,
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=opened.append,
            wait=lambda _seconds: None,
        )
        with self.assertRaises(LaunchFailure) as caught:
            launcher.launch()
        self.assertEqual(caught.exception.code, "port_in_use")
        self.assertEqual(opened, [])

    def test_same_service_without_phase2c_capabilities_is_stale(self) -> None:
        started: list[bool] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: {
                "status": "ok",
                "service": "recruiting-talent-workbench",
                "capabilities": ["older_pairing"],
            },
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: True,
            process_start=lambda: started.append(True),
            browser_open=lambda _url: None,
            wait=lambda _seconds: None,
        )
        with self.assertRaises(LaunchFailure) as caught:
            launcher.launch()
        self.assertEqual(caught.exception.code, "stale_service")
        self.assertEqual(str(caught.exception), "检测到旧版网页工作台仍在运行，请关闭旧实例后重新启动。")
        self.assertEqual(started, [])

    def test_nondefault_bootstrap_port_drives_all_launcher_urls(self) -> None:
        health_urls: list[str] = []
        status_urls: list[str] = []
        checked_ports: list[int] = []
        opened: list[str] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda url: health_urls.append(url) or self.current_health(),
            status_probe=lambda url: status_urls.append(url) or {"status": "ready", "database_ready": True},
            port_in_use=lambda port: checked_ports.append(port) or False,
            process_start=lambda: None,
            browser_open=opened.append,
            wait=lambda _seconds: None,
            port=19064,
        )
        self.assertEqual(launcher.launch(), "already_running")
        self.assertEqual(health_urls, ["http://127.0.0.1:19064/api/health"])
        self.assertEqual(status_urls, ["http://127.0.0.1:19064/api/app/status"])
        self.assertEqual(checked_ports, [])
        self.assertEqual(opened, ["http://127.0.0.1:19064/"])

    def test_default_launcher_reads_nondefault_port_from_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
            pythonw.parent.mkdir(parents=True)
            pythonw.write_bytes(b"")
            assets = root / "web" / "frontend" / "dist" / "assets"
            assets.mkdir(parents=True)
            (assets.parent / "index.html").write_text(
                '<link rel="stylesheet" href="/assets/app.css"><script src="/assets/app.js"></script>',
                encoding="utf-8",
            )
            (assets / "app.js").write_text("", encoding="utf-8")
            (assets / "app.css").write_text("", encoding="utf-8")
            store = BootstrapStore(root / "bootstrap.json")
            store.save(BootstrapSettings(data_dir=str(root / "data"), web_port=19064))
            launcher = create_default_launcher(root, lambda _message: None, bootstrap_store=store)
            self.assertEqual(launcher.port, 19064)
            self.assertEqual(launcher.url, "http://127.0.0.1:19064/")

    def test_default_launcher_reports_invalid_bootstrap_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = BootstrapStore(root / "bootstrap.json")
            store.path.write_text('{"web_port": 70000}', encoding="utf-8")
            with self.assertRaises(LaunchFailure) as caught:
                create_default_launcher(root, lambda _message: None, bootstrap_store=store)
            self.assertEqual(caught.exception.code, "bootstrap_invalid")

    def test_default_launcher_reports_unreadable_bootstrap_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = BootstrapStore(root / "bootstrap.json")
            store.path.write_text("{}", encoding="utf-8")
            with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                with self.assertRaises(LaunchFailure) as caught:
                    create_default_launcher(root, lambda _message: None, bootstrap_store=store)
            self.assertEqual(caught.exception.code, "bootstrap_invalid")

    def test_frontend_assets_are_checked_before_process_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertFalse(_frontend_assets_ready(root))
            started: list[bool] = []
            launcher = WorkbenchLauncher(
                service_probe=lambda _url: None,
                status_probe=lambda _url: None,
                port_in_use=lambda _port: False,
                process_start=lambda: started.append(True),
                browser_open=lambda _url: None,
                wait=lambda _seconds: None,
                frontend_ready=lambda: False,
            )
            with self.assertRaises(LaunchFailure) as caught:
                launcher.launch()
            self.assertEqual(caught.exception.code, "frontend_missing")
            self.assertEqual(started, [])

            assets = root / "web" / "frontend" / "dist" / "assets"
            assets.mkdir(parents=True)
            (assets.parent / "index.html").write_text(
                '<link rel="stylesheet" href="/assets/main.css"><script src="/assets/main.js"></script>',
                encoding="utf-8",
            )
            (assets / "main.js").write_text("js", encoding="utf-8")
            (assets / "main.css").write_text("css", encoding="utf-8")
            self.assertTrue(_frontend_assets_ready(root))
            (assets / "main.js").unlink()
            self.assertFalse(_frontend_assets_ready(root))

    def test_launcher_waits_after_terminate_and_kill(self) -> None:
        events: list[str] = []

        class Process:
            waits = 0

            def poll(self):
                return None

            def terminate(self):
                events.append("terminate")

            def wait(self, timeout=None):
                self.waits += 1
                events.append(f"wait-{self.waits}")
                if self.waits == 1:
                    raise subprocess.TimeoutExpired("web", timeout)

            def kill(self):
                events.append("kill")

        launcher = WorkbenchLauncher(
            service_probe=lambda _url: None,
            status_probe=lambda _url: None,
            port_in_use=lambda _port: False,
            process_start=Process,
            browser_open=lambda _url: None,
            wait=lambda _seconds: None,
            attempts=1,
        )
        with self.assertRaises(LaunchFailure):
            launcher.launch()
        self.assertEqual(events, ["terminate", "wait-1", "kill", "wait-2"])

    def test_launcher_cleanup_failure_does_not_mask_launch_error(self) -> None:
        class Process:
            def poll(self):
                return None

            def terminate(self):
                raise PermissionError("denied")

        launcher = WorkbenchLauncher(
            service_probe=lambda _url: None,
            status_probe=lambda _url: None,
            port_in_use=lambda _port: False,
            process_start=Process,
            browser_open=lambda _url: None,
            wait=lambda _seconds: None,
            attempts=1,
        )
        with self.assertRaises(LaunchFailure) as caught:
            launcher.launch()
        self.assertEqual(caught.exception.code, "service_start_failed")

    def test_launcher_waits_for_child_that_already_exited(self) -> None:
        waits: list[int] = []

        class Process:
            def poll(self):
                return 2

            def wait(self, timeout=None):
                waits.append(timeout)
                raise PermissionError("already reaped")

        launcher = WorkbenchLauncher(
            service_probe=lambda _url: None,
            status_probe=lambda _url: None,
            port_in_use=lambda _port: False,
            process_start=Process,
            browser_open=lambda _url: None,
            wait=lambda _seconds: None,
        )
        with self.assertRaises(LaunchFailure) as caught:
            launcher.launch()
        self.assertEqual(caught.exception.code, "service_start_failed")
        self.assertEqual(waits, [0])

    def test_database_lock_stops_at_recovery_message(self) -> None:
        health_calls = 0
        terminated: list[bool] = []

        class Process:
            def poll(self):
                return None

            def terminate(self):
                terminated.append(True)

        def health(_url):
            nonlocal health_calls
            health_calls += 1
            return None if health_calls == 1 else self.current_health()

        launcher = WorkbenchLauncher(
            service_probe=health,
            status_probe=lambda _url: {"error": {"code": "database_in_use"}},
            port_in_use=lambda _port: False,
            process_start=Process,
            browser_open=lambda _url: None,
            wait=lambda _seconds: None,
        )
        with self.assertRaises(LaunchFailure) as caught:
            launcher.launch()
        self.assertEqual(caught.exception.code, "database_in_use")
        self.assertIn("关闭桌面端", str(caught.exception))
        self.assertEqual(terminated, [True])

    def test_database_fault_matrix_stops_before_opening_browser(self) -> None:
        for fault_code in (
            "configured_database_missing",
            "database_corrupt",
            "unsupported_schema",
            "database_upgrade_failed",
        ):
            with self.subTest(fault_code=fault_code):
                health_calls = 0
                opened: list[str] = []

                class Process:
                    def poll(self):
                        return None

                    def terminate(self):
                        return None

                def health(_url):
                    nonlocal health_calls
                    health_calls += 1
                    if health_calls == 1:
                        return None
                    return self.current_health()

                launcher = WorkbenchLauncher(
                    service_probe=health,
                    status_probe=lambda _url, code=fault_code: {"error": {"code": code}},
                    port_in_use=lambda _port: False,
                    process_start=Process,
                    browser_open=opened.append,
                    wait=lambda _seconds: None,
                )
                with self.assertRaises(LaunchFailure) as caught:
                    launcher.launch()
                self.assertEqual(caught.exception.code, fault_code)
                self.assertEqual(opened, [])

    def test_launcher_emits_structured_progress_for_fresh_startup(self) -> None:
        events: list[dict[str, str]] = []
        health_calls = 0

        class Process:
            def poll(self):
                return None

        def health(_url):
            nonlocal health_calls
            health_calls += 1
            return None if health_calls == 1 else self.current_health()

        launcher = WorkbenchLauncher(
            service_probe=health,
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: False,
            process_start=Process,
            browser_open=lambda _url: True,
            wait=lambda _seconds: None,
            progress=events.append,
        )

        self.assertEqual(launcher.launch(), "started")
        self.assertEqual(
            events,
            [
                {"step": STEP_CHECK_PORT, "state": "running", "detail": "正在检查端口和已有服务"},
                {"step": STEP_CHECK_FRONTEND, "state": "running", "detail": "正在检查网页资源"},
                {"step": STEP_CHECK_FRONTEND, "state": "completed", "detail": "网页资源检查通过"},
                {"step": STEP_CHECK_PORT, "state": "completed", "detail": "端口和已有服务检查完成"},
                {"step": STEP_CONNECT_DATABASE, "state": "running", "detail": "本地服务已启动，正在确认人才库状态"},
                {"step": STEP_CONFIRM_DATABASE, "state": "running", "detail": "正在确认数据库状态"},
                {"step": STEP_CONNECT_DATABASE, "state": "completed", "detail": "人才库已连接"},
                {"step": STEP_CONFIRM_DATABASE, "state": "completed", "detail": "人才库状态已确认"},
                {"step": STEP_OPEN_BROWSER, "state": "running", "detail": "正在提交打开浏览器"},
                {"step": STEP_OPEN_BROWSER, "state": "completed", "detail": "浏览器已打开网页工作台"},
            ],
        )

    def test_running_service_progress_confirms_database_before_opening_browser(self) -> None:
        events: list[dict[str, str]] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: self.current_health(),
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=lambda _url: True,
            wait=lambda _seconds: None,
            progress=events.append,
        )

        self.assertEqual(launcher.launch(), "already_running")
        self.assertEqual(events[2], {"step": STEP_CONNECT_DATABASE, "state": "running", "detail": "本地服务可访问，正在确认人才库状态"})
        self.assertEqual(events[4], {"step": STEP_CONNECT_DATABASE, "state": "completed", "detail": "人才库已连接"})
        self.assertEqual(events[5], {"step": STEP_CONFIRM_DATABASE, "state": "completed", "detail": "人才库状态已确认"})

    def test_running_service_with_unavailable_app_status_marks_both_database_steps_failed(self) -> None:
        events: list[dict[str, str]] = []
        opened: list[str] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: self.current_health(),
            status_probe=lambda _url: None,
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=opened.append,
            wait=lambda _seconds: None,
            progress=events.append,
        )

        with self.assertRaises(LaunchFailure) as caught:
            launcher.launch()
        self.assertEqual(caught.exception.code, "service_start_failed")
        final_states = {event["step"]: event["state"] for event in events}
        self.assertEqual(final_states[STEP_CONNECT_DATABASE], "failed")
        self.assertEqual(final_states[STEP_CONFIRM_DATABASE], "failed")
        self.assertNotIn("running", final_states.values())
        self.assertEqual(opened, [])

    def test_first_setup_path_uses_not_ready_copy_without_claiming_database_connected(self) -> None:
        events: list[dict[str, str]] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: self.current_health(),
            status_probe=lambda _url: {"error": {"code": "database_not_ready"}},
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=lambda _url: True,
            wait=lambda _seconds: None,
            progress=events.append,
        )

        self.assertEqual(launcher.launch(), "already_running")
        details = [event["detail"] for event in events]
        self.assertIn("本地服务可访问，尚未配置人才库，将进入首次设置", details)
        self.assertIn("人才库状态已确认，将进入首次设置", details)
        self.assertNotIn("已连接人才库", "".join(details))
        self.assertNotIn("本地服务已连接人才库", "".join(details))

    def test_database_fault_matrix_never_reports_connected_database_progress(self) -> None:
        for fault_code in (
            "database_corrupt",
            "database_in_use",
            "configured_database_missing",
            "unsupported_schema",
            "database_upgrade_failed",
        ):
            with self.subTest(fault_code=fault_code):
                events: list[dict[str, str]] = []
                health_calls = 0

                class Process:
                    def poll(self):
                        return None

                    def terminate(self):
                        return None

                def health(_url):
                    nonlocal health_calls
                    health_calls += 1
                    return None if health_calls == 1 else self.current_health()

                launcher = WorkbenchLauncher(
                    service_probe=health,
                    status_probe=lambda _url, code=fault_code: {"error": {"code": code}},
                    port_in_use=lambda _port: False,
                    process_start=Process,
                    browser_open=lambda _url: None,
                    wait=lambda _seconds: None,
                    progress=events.append,
                )
                with self.assertRaises(LaunchFailure):
                    launcher.launch()
                details = [event["detail"] for event in events]
                self.assertNotIn("已连接人才库", "".join(details))
                self.assertNotIn("本地服务已连接人才库", "".join(details))
                self.assertIn("正在确认数据库状态", details)
                final_states = {event["step"]: event["state"] for event in events}
                self.assertEqual(final_states[STEP_CONNECT_DATABASE], "failed")
                self.assertEqual(final_states[STEP_CONFIRM_DATABASE], "failed")
                self.assertNotIn("running", final_states.values())

    def test_started_service_with_unavailable_app_status_marks_both_database_steps_failed_and_reaps_process(self) -> None:
        events: list[dict[str, str]] = []
        opened: list[str] = []
        reaped: list[str] = []
        health_calls = {"count": 0}

        class Process:
            def poll(self):
                return None

            def terminate(self):
                reaped.append("terminate")

            def wait(self, timeout=None):
                reaped.append(f"wait:{timeout}")

        def health(_url):
            health_calls["count"] += 1
            return None if health_calls["count"] == 1 else self.current_health()

        def status_probe(_url):
            return None

        launcher = WorkbenchLauncher(
            service_probe=health,
            status_probe=status_probe,
            port_in_use=lambda _port: False,
            process_start=Process,
            browser_open=opened.append,
            wait=lambda _seconds: None,
            attempts=3,
            progress=events.append,
        )

        with self.assertRaises(LaunchFailure) as caught:
            launcher.launch()
        self.assertEqual(caught.exception.code, "service_start_failed")
        final_states = {event["step"]: event["state"] for event in events}
        self.assertEqual(final_states[STEP_CONNECT_DATABASE], "failed")
        self.assertEqual(final_states[STEP_CONFIRM_DATABASE], "failed")
        self.assertNotIn("running", final_states.values())
        self.assertEqual(opened, [])
        self.assertEqual(reaped, ["terminate", "wait:3"])

    def test_launcher_cancel_stops_only_started_process_and_skips_browser_open(self) -> None:
        events: list[str] = []
        wait_calls = 0
        gate = StartupCancellationGate()

        class Process:
            def poll(self):
                return None

            def terminate(self):
                events.append("terminate")

            def wait(self, timeout=None):
                nonlocal wait_calls
                wait_calls += 1
                events.append(f"wait:{timeout}")
                if wait_calls == 1:
                    raise subprocess.TimeoutExpired("web", timeout)

            def kill(self):
                events.append("kill")

        def health(_url):
            return None

        launcher = WorkbenchLauncher(
            service_probe=health,
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: False,
            process_start=Process,
            browser_open=lambda _url: events.append("open-browser"),
            wait=lambda _seconds: None,
            gate=gate,
        )

        health_calls = {"count": 0}

        def health_with_cancel(_url):
            health_calls["count"] += 1
            if health_calls["count"] == 2:
                gate.request_cancel()
            return None

        launcher.service_probe = health_with_cancel

        with self.assertRaisesRegex(RuntimeError, "启动已取消"):
            launcher.launch()
        self.assertEqual(events, ["terminate", "wait:3", "kill", "wait:3"])
        self.assertNotIn("open-browser", events)

    def test_browser_open_commit_wins_over_late_cancel(self) -> None:
        opened: list[str] = []
        gate = StartupCancellationGate()

        class CommitOpen:
            def __call__(self, url):
                gate.request_cancel()
                opened.append(url)
                return True

        launcher = WorkbenchLauncher(
            service_probe=lambda _url: self.current_health(),
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=CommitOpen(),
            wait=lambda _seconds: None,
            gate=gate,
        )

        self.assertEqual(launcher.launch(), "already_running")
        self.assertEqual(opened, ["http://127.0.0.1:17864/"])
        self.assertEqual(
            gate.current_state(),
            {"cancellable": False, "cancelled": False, "browser_open_committed": True},
        )

    def test_create_default_launcher_can_cancel_during_config_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = BootstrapStore(root / "bootstrap.json")
            store.save(BootstrapSettings(data_dir=str(root / "data"), web_port=17864))

            with self.assertRaises(LaunchCancelled) as caught:
                gate = StartupCancellationGate()
                gate.request_cancel()
                create_default_launcher(root, lambda _event: None, bootstrap_store=store, gate=gate)

        self.assertEqual(caught.exception.step, STEP_READ_CONFIG)

    def test_create_default_launcher_can_cancel_during_runtime_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = BootstrapStore(root / "bootstrap.json")
            store.save(BootstrapSettings(data_dir=str(root / "data"), web_port=17864))
            gate = StartupCancellationGate()

            def progress(event: dict[str, str]) -> None:
                if event["step"] == STEP_CHECK_RUNTIME and event["state"] == "running":
                    gate.request_cancel()

            with self.assertRaises(LaunchCancelled) as caught:
                create_default_launcher(root, progress, bootstrap_store=store, gate=gate)

        self.assertEqual(caught.exception.step, STEP_CHECK_RUNTIME)

    def test_launch_window_shows_cancelled_state_when_factory_respects_cancel(self) -> None:
        def launcher_factory(_project_root, progress, gate):
            progress({"step": STEP_READ_CONFIG, "state": "running", "detail": "正在读取本机配置"})

            class FakeLauncher:
                def launch(self_nonlocal):
                    while not gate.current_state()["cancelled"]:
                        threading.Event().wait(0.01)
                    raise LaunchCancelled(step=STEP_READ_CONFIG)

            return FakeLauncher()

        window, root = self.build_fake_launch_window(launcher_factory)
        try:
            window.start_check()
            root.update()
            window.request_close()
            for _ in range(200):
                time.sleep(0.02)
                root.update()
                if not window.running:
                    break
            self.assertFalse(window.running)
            self.assertEqual(window.message.get(), "已取消本轮启动检查。")
            self.assertEqual(window.retry_button["state"], "normal")
            self.assertEqual(window.close_button["text"], "关闭")
        finally:
            root.destroy()

    def test_launch_window_does_not_claim_cancelled_after_browser_open_is_committed(self) -> None:
        def launcher_factory(_project_root, progress, gate):
            class FakeLauncher:
                def launch(self_nonlocal):
                    progress({"step": STEP_OPEN_BROWSER, "state": "running", "detail": "正在提交打开浏览器"})
                    self.assertTrue(gate.commit_browser_open())
                    threading.Event().wait(0.3)

            return FakeLauncher()

        window, root = self.build_fake_launch_window(launcher_factory)
        try:
            window.start_check()
            for _ in range(20):
                time.sleep(0.01)
                root.update()
                if window.current_step == STEP_OPEN_BROWSER:
                    break
            window.request_close()
            for _ in range(5):
                time.sleep(0.01)
                root.update()
            self.assertNotIn("已取消", window.message.get())
            self.assertNotIn("正在取消", window.message.get())
            self.assertEqual(window.close_button["text"], "请稍候")
        finally:
            root.destroy()

    def test_startup_cancellation_gate_allows_exactly_one_winner_across_100_races(self) -> None:
        for _ in range(100):
            gate = StartupCancellationGate()
            barrier = threading.Barrier(3)
            results: list[tuple[str, bool]] = []

            def request_cancel() -> None:
                barrier.wait()
                results.append(("cancel", gate.request_cancel()))

            def commit_browser_open() -> None:
                barrier.wait()
                results.append(("commit", gate.commit_browser_open()))

            threads = [
                threading.Thread(target=request_cancel),
                threading.Thread(target=commit_browser_open),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()

            self.assertEqual(sum(1 for _, won in results if won), 1)
            self.assertIn(
                gate.current_state(),
                (
                    {"cancellable": False, "cancelled": True, "browser_open_committed": False},
                    {"cancellable": False, "cancelled": False, "browser_open_committed": True},
                ),
            )

    def test_launcher_cancel_race_can_win_without_opening_browser(self) -> None:
        opened: list[str] = []

        class CancelFirstGate(StartupCancellationGate):
            def __init__(self) -> None:
                super().__init__()
                self.barrier = threading.Barrier(2)

            def request_cancel(self) -> bool:
                self.barrier.wait()
                return super().request_cancel()

            def commit_browser_open(self) -> bool:
                self.barrier.wait()
                time.sleep(0.01)
                return super().commit_browser_open()

        gate = CancelFirstGate()
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: self.current_health(),
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=lambda url: opened.append(url) or True,
            wait=lambda _seconds: None,
            gate=gate,
        )

        outcome: list[str] = []

        def run_launch() -> None:
            try:
                launcher.launch()
            except LaunchCancelled:
                outcome.append("cancelled")

        thread = threading.Thread(target=run_launch)
        thread.start()
        gate.request_cancel()
        thread.join()

        self.assertEqual(outcome, ["cancelled"])
        self.assertEqual(opened, [])

    def test_launcher_commit_race_can_win_and_open_browser_once(self) -> None:
        opened: list[str] = []

        class CommitFirstGate(StartupCancellationGate):
            def __init__(self) -> None:
                super().__init__()
                self.barrier = threading.Barrier(2)

            def request_cancel(self) -> bool:
                self.barrier.wait()
                time.sleep(0.01)
                return super().request_cancel()

            def commit_browser_open(self) -> bool:
                self.barrier.wait()
                return super().commit_browser_open()

        gate = CommitFirstGate()
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: self.current_health(),
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=lambda url: opened.append(url) or True,
            wait=lambda _seconds: None,
            gate=gate,
        )

        result: list[str] = []

        def run_launch() -> None:
            result.append(launcher.launch())

        thread = threading.Thread(target=run_launch)
        thread.start()
        gate.request_cancel()
        thread.join()

        self.assertEqual(result, ["already_running"])
        self.assertEqual(opened, ["http://127.0.0.1:17864/"])

    def test_cmd_launcher_is_saved_without_bom_crlf_and_question_mark_fallback(self) -> None:
        cmd = Path(__file__).resolve().parents[1] / "launch_web_workbench.cmd"
        content = cmd.read_bytes()
        self.assertFalse(content.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", content)
        text = content.decode("utf-8")
        self.assertIn("启动网页工作台", text)
        self.assertIn("缺少本地运行环境，请重新安装完整项目后再试。", text)
        self.assertNotRegex(text, r"\?{3,}")
        self.assertIn(".venv\\Scripts\\pythonw.exe", text)
        self.assertNotIn(".venv\\Scripts\\python.exe", text)


if __name__ == "__main__":
    unittest.main()
