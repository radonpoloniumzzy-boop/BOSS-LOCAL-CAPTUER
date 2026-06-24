from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.browser import BrowserService
from core.exceptions import PlatformBlockedError
from core.models import AppConfig


class BrowserServiceTest(unittest.TestCase):
    def test_zhipin_url_bypasses_playwright_and_opens_regular_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = AppConfig(
                browser_path="",
                user_data_dir=str(Path(tmp_dir) / "profile"),
                default_export_dir=str(Path(tmp_dir) / "exports"),
                selectors_path=str(Path(tmp_dir) / "selectors.json"),
                target_url="https://www.zhipin.com/web/geek/recommend",
            )
            service = BrowserService()
            with patch.object(service, "_open_regular_browser") as open_regular:
                with self.assertRaises(PlatformBlockedError):
                    service.open_browser(config, target_url=config.target_url)
            open_regular.assert_called_once()


if __name__ == "__main__":
    unittest.main()
