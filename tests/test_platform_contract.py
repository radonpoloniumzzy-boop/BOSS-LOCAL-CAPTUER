from __future__ import annotations

import re
import unittest
from pathlib import Path

from core.models import BOSS_TRUSTED_PLATFORM_UID_ATTRIBUTES
from core.platform import is_boss_recommendation_url


class PlatformContractTest(unittest.TestCase):
    def test_native_favorite_accepts_only_known_boss_recommendation_pages(self) -> None:
        for url in (
            "https://www.zhipin.com/web/geek/recommend",
            "https://www.zhipin.com/web/chat/recommend?ka=menu-geek-recommend",
            "https://www.zhipin.com/web/frame/recommend/",
        ):
            self.assertTrue(is_boss_recommendation_url(url), url)
        for url in (
            "https://www.zhipin.com/web/chat/index",
            "https://www.zhipin.com/web/geek/friend",
            "https://zhipin.com.evil.example/web/geek/recommend",
            "https://www.liepin.com/web/geek/recommend",
        ):
            self.assertFalse(is_boss_recommendation_url(url), url)

    def test_python_and_extension_trusted_identity_attributes_match(self) -> None:
        contract_path = Path(__file__).parents[1] / "extension" / "identity_contract.js"
        source = contract_path.read_text(encoding="utf-8")
        block = re.search(
            r"trustedPlatformUidAttributes:\s*Object\.freeze\(\[(.*?)\]\)",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(block)
        javascript_attributes = re.findall(r'"([^"]+)"', block.group(1))
        self.assertEqual(javascript_attributes, list(BOSS_TRUSTED_PLATFORM_UID_ATTRIBUTES))


if __name__ == "__main__":
    unittest.main()
