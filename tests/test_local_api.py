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


if __name__ == "__main__":
    unittest.main()
