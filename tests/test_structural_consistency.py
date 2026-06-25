"""2D RED → GREEN test suite for verifier/layers/structural_consistency.py.

Layer 2D triggers when verify_set_enrichment returns UNVERIFIABLE_V0 for a
SET_ENRICHMENT claim.  It asks an LLM judge: "are these metabolites'
structures consistent with the claimed pathway?"
"""
from __future__ import annotations

import json

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.helpers.judge_cost_cap import JudgeCostTracker
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)

try:
    from verifier.layers.structural_consistency import verify_structural_consistency
    from verifier.helpers.structural_prompt import (
        extract_metabolites_with_smiles,
        extract_pathway_from_claim,
    )
except ImportError:
    verify_structural_consistency = None  # type: ignore[assignment]
    extract_metabolites_with_smiles = None  # type: ignore[assignment]
    extract_pathway_from_claim = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_TYROSINE_SMILES = "N[C@@H](Cc1ccc(O)cc1)C(=O)O"
_PHENYLALANINE_SMILES = "N[C@@H](Cc1ccccc1)C(=O)O"
_CHOLESTEROL_SMILES = "[C@@H]1(CC[C@@H]2[C@@]1(CC[C@H]3[C@@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C"


def _make_claim(
    text: str,
    *,
    claim_type: ClaimType = ClaimType.SET_ENRICHMENT,
    pathway_name: str | None = None,
    pathway_id: str | None = None,
) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        claim_type=claim_type,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(
            pathway_name=pathway_name,
            pathway_id=pathway_id,
        ),
    )


def _make_source(
    metabolites: list[dict] | None = None,
) -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="test_struct_consistency",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "RAMP_P_test", "pathway_name": "Tyrosine metabolism"},
        ground_truth_signal_compounds=["C00082"],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={"top_pathways": []},
        differential_metabolites=metabolites,
    )


def _judge_ok(verdict: str = "SUPPORTED", confidence: float = 0.92):
    def _judge(*, claim, source_report):
        return json.dumps({
            "verdict": verdict,
            "confidence": confidence,
            "evidence_pointer": "metabolite_smiles",
            "rationale": "test rationale",
        })
    return _judge


def _judge_fail():
    def _judge(*, claim, source_report):
        return "not json at all !@#$"
    return _judge


# ---------------------------------------------------------------------------
# Case 01 — UV when no pathway name extractable from claim
# ---------------------------------------------------------------------------


def test_01_uv_no_pathway_in_claim():
    claim = _make_claim("Several metabolites showed altered levels.")
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    result = verify_structural_consistency(claim, src, judge_call=_judge_ok())
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert result.verifier_layer == "structural_consistency"


# ---------------------------------------------------------------------------
# Case 02 — UV when differential_metabolites is None
# ---------------------------------------------------------------------------


def test_02_uv_no_metabolites():
    claim = _make_claim(
        "These metabolites are enriched in Tyrosine metabolism.",
        pathway_name="Tyrosine metabolism",
    )
    src = _make_source(metabolites=None)
    result = verify_structural_consistency(claim, src, judge_call=_judge_ok())
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert "metabolite" in result.evidence.lower()


# ---------------------------------------------------------------------------
# Case 03 — UV when no metabolites have usable SMILES
# ---------------------------------------------------------------------------


def test_03_uv_no_smiles():
    claim = _make_claim(
        "Phenylalanine metabolism enriched.",
        pathway_name="Phenylalanine metabolism",
    )
    src = _make_source([
        {"name": "L-phenylalanine", "smiles": None, "kegg_id": None, "hmdb_id": None},
        {"name": "trans-cinnamic acid", "smiles": "", "kegg_id": None, "hmdb_id": None},
    ])
    result = verify_structural_consistency(claim, src, judge_call=_judge_ok())
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# Case 04 — SUPPORTED on happy path
# ---------------------------------------------------------------------------


def test_04_supported_happy_path():
    claim = _make_claim(
        "These amino acids are enriched in Tyrosine metabolism.",
        pathway_name="Tyrosine metabolism",
    )
    metabolites = [
        {"name": "L-tyrosine", "smiles": _TYROSINE_SMILES},
        {"name": "L-phenylalanine", "smiles": _PHENYLALANINE_SMILES},
    ]
    src = _make_source(metabolites)
    result = verify_structural_consistency(claim, src, judge_call=_judge_ok("SUPPORTED", 0.92))
    assert result.verdict == ClaimVerdict.SUPPORTED
    assert result.verifier_layer == "structural_consistency"


# ---------------------------------------------------------------------------
# Case 05 — NEEDS_HUMAN_REVIEW when LLM returns HEDGED
# ---------------------------------------------------------------------------


def test_05_hedged_becomes_needs_review():
    claim = _make_claim(
        "These metabolites are partially consistent with lipid metabolism.",
        pathway_name="Lipid metabolism",
    )
    src = _make_source([{"name": "cholesterol", "smiles": _CHOLESTEROL_SMILES}])
    result = verify_structural_consistency(claim, src, judge_call=_judge_ok("HEDGED", 0.70))
    assert result.verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW


# ---------------------------------------------------------------------------
# Case 06 — UV when LLM confidence < 0.50
# ---------------------------------------------------------------------------


def test_06_uv_low_confidence():
    claim = _make_claim(
        "These metabolites are enriched in Pyrimidine metabolism.",
        pathway_name="Pyrimidine metabolism",
    )
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    result = verify_structural_consistency(claim, src, judge_call=_judge_ok("SUPPORTED", 0.40))
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# Case 07 — UV when LLM response is unparsable
# ---------------------------------------------------------------------------


def test_07_uv_parse_failure():
    claim = _make_claim(
        "These metabolites are enriched in Tyrosine metabolism.",
        pathway_name="Tyrosine metabolism",
    )
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    result = verify_structural_consistency(claim, src, judge_call=_judge_fail())
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# Case 08 — UV when cost cap exceeded (no LLM call)
# ---------------------------------------------------------------------------


def test_08_uv_cost_cap_exceeded():
    claim = _make_claim(
        "These metabolites are enriched in Tyrosine metabolism.",
        pathway_name="Tyrosine metabolism",
    )
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    tracker = JudgeCostTracker(cap_usd=0.001, spent_usd=0.002)
    calls = []

    def _recording_judge(*, claim, source_report):
        calls.append(1)
        return json.dumps({"verdict": "SUPPORTED", "confidence": 0.95,
                           "evidence_pointer": "x", "rationale": "r"})

    result = verify_structural_consistency(
        claim, src, judge_call=_recording_judge, cost_tracker=tracker
    )
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert len(calls) == 0


# ---------------------------------------------------------------------------
# Case 09 — Cost tracker records cost after successful call
# ---------------------------------------------------------------------------


def test_09_cost_tracker_records():
    claim = _make_claim(
        "These metabolites are enriched in Tyrosine metabolism.",
        pathway_name="Tyrosine metabolism",
    )
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    tracker = JudgeCostTracker(cap_usd=5.0, spent_usd=0.0)
    verify_structural_consistency(claim, src, judge_call=_judge_ok(), cost_tracker=tracker)
    assert tracker.spent_usd > 0


# ---------------------------------------------------------------------------
# Case 10 — Extract pathway from typed extracted_fields.pathway_name
# ---------------------------------------------------------------------------


def test_10_pathway_from_extracted_fields():
    claim = _make_claim("Something was enriched.", pathway_name="Tyrosine metabolism")
    name = extract_pathway_from_claim(claim)
    assert name == "Tyrosine metabolism"


# ---------------------------------------------------------------------------
# Case 11 — Extract pathway from claim text via regex fallback
# ---------------------------------------------------------------------------


def test_11_pathway_from_text_regex():
    claim = _make_claim(
        "These compounds are enriched in Arachidonic acid metabolism according to RaMP.",
    )
    name = extract_pathway_from_claim(claim)
    assert name is not None
    assert "metabolism" in name.lower()


# ---------------------------------------------------------------------------
# Case 12 — No pathway name in text → returns None
# ---------------------------------------------------------------------------


def test_12_no_pathway_returns_none():
    claim = _make_claim("Several compounds were elevated.")
    name = extract_pathway_from_claim(claim)
    assert name is None


# ---------------------------------------------------------------------------
# Case 13 — extract_metabolites_with_smiles filters metabolites without SMILES
# ---------------------------------------------------------------------------


def test_13_extract_metabolites_filters_no_smiles():
    metabolites = [
        {"name": "L-tyrosine", "smiles": _TYROSINE_SMILES},
        {"name": "unknown", "smiles": None},
        {"name": "blank", "smiles": ""},
    ]
    src = _make_source(metabolites)
    result = extract_metabolites_with_smiles(src)
    assert len(result) == 1
    assert result[0]["name"] == "L-tyrosine"
    assert result[0]["smiles"] == _TYROSINE_SMILES


# ---------------------------------------------------------------------------
# Case 14 — extract_metabolites_with_smiles caps at max_items
# ---------------------------------------------------------------------------


def test_14_extract_metabolites_max_items():
    metabolites = [{"name": f"compound_{i}", "smiles": _TYROSINE_SMILES} for i in range(12)]
    src = _make_source(metabolites)
    result = extract_metabolites_with_smiles(src, max_items=8)
    assert len(result) == 8


# ---------------------------------------------------------------------------
# Case 15 — extract_metabolites_with_smiles returns empty for None source
# ---------------------------------------------------------------------------


def test_15_extract_metabolites_none_source():
    src = _make_source(metabolites=None)
    result = extract_metabolites_with_smiles(src)
    assert result == []


# ---------------------------------------------------------------------------
# Case 16 — SUPPORTED result carries correct metadata
# ---------------------------------------------------------------------------


def test_16_result_metadata():
    claim = _make_claim(
        "These metabolites are enriched in Tyrosine metabolism.",
        pathway_name="Tyrosine metabolism",
    )
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    result = verify_structural_consistency(claim, src, judge_call=_judge_ok())
    assert result.verifier_layer == "structural_consistency"
    assert result.claim_type == ClaimType.SET_ENRICHMENT


# ---------------------------------------------------------------------------
# Case 17 — Falls back to pathway_id when no pathway_name
# ---------------------------------------------------------------------------


def test_17_fallback_to_pathway_id():
    claim = _make_claim("Enrichment observed.", pathway_id="map00350")
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    result = verify_structural_consistency(claim, src, judge_call=_judge_ok())
    assert result.verdict in (
        ClaimVerdict.SUPPORTED,
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        ClaimVerdict.UNVERIFIABLE_V0,
    )


# ---------------------------------------------------------------------------
# Case 18 — LLM returns UNVERIFIABLE_V0 → layer returns UV
# ---------------------------------------------------------------------------


def test_18_llm_returns_uv():
    claim = _make_claim(
        "These metabolites are enriched in Tyrosine metabolism.",
        pathway_name="Tyrosine metabolism",
    )
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    result = verify_structural_consistency(
        claim, src, judge_call=_judge_ok("UNVERIFIABLE_V0", 0.90)
    )
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# Case 19 — SUPPORTED verdict with confidence 0.50-0.85 → NEEDS_HUMAN_REVIEW
# ---------------------------------------------------------------------------


def test_19_medium_confidence_hedged():
    claim = _make_claim(
        "These metabolites are enriched in Tyrosine metabolism.",
        pathway_name="Tyrosine metabolism",
    )
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    result = verify_structural_consistency(
        claim, src, judge_call=_judge_ok("SUPPORTED", 0.70)
    )
    assert result.verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW


# ---------------------------------------------------------------------------
# Case 20 — Multiple metabolites: judge called exactly once
# ---------------------------------------------------------------------------


def test_20_multiple_metabolites_called():
    claim = _make_claim(
        "These amino acids are enriched in Phenylalanine metabolism.",
        pathway_name="Phenylalanine metabolism",
    )
    metabolites = [
        {"name": "L-tyrosine", "smiles": _TYROSINE_SMILES},
        {"name": "L-phenylalanine", "smiles": _PHENYLALANINE_SMILES},
        {"name": "cholesterol", "smiles": _CHOLESTEROL_SMILES},
    ]
    src = _make_source(metabolites)
    calls = []

    def _counting_judge(*, claim, source_report):
        calls.append(1)
        return json.dumps({
            "verdict": "SUPPORTED",
            "confidence": 0.90,
            "evidence_pointer": "metabolite_smiles",
            "rationale": "aromatic amino acids consistent with phenylalanine pathway",
        })

    result = verify_structural_consistency(claim, src, judge_call=_counting_judge)
    assert len(calls) == 1
    assert result.verdict == ClaimVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# Case 21 — Non-SET_ENRICHMENT claim type → UV immediately, no LLM call
# ---------------------------------------------------------------------------


def test_21_wrong_claim_type_uv():
    claim = ClassifiedClaim(
        claim_text="L-tyrosine has molecular formula C9H11NO3.",
        claim_type=ClaimType.FACTUAL,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(pathway_name="Tyrosine metabolism"),
    )
    src = _make_source([{"name": "L-tyrosine", "smiles": _TYROSINE_SMILES}])
    calls = []

    def _recording_judge(*, claim, source_report):
        calls.append(1)
        return json.dumps({"verdict": "SUPPORTED", "confidence": 0.95,
                           "evidence_pointer": "x", "rationale": "r"})

    result = verify_structural_consistency(claim, src, judge_call=_recording_judge)
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert len(calls) == 0


# ---------------------------------------------------------------------------
# Case 22 — Empty differential_metabolites list → UV
# ---------------------------------------------------------------------------


def test_22_empty_metabolites_list():
    claim = _make_claim(
        "These metabolites are enriched in Tyrosine metabolism.",
        pathway_name="Tyrosine metabolism",
    )
    src = _make_source(metabolites=[])
    result = verify_structural_consistency(claim, src, judge_call=_judge_ok())
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
