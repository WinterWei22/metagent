"""W9 D2b ramp — output-shape normaliser wiring (RED → GREEN).

The ramp handler reads `raw.get("pathways")`, but the wrapper output
is `{"report": EnrichmentReport, ...}` — there is no top-level
`pathways` key. The pathways live as
`raw["report"].top_pathways: list[EnrichmentResult]` where each carries
`pathway_id` (RaMP internal RAMP_P_NNNNNN), `pathway_name`,
`pathway_external_id` (R-HSA-NNN / hsa00NNN / WP3604 / SMP00466 ...),
and `pathway_source` (reactome / kegg / wikipathways / smpdb / hmdb).

`concord.normalize.ramp_norm.normalize_ramp_output()` (W3) converts
this to a v0.3.1 `EnrichmentResult` with per-source namespace prefixes:
  reactome     → REACT:R-HSA-NNN
  kegg         → KEGG:hsa00NNN
  wikipathways → WP:WPNNN
  smpdb / hmdb → SMPDB:SMPNNNN

D2b's job: wire that function into `handle_run_ramp_enrichment` so
the envelope carries namespace-prefixed v0.3.1 output.

Tests assert:
  1. Envelope follows v0.3.1 schema
  2. Every pathway_id has a namespace prefix in {REACT, KEGG, WP, SMPDB}
  3. _n_pathways matches the EnrichmentResult.pathways tuple length
"""
from __future__ import annotations

import pytest


STEROID_KEGG_IDS = [
    "C00280", "C00468", "C01227", "C03917", "C00535", "C00951",
]

ALLOWED_RAMP_NS = {"REACT", "KEGG", "WP", "SMPDB"}


def _dispatch(tool_name: str, arguments: dict) -> dict:
    from concord.agent.tool_dispatcher import dispatch, reset_call_cache
    reset_call_cache()
    return dispatch({"name": tool_name, "arguments": arguments}).payload


def test_ramp_envelope_pathway_ids_carry_source_namespace_prefix():
    """D2b ramp target: every envelope pathway_id starts with one of
    the per-source namespace prefixes; current handler reads the
    wrong wrapper key → 0 pathways → vacuously passes; D2a fix gives
    real ramp wrapper output; D2b normaliser surfaces it."""
    env = _dispatch("run_ramp_enrichment", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    if env.get("error"):
        pytest.xfail(f"env: {env['error']}")
    pathways = env.get("result", {}).get("pathways", []) or []
    assert pathways, (
        f"expected non-empty pathways after D2b; envelope={env!r}"
    )
    for p in pathways:
        pid = p.get("pathway_id", "")
        ns = pid.split(":", 1)[0]
        assert ns in ALLOWED_RAMP_NS, (
            f"D2b ramp normaliser not wired or wrong namespace: "
            f"pathway_id={pid!r} ns={ns!r} not in {sorted(ALLOWED_RAMP_NS)}"
        )


def test_ramp_envelope_emits_v031_schema():
    """D2b: envelope.result follows EnrichmentResult v0.3.1."""
    env = _dispatch("run_ramp_enrichment", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    if env.get("error"):
        pytest.xfail(f"env: {env['error']}")
    result = env.get("result", {})
    assert result.get("schema_version") == "concordmet_v0.3.1", (
        f"missing/wrong schema_version: {result.get('schema_version')!r}"
    )
    assert result.get("method") == "ora_ramp", (
        f"missing/wrong method: {result.get('method')!r}"
    )
    pathways = result.get("pathways", [])
    assert pathways, "expected non-empty pathways"
    p0 = pathways[0]
    for f in ("pathway_id", "pathway_name", "pathway_id_native",
              "pathway_db", "score", "score_type", "rank"):
        assert f in p0, f"PathwayHit field {f!r} missing"


def test_ramp_envelope_n_pathways_matches_result_length():
    """The envelope's `_n_pathways` count must equal
    len(result.pathways) — guards against the W8 D2 inconsistency
    where `_n_pathways` came from an empty `pathways` list while
    the wrapper had returned actual hits inside `report`."""
    env = _dispatch("run_ramp_enrichment", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    if env.get("error"):
        pytest.xfail(f"env: {env['error']}")
    n_meta = env.get("_n_pathways", 0)
    n_paths = len(env.get("result", {}).get("pathways", []))
    assert n_meta == n_paths, (
        f"_n_pathways={n_meta} but result.pathways has {n_paths} entries"
    )
