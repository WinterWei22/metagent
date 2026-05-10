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
_DEFAULT_MINIMAX_MODEL = "MiniMax-M2.7"

# Provider switch (env-driven). Default is the historical MiniMax path so
# every existing test/runner stays bit-identical. Set
# `METAGENT_LLM_PROVIDER=openai` to route via an OpenAI-compatible endpoint
# (real OpenAI, viviai.cc relay, Azure OAI, etc.).
PROVIDER = (os.environ.get("METAGENT_LLM_PROVIDER") or "minimax").strip().lower()

# OpenAI-compat config (only consulted when PROVIDER=='openai').
_OPENAI_BASE_URL = (
    os.environ.get("METAGENT_OPENAI_BASE_URL") or "https://api.openai.com/v1"
).rstrip("/")
_OPENAI_DEFAULT_MODEL = os.environ.get("METAGENT_OPENAI_MODEL") or "gpt-5.5"

DEFAULT_MODEL = (
    _OPENAI_DEFAULT_MODEL if PROVIDER == "openai" else _DEFAULT_MINIMAX_MODEL
)
# OpenAI's reasoning-class models reject the legacy 127.9k MiniMax cap.
# Use a per-provider default; runtime callers can still pass max_tokens
# explicitly to override.
DEFAULT_MAX_TOKENS = 16_384 if PROVIDER == "openai" else 127_900

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


# ---------------------------------------------------------------------------
# Retry-with-backoff (phase A3 D0b)
# ---------------------------------------------------------------------------

# A2 audit § 5 debt #5: 3 / 60 verifier calls hit MiniMax 600s read timeout
# or HTTP 529 ("当前服务集群负载较高 ... 2064"). v4 full pilot would be
# ~28 failed calls without retry. Retry with jittered backoff resolves the
# transient failures cheaply.
#
# Default retries=3 with backoff approximately 10 s / 30 s / 60 s plus
# jitter; total max wait ~2 min per call, well inside any per-task
# total_timeout budget.

DEFAULT_MAX_RETRIES = int(os.environ.get("METAGENT_LLM_MAX_RETRIES", "3"))


def _default_retry_backoff() -> list[float]:
    import random
    return [
        random.uniform(8.0, 12.0),    # ~10 s ± 2
        random.uniform(25.0, 35.0),   # ~30 s ± 5
        random.uniform(50.0, 70.0),   # ~60 s ± 10
    ]


# Substring patterns matched against ``str(exc)`` for retry classification.
# MiniMax overloaded error: returns 200 OK with body code 2064 + http_code 529.
_RETRYABLE_ERROR_PATTERNS = (
    "529", "2064", "503", "502", "500",
    "overloaded_error",
    "请稍后重试",
    "服务集群负载",
)


def _is_retryable_exception(exc: BaseException) -> bool:
    """Classify whether an LLM-call exception should be retried.

    Retried:
      - openai.error.Timeout (read / connect timeout)
      - openai.error.APIConnectionError (proxy disconnect, DNS failure)
      - openai.error.ServiceUnavailableError (some 5xx paths)
      - openai.error.APIError when its message contains 5xx / 529 / 2064 /
        MiniMax-specific overload phrases

    Not retried (fast-fail surfacing the bug):
      - openai.error.AuthenticationError (bad API key)
      - openai.error.InvalidRequestError (malformed request — retry won't help)
      - openai.error.RateLimitError (429 — caller should slow down, not retry)
      - generic Exception types we don't recognise
    """
    name = type(exc).__name__
    if name in {"Timeout", "APIConnectionError", "ServiceUnavailableError"}:
        return True
    if name == "APIError":
        msg = str(exc)
        return any(p in msg for p in _RETRYABLE_ERROR_PATTERNS)
    return False


def _create_with_retry(
    openai_module: Any,
    create_kwargs: dict,
    *,
    max_retries: int,
    backoff: list[float],
    caller: str | None,
    trace_id: str | None,
) -> dict:
    """Wrap ``openai.ChatCompletion.create`` in a retry loop.

    On a retryable exception (see :func:`_is_retryable_exception`), sleeps
    ``backoff[attempt]`` seconds (jittered) and retries up to
    ``max_retries`` times. The first non-retryable exception, or the
    final exhausted attempt, raises through. A retry occurrence is
    logged via ``logger.warning`` so audits can spot which calls were
    re-driven without full traceback noise.
    """
    attempt = 0
    while True:
        try:
            return openai_module.ChatCompletion.create(  # type: ignore[attr-defined]
                **create_kwargs,
            )
        except Exception as exc:
            if not _is_retryable_exception(exc):
                raise
            if attempt >= max_retries:
                raise
            wait = backoff[min(attempt, len(backoff) - 1)] if backoff else 1.0
            logger.warning(
                "chat retry attempt %d/%d after %s: %s — sleeping %.1fs (caller=%s, trace=%s)",
                attempt + 1, max_retries, type(exc).__name__,
                str(exc)[:120], wait, caller, trace_id,
            )
            time.sleep(wait)
            attempt += 1

# Separate mock channel for chat_with_tools() — each element is an assistant
# message dict with optional `tool_calls`. Kept distinct from the string-mode
# mock so that the legacy `chat()` path stays bit-identical.
_MOCK_TOOL_MESSAGES: list[dict] | None = None
_MOCK_TOOL_INDEX = 0


def _configure_openai(provider: str = PROVIDER) -> Any:
    """Configure the legacy openai==0.28 client for the active provider.

    Provider choice is driven by ``METAGENT_LLM_PROVIDER`` (default
    ``minimax``). The openai 0.28 SDK is reused for both — only the
    base URL + API key + auth-header workaround differ.
    """
    import openai
    import requests

    if provider == "openai":
        api_key = os.environ.get("METAGENT_OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "METAGENT_LLM_PROVIDER=openai but METAGENT_OPENAI_API_KEY is unset."
            )
        base_url = (
            os.environ.get("METAGENT_OPENAI_BASE_URL") or _OPENAI_BASE_URL
        ).rstrip("/")
    else:
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "MINIMAX_API_KEY is not set. Export it or use set_mock() in tests."
            )
        base_url = MINIMAX_BASE_URL

    openai.api_type = "open_ai"
    openai.api_base = base_url
    openai.api_key = api_key

    # Force Authorization header — works around openai 0.28 + custom base 1004 error.
    # Note: requests.Session uses HTTP/1.1 by default, which sidesteps the HTTP/2
    # POST-corruption issue we observed at certain proxies (see Track Sub-6 fixes).
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


def set_mock_tool_messages(messages: list[dict]) -> None:
    """Install a deterministic mock for chat_with_tools().

    Each entry is an assistant ``message`` dict, e.g.::

        {"role": "assistant", "content": null,
         "tool_calls": [{"id": "call_1", "type": "function",
                          "function": {"name": "...", "arguments": "{...}"}}]}

    Distinct from set_mock() so the legacy chat() path is untouched.
    """
    global _MOCK_TOOL_MESSAGES, _MOCK_TOOL_INDEX
    _MOCK_TOOL_MESSAGES = list(messages)
    _MOCK_TOOL_INDEX = 0


def clear_mock_tool_messages() -> None:
    global _MOCK_TOOL_MESSAGES, _MOCK_TOOL_INDEX
    _MOCK_TOOL_MESSAGES = None
    _MOCK_TOOL_INDEX = 0


def _next_tool_mock() -> dict:
    global _MOCK_TOOL_INDEX
    if _MOCK_TOOL_MESSAGES is None:
        raise RuntimeError("No tool-mock installed.")
    if _MOCK_TOOL_INDEX >= len(_MOCK_TOOL_MESSAGES):
        raise IndexError(
            f"chat_with_tools mock exhausted after {_MOCK_TOOL_INDEX} calls. "
            f"Add more responses via set_mock_tool_messages()."
        )
    msg = _MOCK_TOOL_MESSAGES[_MOCK_TOOL_INDEX]
    _MOCK_TOOL_INDEX += 1
    return msg


# ---------------------------------------------------------------------------
# Public API: chat
# ---------------------------------------------------------------------------


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    model: str = DEFAULT_MODEL,
    provider: str | None = None,
    trace_id: str | None = None,
    caller: str | None = None,
    max_retries: int | None = None,
    retry_backoff_seconds: list[float] | tuple[float, ...] | None = None,
) -> str:
    """Call MiniMax, return the assistant's content with <think> blocks stripped.

    `trace_id` and `caller` are optional metadata threaded into the JSONL log
    so that downstream evaluation can join an LLM call with its originating
    identification / component. Neither affects the model request itself.

    Retry behaviour: phase A3 D0b enables retry-with-jittered-backoff for
    transient 5xx / 529 / Timeout / APIConnectionError. Default
    ``max_retries=DEFAULT_MAX_RETRIES`` (=3 unless ``METAGENT_LLM_MAX_RETRIES``
    overrides). Callers that need fail-fast (e.g. unit tests) can pass
    ``max_retries=0``.
    """
    raw = chat_raw(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
        provider=provider,
        trace_id=trace_id,
        caller=caller,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    return strip_thinking(raw["choices"][0]["message"]["content"])


def chat_raw(
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    model: str = DEFAULT_MODEL,
    provider: str | None = None,
    trace_id: str | None = None,
    caller: str | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    max_retries: int | None = None,
    retry_backoff_seconds: list[float] | tuple[float, ...] | None = None,
) -> dict:
    """Call MiniMax / OpenAI-compat, return the full response dict.

    ``tools`` and ``tool_choice`` are pass-through OpenAI-style fields.
    Both providers accept this shape: viviai relay handles it transparently
    for Opus / GPT (verified phase A1), and MiniMax's M2.7 endpoint
    accepts the same ``tools=[{type, function:{name, description,
    parameters}}]`` schema and returns ``tool_calls[*].function.
    {name, arguments}`` (verified phase A2 D0 live probe).

    Retry (phase A3 D0b): on transient errors (Timeout, APIConnectionError,
    HTTP 5xx / 529 / MiniMax overload code 2064) the call is retried up to
    ``max_retries`` times with jittered backoff. Mock channel skips retry
    so unit tests that inject mock failures fail-fast and remain
    deterministic.
    """
    active_provider = (provider or PROVIDER).strip().lower()
    if max_tokens is None:
        max_tokens = 16_384 if active_provider == "openai" else DEFAULT_MAX_TOKENS
    if max_retries is None:
        max_retries = DEFAULT_MAX_RETRIES
    if retry_backoff_seconds is None:
        retry_backoff_seconds = _default_retry_backoff()
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
            openai = _configure_openai(active_provider)
            # OpenAI deprecated `max_tokens` for reasoning-class models
            # (gpt-5.x / o1 / o3 / o4) in favour of
            # `max_completion_tokens`. Switch the field at the wire level
            # for the openai provider; MiniMax keeps the legacy name.
            create_kwargs: dict = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if active_provider == "openai":
                create_kwargs["max_completion_tokens"] = max_tokens
            else:
                create_kwargs["max_tokens"] = max_tokens
            if tools:
                # Both providers accept the same OpenAI-style ``tools`` /
                # ``tool_choice`` shape:
                #   - openai (viviai) — verified in phase A1 against Opus 4.7.
                #   - minimax — verified via live probe in phase A2 D0.
                # No adapter needed; MiniMax's response carries the same
                # ``tool_calls[*].function.{name, arguments}`` keys.
                create_kwargs["tools"] = tools
                if tool_choice is not None:
                    create_kwargs["tool_choice"] = tool_choice
            response = _create_with_retry(
                openai,
                create_kwargs,
                max_retries=max_retries,
                backoff=list(retry_backoff_seconds),
                caller=caller,
                trace_id=trace_id,
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
# Tool-calling support (Phase A1)
# ---------------------------------------------------------------------------


def _to_plain(obj: Any) -> Any:
    """Recursively convert OpenAIObject / dict / list to plain Python.

    The legacy openai 0.28 SDK returns ``OpenAIObject`` instances, which
    behave like dicts but do not JSON-serialise cleanly. The agent_tools
    dispatcher consumes plain dicts only, so we flatten once at the
    boundary.
    """
    if isinstance(obj, list):
        return [_to_plain(x) for x in obj]
    if hasattr(obj, "items"):  # dict / OpenAIObject
        return {k: _to_plain(v) for k, v in obj.items()}
    return obj


def chat_with_tools(
    messages: list[dict],
    *,
    tools: list[dict],
    tool_choice: str | dict = "auto",
    temperature: float = 0.0,
    max_tokens: int | None = None,
    model: str = DEFAULT_MODEL,
    provider: str | None = None,
    trace_id: str | None = None,
    caller: str | None = None,
    max_retries: int | None = None,
    retry_backoff_seconds: list[float] | tuple[float, ...] | None = None,
) -> dict:
    """Single-turn function-calling chat. Returns the assistant message dict.

    Unlike :func:`chat`, this returns the FULL message including any
    ``tool_calls`` array (or ``content`` when the LLM produced a text
    answer). Caller is responsible for the multi-turn ReAct loop.

    Returned shape::

        {"role": "assistant",
         "content": str | None,
         "tool_calls": [{"id": str, "type": "function",
                          "function": {"name": str, "arguments": str}}, ...]}

    Mock support: when ``set_mock_tool_messages([...])`` is installed,
    the next dict from the mock list is returned verbatim, the network
    is not touched, and a JSONL log entry is still written.
    """
    if _MOCK_TOOL_MESSAGES is not None:
        msg = _next_tool_mock()
        # Best-effort log so test traces look like real ones.
        timestamp = (
            _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        _try_log(
            timestamp=timestamp,
            caller=caller,
            trace_id=trace_id,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
            messages=messages,
            response_raw=json.dumps(msg, ensure_ascii=False, default=str),
            response_cleaned=msg.get("content"),
            response={"choices": [{"message": msg}], "_mock": True},
            elapsed_ms=0,
            is_mock=True,
            error=None,
        )
        return _to_plain(msg)

    response = chat_raw(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
        provider=provider,
        trace_id=trace_id,
        caller=caller,
        tools=tools,
        tool_choice=tool_choice,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    msg = _to_plain(response["choices"][0]["message"])
    # Strip MiniMax-style ``<think>...</think>`` reasoning blocks from
    # ``content`` so the ReAct runner sees clean narrative text. The
    # legacy ``chat()`` path already does this; mirror it here for
    # tool-calling responses. No-op for OpenAI / Claude content.
    content = msg.get("content")
    if isinstance(content, str):
        msg["content"] = strip_thinking(content)
    return msg


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
