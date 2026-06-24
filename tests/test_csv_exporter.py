from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from core.models import CandidateRecord
from storage.csv_exporter import CsvExporter
from storage.db import DatabaseManager
from storage.export_service import ExportService
from storage.repository import CandidateRepository


class ExportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)
        self.export_service = ExportService(self.repository)
        self.csv_exporter = CsvExporter(self.repository)

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def test_csv_export_batch_uses_requested_column_order(self) -> None:
        batch = self._insert_sample_candidate()
        export_dir = Path(self.temp_dir.name) / "exports"

        result = self.csv_exporter.export(
            mode="batch",
            export_dir=export_dir,
            columns=["name", "expected_salary", "raw_card_text"],
            batch_id=batch.id,
            job_title="校招 C++ 工程师",
        )

        self.assertEqual(result.export_format, "csv")
        self.assertTrue(Path(result.file_path).exists())
        with Path(result.file_path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        self.assertEqual(rows[0], ["name", "expected_salary", "raw_card_text"])
        self.assertEqual(rows[1][0], "张三")

    def test_jsonl_export_keeps_structured_fields(self) -> None:
        batch = self._insert_sample_candidate()
        export_dir = Path(self.temp_dir.name) / "exports"

        result = self.export_service.export(
            export_format="jsonl",
            mode="batch",
            export_dir=export_dir,
            columns=["name", "expected_salary", "raw_card_text"],
            batch_id=batch.id,
            job_title="校招 C++ 工程师",
        )

        self.assertEqual(result.export_format, "jsonl")
        lines = Path(result.file_path).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["name"], "张三")
        self.assertEqual(payload["raw_card_text"], "张三 原始文本")
        self.assertEqual(payload["batch_id"], batch.id)

    def test_markdown_export_contains_summary_sections(self) -> None:
        batch = self._insert_sample_candidate()
        export_dir = Path(self.temp_dir.name) / "exports"

        result = self.export_service.export(
            export_format="markdown",
            mode="batch",
            export_dir=export_dir,
            columns=["name", "expected_salary", "raw_card_text"],
            batch_id=batch.id,
            job_title="校招 C++ 工程师",
        )

        self.assertEqual(result.export_format, "markdown")
        content = Path(result.file_path).read_text(encoding="utf-8")
        self.assertIn("# 候选人导出摘要", content)
        self.assertIn("## 1. 张三", content)
        self.assertIn("### 原始卡片文本", content)
        self.assertIn("张三 原始文本", content)

    def _insert_sample_candidate(self):
        batch = self.repository.create_batch("校招 C++ 工程师", "https://example.com")
        candidate = CandidateRecord(
            candidate_key="platform:1",
            raw_text_hash="hash-1",
            job_title="校招 C++ 工程师",
            source_url="https://example.com",
            capture_time="2026-04-07T10:00:00",
            raw_card_text="张三 原始文本",
            name="张三",
            active_status="今日活跃",
            expected_salary="10k-12k",
            work_experience_text="1 年 C++ 开发",
            education_text="本科",
            tags_text="C++, Linux",
            summary_text="做过编译器和基础库。",
            detail_url="https://example.com/detail/1",
        )
        self.repository.upsert_batch_candidates(batch.id, [candidate])
        return batch


if __name__ == "__main__":
    unittest.main()
