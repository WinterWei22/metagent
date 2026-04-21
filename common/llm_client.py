"""MiniMax-compatible LLM client shared across all tools and the orchestrator.

Read docs/LLM_INTEGRATION.md before using. Do not import openai directly in
other modules — go through this client.

Extracted and generalised from the GeneAgent workflow. Preserves the four
MiniMax gotchas (auth header, </think> stripping, JSON extraction fallback,
tiktoken approximation) in a single place.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-M2.7"
DEFAULT_MAX_TOKENS = 127_900

_MOCK_RESPONSES: list[str] | None = None
_MOCK_INDEX = 0


# ---------------------------------------------------------------------------
# Lazy setup: only import openai + requests when actually needed
# ---------------------------------------------------------------------------


def _configure_openai() -> Any:
    """Configure the legacy openai==0.28 client for MiniMax. Called on first chat()."""
    import openai
    import requests

    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "MINIMAX_API_KEY is not set. Export it or use set_mock() in tests."
        )

    openai.api_type = "open_ai"
    openai.api_base = MINIMAX_BASE_URL
    openai.api_key = api_key

    # Force Authorization header — works around openai 0.28 + custom base 1004 error.
    session = requests.Session()
    session.headers["Authorization"] = "Bearer " + api_key
    openai.requestssession = session  # type: ignore[attr-defined]

    return openai


# ---------------------------------------------------------------------------
# Test mocking
# ---------------------------------------------------------------------------


def set_mock(responses: list[str]) -> None:
    """Install a deterministic mock. Subsequent chat() calls return items in order.

    Raises IndexError once the list is exhausted, so tests fail loud if the
    model is called more times than expected.
    """
    global _MOCK_RESPONSES, _MOCK_INDEX
    _MOCK_RESPONSES = list(responses)
    _MOCK_INDEX = 0


def clear_mock() -> None:
    """Remove the mock. Use in test teardown."""
    global _MOCK_RESPONSES, _MOCK_INDEX
    _MOCK_RESPONSES = None
    _MOCK_INDEX = 0


def _next_mock() -> str:
    global _MOCK_INDEX
    if _MOCK_RESPONSES is None:
        raise RuntimeError("No mock installed.")
    if _MOCK_INDEX >= len(_MOCK_RESPONSES):
        raise IndexError(
            f"LLM mock exhausted after {_MOCK_INDEX} calls. "
            f"Add more responses via set_mock() or check for a runaway loop."
        )
    resp = _MOCK_RESPONSES[_MOCK_INDEX]
    _MOCK_INDEX += 1
    return resp


# ---------------------------------------------------------------------------
# Public API: chat
# ---------------------------------------------------------------------------


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model: str = DEFAULT_MODEL,
) -> str:
    """Call MiniMax, return the assistant's content with <think> blocks stripped."""
    raw = chat_raw(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
    )
    return strip_thinking(raw["choices"][0]["message"]["content"])


def chat_raw(
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Call MiniMax, return the full response dict (for appending to history)."""
    if _MOCK_RESPONSES is not None:
        content = _next_mock()
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "index": 0,
                    "finish_reason": "stop",
                }
            ],
            "model": model,
            "_mock": True,
        }

    openai = _configure_openai()
    response = openai.ChatCompletion.create(  # type: ignore[attr-defined]
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    # openai 0.28 returns an OpenAIObject; dict-like access works.
    return response  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def strip_thinking(text: str | None) -> str:
    """Remove MiniMax chain-of-thought delimited by </think>.

    MiniMax returns reasoning before the final answer, terminated by </think>.
    If absent, returns the original text stripped.
    """
    if not text:
        return ""
    if "</think>" not in text:
        return text.strip()
    return text.split("</think>", 1)[1].strip()


def extract_json_list(text: str | None) -> list:
    """Extract a JSON list from a possibly noisy LLM response.

    Strategy:
      1. Strip <think>.
      2. Try json.loads on the whole thing.
      3. Fall back to the last [...] block.
      4. Fall back to the last {...} block, wrapped in a list.
      5. Return [] on total failure, with a warning log. Never raises.
    """
    text = strip_thinking(text)
    if not text:
        return []

    # Direct parse
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        pass

    # Last [...] block
    i, j = text.rfind("["), text.rfind("]")
    if 0 <= i < j:
        try:
            parsed = json.loads(text[i : j + 1])
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            pass

    # Last {...} block
    i, j = text.rfind("{"), text.rfind("}")
    if 0 <= i < j:
        try:
            parsed = json.loads(text[i : j + 1])
            return [parsed]
        except json.JSONDecodeError:
            pass

    logger.warning("extract_json_list: failed to parse any JSON from response.")
    return []


def extract_process_name(text: str | None, prefix: str = "Process:") -> str:
    """Pull a 'Process: <name>' line out of a free-text LLM response.

    Generalised from GeneAgent; `prefix` lets other tools reuse the same pattern
    with e.g. 'Candidate:' or 'Identification:'.
    """
    text = strip_thinking(text)
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith(prefix):
            return line.split(prefix, 1)[1].strip()
    return ""


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


_tiktoken_enc = None


def count_tokens(text: str) -> int:
    """Approximate token count using tiktoken's gpt-4 encoding.

    MiniMax does not expose a native tokenizer. This is close enough for budget
    checks — do not use it for billing reconciliation.
    """
    global _tiktoken_enc
    if _tiktoken_enc is None:
        import tiktoken

        _tiktoken_enc = tiktoken.encoding_for_model("gpt-4")
    return len(_tiktoken_enc.encode(text))
