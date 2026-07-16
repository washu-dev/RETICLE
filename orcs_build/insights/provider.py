"""LLM provider gateway (stdlib port of ai/provider.py; urllib, no httpx).

Three interchangeable providers behind one ``LLMProvider`` Protocol:
  - StubProvider     : always available, no key/network; returns "" -> templated fallback
  - OpenRouterProvider: OpenAI-compatible gateway (Gemini/OpenAI via one key)
  - GeminiProvider   : a Gemini API key directly

An offline path uses no external provider at all — the pipeline emits
the prompt (``--emit-prompt``) and ingests the produced claims (``--claims``). These
providers exist so the same module also runs fully automated when a key is present.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Protocol, runtime_checkable

from . import config


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str, *, model: str, json_schema: dict | None = None) -> str: ...


def _post_json(url: str, body: dict, headers: dict, timeout: int = 180) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


class StubProvider:
    """Deterministic, offline. Empty completion => pipeline uses the templated path."""

    name = "stub"

    def complete(self, prompt: str, *, model: str, json_schema: dict | None = None) -> str:
        return ""


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def complete(self, prompt: str, *, model: str, json_schema: dict | None = None) -> str:
        body: dict = {"model": model or self.model,
                      "messages": [{"role": "user", "content": prompt}]}
        if json_schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "insights", "schema": json_schema}}
        out = _post_json(f"{self.base_url}/chat/completions", body,
                         {"Authorization": f"Bearer {self.api_key}"})
        return out["choices"][0]["message"]["content"]


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def complete(self, prompt: str, *, model: str, json_schema: dict | None = None) -> str:
        mdl = model or self.model
        url = f"{self.base_url}/models/{mdl}:generateContent?key={self.api_key}"
        body: dict = {"contents": [{"parts": [{"text": prompt}]}]}
        if json_schema is not None:
            # Request raw JSON; the schema is also embedded in the prompt for robustness
            # (Gemini's response_schema is a strict OpenAPI subset).
            body["generationConfig"] = {"response_mime_type": "application/json"}
        out = _post_json(url, body, {})
        return out["candidates"][0]["content"]["parts"][0]["text"]


def get_provider(*, allow_external: bool = False, prefer: str | None = None) -> LLMProvider:
    """Stub unless external LLM is allowed AND a key is configured.

    ``prefer='gemini'`` picks the direct Gemini key first (recommended today, since
    OpenRouter is credit-blocked); otherwise Gemini-then-OpenRouter, both by key.
    """
    if not allow_external:
        return StubProvider()
    s = config.settings()
    if prefer in (None, "gemini") and s.gemini_api_key:
        return GeminiProvider(s.gemini_api_key, s.gemini_base_url, s.gemini_model)
    if s.openrouter_api_key:
        return OpenRouterProvider(s.openrouter_api_key, s.openrouter_base_url,
                                  s.openrouter_model_strong)
    if s.gemini_api_key:
        return GeminiProvider(s.gemini_api_key, s.gemini_base_url, s.gemini_model)
    return StubProvider()
