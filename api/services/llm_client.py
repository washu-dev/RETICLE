"""
Minimal LLM client for WashU's internal AI gateway.

Ported from prototype/script/llm_client.py, trimmed to what the API needs and
switched to httpx (the transport available in the api/ environment — no
`requests`). The gateway is an OpenAI-COMPATIBLE chat/completions endpoint
fronted by Azure AD:

    1. client-credentials OAuth2  -> short-lived bearer token
    2. POST chat/completions with `Authorization: Bearer <token>`

This is NOT the Anthropic API and NOT public OpenAI — the request/response
shape is OpenAI's (`messages` in, `choices[0].message.content` out).

FAIL-SOFT CONTRACT
------------------
If credentials are missing OR any HTTP/network error occurs, `chat()` raises
`LlmUnavailable`. The web layer catches that and returns HTTP 503 — a missing
gateway must never crash a request.

Config (env, with the api/ secret names preferred and WASHU_* fallbacks):
    WASHU_TOKEN_URL              OAuth2 token endpoint (required to be configured)
    WASHU_CHAT_URL               chat/completions URL (has a sensible default)
    WASHU_SCOPE                  OAuth2 scope
    SECURE_API_CLIENT_ID     / WASHU_CLIENT_ID       client id
    SECURE_API_CLIENT_SECRET / WASHU_CLIENT_SECRET   client secret
    SECURE_API_KEY           / WASHU_API_KEY          optional -> X-Api-Key header
"""

import os
import time

import httpx

# Default chat endpoint per WashU IT docs; token URL/scope/creds have no safe
# default and must be supplied via the environment.
DEFAULT_CHAT_URL = "https://api.openai.wustl.edu/models/v1/chat/completions"

REQUEST_TIMEOUT = float(os.getenv("WASHU_TIMEOUT", "60"))
TOKEN_EXPIRY_MARGIN = 60  # refresh this many seconds before the token expires


class LlmUnavailable(RuntimeError):
    """Raised when the LLM gateway is not configured or a call fails.

    Callers (routers) should translate this into an HTTP 503 with an {error}
    body rather than letting it bubble up as a 500.
    """


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        val = os.getenv(name)
        if val:
            return val
    return default


def _is_reasoning_model(model: str) -> bool:
    """Reasoning models (gpt-5 / o-series) reject `temperature`/`max_tokens`.

    Detect them by name so we can omit those fields for those models only.
    """
    m = (model or "").lower()
    return m.startswith("gpt-5") or m.startswith(("o1", "o3", "o4"))


class WashULLMClient:
    """Thin client for the WashU OpenAI-compatible gateway.

    Construction never touches the network — config is read from the process
    environment and the bearer token is fetched lazily and cached in memory.
    """

    def __init__(self, model: str = "gpt-4.1") -> None:
        self.model = model or os.getenv("WASHU_MODEL", "gpt-4.1")
        self.token_url = os.getenv("WASHU_TOKEN_URL", "")
        self.chat_url = os.getenv("WASHU_CHAT_URL", DEFAULT_CHAT_URL)
        self.scope = os.getenv("WASHU_SCOPE", "")
        self.client_id = _first_env("SECURE_API_CLIENT_ID", "WASHU_CLIENT_ID")
        self.client_secret = _first_env("SECURE_API_CLIENT_SECRET", "WASHU_CLIENT_SECRET")
        self.api_key = _first_env("SECURE_API_KEY", "WASHU_API_KEY")
        # TEMP dev override: providers like OpenRouter/Groq authenticate with a
        # STATIC bearer key (no OAuth2 exchange). When LLM_STATIC_BEARER is set,
        # use it directly and skip the token exchange. Leave unset in prod so the
        # WashU client-credentials path below is used.
        self.static_bearer = _first_env("LLM_STATIC_BEARER")
        self._cached_token: str | None = None
        self._token_expiry = 0.0  # epoch seconds

    # -- config -------------------------------------------------------------

    def _configured(self) -> bool:
        """True when we can authenticate — either a static bearer key (dev
        override) or enough for an OAuth2 client-credentials exchange."""
        if self.static_bearer:
            return True
        return bool(self.token_url and self.client_id and self.client_secret)

    # -- auth ---------------------------------------------------------------

    def _token(self) -> str:
        """Return a valid bearer token, minting a fresh one only when the cached
        one is missing or within `TOKEN_EXPIRY_MARGIN` of expiring.

        Raises LlmUnavailable when unconfigured or the token exchange fails.
        """
        # Dev override: a static bearer key skips the OAuth2 exchange entirely.
        if self.static_bearer:
            return self.static_bearer

        if self._cached_token and time.time() < self._token_expiry - TOKEN_EXPIRY_MARGIN:
            return self._cached_token

        if not self._configured():
            raise LlmUnavailable("WashU LLM gateway is not configured")

        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scope:
            data["scope"] = self.scope

        try:
            resp = httpx.post(
                self.token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as e:
            raise LlmUnavailable(f"Token request failed: {e}") from e

        if resp.status_code != 200:
            # Don't leak the secret; surface enough of the body to debug auth.
            raise LlmUnavailable(f"Token request failed [{resp.status_code}]")

        try:
            payload = resp.json()
            self._cached_token = payload["access_token"]
        except (ValueError, KeyError, TypeError) as e:
            raise LlmUnavailable("Token response missing access_token") from e

        self._token_expiry = time.time() + float(payload.get("expires_in", 3600))
        return self._cached_token

    # -- chat ---------------------------------------------------------------

    def chat(self, messages: list[dict], temperature: float = 0.3,
             max_tokens: int = 500) -> str:
        """Send a chat-completions request; return the assistant's text.

        `messages` is the OpenAI list-of-dicts form. Any missing config or
        HTTP/network failure is converted to LlmUnavailable — this method never
        raises a bare transport error into the caller.
        """
        token = self._token()

        body: dict = {"model": self.model, "messages": messages}
        if not _is_reasoning_model(self.model):
            if temperature is not None:
                body["temperature"] = temperature
            if max_tokens is not None:
                body["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        # Only the WashU gateway wants X-Api-Key; skip it when a static bearer
        # (OpenRouter/Groq/etc.) is driving auth so we don't leak an unrelated key.
        if self.api_key and not self.static_bearer:
            headers["X-Api-Key"] = self.api_key

        try:
            resp = httpx.post(
                self.chat_url, json=body, headers=headers, timeout=REQUEST_TIMEOUT
            )
        except httpx.HTTPError as e:
            raise LlmUnavailable(f"Chat request failed: {e}") from e

        if resp.status_code != 200:
            raise LlmUnavailable(f"Chat request failed [{resp.status_code}]")

        try:
            data = resp.json()
            content: str = data["choices"][0]["message"]["content"]
            return content
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LlmUnavailable("Unexpected chat response shape") from e
