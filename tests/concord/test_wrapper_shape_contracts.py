"""W9 D1 — 5-wrapper shape contract tests (RED phase).

Drives each PA wrapper through the dispatcher's public `dispatch()`
envelope-level API with a real sub6b-v3 steroid task's KEGG compound
IDs. Each test classifies the envelope into one of three outcomes:

  - **pass**   — `envelope["ok"] is True` AND `_n_pathways > 0` AND
                  every pathway_id uses an ALLOWED namespace prefix.
                  W9 D2 GREEN goal.
  - **fail**   — `envelope["ok"] is True` AND `_n_pathways == 0`. The
                  wrapper itself worked but the dispatcher reads the
                  wrong top-level key of the wrapper output → the
                  W9 D2 handler-output-shape gap.
  - **xfail**  — env-side problem (wrapper_unavailable from missing
                  pkg / Docker / venv, or runtime exception from R
                  subprocess like FELLA's "argument is of length
                  zero"). W9 D4 attempts FELLA fix as stretch; other
                  env issues are W10+ scope.

The xfail vs fail split is critical so D1 RED counts are honest:
"4/5 fail" must mean **handler shape gap**, not "4/5 fail because env
broken". The RED→GREEN progression then directly traces W9 D2's
dispatcher-adapter fix, not env reconfiguration.

Test inputs: 6 KEGG compound IDs from the canonical sub6b-v3 steroid
task (`compound_only_enrich_mammalian_RAMP_P_000000421_seed1`'s
`ground_truth_signal_compounds`).
"""
from __future__ import annotations

from typing import Any

import pytest


# Real signal compounds from compound_only_enrich_mammalian_RAMP_P_000000421_seed1
# (sub6b-v3 ground_truth_signal_compounds — verified 2026-05-19).
# Note: W9 prompt §3 D1 example showed CHEBI: prefixed strings but the
# actual task carries KEGG IDs; using the real KEGG IDs avoids needing
# an extra CHEBI lookup just for the contract test.
STEROID_KEGG_IDS = [
    "C00280",  # Androstenedione
    "C00468",  # Estrone
    "C01227",  # Dehydroepiandrosterone (DHEA)
    "C03917",  # Dihydrotestosterone
    "C00535",  # Testosterone
    "C00951",  # Estradiol
]

ALLOWED_NS = {"REACT", "KEGG", "WP", "SMPDB", "METACYC", "MUMM", "HUMAN1", "RECON2"}


def _diagnose(envelope: dict[str, Any]) -> tuple[str, str]:
    """Classify a dispatch envelope into (state, reason).

    state ∈ {pass, shape_gap, env_wrapper_unavailable, env_runtime_error,
             unknown}.
    `pass` and `shape_gap` are both within W9 scope; the two `env_*`
    states are NOT W9 D2 targets — they get `pytest.xfail`'d so the
    RED→GREEN count for the dispatcher-adapter fix stays honest.
    """
    err = envelope.get("error")
    if err == "wrapper_unavailable":
        reason = envelope.get("reason") or envelope.get("fallback_suggested") or ""
        return ("env_wrapper_unavailable", f"wrapper_unavailable: {reason}")
    if err and isinstance(err, str) and "raised" in err.lower():
        return ("env_runtime_error", err)
    if envelope.get("ok") is True:
        n = int(envelope.get("_n_pathways", 0) or 0)
        if n == 0:
            return (
                "shape_gap",
                "envelope ok=True but _n_pathways=0 — handler reads "
                "wrong top-level key of wrapper output (W9 D2 target)",
            )
        return ("pass", f"_n_pathways={n}")
    return ("unknown", f"unrecognised envelope: {envelope!r}")


def _assert_namespaces_ok(envelope: dict[str, Any]) -> None:
    """For pass-state envelopes, sanity-check that every pathway_id
    uses one of the 8 allowed namespace prefixes."""
    pathways = envelope.get("result", {}).get("pathways") or []
    bad = [
        p.get("pathway_id")
        for p in pathways
        if (p.get("pathway_id") or "").split(":", 1)[0] not in ALLOWED_NS
    ]
    assert not bad, (
        f"pathway_id namespace must be one of {sorted(ALLOWED_NS)}; "
        f"got {bad}"
    )


def _run_contract(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one tool_call envelope-level and return its payload."""
    from concord.agent.tool_dispatcher import dispatch, reset_call_cache
    reset_call_cache()
    result = dispatch({"name": tool_name, "arguments": arguments})
    return result.payload


# ---------------------------------------------------------------------------
# 5 contract tests — one per PA wrapper
# ---------------------------------------------------------------------------


def test_sspa_envelope_shape():
    """sspa: wrapper output is a method-key dict (`ora`/`gsva`/...); the
    D2 handler reads top-level `pathways` → expected shape_gap.
    sspa pkg is also commonly missing in dev envs → env_wrapper_unavailable
    on those, in which case xfail (W10+ env scope)."""
    env = _run_contract("run_sspa_ora", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    state, reason = _diagnose(env)
    if state in {"env_wrapper_unavailable", "env_runtime_error"}:
        pytest.xfail(f"env issue (W10+ scope): {reason}")
    assert state == "pass", (
        f"sspa envelope state={state}: {reason}\n"
        f"  full envelope: {env!r}"
    )
    _assert_namespaces_ok(env)


def test_ramp_envelope_shape():
    """ramp: wrapper returns `{"report": EnrichmentReport, ...}`; D2
    handler reads `pathways` → expected shape_gap despite ramp being
    the working wrapper at the wrapper level (Path Z W8 D5 = 96.83%).
    No env dependency."""
    env = _run_contract("run_ramp_enrichment", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    state, reason = _diagnose(env)
    if state in {"env_wrapper_unavailable", "env_runtime_error"}:
        pytest.xfail(f"env issue (W10+ scope): {reason}")
    assert state == "pass", (
        f"ramp envelope state={state}: {reason}\n"
        f"  full envelope: {env!r}"
    )
    _assert_namespaces_ok(env)


def test_metaboanalystr_psea_envelope_shape():
    """PSEA: wrapper returns `{"raw": <R subprocess JSON>}`; D2
    handler reads `pathways` → expected shape_gap. Docker R container
    must be up (env_wrapper_unavailable xfail otherwise)."""
    env = _run_contract("run_metaboanalystr_psea", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    state, reason = _diagnose(env)
    if state in {"env_wrapper_unavailable", "env_runtime_error"}:
        pytest.xfail(f"env issue (W10+ scope): {reason}")
    assert state == "pass", (
        f"PSEA envelope state={state}: {reason}\n"
        f"  full envelope: {env!r}"
    )
    _assert_namespaces_ok(env)


def test_mummichog_envelope_shape():
    """mummichog: wrapper output already has top-level `pathways`; the
    D2 handler reads `pathways` directly → expected pass (the only one
    of the 5 PA wrappers that does NOT require a normaliser; W8 D5
    Path X trace confirms mummichog is the LLM's only working PA tool)."""
    env = _run_contract("run_mummichog", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    state, reason = _diagnose(env)
    if state in {"env_wrapper_unavailable", "env_runtime_error"}:
        pytest.xfail(f"env issue (W10+ scope): {reason}")
    assert state == "pass", (
        f"mummichog envelope state={state}: {reason}\n"
        f"  full envelope: {env!r}"
    )
    _assert_namespaces_ok(env)


def test_fella_rwr_envelope_shape():
    """FELLA: wrapper returns `{"raw": <R subprocess JSON>}` BUT the R
    subprocess errors with "argument is of length zero" on every sub6b-v3
    task seen in W8 D5 (63/63 100% fail). Handler's catch-all surfaces
    that as an `env_runtime_error`. Strictly this is two W9 issues —
    (i) handler shape gap (D2), (ii) R-side error (D4 stretch). For
    the D1 contract test we EXPECT xfail until D4 wires the R fix; the
    D2 shape gap can't even be measured on FELLA until D4 land."""
    env = _run_contract("run_fella_rwr", {
        "compound_ids": STEROID_KEGG_IDS, "top_n": 10,
    })
    state, reason = _diagnose(env)
    if state in {"env_wrapper_unavailable", "env_runtime_error"}:
        pytest.xfail(f"env issue (W9 D4 stretch / W10+ scope): {reason}")
    assert state == "pass", (
        f"FELLA envelope state={state}: {reason}\n"
        f"  full envelope: {env!r}"
    )
    _assert_namespaces_ok(env)
