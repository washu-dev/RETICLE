"""
RETICLE — LLM client for the WashU AI gateway
=============================================

The single place the rest of the pipeline talks to a language model. Everything
LLM-specific (auth, retries, JSON coaxing, which model) lives here so callers
stay clean — and so swapping the backing model is a one-file change.

WHAT THIS TALKS TO
------------------
`https://aiapi.wustl.edu/models/v2/messages` — WashU's current AI gateway, which
speaks the **Anthropic Messages API** and serves Claude models. Three steps of
auth, all required:

  1. client-credentials OAuth2 -> short-lived **bearer token** (~1 h)
  2. `Authorization: Bearer <token>`
  3. `X-Api-Key: <key>`  ** required — the request 401s without it **

MIGRATED FROM THE OLD OPENAI-COMPATIBLE GATEWAY (2026-07-30)
------------------------------------------------------------
The previous endpoint was `api.openai.wustl.edu/models/v1/chat/completions`,
which spoke OpenAI's shape (gpt-4.1, gpt-5, `choices[0].message.content`). It
still authenticates, so it does not fail loudly — it answers every request with
`402 "You have reached your total spend amount"`, which reads like a billing
problem rather than a dead endpoint. It cost us a day.

The two gateways METER SEPARATELY, and that is the whole explanation:

    old endpoint  ->  billed to the OAuth client   (appid 0b3b1ae6-…)  exhausted
    new endpoint  ->  billed to the API key's client (35282b3d-…)      funded

So the fix was never in the request body — it was the host, the protocol, and a
header we had never sent.

WHAT CHANGED IN THE WIRE FORMAT
-------------------------------
  system prompt   messages[{role:"system"}]        -> top-level `system` field
  token limit     optional                         -> `max_tokens` REQUIRED
  JSON mode       response_format={"type":...}     -> does not exist; ask in the
                                                      prompt (verified reliable)
  reply text      choices[0].message.content       -> content[[]].text blocks
  models          gpt-4.1 / gpt-5                  -> claude-opus-4-7, claude-haiku-4-5

Callers do NOT need to change: `chat()` still takes the OpenAI-style list with a
`system` entry and this module lifts it into the right place. That keeps the
protocol difference in one file.

NETWORK: the gateway is reachable from the WashU network only — off campus and
off VPN every call is `403 Forbidden` while the token still mints fine (Azure AD
is public). A 403 therefore means "not on the WashU network", never "bad key".

BUDGET: every response carries `apiQuotaRemaining`. This module logs it, because
the failure mode of a shared prepaid pool is that it silently drains and then
everything breaks at once.

Config comes from the project `.env` (keys WASHU_*). Smoke test:

    python3 script/llm_client.py
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Config — loaded from .env (no python-dotenv dependency; tiny loader below)
# --------------------------------------------------------------------------

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# WashU IT's published endpoints. Public configuration, not secrets.
DEFAULT_MESSAGES_URL = "https://aiapi.wustl.edu/models/v2/messages"

# Available to this API key as of the migration. Others (sonnet variants,
# opus-4-5) return 403 "your API key does not have access"; the gpt-* names are
# 404 — the new gateway is Anthropic-only.
MODEL_BEST = "claude-opus-4-7"
MODEL_CHEAP = "claude-haiku-4-5"   # ~7x cheaper per token; not currently used


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
REQUEST_TIMEOUT = float(_cfg("WASHU_TIMEOUT", "90"))
MAX_RETRIES = int(_cfg("WASHU_MAX_RETRIES", "4"))
TOKEN_EXPIRY_MARGIN = 60  # refresh this many seconds before the token expires
DEFAULT_MAX_TOKENS = 1024  # the API requires a limit; this is the fallback


class WashULLMClient:
    """Thin, reusable client for the WashU Anthropic-Messages gateway.

    Stateless from the caller's perspective except for the cached token. Safe to
    construct once and reuse for a whole batch run.
    """

    def __init__(self, model=None, session=None):
        # Not read from WASHU_MODEL: like WASHU_CHAT_URL, that key holds a
        # retired-gateway value in existing .env files (gpt-4o-mini), and honouring
        # it produces a 403 "your API key does not have access to the requested
        # model" that looks like a permissions problem rather than stale config.
        # Callers choose a model explicitly; this is only the fallback.
        self.model = model or MODEL_BEST
        self.token_url = _cfg("WASHU_TOKEN_URL", required=True)
        # Deliberately NOT WASHU_CHAT_URL: that key holds the retired
        # openai.wustl.edu address in existing .env files, and silently reusing
        # it would send us straight back to the 402 endpoint.
        self.messages_url = _cfg("WASHU_MESSAGES_URL", DEFAULT_MESSAGES_URL)
        self.client_id = _cfg("WASHU_CLIENT_ID", required=True)
        self.client_secret = _cfg("WASHU_CLIENT_SECRET", required=True)
        self.scope = _cfg("WASHU_SCOPE", required=True)
        self.api_key = _cfg("WASHU_API_KEY", required=True)  # no longer optional
        self._session = session or requests.Session()
        self._token = None
        self._token_expiry = 0.0  # epoch seconds
        self.quota_remaining = None  # last value the gateway reported

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

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    # -- chat ---------------------------------------------------------------

    @staticmethod
    def _split_system(messages):
        """Split OpenAI-style messages into (system_text, remaining_messages).

        The Messages API takes the system prompt as a top-level string rather
        than as a message. Callers still pass the OpenAI shape, so the
        translation happens here — multiple system entries are joined, which
        matches how the old endpoint concatenated them.
        """
        system_parts, rest = [], []
        for m in messages:
            if m.get("role") == "system":
                system_parts.append(m.get("content") or "")
            else:
                rest.append(m)
        return "\n\n".join(p for p in system_parts if p), rest

    def complete(self, messages, *, model=None, temperature=None,
                 max_tokens=None, response_format=None, **extra):
        """Send a request and return the FULL parsed response dict — so callers
        can read `usage`, `stop_reason`, `apiQuotaRemaining`, etc.

        `response_format` is accepted and ignored: the Messages API has no JSON
        mode. It stays in the signature so existing callers do not break; JSON is
        obtained by asking for it in the prompt, which chat_json() does.
        """
        system, msgs = self._split_system(messages)
        body = {
            "model": model or self.model,
            "messages": msgs,
            # Required by the API. A missing limit is a 400, not a default.
            "max_tokens": int(max_tokens) if max_tokens else DEFAULT_MAX_TOKENS,
        }
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        body.update(extra)
        return self._post_with_retries(body)

    @staticmethod
    def text_of(data):
        """Concatenate the text blocks of a Messages response.

        Public because callers that want `usage` or `apiCostThisCall` have to use complete(),
        and should not have to know the block structure to read the reply out of it.
        """
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise RuntimeError(f"Unexpected response shape: {json.dumps(data)[:400]}")
        # A reply can arrive as several blocks; only the text ones carry prose.
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    def chat(self, messages, **kw):
        """Send a request and return just the assistant's text.

        `messages` is the OpenAI list-of-dicts form, e.g.
            [{"role": "system", "content": "..."},
             {"role": "user",   "content": "..."}]
        """
        data = self.complete(messages, **kw)
        text = self.text_of(data)
        if not text and data.get("stop_reason") == "max_tokens":
            raise RuntimeError(
                "Gateway returned no text — the reply hit max_tokens before "
                "producing any. Raise max_tokens for this call."
            )
        return text

    def chat_json(self, messages, *, retries=1, **kw):
        """Like chat(), but expect and return a parsed JSON object.

        There is no server-side JSON mode on this API, so the contract is carried
        by the prompt. Validated in practice: with a system prompt that says
        "reply with ONLY a single valid JSON object", Claude returns bare JSON
        with no markdown fences. The fence-stripping fallback and the corrective
        retry are kept for the cases where it does not.
        """
        kw.pop("response_format", None)
        convo = list(messages)
        last_err = None
        for _attempt in range(retries + 1):
            data = self.complete(convo, **kw)
            text = self.text_of(data)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                obj = _extract_json_block(text)
                if obj is not None:
                    return obj
                # A reply cut off at the token limit is unparseable for a reason no retry can fix
                # — the next attempt truncates at the same place and bills for it again. Claude is
                # markedly more verbose than the gpt-4.1 these prompts were sized against, so this
                # is the likely first failure after the migration; say so instead of "invalid JSON".
                if data.get("stop_reason") == "max_tokens":
                    raise RuntimeError(
                        f"Reply hit max_tokens ({kw.get('max_tokens')}) and was cut off mid-JSON. "
                        f"Raise max_tokens for this call — retrying cannot help."
                    )
                last_err = text
                # Nudge the model to fix its output and try again.
                convo = list(messages) + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content":
                        "That was not valid JSON. Reply with ONLY a single valid "
                        "JSON object, no prose, no markdown fences."},
                ]
        raise RuntimeError(f"Model did not return valid JSON after "
                           f"{retries + 1} attempts. Last reply: {(last_err or '')[:400]}")

    # -- transport ----------------------------------------------------------

    def _post_with_retries(self, body):
        backoff = 1.0
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.post(
                    self.messages_url, headers=self._headers(),
                    json=body, timeout=REQUEST_TIMEOUT,
                )
            except requests.RequestException:
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 200:
                data = resp.json()
                self._note_quota(data)
                return data
            if resp.status_code == 401:
                # Either the token expired early or the API key is missing. Only
                # the first is worth retrying, and the body says which.
                if "X-Api-Key" in resp.text:
                    raise RuntimeError(f"Chat request failed [401]: {resp.text[:200]}")
                self._token = None
            if resp.status_code in (429, 500, 502, 503, 504, 401):
                if attempt == MAX_RETRIES - 1:
                    raise RuntimeError(
                        f"Chat request failed [{resp.status_code}]: {resp.text[:300]}")
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else backoff
                except ValueError:
                    delay = backoff
                time.sleep(min(delay, 30.0))
                backoff *= 2
                continue
            # Non-retryable (400 bad request, 403 off-network, 404 wrong model)
            raise RuntimeError(f"Chat request failed [{resp.status_code}]: {resp.text[:300]}")
        raise RuntimeError("Exhausted retries")

    def _note_quota(self, data):
        """Record and surface the remaining prepaid balance.

        A shared pool gives no warning of its own: it works, then every caller
        fails at once. Printing it on every call is noisy, so this only speaks up
        when the balance crosses a threshold worth acting on.
        """
        q = data.get("apiQuotaRemaining")
        if q is None:
            return
        prev, self.quota_remaining = self.quota_remaining, q
        for limit in (10.0, 5.0, 1.0):
            if q <= limit and (prev is None or prev > limit):
                print(f"[llm_client] WashU AI budget down to ${q:.2f} "
                      f"(this call cost ${data.get('apiCostThisCall', 0):.4f})",
                      file=sys.stderr)
                break


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
# Smoke test
# --------------------------------------------------------------------------

if __name__ == "__main__":
    client = WashULLMClient()
    print(f"Model:    {client.model}")
    print(f"Endpoint: {client.messages_url}")
    print("Fetching token + sending 'Hello!' ...")
    data = client.complete([{"role": "user", "content": "Hello!"}], max_tokens=64)
    print("\n--- reply ---")
    print("".join(b.get("text", "") for b in data.get("content", [])))
    print(f"\nusage: {data.get('usage')}")
    print(f"cost this call: ${data.get('apiCostThisCall', 0):.6f}")
    print(f"budget remaining: ${data.get('apiQuotaRemaining', 0):.2f}")
