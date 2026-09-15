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


def test_fella_envelope_emits_v031_schema_or_escalates_after_d2c():
    """D2b fella target (post-D2c contract update):

    Two acceptable envelope shapes when FELLA's R subprocess errors:
    (a) D2b alone (without D2c): ok=True + result.schema_version =
        'concordmet_v0.3.1' + result.notes carries wrapper_error.
    (b) D2c escalation (canonical post-W9 D2 state):
        error='wrapper_runtime_error' + fallback_suggested + reason
        contains the FELLA error string.

    The test accepts EITHER shape as long as one of them holds. xfail
    on wrapper_unavailable (Docker missing — different env class)."""
    env = _dispatch("run_fella_rwr", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    if env.get("error") == "wrapper_unavailable":
        pytest.xfail(f"env: {env.get('reason')}")

    if env.get("error") == "wrapper_runtime_error":
        # (b) D2c escalation — preferred post-W9 D2 state
        assert env.get("fallback_suggested"), (
            f"D2c escalated envelope missing fallback_suggested: {env!r}"
        )
        assert "argument is of length zero" in (env.get("reason") or "").lower(), (
            f"D2c envelope.reason should preserve FELLA error: {env!r}"
        )
    else:
        # (a) D2b alone — schema invariant on result
        result = env.get("result", {})
        assert result.get("schema_version") == "concordmet_v0.3.1", (
            f"D2b: missing schema_version on FELLA envelope: {env!r}"
        )
        method = result.get("method")
        assert method and "fella" in method.lower(), (
            f"D2b: missing/wrong method on FELLA envelope: {env!r}"
        )


def test_fella_wrapper_error_visible_to_caller():
    """The FELLA R error ("argument is of length zero") must surface
    somewhere the caller (LLM via dispatch envelope) can read it —
    either in `env.reason` (post-D2c escalation) or in
    `env.result.notes` (pre-D2c D2b stub). Without this, the LLM has
    no signal to switch tools."""
    env = _dispatch("run_fella_rwr", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    if env.get("error") == "wrapper_unavailable":
        pytest.xfail(f"env: {env.get('reason')}")

    # Aggregate searchable fields across both shapes
    haystack = " ".join(str(env.get(k, "")) for k in ("reason", "error", "fallback_suggested"))
    result = env.get("result") or {}
    if isinstance(result, dict):
        haystack += " " + str(result.get("notes") or "")
        haystack += " " + str(result.get("error") or "")
    assert "argument is of length zero" in haystack.lower(), (
        f"FELLA R-side error not visible to caller in envelope: {env!r}"
    )
