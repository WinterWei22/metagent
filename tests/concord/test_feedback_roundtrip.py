"""Task 2 TDD: apply_cascade → build_cascade_payload → verify_sub6 roundtrip.

M1 risk: pathway_enrichment claims require term_id/term_name/term_type in the
grammar-v2 dict, but _to_extracted_claim (claim_extractor.py) only stores
pathway_name (mapped from term_name) in ClaimExtractedFields. If apply_cascade
rebuilds from extracted_fields alone, term_id/term_name/term_type are missing →
grammar.validate fails → extract_claims_from_json silently drops the claim.

This test suite:
- Confirms M1 reproduces (claim count drops to 0) before the fix.
- After the fix, asserts claim count is preserved through the full roundtrip.
- Uses a REAL pathway_enrichment VerifiedClaim shape (as produced by
  verify_sub6's set_enrichment layer) + a real SubsixSourceReport built
  from the v4 benchmark trace.

RED should fail on test_roundtrip_pathway_enrichment_claim_count_preserved
(or on test_build_cascade_payload_import if build_cascade_payload not yet
implemented). GREEN requires both apply_cascade field-forwarding fix AND
build_cascade_payload implementation.
"""
from __future__ import annotations

import json
import types

import pytest

from verifier.grammar import ClaimGrammar
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    EnrichmentContext,
    PathwayMatch,
    SubjectKind,
    VerifiedClaim,
)


# ---------------------------------------------------------------------------
# Data fixtures — real v4 trace + benchmark row
# ---------------------------------------------------------------------------


def _load_trace_and_task():
    """Load the trace and benchmark task for hmdb_ramp_easy_kegg_RAMP_P_000000003_rep0."""
    import pathlib, json

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    trace_path = (
        repo_root
        / "data/metagent/v4_live_full/path_x_full"
        / "hmdb_ramp_easy_kegg_RAMP_P_000000003_rep0.json"
    )
    bench_path = (
        repo_root
        / "data/benchmark/metagent_bench_v2"
        / "tasks_hmdb_ramp_easy.jsonl"
    )

    with open(trace_path) as f:
        trace = json.load(f)

    task = None
    with open(bench_path) as f:
        for line in f:
            row = json.loads(line)
            if row["task_id"] == "hmdb_ramp_easy_kegg_RAMP_P_000000003_rep0":
                task = row
                break

    if task is None:
        pytest.skip("Benchmark row for RAMP_P_000000003_rep0 not found")

    return trace, task


def _build_source_report(trace: dict, task: dict):
    """Build SubsixSourceReport from a v4 trace + benchmark task."""
    from concord.agent.verifier_adapter import v4_task_to_subsix_source_report

    frr = trace["final_react_result"]
    react_result = types.SimpleNamespace(
        enrichment_carriers=frr.get("enrichment_carriers", {}),
        final_narrative_text=frr.get("final_narrative_text", ""),
    )
    return v4_task_to_subsix_source_report(task, react_result)


# ---------------------------------------------------------------------------
# Helper — build a VerifiedClaim shaped like set_enrichment layer output
# ---------------------------------------------------------------------------


def _make_pathway_enrichment_verified_claim(
    *,
    term_id: str = "KEGG:hsa00340",
    term_name: str = "Histidine metabolism",
    term_type: str = "pathway",
    verdict: ClaimVerdict = ClaimVerdict.SUPPORTED,
) -> VerifiedClaim:
    """Build a VerifiedClaim as it would emerge from verify_sub6's set_enrichment layer.

    The layer does NOT store term_id/term_name/term_type in extracted_fields
    (only pathway_name is stored there, mapped from term_name). This mirrors
    the actual post-verification state.
    """
    claim_text = f"{term_name} ({term_id}) is enriched in the metabolite set."
    return VerifiedClaim(
        claim_text=claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=None,
        subject_kind=SubjectKind.UNKNOWN,
        verdict=verdict,
        evidence=f"Matched {term_name} in top_pathways via exact name.",
        grammar=ClaimGrammar.PATHWAY_ENRICHMENT,
        # extracted_fields as produced by _to_extracted_claim:
        # only pathway_name is stored; term_id/term_name/term_type are NOT.
        extracted_fields=ClaimExtractedFields(
            pathway_name=term_name,  # term_name mapped here by _to_extracted_claim
            pathway_id=None,         # NOT populated (term_id not mapped)
        ),
        # enrichment_context populated by set_enrichment layer
        enrichment_context=EnrichmentContext(
            claimed_pathway=term_name,
            claimed_pathway_id=term_id,
            best_match=PathwayMatch(
                pathway_id=term_id,
                pathway_name=term_name,
                rank=1,
            ),
            pathway_match_method="exact",
        ),
    )


# ---------------------------------------------------------------------------
# Import tests — RED if function does not exist
# ---------------------------------------------------------------------------


def test_build_cascade_payload_import():
    """build_cascade_payload must be importable from concord.agent.feedback_strategies."""
    from concord.agent.feedback_strategies import build_cascade_payload  # noqa: F401


# ---------------------------------------------------------------------------
# build_cascade_payload unit tests
# ---------------------------------------------------------------------------


def test_build_cascade_payload_returns_json_string():
    """Must return a valid JSON string."""
    from concord.agent.feedback_strategies import apply_cascade, build_cascade_payload

    claim = _make_pathway_enrichment_verified_claim()
    corrected = apply_cascade([claim])
    payload = build_cascade_payload(corrected, narrative_text="Histidine metabolism is enriched.")
    obj = json.loads(payload)
    assert isinstance(obj, dict)
    assert "narrative_text" in obj
    assert "claims" in obj


def test_build_cascade_payload_narrative_text_preserved():
    """narrative_text must match the input string."""
    from concord.agent.feedback_strategies import apply_cascade, build_cascade_payload

    claim = _make_pathway_enrichment_verified_claim()
    corrected = apply_cascade([claim])
    text = "Custom narrative for test."
    payload = build_cascade_payload(corrected, narrative_text=text)
    obj = json.loads(payload)
    assert obj["narrative_text"] == text


def test_build_cascade_payload_claims_list():
    """claims must be a list of dicts."""
    from concord.agent.feedback_strategies import apply_cascade, build_cascade_payload

    claim = _make_pathway_enrichment_verified_claim()
    corrected = apply_cascade([claim])
    payload = build_cascade_payload(corrected, narrative_text="text")
    obj = json.loads(payload)
    assert isinstance(obj["claims"], list)
    assert len(obj["claims"]) == len(corrected)


def test_build_cascade_payload_empty_claims():
    """Empty corrected_claims must produce valid payload with empty claims list."""
    from concord.agent.feedback_strategies import build_cascade_payload

    payload = build_cascade_payload([], narrative_text="")
    obj = json.loads(payload)
    assert obj["claims"] == []


# ---------------------------------------------------------------------------
# M1 regression — pathway_enrichment required fields survive apply_cascade
# ---------------------------------------------------------------------------


def test_apply_cascade_pathway_enrichment_has_term_id():
    """After apply_cascade, pathway_enrichment dicts must carry term_id."""
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_pathway_enrichment_verified_claim(
        term_id="KEGG:hsa00340", term_name="Histidine metabolism"
    )
    result = apply_cascade([claim])
    assert len(result) == 1, "claim should not be dropped"
    d = result[0]
    assert "term_id" in d, (
        "term_id missing from apply_cascade output — M1 not fixed. "
        "apply_cascade must forward term_id for pathway_enrichment grammar."
    )


def test_apply_cascade_pathway_enrichment_has_term_name():
    """After apply_cascade, pathway_enrichment dicts must carry term_name."""
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_pathway_enrichment_verified_claim(
        term_id="KEGG:hsa00340", term_name="Histidine metabolism"
    )
    result = apply_cascade([claim])
    assert len(result) == 1
    d = result[0]
    assert "term_name" in d and d["term_name"], (
        "term_name missing or empty — pathway_enrichment claim will fail grammar.validate"
    )


def test_apply_cascade_pathway_enrichment_has_term_type():
    """After apply_cascade, pathway_enrichment dicts must carry term_type."""
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_pathway_enrichment_verified_claim(term_type="pathway")
    result = apply_cascade([claim])
    assert len(result) == 1
    d = result[0]
    assert "term_type" in d and d["term_type"], (
        "term_type missing or empty — pathway_enrichment claim will fail grammar.validate"
    )


def test_apply_cascade_pathway_enrichment_grammar_validate_passes():
    """The rebuilt dict must pass verifier.grammar.validate."""
    from concord.agent.feedback_strategies import apply_cascade
    from verifier.grammar import validate

    claim = _make_pathway_enrichment_verified_claim(
        term_id="KEGG:hsa00340",
        term_name="Histidine metabolism",
        term_type="pathway",
    )
    result = apply_cascade([claim])
    assert len(result) == 1
    vr = validate(result[0])
    assert vr.is_valid, f"grammar.validate returned invalid: {vr.drop_reason}"


# ---------------------------------------------------------------------------
# Roundtrip test — apply_cascade → build_cascade_payload → verify_sub6
# ---------------------------------------------------------------------------


def test_roundtrip_pathway_enrichment_claim_count_preserved():
    """Core M1 roundtrip: apply_cascade → build_cascade_payload → verify_sub6.

    A SUPPORTED pathway_enrichment VerifiedClaim fed through the cascade
    must emerge from verify_sub6 with at least 1 verified claim (not dropped).
    This fails before the M1 fix because term_id/term_name/term_type are lost
    in apply_cascade's rebuild → grammar.validate drops the claim in
    extract_claims_from_json → verify_sub6 returns 0 total_claims.
    """
    from concord.agent.feedback_strategies import apply_cascade, build_cascade_payload
    from verifier.agent import verify_sub6

    trace, task = _load_trace_and_task()
    source_report = _build_source_report(trace, task)

    # Build a pathway_enrichment VerifiedClaim matching the trace's top pathway.
    claim = _make_pathway_enrichment_verified_claim(
        term_id="KEGG:hsa00340",
        term_name="Histidine metabolism",
        term_type="pathway",
        verdict=ClaimVerdict.SUPPORTED,
    )

    corrected = apply_cascade([claim])
    assert len(corrected) == 1, "apply_cascade should keep SUPPORTED claim"

    payload = build_cascade_payload(
        corrected,
        narrative_text="Histidine metabolism (KEGG:hsa00340) is enriched in the metabolite set.",
    )

    result = verify_sub6(
        payload,
        source_report,
        trace_id="t2.roundtrip",
        is_final_iteration=True,
    )

    # The single corrected claim must survive verify_sub6 without being dropped.
    # Before the fix: total_claims=0 (dropped by grammar), claim_count_preserved fails.
    total = result.claim_metrics.total_claims if result.claim_metrics else len(result.claims_v1)
    assert total >= 1, (
        f"Roundtrip dropped all claims — M1 not fixed. "
        f"total_claims={total}, "
        f"dropped={len(result.dropped_claims)}, "
        f"dropped_reasons={[d.drop_reason for d in result.dropped_claims]}"
    )


def test_roundtrip_no_extra_claims_injected():
    """verify_sub6 must not produce more claims than we injected."""
    from concord.agent.feedback_strategies import apply_cascade, build_cascade_payload
    from verifier.agent import verify_sub6

    trace, task = _load_trace_and_task()
    source_report = _build_source_report(trace, task)

    claim = _make_pathway_enrichment_verified_claim(verdict=ClaimVerdict.SUPPORTED)
    corrected = apply_cascade([claim])
    payload = build_cascade_payload(corrected, narrative_text="Histidine metabolism is enriched.")

    result = verify_sub6(payload, source_report, trace_id="t2.count", is_final_iteration=True)

    total = result.claim_metrics.total_claims if result.claim_metrics else len(result.claims_v1)
    # At most 1 claim can be verified (we fed exactly 1 corrected claim).
    assert total <= 1, f"verify_sub6 produced {total} claims but we fed 1"


def test_roundtrip_no_enrichment_context_no_pathway_id():
    """M1 edge case: enrichment_context=None AND extracted_fields.pathway_id=None.

    When a pathway_enrichment VerifiedClaim lacks both enrichment_context
    (layer 6a may be absent in some traces) and pathway_id (fallback),
    the old code would set term_id="" → grammar.validate fails →
    claim is silently dropped.

    With the M1 fix, term_id must have a non-empty fallback (e.g., term_name)
    so the claim survives the roundtrip.
    """
    from concord.agent.feedback_strategies import apply_cascade, build_cascade_payload
    from verifier.agent import verify_sub6

    trace, task = _load_trace_and_task()
    source_report = _build_source_report(trace, task)

    # Build a pathway_enrichment claim with NO enrichment_context
    # and NO pathway_id in extracted_fields.
    claim_text = "Histidine metabolism is enriched in the metabolite set."
    claim = VerifiedClaim(
        claim_text=claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=None,
        subject_kind=SubjectKind.UNKNOWN,
        verdict=ClaimVerdict.SUPPORTED,
        evidence="Matched pathway via exact name.",
        grammar=ClaimGrammar.PATHWAY_ENRICHMENT,
        extracted_fields=ClaimExtractedFields(
            pathway_name="Histidine metabolism",
            pathway_id=None,  # EDGE CASE: no pathway_id
        ),
        enrichment_context=None,  # EDGE CASE: no enrichment_context
    )

    corrected = apply_cascade([claim])
    assert len(corrected) == 1, (
        "apply_cascade should keep SUPPORTED claim even when "
        "enrichment_context=None and pathway_id=None"
    )

    # Verify that the rebuilt dict has a non-empty term_id
    d = corrected[0]
    assert "term_id" in d, "term_id missing from apply_cascade output"
    assert d["term_id"] and d["term_id"].strip(), (
        "term_id is empty/None — will fail grammar.validate. "
        "M1 fix must provide a non-empty fallback (e.g., term_name)."
    )

    payload = build_cascade_payload(corrected, narrative_text=claim_text)

    result = verify_sub6(
        payload,
        source_report,
        trace_id="t2.no_context_no_id",
        is_final_iteration=True,
    )

    total = result.claim_metrics.total_claims if result.claim_metrics else len(result.claims_v1)
    assert total >= 1, (
        f"Roundtrip dropped the claim when enrichment_context=None and pathway_id=None. "
        f"total_claims={total}, "
        f"dropped_reasons={[d.drop_reason for d in result.dropped_claims]}"
    )
