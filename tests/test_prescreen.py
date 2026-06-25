import unittest

from ai.prescreen import HOLD, MANUAL_CHECK, PASS_TO_AI, RulePrescreener


class RulePrescreenerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.prescreener = RulePrescreener()
        self.profile = {"job_title": "SaaS Sales"}
        self.strict_profile = {
            "job_title": "SaaS Sales",
            "jd_text": "Must have 3+ years B2B SaaS sales experience in Shenzhen.",
        }

    def test_routes_rich_candidate_to_ai(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Alice",
                "work_experience_text": "5 years B2B SaaS key account sales experience",
                "education_text": "Bachelor degree in business administration",
                "tags_text": "SaaS, CRM, enterprise software, KA sales",
                "summary_text": "Closed enterprise accounts and managed full-cycle solution sales.",
                "raw_card_text": "Alice has enterprise software sales experience in Shenzhen.",
            },
            self.profile,
        )

        self.assertEqual(decision.route, PASS_TO_AI)
        self.assertEqual(decision.reason, "sufficient_candidate_evidence")

    def test_routes_sparse_candidate_to_manual_check(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "",
                "raw_card_text": "Candidate mentions sales but has no work history details.",
            },
            self.profile,
        )

        self.assertEqual(decision.route, MANUAL_CHECK)
        self.assertEqual(decision.reason, "insufficient_candidate_evidence")

    def test_routes_empty_candidate_to_hold(self) -> None:
        decision = self.prescreener.evaluate({"name": "C"}, self.profile)

        self.assertEqual(decision.route, HOLD)
        self.assertEqual(decision.reason, "no_meaningful_candidate_text")

    def test_role_requirement_match_passes_to_ai(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Jordan",
                "work_experience_text": "Shenzhen 5 years B2B SaaS sales experience.",
                "education_text": "Bachelor degree",
                "tags_text": "B2B, SaaS, CRM",
                "summary_text": "Owned full-cycle enterprise software sales.",
                "raw_card_text": "Jordan is active in Shenzhen and has SaaS account experience.",
            },
            self.strict_profile,
        )

        self.assertEqual(decision.route, PASS_TO_AI)
        self.assertEqual(decision.reason, "sufficient_candidate_evidence")
        self.assertEqual(decision.details["candidate_years"], 5)
        self.assertEqual(decision.details["role_requirements"]["job_track"], "SaaS销售")

    def test_role_city_mismatch_is_held_without_ai_call(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Morgan",
                "work_experience_text": "Shanghai 5 years B2B SaaS sales experience.",
                "education_text": "Bachelor degree",
                "tags_text": "B2B, SaaS, CRM",
                "summary_text": "Managed enterprise accounts.",
                "raw_card_text": "Morgan is currently based in Shanghai.",
            },
            self.strict_profile,
        )

        self.assertEqual(decision.route, HOLD)
        self.assertEqual(decision.reason, "role_city_mismatch")

    def test_role_years_below_minimum_is_held_without_ai_call(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Riley",
                "work_experience_text": "Shenzhen 1 year B2B SaaS sales experience.",
                "education_text": "Bachelor degree",
                "tags_text": "B2B, SaaS, CRM",
                "summary_text": "Supported enterprise account sales.",
                "raw_card_text": "Riley is currently based in Shenzhen.",
            },
            self.strict_profile,
        )

        self.assertEqual(decision.route, HOLD)
        self.assertEqual(decision.reason, "role_years_below_minimum")

    def test_missing_role_keywords_goes_to_manual_check(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Casey",
                "work_experience_text": "Shenzhen 5 years retail sales experience.",
                "education_text": "Bachelor degree",
                "tags_text": "Retail, store operations",
                "summary_text": "Managed offline sales conversion and store campaigns.",
                "raw_card_text": "Casey is currently based in Shenzhen.",
            },
            self.strict_profile,
        )

        self.assertEqual(decision.route, MANUAL_CHECK)
        self.assertEqual(decision.reason, "missing_role_keywords")
        self.assertIn("B2B", decision.details["missing_required_terms"])


if __name__ == "__main__":
    unittest.main()
