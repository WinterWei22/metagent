"""MiniMax-compatible LLM client shared across all tools and the orchestrator.

Read docs/LLM_INTEGRATION.md before using. Do not import openai directly in
other modules — go through this client.

Extracted and generalised from the GeneAgent workflow. Preserves the four
MiniMax gotchas (auth header, </think> stripping, JSON extraction fallback,
tiktoken approximation) in a single place.

Part 1 of Track O1 added JSONL call logging. Every `chat()` / `chat_raw()`
invocation appends one self-contained record to `logs/llm_calls.jsonl`
(overridable via `METAGENT_LLM_LOG_PATH` or `set_log_path()`). Logging is
best-effort — a failing logger prints to stderr and never changes what the
caller receives.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-M2.7"
DEFAULT_MAX_TOKENS = 127_900

# ---------------------------------------------------------------------------
# Call logging
# ---------------------------------------------------------------------------

LOG_SCHEMA_VERSION = 1
_DEFAULT_LOG_PATH: Path = (
    Path(__file__).resolve().parent.parent / "logs" / "llm_calls.jsonl"
)
_LOG_PATH: Path = Path(
    os.environ.get("METAGENT_LLM_LOG_PATH") or _DEFAULT_LOG_PATH
)


def set_log_path(path: Path | str | None) -> None:
    """Override the JSONL log file. Pass None to restore the default path."""
    global _LOG_PATH
    _LOG_PATH = Path(path) if path else _DEFAULT_LOG_PATH


def get_log_path() -> Path:
    return _LOG_PATH


# ---------------------------------------------------------------------------
# Test mocking
# ---------------------------------------------------------------------------

_MOCK_RESPONSES: list[str] | None = None
_MOCK_INDEX = 0


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
    trace_id: str | None = None,
    caller: str | None = None,
) -> str:
    """Call MiniMax, return the assistant's content with <think> blocks stripped.

    `trace_id` and `caller` are optional metadata threaded into the JSONL log
    so that downstream evaluation can join an LLM call with its originating
    identification / component. Neither affects the model request itself.
    """
    raw = chat_raw(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
        trace_id=trace_id,
        caller=caller,
    )
    return strip_thinking(raw["choices"][0]["message"]["content"])


def chat_raw(
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model: str = DEFAULT_MODEL,
    trace_id: str | None = None,
    caller: str | None = None,
) -> dict:
    """Call MiniMax, return the full response dict (for appending to history)."""
    t0 = time.perf_counter()
    timestamp = (
        _dt.datetime.now(_dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    is_mock = _MOCK_RESPONSES is not None
    response: dict | None = None
    response_raw: str | None = None

    try:
        if is_mock:
            content = _next_mock()
            response = {
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
            response_raw = content
        else:
            openai = _configure_openai()
            response = openai.ChatCompletion.create(  # type: ignore[attr-defined]
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            try:
                response_raw = response["choices"][0]["message"]["content"]
            except Exception:  # pragma: no cover — defensive; log what we have
                response_raw = None
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        _try_log(
            timestamp=timestamp,
            caller=caller,
            trace_id=trace_id,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
            response_raw=response_raw,
            response_cleaned=None,
            response=None,
            elapsed_ms=elapsed_ms,
            is_mock=is_mock,
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    response_cleaned = (
        strip_thinking(response_raw) if response_raw is not None else None
    )
    _try_log(
        timestamp=timestamp,
        caller=caller,
        trace_id=trace_id,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=messages,
        response_raw=response_raw,
        response_cleaned=response_cleaned,
        response=response,
        elapsed_ms=elapsed_ms,
        is_mock=is_mock,
        error=None,
    )
    return response  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Logging internals
# ---------------------------------------------------------------------------


def _try_log(
    *,
    timestamp: str,
    caller: str | None,
    trace_id: str | None,
    model: str,
    temperature: float,
    max_tokens: int,
    messages: list[dict],
    response_raw: str | None,
    response_cleaned: str | None,
    response: dict | None,
    elapsed_ms: int,
    is_mock: bool,
    error: dict | None,
) -> None:
    """Append one JSONL record to the configured log path. Never raises."""
    try:
        token_source = "none"
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        total_tokens: int | None = None
        cached_tokens: int | None = None
        if response is not None:
            usage = _safe_dict(response.get("usage"))
            if usage:
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")
                total_tokens = usage.get("total_tokens")
                details = _safe_dict(usage.get("prompt_tokens_details"))
                cached_tokens = details.get("cached_tokens")
                if any(
                    v is not None
                    for v in (prompt_tokens, completion_tokens, total_tokens)
                ):
                    token_source = "api"
        if token_source == "none" and error is None:
            try:
                prompt_text = "".join(
                    str(m.get("content", ""))
                    for m in messages
                    if isinstance(m, dict)
                )
                prompt_tokens = count_tokens(prompt_text)
                completion_tokens = count_tokens(response_cleaned or "")
                total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
                token_source = "tiktoken_approx"
            except Exception:  # pragma: no cover — tiktoken optional
                pass

        base_resp_status: int | None = None
        if response is not None:
            br = _safe_dict(response.get("base_resp"))
            base_resp_status = br.get("status_code")

        record = {
            "log_schema_version": LOG_SCHEMA_VERSION,
            "timestamp": timestamp,
            "caller": caller,
            "trace_id": trace_id,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
            "response_raw": response_raw,
            "response_cleaned": response_cleaned,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cached_tokens": cached_tokens,
            "token_source": token_source,
            "base_resp_status_code": base_resp_status,
            "elapsed_ms": elapsed_ms,
            "mock": is_mock,
            "error": error,
        }
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        print(
            f"[llm_client] logging failed ({_LOG_PATH}): "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def _safe_dict(obj: Any) -> dict:
    """Coerce an openai OpenAIObject / dict / None to a plain dict for .get()."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)
    except Exception:
        return {}


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
