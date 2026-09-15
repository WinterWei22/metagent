"""ConcordMet LLM-agent tool dispatcher (W8 D1 skeleton).

Registers nine OpenAI function-tool specs the LLM may call inside the
ReAct loop, and routes a `tool_call` to the matching handler. D1 only
fixes the **shape** of the registry: spec list, name set, dispatch
plumbing, per-call dedup cache. D2 wires the five PA wrappers behind
the spec; D3 + verifier-adapter wire the four reconciliation tools.

Until a handler is wired, calling its tool returns the conventional
``{"error": "...", "fallback_suggested": "..."}`` envelope so an LLM
running against this dispatcher during a dry smoke does not crash — it
simply receives a "not wired yet" error and can react accordingly. This
mirrors the convention used by ``tools/agent_tools/dispatcher.py``.

Why a parallel package rather than extending `tools/agent_tools/`:
  - W8 architectural rule: B1 paths read-only. Adding nine new tools to
    `tools/agent_tools/` would be a `tools/agent_tools/` edit.
  - The two registries are intentionally independent — a B1 runner
    must keep seeing exactly its 5 tools (no surprises from a ConcordMet
    rebuild) and a ConcordMet runner must keep seeing exactly its 9.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool catalogue (W8 spec §2 Tool Catalog — 9 entries, no V3 aggregator)
# ---------------------------------------------------------------------------

# Each entry is the OpenAI tool-call spec. `description` is human-written
# (not Pydantic-autoderived) because the LLM relies on these strings to
# decide which paradigm to call when; the schema parameters carry the
# typed contract for the dispatcher.

TOOL_SPECS: list[dict[str, Any]] = [
    # --- 5 pathway-analysis tools (the five paradigms) ---
    {
        "type": "function",
        "function": {
            "name": "run_sspa_ora",
            "description": (
                "Reactome-namespace over-representation analysis (sspa "
                "hypergeometric ORA). Returns the top pathways ranked by "
                "FDR. Use for a clean curated-pathway ORA verdict."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "compound_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of compound IDs (ChEBI 'CHEBI:NNNN', "
                            "KEGG 'Cxxxxx', HMDB 'HMDB0000NNN'). Mixed "
                            "namespaces accepted; use lookup_chebi if "
                            "input IDs are unfamiliar."
                        ),
                    },
                    "top_n": {
                        "type": "integer",
                        "default": 10,
                        "description": "Number of top pathways to return.",
                    },
                },
                "required": ["compound_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_ramp_enrichment",
            "description": (
                "RaMP-DB multi-database ORA (Reactome + SMPDB + KEGG + "
                "WikiPathways). Broadest namespace coverage, fast (~1s, "
                "local sqlite, no Docker). Best first call: cheapest "
                "broad-coverage ORA when namespace mix is unclear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "compound_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Compound IDs (any supported namespace).",
                    },
                    "top_n": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Number of top pathways to return.",
                    },
                    "pathway_sources": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["kegg", "reactome", "wikipathways", "smpdb"],
                        },
                        "description": (
                            "Optional. Restrict enrichment to these pathway "
                            "databases. Omit for the default multi-DB mix. Use "
                            "[\"kegg\"] to get canonical KEGG metabolic pathways "
                            "(e.g. Citrate cycle / TCA) when the default mix is "
                            "dominated by disease-specific SMPDB pathways."
                        ),
                    },
                },
                "required": ["compound_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_metaboanalystr_psea",
            "description": (
                "MetaboAnalystR PSEA over the KEGG pathway library (the "
                "community-standard tool). Slower (Docker R subprocess, "
                "~10s). Use when you want a KEGG-only verdict as a "
                "well-cited baseline."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "compound_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Compound IDs (KEGG preferred).",
                    },
                    "top_n": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Number of top pathways to return.",
                    },
                },
                "required": ["compound_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_mummichog",
            "description": (
                "m/z-direct pathway activity against the human_mfn "
                "empirical-compound network. Use when input is lipid- "
                "heavy or annotation-poor; hits pathways even when ID "
                "resolution is weak. Returns MUMM: namespace pathways."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "compound_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Compound IDs; the wrapper synthesises a "
                            "(m/z, p, t) input from compound mass when "
                            "the caller does not provide peaks directly."
                        ),
                    },
                    "peaks": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "Optional explicit list of {mz, p_value, "
                            "t_score} peaks. When omitted, synthesised "
                            "from compound_ids."
                        ),
                    },
                    "top_n": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Number of top pathways to return.",
                    },
                },
                "required": ["compound_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_fella_rwr",
            "description": (
                "FELLA random-walk-with-restart on the KEGG hierarchical "
                "graph (compound → reaction → enzyme → module → "
                "pathway). Captures indirect pathway involvement. Slow "
                "(Docker R subprocess, ~8s)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "compound_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Compound IDs (KEGG preferred).",
                    },
                    "top_n": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Number of top pathways to return.",
                    },
                },
                "required": ["compound_ids"],
            },
        },
    },
    # --- 3 ID / pathway reconciliation tools ---
    {
        "type": "function",
        "function": {
            "name": "lookup_chebi",
            "description": (
                "Resolve one identifier to a structured CompoundRef with "
                "namespace-prefixed primary_id, full InChIKey, and "
                "cross-DB IDs. Accepts: 'CHEBI:NNNNN', 'KEGG:Cxxxxx' or "
                "bare 'Cxxxxx', 'HMDB:HMDB...' or bare 'HMDB0000NNN', "
                "'LIPIDMAPS:LM...' or bare 'LM...', a full 27-char "
                "InChIKey, a compound name, or SMILES (pass "
                "namespace='SMILES' hint). Call before running a PA tool "
                "when input namespaces are mixed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "The identifier to resolve.",
                    },
                    "namespace": {
                        "type": "string",
                        "description": (
                            "Source namespace hint: 'CHEBI', 'KEGG', "
                            "'HMDB', 'LIPIDMAPS', 'INCHIKEY', 'SMILES', "
                            "or 'NAME'. Required when the literal form "
                            "is ambiguous (e.g. plain name)."
                        ),
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reconcile_inchikey",
            "description": (
                "Deduplicate a list of CompoundRef-like dicts by full "
                "InChIKey and return a ConflictReport on structural "
                "disagreements (same name, different InChIKey blocks). "
                "Use when PA tools disagree on which compound sits in a "
                "pathway and you need to know if it is a namespace "
                "artefact or true biology."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "refs": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "List of CompoundRef-like dicts; each must "
                            "have at minimum {inchikey, display_name}, "
                            "ideally also primary_id."
                        ),
                    }
                },
                "required": ["refs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_pathway_members",
            "description": (
                "Return the canonical compound member set (ChEBI IDs) for "
                "one namespace-prefixed pathway_id ('WP:WP167', "
                "'KEGG:hsa00590', etc.). Use to verify that a pathway "
                "you intend to call out actually contains the driver "
                "metabolites you intend to highlight."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pathway_id": {
                        "type": "string",
                        "description": (
                            "Namespace-prefixed pathway ID, e.g. "
                            "'WP:WP167', 'KEGG:hsa00590', "
                            "'REACT:R-HSA-211859'."
                        ),
                    }
                },
                "required": ["pathway_id"],
            },
        },
    },
    # --- 1 literature tool ---
    {
        "type": "function",
        "function": {
            "name": "search_literature",
            "description": (
                "Free-text query against PubMed / Europe PMC. Returns up "
                "to max_results papers with PMID, title, abstract, year. "
                "Use only when the structured tools cannot answer the "
                "specific biological-context question — never for a "
                "pathway-membership lookup (use query_pathway_members)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Free-text search query — biological-context "
                            "specific. Use compound or pathway names + "
                            "biology keywords (e.g. 'eicosanoid signalling "
                            "arachidonic acid metabolism')."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                        "description": "Maximum number of papers to return.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def get_tool_specs() -> list[dict[str, Any]]:
    """Return a fresh shallow copy of the 9 OpenAI tool specs."""
    return [dict(s) for s in TOOL_SPECS]


TOOL_NAMES: tuple[str, ...] = tuple(
    spec["function"]["name"] for spec in TOOL_SPECS
)


# ---------------------------------------------------------------------------
# Per-call dedup cache (mirrors tools/agent_tools/dispatcher.py pattern)
# ---------------------------------------------------------------------------

_CACHE_TLS = threading.local()


def _get_call_cache() -> dict[str, dict[str, Any]]:
    cache = getattr(_CACHE_TLS, "call_cache", None)
    if cache is None:
        cache = {}
        _CACHE_TLS.call_cache = cache
    return cache


def reset_call_cache() -> None:
    """Clear the calling thread's dedup cache. Call between tasks."""
    _CACHE_TLS.call_cache = {}


# ---------------------------------------------------------------------------
# Handler registry — D2 wires all 9 handlers via concord.agent.tool_handlers.
# Each handler validates arguments, defers wrapper import to call-time
# (for ImportError resilience), and returns a uniform envelope.
# ---------------------------------------------------------------------------

HandlerFn = Callable[[dict[str, Any]], dict[str, Any]]


from concord.agent.tool_handlers import HANDLERS  # noqa: E402  (post-spec)


# Sanity: the spec list, name tuple, and handler dict must agree.
assert set(HANDLERS) == set(TOOL_NAMES), (
    f"concord/agent registry mismatch: specs={sorted(TOOL_NAMES)}, "
    f"handlers={sorted(HANDLERS)}"
)


# ---------------------------------------------------------------------------
# Dispatch entry point
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """Envelope returned to the ReAct runner for one tool_call."""

    tool_name: str
    tool_call_id: str
    payload: dict[str, Any]
    from_cache: bool = False


def _coerce_arguments(raw: Any) -> dict[str, Any]:
    """Accept OpenAI's `arguments` as either a JSON string or a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        return json.loads(raw)
    raise TypeError(f"tool_call arguments must be dict or JSON str, got {type(raw)!r}")


def _canonicalise_args(args: dict[str, Any]) -> str:
    """Stable JSON key for cache lookup."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"))


def dispatch(tool_call: dict[str, Any]) -> DispatchResult:
    """Route one OpenAI-style tool_call to its handler.

    Accepts either::

        {"id": "call_xyz", "type": "function",
         "function": {"name": "...", "arguments": "{...JSON...}"}}

    or the simplified shape::

        {"name": "...", "arguments": {...} | "{...}"}

    Returns a `DispatchResult`. On error, `payload` is the conventional
    ``{"error": ..., "fallback_suggested": ...}`` envelope; the runner
    serialises this verbatim as the `tool` role message body.

    D1 behaviour: every wired tool stub raises NotImplementedError; the
    dispatcher catches it and returns ``{"error": "...not wired...",
    "fallback_suggested": "..."}`` so an early smoke does not crash.
    """
    if "function" in tool_call:
        fn_part = tool_call["function"]
        name = fn_part.get("name") or ""
        raw_args = fn_part.get("arguments", {})
        call_id = tool_call.get("id") or ""
    else:
        name = tool_call.get("name") or ""
        raw_args = tool_call.get("arguments", {})
        call_id = tool_call.get("id") or ""

    if name not in HANDLERS:
        return DispatchResult(
            tool_name=name,
            tool_call_id=call_id,
            payload={
                "error": f"unknown tool {name!r}",
                "fallback_suggested": (
                    f"pick one of {sorted(TOOL_NAMES)}"
                ),
            },
        )

    try:
        arguments = _coerce_arguments(raw_args)
    except (TypeError, ValueError) as exc:
        return DispatchResult(
            tool_name=name,
            tool_call_id=call_id,
            payload={
                "error": f"arguments parse failed: {exc}",
                "fallback_suggested": "fix the JSON and retry",
            },
        )

    cache = _get_call_cache()
    cache_key = f"{name}|{_canonicalise_args(arguments)}"
    if cache_key in cache:
        cached = dict(cache[cache_key])
        cached.setdefault("_note", (
            "you already called this tool with identical arguments — "
            "change inputs or move on"
        ))
        cached["_cached"] = True
        return DispatchResult(
            tool_name=name,
            tool_call_id=call_id,
            payload=cached,
            from_cache=True,
        )

    handler = HANDLERS[name]
    try:
        payload = handler(arguments)
    except Exception as exc:
        # Handlers are contracted to never raise — anything that does
        # escape is treated as a wrapper bug. Catch + envelope so a
        # malformed handler does not crash the ReAct loop. The
        # exception is logged for the runner to inspect.
        logger.exception("concord.dispatch.%s raised — handler contract violated", name)
        payload = {
            "error": f"tool {name!r} raised unexpectedly: {exc!r}",
            "fallback_suggested": "switch tool or accept the gap",
            "_tool_name": name,
        }

    cache[cache_key] = payload
    return DispatchResult(
        tool_name=name,
        tool_call_id=call_id,
        payload=payload,
    )
