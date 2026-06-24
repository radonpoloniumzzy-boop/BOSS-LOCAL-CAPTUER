from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai.prompt_manager import PromptManager


class PromptManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = PromptManager(Path("assets/prompts"))

    def test_build_from_jd_creates_compact_rating_protocol(self) -> None:
        prompt = self.manager.build_from_jd("量化私募销售", "本科；有渠道销售经验；能够独立路演。")
        self.assertIn("量化私募销售", prompt)
        self.assertIn("能够独立路演", prompt)
        self.assertIn('"rating"', prompt)
        self.assertIn('"persona"', prompt)
        self.assertIn("UR", prompt)

    def test_sensitive_employment_criteria_are_blocked(self) -> None:
        prompt = "年龄要求不得超过30岁，形象气质好的人优先推进。"
        errors = self.manager.validate_screening_criteria(prompt)
        self.assertIn("年龄筛选", errors)
        self.assertIn("外貌或形象筛选", errors)
        with self.assertRaises(ValueError):
            self.manager.finalize_custom_prompt(prompt, "销售", "本科，有销售经验")

    def test_custom_prompt_gets_fixed_output_contract(self) -> None:
        prompt = self.manager.finalize_custom_prompt(
            "重点判断个人募资贡献、渠道来源、路演频率和产品理解。",
            "私募销售",
            "本科，能够维护券商渠道。",
        )
        self.assertIn("个人募资贡献", prompt)
        self.assertIn("岗位原始 JD", prompt)
        self.assertIn('"rating"', prompt)

    def test_read_uploaded_text_supports_utf8_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "jd.md"
            path.write_text("# Python 工程师\n熟悉 FastAPI", encoding="utf-8")
            text = self.manager.read_uploaded_text(path)
        self.assertIn("FastAPI", text)


if __name__ == "__main__":
    unittest.main()
