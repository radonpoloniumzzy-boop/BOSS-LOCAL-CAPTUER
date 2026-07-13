from __future__ import annotations

import unittest
from unittest.mock import patch

from core.credentials import CredentialStore, MemoryCredentialBackend, normalize_api_base


class CredentialStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = MemoryCredentialBackend()
        self.store = CredentialStore(self.backend)

    def test_round_trip_uses_provider_and_normalized_base(self) -> None:
        reference = self.store.save("OpenAI", "HTTPS://API.OPENAI.COM/v1/", "secret-key")

        self.assertTrue(reference.startswith("BossLocalCapture/"))
        self.assertEqual(self.store.read("openai", "https://api.openai.com/v1"), "secret-key")
        self.assertNotIn("secret-key", reference)

    def test_delete_and_environment_fallback(self) -> None:
        self.store.save("deepseek", "https://api.deepseek.com", "saved-key")
        self.assertTrue(self.store.delete("deepseek", "https://api.deepseek.com/"))
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "env-key"}, clear=True):
            self.assertEqual(
                self.store.resolve("deepseek", "https://api.deepseek.com", "", "DEEPSEEK_API_KEY"),
                "env-key",
            )

    def test_explicit_key_wins_without_being_logged_in_reference(self) -> None:
        self.store.save("openai", "https://api.openai.com/v1", "saved-key")
        self.assertEqual(
            self.store.resolve("openai", "https://api.openai.com/v1", "typed-key", ""),
            "typed-key",
        )

    def test_normalize_api_base_rejects_credentials_and_non_http_urls(self) -> None:
        self.assertEqual(normalize_api_base(" HTTPS://Example.COM/v1/ "), "https://example.com/v1")
        for value in ["not-a-url", "file:///tmp/api", "https://user:pass@example.com/v1"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_api_base(value)


if __name__ == "__main__":
    unittest.main()
