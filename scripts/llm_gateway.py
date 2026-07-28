"""
RETICLE — LLM gateway (WashU Secure API, multi-provider, config-driven).

One place the pipeline talks to a language model. Which model/provider is used is
driven entirely by scripts/llm_config.json (edit that, not this file). The WashU
Secure API (aiapi.wustl.edu) exposes each provider through its NATIVE payload
shape, so this module has one adapter per style:

  provider  endpoint (v2)           api_style            payload/response
  --------  ----------------------  -------------------  ---------------------------
  claude    /models/v2/messages     anthropic_messages   {model,max_tokens,messages,system?}  -> content[0].text
  gpt       /models/v2/chat/completions  openai_chat     {model,messages}                     -> choices[0].message.content
  gemini    /models/v2/generateContent   gemini_generate {model,contents:[{role,parts}],systemInstruction?} -> candidates[0].content.parts[0].text

AUTH (never stored here or in git):
  - client_id / client_secret / api_key come from AWS Secrets Manager
    (RETICLE/secure_api/*); the Azure tenant from RETICLE/sso/TENANT_ID.
  - client-credentials OAuth2 to login.microsoftonline.com -> short-lived bearer
    token (cached). Every request: Authorization: Bearer <token> + <api_key_header>.

Callers use a single normalized interface:
    gw = LLMGateway()                       # default model from config
    obj = gw.chat_json([{ "role":"system","content":...},
                        { "role":"user","content":...}], model="claude-opus-5")

Requires: requests, boto3 (see scripts/requirements.txt). Network access is
limited to the WashU network (VPN/campus) — off-network calls 403.
"""

import json
import os
import time
from pathlib import Path

import requests

_CONFIG_PATH = os.environ.get("RETICLE_LLM_CONFIG",
                              str(Path(__file__).resolve().parent / "llm_config.json"))
_TOKEN_EXPIRY_MARGIN = 60
_REQUEST_TIMEOUT = float(os.environ.get("RETICLE_LLM_TIMEOUT", "90"))
_MAX_RETRIES = int(os.environ.get("RETICLE_LLM_MAX_RETRIES", "4"))


def _load_config(path=_CONFIG_PATH):
    with open(path) as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Secrets — AWS Secrets Manager (with per-key env override for local/dry use)
# --------------------------------------------------------------------------

def _boto_session(region):
    import boto3
    role_arn = os.environ.get("RETICLE_SECRETS_ROLE_ARN")
    if not role_arn:
        return boto3.session.Session(region_name=region)
    sts = boto3.client("sts", region_name=region)
    creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="reticle-llm")["Credentials"]
    return boto3.session.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


def _fetch_secret(secret_id, region, _cache={}):
    """Return a secret string. Env override RETICLE_SECRET__<sanitized id> wins
    (handy for local dry-runs); otherwise AWS Secrets Manager. Cached per id."""
    env_key = "RETICLE_SECRET__" + secret_id.replace("/", "_").replace("-", "_").upper()
    if os.environ.get(env_key):
        return os.environ[env_key]
    if secret_id in _cache:
        return _cache[secret_id]
    client = _boto_session(region).client("secretsmanager", region_name=region)
    val = client.get_secret_value(SecretId=secret_id)["SecretString"]
    _cache[secret_id] = val
    return val


# --------------------------------------------------------------------------
# Provider adapters — normalize [{role,content}] -> native body; parse -> text
# --------------------------------------------------------------------------

def _split_system(messages):
    """Return (system_text_or_None, [non-system messages])."""
    sys_txt = None
    rest = []
    for m in messages:
        if m.get("role") == "system":
            sys_txt = (sys_txt + "\n" if sys_txt else "") + m["content"]
        else:
            rest.append(m)
    return sys_txt, rest


def _build_anthropic(model, messages, max_tokens, temperature, want_json):
    sys_txt, rest = _split_system(messages)
    body = {"model": model, "max_tokens": max_tokens or 1024,
            "messages": [{"role": m["role"], "content": m["content"]} for m in rest]}
    if sys_txt:
        body["system"] = sys_txt
    if temperature is not None:
        body["temperature"] = temperature
    return body


def _parse_anthropic(data):
    parts = data.get("content") or []
    for blk in parts:
        if blk.get("type") == "text":
            return blk.get("text", "")
    raise RuntimeError(f"Unexpected Anthropic response: {json.dumps(data)[:400]}")


def _build_openai(model, messages, max_tokens, temperature, want_json):
    body = {"model": model, "messages": messages}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature
    if want_json:
        body["response_format"] = {"type": "json_object"}
    return body


def _parse_openai(data):
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Unexpected OpenAI response: {json.dumps(data)[:400]}") from e


def _build_gemini(model, messages, max_tokens, temperature, want_json):
    sys_txt, rest = _split_system(messages)
    contents = [{"role": ("model" if m["role"] == "assistant" else "user"),
                 "parts": [{"text": m["content"]}]} for m in rest]
    body = {"model": model, "contents": contents}
    if sys_txt:
        body["systemInstruction"] = {"parts": [{"text": sys_txt}]}
    gen = {}
    if max_tokens is not None:
        gen["maxOutputTokens"] = max_tokens
    if temperature is not None:
        gen["temperature"] = temperature
    if want_json:
        gen["responseMimeType"] = "application/json"
    if gen:
        body["generationConfig"] = gen
    return body


def _parse_gemini(data):
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Unexpected Gemini response: {json.dumps(data)[:400]}") from e


_ADAPTERS = {
    "anthropic_messages": (_build_anthropic, _parse_anthropic),
    "openai_chat":        (_build_openai,    _parse_openai),
    "gemini_generate":    (_build_gemini,    _parse_gemini),
}


# --------------------------------------------------------------------------
# Gateway
# --------------------------------------------------------------------------

class LLMGateway:
    def __init__(self, model=None, config_path=_CONFIG_PATH, session=None):
        self.cfg = _load_config(config_path)
        self.default_model = model or self.cfg["default_model"]
        self._auth = self.cfg["auth"]
        self._session = session or requests.Session()
        self._token = None
        self._token_expiry = 0.0

    # -- model routing --
    def _resolve(self, model):
        model = model or self.default_model
        m = self.cfg["models"].get(model)
        if not m:
            raise ValueError(f"Model '{model}' not enabled in llm_config.json "
                             f"(enabled: {sorted(self.cfg['models'])})")
        prov = self.cfg["providers"][m["provider"]]
        return model, prov

    # -- auth --
    def _secret(self, key):
        return _fetch_secret(self._auth["secret_ids"][key], self._auth["aws_region"])

    def _get_token(self):
        if self._token and time.time() < self._token_expiry - _TOKEN_EXPIRY_MARGIN:
            return self._token
        tenant = self._secret("tenant_id")
        token_url = self._auth["token_url_template"].format(tenant=tenant)
        resp = self._session.post(
            token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials",
                  "client_id": self._secret("client_id"),
                  "client_secret": self._secret("client_secret"),
                  "scope": self._auth["scope"]},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Token request failed [{resp.status_code}]: {resp.text[:200]}")
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + float(payload.get("expires_in", 3600))
        return self._token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            self._auth.get("api_key_header", "X-Api-Key"): self._secret("api_key"),
        }

    # -- transport --
    def _post(self, url, body):
        backoff = 1.0
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._session.post(url, headers=self._headers(), json=body,
                                          timeout=_REQUEST_TIMEOUT)
            except requests.RequestException:
                if attempt == _MAX_RETRIES - 1:
                    raise
                time.sleep(backoff); backoff *= 2; continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401:
                self._token = None
            if resp.status_code in (401, 429, 500, 502, 503, 504):
                if attempt == _MAX_RETRIES - 1:
                    raise RuntimeError(f"LLM request failed [{resp.status_code}]: {resp.text[:200]}")
                ra = resp.headers.get("Retry-After")
                time.sleep(float(ra) if ra else backoff); backoff *= 2; continue
            raise RuntimeError(f"LLM request failed [{resp.status_code}]: {resp.text[:200]}")
        raise RuntimeError("Exhausted retries")

    # -- public API --
    def chat(self, messages, *, model=None, max_tokens=None, temperature=None, want_json=False):
        model, prov = self._resolve(model)
        build, parse = _ADAPTERS[prov["api_style"]]
        if max_tokens is None and prov.get("requires_max_tokens"):
            max_tokens = prov.get("default_max_tokens", 1024)
        body = build(model, messages, max_tokens, temperature, want_json)
        return parse(self._post(prov["endpoint"], body))

    def chat_json(self, messages, *, model=None, retries=1, **kw):
        kw["want_json"] = True
        convo = list(messages)
        last = None
        for _ in range(retries + 1):
            text = self.chat(convo, model=model, **kw)
            obj = _first_json(text)
            if obj is not None:
                return obj
            last = text
            convo = list(messages) + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "That was not valid JSON. Reply with ONLY a single valid JSON object."},
            ]
        raise RuntimeError(f"Model returned no valid JSON. Last: {str(last)[:300]}")


def _first_json(text):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    start = (text or "").find("{")
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


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Smoke-test the LLM gateway")
    ap.add_argument("--model", default=None)
    ap.add_argument("--prompt", default="Reply with a JSON object {\"ok\": true}.")
    args = ap.parse_args()
    gw = LLMGateway(model=args.model)
    print("model:", args.model or gw.default_model)
    print(gw.chat_json([{"role": "user", "content": args.prompt}]))
