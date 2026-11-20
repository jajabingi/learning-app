"""AI provider abstraction. Only this module knows about vendors and API keys."""
import logging
from typing import Protocol

import httpx

from app.core.config import get_settings

log = logging.getLogger("recall.ai")


class AIError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message, self.status_code = message, status_code


class AIProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str: ...


class AnthropicProvider:
    name = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, max_tokens: int):
        self._key, self.model, self._max = api_key, model, max_tokens

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        try:
            r = httpx.post(
                self.URL,
                headers={"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": self.model, "max_tokens": max_tokens or self._max, "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=120,
            )
        except httpx.HTTPError as e:
            log.error("AI request failed: %s", type(e).__name__)
            raise AIError("Could not reach the AI service") from e
        if r.status_code != 200:
            log.error("AI provider returned %s", r.status_code)  # body intentionally not logged
            raise AIError("The AI service returned an error" + (" (rate limited)" if r.status_code == 429 else ""))
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


class OpenAIProvider:
    """ChatGPT / any OpenAI-compatible chat-completions API (set OPENAI_BASE_URL for compatible vendors)."""

    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str, max_tokens: int):
        self._key, self.model, self._url, self._max = api_key, model, base_url.rstrip("/") + "/chat/completions", max_tokens

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        try:
            r = httpx.post(self._url, headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                           json={"model": self.model, "max_completion_tokens": max_tokens or self._max,
                                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, timeout=120)
        except httpx.HTTPError as e:
            log.error("AI request failed: %s", type(e).__name__)
            raise AIError("Could not reach the AI service") from e
        if r.status_code != 200:
            log.error("AI provider returned %s", r.status_code)  # body intentionally not logged
            raise AIError("The AI service returned an error" + (" (rate limited)" if r.status_code == 429 else ""))
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError):
            raise AIError("The AI service returned an unexpected response")


_override: AIProvider | None = None


def set_provider_override(p: AIProvider | None) -> None:
    """Used by tests to inject a fake provider."""
    global _override
    _override = p


def get_provider() -> AIProvider | None:
    if _override is not None:
        return _override
    s = get_settings()
    if s.ai_provider == "anthropic" and s.anthropic_api_key:
        return AnthropicProvider(s.anthropic_api_key, s.ai_model, s.ai_max_tokens)
    if s.ai_provider == "openai" and s.openai_api_key:
        return OpenAIProvider(s.openai_api_key, s.openai_model, s.openai_base_url, s.ai_max_tokens)
    return None
