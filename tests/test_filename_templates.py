from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.filename_templates import render_filename, unique_path


class FilenameTemplateTest(unittest.TestCase):
    def test_shared_fixtures(self) -> None:
        fixtures = json.loads(
            (Path(__file__).parent / "fixtures" / "filename_templates.json").read_text(encoding="utf-8")
        )
        for fixture in fixtures:
            with self.subTest(template=fixture["template"], values=fixture["values"]):
                self.assertEqual(
                    render_filename(fixture["template"], fixture["values"]),
                    fixture["expected"],
                )

    def test_unknown_variables_and_path_traversal_are_safe(self) -> None:
        rendered = render_filename("../../{candidate_name}_{missing}", {"candidate_name": "A/B"})
        self.assertNotIn("..", rendered)
        self.assertNotIn("/", rendered)
        self.assertIn("unknown", rendered)

    def test_unique_path_keeps_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            first = Path(tmp_dir) / "resume.pdf"
            first.write_text("old", encoding="utf-8")
            second = unique_path(first)
            second.write_text("new", encoding="utf-8")
            third = unique_path(first)

            self.assertEqual(second.name, "resume_2.pdf")
            self.assertEqual(third.name, "resume_3.pdf")
            self.assertEqual(first.read_text(encoding="utf-8"), "old")


if __name__ == "__main__":
    unittest.main()
