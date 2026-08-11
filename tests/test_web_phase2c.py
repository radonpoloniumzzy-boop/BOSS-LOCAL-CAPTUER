from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.bootstrap import BootstrapService, BootstrapSettings, BootstrapStore
from core.config import ConfigService
from web.backend.app import WEB_CAPABILITIES, create_web_app
from web.backend.pairing import PairingCodeError, PluginPairingService
from web.backend.workbench_launcher import (
    LaunchFailure,
    WorkbenchLauncher,
    _frontend_assets_ready,
    _request_json,
    create_default_launcher,
)


class Phase2CWebApiTest(unittest.TestCase):
    @staticmethod
    def current_health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "recruiting-talent-workbench",
            "capabilities": WEB_CAPABILITIES,
        }

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


    def test_launcher_reports_real_progress_for_running_service(self) -> None:
        progress: list[str] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: self.current_health(),
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: True,
            process_start=lambda: None,
            browser_open=lambda _url: None,
            wait=lambda _seconds: None,
            progress=progress.append,
        )
        self.assertEqual(launcher.launch(), "already_running")
        self.assertEqual(
            progress,
            [
                "正在检查端口和已有服务",
                "网页工作台已经运行",
                "正在确认数据库状态",
                "正在打开浏览器",
            ],
        )

    def test_launcher_reports_real_progress_for_new_launch(self) -> None:
        progress: list[str] = []
        health_calls = 0

        class Process:
            def poll(self):
                return None

        def health(_url):
            nonlocal health_calls
            health_calls += 1
            if health_calls < 2:
                return None
            return self.current_health()

        launcher = WorkbenchLauncher(
            service_probe=health,
            status_probe=lambda _url: {"status": "ready", "database_ready": True},
            port_in_use=lambda _port: False,
            process_start=Process,
            browser_open=lambda _url: None,
            wait=lambda _seconds: None,
            progress=progress.append,
        )
        self.assertEqual(launcher.launch(), "started")
        self.assertEqual(
            progress,
            [
                "正在检查端口和已有服务",
                "正在检查网页资源",
                "正在连接人才库",
                "正在确认数据库状态",
                "正在启动本地服务",
                "正在等待网页工作台响应",
                "正在打开浏览器",
            ],
        )


if __name__ == "__main__":
    unittest.main()
