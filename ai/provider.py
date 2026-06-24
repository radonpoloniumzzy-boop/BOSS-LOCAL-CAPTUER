from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ai.schemas import ScreeningDecision
from core.utils import normalize_text


RATINGS = {"UR", "SSR", "SR", "R", "N"}


class AIProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class ProviderSettings:
    provider: str
    model: str
    api_base: str
    api_key: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: int = 90


class AIProvider:
    def __init__(self, settings: ProviderSettings, logger=None) -> None:
        self.settings = settings
        self.logger = logger

    def screen(self, system_prompt: str, candidate_text: str) -> ScreeningDecision:
        raise NotImplementedError

    def test_connection(self) -> ScreeningDecision:
        return self.screen(
            "你是 API 连通性测试助手。只输出指定 JSON。",
            '请输出 {"rating":"R","persona":"API 连接正常"}',
        )

    def _api_key(self) -> str:
        value = self.settings.api_key.strip() or os.getenv(self.settings.api_key_env, "").strip()
        if not value:
            raise AIProviderError("未填写 API Key，且环境变量中也未找到密钥。")
        return value

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key()}",
                "Content-Type": "application/json",
                "User-Agent": "RecruitingLocalCapture/2.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = _extract_api_error(body) or f"HTTP {exc.code}"
            raise AIProviderError(f"AI 接口请求失败：{message}") from exc
        except urllib.error.URLError as exc:
            raise AIProviderError(f"无法连接 AI 接口：{exc.reason}") from exc
        except TimeoutError as exc:
            raise AIProviderError("AI 接口请求超时。") from exc
        except json.JSONDecodeError as exc:
            raise AIProviderError("AI 接口返回了无法解析的 JSON。") from exc


class OpenAIResponsesProvider(AIProvider):
    def screen(self, system_prompt: str, candidate_text: str) -> ScreeningDecision:
        url = _join_api_url(self.settings.api_base or "https://api.openai.com/v1", "responses")
        payload = {
            "model": self.settings.model or "gpt-5.4-mini",
            "instructions": system_prompt,
            "input": candidate_text,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "candidate_screening",
                    "strict": True,
                    "schema": _screening_json_schema(),
                }
            },
        }
        response = self._post_json(url, payload)
        raw_text = _extract_responses_text(response)
        return _parse_decision(raw_text)


class OpenAICompatibleProvider(AIProvider):
    def screen(self, system_prompt: str, candidate_text: str) -> ScreeningDecision:
        default_base = "https://api.deepseek.com" if self.settings.provider == "deepseek" else ""
        if not self.settings.api_base and not default_base:
            raise AIProviderError("自定义兼容服务必须填写 API Base。")
        url = _join_api_url(self.settings.api_base or default_base, "chat/completions")
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": candidate_text},
            ],
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 500,
        }
        if self.settings.provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        response = self._post_json(url, payload)
        try:
            raw_text = str(response["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("兼容接口响应中缺少 choices[0].message.content。") from exc
        return _parse_decision(raw_text)


def create_provider(settings: ProviderSettings, logger=None) -> AIProvider:
    provider = normalize_text(settings.provider).lower()
    if provider == "openai":
        return OpenAIResponsesProvider(settings, logger=logger)
    if provider in {"deepseek", "custom"}:
        return OpenAICompatibleProvider(settings, logger=logger)
    raise AIProviderError(f"不支持的 AI 服务商：{settings.provider}")


def _screening_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "rating": {"type": "string", "enum": ["UR", "SSR", "SR", "R", "N"]},
            "persona": {"type": "string", "minLength": 1, "maxLength": 240},
        },
        "required": ["rating", "persona"],
        "additionalProperties": False,
    }


def _join_api_url(base: str, endpoint: str) -> str:
    cleaned = str(base or "").strip().rstrip("/")
    endpoint = endpoint.strip("/")
    if cleaned.endswith(f"/{endpoint}"):
        return cleaned
    if cleaned.endswith("/v1") or endpoint.startswith("v1/"):
        return f"{cleaned}/{endpoint}"
    if cleaned.endswith("/api"):
        return f"{cleaned}/{endpoint}"
    return f"{cleaned}/{endpoint}"


def _extract_responses_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return str(response["output_text"])
    texts: list[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                texts.append(str(content["text"]))
    if not texts:
        raise AIProviderError("OpenAI Responses API 响应中没有文本输出。")
    return "\n".join(texts)


def _parse_decision(raw_text: str) -> ScreeningDecision:
    raw = str(raw_text or "").strip()
    if not raw:
        raise AIProviderError("模型没有返回评级结果。")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise AIProviderError("模型输出不是有效 JSON。")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise AIProviderError("模型输出中的 JSON 无法解析。") from exc

    rating = normalize_text(str(data.get("rating") or "")).upper()
    persona = normalize_text(str(data.get("persona") or ""))
    if rating not in RATINGS:
        raise AIProviderError(f"模型返回了无效评级：{rating or '-'}")
    if not persona:
        raise AIProviderError("模型未返回人物画像。")
    return ScreeningDecision(rating=rating, persona=persona[:240], raw_response=raw)


def _extract_api_error(body: str) -> str:
    try:
        payload = json.loads(body or "{}")
        error = payload.get("error")
        if isinstance(error, dict):
            return normalize_text(str(error.get("message") or error.get("code") or ""))
        return normalize_text(str(error or payload.get("message") or ""))
    except json.JSONDecodeError:
        return normalize_text(body)[:300]
