"""Optional `pathway_sources` filter for run_ramp_enrichment (RED → GREEN).

Root cause (2026-07-03 diagnosis): RaMP-DB queries all pathway.type at once
(kegg / reactome / wiki / hmdb=SMPDB); SMPDB disease pathways ("The oncogenic
action of 2-hydroxyglutarate", FDR ~1e-29) rank ABOVE canonical KEGG
"Citrate cycle (TCA)" for oncometabolite inputs, so TCA falls out of the
top-N and the LLM waffles.

Fix = ADDITIVE optional `pathway_sources` param (INCLUDE semantics). Default
(None) preserves current multi-DB behaviour byte-identical (guardrail: old
63-task benchmark must not regress). `["kegg"]` returns only KEGG-source
pathways so the LLM can request canonical metabolic pathways on demand.

LLM-driven (death command): the source choice is exposed as a tool param,
not hard-coded.
"""
from __future__ import annotations

import pytest

# TCA-cycle metabolites as KEGG compound IDs — hit both KEGG "Citrate cycle"
# and SMPDB disease pathways by default.
TCA_KEGG_IDS = ["C00042", "C00158", "C00122", "C00149", "C00311", "C00026", "C00417"]


def _dispatch(tool_name: str, arguments: dict) -> dict:
    from concord.agent.tool_dispatcher import dispatch, reset_call_cache
    reset_call_cache()
    return dispatch({"name": tool_name, "arguments": arguments}).payload


def _sources(env: dict) -> list[str]:
    """Namespace prefixes of returned pathway_ids (KEGG / SMPDB / REACT / WP)."""
    pw = env.get("result", {}).get("pathways", []) or []
    return [str(p.get("pathway_id", "")).split(":", 1)[0] for p in pw]


# --- P1: helper is a pure function (no DB needed) ---------------------------

def test_sources_to_excluded_types_kegg_only():
    from tools.benchmark.sub6.ramp_enrichment import _sources_to_excluded_types
    excluded = set(_sources_to_excluded_types(["kegg"]))
    # everything except kegg is excluded (incl. always-noisy pfocr)
    assert "kegg" not in excluded
    assert {"reactome", "wiki", "hmdb", "pfocr"} <= excluded


def test_sources_to_excluded_types_multi():
    from tools.benchmark.sub6.ramp_enrichment import _sources_to_excluded_types
    excluded = set(_sources_to_excluded_types(["kegg", "reactome"]))
    assert excluded.isdisjoint({"kegg", "reactome"})
    assert {"wiki", "hmdb", "pfocr"} <= excluded


# --- P1/P2: integration via dispatch (needs ramp.sqlite) --------------------

def test_pathway_sources_kegg_returns_only_kegg():
    env = _dispatch("run_ramp_enrichment", {
        "compound_ids": TCA_KEGG_IDS, "top_n": 15, "pathway_sources": ["kegg"],
    })
    if env.get("error"):
        pytest.xfail(f"ramp db unavailable: {env['error']}")
    prefixes = _sources(env)
    assert prefixes, f"expected pathways; env={env!r}"
    assert set(prefixes) <= {"KEGG"}, f"expected KEGG-only, got sources={set(prefixes)}"


def test_default_unchanged_multi_source():
    """Guardrail: default (no pathway_sources) still returns multi-DB incl. SMPDB."""
    env = _dispatch("run_ramp_enrichment", {
        "compound_ids": TCA_KEGG_IDS, "top_n": 15,
    })
    if env.get("error"):
        pytest.xfail(f"ramp db unavailable: {env['error']}")
    prefixes = set(_sources(env))
    assert prefixes, f"expected pathways; env={env!r}"
    # default is multi-source: SMPDB (or a non-KEGG source) is present
    assert prefixes - {"KEGG"}, f"default should be multi-source, got only {prefixes}"
