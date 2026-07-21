from __future__ import annotations

import http.client
import json
import tempfile
import unittest
from pathlib import Path

from automation.importer import CardImportService
from automation.parser import CandidateParser
from core.local_api import LocalApiServer
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class LocalApiServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.token = "test-local-token"
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.service = CardImportService(self.repository, CandidateParser())
        self.server = LocalApiServer("127.0.0.1", 0, self.service, auth_token=self.token)
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_health_endpoint(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request("GET", "/health")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_root_endpoint_explains_how_to_check_connection(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request("GET", "/")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["connection_check"], "/api/connection/check")

    def test_connection_check_verifies_token(self) -> None:
        authorized = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        authorized.request(
            "GET",
            "/api/connection/check",
            headers={"X-Boss-Local-Token": self.token},
        )
        authorized_response = authorized.getresponse()
        authorized_payload = json.loads(authorized_response.read().decode("utf-8"))

        self.assertEqual(authorized_response.status, 200)
        self.assertTrue(authorized_payload["ok"])
        self.assertEqual(authorized_payload["auth"], "ok")

        unauthorized = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        unauthorized.request("GET", "/api/connection/check")
        unauthorized_response = unauthorized.getresponse()
        unauthorized_payload = json.loads(unauthorized_response.read().decode("utf-8"))

        self.assertEqual(unauthorized_response.status, 401)
        self.assertFalse(unauthorized_payload["ok"])

    def test_extension_config_requires_token_and_returns_naming_template(self) -> None:
        self.server.get_extension_config = lambda: {
            "resume_filename_template": "{candidate_name}_{original_name}",
            "job_title": "证券交易员",
        }
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request(
            "GET",
            "/api/extension/config",
            headers={"X-Boss-Local-Token": self.token},
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["result"]["job_title"], "证券交易员")

    def test_import_endpoint(self) -> None:
        body = json.dumps(
            {
                "job_title": "Recruiting Intern",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {
                        "raw_card_text": "Bob recruiting 11k bachelor",
                        "name": "Bob",
                        "expected_salary": "11k-13k",
                        "education_text": "Bachelor",
                    }
                ],
            }
        ).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request(
            "POST",
            "/api/import/cards",
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-Boss-Local-Token": self.token,
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(self.repository.list_candidates()), 1)

    def test_automation_progress_endpoint_forwards_authenticated_stage(self) -> None:
        received = []
        self.server.on_automation_progress = received.append
        body = json.dumps(
            {
                "collection_run_id": "collect-1",
                "stage": "scrolling",
                "current": 120,
                "message": "正在滚动采集",
            }
        ).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request(
            "POST",
            "/api/automation/progress",
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-Boss-Local-Token": self.token,
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(received[0]["stage"], "scrolling")
        self.assertEqual(received[0]["collection_run_id"], "collect-1")

    def test_import_rejects_missing_token(self) -> None:
        body = json.dumps({"cards": [{"raw_card_text": "Mallory"}]}).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request(
            "POST",
            "/api/import/cards",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 401)
        self.assertFalse(payload["ok"])
        self.assertEqual(len(self.repository.list_candidates()), 0)

    def test_options_allows_chrome_private_network_preflight(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request(
            "OPTIONS",
            "/api/import/cards",
            headers={
                "Origin": "https://www.zhipin.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-boss-local-token",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 204)
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), "*")
        self.assertEqual(response.getheader("Access-Control-Allow-Private-Network"), "true")

    def test_automation_status_and_start_endpoints(self) -> None:
        self.server.get_automation_status = lambda: {
            "ready": True,
            "enabled": False,
            "profile_job_title": "Java工程师",
        }
        self.server.start_automation = lambda payload: {
            "ready": True,
            "enabled": True,
            "profile_job_title": "Java工程师",
            "job_title": "Java工程师",
            "source_url": str(payload.get("source_url") or ""),
            "provider": "openai",
            "model": "test-model",
        }

        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request(
            "GET",
            "/api/automation/status",
            headers={"X-Boss-Local-Token": self.token},
        )
        status_response = connection.getresponse()
        status_payload = json.loads(status_response.read().decode("utf-8"))
        self.assertEqual(status_response.status, 200)
        self.assertTrue(status_payload["result"]["ready"])

        body = json.dumps({"source_url": "https://www.zhipin.com/web/geek/recommend"}).encode(
            "utf-8"
        )
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request(
            "POST",
            "/api/automation/start",
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-Boss-Local-Token": self.token,
            },
        )
        start_response = connection.getresponse()
        start_payload = json.loads(start_response.read().decode("utf-8"))
        self.assertEqual(start_response.status, 200)
        self.assertTrue(start_payload["result"]["enabled"])
        self.assertEqual(start_payload["result"]["job_title"], "Java工程师")

    def test_native_favorite_claim_and_result_endpoints_use_authenticated_callbacks(self) -> None:
        reported: list[dict[str, object]] = []
        self.server.claim_favorite_task = lambda payload: {
            "task_id": 71,
            "batch_id": int(payload["batch_id"]),
            "status": "running",
            "platform": "boss",
            "platform_identity": {
                "attribute": "data-geekid",
                "value": "trusted-geek-71",
            },
            "claim_token": "claim-token-71",
        }
        self.server.report_favorite_result = lambda payload: (
            reported.append(dict(payload))
            or {
                "task_id": int(payload["task_id"]),
                "status": str(payload["status"]),
                "attempt_count": 1,
            }
        )
        self.server.retry_favorite_task = lambda payload: {
            "task_id": int(payload["task_id"]),
            "status": "pending",
            "attempt_count": 1,
        }
        self.server.reconcile_favorite_batch = lambda payload: {
            "batch_id": int(payload["batch_id"]),
            "running": 0,
            "pending": 2,
            "unknown": 1,
            "can_resume_pending": True,
        }
        self.server.claim_favorite_verification = lambda payload: {
            "task_id": 71,
            "batch_id": int(payload["batch_id"]),
            "status": "verifying",
            "source_action_attempted": True,
            "claim_token": "verification-token-71",
        }
        self.server.report_favorite_verification = lambda payload: {
            "task_id": int(payload["task_id"]),
            "status": str(payload["status"]),
        }
        self.server.get_favorite_batch_status = lambda payload: {
            "batch_id": int(payload["batch_id"]),
            "status": "awaiting_verification",
            "pending_verification": 1,
        }

        claim_body = json.dumps({"batch_id": 19, "worker_id": "extension-tab-91"}).encode(
            "utf-8"
        )
        claim_connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        claim_connection.request(
            "POST",
            "/api/favorites/claim",
            body=claim_body,
            headers={
                "Content-Type": "application/json",
                "X-Boss-Local-Token": self.token,
            },
        )
        claim_response = claim_connection.getresponse()
        claim_payload = json.loads(claim_response.read().decode("utf-8"))

        self.assertEqual(claim_response.status, 200)
        self.assertEqual(claim_payload["result"]["task_id"], 71)
        self.assertEqual(
            claim_payload["result"]["platform_identity"],
            {"attribute": "data-geekid", "value": "trusted-geek-71"},
        )

        result_body = json.dumps(
            {
                "task_id": 71,
                "claim_token": "claim-token-71",
                "status": "unknown",
                "attempted": True,
                "reason": "favorite_management_identity_not_visible",
                "method": "native_detail_control",
            }
        ).encode("utf-8")
        result_connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        result_connection.request(
            "POST",
            "/api/favorites/result",
            body=result_body,
            headers={
                "Content-Type": "application/json",
                "X-Boss-Local-Token": self.token,
            },
        )
        result_response = result_connection.getresponse()
        result_payload = json.loads(result_response.read().decode("utf-8"))

        self.assertEqual(result_response.status, 200)
        self.assertEqual(result_payload["result"]["status"], "unknown")
        self.assertEqual(len(reported), 1)
        self.assertIs(reported[0]["attempted"], True)

        retry_body = json.dumps({"task_id": 71}).encode("utf-8")
        retry_connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        retry_connection.request(
            "POST",
            "/api/favorites/retry",
            body=retry_body,
            headers={
                "Content-Type": "application/json",
                "X-Boss-Local-Token": self.token,
            },
        )
        retry_response = retry_connection.getresponse()
        retry_payload = json.loads(retry_response.read().decode("utf-8"))

        self.assertEqual(retry_response.status, 200)
        self.assertEqual(retry_payload["result"]["status"], "pending")

        reconcile_connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        reconcile_connection.request(
            "POST",
            "/api/favorites/reconcile",
            body=json.dumps({"batch_id": 19}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Boss-Local-Token": self.token,
            },
        )
        reconcile_response = reconcile_connection.getresponse()
        reconcile_payload = json.loads(reconcile_response.read().decode("utf-8"))
        self.assertEqual(reconcile_response.status, 200)
        self.assertTrue(reconcile_payload["result"]["can_resume_pending"])

        verify_claim = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        verify_claim.request(
            "POST", "/api/favorites/verification/claim",
            body=json.dumps({"batch_id": 19}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Boss-Local-Token": self.token},
        )
        verify_claim_response = verify_claim.getresponse()
        verify_claim_payload = json.loads(verify_claim_response.read().decode("utf-8"))
        self.assertEqual(verify_claim_response.status, 200)
        self.assertEqual(verify_claim_payload["result"]["status"], "verifying")

        verify_result = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        verify_result.request(
            "POST", "/api/favorites/verification/result",
            body=json.dumps({
                "task_id": 71,
                "claim_token": "verification-token-71",
                "status": "success",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Boss-Local-Token": self.token},
        )
        verify_result_response = verify_result.getresponse()
        verify_result_payload = json.loads(verify_result_response.read().decode("utf-8"))
        self.assertEqual(verify_result_response.status, 200)
        self.assertEqual(verify_result_payload["result"]["status"], "success")

        status_connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        status_connection.request(
            "POST", "/api/favorites/status",
            body=json.dumps({"batch_id": 19}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Boss-Local-Token": self.token},
        )
        status_response = status_connection.getresponse()
        status_payload = json.loads(status_response.read().decode("utf-8"))
        self.assertEqual(status_response.status, 200)
        self.assertEqual(status_payload["result"]["status"], "awaiting_verification")


if __name__ == "__main__":
    unittest.main()
