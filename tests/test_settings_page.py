from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.models import AppConfig
from ui.pages.settings import SettingsPage


class SettingsPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_copy_extension_pairing_code_includes_address_and_token(self) -> None:
        page = SettingsPage()
        self.addCleanup(page.deleteLater)
        page.load_config(AppConfig(local_api_port=19001, local_api_token="pair-token_123"))

        page.copy_pairing_code_button.click()

        self.assertEqual(
            QApplication.clipboard().text(),
            "boss-local://pair?apiBase=http%3A%2F%2F127.0.0.1%3A19001&apiToken=pair-token_123",
        )
        self.assertEqual(page.copy_pairing_code_button.text(), "已复制连接码")


if __name__ == "__main__":
    unittest.main()
