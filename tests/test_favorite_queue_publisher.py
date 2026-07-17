from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai.prompt_manager import PromptManager
from ai.schemas import ScreeningDecision
from ai.screening_service import ScreeningService
from automation.favorite_queue import NativeFavoriteQueuePublisher
from automation.importer import CardImportService
from automation.parser import CandidateParser
from core.models import ScreeningProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class QueueRatingProvider:
    def screen(self, _system_prompt: str, candidate_text: str) -> ScreeningDecision:
        if "Dana" in candidate_text:
            raise RuntimeError("provider failed")
        rating = (
            "SSR"
            if "Alice" in candidate_text
            else ("SR" if "Bob" in candidate_text or "Eve" in candidate_text else "R")
        )
        return ScreeningDecision(
            rating=rating,
            persona=f"{rating} queue test",
            raw_response=f'{{"rating":"{rating}","persona":"queue test"}}',
        )


class NativeFavoriteQueuePublisherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "favorite_queue.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.importer = CardImportService(self.repository, CandidateParser())

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_completed_initial_screening_publishes_only_eligible_candidates_with_a_locked_snapshot(self) -> None:
        imported = self.importer.import_cards(
            {
                "job_title": "Queue Role",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {
                        "platform": "boss",
                        "raw_card_text": "Alice strong evidence",
                        "name": "Alice",
                        "platform_uid": "visible-alice",
                        "action_platform_uid": "trusted-alice",
                        "raw_identity": {"data-geekid": "trusted-alice"},
                    },
                    {
                        "platform": "boss",
                        "raw_card_text": "Bob good evidence",
                        "name": "Bob",
                        "platform_uid": "visible-bob",
                    },
                    {
                        "platform": "boss",
                        "raw_card_text": "Carol weak evidence",
                        "name": "Carol",
                        "platform_uid": "visible-carol",
                        "action_platform_uid": "trusted-carol",
                        "raw_identity": {"data-geekid": "trusted-carol"},
                    },
                    {
                        "platform": "boss",
                        "raw_card_text": "Dana provider failure",
                        "name": "Dana",
                        "platform_uid": "visible-dana",
                        "action_platform_uid": "trusted-dana",
                        "raw_identity": {"data-geekid": "trusted-dana"},
                    },
                    {
                        "platform": "boss",
                        "raw_card_text": "Eve good evidence",
                        "name": "Eve",
                        "platform_uid": "visible-eve",
                        "action_platform_uid": "trusted-eve",
                        "raw_identity": {"data-geekid": "trusted-eve"},
                    },
                ],
            }
        )
        capture_batch_id = int(imported["batch_id"])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Queue Role",
                jd_text="Queue test",
                prompt_text="Evaluate",
                favorite_eligible_ratings=["SSR", "SR"],
            )
        )
        snapshot = {
            "post_screen_action": "screen_and_favorite",
            "profile_id": int(profile.id),
            "profile_version": int(profile.version),
            "favorite_eligible_ratings": ["SSR", "SR"],
            "favorite_interval_seconds": 5,
            "favorite_max_candidates": 1,
            "source_page_context": {
                "capture_batch_id": capture_batch_id,
                "tab_id": 91,
                "document_id": "source-doc-91",
                "platform": "boss",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
            },
        }
        service = ScreeningService(
            repository=self.repository,
            prompt_manager=PromptManager(Path(self.temp_dir.name) / "prompts"),
            provider=QueueRatingProvider(),
            max_retry_count=0,
            retry_backoff_base_seconds=0,
        )
        screening = service.run(
            profile=profile.to_dict(),
            candidates=self.repository.list_screening_candidates(batch_id=capture_batch_id),
            source_job_title="Queue Role",
            batch_id=capture_batch_id,
            provider_name="fake",
            model="fake-model",
            origin="automation",
            automation_snapshot=snapshot,
        )

        favorite_batch_id = NativeFavoriteQueuePublisher(self.repository).publish(
            int(screening["run_id"])
        )

        self.assertIsNotNone(favorite_batch_id)
        tasks = self.repository.list_native_favorite_tasks(int(favorite_batch_id))
        self.assertEqual(len(tasks), 3)
        self.assertEqual(
            {str(task["status"]) for task in tasks},
            {"pending", "identity_incomplete"},
        )
        claimed = self.repository.claim_next_native_favorite_task(int(favorite_batch_id))
        self.assertEqual(
            claimed["platform_identity"],
            {"attribute": "data-geekid", "value": "trusted-alice"},
        )
        self.assertEqual(claimed["source_page_context"]["tab_id"], 91)
        self.assertEqual(claimed["config_snapshot"], snapshot)
        self.repository.complete_native_favorite_task(
            int(claimed["task_id"]),
            claim_token=str(claimed["claim_token"]),
            status="success",
            attempted=True,
            reason="favorite_management_identity_confirmed",
        )
        self.assertIsNone(
            self.repository.claim_next_native_favorite_task(int(favorite_batch_id))
        )
        remaining = self.repository.list_native_favorite_tasks(int(favorite_batch_id))
        self.assertEqual(sum(str(task["status"]) == "pending" for task in remaining), 1)
        names = {
            str(row["name"]): str(row["rating"])
            for row in self.repository.list_screening_results(int(screening["run_id"]))
        }
        self.assertEqual(names["Carol"], "R")
        dana_id = next(
            int(row["id"])
            for row in self.repository.list_candidates(job_title="Queue Role")
            if str(row["name"]) == "Dana"
        )
        self.assertNotIn(dana_id, [int(task["candidate_id"]) for task in tasks])

    def test_stopped_screening_run_cannot_publish_a_favorite_queue(self) -> None:
        profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Stopped Queue Role",
                jd_text="Queue test",
                prompt_text="Evaluate",
                favorite_eligible_ratings=["SSR"],
            )
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title=profile.job_title,
            batch_id=None,
            provider="fake",
            model="fake-model",
            total_candidates=0,
            origin="automation",
            automation_snapshot={
                "post_screen_action": "screen_and_favorite",
                "favorite_eligible_ratings": ["SSR"],
            },
        )
        self.repository.finalize_screening_run(run_id, "stopped", 0, 0)

        with self.assertRaisesRegex(ValueError, "completed"):
            NativeFavoriteQueuePublisher(self.repository).publish(run_id)

    def test_queue_rejects_non_boss_or_non_recommendation_source_context(self) -> None:
        imported = self.importer.import_cards(
            {
                "job_title": "Source Guard Role",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [{"raw_card_text": "Guard candidate", "name": "Guard"}],
            }
        )
        profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Source Guard Role",
                jd_text="Guard",
                prompt_text="Evaluate",
                favorite_eligible_ratings=["SSR"],
            )
        )
        invalid_contexts = (
            {
                "capture_batch_id": int(imported["batch_id"]),
                "tab_id": 91,
                "document_id": "source-doc-91",
                "platform": "liepin",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
            },
            {
                "capture_batch_id": int(imported["batch_id"]),
                "tab_id": 91,
                "document_id": "source-doc-91",
                "platform": "boss",
                "source_url": "https://www.zhipin.com/web/geek/friend",
            },
        )
        for source_context in invalid_contexts:
            with self.subTest(source_context=source_context):
                run_id = self.repository.create_screening_run(
                    profile_id=int(profile.id),
                    source_job_title=profile.job_title,
                    batch_id=int(imported["batch_id"]),
                    provider="fake",
                    model="fake-model",
                    total_candidates=0,
                    origin="automation",
                    automation_snapshot={
                        "post_screen_action": "screen_and_favorite",
                        "profile_id": int(profile.id),
                        "profile_version": int(profile.version),
                        "favorite_eligible_ratings": ["SSR"],
                        "favorite_interval_seconds": 5,
                        "favorite_max_candidates": 20,
                        "source_page_context": source_context,
                    },
                )
                self.repository.finalize_screening_run(run_id, "completed", 0, 0)
                with self.assertRaisesRegex(ValueError, "BOSS"):
                    NativeFavoriteQueuePublisher(self.repository).publish(run_id)


if __name__ == "__main__":
    unittest.main()
