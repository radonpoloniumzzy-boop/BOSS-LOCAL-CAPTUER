from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from automation.importer import CardImportService
from automation.parser import CandidateParser
from core.bootstrap import BootstrapService, BootstrapStore
from core.config import ConfigService
from core.models import JobProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository
from web.backend.app import create_web_app


class CandidateIntakeServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "boss_local_tool.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.service = CardImportService(self.repository, CandidateParser())

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp.cleanup()

    def test_import_candidates_accepts_job_optional_records(self) -> None:
        result = self.service.import_candidates(
            {
                "source_platform": "boss",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "candidates": [
                    {
                        "name": "Alice",
                        "source_candidate_id": "boss-1",
                        "raw_card_text": "Alice trader card",
                        "source_job_title": "证券交易员",
                    }
                ],
            }
        )

        self.assertEqual(result["inserted_candidates"], 1)
        self.assertEqual(result["job_profile_id"], None)
        candidates = [dict(row) for row in self.repository.list_candidates()]
        self.assertEqual(candidates[0]["source_platform"], "boss")
        self.assertEqual(candidates[0]["job_title"], "证券交易员")

    def test_import_candidates_only_source_job_title_and_blank_role_is_valid(self) -> None:
        result = self.service.import_candidates(
            {
                "source_platform": "liepin",
                "candidates": [
                    {
                        "name": "Bob",
                        "source_candidate_id": "resume-2",
                        "raw_card_text": "Bob java card",
                        "source_job_title": "Java工程师",
                    }
                ],
            }
        )

        self.assertEqual(result["inserted_candidates"], 1)
        self.assertEqual(result["failed_candidates"], 0)

    def test_import_candidates_is_idempotent(self) -> None:
        payload = {
            "source_platform": "boss",
            "idempotency_key": "same-request",
            "candidates": [
                {
                    "name": "Alice",
                    "source_candidate_id": "boss-1",
                    "raw_card_text": "Alice trader card",
                }
            ],
        }

        first = self.service.import_candidates(payload)
        second = self.service.import_candidates(payload)

        self.assertEqual(first["batch_id"], second["batch_id"])
        self.assertEqual(len(self.repository.list_batches()), 1)
        self.assertEqual(len(self.repository.list_candidates()), 1)

    def test_blank_updates_do_not_overwrite_existing_master_and_old_snapshot_is_immutable(self) -> None:
        first = self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [
                    {
                        "name": "Alice",
                        "source_candidate_id": "boss-1",
                        "raw_card_text": "Alice first card",
                        "expected_salary": "20k-30k",
                    }
                ],
            }
        )
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [
                    {
                        "name": "",
                        "source_candidate_id": "boss-1",
                        "raw_card_text": "Alice second card",
                        "expected_salary": "",
                    }
                ],
            }
        )

        candidate = dict(self.repository.list_candidates()[0])
        export_rows = self.repository.get_capture_batch_export_rows(first["batch_id"])

        self.assertEqual(candidate["name"], "Alice")
        self.assertEqual(candidate["expected_salary"], "20k-30k")
        self.assertEqual(export_rows[0]["name"], "Alice")
        self.assertEqual(export_rows[0]["expected_salary"], "20k-30k")
        self.assertEqual(export_rows[0]["raw_card_text"], "Alice first card")

    def test_same_name_without_safe_identity_match_is_not_merged(self) -> None:
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [
                    {
                        "name": "Chris",
                        "detail_url": "https://example.com/a",
                        "raw_card_text": "Chris first",
                    },
                    {
                        "name": "Chris",
                        "detail_url": "https://example.com/b",
                        "raw_card_text": "Chris second",
                    },
                ],
            }
        )

        self.assertEqual(len(self.repository.list_candidates()), 2)


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

    def test_candidate_intake_requires_token(self) -> None:
        response = self.client.post(
            "/api/intake/candidates",
            json={"source_platform": "boss", "candidates": [{"raw_card_text": "x"}]},
            headers={"Origin": "http://127.0.0.1:17864"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn(self.token, response.text)

    def test_candidate_intake_and_candidate_queries_work_without_role_binding(self) -> None:
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
                    "name": "Broken",
                    "source_candidate_id": "boss-2",
                },
            ],
        }
        intake = self.client.post(
            "/api/intake/candidates",
            json=payload,
            headers={
                "Origin": "http://127.0.0.1:17864",
                "X-Boss-Local-Token": self.token,
            },
        )

        self.assertEqual(intake.status_code, 200, intake.text)
        result = intake.json()
        self.assertEqual(result["inserted_candidates"], 1)
        self.assertEqual(result["failed_candidates"], 1)
        self.assertEqual(result["failures"][0]["code"], "invalid_candidate")
        self.assertNotIn("Alice card", intake.text)

        candidates = self.client.get("/api/candidates?page=1&page_size=100&unbound_only=true")
        self.assertEqual(candidates.status_code, 200)
        rows = candidates.json()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Alice")
        self.assertEqual(rows[0]["latest_source_job_title"], "证券交易员")
        self.assertEqual(rows[0]["latest_ingest_status"], "new")
        self.assertEqual(rows[0]["latest_batch_role_id"], None)

        batches = self.client.get("/api/capture-batches?page=1&page_size=20&source_platform=boss")
        self.assertEqual(batches.status_code, 200)
        batch_rows = batches.json()["rows"]
        self.assertEqual(len(batch_rows), 1)
        self.assertEqual(batch_rows[0]["total_failed"], 1)
        self.assertEqual(batch_rows[0]["total_new"], 1)

        batch_id = batch_rows[0]["id"]
        batch_candidates = self.client.get(f"/api/capture-batches/{batch_id}/candidates?page=1&page_size=20")
        self.assertEqual(batch_candidates.status_code, 200)
        self.assertEqual(batch_candidates.json()["rows"][0]["name"], "Alice")

    def test_candidate_intake_accepts_bound_role_when_provided(self) -> None:
        repository = CandidateRepository(DatabaseManager(self.data_dir / "boss_local_tool.db"))
        profile = repository.save_job_profile(
            JobProfile(job_title="证券交易员", jd_text="", prompt_text="", status="active")
        )
        repository.db.close_thread_connection()

        response = self.client.post(
            "/api/intake/candidates",
            json={
                "source_platform": "boss",
                "source_job_title": "证券交易员",
                "job_profile_id": profile.id,
                "candidates": [
                    {
                        "name": "Dana",
                        "source_candidate_id": "boss-3",
                        "raw_card_text": "Dana card",
                    }
                ],
            },
            headers={
                "Origin": "http://127.0.0.1:17864",
                "X-Boss-Local-Token": self.token,
            },
        )

        self.assertEqual(response.status_code, 200)
        batch_id = response.json()["batch_id"]
        candidates = self.client.get("/api/candidates?page=1&page_size=100").json()["rows"]
        self.assertEqual(candidates[0]["latest_batch_role_id"], int(profile.id))
        batches = self.client.get("/api/capture-batches?page=1&page_size=20").json()["rows"]
        self.assertEqual(batches[0]["id"], batch_id)

