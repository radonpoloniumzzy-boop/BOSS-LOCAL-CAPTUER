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

    def _create_favorite_batch(
        self,
        suffix: str,
        platform_identities: list[str],
    ) -> tuple[int, list[int]]:
        job_title = f"Favorite test {suffix}"
        imported = self.import_service.import_cards(
            {
                "job_title": job_title,
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "cards": [
                    {
                        "platform": "boss",
                        "raw_card_text": f"Candidate {suffix}-{index}",
                        "name": f"Candidate {suffix}-{index}",
                        "platform_uid": f"visible-{suffix}-{index}",
                        "action_platform_uid": identity,
                        "raw_identity": {"data-geekid": identity},
                    }
                    for index, identity in enumerate(platform_identities)
                ],
            }
        )
        capture_batch_id = int(imported["batch_id"])
        rows = self.repository.list_candidates(job_title=job_title)
        candidate_by_visible_uid = {
            str(row["platform_uid"]): int(row["id"])
            for row in rows
        }
        candidate_ids = [
            candidate_by_visible_uid[f"visible-{suffix}-{index}"]
            for index in range(len(platform_identities))
        ]
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title=job_title, jd_text="test", prompt_text="screen")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title=job_title,
            batch_id=capture_batch_id,
            provider="fake",
            model="fake-model",
            total_candidates=len(candidate_ids),
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
                        "value": identity,
                    },
                }
                for candidate_id, identity in zip(candidate_ids, platform_identities, strict=True)
            ],
        )
        return favorite_batch_id, candidate_ids

    def test_batch_allows_only_one_running_task_and_expired_lease_becomes_unknown(self) -> None:
        favorite_batch_id, _candidate_ids = self._create_favorite_batch(
            "serial",
            ["trusted-serial-1", "trusted-serial-2"],
        )
        first = self.repository.claim_next_native_favorite_task(favorite_batch_id)

        self.assertIsNotNone(first)
        self.assertIsNone(self.repository.claim_next_native_favorite_task(favorite_batch_id))

        self.db.get_connection().execute(
            "UPDATE native_favorite_tasks SET locked_at = '2000-01-01T00:00:00' WHERE id = ?",
            (int(first["task_id"]),),
        )
        self.db.get_connection().commit()
        second = self.repository.claim_next_native_favorite_task(
            favorite_batch_id,
            lock_timeout_seconds=0,
        )

        self.assertIsNotNone(second)
        self.assertNotEqual(second["task_id"], first["task_id"])
        tasks = self.repository.list_native_favorite_tasks(favorite_batch_id)
        recovered = next(row for row in tasks if int(row["id"]) == int(first["task_id"]))
        self.assertEqual(recovered["status"], "unknown")
        self.assertEqual(
            recovered["error_reason"],
            "claim_lease_expired_requires_manual_resolution",
        )
        attempts = self.repository.list_native_favorite_attempts(int(first["task_id"]))
        self.assertEqual(len(attempts), 1)
        self.assertIsNone(attempts[0]["attempted"])

    def test_reconciliation_recovers_expired_claim_without_claiming_next_pending_task(self) -> None:
        favorite_batch_id, _candidate_ids = self._create_favorite_batch(
            "reconcile", ["trusted-reconcile-1", "trusted-reconcile-2"]
        )
        first = self.repository.claim_next_native_favorite_task(favorite_batch_id)
        active = self.repository.reconcile_native_favorite_batch(favorite_batch_id)
        self.assertFalse(active["can_resume_pending"])
        self.assertEqual(active["running"], 1)

        self.db.get_connection().execute(
            "UPDATE native_favorite_tasks SET locked_at = '2000-01-01T00:00:00' WHERE id = ?",
            (int(first["task_id"]),),
        )
        self.db.get_connection().commit()
        recovered = self.repository.reconcile_native_favorite_batch(
            favorite_batch_id, lock_timeout_seconds=0
        )
        self.assertTrue(recovered["can_resume_pending"])
        self.assertEqual(recovered["recovered_unknown"], 1)
        self.assertEqual(recovered["pending"], 1)
        self.assertEqual(recovered["unknown"], 1)
        self.assertFalse(any(
            str(task["status"]) == "running"
            for task in self.repository.list_native_favorite_tasks(favorite_batch_id)
        ))

    def test_failed_task_has_one_explicit_retry_and_identity_conflict_maps_to_failed(self) -> None:
        favorite_batch_id, _candidate_ids = self._create_favorite_batch(
            "retry",
            ["trusted-retry-1"],
        )
        first = self.repository.claim_next_native_favorite_task(favorite_batch_id)

        with self.assertRaisesRegex(ValueError, "terminal status"):
            self.repository.complete_native_favorite_task(
                int(first["task_id"]),
                claim_token=str(first["claim_token"]),
                status="stopped",
                attempted=True,
            )
        failed = self.repository.complete_native_favorite_task(
            int(first["task_id"]),
            claim_token=str(first["claim_token"]),
            status="failed",
            attempted=True,
            reason="favorite_control_missing",
        )
        self.assertEqual(failed["status"], "failed")

        retried = self.repository.retry_native_favorite_task(int(first["task_id"]))
        self.assertEqual(retried["status"], "pending")
        second = self.repository.claim_next_native_favorite_task(favorite_batch_id)
        conflict = self.repository.complete_native_favorite_task(
            int(second["task_id"]),
            claim_token=str(second["claim_token"]),
            status="identity_conflict",
            attempted=False,
        )

        self.assertEqual(conflict["status"], "failed")
        self.assertEqual(
            conflict["reason"],
            "multiple_favorite_management_identity_matches",
        )
        with self.assertRaisesRegex(ValueError, "retry limit"):
            self.repository.retry_native_favorite_task(int(first["task_id"]))

    def test_historical_success_requires_current_management_verification_without_write(self) -> None:
        first_batch_id, _candidate_ids = self._create_favorite_batch(
            "verified-first",
            ["trusted-verified-1"],
        )
        first = self.repository.claim_next_native_favorite_task(first_batch_id)
        self.repository.complete_native_favorite_task(
            int(first["task_id"]),
            claim_token=str(first["claim_token"]),
            status="success",
            attempted=True,
            reason="favorite_management_identity_confirmed",
        )

        next_batch_id, _next_candidate_ids = self._create_favorite_batch(
            "verified-next",
            ["trusted-verified-1"],
        )
        verification = self.repository.claim_next_native_favorite_task(next_batch_id)

        self.assertIsNotNone(verification)
        self.assertEqual(verification["write_policy"], "verify_only")
        self.assertEqual(verification["status"], "running")
        with self.assertRaisesRegex(ValueError, "verify_only"):
            self.repository.complete_native_favorite_task(
                int(verification["task_id"]),
                claim_token=str(verification["claim_token"]),
                status="success",
                attempted=True,
                reason="favorite_management_identity_confirmed",
            )
        verified = self.repository.complete_native_favorite_task(
            int(verification["task_id"]),
            claim_token=str(verification["claim_token"]),
            status="already_favorited",
            attempted=False,
            reason="favorite_management_identity_confirmed",
        )
        self.assertEqual(verified["status"], "already_favorited")

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
