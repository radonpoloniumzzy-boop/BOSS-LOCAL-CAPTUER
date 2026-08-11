from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from core.bootstrap import BootstrapService, BootstrapStore
from core.config import ConfigService
from web.backend.app import create_web_app
from web.backend.workbench_launcher import LaunchFailure, WorkbenchLauncher


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
        self.app = create_web_app(self.bootstrap, lock_root=self.root / "locks")
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

    def test_state_change_without_origin_is_rejected(self) -> None:
        response = self.client.post("/api/plugin-connection/pairing-code")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "same_origin_required")


class WorkbenchLauncherBehaviorTest(unittest.TestCase):
    def test_running_service_is_opened_without_starting_second_process(self) -> None:
        opened: list[str] = []
        started: list[bool] = []
        launcher = WorkbenchLauncher(
            service_probe=lambda _url: {
                "status": "ok",
                "service": "recruiting-talent-workbench",
            },
            status_probe=lambda _url: {"database_ready": True},
            port_in_use=lambda _port: True,
            process_start=lambda: started.append(True),
            browser_open=opened.append,
            wait=lambda _seconds: None,
        )
        self.assertEqual(launcher.launch(), "already_running")
        self.assertEqual(started, [])
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
            return None if health_calls == 1 else {
                "status": "ok",
                "service": "recruiting-talent-workbench",
            }

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


if __name__ == "__main__":
    unittest.main()
