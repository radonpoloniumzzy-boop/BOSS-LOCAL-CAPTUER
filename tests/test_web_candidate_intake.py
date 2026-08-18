from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def _headers(self, origin: str = "http://127.0.0.1:17864") -> dict[str, str]:
        return {
            "Origin": origin,
            "X-Boss-Local-Token": self.token,
        }

    def _repository(self) -> CandidateRepository:
        runtime = self.app.state.runtime
        assert runtime.repository is not None
        return runtime.repository

    def test_candidate_intake_requires_token(self) -> None:
        response = self.client.post(
            "/api/intake/candidates",
            json={"source_platform": "boss", "candidates": [{"raw_card_text": "x"}]},
            headers={"Origin": "http://127.0.0.1:17864"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn(self.token, response.text)

    def test_candidate_intake_accepts_chrome_extension_origin(self) -> None:
        response = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "idempotency_key": "chrome-extension-origin",
                "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
            },
            headers=self._headers("chrome-extension://unit-test-extension"),
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["inserted_candidates"], 1)

    def test_candidate_intake_rejects_non_local_non_extension_origin(self) -> None:
        response = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "idempotency_key": "bad-origin",
                "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
            },
            headers=self._headers("https://example.com"),
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["error"]["code"], "same_origin_required")

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

    def test_candidate_search_sort_detail_and_batch_lookup(self) -> None:
        first = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "source_job_title": "证券交易员",
                "idempotency_key": "candidate-search-1",
                "candidates": [
                    {
                        "name": "Alice Zhang",
                        "source_candidate_id": "boss-101",
                        "raw_card_text": "Alice raw card with 高频交易 经验",
                        "capture_time": "2026-08-10T09:00:00",
                    }
                ],
            },
            headers=self._headers(),
        )
        second = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "liepin",
                "source_job_title": "量化研究员",
                "idempotency_key": "candidate-search-2",
                "candidates": [
                    {
                        "name": "Bob Li",
                        "source_candidate_id": "liepin-202",
                        "raw_card_text": "Bob raw card with 因子研究 与 原始卡片关键词",
                        "capture_time": "2026-08-11T10:30:00",
                    }
                ],
            },
            headers=self._headers(),
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)

        by_name = self.client.get("/api/candidates?page=1&page_size=100&keyword=Alice")
        self.assertEqual(by_name.status_code, 200)
        self.assertEqual(len(by_name.json()["rows"]), 1)
        self.assertEqual(by_name.json()["rows"][0]["name"], "Alice Zhang")
        self.assertEqual(
            set(by_name.json()["rows"][0].keys()),
            {
                "id",
                "name",
                "source_platform",
                "latest_source_platform",
                "latest_source_job_title",
                "latest_batch_id",
                "latest_capture_time",
                "latest_ingest_status",
                "latest_batch_role_id",
                "has_role_binding",
                "batch_count",
            },
        )
        for forbidden_field in (
            "raw_card_text",
            "latest_raw_card_text",
            "source_url",
            "latest_source_url",
            "detail_url",
            "latest_detail_url",
            "evidence_json",
            "gap_json",
            "risk_json",
            "recommended_action",
            "human_decision",
            "status_events",
            "role_matches",
        ):
            self.assertNotIn(forbidden_field, by_name.json()["rows"][0])

        by_job_title = self.client.get("/api/candidates?page=1&page_size=100&keyword=量化研究员")
        self.assertEqual(by_job_title.status_code, 200)
        self.assertEqual(len(by_job_title.json()["rows"]), 1)
        self.assertEqual(by_job_title.json()["rows"][0]["name"], "Bob Li")

        by_raw_keyword = self.client.get("/api/candidates?page=1&page_size=100&keyword=原始卡片关键词")
        self.assertEqual(by_raw_keyword.status_code, 200)
        self.assertEqual(len(by_raw_keyword.json()["rows"]), 1)
        self.assertEqual(by_raw_keyword.json()["rows"][0]["name"], "Bob Li")

        newest_first = self.client.get("/api/candidates?page=1&page_size=100&sort=latest_capture_desc")
        oldest_first = self.client.get("/api/candidates?page=1&page_size=100&sort=latest_capture_asc")
        self.assertEqual(newest_first.status_code, 200)
        self.assertEqual(oldest_first.status_code, 200)
        self.assertEqual(newest_first.json()["rows"][0]["name"], "Bob Li")
        self.assertEqual(oldest_first.json()["rows"][0]["name"], "Alice Zhang")

        candidate_id = newest_first.json()["rows"][0]["id"]
        detail = self.client.get(f"/api/candidates/{candidate_id}")
        self.assertEqual(detail.status_code, 200)
        detail_payload = detail.json()
        self.assertEqual(detail_payload["name"], "Bob Li")
        self.assertEqual(detail_payload["latest_source_job_title"], "量化研究员")
        self.assertIn("原始卡片关键词", detail_payload["latest_raw_card_text"])
        self.assertEqual(
            set(detail_payload.keys()),
            {
                "id",
                "name",
                "source_platform",
                "latest_source_platform",
                "latest_source_job_title",
                "latest_batch_id",
                "latest_capture_time",
                "latest_ingest_status",
                "latest_batch_role_id",
                "has_role_binding",
                "batch_count",
                "job_title",
                "source_url",
                "capture_time",
                "raw_card_text",
                "active_status",
                "expected_salary",
                "work_experience_text",
                "education_text",
                "tags_text",
                "summary_text",
                "detail_url",
                "latest_raw_card_text",
                "latest_source_url",
                "latest_detail_url",
                "city",
                "years_experience",
                "job_family",
                "job_track",
            },
        )
        for forbidden_field in (
            "role_matches",
            "status_events",
            "evidence_json",
            "gap_json",
            "risk_json",
            "recommended_action",
            "human_decision",
        ):
            self.assertNotIn(forbidden_field, detail_payload)

        batch_id = newest_first.json()["rows"][0]["latest_batch_id"]
        batch = self.client.get(f"/api/capture-batches/{batch_id}")
        self.assertEqual(batch.status_code, 200)
        self.assertEqual(batch.json()["id"], batch_id)

    def test_candidate_detail_returns_not_found_for_missing_candidate(self) -> None:
        response = self.client.get("/api/candidates/999999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "candidate_not_found")

    def test_candidate_appearance_history_uses_batch_snapshots_and_limited_fields(self) -> None:
        first = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "source_job_title": "证券交易员",
                "idempotency_key": "appearance-history-1",
                "candidates": [
                    {
                        "name": "History Candidate",
                        "source_candidate_id": "boss-history-1",
                        "raw_card_text": "first snapshot",
                        "capture_time": "2026-08-10T09:00:00",
                    }
                ],
            },
            headers=self._headers(),
        )
        second = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "source_job_title": "量化研究员",
                "idempotency_key": "appearance-history-2",
                "candidates": [
                    {
                        "name": "History Candidate Updated",
                        "source_candidate_id": "boss-history-1",
                        "raw_card_text": "second snapshot",
                        "capture_time": "2026-08-11T10:30:00",
                    }
                ],
            },
            headers=self._headers(),
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)

        candidates = self.client.get("/api/candidates?page=1&page_size=100&keyword=History Candidate")
        self.assertEqual(candidates.status_code, 200)
        candidate_id = candidates.json()["rows"][0]["id"]

        appearances = self.client.get(f"/api/candidates/{candidate_id}/appearances")
        self.assertEqual(appearances.status_code, 200)
        rows = appearances.json()["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source_job_title"], "量化研究员")
        self.assertEqual(rows[1]["source_job_title"], "证券交易员")
        self.assertEqual(
            set(rows[0].keys()),
            {"batch_id", "source_platform", "source_job_title", "capture_time", "ingest_status"},
        )
        for forbidden in (
            "raw_card_text",
            "name",
            "source_url",
            "detail_url",
            "role_matches",
            "status_events",
            "evidence_json",
            "gap_json",
            "risk_json",
            "recommended_action",
            "human_decision",
        ):
            self.assertNotIn(forbidden, rows[0])

        missing = self.client.get("/api/candidates/999999/appearances")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "candidate_not_found")

    def test_capture_batch_filters_support_status_failed_today_and_export_snapshot(self) -> None:
        repo = self._repository()
        with patch("storage.repository.now_iso", return_value="2026-08-18T09:30:00"):
            first = self.client.post(
                "/api/intake/candidates",
                json={
                    "source_platform": "boss",
                    "source_job_title": "证券交易员",
                    "idempotency_key": "batch-filter-1",
                    "candidates": [
                        {
                            "name": "Today Success",
                            "source_candidate_id": "boss-batch-1",
                            "raw_card_text": "today success snapshot",
                            "capture_time": "2026-08-18T00:15:00",
                        }
                    ],
                },
                headers=self._headers(),
            )
            second = self.client.post(
                "/api/intake/candidates",
                json={
                    "source_platform": "liepin",
                    "source_job_title": "量化研究员",
                    "idempotency_key": "batch-filter-2",
                    "candidates": [
                        {
                            "name": "Today Partial",
                            "source_candidate_id": "liepin-batch-2",
                            "raw_card_text": "today partial snapshot",
                            "capture_time": "2026-08-18T12:00:00",
                        },
                        {
                            "name": "Broken",
                            "source_candidate_id": "liepin-batch-3",
                        },
                    ],
                },
                headers=self._headers(),
            )
            third = self.client.post(
                "/api/intake/candidates",
                json={
                    "source_platform": "boss",
                    "source_job_title": "昨日批次",
                    "idempotency_key": "batch-filter-3",
                    "candidates": [
                        {
                            "name": "Yesterday Failed",
                            "source_candidate_id": "boss-batch-4",
                            "raw_card_text": "yesterday failed snapshot",
                            "capture_time": "2026-08-17T23:50:00",
                        }
                    ],
                },
                headers=self._headers(),
            )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(third.status_code, 200, third.text)

        batch_by_job = {
            "证券交易员": first.json()["batch_id"],
            "量化研究员": second.json()["batch_id"],
            "昨日批次": third.json()["batch_id"],
        }
        repo.db.get_connection().execute(
            "UPDATE capture_batches SET status = 'failed', total_failed = 1 WHERE id = ?",
            (batch_by_job["昨日批次"],),
        )
        repo.db.get_connection().execute(
            "UPDATE capture_batches SET start_time = '2026-08-17T23:50:00' WHERE id = ?",
            (batch_by_job["昨日批次"],),
        )
        repo.db.get_connection().commit()

        completed = self.client.get("/api/capture-batches?page=1&page_size=20&status=completed")
        self.assertEqual(completed.status_code, 200)
        self.assertEqual([row["job_title"] for row in completed.json()["rows"]], ["证券交易员"])

        failed_only = self.client.get("/api/capture-batches?page=1&page_size=20&failed_only=true")
        self.assertEqual(failed_only.status_code, 200)
        self.assertEqual({row["job_title"] for row in failed_only.json()["rows"]}, {"量化研究员", "昨日批次"})

        with patch("storage.repository.now_iso", return_value="2026-08-18T09:30:00"):
            today_only = self.client.get("/api/capture-batches?page=1&page_size=20&today_only=true")
        self.assertEqual(today_only.status_code, 200)
        self.assertEqual({row["job_title"] for row in today_only.json()["rows"]}, {"证券交易员", "量化研究员"})

        combo = self.client.get("/api/capture-batches?page=1&page_size=20&source_platform=liepin&status=partial")
        self.assertEqual(combo.status_code, 200)
        self.assertEqual(combo.json()["total"], 1)
        self.assertEqual(combo.json()["rows"][0]["job_title"], "量化研究员")

        paged = self.client.get("/api/capture-batches?page=1&page_size=1&failed_only=true")
        self.assertEqual(paged.status_code, 200)
        self.assertEqual(paged.json()["total"], 2)
        self.assertEqual(len(paged.json()["rows"]), 1)

        export_target = batch_by_job["证券交易员"]
        repo.db.get_connection().execute(
            "UPDATE candidates SET name = 'Changed Later' WHERE candidate_key = ?",
            ("boss:boss-batch-1",),
        )
        repo.db.get_connection().commit()
        exported = self.client.get(f"/api/capture-batches/{export_target}/export.md")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("Today Success", exported.text)
        self.assertIn("today success snapshot", exported.text)

        missing_batch = self.client.get("/api/capture-batches/999999")
        self.assertEqual(missing_batch.status_code, 404)
        self.assertEqual(missing_batch.json()["error"]["code"], "batch_not_found")


if __name__ == "__main__":
    unittest.main()
