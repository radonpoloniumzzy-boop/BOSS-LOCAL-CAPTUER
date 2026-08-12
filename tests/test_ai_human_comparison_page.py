from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.pages.ai_human_comparison import AIHumanComparisonPage


class AIHumanComparisonPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_filters_displays_comparison_detail_and_opens_candidate(self) -> None:
        page = AIHumanComparisonPage()
        self.addCleanup(page.deleteLater)
        page.set_profiles([{"id": 3, "job_title": "产品经理"}])
        page.role_combo.setCurrentIndex(page.role_combo.findData(3))
        page.comparison_combo.setCurrentIndex(
            page.comparison_combo.findData("disagreement")
        )
        page.set_summary(
            {
                "compared_total": 10,
                "agreement_count": 6,
                "disagreement_count": 2,
                "manual_resolved_count": 2,
                "human_passed_count": 7,
                "human_rejected_count": 3,
                "agreement_rate": 75.0,
            }
        )
        page.set_page_result(
            [
                {
                    "candidate_id": 17,
                    "role_id": 3,
                    "name": "对照候选人",
                    "role_title": "产品经理",
                    "latest_rating": "SSR",
                    "latest_confidence": "high",
                    "recommended_action": "priority_outreach",
                    "persona": "企业软件产品负责人",
                    "evidence_json": '[{"item":"产品经验","evidence":"企业软件"}]',
                    "gap_json": '["团队规模待确认"]',
                    "risk_json": '["行业跨度"]',
                    "human_decision": "manual_review_rejected",
                    "human_note": "核心经历不匹配",
                    "human_reviewed_at": "2026-08-06T12:00:00",
                    "ai_decision": "recommended",
                    "comparison_status": "disagreement",
                    "difference_type": "ai_overestimated",
                }
            ],
            total=1,
            page=1,
            page_size=100,
        )
        opened: list[int] = []
        page.candidate_open_requested.connect(opened.append)

        page.open_candidate_button.click()

        self.assertEqual(page.current_filters(), {
            "role_id": 3,
            "comparison_status": "disagreement",
        })
        self.assertIn("已对照 10", page.summary_label.text())
        self.assertIn("一致率 75.0%", page.summary_label.text())
        self.assertIn("AI 高估", page.table.item(0, 0).text())
        detail = page.detail_text.toPlainText()
        self.assertIn("企业软件产品负责人", detail)
        self.assertIn("核心经历不匹配", detail)
        self.assertIn("团队规模待确认", detail)
        self.assertIn("行业跨度", detail)
        self.assertEqual(opened, [17])


if __name__ == "__main__":
    unittest.main()
