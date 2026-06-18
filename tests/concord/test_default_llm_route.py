"""Default LLM route tests.

These tests are mock-only. They lock the project default to the current
production rerun model without touching live APIs.
"""
from __future__ import annotations

import importlib


def test_llm_client_defaults_to_gpt55_openai(monkeypatch):
    monkeypatch.delenv("METAGENT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("METAGENT_OPENAI_MODEL", raising=False)

    import common.llm_client as llm_client

    llm_client = importlib.reload(llm_client)

    assert llm_client.PROVIDER == "openai"
    assert llm_client.DEFAULT_MODEL == "gpt-5.5"
    assert llm_client.DEFAULT_MAX_TOKENS == 16_384
    assert llm_client._OPENAI_BASE_URL == "https://api.viviai.cc/v1"


def test_react_runner_defaults_to_gpt55_openai():
    import concord.agent.react_runner as react_runner

    assert react_runner.DEFAULT_LLM_PROVIDER == "openai"
    assert react_runner.DEFAULT_LLM_MODEL == "gpt-5.5"
