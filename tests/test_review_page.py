from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.pages.review import ReviewPage


class ReviewPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_quick_pass_records_standard_manual_review_reason(self) -> None:
        page = ReviewPage()
        self.addCleanup(page.deleteLater)
        emitted: list[dict[str, object]] = []
        page.status_change_requested.connect(lambda payload: emitted.append(dict(payload)))
        rows = [
                {
                    "candidate_id": 7,
                    "role_id": 3,
                    "name": "Manual Candidate",
                    "role_title": "Java Engineer",
                    "latest_rating": "SSR",
                    "latest_confidence": "low",
                    "review_reason": "low_confidence",
                    "recommended_action": "manual_review",
                    "recruitment_status": "screened",
                }
            ]
        page.set_rows(rows)

        page.table.selectRow(0)
        page.pass_review_button.click()

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["candidate_id"], 7)
        self.assertEqual(emitted[0]["role_id"], 3)
        self.assertEqual(emitted[0]["to_status"], "priority_outreach")
        self.assertEqual(emitted[0]["reason_code"], "manual_review_passed")
        self.assertIn("Manual review passed", emitted[0]["note"])
        self.assertEqual(page.summary_label.text(), "待复核 1")

    def test_route_detail_explains_generic_transaction_exclusion(self) -> None:
        detail = ReviewPage._route_detail(
            {
                "route_reason": "generic_transaction_without_market_context",
                "route_details_json": json.dumps(
                    {
                        "evidence_policy": "securities_trader:v1",
                        "matched_direct_evidence": [],
                        "matched_market_terms": [],
                        "matched_action_terms": ["交易"],
                        "matched_exclusion_terms": ["电商交易"],
                    },
                    ensure_ascii=False,
                ),
            }
        )

        self.assertIn("泛交易描述，缺少证券市场证据", detail)
        self.assertIn("- 证据策略：securities_trader:v1", detail)
        self.assertIn("- 动作证据：交易", detail)
        self.assertIn("- 排除证据：电商交易", detail)

    def test_workbench_shows_todo_summary_filters_and_defers_with_next_action(self) -> None:
        page = ReviewPage()
        self.addCleanup(page.deleteLater)
        page.set_workbench_summary(
            {
                "pending_total": 12,
                "high_priority": 4,
                "ai_uncertain": 3,
                "incomplete_profiles": 2,
                "needs_info": 2,
                "deferred": 1,
                "reviewed_today": 5,
            }
        )
        rows = [
                {
                    "candidate_id": 7,
                    "role_id": 3,
                    "name": "待确认候选人",
                    "role_title": "Java Engineer",
                    "latest_rating": "SR",
                    "latest_confidence": "low",
                    "review_bucket": "priority",
                    "priority_reason": "AI 判断不确定",
                    "review_reason": "模型置信度低",
                    "recommended_action": "manual_review",
                    "recruitment_status": "screened",
                    "review_history_text": (
                        "2026-08-06T10:00:00｜screened｜manual_review_deferred｜此前暂缓"
                    ),
                },
                {
                    "candidate_id": 8,
                    "role_id": 3,
                    "name": "下一位候选人",
                    "role_title": "Java Engineer",
                    "latest_rating": "R",
                    "latest_confidence": "high",
                    "review_bucket": "pending",
                    "priority_reason": "普通待复核",
                    "review_reason": "需要复核",
                    "recommended_action": "manual_review",
                    "recruitment_status": "screened",
                },
            ]
        page.set_rows(rows)
        emitted: list[dict[str, object]] = []
        page.status_change_requested.connect(lambda payload: emitted.append(dict(payload)))
        page.queue_combo.setCurrentIndex(page.queue_combo.findData("needs_info"))

        page.needs_info_button.click()

        self.assertEqual(emitted, [])
        self.assertIn("请先填写需要补充的具体资料", page.review_feedback_label.text())

        page.status_note_input.setText("请补充最近一段工作经历")
        page.needs_info_button.click()
        page.set_rows(rows)

        self.assertIn("待复核 12", page.todo_summary_label.text())
        self.assertIn("高优先级 4", page.todo_summary_label.text())
        self.assertIn("今日已复核 5", page.todo_summary_label.text())
        self.assertEqual(page.current_filters()["queue_category"], "needs_info")
        self.assertEqual(emitted[0]["to_status"], "screened")
        self.assertEqual(emitted[0]["reason_code"], "manual_review_needs_info")
        self.assertEqual(emitted[0]["note"], "请补充最近一段工作经历")
        self.assertEqual(emitted[0]["operator"], "review_workbench")
        self.assertTrue(emitted[0]["advance_after_save"])
        self.assertEqual(page.table.currentRow(), 1)
        self.assertIn("下一位候选人", page.detail_text.toPlainText())
        self.assertIn("人工复核记录", page.detail_text.toPlainText())


if __name__ == "__main__":
    unittest.main()
