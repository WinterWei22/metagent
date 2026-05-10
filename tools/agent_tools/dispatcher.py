"""Route an LLM tool_call to the matching wrapper.

Phase A3 D0a: the per-call dedup cache is **thread-local**. When the
parallel runner runs K tasks concurrently in a thread pool, each
worker thread gets its own ``_CALL_CACHE`` instance — task A's tool
calls do not pollute task B's cache. The single-threaded behaviour is
unchanged: ``reset_call_cache()`` clears the calling thread's cache,
which is what the legacy A1 / A2 runners expect.

Accepts either an OpenAI-style tool_call dict::

    {"id": "call_xyz", "type": "function",
     "function": {"name": "...", "arguments": "{...JSON string...}"}}

or a simplified dict::

    {"name": "...", "arguments": {...} | "{...}"}

and returns a result envelope that the ReAct runner serialises into a
``tool`` role message.

Per-call deduplication (spec pitfall #4): when the LLM calls the same
``(tool_name, canonical_args)`` twice in a single conversation, the
second call returns the cached result with ``_cached=True`` and a
``_note`` telling the LLM "you already called this — change something or
move on". This breaks the most common ReAct death-spiral.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from pydantic import ValidationError

from tools.agent_tools.lookup_compound_info import lookup_compound_info
from tools.agent_tools.query_kegg_path import query_kegg_path
from tools.agent_tools.query_pathway_membership import query_pathway_membership
from tools.agent_tools.query_ramp_enrichment import query_ramp_enrichment
from tools.agent_tools.schemas import SCHEMA_REGISTRY, truncate_to_budget
from tools.agent_tools.search_literature import search_literature

logger = logging.getLogger(__name__)


# Wrapper registry — each takes a payload dict and returns a result dict.
WrapperFn = Callable[[dict[str, Any]], dict[str, Any]]

WRAPPERS: dict[str, WrapperFn] = {
    "query_ramp_enrichment": query_ramp_enrichment,
    "query_pathway_membership": query_pathway_membership,
    "query_kegg_path": query_kegg_path,
    "lookup_compound_info": lookup_compound_info,
    "search_literature": search_literature,
}

# Sanity: the schema registry and wrapper registry must agree on tool names,
# otherwise the LLM would see a tool definition with no executor.
assert set(WRAPPERS) == set(SCHEMA_REGISTRY), (
    f"agent_tools registry mismatch: schemas={sorted(SCHEMA_REGISTRY)}, "
    f"wrappers={sorted(WRAPPERS)}"
)


# ---------------------------------------------------------------------------
# In-process call cache (per session, per thread — reset between tasks)
# ---------------------------------------------------------------------------

import threading as _threading

_CACHE_TLS = _threading.local()


def _get_call_cache() -> dict[str, dict[str, Any]]:
    cache = getattr(_CACHE_TLS, "call_cache", None)
    if cache is None:
        cache = {}
        _CACHE_TLS.call_cache = cache
    return cache


def reset_call_cache() -> None:
    """Clear the calling thread's dedup cache. Call this between tasks in a
    batch run.

    Each worker thread in the parallel runner has its own cache, so a
    reset in thread A does not affect thread B.
    """
    _CACHE_TLS.call_cache = {}


def _cache_key(name: str, args: dict[str, Any]) -> str:
    canonical = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    return f"{name}::{canonical}"


# ---------------------------------------------------------------------------
# Argument extraction
# ---------------------------------------------------------------------------


def _extract_call(tool_call: dict[str, Any]) -> tuple[str, dict[str, Any], str | None]:
    """Pull (name, args, call_id) out of any of the supported shapes.

    Raises ValueError on a malformed call.
    """
    call_id = tool_call.get("id")
    fn = tool_call.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        raw_args = fn.get("arguments")
    else:
        name = tool_call.get("name")
        raw_args = tool_call.get("arguments")

    if not isinstance(name, str) or not name:
        raise ValueError("tool_call missing 'name'")

    if raw_args is None:
        args: dict[str, Any] = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    elif isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"tool_call arguments not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"tool_call arguments must decode to an object, got {type(parsed).__name__}")
        args = parsed
    else:
        raise ValueError(f"tool_call arguments has unsupported type {type(raw_args).__name__}")

    return name, args, call_id


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def dispatch(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Route the tool_call to its wrapper, returning a result envelope.

    Envelope shape (always present)::

        {
            "name": str,
            "tool_call_id": str | None,
            "result": dict,         # wrapper output OR error dict
            "cached": bool,
        }

    The wrapper itself never raises; ``result`` is either the projection
    described in the wrapper docstring or ``{"error": ..., ...}``. Schema
    validation errors and unknown-tool errors also surface as an error
    dict in ``result`` (NOT raised) so the ReAct loop can keep going.
    """
    try:
        name, args, call_id = _extract_call(tool_call)
    except ValueError as exc:
        return {
            "name": tool_call.get("function", {}).get("name") or tool_call.get("name") or "unknown",
            "tool_call_id": tool_call.get("id"),
            "result": {
                "error": f"malformed_tool_call: {exc}",
                "fallback_suggested": (
                    "emit a JSON object with keys 'name' and 'arguments'; "
                    "arguments may be a JSON string or a JSON object"
                ),
            },
            "cached": False,
        }

    if name not in WRAPPERS:
        return {
            "name": name,
            "tool_call_id": call_id,
            "result": {
                "error": f"unknown_tool: {name!r}",
                "fallback_suggested": (
                    f"valid tools: {sorted(WRAPPERS.keys())}"
                ),
            },
            "cached": False,
        }

    schema_cls = SCHEMA_REGISTRY[name]
    try:
        validated = schema_cls.model_validate(args).model_dump()
    except ValidationError as exc:
        # Surface a compact summary so the LLM can self-correct.
        errors = [
            {
                "loc": ".".join(str(x) for x in e.get("loc", ())),
                "msg": e.get("msg", ""),
                "type": e.get("type", ""),
            }
            for e in exc.errors()[:5]
        ]
        return {
            "name": name,
            "tool_call_id": call_id,
            "result": {
                "error": "validation_error",
                "details": errors,
                "fallback_suggested": (
                    "fix the argument types/values and retry; consult the "
                    "tool definition for the required schema"
                ),
            },
            "cached": False,
        }

    # Dedup against canonical (post-validation) args. Per-thread cache.
    cache = _get_call_cache()
    key = _cache_key(name, validated)
    if key in cache:
        cached = dict(cache[key])
        cached["_cached"] = True
        cached["_note"] = (
            "you already called this tool with these exact arguments earlier "
            "in the conversation — same answer returned; switch tool or "
            "change arguments to make progress"
        )
        return {
            "name": name,
            "tool_call_id": call_id,
            "result": truncate_to_budget(cached),
            "cached": True,
        }

    wrapper = WRAPPERS[name]
    try:
        result = wrapper(validated)
    except Exception as exc:  # pragma: no cover — wrappers swallow internally
        logger.exception("dispatch: wrapper %s raised unexpectedly", name)
        result = {
            "error": f"wrapper_unexpected: {type(exc).__name__}: {exc}",
            "fallback_suggested": "retry once or move on",
        }

    cache[key] = result
    return {
        "name": name,
        "tool_call_id": call_id,
        "result": result,
        "cached": False,
    }
