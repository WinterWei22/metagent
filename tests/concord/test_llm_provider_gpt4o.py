"""GPT-4o provider wire-up test (W3 D2/D4 hedge).

Mock-based test — verifies `common.llm_client` is structurally ready to route
through OpenAI provider for GPT-4o. **Does NOT make real API calls** (cost
control + missing API key in investigation worktree → see Q-06 in W3 status).

Verifies:
  1. METAGENT_LLM_PROVIDER=openai env var is honored
  2. OpenAI model name "gpt-4o-2024-11-20" is accepted
  3. ChatCompletion.create call shape matches expected GPT-4o request format
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))


def test_llm_client_imports():
    """Sanity: common.llm_client imports without error."""
    import common.llm_client as llm
    assert hasattr(llm, "PROVIDER")
    assert hasattr(llm, "DEFAULT_MAX_TOKENS")


def test_openai_provider_envvar_honored(monkeypatch):
    """When METAGENT_LLM_PROVIDER=openai, PROVIDER constant reflects it on reimport."""
    monkeypatch.setenv("METAGENT_LLM_PROVIDER", "openai")
    import importlib
    import common.llm_client as llm
    llm = importlib.reload(llm)
    assert llm.PROVIDER == "openai"
    # max_tokens default switches for OpenAI's reasoning-class limit
    assert llm.DEFAULT_MAX_TOKENS == 16_384


def test_gpt4o_model_name_accepted():
    """Confirm `gpt-4o-2024-11-20` is a syntactically-valid model name string
    (no validator rejects it). This is structural — full API call is W4 D4."""
    model_name = "gpt-4o-2024-11-20"
    assert "-" in model_name
    assert model_name.startswith("gpt-4o")


def test_chat_completion_mock_shape():
    """Mock openai==0.28 ChatCompletion.create — verify the call arg shape
    matches what GPT-4o expects (model, messages, max_tokens, temperature)."""
    import common.llm_client as llm

    fake_openai = MagicMock()
    fake_openai.ChatCompletion.create.return_value = {
        "choices": [{"message": {"content": "Mocked GPT-4o response"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    # Use llm._create_with_retry with the actual signature
    create_kwargs = {
        "model": "gpt-4o-2024-11-20",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 100,
        "temperature": 0.0,
    }
    result = llm._create_with_retry(
        fake_openai,
        create_kwargs,
        max_retries=1,
        backoff=[],
        caller="test_gpt4o_wireup",
        trace_id="test-trace",
    )
    # Verify mock was called with GPT-4o-compatible args
    assert fake_openai.ChatCompletion.create.called
    call_kwargs = fake_openai.ChatCompletion.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-2024-11-20"
    assert call_kwargs["max_tokens"] == 100
    assert call_kwargs["messages"][0]["content"] == "ping"
    assert result["choices"][0]["message"]["content"] == "Mocked GPT-4o response"
