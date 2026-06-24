from __future__ import annotations

import unittest

from automation.parser import CandidateParser


class CandidateParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = CandidateParser()

    def test_parse_card_uses_platform_key_when_available(self) -> None:
        record = self.parser.parse_card(
            {
                "raw_card_text": "张三 Python 招聘 10k",
                "name": "张三",
                "expected_salary": "10k-12k",
                "platform_uid": "geek-123",
            },
            job_title="招聘实习生",
            source_url="https://example.com",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.candidate_key, "platform:geek-123")

    def test_parse_card_falls_back_to_fingerprint(self) -> None:
        record = self.parser.parse_card(
            {
                "raw_card_text": "李四 数据分析 15k",
                "name": "李四",
                "expected_salary": "15k-18k",
                "work_experience_text": "2年招聘",
                "education_text": "本科",
            },
            job_title="招聘专员",
            source_url="https://example.com",
        )
        self.assertTrue(record.candidate_key.startswith("fingerprint:"))

    def test_parse_card_returns_none_for_empty_raw_text(self) -> None:
        record = self.parser.parse_card({}, job_title="招聘专员", source_url="https://example.com")
        self.assertIsNone(record)


if __name__ == "__main__":
    unittest.main()

