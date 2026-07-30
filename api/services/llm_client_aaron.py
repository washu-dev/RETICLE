"""WashU AI gateway client (ported from prototype/script/llm_client.py).

The single place the cloud API talks to a language model. Everything LLM-specific — auth,
retries, JSON coaxing, which model — lives here so the analysis service stays clean and
swapping the backing model (or provider) is a one-file change.

WHAT THIS TALKS TO
------------------
Per the official WashU IT docs (https://it.wustl.edu/items/secure-api-access-to-ai-endpoints/),
``https://api.openai.wustl.edu/models/v1/chat/completions`` is an **OpenAI-compatible**
chat-completions endpoint fronted by Azure AD. Two steps:

  1. client-credentials OAuth2 -> short-lived **bearer token** (~1 h)
  2. POST the chat request with ``Authorization: Bearer <token>``

So this is *not* the Anthropic API — the request/response shape is OpenAI's (``messages`` in,
``choices[0].message.content`` out). Approved models: gpt-4o, gpt-4o-mini, gpt-4.1, gpt-5,
grok-3, text-embedding-3-small.

KNOWN GATEWAY STATES (what a failure here usually means)
--------------------------------------------------------
  * **402** ``"You have reached your total spend amount"`` — what this account returns *today*.
    The OAuth token step still succeeds; only the chat call is refused. Nothing in this file
    can fix it — the team has to top the account up.
  * **403** — the gateway is reachable only from the WashU network. Off-campus/off-VPN every
    chat call is APIM ``403 Forbidden`` while the token still mints fine (Azure AD is public).
    In the cloud this means the ECS task's egress is not seen as WashU.
  * **401** — token revoked early; retried once with a forced refresh.

WHAT CHANGED VERSUS THE PROTOTYPE (and nothing else)
----------------------------------------------------
  * **Credentials** resolve ``SECURE_API_*`` first (config.py maps AWS Secrets Manager into
    those names), falling back to the prototype's ``WASHU_*`` — one file works in the
    container and in local dev. There is no ``.env`` parser here; config.py already ran
    ``load_dotenv()`` before any router imports this module.
  * **Endpoint URLs** are read from the environment with documented public defaults. They are
    WashU IT's published endpoints, not secrets, so they are deliberately NOT in Secrets Manager.
  * **httpx instead of requests** — ``requests`` is not a cloud dependency. One module-level
    ``httpx.Client`` keeps the connection pool warm across requests.
  * **Token cache is process-wide and lock-guarded.** The prototype cached on the instance and
    ran single-threaded; here the service layer builds a client per request and FastAPI runs
    them on a threadpool, so a per-instance cache would mint a token per request. The token
    depends only on the (process-wide) credentials, so one shared cache is correct.
  * **Failures raise LLMUnavailable** (a RuntimeError subclass) carrying ``.status``, and every
    message is scrubbed of credential values so it is safe to surface to a client.
  * Three defensive fixes with no behavioural equivalent in the prototype: a non-numeric
    ``Retry-After`` falls back to backoff instead of raising ValueError, the honoured delay is
    capped (a threadpool worker must not be parked for minutes), and a null ``content`` on an
    otherwise-200 response raises instead of reaching the page as the text "None".

Everything here is SYNCHRONOUS on purpose — the service layer calls it through
``starlette.concurrency.run_in_threadpool``.
"""

import json
import logging
import os
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# The "advanced / more expensive" model for the AI reading.
INTERPRET_MODEL = "gpt-4.1"  # fast, capable, non-reasoning — ONLY for the CRISPR-screen analysis

# The frontier reasoning model, reserved for the Network tab's function-prediction feature — that
# task needs real multi-step reasoning over a partner dossier, not just fast text generation, so it
# gets the most capable model on the WashU gateway rather than INTERPRET_MODEL's classic gpt-4.1.
NET_PREDICT_MODEL = "gpt-5"

# ── endpoints ────────────────────────────────────────────────────────────────────────────────
# Published by WashU IT, identical for every consumer of the gateway — public configuration, not
# credentials, which is why they live here/in env rather than in AWS Secrets Manager.
_DEFAULT_TOKEN_URL = (
    "https://login.microsoftonline.com/"
    "4ccca3b5-71cd-4e6d-974b-4d9beb96c6d6/oauth2/v2.0/token"
)
_DEFAULT_CHAT_URL = "https://api.openai.wustl.edu/models/v1/chat/completions"
_DEFAULT_SCOPE = "api://bbeee386-60d6-4ba4-b9a7-631763f66065/.default"


class LLMUnavailable(RuntimeError):
    """The gateway could not answer. ``status`` is the HTTP status when there was one
    (402 spend cap, 403 off-network, 429, 5xx...) and None when there was no HTTP status to
    report — a transport failure, missing config, or a 200 whose body made no sense. The message
    is always credential-free and safe to return to a client.

    It subclasses RuntimeError so callers written against the prototype's ``except RuntimeError``
    keep working unchanged.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _TokenTransportError(LLMUnavailable):
    """A transport-level failure while minting the token, as opposed to a *rejected* credential.

    Internal only, and only so the retry loop can tell the two apart: the prototype issued its
    token request from inside the chat try/except, so a connect blip against Azure AD was retried
    with the rest. A token endpoint that answers with a non-200 stays terminal, as it was there.
    """


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
    """The gateway API key — returned ONLY when sending it has been explicitly opted into.

    Special-cased because the cloud name is ``SECURE_API_KEY`` (config.py maps
    ``RETICLE/secure_api/API_KEY`` to it), NOT ``SECURE_API_API_KEY``, so it does not fit the
    ``_cfg`` prefix pattern.

    WHY THIS IS OPT-IN RATHER THAN "send it if we have one"
    -------------------------------------------------------
    Whether the gateway *wants* ``X-Api-Key`` is UNCONFIRMED. The only request shape ever proven
    to work against api.openai.wustl.edu is bearer-token-only: the prototype's .env has no
    ``WASHU_API_KEY`` and prototype/script/llm_client.py documents the endpoint as
    "Authorization: Bearer <token> (NO X-Api-Key)". But config.py *always* populates
    ``SECURE_API_KEY`` in the container, so a naive "send it when present" would silently make
    every cloud request differ from every request we have ever validated — on the one code path
    that cannot be exercised off the WashU network. If APIM rejects an unexpected or stale
    subscription key the result is a 403, which is indistinguishable from the documented
    off-network 403 and would be misdiagnosed for hours.

    So the default matches the proven shape. Set ``SECURE_API_SEND_API_KEY=1`` to turn the header
    on once WashU IT confirms the gateway expects it (ask about ``Ocp-Apim-Subscription-Key`` too —
    that is the usual APIM header name).
    """
    if os.getenv("SECURE_API_SEND_API_KEY", "").strip().lower() not in ("1", "true", "yes"):
        return ""
    return (os.getenv("SECURE_API_KEY") or os.getenv("WASHU_API_KEY") or "").strip()


# Tunables (override via SECURE_API_* / WASHU_* if ever needed)
REQUEST_TIMEOUT = float(_cfg("TIMEOUT", "60"))
MAX_RETRIES = int(_cfg("MAX_RETRIES", "4"))
TOKEN_EXPIRY_MARGIN = 60.0  # refresh this many seconds before the token expires
TOKEN_TIMEOUT = 15.0  # the Azure AD hop runs under a lock — keep it well under REQUEST_TIMEOUT
MAX_RETRY_AFTER = 30.0  # cap on an honoured Retry-After (seconds) — see module docstring

# One pool for the whole process: the gateway is a single host and a fresh Client per request
# would pay TLS setup every time. httpx.Client is thread-safe.
_HTTP = httpx.Client(timeout=httpx.Timeout(REQUEST_TIMEOUT))

# Process-wide bearer-token cache. The token is a function of the credentials only, so it is
# shared by every client instance; the lock also collapses a cold-start stampede into one
# token request instead of one per in-flight thread.
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, Any] = {"token": None, "expiry": 0.0}


def gen_kwargs(model: str) -> dict[str, Any]:
    """gpt-5 / o-series are reasoning models: they reject `max_tokens` and a custom
    temperature, and need headroom for reasoning tokens (else the visible answer is
    empty). Everything else uses the classic params."""
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"max_completion_tokens": 3000}
    return {"temperature": 0.3, "max_tokens": 600}


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
            # RFC 7231 also allows an HTTP-date here; the prototype's bare float() would raise.
            pass
    return backoff


def _invalidate_token(stale: str | None) -> None:
    """Drop the cached token after a 401 — but only if it is still the one that failed, so we do
    not throw away a refresh another thread just completed."""
    with _TOKEN_LOCK:
        if stale is None or _TOKEN_CACHE["token"] == stale:
            _TOKEN_CACHE["token"] = None
            _TOKEN_CACHE["expiry"] = 0.0


class WashULLMClientAaron:
    """Thin, reusable client for the WashU OpenAI-compatible gateway.

    Stateless from the caller's perspective (the token cache is module-level), so constructing
    one per request is cheap — no token round-trip, no new connection pool.
    """

    def __init__(self, model: str | None = None) -> None:
        self.model = model or _cfg("MODEL", "gpt-4o-mini")
        self.token_url = _cfg("TOKEN_URL", _DEFAULT_TOKEN_URL)
        self.chat_url = _cfg("CHAT_URL", _DEFAULT_CHAT_URL)
        self.scope = _cfg("SCOPE", _DEFAULT_SCOPE)
        self.client_id = _cfg("CLIENT_ID", required=True)
        self.client_secret = _cfg("CLIENT_SECRET", required=True)
        self.api_key = _api_key()  # optional — see _api_key()

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

    def _get_token(self) -> str:
        """Return a valid bearer token, fetching a fresh one only when the cached one is missing
        or about to expire.

        Double-checked: the common case (a warm token) reads the cache WITHOUT taking the lock, so
        a slow refresh cannot stall unrelated requests. Only the fetch is serialized, and it
        re-checks after acquiring — so N threads arriving on a cold cache mint one token, not N.
        (Holding the lock across the network call was the first version; it meant one 60 s blip
        against Azure AD froze the whole LLM surface, since _post_with_retries re-enters this on
        every retry attempt.)
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
                    timeout=TOKEN_TIMEOUT,
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

    # -- chat ---------------------------------------------------------------

    def _headers(self, token: str) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

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
        """Send a chat-completions request and return the FULL parsed response dict — so callers
        can read `usage`, `finish_reason`, etc.

        This is the one public entry point that actually talks to the gateway; `chat()` and
        `chat_json()` are thin convenience wrappers over it. Callers that need token usage should
        use this rather than reaching into private transport internals.

        `temperature`/`max_tokens` are only sent if provided (some GPT-5-class models reject a
        non-default temperature). `response_format` lets you pass {"type": "json_object"} when the
        gateway supports it.
        """
        body: dict[str, Any] = {"model": model or self.model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format
        body.update(extra)
        return self._post_with_retries(body)

    def chat(self, messages: list[dict], **kw: Any) -> str:
        """Send a chat-completions request and return just the assistant's text.

        `messages` is the OpenAI list-of-dicts form, e.g.
            [{"role": "system", "content": "..."},
             {"role": "user",   "content": "..."}]
        """
        data = self.complete(messages, **kw)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMUnavailable(
                f"Unexpected response shape: {_scrub(json.dumps(data))[:400]}"
            ) from e
        if not isinstance(content, str):
            # `content` comes back null when a reasoning model spends its whole budget on
            # reasoning tokens (see gen_kwargs). The prototype returned None and the caller then
            # died on .strip(); raising here is the same outcome with a diagnosis attached — and
            # crucially not the string "None" rendered into the page. An EMPTY string is left
            # alone: that is a legitimate answer and the prototype passed it through.
            fin = data["choices"][0].get("finish_reason")
            raise LLMUnavailable(f"Gateway returned no message content (finish_reason={fin!r}).")
        return content

    def chat_json(self, messages: list[dict], *, retries: int = 1, **kw: Any) -> dict:
        """Like chat(), but expect and return a parsed JSON object.

        Requests JSON mode when possible, validates the reply parses, and on failure retries with
        a corrective message. Falls back to extracting the first {...} block if the model wraps
        JSON in prose."""
        kw.setdefault("response_format", {"type": "json_object"})
        convo = list(messages)
        last_err = None
        for _attempt in range(retries + 1):
            text = self.chat(convo, **kw)
            try:
                parsed: dict = json.loads(text)
                return parsed
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
        # NOT LLMUnavailable: the gateway answered fine, the model just would not format.
        raise RuntimeError(f"Model did not return valid JSON after "
                           f"{retries + 1} attempts. Last reply: {(last_err or '')[:400]}")

    # -- transport ----------------------------------------------------------

    def _post_with_retries(self, body: dict[str, Any]) -> dict[str, Any]:
        """Retry 429 / 5xx (and 401 once, after forcing a token refresh) with exponential backoff
        that honours Retry-After. Every other 4xx — 400 bad request, 402 spend cap, 403
        off-WashU-network — is terminal: retrying cannot change the answer."""
        backoff = 1.0
        auth_retry_used = False
        last_status: int | None = None

        for attempt in range(MAX_RETRIES):
            last = attempt == MAX_RETRIES - 1
            try:
                # Inside the try, as in the prototype: a connect blip on either hop is transient.
                token = self._get_token()
                resp = _HTTP.post(self.chat_url, headers=self._headers(token), json=body)
            except (httpx.RequestError, _TokenTransportError) as exc:
                if last:
                    if isinstance(exc, LLMUnavailable):
                        raise
                    raise LLMUnavailable(
                        f"Chat request failed (transport): {_scrub(str(exc))}"
                    ) from exc
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 200:
                try:
                    payload: dict[str, Any] = resp.json()
                except ValueError as exc:
                    raise LLMUnavailable(
                        f"Chat response was not JSON: {_body_slice(resp)}", status=200
                    ) from exc
                return payload

            last_status = resp.status_code
            retryable = resp.status_code in (429, 500, 502, 503, 504)
            if resp.status_code == 401 and not auth_retry_used:
                # Token may have been revoked early — force a refresh once. A second 401 means
                # the credentials themselves are rejected, so stop instead of burning attempts.
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
            time.sleep(_retry_delay(resp, backoff))
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
