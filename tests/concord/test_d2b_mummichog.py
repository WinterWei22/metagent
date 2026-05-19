"""W9 D2b mummichog — output-shape normaliser wiring (RED → GREEN).

D1 RED surfaced that the mummichog handler passes raw wrapper output
through unchanged. Mummichog's `pathway_id` field carries the bare
pathway NAME ("Vitamin D3 (cholecalciferol) metabolism") with no
namespace prefix, so the D1 contract test fails its
ALLOWED_NS-prefix check.

The `concord.normalize.mummichog_norm.normalize_mummichog_output()`
function was already implemented in W3 — it converts the raw dict to
a v0.3.1 `EnrichmentResult` with each pathway's id rewritten to
`MUMM:<slug>` (e.g. `MUMM:vitamin_d3_cholecalciferol_metabolism`).
D2b's job is to wire it into the dispatcher handler so the LLM-facing
envelope carries the normalised output.

Tests assert two D2b targets:
  1. Every envelope pathway_id starts with `MUMM:`
  2. Envelope's result dict follows the v0.3.1 schema (method,
     pathway_db, schema_version, per-PathwayHit fields all present)
"""
from __future__ import annotations

import pytest


STEROID_KEGG_IDS = [
    "C00280", "C00468", "C01227", "C03917", "C00535", "C00951",
]


def _dispatch(tool_name: str, arguments: dict) -> dict:
    from concord.agent.tool_dispatcher import dispatch, reset_call_cache
    reset_call_cache()
    return dispatch({"name": tool_name, "arguments": arguments}).payload


def test_mummichog_envelope_pathway_ids_have_mumm_namespace_prefix():
    """D2b target: every pathway_id starts with 'MUMM:' (normaliser
    output, not the bare wrapper pathway name)."""
    env = _dispatch("run_mummichog", {"compound_ids": STEROID_KEGG_IDS, "top_n": 10})
    if env.get("error"):
        pytest.xfail(f"env: {env['error']}")
    pathways = env.get("result", {}).get("pathways", []) or []
    assert pathways, f"expected non-empty pathways; envelope={env!r}"
    for p in pathways:
        pid = p.get("pathway_id", "")
        assert pid.startswith("MUMM:"), (
            f"D2b mummichog normaliser not wired — pathway_id={pid!r} "
            f"lacks 'MUMM:' namespace prefix"
        )


def test_mummichog_envelope_emits_v031_schema():
    """D2b target: envelope.result follows EnrichmentResult v0.3.1
    (schema_version, method, pathway_db, plus full PathwayHit fields
    per pathway entry)."""
    env = _dispatch("run_mummichog", {"compound_ids": STEROID_KEGG_IDS, "top_n": 10})
    if env.get("error"):
        pytest.xfail(f"env: {env['error']}")
    result = env.get("result", {})
    assert result.get("schema_version") == "concordmet_v0.3.1", (
        f"missing/wrong schema_version: {result.get('schema_version')!r}"
    )
    assert result.get("method") == "mummichog", (
        f"missing/wrong method: {result.get('method')!r}"
    )
    pathways = result.get("pathways", [])
    assert pathways, "expected non-empty pathways"
    p0 = pathways[0]
    required_fields = (
        "pathway_id", "pathway_name", "pathway_id_native",
        "pathway_db", "score", "score_type", "rank",
        "metabolites_hit",
    )
    for f in required_fields:
        assert f in p0, f"PathwayHit field {f!r} missing from envelope: {p0!r}"
