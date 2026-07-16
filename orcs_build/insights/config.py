"""Tiny stdlib settings for the insight layer.

Replaces ``apps/api/reticle_api/config.py``'s pydantic ``Settings`` with a
dependency-free reader. Values come from ``os.environ`` first, then from the same
gitignored ``infra/env/.env`` the API uses (parsed as plain ``KEY=VALUE`` lines) so
a single credential store serves both. No secret is ever written to an output file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# orcs_build/ -> repo root is two levels up (repo/orcs_build/insights/config.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILES = (
    _REPO_ROOT / "infra" / "env" / ".env",
    _REPO_ROOT / ".env",
)


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                out[key] = val
    except OSError:
        return {}
    return out


@lru_cache(maxsize=1)
def _file_env() -> dict[str, str]:
    merged: dict[str, str] = {}
    for f in _ENV_FILES:
        merged.update(_parse_env_file(f))
    return merged


def _get(key: str, default: str = "") -> str:
    """os.environ wins; otherwise fall back to the .env file; otherwise default."""
    if key in os.environ and os.environ[key] != "":
        return os.environ[key]
    return _file_env().get(key, default)


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model_strong: str
    gemini_api_key: str
    gemini_base_url: str
    gemini_model: str


def settings() -> Settings:
    return Settings(
        openrouter_api_key=_get("OPENROUTER_API_KEY"),
        openrouter_base_url=_get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_model_strong=_get("OPENROUTER_MODEL_STRONG", "openai/gpt-4o"),
        gemini_api_key=_get("GEMINI_API_KEY") or _get("GOOGLE_API_KEY"),
        gemini_base_url=_get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
        gemini_model=_get("GEMINI_MODEL", "gemini-2.5-pro"),
    )
