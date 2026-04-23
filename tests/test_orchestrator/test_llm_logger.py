"""Unit tests for the JSONL call logger added to common.llm_client (Part 1).

All tests drive chat()/chat_raw() through set_mock(); no real MiniMax call.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common import llm_client


def _read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


@pytest.fixture
def tmp_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the JSONL logger to a tmp file for each test."""
    path = tmp_path / "llm_calls.jsonl"
    monkeypatch.setattr(llm_client, "_LOG_PATH", path)
    yield path
    llm_client.clear_mock()


def test_llm_logger_appends_jsonl(tmp_log: Path) -> None:
    llm_client.set_mock(["hello there"])
    out = llm_client.chat(
        [{"role": "user", "content": "hi"}],
        trace_id="trace-appends-001",
        caller="test.llm_logger.appends",
    )
    assert out == "hello there"
    lines = _read_lines(tmp_log)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["log_schema_version"] == 1
    assert rec["trace_id"] == "trace-appends-001"
    assert rec["caller"] == "test.llm_logger.appends"
    assert rec["messages"] == [{"role": "user", "content": "hi"}]
    assert rec["response_raw"] == "hello there"
    assert rec["response_cleaned"] == "hello there"
    assert rec["mock"] is True
    assert rec["error"] is None
    assert rec["model"] == llm_client.DEFAULT_MODEL
    assert rec["max_tokens"] == llm_client.DEFAULT_MAX_TOKENS
    assert rec["temperature"] == 0.0
    assert isinstance(rec["elapsed_ms"], int) and rec["elapsed_ms"] >= 0
    # Timestamp is ISO-8601 UTC with milliseconds, ending in Z.
    assert rec["timestamp"].endswith("Z")
    # No usage on mock responses; logger should fall back to tiktoken.
    assert rec["token_source"] in {"tiktoken_approx", "none"}


def test_llm_logger_doesnt_break_on_unwritable_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A read-only / unresolvable log path must never break the LLM call."""
    # A regular file masquerading as a directory — mkdir(parents=True) fails.
    regular_file = tmp_path / "regfile"
    regular_file.write_text("not a directory")
    bogus_log = regular_file / "nested" / "llm_calls.jsonl"
    monkeypatch.setattr(llm_client, "_LOG_PATH", bogus_log)

    llm_client.set_mock(["still_returned"])
    out = llm_client.chat([{"role": "user", "content": "x"}])
    assert out == "still_returned", "logging failure must not change return value"

    stderr = capsys.readouterr().err
    assert "logging failed" in stderr
    assert not bogus_log.exists()


def test_llm_logger_captures_raw_and_cleaned_separately(tmp_log: Path) -> None:
    """A response with a </think> block logs the raw pre-strip text in
    response_raw and the post-strip_thinking text in response_cleaned."""
    raw_text = "<think>step-by-step reasoning here</think>final answer"
    llm_client.set_mock([raw_text])
    out = llm_client.chat([{"role": "user", "content": "q"}])
    assert out == "final answer"

    lines = _read_lines(tmp_log)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["response_raw"] == raw_text
    assert rec["response_cleaned"] == "final answer"


def test_llm_logger_preserves_return_value(
    tmp_log: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chat() returns the same value regardless of whether logging worked."""
    llm_client.set_mock(["answer_a"])
    a = llm_client.chat([{"role": "user", "content": "q"}])
    assert a == "answer_a"
    # First call wrote a line.
    assert len(_read_lines(tmp_log)) == 1

    # Break logging mid-run by pointing at an unwritable path.
    regular_file = tmp_log.parent / "regfile_b"
    regular_file.write_text("x")
    monkeypatch.setattr(
        llm_client, "_LOG_PATH", regular_file / "nested" / "llm.jsonl"
    )
    llm_client.set_mock(["answer_b"])
    b = llm_client.chat([{"role": "user", "content": "q"}])
    assert b == "answer_b", (
        "logging failure must not alter chat() return value"
    )


def test_llm_logger_trace_id_and_caller_default_to_none(tmp_log: Path) -> None:
    """Callers that don't pass trace_id/caller still get a clean log line
    with those fields null — proves existing callers don't break."""
    llm_client.set_mock(["plain"])
    out = llm_client.chat([{"role": "user", "content": "q"}])
    assert out == "plain"
    rec = _read_lines(tmp_log)[0]
    assert rec["trace_id"] is None
    assert rec["caller"] is None


def test_llm_logger_chat_raw_also_logged(tmp_log: Path) -> None:
    """chat_raw() is the primitive both chat() and multi-turn callers use —
    a single chat_raw() call must produce exactly one log line."""
    llm_client.set_mock(["<think>x</think>y"])
    raw = llm_client.chat_raw(
        [{"role": "user", "content": "hi"}],
        trace_id="raw-001",
        caller="test.llm_logger.chat_raw",
    )
    assert raw["choices"][0]["message"]["content"] == "<think>x</think>y"
    lines = _read_lines(tmp_log)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["trace_id"] == "raw-001"
    assert rec["response_raw"] == "<think>x</think>y"
    assert rec["response_cleaned"] == "y"


def test_llm_logger_records_error_when_call_raises(
    tmp_log: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the underlying LLM call raises, the logger still writes a line
    with the error payload populated, and the exception is re-raised."""

    # Poison _next_mock() to simulate a backend failure after the mock path
    # was entered. _next_mock returns from the mock list; exhaustion raises.
    llm_client.set_mock([])  # empty -> IndexError on first call
    with pytest.raises(IndexError):
        llm_client.chat(
            [{"role": "user", "content": "boom"}],
            trace_id="err-001",
            caller="test.llm_logger.errors",
        )
    lines = _read_lines(tmp_log)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["trace_id"] == "err-001"
    assert rec["error"] is not None
    assert rec["error"]["type"] == "IndexError"
    assert rec["response_raw"] is None
    assert rec["response_cleaned"] is None
