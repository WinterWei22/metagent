"""W9 D2b fella — output-shape normaliser STUB wiring.

FELLA's R subprocess errors with "argument is of length zero" on
every sub6b-v3 task seen in W8 D5 (63/63 100% fail). The W9 D4
stretch target is to fix the R-side; D2b's scope is only to wire
the existing `normalize_fella_output()` so the envelope follows
v0.3.1 schema even when the wrapper errors out — which lets D2c
(wrapper-internal error surfacing) detect the error and escalate
to envelope-level.

D2b fella tests assert:
  1. Envelope.result follows v0.3.1 schema (schema_version,
     method, pathway_db present) even when the wrapper errored.
  2. When wrapper raw has `error` field, envelope.result preserves
     that error in a discoverable location (for D2c to consume).

Note: the namespace-prefix check that D2b mummichog/ramp/psea have
is NOT applicable here because FELLA returns 0 pathways pending the
D4 R-side fix; we test schema invariants instead.
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


def test_fella_envelope_emits_v031_schema_even_on_wrapper_error():
    """D2b fella target: even when FELLA's R subprocess errors out,
    the envelope.result must follow EnrichmentResult v0.3.1 schema.
    Currently the handler returns the raw wrapper dict (no
    schema_version key) — RED."""
    env = _dispatch("run_fella_rwr", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    if env.get("error") == "wrapper_unavailable":
        pytest.xfail(f"env: {env.get('reason')}")
    result = env.get("result", {})
    assert result.get("schema_version") == "concordmet_v0.3.1", (
        f"missing/wrong schema_version: {result.get('schema_version')!r}; "
        f"keys={sorted(result.keys())}"
    )
    method = result.get("method")
    assert method and "fella" in method.lower(), (
        f"missing/wrong method: {method!r}"
    )


def test_fella_envelope_preserves_wrapper_error_for_d2c():
    """D2b leaves wrapper-internal error visible in envelope.result
    (so D2c can detect + escalate). FELLA wrapper sets
    `raw.error = "FELLA exception: argument is of length zero"`;
    the v0.3.1 EnrichmentResult.notes (or another discoverable
    field) must preserve that — otherwise D2c has nothing to act on."""
    env = _dispatch("run_fella_rwr", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    if env.get("error") == "wrapper_unavailable":
        pytest.xfail(f"env: {env.get('reason')}")
    result = env.get("result", {})
    # Either notes or a dedicated error block must mention the
    # FELLA R-side error so D2c can act on it.
    notes = (result.get("notes") or "").lower()
    error_blob = str(result.get("error") or "").lower()
    assert "argument is of length zero" in notes or "argument is of length zero" in error_blob, (
        f"D2b fella stub: wrapper-internal R error not preserved "
        f"in envelope.result for D2c to escalate. "
        f"notes={notes!r}, error_blob={error_blob!r}, "
        f"keys={sorted(result.keys())}"
    )
