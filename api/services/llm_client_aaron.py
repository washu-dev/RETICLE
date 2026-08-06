"""WashU AI gateway client.

The single place the cloud API talks to a language model. Everything LLM-specific — auth, retries,
JSON coaxing, which model — lives here so the analysis service stays clean and swapping the backing
model (or provider) is a one-file change.

WHAT THIS TALKS TO
------------------
``https://aiapi.wustl.edu/models/v2/messages`` — WashU's AI gateway, which speaks the **Anthropic
Messages API** and serves Claude models. Three pieces of auth, all required:

  1. client-credentials OAuth2 -> short-lived **bearer token** (~1 h)
  2. ``Authorization: Bearer <token>``
  3. ``X-Api-Key: <key>``   ** required — the request 401s without it **

MIGRATED FROM THE OPENAI-COMPATIBLE GATEWAY (2026-07-30)
--------------------------------------------------------
The previous endpoint was ``api.openai.wustl.edu/models/v1/chat/completions``, OpenAI-shaped, with
gpt-4.1 and gpt-5. It has not been switched off — it still authenticates and then answers every
request with ``402 "You have reached your total spend amount"``, which reads like a billing problem
rather than a retired endpoint.

The two gateways METER SEPARATELY, and that is the whole explanation:

    old endpoint  ->  billed to the OAuth client     (appid 0b3b1ae6-…)  exhausted
    new endpoint  ->  billed to the API key's client (35282b3d-…)        funded

So the fix was never in the request body — it was the host, the protocol, and a header we had
never sent. If this file ever starts returning 402 again, check which host it is pointed at before
anything else.

WIRE-FORMAT DIFFERENCES THIS MODULE ABSORBS
-------------------------------------------
  system prompt   messages[{role:"system"}]      ->  top-level ``system`` field
  token limit     optional                       ->  ``max_tokens`` REQUIRED (omitting it is a 400)
  temperature     supported                      ->  REJECTED by claude-opus-4-7 ("deprecated")
  JSON mode       response_format={"type":…}     ->  does not exist; ask in the prompt
  reply text      choices[0].message.content     ->  content[] blocks of {"type":"text","text":…}

Callers keep passing the OpenAI-style message list with a ``system`` entry; the translation happens
here so the protocol lives in one file.

FAILURE MODES WORTH TELLING APART
---------------------------------
  * **401** with "X-Api-Key" in the body — the key is missing or wrong. Not retryable.
  * **403** — off the WashU network. The gateway is reachable from campus/VPN only, and the OAuth
    token still mints fine off-network (Azure AD is public), so a 403 never means "bad credentials".
  * **404** — the model name is not served here (the gpt-* names now 404).
  * **403 "does not have access to the requested model"** — the key is not entitled to that model.
  * **stop_reason == "max_tokens"** — the reply was cut off. For JSON that is unparseable, and no
    retry can fix it; see chat_json.

BUDGET: every 200 carries ``apiQuotaRemaining``. It is logged, because the failure mode of a shared
prepaid pool is that it silently drains and then every caller breaks at once.

Everything here is SYNCHRONOUS on purpose — the service layer calls it through
the bounded ``services.execution`` LLM worker pool.
"""

import json
import logging
import os
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Model for the grounded text syntheses (screen analysis, reporter explanation, the AI reading).
# Of the Claude models this API key can reach — opus-4-7 and haiku-4-5 — opus is the one chosen.
# haiku is ~7x cheaper per token if the shared budget ever gets tight; it is a one-line change.
INTERPRET_MODEL = "claude-opus-4-7"

# The Network tab's function prediction reasons over a partner dossier rather than summarising, so
# it gets the strongest available model. Same name as INTERPRET_MODEL today; kept separate because
# the two have different quality/cost tradeoffs and are tuned independently.
NET_PREDICT_MODEL = "claude-opus-4-7"

# ── endpoint ─────────────────────────────────────────────────────────────────────────────────
# Published by WashU IT — public configuration, not a credential, which is why it lives here and
# in env rather than in AWS Secrets Manager.
_DEFAULT_MESSAGES_URL = "https://aiapi.wustl.edu/models/v2/messages"
_DEFAULT_TOKEN_URL = (
    "https://login.microsoftonline.com/"
    "4ccca3b5-71cd-4e6d-974b-4d9beb96c6d6/oauth2/v2.0/token"
)
_DEFAULT_SCOPE = "api://bbeee386-60d6-4ba4-b9a7-631763f66065/.default"

# The API requires a limit on every request; this is only the fallback for callers that omit one.
DEFAULT_MAX_TOKENS = 1024


class LLMUnavailable(RuntimeError):
    """The gateway could not answer. ``status`` is the HTTP status when there was one (401 missing
    key, 403 off-network or model not entitled, 429, 5xx…) and None when there was no HTTP status
    to report — a transport failure, missing config, or a 200 whose body made no sense. The message
    is always credential-free and safe to return to a client.

    It subclasses RuntimeError so callers written against ``except RuntimeError`` keep working.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _TokenTransportError(LLMUnavailable):
    """A transport-level failure while minting the token, as opposed to a *rejected* credential.

    Internal only, and only so the retry loop can tell the two apart: a connect blip against Azure
    AD is transient, while a token endpoint that answers with a non-200 is terminal.
    """


class _RequestDeadline:
    """One wall-clock budget shared by every attempt and retry delay."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.deadline = time.monotonic() + seconds

    def remaining(self, status: int | None) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise LLMUnavailable(
                f"Chat request exceeded the {self.seconds:g}s total timeout",
                status=status,
            )
        return left

    def sleep(self, delay: float, status: int | None) -> None:
        left = self.remaining(status)
        if delay >= left:
            raise LLMUnavailable(
                f"Chat request exceeded the {self.seconds:g}s total timeout",
                status=status,
            )
        time.sleep(delay)


def _cfg(name: str, default: str = "", *, required: bool = False) -> str:
    """Resolve one setting: ``SECURE_API_<name>`` (cloud) -> ``WASHU_<name>`` (local dev) ->
    ``default``. Read lazily (never at import time) so config.py's secret load always wins the
    ordering race with whatever imports this module."""
    val = (os.getenv(f"SECURE_API_{name}") or os.getenv(f"WASHU_{name}") or default).strip()
    if required and not val:
        raise LLMUnavailable(
            f"LLM gateway not configured: set SECURE_API_{name} (cloud, via AWS Secrets "
            f"Manager) or WASHU_{name} (local dev)."
        )
    return val


def _api_key() -> str:
    """The gateway API key. REQUIRED — the endpoint 401s with "X-Api-Key header is required."

    Special-cased because the cloud name is ``SECURE_API_KEY`` (config.py maps
    ``RETICLE/secure_api/API_KEY`` to it), NOT ``SECURE_API_API_KEY``, so it does not fit the
    ``_cfg`` prefix pattern.

    This used to be optional, and briefly opt-in, on the theory that the proven request shape was
    bearer-token-only. That was true of the OLD gateway and is exactly backwards here: the key is
    also what the new gateway meters spend against, so without it there is neither auth nor budget.
    """
    key = (os.getenv("SECURE_API_KEY") or os.getenv("WASHU_API_KEY") or "").strip()
    if not key:
        raise LLMUnavailable(
            "LLM gateway not configured: set SECURE_API_KEY (cloud, via AWS Secrets Manager) "
            "or WASHU_API_KEY (local dev). The gateway requires an X-Api-Key header."
        )
    return key


# Tunables (override via SECURE_API_* / WASHU_* if ever needed)
REQUEST_TIMEOUT = max(1.0, float(_cfg("TIMEOUT", "25")))
MAX_RETRIES = max(1, int(_cfg("MAX_RETRIES", "2")))
TOTAL_TIMEOUT = max(1.0, float(_cfg("TOTAL_TIMEOUT", "45")))
TOKEN_EXPIRY_MARGIN = 60.0  # refresh this many seconds before the token expires
TOKEN_TIMEOUT = 15.0  # the Azure AD hop runs under a lock — keep it well under REQUEST_TIMEOUT
MAX_RETRY_AFTER = 5.0  # keep one gateway call inside TOTAL_TIMEOUT

# One pool for the whole process: the gateway is a single host and a fresh Client per request would
# pay TLS setup every time. httpx.Client is thread-safe.
_HTTP = httpx.Client(timeout=httpx.Timeout(REQUEST_TIMEOUT))

# Process-wide bearer-token cache. The token is a function of the credentials only, so it is shared
# by every client instance; the lock also collapses a cold-start stampede into one token request.
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, Any] = {"token": None, "expiry": 0.0}

# Last reported prepaid balance, and the thresholds already warned about (so a draining pool logs
# once per threshold rather than on every call).
_QUOTA_LOCK = threading.Lock()
_QUOTA: dict[str, Any] = {"remaining": None, "warned": set()}
_QUOTA_THRESHOLDS = (10.0, 5.0, 1.0)


def gen_kwargs(model: str, max_tokens: int = 600) -> dict[str, Any]:
    """Generation parameters for a call.

    ``max_tokens`` is REQUIRED by the Messages API — omitting it is a 400, not a default. 600 covers
    the ~200-word syntheses; callers whose reply is longer (net_predict's JSON, screen_analysis's
    per-phenotype list) pass more, because a reply truncated at the limit comes back as unparseable
    JSON rather than as an error.

    No ``temperature``: claude-opus-4-7 rejects it outright ("`temperature` is deprecated for this
    model", HTTP 400).
    """
    return {"max_tokens": max_tokens}


def _scrub(text: str) -> str:
    """Redact any configured credential (and the live bearer token) from text destined for a log
    line or an HTTP error body. Azure AD is the concrete reason this exists: AADSTS700016 echoes
    the client id straight back in its error description."""
    out = text
    secrets = [
        os.getenv("SECURE_API_CLIENT_SECRET"),
        os.getenv("WASHU_CLIENT_SECRET"),
        os.getenv("SECURE_API_CLIENT_ID"),
        os.getenv("WASHU_CLIENT_ID"),
        os.getenv("SECURE_API_KEY"),
        os.getenv("WASHU_API_KEY"),
        _TOKEN_CACHE.get("token"),  # plain dict read — atomic, no lock needed
    ]
    for raw in secrets:
        val = (raw or "").strip()
        # The length guard stops a stray one-character value from shredding the whole message.
        if len(val) >= 8 and val in out:
            out = out.replace(val, "***")
    return out


def _body_slice(resp: httpx.Response, limit: int = 300) -> str:
    """A short, credential-free excerpt of a gateway response — scrub first, then truncate, so a
    secret straddling the cut cannot survive in halves."""
    return _scrub(resp.text)[:limit]


def _retry_delay(resp: httpx.Response, backoff: float) -> float:
    """Honour Retry-After when the gateway sends one, else exponential backoff."""
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return max(0.0, min(float(raw), MAX_RETRY_AFTER))
        except ValueError:
            # RFC 7231 also allows an HTTP-date here; a bare float() would raise.
            pass
    return backoff


def _invalidate_token(stale: str | None) -> None:
    """Drop the cached token after a 401 — but only if it is still the one that failed, so we do
    not throw away a refresh another thread just completed."""
    with _TOKEN_LOCK:
        if stale is None or _TOKEN_CACHE["token"] == stale:
            _TOKEN_CACHE["token"] = None
            _TOKEN_CACHE["expiry"] = 0.0


def _note_quota(data: dict[str, Any]) -> None:
    """Record the remaining prepaid balance and warn as it drains.

    A shared pool gives no warning of its own: it works, then every caller fails at once. Logging
    the number on every call would be noise, so this only speaks up when a threshold is crossed.
    """
    q = data.get("apiQuotaRemaining")
    if not isinstance(q, int | float):
        return
    with _QUOTA_LOCK:
        _QUOTA["remaining"] = float(q)
        for limit in _QUOTA_THRESHOLDS:
            if q <= limit and limit not in _QUOTA["warned"]:
                _QUOTA["warned"].add(limit)
                logger.warning(
                    "WashU AI prepaid budget down to $%.2f (this call cost $%.4f)",
                    q, data.get("apiCostThisCall", 0.0),
                )
                break


def quota_remaining() -> float | None:
    """Last balance the gateway reported, or None if no call has succeeded yet."""
    q = _QUOTA["remaining"]
    return float(q) if q is not None else None


class WashULLMClientAaron:
    """Thin, reusable client for the WashU Anthropic-Messages gateway.

    Stateless from the caller's perspective (the token cache is module-level), so constructing one
    per request is cheap — no token round-trip, no new connection pool.
    """

    def __init__(self, model: str | None = None) -> None:
        # Not read from an env var: SECURE_API_MODEL / WASHU_MODEL hold a retired-gateway value
        # (gpt-4o-mini) in existing .env files, and honouring it yields a 403 "your API key does
        # not have access to the requested model" that looks like a permissions problem rather
        # than stale config. Callers choose a model explicitly; this is only the fallback.
        self.model = model or INTERPRET_MODEL
        self.token_url = _cfg("TOKEN_URL", _DEFAULT_TOKEN_URL)
        # Deliberately NOT CHAT_URL: that key holds the retired openai.wustl.edu address in
        # existing .env files, and silently reusing it would send us back to the 402 endpoint.
        self.messages_url = _cfg("MESSAGES_URL", _DEFAULT_MESSAGES_URL)
        self.scope = _cfg("SCOPE", _DEFAULT_SCOPE)
        self.client_id = _cfg("CLIENT_ID", required=True)
        self.client_secret = _cfg("CLIENT_SECRET", required=True)
        self.api_key = _api_key()

    def __repr__(self) -> str:
        # Explicit, so an incidental repr() in a log line or traceback can never spill a secret.
        return f"WashULLMClientAaron(model={self.model!r})"

    # -- auth ---------------------------------------------------------------

    @staticmethod
    def _cached_token() -> str | None:
        """The cached token if it is still comfortably valid, else None. Lock-free on purpose —
        see _get_token."""
        cached = _TOKEN_CACHE["token"]
        if cached and time.time() < float(_TOKEN_CACHE["expiry"]) - TOKEN_EXPIRY_MARGIN:
            return str(cached)
        return None

    def _get_token(self, timeout: float = TOKEN_TIMEOUT) -> str:
        """Return a valid bearer token, fetching a fresh one only when the cached one is missing
        or about to expire.

        Double-checked: the common case (a warm token) reads the cache WITHOUT taking the lock, so
        a slow refresh cannot stall unrelated requests. Only the fetch is serialized, and it
        re-checks after acquiring — so N threads arriving on a cold cache mint one token, not N.
        """
        warm = self._cached_token()
        if warm:
            return warm

        with _TOKEN_LOCK:
            # Re-check: another thread may have refreshed while we waited for the lock.
            warm = self._cached_token()
            if warm:
                return warm

            try:
                resp = _HTTP.post(
                    self.token_url,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "scope": self.scope,
                    },
                    # Shorter than REQUEST_TIMEOUT: this hop is a small Azure AD call, and it runs
                    # under the lock, so it must never park other threads for a full minute.
                    timeout=max(0.1, min(TOKEN_TIMEOUT, timeout)),
                )
            except httpx.RequestError as exc:
                raise _TokenTransportError(
                    f"Token request failed (transport): {_scrub(str(exc))}"
                ) from exc

            if resp.status_code != 200:
                # Enough of the body to debug auth, with every credential value redacted.
                raise LLMUnavailable(
                    f"Token request failed [{resp.status_code}]: {_body_slice(resp)}",
                    status=resp.status_code,
                )
            try:
                payload: dict[str, Any] = resp.json()
            except ValueError as exc:
                raise LLMUnavailable(
                    f"Token response was not JSON [{resp.status_code}].",
                    status=resp.status_code,
                ) from exc

            token = payload.get("access_token")
            if not token:
                # Deliberately no body excerpt: whatever came back may itself be a token.
                raise LLMUnavailable(
                    "Token response contained no access_token.", status=resp.status_code
                )
            _TOKEN_CACHE["token"] = token
            _TOKEN_CACHE["expiry"] = time.time() + float(payload.get("expires_in", 3600))
            return str(token)

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    # -- chat ---------------------------------------------------------------

    @staticmethod
    def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
        """Split OpenAI-style messages into (system_text, remaining_messages).

        The Messages API takes the system prompt as a top-level string rather than as a message.
        Callers still pass the OpenAI shape, so the translation happens here — multiple system
        entries are joined, matching how the old endpoint concatenated them.
        """
        system_parts: list[str] = []
        rest: list[dict] = []
        for m in messages:
            if m.get("role") == "system":
                system_parts.append(m.get("content") or "")
            else:
                rest.append(m)
        return "\n\n".join(p for p in system_parts if p), rest

    @staticmethod
    def _text_of(data: dict[str, Any]) -> str:
        """Concatenate the text blocks of a Messages response."""
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise LLMUnavailable(f"Unexpected response shape: {_scrub(json.dumps(data))[:400]}")
        # A reply can arrive as several blocks; only the text ones carry prose.
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Send a request and return the FULL parsed response dict — so callers can read ``usage``,
        ``stop_reason``, ``apiQuotaRemaining``, etc.

        ``temperature`` and ``response_format`` are accepted and IGNORED: claude-opus-4-7 rejects
        the first outright, and the Messages API has no JSON mode. They stay in the signature so
        existing callers do not break; JSON is obtained by asking for it in the prompt, which
        chat_json() does.
        """
        system, msgs = self._split_system(messages)
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": msgs,
            # Required by the API. A missing limit is a 400, not a default.
            "max_tokens": int(max_tokens) if max_tokens else DEFAULT_MAX_TOKENS,
        }
        if system:
            body["system"] = system
        body.update(extra)
        return self._post_with_retries(body)

    def chat(self, messages: list[dict], **kw: Any) -> str:
        """Send a request and return just the assistant's text.

        `messages` is the OpenAI list-of-dicts form, e.g.
            [{"role": "system", "content": "..."},
             {"role": "user",   "content": "..."}]
        """
        data = self.complete(messages, **kw)
        text = self._text_of(data)
        if not text and data.get("stop_reason") == "max_tokens":
            raise LLMUnavailable(
                "Gateway returned no text — the reply hit max_tokens before producing any. "
                "Raise max_tokens for this call."
            )
        return text

    def chat_json(self, messages: list[dict], *, retries: int = 0, **kw: Any) -> dict:
        """Like chat(), but expect and return a parsed JSON object.

        There is no server-side JSON mode on this API, so the contract is carried by the prompt.
        Validated in practice: with a system prompt that says "reply with ONLY a single valid JSON
        object", Claude returns bare JSON with no markdown fences. Fence stripping remains the
        fallback; callers may explicitly request a corrective retry, but request paths default to
        zero so one malformed answer cannot double the total gateway wall clock.
        """
        kw.pop("response_format", None)
        convo = list(messages)
        last_err = None
        for _attempt in range(retries + 1):
            data = self.complete(convo, **kw)
            text = self._text_of(data)
            try:
                parsed: dict = json.loads(text)
                return parsed
            except json.JSONDecodeError:
                obj = _extract_json_block(text)
                if obj is not None:
                    return obj
                # A reply cut off at the token limit is unparseable for a reason no retry can fix —
                # the next attempt truncates at the same place and bills for it again. Claude is
                # markedly more verbose than the gpt-4.1 these prompts were sized against, so this
                # is the likely first failure after the migration; say so instead of "invalid JSON".
                if data.get("stop_reason") == "max_tokens":
                    raise LLMUnavailable(
                        f"Reply hit max_tokens ({kw.get('max_tokens')}) and was cut off mid-JSON. "
                        f"Raise max_tokens for this call — retrying cannot help."
                    ) from None
                last_err = text
                # Nudge the model to fix its output and try again.
                convo = list(messages) + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content":
                        "That was not valid JSON. Reply with ONLY a single valid "
                        "JSON object, no prose, no markdown fences."},
                ]
        # NOT LLMUnavailable: the gateway answered fine, the model just would not format.
        raise RuntimeError(f"Model did not return valid JSON after "
                           f"{retries + 1} attempts. Last reply: {(last_err or '')[:400]}")

    # -- transport ----------------------------------------------------------

    def _post_with_retries(self, body: dict[str, Any]) -> dict[str, Any]:
        """Retry 429 / 5xx (and 401 once, after forcing a token refresh) with exponential backoff
        that honours Retry-After. Every other 4xx — 400 bad request, 403 off-network or model not
        entitled, 404 unknown model — is terminal: retrying cannot change the answer."""
        backoff = 1.0
        auth_retry_used = False
        last_status: int | None = None
        budget = _RequestDeadline(TOTAL_TIMEOUT)

        for attempt in range(MAX_RETRIES):
            last = attempt == MAX_RETRIES - 1
            try:
                # Inside the try, as before: a connect blip on either hop is transient.
                token = self._get_token(budget.remaining(last_status))
                resp = _HTTP.post(
                    self.messages_url,
                    headers=self._headers(token),
                    json=body,
                    timeout=max(
                        0.1,
                        min(REQUEST_TIMEOUT, budget.remaining(last_status)),
                    ),
                )
            except (httpx.RequestError, _TokenTransportError) as exc:
                if last:
                    if isinstance(exc, LLMUnavailable):
                        raise
                    raise LLMUnavailable(
                        f"Chat request failed (transport): {_scrub(str(exc))}"
                    ) from exc
                budget.sleep(backoff, last_status)
                backoff *= 2
                continue

            if resp.status_code == 200:
                try:
                    payload: dict[str, Any] = resp.json()
                except ValueError as exc:
                    raise LLMUnavailable(
                        f"Chat response was not JSON: {_body_slice(resp)}", status=200
                    ) from exc
                _note_quota(payload)
                return payload

            last_status = resp.status_code
            retryable = resp.status_code in (429, 500, 502, 503, 504)
            if resp.status_code == 401 and not auth_retry_used:
                # A missing/incorrect X-Api-Key also 401s, and no token refresh fixes that — the
                # body distinguishes them, so only retry the token case.
                if "X-Api-Key" in resp.text:
                    raise LLMUnavailable(
                        f"Chat request failed [401]: {_body_slice(resp)}", status=401
                    )
                auth_retry_used = True
                _invalidate_token(token)
                retryable = True

            if not retryable or last:
                raise LLMUnavailable(
                    f"Chat request failed [{resp.status_code}]: {_body_slice(resp)}",
                    status=resp.status_code,
                )

            logger.warning(
                "WashU gateway returned %s (attempt %d/%d) — retrying",
                resp.status_code, attempt + 1, MAX_RETRIES,
            )
            budget.sleep(_retry_delay(resp, backoff), last_status)
            backoff *= 2

        raise LLMUnavailable("Chat request failed: exhausted retries", status=last_status)


def _extract_json_block(text: str) -> dict | None:
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
                    obj: dict = json.loads(text[start:i + 1])
                    return obj
                except json.JSONDecodeError:
                    return None
    return None
