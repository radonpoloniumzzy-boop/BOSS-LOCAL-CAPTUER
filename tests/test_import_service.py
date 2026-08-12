from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from automation.importer import CardImportService
from automation.parser import CandidateParser
from core.models import JobProfile, RecruitmentTask
from storage.db import DatabaseManager
from storage.repository import CandidateRepository, IdempotencyConflictError


class CardImportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.service = CardImportService(self.repository, CandidateParser())

    def tearDown(self) -> None:
        self.db.close_all_connections()
        self.temp_dir.cleanup()

    def _assert_thread_connection_closed_and_db_writable(self) -> None:
        self.assertIsNone(getattr(self.db._local, "connection", None))
        batch = self.repository.create_batch("Followup", "https://example.test/followup")
        self.assertGreater(int(batch.id), 0)
        self.db.close_thread_connection()

    def _assert_batch_count(self, expected: int) -> None:
        probe_db = DatabaseManager(self.db.db_path)
        try:
            probe_repository = CandidateRepository(probe_db)
            self.assertEqual(len(probe_repository.list_batches()), expected)
        finally:
            probe_db.close_all_connections()

    def test_import_cards_creates_batch_and_candidates(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(
                job_title="Recruiting Intern",
                jd_text="Recruiting support",
                prompt_text="Screen recruiting experience",
                status="active",
            )
        )
        result = self.service.import_cards(
            {
                "job_profile_id": profile.id,
                "job_title": "Recruiting Intern",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {
                        "raw_card_text": "Alice recruiting 10k bachelor",
                        "name": "Alice",
                        "expected_salary": "10k-12k",
                        "work_experience_text": "1 year recruiting",
                        "education_text": "Bachelor",
                        "detail_url": "https://www.zhipin.com/geek/1",
                    },
                    {
                        "raw_card_text": "Alice recruiting 10k bachelor",
                        "name": "Alice",
                        "expected_salary": "10k-12k",
                        "work_experience_text": "1 year recruiting",
                        "education_text": "Bachelor",
                        "detail_url": "https://www.zhipin.com/geek/1",
                    },
                ],
                "meta": {
                    "rounds_completed": 5,
                    "unique_cards": 1,
                    "automation_requested": True,
                },
            }
        )

        self.assertEqual(result["parsed_cards"], 2)
        self.assertEqual(result["total_batch_items"], 1)
        self.assertEqual(result["skipped_candidates"], 1)
        self.assertEqual(result["job_title"], "Recruiting Intern")
        self.assertEqual(result["source_url"], "https://www.zhipin.com/web/geek/recommend")
        self.assertTrue(result["automation_requested"])
        self.assertEqual(
            result["received_cards"],
            result["inserted_candidates"]
            + result["updated_candidates"]
            + result["skipped_candidates"]
            + result["failed_candidates"],
        )
        self.assertEqual(len(self.repository.list_candidates()), 1)

    def test_import_liepin_cards_reuses_existing_candidate_model(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(
                job_title="猎聘推荐人才",
                jd_text="猎聘人才采集",
                prompt_text="筛选人才",
                status="active",
            )
        )
        result = self.service.import_cards(
            {
                "job_profile_id": profile.id,
                "job_title": "猎聘推荐人才",
                "source_url": "https://lpt.liepin.com/recommend",
                "cards": [
                    {
                        "platform": "liepin",
                        "raw_card_text": "张三\nJava开发工程师\n20-35k\n5年经验\n本科\nSpring Cloud",
                        "name": "张三",
                        "expected_salary": "20-35k",
                        "work_experience_text": "5年经验",
                        "education_text": "本科",
                        "tags_text": ["Java", "Spring Cloud"],
                        "detail_url": "https://lpt.liepin.com/resume/resume-1",
                        "platform_uid": "liepin:resume-1",
                    },
                    {
                        "platform": "liepin",
                        "raw_card_text": "张三\nJava开发工程师\n20-35k\n5年经验\n本科\nSpring Cloud",
                        "name": "张三",
                        "expected_salary": "20-35k",
                        "work_experience_text": "5年经验",
                        "education_text": "本科",
                        "tags_text": ["Java", "Spring Cloud"],
                        "detail_url": "https://lpt.liepin.com/resume/resume-1",
                        "platform_uid": "liepin:resume-1",
                    },
                ],
                "meta": {"platform": "liepin", "rounds_completed": 3, "unique_cards": 1},
            }
        )

        candidates = self.repository.list_candidates()
        self.assertEqual(result["parsed_cards"], 2)
        self.assertEqual(result["total_batch_items"], 1)
        self.assertEqual(result["skipped_candidates"], 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_url"], "https://lpt.liepin.com/recommend")
        self.assertEqual(candidates[0]["candidate_key"], "platform:liepin:resume-1")

    def test_import_batch_links_matching_job_profile_without_changing_candidate_identity(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(
                job_title="招聘实习生",
                jd_text="负责招聘支持",
                prompt_text="筛选招聘经验",
                status="active",
            )
        )

        result = self.service.import_cards(
            {
                "job_title": "招聘实习生",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [{"raw_card_text": "李四 招聘实习 本科", "name": "李四"}],
            }
        )
        batch = next(
            row for row in self.repository.list_batches() if int(row["id"]) == int(result["batch_id"])
        )

        self.assertEqual(batch["role_id"], profile.id)

    def test_explicit_job_profile_id_survives_renamed_source_title(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="当前统一名称", jd_text="", prompt_text="", status="active")
        )

        result = self.service.import_cards(
            {
                "job_profile_id": profile.id,
                "job_title": "插件缓存的旧名称",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [{"raw_card_text": "王五 五年招聘经验", "name": "王五"}],
            }
        )
        batch = next(
            row for row in self.repository.list_batches() if int(row["id"]) == int(result["batch_id"])
        )

        self.assertEqual(batch["role_id"], profile.id)
        self.assertEqual(result["job_profile_id"], profile.id)
        self.assertEqual(batch["job_title"], "插件缓存的旧名称")

    def test_import_rejects_inactive_explicit_job_profile(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="暂停岗位", jd_text="", prompt_text="", status="active")
        )
        self.repository.set_job_profile_status(int(profile.id), "paused")

        with self.assertRaisesRegex(ValueError, "不是招聘中"):
            self.service.import_cards(
                {
                    "job_profile_id": profile.id,
                    "job_title": "暂停岗位",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "cards": [{"raw_card_text": "赵六 招聘经验", "name": "赵六"}],
                }
            )

        with self.assertRaisesRegex(ValueError, "不是招聘中"):
            self.service.import_cards(
                {
                    "job_title": "暂停岗位",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "cards": [{"raw_card_text": "钱七 招聘经验", "name": "钱七"}],
                }
            )

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

    def test_only_name_candidates_do_not_merge(self) -> None:
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [
                    {"name": "张伟", "raw_card_text": "张伟 first card"},
                    {"name": "张伟", "raw_card_text": "张伟 second card"},
                ],
            }
        )

        self.assertEqual(len(self.repository.list_candidates()), 2)

    def test_same_stable_platform_uid_updates_same_candidate(self) -> None:
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [
                    {
                        "name": "Alice",
                        "source_candidate_id": "boss-1",
                        "raw_card_text": "Alice first card",
                    }
                ],
            }
        )
        result = self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [
                    {
                        "name": "Alice Updated",
                        "source_candidate_id": "boss-1",
                        "raw_card_text": "Alice second card",
                    }
                ],
            }
        )

        candidates = [dict(row) for row in self.repository.list_candidates()]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(result["updated_candidates"], 1)
        self.assertEqual(candidates[0]["name"], "Alice Updated")

    def test_different_platforms_with_same_source_candidate_id_do_not_merge(self) -> None:
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [{"source_candidate_id": "same-id", "raw_card_text": "boss card"}],
            }
        )
        self.service.import_candidates(
            {
                "source_platform": "liepin",
                "candidates": [{"source_candidate_id": "same-id", "raw_card_text": "liepin card"}],
            }
        )

        self.assertEqual(len(self.repository.list_candidates()), 2)

    def test_unknown_platform_same_id_does_not_merge(self) -> None:
        self.service.import_candidates(
            {
                "source_platform": "unknown",
                "candidates": [{"source_candidate_id": "same-id", "raw_card_text": "unknown card 1"}],
            }
        )
        self.service.import_candidates(
            {
                "source_platform": "unknown",
                "candidates": [{"source_candidate_id": "same-id", "raw_card_text": "unknown card 2"}],
            }
        )

        self.assertEqual(len(self.repository.list_candidates()), 2)

    def test_explicit_job_profile_id_creates_formal_role_binding(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="证券交易员", jd_text="", prompt_text="", status="active")
        )

        self.service.import_candidates(
            {
                "source_platform": "boss",
                "job_profile_id": profile.id,
                "source_job_title": "证券交易员",
                "candidates": [
                    {"source_candidate_id": "boss-1", "raw_card_text": "Alice card", "name": "Alice"}
                ],
            }
        )

        candidate = dict(self.repository.list_candidates()[0])
        matches = self.repository.list_candidate_role_matches(role_id=int(profile.id))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], candidate["id"])

    def test_same_named_source_job_title_does_not_auto_bind_role(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="证券交易员", jd_text="", prompt_text="", status="active")
        )

        self.service.import_candidates(
            {
                "source_platform": "boss",
                "source_job_title": "证券交易员",
                "candidates": [
                    {"source_candidate_id": "boss-1", "raw_card_text": "Alice card", "name": "Alice"}
                ],
            }
        )

        self.assertEqual(self.repository.list_candidate_role_matches(role_id=int(profile.id)), [])

    def test_one_candidate_can_bind_multiple_roles(self) -> None:
        first_role = self.repository.save_job_profile(
            JobProfile(job_title="证券交易员", jd_text="", prompt_text="", status="active")
        )
        second_role = self.repository.save_job_profile(
            JobProfile(job_title="量化交易员", jd_text="", prompt_text="", status="active")
        )

        self.service.import_candidates(
            {
                "source_platform": "boss",
                "job_profile_id": first_role.id,
                "idempotency_key": "role-one",
                "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
            }
        )
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "job_profile_id": second_role.id,
                "idempotency_key": "role-two",
                "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card second"}],
            }
        )

        rows = self.repository.list_candidate_role_matches()
        self.assertEqual(len(rows), 2)

    def test_concurrent_idempotent_same_payload_creates_one_batch(self) -> None:
        payload = {
            "source_platform": "boss",
            "idempotency_key": "same-request",
            "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
        }
        barrier = threading.Barrier(2)

        def run_import() -> dict[str, object]:
            barrier.wait(timeout=5)
            return self.service.import_candidates(payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _value: run_import(), range(2)))

        self.assertEqual(first["batch_id"], second["batch_id"])
        self.assertEqual(len(self.repository.list_batches()), 1)
        self.assertEqual(len(self.repository.list_candidates()), 1)
        batch_id = int(first["batch_id"])
        batch_rows = self.repository.page_capture_batch_candidates(batch_id)["rows"]
        self.assertEqual(len(batch_rows), 1)

    def test_concurrent_idempotent_different_payload_conflicts_cleanly(self) -> None:
        barrier = threading.Barrier(2)
        results: list[object] = []
        payloads = [
            {
                "source_platform": "boss",
                "idempotency_key": "same-request",
                "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
            },
            {
                "source_platform": "boss",
                "idempotency_key": "same-request",
                "candidates": [{"source_candidate_id": "boss-2", "raw_card_text": "Bob card"}],
            },
        ]

        def run_import(payload: dict[str, object]) -> object:
            try:
                barrier.wait(timeout=5)
                return self.service.import_candidates(payload)
            except Exception as exc:  # pragma: no cover - asserted below
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results.extend(pool.map(run_import, payloads))

        successes = [result for result in results if isinstance(result, dict)]
        conflicts = [result for result in results if isinstance(result, IdempotencyConflictError)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(len(self.repository.list_batches()), 1)

    def test_repeated_explicit_role_intake_does_not_roll_back_existing_progress(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="Trader", jd_text="", prompt_text="", status="active")
        )
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "job_profile_id": profile.id,
                "candidates": [
                    {"source_candidate_id": "boss-1", "raw_card_text": "Alice first card", "name": "Alice"}
                ],
            }
        )
        candidate = dict(self.repository.list_candidates()[0])
        self.repository.upsert_candidate_role_match(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            match_status="screened",
            recruitment_status="contacted",
        )

        self.service.import_candidates(
            {
                "source_platform": "boss",
                "job_profile_id": profile.id,
                "candidates": [
                    {"source_candidate_id": "boss-1", "raw_card_text": "Alice second card", "name": "Alice Updated"}
                ],
            }
        )

        match = self.repository.list_candidate_role_matches(role_id=int(profile.id))[0]
        self.assertEqual(match["match_status"], "screened")
        self.assertEqual(match["recruitment_status"], "contacted")

    def test_atomic_role_binding_failure_rolls_back_candidates_snapshots_and_matches(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="Atomic Trader", jd_text="", prompt_text="", status="active")
        )
        original = self.repository._ensure_candidate_role_match_exists
        calls = 0

        def fail_on_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("bind failed")
            return original(*args, **kwargs)

        with patch.object(
            self.repository,
            "_ensure_candidate_role_match_exists",
            side_effect=fail_on_second,
        ):
            with self.assertRaisesRegex(RuntimeError, "bind failed"):
                self.service.import_candidates(
                    {
                        "source_platform": "boss",
                        "job_profile_id": profile.id,
                        "candidates": [
                            {"source_candidate_id": "boss-1", "raw_card_text": "Alice card"},
                            {"source_candidate_id": "boss-2", "raw_card_text": "Bob card"},
                        ],
                    }
                )

        self.assertEqual(len(self.repository.list_candidates()), 0)
        self.assertEqual(len(self.repository.list_candidate_role_matches()), 0)
        batches = self.repository.list_batches()
        self.assertEqual(len(batches), 1)
        batch_id = int(batches[0]["id"])
        self.assertEqual(batches[0]["status"], "failed")
        self.assertEqual(int(batches[0]["total_failed"]), 2)
        self.assertEqual(self.repository.page_capture_batch_candidates(batch_id)["total"], 0)

    def test_source_candidate_id_with_colon_is_namespaced_per_platform(self) -> None:
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [{"source_candidate_id": "user:123", "raw_card_text": "boss card"}],
            }
        )
        self.service.import_candidates(
            {
                "source_platform": "liepin",
                "candidates": [{"source_candidate_id": "user:123", "raw_card_text": "liepin card"}],
            }
        )

        self.assertEqual(len(self.repository.list_candidates()), 2)

    def test_mismatched_prefixed_source_candidate_id_does_not_cross_merge(self) -> None:
        self.service.import_candidates(
            {
                "source_platform": "liepin",
                "candidates": [{"source_candidate_id": "123", "raw_card_text": "liepin card"}],
            }
        )
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [{"source_candidate_id": "liepin:123", "raw_card_text": "boss card"}],
            }
        )

        self.assertEqual(len(self.repository.list_candidates()), 2)

    def test_same_platform_prefixed_source_candidate_id_still_deduplicates(self) -> None:
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [{"source_candidate_id": "boss:123", "raw_card_text": "first card"}],
            }
        )
        result = self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [{"source_candidate_id": "boss:123", "raw_card_text": "second card"}],
            }
        )

        self.assertEqual(len(self.repository.list_candidates()), 1)
        self.assertEqual(result["updated_candidates"], 1)

    def test_structured_source_candidate_id_does_not_mix_with_explicit_platform_uid(self) -> None:
        self.service.import_cards(
            {
                "job_title": "Boss 推荐牛人",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [{"platform": "boss", "platform_uid": "boss:123", "raw_card_text": "extension card"}],
            }
        )
        self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [{"source_candidate_id": "boss:123", "raw_card_text": "web card"}],
            }
        )

        self.assertEqual(len(self.repository.list_candidates()), 2)

    def test_import_cards_statistics_are_conserved_for_new_update_skip_and_fail(self) -> None:
        self.service.import_cards(
            {
                "job_title": "Recruiting Intern",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [{"platform": "boss", "platform_uid": "seed-1", "raw_card_text": "seed card"}],
            }
        )
        result = self.service.import_cards(
            {
                "job_title": "Recruiting Intern",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {"platform": "boss", "platform_uid": "new-1", "raw_card_text": "new card"},
                    {"platform": "boss", "platform_uid": "new-1", "raw_card_text": "new card duplicate"},
                    "invalid",
                    {"platform": "boss", "platform_uid": "seed-1", "raw_card_text": "seed updated"},
                ],
            }
        )

        self.assertEqual(result["received_cards"], 4)
        self.assertEqual(result["inserted_candidates"], 1)
        self.assertEqual(result["updated_candidates"], 1)
        self.assertEqual(result["skipped_candidates"], 1)
        self.assertEqual(result["failed_candidates"], 1)
        self.assertEqual(
            result["received_cards"],
            result["inserted_candidates"]
            + result["updated_candidates"]
            + result["skipped_candidates"]
            + result["failed_candidates"],
        )
        batch = self.repository.get_capture_batch(int(result["batch_id"]))
        assert batch is not None
        self.assertEqual(int(batch["total_collected"]), 4)
        self.assertEqual(int(batch["total_new"]), 1)
        self.assertEqual(int(batch["total_updated"]), 1)
        self.assertEqual(int(batch["total_skipped"]), 1)
        self.assertEqual(int(batch["total_failed"]), 1)

    def test_idempotent_reuse_closes_thread_connection(self) -> None:
        payload = {
            "source_platform": "boss",
            "idempotency_key": "reuse-request",
            "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
        }

        self.service.import_candidates(payload)
        self.assertIsNone(getattr(self.db._local, "connection", None))
        self.service.import_candidates(payload)
        self.assertIsNone(getattr(self.db._local, "connection", None))

    def test_idempotency_conflict_rolls_back_transaction_and_allows_followup_write(self) -> None:
        connection = self.db.get_connection()
        self.repository.claim_intake_batch(
            "Trader",
            "https://example.test/boss",
            request_id="conflict-key",
            request_payload_hash="hash-one",
            source_platform="boss",
        )

        with self.assertRaises(IdempotencyConflictError):
            self.repository.claim_intake_batch(
                "Trader",
                "https://example.test/boss",
                request_id="conflict-key",
                request_payload_hash="hash-two",
                source_platform="boss",
            )

        self.assertFalse(connection.in_transaction)
        self.db.close_thread_connection()

        second_db = DatabaseManager(Path(self.temp_dir.name) / "test.db")
        second_repository = CandidateRepository(second_db)
        created = second_repository.create_batch("Followup", "https://example.test/next")
        self.assertGreater(int(created.id), 0)
        second_db.close_all_connections()

    def test_import_cards_invalid_job_profile_id_releases_connection_and_creates_no_batch(self) -> None:
        with self.assertRaises(ValueError):
            self.service.import_cards(
                {
                    "job_profile_id": 999999,
                    "job_title": "Missing Role",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "cards": [{"raw_card_text": "Alice card", "name": "Alice"}],
                }
            )

        self._assert_batch_count(0)
        self._assert_thread_connection_closed_and_db_writable()

    def test_import_cards_paused_matching_title_releases_connection_and_creates_no_batch(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="Paused Role", jd_text="", prompt_text="", status="active")
        )
        self.repository.set_job_profile_status(int(profile.id), "paused")

        with self.assertRaises(ValueError):
            self.service.import_cards(
                {
                    "job_title": "Paused Role",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "cards": [{"raw_card_text": "Alice card", "name": "Alice"}],
                }
            )

        self._assert_batch_count(0)
        self._assert_thread_connection_closed_and_db_writable()

    def test_import_candidates_missing_job_profile_releases_connection_and_creates_no_batch(self) -> None:
        with self.assertRaises(ValueError):
            self.service.import_candidates(
                {
                    "source_platform": "boss",
                    "job_profile_id": 999999,
                    "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
                }
            )

        self._assert_batch_count(0)
        self._assert_thread_connection_closed_and_db_writable()

    def test_import_candidates_paused_job_profile_releases_connection_and_creates_no_batch(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(job_title="Paused Candidate Role", jd_text="", prompt_text="", status="active")
        )
        self.repository.set_job_profile_status(int(profile.id), "paused")

        with self.assertRaises(ValueError):
            self.service.import_candidates(
                {
                    "source_platform": "boss",
                    "job_profile_id": profile.id,
                    "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
                }
            )

        self._assert_batch_count(0)
        self._assert_thread_connection_closed_and_db_writable()

    def test_import_candidates_task_mismatch_releases_connection_and_creates_no_batch(self) -> None:
        first_role = self.repository.save_job_profile(
            JobProfile(job_title="First Role", jd_text="", prompt_text="", status="active")
        )
        second_role = self.repository.save_job_profile(
            JobProfile(job_title="Second Role", jd_text="", prompt_text="", status="active")
        )
        task = self.repository.save_recruitment_task(
            RecruitmentTask(
                name="Role Task",
                role_id=int(first_role.id),
                platform="boss",
                source_url="https://www.zhipin.com/web/geek/recommend",
            )
        )
        self.repository.set_recruitment_task_status(int(task.id), "running")

        with self.assertRaises(ValueError):
            self.service.import_candidates(
                {
                    "source_platform": "boss",
                    "job_profile_id": second_role.id,
                    "recruitment_task_id": task.id,
                    "candidates": [{"source_candidate_id": "boss-1", "raw_card_text": "Alice card"}],
                }
            )

        self._assert_batch_count(0)
        self._assert_thread_connection_closed_and_db_writable()

    def test_raw_source_candidate_id_and_explicit_platform_uid_merge_when_semantically_same(self) -> None:
        self.service.import_cards(
            {
                "job_title": "Boss 推荐牛人",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [{"platform": "boss", "platform_uid": "boss:123", "raw_card_text": "extension card"}],
            }
        )
        result = self.service.import_candidates(
            {
                "source_platform": "boss",
                "candidates": [{"source_candidate_id": "123", "raw_card_text": "web card"}],
            }
        )

        self.assertEqual(len(self.repository.list_candidates()), 1)
        self.assertEqual(result["updated_candidates"], 1)

    def test_import_cards_reports_partial_status_and_unique_candidates(self) -> None:
        self.service.import_cards(
            {
                "job_title": "Recruiting Intern",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [{"platform": "boss", "platform_uid": "seed-1", "raw_card_text": "seed card"}],
            }
        )
        result = self.service.import_cards(
            {
                "job_title": "Recruiting Intern",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {"platform": "boss", "platform_uid": "new-1", "raw_card_text": "new card"},
                    {"platform": "boss", "platform_uid": "new-1", "raw_card_text": "new card duplicate"},
                    "invalid",
                    {"platform": "boss", "platform_uid": "seed-1", "raw_card_text": "seed updated"},
                ],
            }
        )

        self.assertEqual(result["received_cards"], 4)
        self.assertEqual(result["inserted_candidates"], 1)
        self.assertEqual(result["updated_candidates"], 1)
        self.assertEqual(result["skipped_candidates"], 1)
        self.assertEqual(result["failed_candidates"], 1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["total_unique"], 2)
        self.assertEqual(result["total_batch_items"], 2)
        batch = self.repository.get_capture_batch(int(result["batch_id"]))
        assert batch is not None
        self.assertEqual(str(batch["status"]), "partial")

    def test_import_cards_all_valid_records_finish_completed(self) -> None:
        result = self.service.import_cards(
            {
                "job_title": "Recruiting Intern",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {"platform": "boss", "platform_uid": "boss:1", "raw_card_text": "first card"},
                    {"platform": "boss", "platform_uid": "boss:2", "raw_card_text": "second card"},
                ],
            }
        )

        batch = self.repository.get_capture_batch(int(result["batch_id"]))
        assert batch is not None
        self.assertEqual(result["status"], "completed")
        self.assertEqual(str(batch["status"]), "completed")
        self.assertEqual(result["failed_candidates"], 0)
        self.assertEqual(result["total_unique"], 2)

    def test_import_cards_unhandled_exception_marks_batch_failed(self) -> None:
        with patch.object(
            self.repository,
            "upsert_batch_candidates",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                self.service.import_cards(
                    {
                        "job_title": "Recruiting Intern",
                        "source_url": "https://www.zhipin.com/web/geek/recommend",
                        "cards": [{"platform": "boss", "platform_uid": "boss:1", "raw_card_text": "first card"}],
                    }
                )

        batches = self.repository.list_batches()
        self.assertEqual(len(batches), 1)
        self.assertEqual(str(batches[0]["status"]), "failed")


if __name__ == "__main__":
    unittest.main()
