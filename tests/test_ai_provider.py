from __future__ import annotations

import io
import unittest
import urllib.error
from unittest.mock import patch

from ai.provider import (
    AIProviderError,
    OpenAICompatibleProvider,
    OpenAIResponsesProvider,
    ProviderSettings,
    _join_api_url,
    _parse_decision,
    validate_provider_settings,
)


class _FakeResponsesProvider(OpenAIResponsesProvider):
    def __init__(self) -> None:
        super().__init__(
            ProviderSettings(
                provider="openai",
                model="gpt-5.4-mini",
                api_base="https://api.openai.com/v1",
                api_key="test-key",
            )
        )
        self.request_url = ""
        self.request_payload = {}

    def _post_json(self, url, payload):
        self.request_url = url
        self.request_payload = payload
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"rating":"SR","persona":"有渠道维护记录，独立募资贡献尚未验证。"}',
                        }
                    ],
                }
            ]
        }


class _FakeDeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self) -> None:
        super().__init__(
            ProviderSettings(
                provider="deepseek",
                model="deepseek-v4-flash",
                api_base="https://api.deepseek.com",
                api_key="test-key",
            )
        )
        self.request_payload = {}

    def _post_json(self, _url, payload):
        self.request_payload = payload
        return {"choices": [{"message": {"content": '{"rating":"R","persona":"证据不足，不能高评。"}'}}]}


class AIProviderTest(unittest.TestCase):
    def test_openai_responses_uses_strict_compact_schema(self) -> None:
        provider = _FakeResponsesProvider()

        decision = provider.screen("system", "candidate")

        self.assertEqual(decision.rating, "SR")
        self.assertEqual(provider.request_url, "https://api.openai.com/v1/responses")
        schema = provider.request_payload["text"]["format"]["schema"]
        self.assertTrue(provider.request_payload["text"]["format"]["strict"])
        self.assertEqual(schema["properties"]["persona"]["maxLength"], 240)
        self.assertIn("confidence", schema["required"])
        self.assertIn("recommended_action", schema["properties"])

    def test_deepseek_uses_json_mode_and_disables_thinking(self) -> None:
        provider = _FakeDeepSeekProvider()

        decision = provider.screen("system", "candidate")

        self.assertEqual(decision.rating, "R")
        self.assertEqual(provider.request_payload["response_format"], {"type": "json_object"})
        self.assertEqual(provider.request_payload["thinking"], {"type": "disabled"})

    def test_parse_decision_rejects_unknown_rating(self) -> None:
        with self.assertRaises(AIProviderError):
            _parse_decision('{"rating":"A","persona":"invalid"}')

    def test_parse_decision_keeps_structured_fields(self) -> None:
        decision = _parse_decision(
            """
            {
              "rating": "SSR",
              "persona": "SaaS sales evidence is explicit.",
              "confidence": "high",
              "evidence": [{"item": "SaaS", "evidence": "5 years CRM sales"}],
              "gaps": ["quota not shown"],
              "risks": ["recent job change"],
              "recommended_action": "priority_outreach"
            }
            """
        )

        self.assertEqual(decision.confidence, "high")
        self.assertEqual(decision.evidence, [{"item": "SaaS", "evidence": "5 years CRM sales"}])
        self.assertEqual(decision.gaps, ["quota not shown"])
        self.assertEqual(decision.risks, ["recent job change"])
        self.assertEqual(decision.recommended_action, "priority_outreach")

    def test_join_api_url_does_not_duplicate_endpoint(self) -> None:
        self.assertEqual(
            _join_api_url("https://example.com/v1/responses", "responses"),
            "https://example.com/v1/responses",
        )

    def test_validate_provider_settings_requires_api_key_before_batch_run(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(AIProviderError, "OPENAI_API_KEY"):
                validate_provider_settings(
                    ProviderSettings(
                        provider="openai",
                        model="gpt-5.4-mini",
                        api_base="https://api.openai.com/v1",
                        api_key_env="OPENAI_API_KEY",
                    )
                )

    def test_validate_provider_settings_accepts_environment_api_key(self) -> None:
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
            validate_provider_settings(
                ProviderSettings(
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    api_base="https://api.deepseek.com",
                    api_key_env="DEEPSEEK_API_KEY",
                )
            )

    def test_http_errors_redact_api_key_from_status_message(self) -> None:
        provider = OpenAICompatibleProvider(
            ProviderSettings(
                provider="custom",
                model="model",
                api_base="https://example.com/v1",
                api_key="top-secret-key",
            )
        )
        error = urllib.error.HTTPError(
            "https://example.com/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":{"message":"bad top-secret-key"}}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(AIProviderError) as raised:
                provider.screen("system", "candidate")

        self.assertNotIn("top-secret-key", str(raised.exception))
        self.assertIn("[REDACTED]", str(raised.exception))

    def test_validate_provider_settings_rejects_invalid_api_base_before_network(self) -> None:
        with self.assertRaises(AIProviderError):
            validate_provider_settings(
                ProviderSettings(
                    provider="custom",
                    model="model",
                    api_base="not-a-url",
                    api_key="key",
                )
            )


if __name__ == "__main__":
    unittest.main()
