"""
RETICLE — LLM client for the WashU AI gateway (Phase 2 support infrastructure)
==============================================================================

The single place the rest of the pipeline talks to a language model. Everything
LLM-specific (auth, retries, JSON coaxing, which model) lives here so the
extractor and any future caller stay clean — and so swapping the backing model
(or moving to a different provider) is a one-file change.

WHAT THIS TALKS TO
------------------
Per the official WashU IT docs
(https://it.wustl.edu/items/secure-api-access-to-ai-endpoints/),
`https://api.openai.wustl.edu/models/v1/chat/completions` is an
**OpenAI-compatible** chat-completions endpoint, fronted by Azure AD. Two steps:

  1. client-credentials OAuth2 → short-lived **bearer token** (~1 h)
  2. POST the chat request with `Authorization: Bearer <token>` (NO X-Api-Key)

So this is *not* the Anthropic API — the request/response shape is OpenAI's
(`messages` in, `choices[0].message.content` out). The roadmap's "Claude API"
language predates the gateway; approved models are gpt-4o, gpt-4o-mini, gpt-4.1,
gpt-5, grok-3, text-embedding-3-small.

NETWORK: access is limited to the WashU network — you must be on campus or VPN,
otherwise every call returns APIM `403 Forbidden` (the token still mints fine,
since that comes from public Azure AD).

DESIGN NOTES
------------
* The token is cached in memory and reused until ~60 s before it expires; we do
  NOT mint a token per request (that would be slow and hammer Azure AD).
* Transient failures (429 / 5xx / timeouts) are retried with exponential backoff.
* `chat_json()` asks the model for strict JSON, validates it parses, and retries
  once with a corrective nudge — the extractor wants structured output, not prose.
* Zero new dependencies: stdlib + `requests` (already in the env).

Config is read from the project `.env` (see keys WASHU_*). Smoke test:

    python3 script/llm_client.py            # runs the manager's "Hello!" example
"""

import json
import os
import time
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Config — loaded from .env (no python-dotenv dependency; tiny loader below)
# --------------------------------------------------------------------------

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_env(path=_ENV_PATH):
    """Populate os.environ from a `KEY = value` .env file (does not overwrite
    anything already set in the real environment)."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_env()


def _cfg(key, default=None, required=False):
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(
            f"Missing config '{key}'. Set it in {_ENV_PATH} or the environment."
        )
    return val


# Tunables (override via env if ever needed)
REQUEST_TIMEOUT = float(_cfg("WASHU_TIMEOUT", "60"))
MAX_RETRIES = int(_cfg("WASHU_MAX_RETRIES", "4"))
TOKEN_EXPIRY_MARGIN = 60  # refresh this many seconds before the token expires


class WashULLMClient:
    """Thin, reusable client for the WashU OpenAI-compatible gateway.

    Stateless from the caller's perspective except for the cached token. Safe to
    construct once and reuse for a whole batch run.
    """

    def __init__(self, model=None, session=None):
        self.model = model or _cfg("WASHU_MODEL", "gpt-4o-mini")
        self.token_url = _cfg("WASHU_TOKEN_URL", required=True)
        self.chat_url = _cfg("WASHU_CHAT_URL", required=True)
        self.client_id = _cfg("WASHU_CLIENT_ID", required=True)
        self.client_secret = _cfg("WASHU_CLIENT_SECRET", required=True)
        self.scope = _cfg("WASHU_SCOPE", required=True)
        self.api_key = _cfg("WASHU_API_KEY")  # optional
        self._session = session or requests.Session()
        self._token = None
        self._token_expiry = 0.0  # epoch seconds

    # -- auth ---------------------------------------------------------------

    def _get_token(self):
        """Return a valid bearer token, fetching a fresh one only when the
        cached one is missing or about to expire."""
        if self._token and time.time() < self._token_expiry - TOKEN_EXPIRY_MARGIN:
            return self._token

        resp = self._session.post(
            self.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            # Don't leak the secret; surface enough of the body to debug auth.
            raise RuntimeError(
                f"Token request failed [{resp.status_code}]: {resp.text[:300]}"
            )
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + float(payload.get("expires_in", 3600))
        return self._token

    # -- chat ---------------------------------------------------------------

    def _headers(self):
        h = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

    def complete(self, messages, *, model=None, temperature=None,
                 max_tokens=None, response_format=None, **extra):
        """Send a chat-completions request and return the FULL parsed response
        dict — so callers can read `usage`, `finish_reason`, etc.

        This is the one public entry point that actually talks to the gateway;
        `chat()` and `chat_json()` are thin convenience wrappers over it. Callers
        that need token usage should use this rather than reaching into private
        transport internals.

        `temperature`/`max_tokens` are only sent if provided (some GPT-5-class
        models reject a non-default temperature). `response_format` lets you pass
        {"type": "json_object"} when the gateway supports it.
        """
        body = {"model": model or self.model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format
        body.update(extra)
        return self._post_with_retries(body)

    def chat(self, messages, **kw):
        """Send a chat-completions request and return just the assistant's text.

        `messages` is the OpenAI list-of-dicts form, e.g.
            [{"role": "system", "content": "..."},
             {"role": "user",   "content": "..."}]
        """
        data = self.complete(messages, **kw)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"Unexpected response shape: {json.dumps(data)[:400]}") from e

    def chat_json(self, messages, *, retries=1, **kw):
        """Like chat(), but expect and return a parsed JSON object.

        Requests JSON mode when possible, validates the reply parses, and on
        failure retries with a corrective message. Falls back to extracting the
        first {...} block if the model wraps JSON in prose."""
        kw.setdefault("response_format", {"type": "json_object"})
        convo = list(messages)
        last_err = None
        for attempt in range(retries + 1):
            text = self.chat(convo, **kw)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                obj = _extract_json_block(text)
                if obj is not None:
                    return obj
                last_err = text
                # Nudge the model to fix its output and try again.
                convo = list(messages) + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content":
                        "That was not valid JSON. Reply with ONLY a single valid "
                        "JSON object, no prose, no markdown fences."},
                ]
        raise RuntimeError(f"Model did not return valid JSON after "
                           f"{retries + 1} attempts. Last reply: {last_err[:400]}")

    # -- transport ----------------------------------------------------------

    def _post_with_retries(self, body):
        backoff = 1.0
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.post(
                    self.chat_url, headers=self._headers(),
                    json=body, timeout=REQUEST_TIMEOUT,
                )
            except requests.RequestException as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401:
                # Token may have been revoked early — force a refresh once.
                self._token = None
            if resp.status_code in (429, 500, 502, 503, 504) or resp.status_code == 401:
                if attempt == MAX_RETRIES - 1:
                    raise RuntimeError(
                        f"Chat request failed [{resp.status_code}]: {resp.text[:300]}")
                retry_after = resp.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else backoff)
                backoff *= 2
                continue
            # Non-retryable (e.g. 400 bad request)
            raise RuntimeError(f"Chat request failed [{resp.status_code}]: {resp.text[:300]}")
        raise RuntimeError("Exhausted retries")


def _extract_json_block(text):
    """Best-effort: pull the first balanced {...} object out of a string."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# --------------------------------------------------------------------------
# Smoke test — mirrors the manager's two-step example
# --------------------------------------------------------------------------

if __name__ == "__main__":
    client = WashULLMClient()
    print(f"Model: {client.model}")
    print("Fetching token + sending 'Hello!' ...")
    reply = client.chat([{"role": "user", "content": "Hello!"}])
    print("\n--- reply ---")
    print(reply)
