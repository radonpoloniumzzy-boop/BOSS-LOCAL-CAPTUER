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
        self.trader_profile = {
            "job_title": "证券交易员",
            "jd_text": (
                "关注市场公开信息和上市公司重要公告，能够对行情快速判断。"
                "负责账户的证券操作，根据指令及时进行准确买卖操作。"
                "本科及以上学历，对金融行业和证券投资有兴趣，具有两年以上交易经验。"
            ),
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

    def test_trader_candidate_with_market_trading_terms_passes_without_finance_word(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Lin",
                "work_experience_text": "2 years 股票交易 and A股账户下单 experience.",
                "education_text": "Bachelor degree",
                "tags_text": "股票交易 | 行情判断 | 止损纪律",
                "summary_text": "Built daily trading plans from market announcements and price action.",
                "raw_card_text": "Handled A股账户买卖操作 and intraday risk controls.",
            },
            self.trader_profile,
        )

        self.assertEqual(decision.route, PASS_TO_AI)
        self.assertEqual(decision.reason, "matched_securities_trading_evidence")
        self.assertTrue(decision.details["keyword_signal"])
        self.assertEqual(decision.details["evidence_policy"], "securities_trader:v1")
        self.assertIn("股票交易", decision.details["matched_direct_evidence"])
        self.assertIn("A股", decision.details["matched_market_terms"])
        self.assertIn("下单", decision.details["matched_action_terms"])

    def test_generic_transaction_mentions_still_need_manual_check_for_trader_role(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Evan",
                "work_experience_text": "3 years ecommerce transaction operations.",
                "education_text": "Bachelor degree",
                "tags_text": "电商交易 | 订单交易 | 客服协同",
                "summary_text": "Optimized marketplace order transaction conversion and after-sales flows.",
                "raw_card_text": "Responsible for online shop transaction data and promotion operations.",
            },
            self.trader_profile,
        )

        self.assertEqual(decision.route, MANUAL_CHECK)
        self.assertEqual(decision.reason, "generic_transaction_without_market_context")
        self.assertFalse(decision.details["keyword_signal"])
        self.assertEqual(decision.details["evidence_policy"], "securities_trader:v1")
        self.assertIn("电商交易", decision.details["matched_exclusion_terms"])

    def test_market_and_action_evidence_passes_to_ai_without_direct_phrase(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Mei",
                "work_experience_text": "负责A股账户日常下单与盘中风险控制。",
                "education_text": "本科",
                "tags_text": "A股 | 下单 | 风控",
                "summary_text": "根据行情变化执行止损纪律。",
                "raw_card_text": "有二级市场账户操作经验。",
            },
            self.trader_profile,
        )

        self.assertEqual(decision.route, PASS_TO_AI)
        self.assertEqual(decision.reason, "matched_securities_trading_evidence")
        self.assertIn("A股", decision.details["matched_market_terms"])
        self.assertIn("下单", decision.details["matched_action_terms"])

    def test_action_only_evidence_stays_in_manual_check(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Kai",
                "work_experience_text": "负责交易数据复盘与订单协同。",
                "education_text": "本科",
                "tags_text": "交易 | 数据分析",
                "summary_text": "跟进业务交易流程。",
                "raw_card_text": "其余职业经历信息较少。",
            },
            self.trader_profile,
        )

        self.assertEqual(decision.route, MANUAL_CHECK)
        self.assertEqual(decision.reason, "generic_transaction_without_market_context")
        self.assertIn("交易", decision.details["matched_action_terms"])

    def test_exclusion_blocks_market_and_action_combination(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Chen",
                "work_experience_text": "负责股票类电商交易产品的订单下单流程。",
                "education_text": "本科",
                "tags_text": "股票 | 下单 | 电商交易",
                "summary_text": "优化商城交易链路。",
                "raw_card_text": "电商平台运营岗位。",
            },
            self.trader_profile,
        )

        self.assertEqual(decision.route, MANUAL_CHECK)
        self.assertIn("股票", decision.details["matched_market_terms"])
        self.assertIn("下单", decision.details["matched_action_terms"])
        self.assertIn("电商交易", decision.details["matched_exclusion_terms"])

    def test_direct_evidence_overrides_generic_transaction_exclusion(self) -> None:
        decision = self.prescreener.evaluate(
            {
                "name": "Zhou",
                "work_experience_text": "早期负责电商交易，后转岗从事股票交易。",
                "education_text": "本科",
                "tags_text": "股票交易 | 电商交易",
                "summary_text": "执行A股账户买卖计划。",
                "raw_card_text": "有明确二级市场交易经历。",
            },
            self.trader_profile,
        )

        self.assertEqual(decision.route, PASS_TO_AI)
        self.assertIn("股票交易", decision.details["matched_direct_evidence"])
        self.assertIn("电商交易", decision.details["matched_exclusion_terms"])


if __name__ == "__main__":
    unittest.main()
