from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai.prompt_manager import PromptManager
from core.models import ScreeningProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class StructuredScreeningProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "profiles.db")
        self.db.initialize()
        self.repository = CandidateRepository(self.db)

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_structured_fields_round_trip_and_version_increments(self) -> None:
        profile = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Securities Trader Custom",
                jd_text="Trade securities",
                prompt_text="Evaluate evidence",
                must_have=["证券交易经验"],
                nice_to_have=["量化策略"],
                risk_flags=["只写交易但未写交易品种"],
                exclusions=["无任何交易相关经历"],
                interview_checks=["核验独立下单范围"],
                evidence_policy={"explicit_evidence_required": True},
            )
        )
        profile.nice_to_have.append("风控经验")
        updated = self.repository.save_screening_profile(profile)
        row = dict(self.repository.get_screening_profile(int(updated.id)))

        self.assertEqual(row["version"], 2)
        self.assertEqual(row["must_have"], ["证券交易经验"])
        self.assertEqual(row["nice_to_have"], ["量化策略", "风控经验"])
        self.assertTrue(row["evidence_policy"]["explicit_evidence_required"])

    def test_clone_is_independent_and_starts_new_version_line(self) -> None:
        source = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="Trader Source",
                jd_text="JD",
                prompt_text="Prompt",
                must_have=["证券交易"],
            )
        )
        clone = self.repository.clone_screening_profile(int(source.id), "Trader Copy")
        clone.must_have.append("风险控制")
        self.repository.save_screening_profile(clone)
        source_row = dict(self.repository.get_screening_profile(int(source.id)))
        clone_row = dict(self.repository.get_screening_profile(int(clone.id)))

        self.assertEqual(source_row["must_have"], ["证券交易"])
        self.assertEqual(clone_row["must_have"], ["证券交易", "风险控制"])
        self.assertEqual(clone_row["parent_profile_id"], source.id)

    def test_structured_prompt_is_deterministic_and_keeps_output_protocol(self) -> None:
        manager = PromptManager(Path(self.temp_dir.name))
        profile = ScreeningProfile(
            job_title="Securities Trader",
            jd_text="负责证券交易与风险控制",
            prompt_text="",
            must_have=["明确证券交易证据"],
            nice_to_have=["量化策略"],
            risk_flags=["交易品种不明"],
            exclusions=["只有模拟盘"],
            interview_checks=["核验实盘权限"],
            evidence_policy={"explicit_evidence_required": True},
        )

        first = manager.build_structured(profile)
        second = manager.build_structured(profile)

        self.assertEqual(first, second)
        self.assertIn("明确证券交易证据", first)
        self.assertIn('"rating"', first)
        self.assertIn("只有模拟盘", first)


if __name__ == "__main__":
    unittest.main()
