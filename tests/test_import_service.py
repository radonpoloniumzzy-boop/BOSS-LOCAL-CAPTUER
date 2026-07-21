from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.importer import CardImportService
from automation.parser import CandidateParser
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class CardImportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.service = CardImportService(self.repository, CandidateParser())

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_import_cards_creates_batch_and_candidates(self) -> None:
        result = self.service.import_cards(
            {
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
                    "platform": "boss",
                    "source_tab_id": 91,
                    "source_document_id": "source-doc-91",
                    "source_candidate_documents": [
                        {
                            "frame_id": 7,
                            "document_id": "candidate-doc-7",
                            "frame_url": "https://www.zhipin.com/web/frame/recommend/",
                        }
                    ],
                },
            }
        )
        self.assertEqual(result["parsed_cards"], 1)
        self.assertEqual(result["total_batch_items"], 1)
        self.assertEqual(result["job_title"], "Recruiting Intern")
        self.assertEqual(result["source_url"], "https://www.zhipin.com/web/geek/recommend")
        self.assertTrue(result["automation_requested"])
        self.assertEqual(
            result["source_page_context"],
            {
                "capture_batch_id": int(result["batch_id"]),
                "platform": "boss",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "tab_id": 91,
                "document_id": "source-doc-91",
                "candidate_documents": [
                    {
                        "frame_id": 7,
                        "document_id": "candidate-doc-7",
                        "frame_url": "https://www.zhipin.com/web/frame/recommend/",
                    }
                ],
            },
        )
        self.assertEqual(len(self.repository.list_candidates()), 1)

    def test_collection_run_is_idempotent_and_duplicate_content_does_not_start_screening(self) -> None:
        payload = {
            "job_title": "Recruiting Intern",
            "source_url": "https://www.zhipin.com/web/geek/recommend",
            "cards": [
                {
                    "raw_card_text": "Alice recruiting 10k bachelor",
                    "name": "Alice",
                    "detail_url": "https://www.zhipin.com/geek/1",
                }
            ],
            "meta": {
                "collection_run_id": "collect-run-1",
                "automation_requested": True,
                "platform": "boss",
                "source_document_id": "document-1",
                "source_frame_id": 7,
                "source_frame_url": "https://www.zhipin.com/web/frame/recommend/",
            },
        }

        first = self.service.import_cards(payload)
        replay = self.service.import_cards(payload)
        duplicate = self.service.import_cards(
            {
                **payload,
                "meta": {
                    **payload["meta"],
                    "collection_run_id": "collect-run-2",
                    "source_document_id": "document-2",
                },
            }
        )

        self.assertTrue(first["automation_allowed"])
        self.assertFalse(first["duplicate_content"])
        self.assertTrue(first["content_fingerprint"].startswith("sha256:"))
        self.assertEqual(replay["batch_id"], first["batch_id"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(replay["automation_allowed"])
        self.assertEqual(duplicate["batch_id"], first["batch_id"])
        self.assertTrue(duplicate["duplicate_content"])
        self.assertEqual(duplicate["duplicate_of_batch_id"], first["batch_id"])
        self.assertFalse(duplicate["automation_allowed"])
        self.assertEqual(len(self.repository.list_batches()), 1)

    def test_collection_run_id_cannot_be_reused_for_different_content(self) -> None:
        base = {
            "job_title": "Recruiting Intern",
            "source_url": "https://www.zhipin.com/web/geek/recommend",
            "meta": {"collection_run_id": "collect-run-conflict"},
        }
        self.service.import_cards(
            {**base, "cards": [{"name": "Alice", "raw_card_text": "Alice recruiting"}]}
        )

        with self.assertRaisesRegex(ValueError, "不同内容"):
            self.service.import_cards(
                {**base, "cards": [{"name": "Bob", "raw_card_text": "Bob engineering"}]}
            )

    def test_parse_count_mismatch_blocks_automation(self) -> None:
        result = self.service.import_cards(
            {
                "job_title": "Recruiting Intern",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {"name": "Alice", "raw_card_text": "Alice recruiting"},
                    {"name": "Alice", "raw_card_text": "Alice recruiting"},
                ],
                "meta": {
                    "collection_run_id": "collect-parse-mismatch",
                    "automation_requested": True,
                },
            }
        )

        self.assertEqual(result["received_cards"], 2)
        self.assertEqual(result["parsed_cards"], 1)
        self.assertFalse(result["automation_allowed"])
        self.assertEqual(result["validation_error"], "import_count_mismatch")

    def test_only_immediately_previous_batch_is_used_for_duplicate_warning(self) -> None:
        def collect(run_id: str, name: str) -> dict[str, object]:
            return self.service.import_cards(
                {
                    "job_title": "Recruiting Intern",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "cards": [{"name": name, "raw_card_text": f"{name} recruiting"}],
                    "meta": {
                        "collection_run_id": run_id,
                        "automation_requested": True,
                    },
                }
            )

        first = collect("collect-a", "Alice")
        second = collect("collect-b", "Bob")
        third = collect("collect-c", "Alice")

        self.assertNotEqual(first["batch_id"], second["batch_id"])
        self.assertNotEqual(third["batch_id"], first["batch_id"])
        self.assertTrue(third["automation_allowed"])

    def test_import_liepin_cards_reuses_existing_candidate_model(self) -> None:
        result = self.service.import_cards(
            {
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
        self.assertEqual(result["parsed_cards"], 1)
        self.assertEqual(result["total_batch_items"], 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_url"], "https://lpt.liepin.com/recommend")
        self.assertEqual(candidates[0]["candidate_key"], "platform:liepin:resume-1")

    def test_imported_boss_identity_is_available_from_candidate_detail(self) -> None:
        self.service.import_cards(
            {
                "job_title": "量化研究员",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {
                        "platform": "boss",
                        "raw_card_text": "候选人甲\n量化研究\n硕士",
                        "name": "候选人甲",
                        "detail_url": "https://www.zhipin.com/web/geek/detail/example",
                        "platform_uid": "encrypted-geek-1",
                        "action_platform_uid": "encrypted-geek-1",
                        "friend_id": "friend-1",
                        "friend_source": "recommend",
                        "security_id": "security-1",
                        "lid": "lid-1",
                        "job_context_id": "job-1",
                        "raw_identity": {
                            "data-geek-id": "encrypted-geek-1",
                        },
                        "raw_action_context": {"data-friend-id": "friend-1"},
                    }
                ],
            }
        )

        candidate_id = int(self.repository.list_candidates()[0]["id"])
        detail = self.repository.get_candidate_detail(candidate_id)

        self.assertIsNotNone(detail)
        self.assertEqual(
            detail["platform_identities"],
            [
                {
                    "platform": "boss",
                    "platform_uid": "encrypted-geek-1",
                    "detail_url": "https://www.zhipin.com/web/geek/detail/example",
                    "raw_identity": {
                        "data-geek-id": "encrypted-geek-1",
                    },
                }
            ],
        )
        self.assertEqual(len(detail["platform_action_contexts"]), 1)
        action_context = detail["platform_action_contexts"][0]
        self.assertEqual(action_context["capture_batch_id"], 1)
        self.assertEqual(action_context["platform"], "boss")
        self.assertEqual(action_context["platform_uid"], "encrypted-geek-1")
        self.assertEqual(action_context["friend_id"], "friend-1")
        self.assertEqual(action_context["job_context_id"], "job-1")
        self.assertEqual(
            action_context["raw_action_context"], {"data-friend-id": "friend-1"}
        )
        self.assertTrue(action_context["observed_at"])

    def test_import_keeps_distinct_boss_action_contexts_for_the_same_candidate(self) -> None:
        base_card = {
            "platform": "boss",
            "raw_card_text": "候选人甲\n量化研究\n硕士",
            "name": "候选人甲",
            "detail_url": "https://www.zhipin.com/web/geek/detail/example",
            "platform_uid": "encrypted-geek-1",
            "action_platform_uid": "encrypted-geek-1",
            "friend_id": "friend-1",
            "friend_source": "recommend",
            "security_id": "security-1",
            "lid": "lid-1",
        }
        for job_context_id in ("job-1", "job-2"):
            self.service.import_cards(
                {
                    "job_title": "量化研究员",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "cards": [
                        {
                            **base_card,
                            "action_platform_uid": f"trusted-{job_context_id}",
                            "job_context_id": job_context_id,
                        }
                    ],
                }
            )

        candidate_id = int(self.repository.list_candidates()[0]["id"])
        detail = self.repository.get_candidate_detail(candidate_id)

        self.assertEqual(
            [context["job_context_id"] for context in detail["platform_action_contexts"]],
            ["job-1", "job-2"],
        )
        self.assertEqual(
            [identity["platform_uid"] for identity in detail["platform_identities"]],
            ["trusted-job-1", "trusted-job-2"],
        )


if __name__ == "__main__":
    unittest.main()
