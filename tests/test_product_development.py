from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.product_development import ProductDevelopmentRepository
from ui.pages.product_development import ProductDevelopmentPage


class ProductDevelopmentRepositoryTest(unittest.TestCase):
    def test_plan_is_loaded_from_one_source_and_feedback_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_path = root / "plan.json"
            feedback_path = root / "feedback.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "product": {"name": "招聘工作台", "current_version": "0.2.0"},
                        "status_options": ["开发中", "可试用"],
                        "roadmap": [{"stage": "第一阶段", "status": "开发中"}],
                        "modules": [
                            {
                                "id": "capture",
                                "name": "候选人采集",
                                "status": "可试用",
                                "current": "已经能够采集",
                                "ideal": "按岗位自动采集",
                                "limitations": "仍需人工登录",
                                "next_step": "增加任务编排",
                                "flow": ["创建岗位", "启动采集"],
                                "acceptance": ["数据可追溯"],
                            }
                        ],
                        "versions": [{"version": "0.2.0", "status": "当前版本"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            repository = ProductDevelopmentRepository(plan_path, feedback_path)
            snapshot = repository.load_snapshot()
            self.assertEqual(snapshot["plan"]["modules"][0]["name"], "候选人采集")
            self.assertEqual(snapshot["feedback"], [])

            saved = repository.submit_feedback(
                {
                    "type": "功能建议",
                    "module": "候选人采集",
                    "impact": "阻碍主要流程",
                    "description": "希望保存采集条件",
                    "expected": "下次可以直接复用",
                }
            )

            restarted = ProductDevelopmentRepository(plan_path, feedback_path)
            feedback = restarted.load_snapshot()["feedback"]
            self.assertEqual(feedback[0]["id"], saved["id"])
            self.assertEqual(feedback[0]["description"], "希望保存采集条件")
            self.assertEqual(feedback[0]["status"], "待处理")

    def test_feedback_description_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "product": {"name": "招聘工作台", "current_version": "0.2.0"},
                        "status_options": ["开发中"],
                        "roadmap": [],
                        "modules": [],
                        "versions": [],
                    }
                ),
                encoding="utf-8",
            )
            repository = ProductDevelopmentRepository(plan_path, root / "feedback.json")

            with self.assertRaisesRegex(ValueError, "反馈内容"):
                repository.submit_feedback({"description": "  "})

    def test_plan_rejects_non_object_list_items_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "product": {"name": "招聘工作台", "current_version": "0.2.0"},
                        "status_options": ["开发中"],
                        "roadmap": [],
                        "modules": ["错误数据"],
                        "versions": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            repository = ProductDevelopmentRepository(plan_path, root / "feedback.json")

            with self.assertRaisesRegex(ValueError, "modules.*对象"):
                repository.load_snapshot()


class ProductDevelopmentPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_page_renders_four_product_tabs_and_emits_feedback(self) -> None:
        page = ProductDevelopmentPage()
        page.set_snapshot(
            {
                "plan": {
                    "product": {
                        "name": "招聘工作台",
                        "current_version": "0.2.0",
                        "phase": "基础闭环完善",
                        "updated_at": "2026-08-04",
                        "summary": "先把采集、筛选、复核、入库跑稳。",
                    },
                    "status_options": ["开发中", "可试用"],
                    "roadmap": [{"stage": "第一阶段", "goal": "基础闭环", "status": "开发中"}],
                    "modules": [
                        {
                            "id": "capture",
                            "name": "候选人采集",
                            "status": "可试用",
                            "current": "已经能够采集",
                            "ideal": "按岗位自动采集",
                            "limitations": "仍需人工登录",
                            "next_step": "增加任务编排",
                            "flow": ["创建岗位", "启动采集"],
                            "acceptance": ["数据可追溯"],
                        }
                    ],
                    "versions": [{"version": "0.2.0", "date": "2026-08-04", "status": "当前版本", "changes": ["新增产品建设页"]}],
                },
                "feedback": [],
            }
        )

        self.assertEqual(
            [page.tabs.tabText(index) for index in range(page.tabs.count())],
            ["产品路线", "功能模块", "版本记录", "使用反馈"],
        )
        self.assertIn("0.2.0", page.version_value.text())
        self.assertEqual(page.module_table.rowCount(), 1)
        self.assertEqual(page.module_table.item(0, 1).text(), "可试用")

        page.set_feedback(
            [
                {
                    "id": "FB-1",
                    "created_at": "2026-08-04T12:00:00+08:00",
                    "type": "功能建议",
                    "module": "候选人采集",
                    "impact": "影响效率",
                    "status": "待处理",
                    "description": "希望保存采集条件",
                    "expected": "下次可以直接复用",
                }
            ]
        )
        self.assertEqual(page.feedback_table.item(0, 7).text(), "下次可以直接复用")

        emitted: list[dict[str, str]] = []
        page.feedback_submit_requested.connect(emitted.append)
        page.feedback_description_input.setPlainText("希望保存采集条件")
        page.feedback_expected_input.setPlainText("下次可以直接复用")
        page.feedback_submit_button.click()

        self.assertEqual(emitted[0]["description"], "希望保存采集条件")
        self.assertEqual(emitted[0]["module"], "候选人采集")


if __name__ == "__main__":
    unittest.main()
