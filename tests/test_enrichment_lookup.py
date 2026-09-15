"""W16 D2 RED - enrichment signal lookup helper."""
from __future__ import annotations

import pytest

from schemas.sub6_report import SubsixSourceReport


def _signal_mention(**kwargs):
    try:
        from verifier.helpers.signal_extractor import SignalMention
    except ImportError as exc:
        pytest.fail(f"SignalMention not implemented: {exc}")
    return SignalMention(**kwargs)


def _lookup_signal_evidence(mention, task):
    try:
        from verifier.helpers.enrichment_lookup import lookup_signal_evidence
    except ImportError as exc:
        pytest.fail(f"enrichment_lookup helper not implemented: {exc}")
    return lookup_signal_evidence(mention, task)


def _task() -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="w16_lookup",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "RAMP_P_1", "pathway_name": "Tyrosine metabolism"},
        ground_truth_signal_compounds=["C00082"],
        ground_truth_noise_compounds=[],
        differential_metabolites=[],
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_1",
                    "pathway_name": "Tyrosine metabolism",
                    "pathway_source": "kegg",
                    "pathway_external_id": "map00350",
                    "p_value": 8.40e-5,
                    "fdr": 1.12e-9,
                    "fold_enrichment": 12.5,
                    "matched_compounds": ["C00082", "C00400", "C00079", "C00166", "C00355"],
                    "total_pathway_compounds": 27,
                },
                {
                    "pathway_id": "RAMP_P_2",
                    "pathway_name": "Eicosanoid synthesis",
                    "pathway_source": "smpdb",
                    "pathway_external_id": "SMP00001",
                    "p_value": 6.1e-8,
                    "fdr": 6.97e-14,
                    "matched_compounds": ["C14768", "C14769", "C14770", "C14771", "C14772"],
                    "total_pathway_compounds": 27,
                },
            ],
        },
    )


def test_lookup_exact_p_value_by_pathway_hint():
    match = _lookup_signal_evidence(
        _signal_mention(metric="p_value", value=8.40e-5, pathway_hint="Tyrosine metabolism"),
        _task(),
    )
    assert match is not None
    assert match.matched is True
    assert match.metric == "p_value"
    assert match.actual_value == pytest.approx(8.40e-5)
    assert match.pathway_name == "Tyrosine metabolism"


def test_lookup_fdr_threshold_with_less_than_operator():
    match = _lookup_signal_evidence(
        _signal_mention(metric="fdr", value=1e-8, operator="lt", pathway_hint="Tyrosine metabolism"),
        _task(),
    )
    assert match is not None
    assert match.matched is True
    assert match.actual_value == pytest.approx(1.12e-9)


def test_lookup_rank_by_mumm_namespace_pathway_hint():
    match = _lookup_signal_evidence(
        _signal_mention(metric="rank", value=2, pathway_hint="Eicosanoid synthesis", method="mummichog"),
        _task(),
    )
    assert match is not None
    assert match.matched is True
    assert match.actual_value == pytest.approx(2)


def test_lookup_overlap_count_from_matched_compounds():
    match = _lookup_signal_evidence(
        _signal_mention(metric="overlap_count", value=5, total=27, pathway_hint="Eicosanoid synthesis"),
        _task(),
    )
    assert match is not None
    assert match.matched is True
    assert match.actual_value == pytest.approx(5)
    assert match.actual_total == pytest.approx(27)


def test_lookup_mismatch_returns_nonmatching_result_with_actual_value():
    match = _lookup_signal_evidence(
        _signal_mention(metric="p_value", value=0.05, pathway_hint="Tyrosine metabolism"),
        _task(),
    )
    assert match is not None
    assert match.matched is False
    assert match.actual_value == pytest.approx(8.40e-5)


def test_lookup_missing_pathway_returns_none():
    assert _lookup_signal_evidence(
        _signal_mention(metric="p_value", value=0.05, pathway_hint="Missing pathway"),
        _task(),
    ) is None
