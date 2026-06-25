from __future__ import annotations

import unittest

from ai.prescreen import RulePrescreener
from talent.calibration import CalibrationSampler
from talent.profile_builder import StandardProfileBuilder


class CalibrationSamplerTest(unittest.TestCase):
    def test_build_sample_exposes_prescreen_profile_and_manual_placeholders(self) -> None:
        sampler = CalibrationSampler(
            prescreener=RulePrescreener(),
            profile_builder=StandardProfileBuilder(),
        )
        profile = {
            "job_title": "Java Engineer",
            "jd_text": "Shenzhen, 5+ years Java and Spring Cloud.",
        }
        candidates = [
            {
                "id": 1,
                "name": "Rich",
                "job_title": "Java Engineer",
                "raw_card_text": "Rich Shenzhen 6 years Java Spring Cloud Bachelor",
                "work_experience_text": "6 years Java development",
                "education_text": "Bachelor",
                "tags_text": "Java | Spring Cloud",
            },
            {
                "id": 2,
                "name": "",
                "job_title": "Java Engineer",
                "raw_card_text": "Java only",
            },
            {
                "id": 3,
                "name": "Young",
                "job_title": "Java Engineer",
                "raw_card_text": "Young Shenzhen 1 years Java Spring Cloud",
                "work_experience_text": "1 years Java",
                "education_text": "Bachelor",
                "tags_text": "Java",
            },
        ]

        sample = sampler.build_sample(profile=profile, candidates=candidates, sample_size=10)

        rows = sample["rows"]
        summary = sample["summary"]
        self.assertEqual(summary["sample_size"], 3)
        self.assertIn("route_counts", summary)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all("manual_route_judgment" in row for row in rows))
        self.assertTrue(all("manual_profile_judgment" in row for row in rows))
        self.assertTrue(any(row["review_priority"] for row in rows))
        self.assertTrue(any(row["prescreen_route"] in {"manual_check", "hold"} for row in rows))

    def test_manual_metrics_calculates_route_and_profile_error_rates(self) -> None:
        sampler = CalibrationSampler(
            prescreener=RulePrescreener(),
            profile_builder=StandardProfileBuilder(),
        )
        rows = [
            {
                "candidate_id": 1,
                "manual_route_judgment": "correct",
                "manual_profile_judgment": "",
            },
            {
                "candidate_id": 2,
                "manual_route_judgment": "false_hold",
                "manual_profile_judgment": "wrong_city",
            },
            {
                "candidate_id": 3,
                "manual_route_judgment": "",
                "manual_profile_judgment": "correct",
            },
        ]

        metrics = sampler.manual_metrics(rows)

        self.assertEqual(metrics["reviewed_count"], 3)
        self.assertEqual(metrics["route_reviewed_count"], 2)
        self.assertEqual(metrics["profile_reviewed_count"], 2)
        self.assertEqual(metrics["route_error_count"], 1)
        self.assertEqual(metrics["profile_error_count"], 1)
        self.assertEqual(metrics["route_error_rate"], 0.5)
        self.assertEqual(metrics["profile_error_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
