"""Tests for tool-calling support in common/llm_client.py.

Phase A1 added ``tools`` / ``tool_choice`` pass-through for OpenAI-compat
(viviai). Phase A2 D0 extended that pass-through to the MiniMax provider
after a live probe confirmed MiniMax's M2.7 endpoint accepts the same
OpenAI-shape request.

These tests use the ``set_mock_tool_messages`` channel so they do NOT
touch the real APIs. The dispatcher contract round-trip lives in
``tools/agent_tools/tests/test_tools.py``; here we only verify the
provider-routing behaviour of ``chat_with_tools`` and ``chat_raw``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from common import llm_client
from tools.agent_tools import TOOL_DEFINITIONS_OPENAI, dispatch


@pytest.fixture(autouse=True)
def _reset() -> None:
    llm_client.clear_mock_tool_messages()
    llm_client.clear_mock()
    yield
    llm_client.clear_mock_tool_messages()
    llm_client.clear_mock()


# ---------------------------------------------------------------------------
# Mock-channel parity (legacy chat() vs new chat_with_tools())
# ---------------------------------------------------------------------------


class TestMockChannels:
    def test_chat_mock_unchanged_by_a1(self):
        # Legacy mock channel still works byte-for-byte for non-tool callers.
        llm_client.set_mock(["plain narrative"])
        out = llm_client.chat([{"role": "user", "content": "hi"}])
        assert out == "plain narrative"

    def test_chat_with_tools_mock_returns_message_dict(self):
        llm_client.set_mock_tool_messages([
            {"role": "assistant", "content": "ok", "tool_calls": None},
        ])
        msg = llm_client.chat_with_tools(
            [{"role": "user", "content": "hi"}],
            tools=TOOL_DEFINITIONS_OPENAI,
        )
        assert msg["role"] == "assistant"
        assert msg["content"] == "ok"

    def test_chat_with_tools_mock_returns_tool_calls(self):
        llm_client.set_mock_tool_messages([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_x",
                        "type": "function",
                        "function": {
                            "name": "query_ramp_enrichment",
                            "arguments": '{"compound_kegg_ids": ["C00031"]}',
                        },
                    }
                ],
            },
        ])
        msg = llm_client.chat_with_tools(
            [{"role": "user", "content": "Find pathways for glucose"}],
            tools=TOOL_DEFINITIONS_OPENAI,
        )
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["function"]["name"] == "query_ramp_enrichment"


# ---------------------------------------------------------------------------
# Provider routing — D0 hard gate
# ---------------------------------------------------------------------------


class TestProviderRouting:
    """The A2 D0 change: chat_raw must NOT raise when tools= is passed
    with provider='minimax'. Previously it raised RuntimeError; now both
    providers should pass tools through identically.
    """

    def _capture_create_kwargs(self):
        """Patch openai.ChatCompletion.create to capture call kwargs."""
        captured: dict = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            # Return an OpenAI-shape response with no tool_calls.
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "stub",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "model": kwargs.get("model"),
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }

        return captured, fake_create

    def _patch_configure(self):
        """Stub _configure_openai so no real network setup runs."""
        m = MagicMock()
        m.ChatCompletion = MagicMock()
        return m

    def test_minimax_tools_pass_through_no_raise(self):
        """The pre-D0 behaviour was a RuntimeError when tools= + provider=minimax.
        After D0 the call must pass tools through to ChatCompletion.create."""
        captured, fake_create = self._capture_create_kwargs()
        with patch.object(llm_client, "_configure_openai") as cfg, \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}):
            cfg.return_value.ChatCompletion.create = fake_create
            resp = llm_client.chat_raw(
                [{"role": "user", "content": "hi"}],
                tools=TOOL_DEFINITIONS_OPENAI,
                tool_choice="auto",
                provider="minimax",
                model="MiniMax-M2.7",
            )
        assert "tools" in captured
        assert captured["tool_choice"] == "auto"
        # Verify it actually used the tools list we passed.
        names = {t["function"]["name"] for t in captured["tools"]}
        assert "query_ramp_enrichment" in names

    def test_openai_tools_pass_through_unchanged(self):
        # Sanity: A1's behaviour for provider=openai is preserved.
        captured, fake_create = self._capture_create_kwargs()
        with patch.object(llm_client, "_configure_openai") as cfg, \
             patch.dict(os.environ, {"METAGENT_OPENAI_API_KEY": "test-key"}):
            cfg.return_value.ChatCompletion.create = fake_create
            llm_client.chat_raw(
                [{"role": "user", "content": "hi"}],
                tools=TOOL_DEFINITIONS_OPENAI,
                provider="openai",
                model="claude-opus-4-7",
            )
        assert "tools" in captured
        # OpenAI / viviai uses max_completion_tokens, not max_tokens.
        assert "max_completion_tokens" in captured
        assert "max_tokens" not in captured

    def test_minimax_uses_max_tokens_not_completion(self):
        # MiniMax keeps the legacy max_tokens field name even with tools=.
        captured, fake_create = self._capture_create_kwargs()
        with patch.object(llm_client, "_configure_openai") as cfg, \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}):
            cfg.return_value.ChatCompletion.create = fake_create
            llm_client.chat_raw(
                [{"role": "user", "content": "hi"}],
                tools=TOOL_DEFINITIONS_OPENAI,
                provider="minimax",
                model="MiniMax-M2.7",
            )
        assert "max_tokens" in captured
        assert "max_completion_tokens" not in captured

    def test_no_tools_no_pass_through(self):
        # When tools is None / empty, neither field should appear.
        captured, fake_create = self._capture_create_kwargs()
        with patch.object(llm_client, "_configure_openai") as cfg, \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}):
            cfg.return_value.ChatCompletion.create = fake_create
            llm_client.chat_raw(
                [{"role": "user", "content": "hi"}],
                provider="minimax",
                model="MiniMax-M2.7",
            )
        assert "tools" not in captured
        assert "tool_choice" not in captured


# ---------------------------------------------------------------------------
# Round-trip: MiniMax-shape tool_calls dispatch through agent_tools
# ---------------------------------------------------------------------------


class TestMiniMaxResponseRoundTrip:
    """Confirm the dispatcher consumes a MiniMax-shape response correctly.

    MiniMax returns IDs like ``call_function_xxx_1`` (vs OpenAI's
    ``call_xxx``) and content with a ``<think>...</think>`` block. The
    dispatcher must not care about either.
    """

    def test_minimax_shape_tool_call_dispatches(self):
        # Realistic MiniMax-shaped assistant message (live-probe captured).
        minimax_msg = {
            "role": "assistant",
            "content": "<think>I should call the tool.</think>\n",
            "tool_calls": [
                {
                    "id": "call_function_gh7iom8q4o0a_1",
                    "type": "function",
                    "function": {
                        "name": "query_ramp_enrichment",
                        "arguments": '{"compound_kegg_ids": ["C00031"]}',
                    },
                }
            ],
        }
        # Stub the wrapper so we don't hit RaMP DB.
        from tools.agent_tools import dispatcher as dsp
        dsp.reset_call_cache()
        with patch.dict(
            dsp.WRAPPERS,
            {"query_ramp_enrichment": lambda p: {"top_pathways": [], "n_resolved": 0}},
        ):
            envelope = dispatch(minimax_msg["tool_calls"][0])
        assert envelope["name"] == "query_ramp_enrichment"
        assert envelope["tool_call_id"] == "call_function_gh7iom8q4o0a_1"
        assert "top_pathways" in envelope["result"]


# ---------------------------------------------------------------------------
# Phase A3 D0b — retry-with-backoff
# ---------------------------------------------------------------------------


class TestRetryClassification:
    """Pure unit tests on _is_retryable_exception."""

    def test_timeout_is_retryable(self):
        # openai.error.Timeout has a subclass relationship that's hard to
        # mock without importing the real openai. Build a mock with the
        # right ``type(exc).__name__``.
        class Timeout(Exception):
            pass
        assert llm_client._is_retryable_exception(Timeout("read timeout"))

    def test_apiconnectionerror_is_retryable(self):
        class APIConnectionError(Exception):
            pass
        assert llm_client._is_retryable_exception(APIConnectionError("proxy down"))

    def test_apierror_with_2064_is_retryable(self):
        class APIError(Exception):
            pass
        # Realistic A2 message body
        msg = '当前服务集群负载较高，请稍后重试，感谢您的耐心等待。 (2064) {"http_code":"529"}'
        assert llm_client._is_retryable_exception(APIError(msg))

    def test_apierror_with_503_is_retryable(self):
        class APIError(Exception):
            pass
        assert llm_client._is_retryable_exception(APIError("upstream returned 503"))

    def test_apierror_unrelated_message_not_retryable(self):
        class APIError(Exception):
            pass
        assert not llm_client._is_retryable_exception(APIError("malformed request: bad arg"))

    def test_authentication_error_not_retryable(self):
        class AuthenticationError(Exception):
            pass
        assert not llm_client._is_retryable_exception(AuthenticationError("bad api key"))

    def test_invalidrequest_not_retryable(self):
        class InvalidRequestError(Exception):
            pass
        assert not llm_client._is_retryable_exception(InvalidRequestError("validation failed"))

    def test_ratelimit_not_retryable(self):
        # 429 — caller should slow down, not retry.
        class RateLimitError(Exception):
            pass
        assert not llm_client._is_retryable_exception(RateLimitError("429 too many requests"))


class TestCreateWithRetry:
    """End-to-end retry control flow with mocked openai module."""

    def _patch_sleep(self, monkeypatch):
        """Patch time.sleep inside llm_client to no-op so tests run fast."""
        monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

    def test_retries_on_transient_then_succeeds(self, monkeypatch):
        """503 once → retry → 200 OK on attempt 2."""
        self._patch_sleep(monkeypatch)
        attempts = {"n": 0}

        class APIError(Exception):
            pass

        def flaky_create(**kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise APIError("upstream 503 service unavailable")
            return {
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "model": kwargs.get("model"),
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }

        with patch.object(llm_client, "_configure_openai") as cfg, \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test"}):
            cfg.return_value.ChatCompletion.create = flaky_create
            out = llm_client.chat(
                [{"role": "user", "content": "hi"}],
                provider="minimax", model="MiniMax-M2.7",
                max_retries=3,
                retry_backoff_seconds=[0.0, 0.0, 0.0],
            )
        assert out == "ok"
        assert attempts["n"] == 2

    def test_retries_exhausted_raises_original(self, monkeypatch):
        """All 4 attempts (1 + 3 retries) get 503 — final raise propagates."""
        self._patch_sleep(monkeypatch)
        attempts = {"n": 0}

        class APIError(Exception):
            pass

        def always_fail(**kwargs):
            attempts["n"] += 1
            raise APIError("upstream 503 service unavailable")

        with patch.object(llm_client, "_configure_openai") as cfg, \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test"}), \
             pytest.raises(APIError):
            cfg.return_value.ChatCompletion.create = always_fail
            llm_client.chat(
                [{"role": "user", "content": "hi"}],
                provider="minimax", model="MiniMax-M2.7",
                max_retries=3,
                retry_backoff_seconds=[0.0, 0.0, 0.0],
            )
        assert attempts["n"] == 4  # 1 initial + 3 retries

    def test_non_retryable_fails_fast(self, monkeypatch):
        """Authentication errors are NOT retried."""
        self._patch_sleep(monkeypatch)
        attempts = {"n": 0}

        class AuthenticationError(Exception):
            pass

        def auth_fail(**kwargs):
            attempts["n"] += 1
            raise AuthenticationError("invalid api key")

        with patch.object(llm_client, "_configure_openai") as cfg, \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test"}), \
             pytest.raises(AuthenticationError):
            cfg.return_value.ChatCompletion.create = auth_fail
            llm_client.chat(
                [{"role": "user", "content": "hi"}],
                provider="minimax", model="MiniMax-M2.7",
                max_retries=3,
                retry_backoff_seconds=[0.0, 0.0, 0.0],
            )
        # 1 attempt only, no retries.
        assert attempts["n"] == 1

    def test_max_retries_zero_disables_retry(self, monkeypatch):
        """max_retries=0 = fail-fast on first transient (test parity)."""
        self._patch_sleep(monkeypatch)
        attempts = {"n": 0}

        class APIError(Exception):
            pass

        def flaky_create(**kwargs):
            attempts["n"] += 1
            raise APIError("upstream 503 service unavailable")

        with patch.object(llm_client, "_configure_openai") as cfg, \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test"}), \
             pytest.raises(APIError):
            cfg.return_value.ChatCompletion.create = flaky_create
            llm_client.chat(
                [{"role": "user", "content": "hi"}],
                provider="minimax", model="MiniMax-M2.7",
                max_retries=0,
            )
        assert attempts["n"] == 1

    def test_chat_with_tools_inherits_retry(self, monkeypatch):
        """The tool-calling path (chat_with_tools) also retries."""
        self._patch_sleep(monkeypatch)
        attempts = {"n": 0}

        class APIError(Exception):
            pass

        def flaky_create(**kwargs):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise APIError("overloaded_error 2064 cluster busy")
            return {
                "choices": [{"message": {"role": "assistant", "content": "narr",
                                          "tool_calls": None}}],
                "model": kwargs.get("model"),
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }

        with patch.object(llm_client, "_configure_openai") as cfg, \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test"}):
            cfg.return_value.ChatCompletion.create = flaky_create
            msg = llm_client.chat_with_tools(
                [{"role": "user", "content": "hi"}],
                tools=TOOL_DEFINITIONS_OPENAI,
                provider="minimax", model="MiniMax-M2.7",
                max_retries=3,
                retry_backoff_seconds=[0.0, 0.0, 0.0],
            )
        assert msg["content"] == "narr"
        assert attempts["n"] == 2
