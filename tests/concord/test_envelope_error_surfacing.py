"""W9 D2c — wrapper-internal error surfacing to envelope-level.

After W9 D2b, FELLA's R subprocess error ("argument is of length
zero") is preserved in `result.notes` but the envelope still reports
`ok=True` with `_n_pathways=0`. The LLM and the D1 contract test
both misread that as a shape gap. D2c's job: detect wrapper-internal
error sentinels in the normalised result and rewrite the envelope as
`{"error": "wrapper_runtime_error", "fallback_suggested": "...",
"_tool_name": "...", "reason": "<wrapper error msg>"}` so the LLM
sees a clean fail-fast signal (same shape as wrapper_unavailable).

Tests:
  1. FELLA real call — wrapper.notes carries the R error → envelope
     escalates to wrapper_runtime_error.
  2. Mummichog real call — no wrapper error → envelope stays ok=True
     (no false-positive escalation).
  3. Monkeypatched generic wrapper — synthetic notes with
     "wrapper_error:" sentinel → envelope escalates regardless of
     which PA handler.
"""
from __future__ import annotations

from typing import Any

import pytest


STEROID_KEGG_IDS = [
    "C00280", "C00468", "C01227", "C03917", "C00535", "C00951",
]


def _dispatch(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from concord.agent.tool_dispatcher import dispatch, reset_call_cache
    reset_call_cache()
    return dispatch({"name": tool_name, "arguments": arguments}).payload


def test_fella_internal_error_surfaces_to_envelope():
    """FELLA's R subprocess emits "argument is of length zero"; the
    handler's D2b stub preserves that in `result.notes`. D2c must
    escalate to envelope-level `error="wrapper_runtime_error"`."""
    env = _dispatch("run_fella_rwr", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    # Wrapper-unavailable case is unrelated (Docker not running, etc.)
    if env.get("error") == "wrapper_unavailable":
        pytest.xfail(f"env: {env.get('reason')}")

    # Gate: ensure FELLA actually emitted "argument is of length zero"
    # in this run (either pre-D2c via result.notes, or post-D2c via
    # envelope.reason). If neither location has the error string,
    # FELLA succeeded this time (e.g. D4 landed) and the D2b→D2c
    # bridge isn't exercised — xfail with explanation.
    notes_str = str((env.get("result") or {}).get("notes", "") or "")
    reason_str = str(env.get("reason") or "")
    err_visible_anywhere = (
        "argument is of length zero" in notes_str
        or "argument is of length zero" in reason_str
    )
    if not err_visible_anywhere:
        pytest.xfail(
            "FELLA no longer emits 'argument is of length zero' — D4 "
            "may have landed or env state changed; this test guards "
            "the D2b → D2c bridge only when the R error still occurs"
        )

    # GREEN target: envelope escalated to wrapper_runtime_error
    assert env.get("error") == "wrapper_runtime_error", (
        f"wrapper-internal R error not escalated to envelope: env={env!r}"
    )
    assert env.get("ok") is not True, (
        f"envelope.ok should NOT be True when wrapper errored: env={env!r}"
    )
    assert env.get("fallback_suggested"), (
        f"fallback_suggested missing on escalated envelope: env={env!r}"
    )
    # Reason field preserves the underlying wrapper message
    assert "argument is of length zero" in reason_str.lower(), (
        f"envelope.reason should preserve wrapper error: env={env!r}"
    )


def test_normal_wrapper_no_false_positive_escalation():
    """Mummichog returns normal output with no wrapper_error sentinel
    → D2c must NOT escalate. Envelope stays ok=True."""
    env = _dispatch("run_mummichog", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    if env.get("error") == "wrapper_unavailable":
        pytest.xfail(f"env: {env.get('reason')}")

    # Mummichog should produce non-empty pathways and clean envelope
    assert env.get("ok") is True, (
        f"D2c false-positive: mummichog clean output rewritten to "
        f"error envelope: env={env!r}"
    )
    assert "error" not in env or not env.get("error"), (
        f"D2c false-positive: error field set on clean envelope: env={env!r}"
    )
    assert env.get("_n_pathways", 0) > 0, (
        f"mummichog should produce pathways for steroid task: env={env!r}"
    )


def test_synthetic_wrapper_error_sentinel_escalates(monkeypatch):
    """Generic protocol test: any PA handler whose normalised result
    has a wrapper_error sentinel in `notes` must produce a
    wrapper_runtime_error envelope. Drives the detection logic via a
    synthetic test fixture (monkeypatch the normaliser to inject a
    sentinel) so the detection isn't coupled to FELLA specifically."""
    from concord.normalize import mummichog_norm
    from concord.schema.enrichment import (
        EnrichmentMethod, PathwayDB, EnrichmentResult,
    )

    # Build a synthetic EnrichmentResult mimicking a wrapper-error state
    def _fake_normaliser(raw, **_kwargs):
        return EnrichmentResult(
            method=EnrichmentMethod.MUMMICHOG,
            pathway_db=PathwayDB.MUMMICHOG_MFN,
            pathways=(),  # empty due to wrapper error
            parameters={},
            tool_version="mummichog-test-1.0",
            db_release="test_2026",
            n_input=6,
            n_input_resolved=0,
            wall_time_sec=0.1,
            notes="mummichog synthetic; wrapper_error: simulated R-side panic",
        )

    monkeypatch.setattr(mummichog_norm, "normalize_mummichog_output", _fake_normaliser)

    env = _dispatch("run_mummichog", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    if env.get("error") == "wrapper_unavailable":
        pytest.xfail(f"env: {env.get('reason')}")

    assert env.get("error") == "wrapper_runtime_error", (
        f"synthetic wrapper_error sentinel didn't escalate to envelope: "
        f"env={env!r}"
    )
    assert "simulated R-side panic" in (env.get("reason") or ""), (
        f"envelope.reason should preserve synthetic wrapper message: "
        f"env={env!r}"
    )
