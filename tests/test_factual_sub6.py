"""W12 D2 RED — verifier/layers/factual_sub6.py (8 cases, main course).

W11 UV diagnosis (commit e74af22) showed 226 C7 namespace_form UV claims;
181 (80.1%) are FACTUAL/GROUNDED claim_type that currently fall through
verify_sub6 dispatch (verifier/agent.py:664-685) because
SubsixSourceReport carries no candidates[*].metabolite_info.cross_refs
shape. This RED suite pins the contract a new
verifier/layers/factual_sub6.py + a new dispatcher case must satisfy.

Data sources the layer is allowed to consult (per W12 spec §1):
  1. SubsixSourceReport.differential_metabolites[*]
     (name / kegg_id / hmdb_id / inchikey / inchikey_first_block /
      chebi_id when present)
  2. data/benchmark/sub6/curated_hmdb_mammalian.jsonl (fallback pool)

NOT allowed in this sprint:
  - External RaMP DB lookup (engineering doubles + triggers
    verifier-modify policy unnecessarily)

Expected at RED commit (pre-implementation):
  - case 7 (no_data_uv) PASS — fall-through dispatcher already yields UV
  - case 1-6, 8 FAIL — verify_factual_sub6 not yet implemented +
    dispatcher does not yet route FACTUAL to factual_sub6
"""
from __future__ import annotations

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)

# verify_factual_sub6 lives at verifier.layers.factual_sub6 once GREEN lands.
# At RED, importing succeeds returning a placeholder None — tests then
# fail with TypeError when calling None, which is the correct RED signal.
try:
    from verifier.layers.factual_sub6 import verify_factual_sub6
except ImportError:
    verify_factual_sub6 = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _claim(
    text: str,
    *,
    claim_type: ClaimType = ClaimType.FACTUAL,
    subject: str | None = None,
) -> ClassifiedClaim:
    """Minimal ClassifiedClaim builder for sub6 layer tests."""
    return ClassifiedClaim(
        claim_text=text,
        claim_type=claim_type,
        classifier_source="rule",
        subject=subject,
        extracted_fields=ClaimExtractedFields(),
    )


def _task_with_tyrosine() -> SubsixSourceReport:
    """A sub6b-like task with differential_metabolites for tyrosine and phenylalanine."""
    return SubsixSourceReport(
        task_id="w12_d2_tyrosine",
        task_type="compound_only_enrichment",
        ground_truth_pathway={
            "pathway_id": "RAMP_P_000000106",
            "pathway_name": "Tyrosine metabolism",
        },
        ground_truth_signal_compounds=["C00082"],
        ground_truth_noise_compounds=[],
        differential_metabolites=[
            {
                "name": "L-tyrosine",
                "kegg_id": "C00082",
                "hmdb_id": "HMDB0000158",
                "inchikey": "OUYCCCASQSFEME-QMMMGPOBSA-N",
                "inchikey_first_block": "OUYCCCASQSFEME",
                "chebi_id": "CHEBI:17895",
            },
            {
                "name": "Phenylalanine",
                "kegg_id": "C00079",
                "hmdb_id": "HMDB0000159",
                "inchikey_first_block": "COLNVLDHVKWLRT",
            },
        ],
        ramp_enrichment_result={"top_pathways": []},
    )


def _task_empty() -> SubsixSourceReport:
    """Task with no differential_metabolites — for the no-data UV case."""
    return SubsixSourceReport(
        task_id="w12_d2_empty",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "X", "pathway_name": "Y"},
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=[],
        differential_metabolites=[],
        ramp_enrichment_result={"top_pathways": []},
    )


# ---------------------------------------------------------------------------
# 8 RED cases
# ---------------------------------------------------------------------------


def test_factual_kegg_id_match_in_differential_metabolites_supported():
    """Case 1 — FACTUAL claim 'L-tyrosine has KEGG ID C00082' matches
    differential_metabolites[0] (kegg_id=C00082) → SUPPORTED.

    Expected at RED: FAIL (verify_factual_sub6 not implemented).
    """
    task = _task_with_tyrosine()
    claim = _claim(
        "L-tyrosine has KEGG ID C00082",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_factual_id_match_in_curated_jsonl_supported():
    """Case 2 — claim 'Pyruvic acid has KEGG ID C00022' — Pyruvic not in task
    differential_metabolites, but it IS in curated_hmdb_mammalian.jsonl
    (kegg_id=C00022) → SUPPORTED via curated fallback.

    Expected at RED: FAIL.
    """
    task = _task_empty()
    claim = _claim(
        "Pyruvic acid has KEGG ID C00022",
        claim_type=ClaimType.FACTUAL,
        subject="Pyruvic acid",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_factual_kegg_id_mismatch_contradicted():
    """Case 3 — claim 'L-tyrosine has KEGG ID C99999' — task diff_metab has
    L-tyrosine with kegg_id=C00082 (not C99999) → CONTRADICTED with
    correction='C00082'.

    Expected at RED: FAIL.
    """
    task = _task_with_tyrosine()
    claim = _claim(
        "L-tyrosine has KEGG ID C99999",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.CONTRADICTED, result.evidence
    assert "C00082" in (result.correction or ""), (
        f"expected correction to mention C00082, got correction={result.correction!r}"
    )


def test_grounded_metabolite_field_lookup_supported():
    """Case 4 — GROUNDED claim 'L-tyrosine has InChIKey OUYCCCASQSFEME' —
    diff_metab has L-tyrosine with inchikey_first_block=OUYCCCASQSFEME → SUPPORTED.

    Expected at RED: FAIL.
    """
    task = _task_with_tyrosine()
    claim = _claim(
        "L-tyrosine has InChIKey OUYCCCASQSFEME",
        claim_type=ClaimType.GROUNDED,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_factual_chebi_id_supported():
    """Case 5 — FACTUAL claim 'L-tyrosine has CHEBI ID CHEBI:17895' —
    diff_metab has chebi_id=CHEBI:17895 → SUPPORTED.

    Expected at RED: FAIL.
    """
    task = _task_with_tyrosine()
    claim = _claim(
        "L-tyrosine has CHEBI ID CHEBI:17895",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_factual_hmdb_id_supported():
    """Case 6 — FACTUAL claim 'L-tyrosine has HMDB ID HMDB0000158' —
    diff_metab has hmdb_id=HMDB0000158 → SUPPORTED.

    Expected at RED: FAIL.
    """
    task = _task_with_tyrosine()
    claim = _claim(
        "L-tyrosine has HMDB ID HMDB0000158",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_factual_no_data_uv():
    """Case 7 (regression) — empty differential_metabolites + nonexistent
    compound (not in curated pool) → UV via dispatcher fall-through.

    Routed through the dispatcher (not directly through verify_factual_sub6)
    so that pre-impl this test PASSES: the current fall-through already
    yields UNVERIFIABLE_V0 for FACTUAL claim_type. After GREEN, the new
    factual_sub6 layer must preserve UV for the no-data case.

    Expected at RED: PASS (regression).
    """
    from verifier.agent import _verify_per_claim_sub6

    classified = [_claim(
        "Nonexistent_W12_test_compound has KEGG ID C99999",
        claim_type=ClaimType.FACTUAL,
        subject="Nonexistent_W12_test_compound",
    )]
    out = _verify_per_claim_sub6(
        classified, _task_empty(),
        ramp_db_path=None, ramp_conn=None, driver_lookup=None,
    )
    assert len(out) == 1
    assert out[0].verdict == ClaimVerdict.UNVERIFIABLE_V0, out[0].evidence


def test_dispatch_factual_in_sub6_routes_to_factual_sub6():
    """Case 8 — dispatcher routes ClaimType.FACTUAL to the new factual_sub6
    layer, not to the fall-through UV bucket.

    Asserts verifier_layer attribute == 'factual_sub6' on the resulting
    VerifiedClaim. At RED, fall-through sets verifier_layer='verify_sub6'
    so this assertion fails.

    Expected at RED: FAIL.
    """
    from verifier.agent import _verify_per_claim_sub6

    classified = [_claim(
        "L-tyrosine has KEGG ID C00082",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )]
    out = _verify_per_claim_sub6(
        classified, _task_with_tyrosine(),
        ramp_db_path=None, ramp_conn=None, driver_lookup=None,
    )
    assert len(out) == 1
    assert out[0].verifier_layer == "factual_sub6", (
        f"FACTUAL claim must route to factual_sub6 layer; got "
        f"verifier_layer={out[0].verifier_layer!r}, "
        f"verdict={out[0].verdict!r}"
    )
    assert out[0].verdict == ClaimVerdict.SUPPORTED, out[0].evidence
