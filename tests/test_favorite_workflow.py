from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.importer import CardImportService
from automation.parser import CandidateParser
from core.models import ScreeningProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class NativeFavoriteWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "favorite.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.import_service = CardImportService(self.repository, CandidateParser())

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_claim_and_unknown_result_are_persistent_and_not_reclaimed(self) -> None:
        imported = self.import_service.import_cards(
            {
                "job_title": "量化研究员",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {
                        "platform": "boss",
                        "raw_card_text": "候选人甲\n量化研究\n硕士",
                        "name": "候选人甲",
                        "platform_uid": "geek-visible-1",
                        "action_platform_uid": "trusted-geek-1",
                        "raw_identity": {"data-geekid": "trusted-geek-1"},
                    }
                ],
            }
        )
        capture_batch_id = int(imported["batch_id"])
        candidate_id = int(self.repository.list_candidates()[0]["id"])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="量化研究员", jd_text="研究能力", prompt_text="screen")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="量化研究员",
            batch_id=capture_batch_id,
            provider="fake",
            model="fake-model",
            total_candidates=1,
            origin="automation",
        )

        favorite_batch_id = self.repository.create_native_favorite_batch(
            capture_batch_id=capture_batch_id,
            screening_run_id=run_id,
            role_id=int(profile.id),
            source_page_url="https://www.zhipin.com/web/geek/recommend",
            source_page_context={"capture_batch_id": capture_batch_id, "tab_id": 91},
            config_snapshot={"eligible_ratings": ["SSR"], "max_candidates": 20},
            tasks=[
                {
                    "candidate_id": candidate_id,
                    "platform_identity": {
                        "attribute": "data-geekid",
                        "value": "trusted-geek-1",
                    },
                }
            ],
        )

        claimed = self.repository.claim_next_native_favorite_task(
            favorite_batch_id,
            worker_id="extension-tab-91",
        )

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(
            claimed["platform_identity"],
            {"attribute": "data-geekid", "value": "trusted-geek-1"},
        )
        self.assertEqual(claimed["source_page_context"]["tab_id"], 91)
        self.assertTrue(claimed["claim_token"])
        self.assertIsNone(self.repository.claim_next_native_favorite_task(favorite_batch_id))

        with self.assertRaisesRegex(ValueError, "claim token"):
            self.repository.complete_native_favorite_task(
                int(claimed["task_id"]),
                claim_token="wrong-token",
                status="unknown",
                attempted=True,
                reason="favorite_control_click_uncertain",
                method="native_detail_control",
            )

        with self.assertRaisesRegex(ValueError, "requires an attempted write"):
            self.repository.complete_native_favorite_task(
                int(claimed["task_id"]),
                claim_token=str(claimed["claim_token"]),
                status="success",
                attempted=False,
                reason="favorite_management_identity_confirmed",
                method="native_detail_control",
            )

        completed = self.repository.complete_native_favorite_task(
            int(claimed["task_id"]),
            claim_token=str(claimed["claim_token"]),
            status="unknown",
            attempted=True,
            reason="favorite_control_click_uncertain",
            method="native_detail_control",
        )

        self.assertEqual(completed["status"], "unknown")
        self.assertEqual(completed["attempt_count"], 1)
        self.assertIsNone(self.repository.claim_next_native_favorite_task(favorite_batch_id))
        attempts = self.repository.list_native_favorite_attempts(int(claimed["task_id"]))
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "unknown")
        self.assertEqual(attempts[0]["reason"], "favorite_control_click_uncertain")

        next_capture = self.import_service.import_cards(
            {
                "job_title": "量化研究员",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {
                        "platform": "boss",
                        "raw_card_text": "候选人甲\n量化研究\n硕士",
                        "name": "候选人甲",
                        "platform_uid": "geek-visible-1",
                        "action_platform_uid": "trusted-geek-1",
                        "raw_identity": {"data-geekid": "trusted-geek-1"},
                    }
                ],
            }
        )
        next_capture_batch_id = int(next_capture["batch_id"])
        next_run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="量化研究员",
            batch_id=next_capture_batch_id,
            provider="fake",
            model="fake-model",
            total_candidates=1,
            origin="automation",
        )
        next_favorite_batch_id = self.repository.create_native_favorite_batch(
            capture_batch_id=next_capture_batch_id,
            screening_run_id=next_run_id,
            role_id=int(profile.id),
            source_page_url="https://www.zhipin.com/web/geek/recommend",
            source_page_context={"capture_batch_id": next_capture_batch_id, "tab_id": 91},
            config_snapshot={"eligible_ratings": ["SSR"], "max_candidates": 20},
            tasks=[
                {
                    "candidate_id": candidate_id,
                    "platform_identity": {
                        "attribute": "data-geekid",
                        "value": "trusted-geek-1",
                    },
                }
            ],
        )

        self.assertIsNone(
            self.repository.claim_next_native_favorite_task(next_favorite_batch_id)
        )
        next_tasks = self.repository.list_native_favorite_tasks(next_favorite_batch_id)
        self.assertEqual(len(next_tasks), 1)
        self.assertEqual(next_tasks[0]["status"], "unknown")
        self.assertEqual(next_tasks[0]["error_reason"], "prior_unknown_requires_manual_resolution")


if __name__ == "__main__":
    unittest.main()
