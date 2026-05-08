"""OpenAI-style ``tools=[...]`` JSON definitions for the 5 agent tools.

Phase A1 only emits OpenAI/viviai-compat definitions. The viviai relay
forwards Anthropic Claude calls in OpenAI tool-call format, so a single
flavour suffices. Anthropic-native ``input_schema`` definitions can be
derived later (deferred to phase A3 if/when we bypass the relay).

Each entry is a dict with shape::

    {
        "type": "function",
        "function": {
            "name": "...",
            "description": "...",
            "parameters": {<JSON Schema>},
        },
    }

The JSON Schema is auto-derived from the matching Pydantic input model
in ``schemas.SCHEMA_REGISTRY``, so adding a field to a schema
automatically updates the LLM-facing definition.
"""
from __future__ import annotations

from typing import Any

from tools.agent_tools.schemas import SCHEMA_REGISTRY


# Human-written one-liners — Pydantic auto-generated descriptions are too
# verbose for the system prompt's tool list, so we override here.
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "query_ramp_enrichment": (
        "Hypergeometric pathway enrichment over RaMP-DB for a list of KEGG "
        "compound IDs. Returns the top_k pathways ranked by FDR with name, "
        "source, FDR, fold-enrichment, and the matched input compounds. Call "
        "this FIRST to identify candidate pathways before making claims."
    ),
    "query_pathway_membership": (
        "List the pathways one specific metabolite belongs to (HMDB or KEGG "
        "ID), plus a co-occurrence plausibility score against other observed "
        "metabolites. Use to verify a 'metabolite X is in pathway Y' claim "
        "before writing it."
    ),
    "query_kegg_path": (
        "Check whether compound A is upstream of compound B via the KEGG "
        "reaction graph (directed BFS, reversible reactions traversed both "
        "ways). Returns the shortest path and direction. Use before any "
        "'X drives Y' or 'X is a precursor of Y' claim."
    ),
    "lookup_compound_info": (
        "Resolve one compound identifier (HMDB / KEGG / InChIKey / SMILES / "
        "name) to a metadata bundle: primary name, formula, mass, chemical "
        "class, tissue locations, disease associations, cross-references. "
        "Backed by HMDB → MoNA → PubChem fallback."
    ),
    "search_literature": (
        "Free-text search over PubMed / Europe PMC. Returns up to "
        "max_results papers with verifiable PMIDs, titles, abstracts, "
        "authors, year, and journal. Use to ground biological claims that "
        "are not directly answerable from the structured tools."
    ),
}


def _build_function_def(name: str, schema_cls: Any) -> dict[str, Any]:
    """Convert a Pydantic schema class to an OpenAI function definition."""
    json_schema: dict[str, Any] = schema_cls.model_json_schema()
    # Pydantic emits 'title' and '$defs' which OpenAI tolerates but they
    # bloat the prompt; strip the obvious ones at the top level.
    json_schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": _TOOL_DESCRIPTIONS[name],
            "parameters": json_schema,
        },
    }


TOOL_NAMES: tuple[str, ...] = tuple(SCHEMA_REGISTRY.keys())


TOOL_DEFINITIONS_OPENAI: list[dict[str, Any]] = [
    _build_function_def(name, schema_cls)
    for name, schema_cls in SCHEMA_REGISTRY.items()
]


def get_tool_definition(name: str) -> dict[str, Any]:
    """Return the OpenAI-style definition for one tool, or raise KeyError."""
    for entry in TOOL_DEFINITIONS_OPENAI:
        if entry["function"]["name"] == name:
            return entry
    raise KeyError(f"unknown tool: {name!r}")
