from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.models import JobProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class JobProfileRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "job_profiles.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_job_profile_is_the_single_versioned_source_for_screening(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(
                job_title="高级招聘顾问",
                department="人才招聘部",
                hiring_manager="钟女士",
                location="上海",
                employment_type="全职",
                experience_requirement="5 年以上招聘经验",
                education_requirement="本科及以上",
                target_hires=2,
                recruitment_deadline="2026-10-31",
                priority="high",
                status="active",
                jd_text="负责关键岗位招聘与人才 Mapping",
                prompt_text="按岗位规则进行筛选",
                must_have=["独立招聘闭环经验"],
                nice_to_have=["猎头经验"],
                exclusions=["无招聘经验"],
            )
        )

        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="高级招聘顾问",
            batch_id=None,
            provider="fake",
            model="fake-model",
            total_candidates=0,
        )
        profile.target_hires = 3
        profile.must_have.append("Mapping 项目经验")
        updated = self.repository.save_job_profile(profile)

        current = self.repository.get_job_profile(int(profile.id))
        versions = self.repository.list_job_profile_versions(int(profile.id))
        run = self.repository.get_screening_run(run_id)

        self.assertEqual(updated.version, 2)
        self.assertEqual(current["department"], "人才招聘部")
        self.assertEqual(current["target_hires"], 3)
        self.assertEqual(current["must_have"], ["独立招聘闭环经验", "Mapping 项目经验"])
        self.assertEqual([row["version"] for row in versions], [2, 1])
        self.assertEqual(versions[1]["snapshot"]["target_hires"], 2)
        self.assertEqual(run["profile_version"], 1)

    def test_paused_job_is_not_offered_for_new_work_and_clone_starts_as_draft(self) -> None:
        profile = self.repository.save_job_profile(
            JobProfile(
                job_title="证券交易员",
                jd_text="负责证券交易",
                prompt_text="筛选证券交易经验",
                status="active",
            )
        )
        self.repository.set_job_profile_status(int(profile.id), "paused")
        clone = self.repository.clone_job_profile(int(profile.id), "证券交易员（二期）")

        active_ids = {row["id"] for row in self.repository.list_job_profiles(active_only=True)}
        paused = self.repository.get_job_profile(int(profile.id))
        cloned = self.repository.get_job_profile(int(clone.id))

        self.assertNotIn(profile.id, active_ids)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(cloned["status"], "draft")
        self.assertEqual(cloned["parent_profile_id"], profile.id)
        self.assertEqual(cloned["must_have"], paused["must_have"])


if __name__ == "__main__":
    unittest.main()
