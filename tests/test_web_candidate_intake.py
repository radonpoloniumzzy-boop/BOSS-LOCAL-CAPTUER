from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from core.bootstrap import BootstrapService, BootstrapStore
from core.config import ConfigService
from core.models import JobProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository
from web.backend.app import create_web_app


class CandidateIntakeWebApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = BootstrapStore(self.root / "local" / "bootstrap.json")
        self.service = BootstrapService(
            project_root=self.project,
            store=self.store,
            d_drive=self.root / "missing-d-drive",
            documents_dir=self.root / "Documents",
        )
        self.data_dir = self.root / "data"
        self.service.setup(self.data_dir)
        self.config_service = ConfigService(data_dir=self.data_dir)
        self.token = self.config_service.load().local_api_token
        self.app = create_web_app(self.service, lock_root=self.root / "locks")
        self.client = TestClient(self.app, base_url="http://127.0.0.1:17864")
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def _headers(self) -> dict[str, str]:
        return {
            "Origin": "http://127.0.0.1:17864",
            "X-Boss-Local-Token": self.token,
        }

    def test_candidate_intake_requires_token(self) -> None:
        response = self.client.post(
            "/api/intake/candidates",
            json={"source_platform": "boss", "candidates": [{"raw_card_text": "x"}]},
            headers={"Origin": "http://127.0.0.1:17864"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn(self.token, response.text)

    def test_candidate_intake_and_queries_work_without_formal_role_binding(self) -> None:
        payload = {
            "source_platform": "boss",
            "source_job_title": "证券交易员",
            "idempotency_key": "web-intake-1",
            "candidates": [
                {
                    "name": "Alice",
                    "source_candidate_id": "boss-1",
                    "raw_card_text": "Alice card",
                },
                {
                    "name": "Alice Duplicate",
                    "source_candidate_id": "boss-1",
                    "raw_card_text": "Alice duplicate card",
                },
                {
                    "name": "Broken",
                    "source_candidate_id": "boss-2",
                },
            ],
        }
        intake = self.client.post("/api/intake/candidates", json=payload, headers=self._headers())

        self.assertEqual(intake.status_code, 200, intake.text)
        result = intake.json()
        self.assertEqual(result["inserted_candidates"], 1)
        self.assertEqual(result["skipped_candidates"], 1)
        self.assertEqual(result["failed_candidates"], 1)
        self.assertEqual(result["failures"][0]["code"], "invalid_candidate")
        self.assertNotIn("Alice card", intake.text)
        self.assertEqual(
            result["received_count"],
            result["inserted_candidates"]
            + result["updated_candidates"]
            + result["skipped_candidates"]
            + result["failed_candidates"],
        )

        candidates = self.client.get("/api/candidates?page=1&page_size=100&unbound_only=true")
        self.assertEqual(candidates.status_code, 200)
        rows = candidates.json()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Alice")
        self.assertEqual(rows[0]["latest_source_job_title"], "证券交易员")
        self.assertEqual(rows[0]["latest_ingest_status"], "new")
        self.assertEqual(rows[0]["latest_batch_role_id"], None)
        self.assertFalse(bool(rows[0]["has_role_binding"]))

        batches = self.client.get("/api/capture-batches?page=1&page_size=20&source_platform=boss")
        self.assertEqual(batches.status_code, 200)
        batch_rows = batches.json()["rows"]
        self.assertEqual(len(batch_rows), 1)
        self.assertEqual(batch_rows[0]["total_failed"], 1)
        self.assertEqual(batch_rows[0]["total_new"], 1)
        self.assertEqual(batch_rows[0]["total_skipped"], 1)
        self.assertEqual(
            batch_rows[0]["total_collected"],
            batch_rows[0]["total_new"]
            + batch_rows[0]["total_updated"]
            + batch_rows[0]["total_skipped"]
            + batch_rows[0]["total_failed"],
        )

        batch_id = batch_rows[0]["id"]
        batch_candidates = self.client.get(f"/api/capture-batches/{batch_id}/candidates?page=1&page_size=20")
        self.assertEqual(batch_candidates.status_code, 200)
        self.assertEqual(len(batch_candidates.json()["rows"]), 1)
        self.assertEqual(batch_candidates.json()["rows"][0]["name"], "Alice")

    def test_candidate_intake_creates_formal_role_binding_only_for_explicit_job_profile(self) -> None:
        repository = CandidateRepository(DatabaseManager(self.data_dir / "boss_local_tool.db"))
        profile = repository.save_job_profile(
            JobProfile(job_title="证券交易员", jd_text="", prompt_text="", status="active")
        )
        repository.db.close_thread_connection()

        same_title_unbound = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "source_job_title": "证券交易员",
                "idempotency_key": "same-title-no-role",
                "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
            },
            headers=self._headers(),
        )
        self.assertEqual(same_title_unbound.status_code, 200)

        bound = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "source_job_title": "证券交易员",
                "job_profile_id": profile.id,
                "idempotency_key": "explicit-role",
                "candidates": [{"source_candidate_id": "boss-2", "raw_card_text": "Dana card"}],
            },
            headers=self._headers(),
        )
        self.assertEqual(bound.status_code, 200)

        all_rows = self.client.get("/api/candidates?page=1&page_size=100").json()["rows"]
        self.assertEqual(len(all_rows), 2)
        self.assertTrue(any(bool(row["has_role_binding"]) for row in all_rows))
        self.assertTrue(any(not bool(row["has_role_binding"]) for row in all_rows))

        unbound_rows = self.client.get("/api/candidates?page=1&page_size=100&unbound_only=true").json()["rows"]
        self.assertEqual(len(unbound_rows), 1)
        self.assertFalse(bool(unbound_rows[0]["has_role_binding"]))

    def test_candidate_intake_accepts_explicit_platform_uid_without_raw_source_id(self) -> None:
        first = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "idempotency_key": "platform-uid-intake",
                "candidates": [{"platform_uid": "boss:123", "raw_card_text": "Alice card"}],
            },
            headers=self._headers(),
        )
        second = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "idempotency_key": "platform-uid-intake-update",
                "candidates": [{"platform_uid": "boss:123", "raw_card_text": "Alice updated card"}],
            },
            headers=self._headers(),
        )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["inserted_candidates"], 1)
        self.assertEqual(second.json()["updated_candidates"], 1)

    def test_candidate_intake_keeps_prefixed_raw_source_id_separate_from_explicit_platform_uid(self) -> None:
        first = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "idempotency_key": "explicit-platform-uid",
                "candidates": [{"platform_uid": "boss:123", "raw_card_text": "Alice card"}],
            },
            headers=self._headers(),
        )
        second = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "idempotency_key": "raw-prefixed-id",
                "candidates": [{"source_candidate_id": "boss:123", "raw_card_text": "Alice raw id card"}],
            },
            headers=self._headers(),
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        rows = self.client.get("/api/candidates?page=1&page_size=100").json()["rows"]
        self.assertEqual(len(rows), 2)

    def test_idempotency_conflict_returns_stable_business_error(self) -> None:
        first = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "idempotency_key": "conflict-key",
                "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
            },
            headers=self._headers(),
        )
        self.assertEqual(first.status_code, 200)

        second = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "idempotency_key": "conflict-key",
                "candidates": [{"source_candidate_id": "boss-2", "raw_card_text": "Bob card"}],
            },
            headers=self._headers(),
        )
        self.assertEqual(second.status_code, 409)
        payload = second.json()
        self.assertEqual(payload["error"]["code"], "idempotency_conflict")
        self.assertNotIn("Bob card", second.text)
        self.assertNotIn(self.token, second.text)


if __name__ == "__main__":
    unittest.main()
