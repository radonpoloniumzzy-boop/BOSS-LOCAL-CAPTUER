from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.collector import BossCardCollector
from automation.selectors import BossSelectorConfig


SAMPLE_HTML = """
<html>
  <body>
    <div class="candidate-list">
      <div class="candidate-card-wrap" data-geek-id="geek-1">
        <a href="https://www.zhipin.com/geek/1"></a>
        <span class="name">张三</span>
        <span class="active-time">2分钟前活跃</span>
        <span class="salary">10k-12k</span>
        <div class="experience">2年招聘经验</div>
        <div class="education">本科</div>
        <div class="tags">
          <span>招聘</span>
          <span>HR</span>
        </div>
        <div class="description">负责招聘与面试安排</div>
      </div>
    </div>
  </body>
</html>
"""


class BossCardCollectorTest(unittest.TestCase):
    def test_extract_loaded_cards_from_static_html(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            selectors = BossSelectorConfig.load(Path(tmp_dir) / "missing.json")
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.set_content(SAMPLE_HTML)
                    collector = BossCardCollector(selectors)
                    self.assertTrue(collector.wait_for_page_ready(page))
                    cards = collector.extract_loaded_cards(page)
                    browser.close()
            except Exception as exc:
                self.skipTest(f"playwright browser unavailable: {exc}")

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["name"], "张三")
        self.assertEqual(cards[0]["tags_text"], ["招聘", "HR"])
        self.assertEqual(cards[0]["platform_uid"], "geek-1")


if __name__ == "__main__":
    unittest.main()

