import unittest

from ai.role_requirements import RoleRequirementExtractor
from talent.profile_builder import StandardProfileBuilder
from talent.role_taxonomy import RoleTaxonomy


class RoleTaxonomyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.taxonomy = RoleTaxonomy()

    def test_classifies_common_sales_tracks(self) -> None:
        self.assertEqual(
            self.taxonomy.classify("5 years B2B SaaS CRM enterprise software sales"),
            ("销售", "SaaS销售"),
        )
        self.assertEqual(
            self.taxonomy.classify("招商主管 平台招商 商户拓展 加盟门店"),
            ("销售", "招商主管"),
        )

    def test_classifies_technical_tracks(self) -> None:
        self.assertEqual(
            self.taxonomy.classify("Java工程师 后端开发 Spring Cloud SQL API"),
            ("技术", "后端开发"),
        )

    def test_classifies_securities_trader_track(self) -> None:
        self.assertEqual(
            self.taxonomy.classify("证券交易员 股票 期货 账户操作 行情判断 下单 风控"),
            ("金融", "证券交易员"),
        )

    def test_securities_trader_exposes_versioned_evidence_policy(self) -> None:
        track = self.taxonomy.get_track("金融", "证券交易员")

        self.assertIsNotNone(track)
        policy = track.to_dict()["evidence_policy"]
        self.assertEqual(policy["name"], "securities_trader:v1")
        self.assertIn("股票交易", policy["direct_evidence"])
        self.assertIn("A股", policy["market_terms"])
        self.assertIn("下单", policy["action_terms"])
        self.assertIn("电商交易", policy["exclusion_terms"])

    def test_profile_builder_uses_shared_taxonomy(self) -> None:
        profile = StandardProfileBuilder(role_taxonomy=self.taxonomy).build(
            {
                "id": 1,
                "name": "Taylor",
                "job_title": "SaaS Sales",
                "work_experience_text": "Shenzhen 5 years B2B SaaS CRM enterprise software sales",
                "education_text": "Bachelor",
                "tags_text": "SaaS | CRM | enterprise service",
                "raw_card_text": "Taylor closed enterprise software customers.",
            }
        )

        self.assertEqual(profile["job_family"], "销售")
        self.assertEqual(profile["job_track"], "SaaS销售")
        self.assertIn("SaaS", profile["skill_tags"])

    def test_profile_builder_tags_securities_trader_without_finance_word(self) -> None:
        profile = StandardProfileBuilder(role_taxonomy=self.taxonomy).build(
            {
                "id": 2,
                "name": "Lin",
                "job_title": "交易员",
                "work_experience_text": "2 years 股票交易 and A股账户下单 experience.",
                "education_text": "Bachelor",
                "tags_text": "股票交易 | 行情判断 | 止损纪律",
                "raw_card_text": "Handled A股账户买卖操作 and intraday risk controls.",
            }
        )

        self.assertEqual(profile["job_family"], "金融")
        self.assertEqual(profile["job_track"], "证券交易员")
        self.assertIn("股票", profile["skill_tags"])

    def test_role_requirements_include_taxonomy_classification(self) -> None:
        requirements = RoleRequirementExtractor(role_taxonomy=self.taxonomy).from_profile(
            {
                "job_title": "SaaS销售",
                "jd_text": "Must have 3+ years B2B SaaS sales experience in Shenzhen.\nNice to have CRM.",
            }
        )

        self.assertEqual(requirements.job_family, "销售")
        self.assertEqual(requirements.job_track, "SaaS销售")
        self.assertEqual(requirements.min_years, 3)
        self.assertIn("B2B", requirements.required_terms)
        self.assertIn("SaaS", requirements.required_terms)
        self.assertIn("CRM", requirements.preferred_terms)

    def test_trader_requirements_include_market_and_trading_terms(self) -> None:
        requirements = RoleRequirementExtractor(role_taxonomy=self.taxonomy).from_profile(
            {
                "job_title": "证券交易员",
                "jd_text": "负责账户的证券操作，关注行情并做股票交易计划，对金融行业和证券投资有兴趣。",
            }
        )

        self.assertEqual(requirements.job_family, "金融")
        self.assertEqual(requirements.job_track, "证券交易员")
        self.assertIn("证券", requirements.required_terms)
        self.assertIn("交易", requirements.required_terms)
        self.assertIn("股票", requirements.required_terms)


if __name__ == "__main__":
    unittest.main()
