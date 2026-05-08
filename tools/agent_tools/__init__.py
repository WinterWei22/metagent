"""LLM-facing function-tool wrappers for Phase A1 (track AGENT).

Each tool wraps an existing internal module and exposes a slim,
2 KB-bounded JSON output suitable for inclusion in a ReAct loop's
tool_result message. The dispatcher routes a single OpenAI-style
``tool_call`` (name + JSON arguments) to the matching wrapper, with
input-validation error capture and per-call deduplication.

Wrappers in this package never raise: a tool failure is returned as
``{"error": ..., "fallback_suggested": ...}`` so the LLM can decide
whether to retry, switch tool, or stop.

Public:
    TOOL_NAMES               — set of valid tool names (registry order)
    TOOL_DEFINITIONS_OPENAI  — OpenAI-style JSON definitions list
    dispatch(tool_call)      — main dispatch entry point
"""
from __future__ import annotations

from tools.agent_tools.dispatcher import dispatch, reset_call_cache
from tools.agent_tools.tool_definitions import (
    TOOL_DEFINITIONS_OPENAI,
    TOOL_NAMES,
)

__all__ = [
    "TOOL_NAMES",
    "TOOL_DEFINITIONS_OPENAI",
    "dispatch",
    "reset_call_cache",
]
