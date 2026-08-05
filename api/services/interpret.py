"""
AI narrative service — turns a gene footprint into a plain-language, hypothesis-
generating story via WashU's internal LLM gateway.

Two entry points back the Explorer's "interpret" and reporter-explain features:

    interpret(payload)                 -> {model, text, sources}
    reporter_explain(symbol, screens)  -> {text, process, darkness, sources}

Both build OpenAI-style system+user messages, call the shared `WashULLMClient`,
and return RAW snake_case dicts (the ported prototype contract). Neither touches
the database. If the gateway is unconfigured or a call fails, `client.chat`
raises `LlmUnavailable`, which the router turns into a 503 — these functions
deliberately let that exception propagate.

The prompt-building helpers are pure (no I/O) so they can be unit-tested with a
synthetic payload.
"""

from typing import Any

from services.llm_client import WashULLMClient

# Module-level, reused across requests (construction does no network I/O).
# Tests patch `services.interpret.client.chat`.
client = WashULLMClient()

# Cap on how many screen ids we let into a reporter-explain prompt.
MAX_REPORTER_SCREENS = 6


def _num(value: Any) -> Any:
    """Coerce to int/float for prompt text; return None if not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _summarize_block(label: str, block: Any) -> str:
    """One human-readable line describing an optional footprint block."""
    if not isinstance(block, dict) or not block:
        return f"- {label}: no data"
    parts = []
    for key, val in block.items():
        if isinstance(val, (str, int, float)) and not isinstance(val, bool):
            parts.append(f"{key}={val}")
    detail = ", ".join(parts) if parts else "present"
    return f"- {label}: {detail}"


def build_footprint_messages(payload: dict) -> list[dict]:
    """Build the system+user chat messages summarising a gene footprint.

    Pure function: given the footprint dict, returns the OpenAI-style message
    list. Unknown/missing fields degrade gracefully so a sparse payload still
    yields a usable prompt.
    """
    payload = payload or {}
    symbol = str(payload.get("symbol") or "the query gene")
    organism = str(payload.get("organism") or "Homo sapiens")
    n_total = _num(payload.get("n_total"))

    lines = [
        f"Gene: {symbol}",
        f"Organism: {organism}",
        f"Screens in footprint: {n_total if n_total is not None else 'unknown'}",
        _summarize_block("Fitness behavior", payload.get("fitness")),
        _summarize_block("Stress/context behavior", payload.get("stress")),
        _summarize_block("Reporter behavior", payload.get("reporter")),
    ]

    system = (
        "You are a cautious genomics research assistant helping a bench "
        "biologist interpret a gene's behavior across pooled CRISPR screens. "
        "Write a hypothesis-generating narrative grounded ONLY in the footprint "
        "provided. Be specific but never overclaim; frame ideas as hypotheses to "
        "test, not established fact. You MAY cite relevant literature inline as "
        "'(PMID nnnn)' when confident, otherwise omit citations."
    )
    user = (
        "Here is the gene's cross-screen footprint:\n"
        + "\n".join(lines)
        + "\n\nWrite a single 140-200 word paragraph proposing what this gene "
        "may do and how a bench biologist could follow up. Plain prose, no "
        "headers or bullet lists."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def interpret(payload: dict) -> dict:
    """Generate an AI narrative for a gene footprint.

    Returns EXACTLY {"model": <model id>, "text": <str>, "sources": []}.
    Raises LlmUnavailable (via the client) if the gateway is unavailable.
    """
    messages = build_footprint_messages(payload or {})
    text = client.chat(messages, temperature=0.3, max_tokens=500)
    return {"model": client.model, "text": text, "sources": []}


def build_reporter_messages(symbol: str, screen_ids: list[str]) -> list[dict]:
    """Pure prompt builder for reporter_explain (screen ids already capped)."""
    screens_str = ", ".join(screen_ids) if screen_ids else "none specified"
    system = (
        "You are a genomics research assistant. Explain, in plain language for a "
        "bench biologist, what biological process a fluorescent/transcriptional "
        "reporter screen is most likely reading out for the given gene, and why "
        "the gene may score in it. Keep it to ~120 words. You MAY cite '(PMID "
        "nnnn)' when confident."
    )
    user = (
        f"Gene: {symbol}\n"
        f"Reporter screen ids: {screens_str}\n\n"
        "What process does this reporter most plausibly measure, and what is the "
        "gene's likely connection to it?"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def reporter_explain(symbol: str, screen_ids: list[str]) -> dict:
    """Explain a gene's likely role in a set of reporter screens.

    `screen_ids` is capped to MAX_REPORTER_SCREENS. Returns EXACTLY
    {"text": <str>, "process": <str>, "darkness": <number|null>, "sources": []}.
    Raises LlmUnavailable (via the client) if the gateway is unavailable.
    """
    screen_ids = list(screen_ids or [])[:MAX_REPORTER_SCREENS]
    messages = build_reporter_messages(symbol, screen_ids)
    text = client.chat(messages, temperature=0.3, max_tokens=400)
    return {
        "text": text,
        "process": f"reporter readout for {symbol}",
        "darkness": None,
        "sources": [],
    }
