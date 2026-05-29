"""W16 D2 RED - signal evidence extraction helpers."""
from __future__ import annotations

import pytest


def _extract_signal_mentions(text: str):
    try:
        from verifier.helpers.signal_extractor import extract_signal_mentions
    except ImportError as exc:
        pytest.fail(f"signal_extractor helper not implemented: {exc}")
    return extract_signal_mentions(text)


def _one(text: str):
    mentions = _extract_signal_mentions(text)
    assert len(mentions) == 1
    return mentions[0]


def test_extracts_mummichog_p_value_scientific_notation():
    m = _one("Mummichog m/z-direct activity has p-value 8.40e-5")
    assert m.method == "mummichog"
    assert m.metric == "p_value"
    assert m.value == pytest.approx(8.40e-5)
    assert m.operator == "eq"


def test_extracts_fdr_threshold():
    m = _one("17-Beta Hydroxysteroid Dehydrogenase III Deficiency has FDR < 1e-12")
    assert m.metric == "fdr"
    assert m.value == pytest.approx(1e-12)
    assert m.operator == "lt"


def test_extracts_rank_from_namespace_claim():
    m = _one("MUMM:tyrosine_metabolism has rank-3")
    assert m.method == "mummichog"
    assert m.metric == "rank"
    assert m.value == pytest.approx(3)
    assert m.pathway_hint == "tyrosine metabolism"


def test_extracts_overlap_count_and_total():
    m = _one("Five metabolites overlapped the 27-member roster of Eicosanoid synthesis")
    assert m.metric == "overlap_count"
    assert m.value == pytest.approx(5)
    assert m.total == pytest.approx(27)
    assert m.pathway_hint == "eicosanoid synthesis"


def test_extracts_compound_count():
    m = _one("MUMM:c21_steroid_hormone_biosynthesis_and_metabolism involves 15 compounds")
    assert m.method == "mummichog"
    assert m.metric == "total_compounds"
    assert m.value == pytest.approx(15)


def test_extracts_top_hit_count_with_fdr():
    mentions = _extract_signal_mentions("The top-6 hits have FDR = 1.12e-09")
    assert [(m.metric, m.value) for m in mentions] == [
        ("rank_cutoff", pytest.approx(6)),
        ("fdr", pytest.approx(1.12e-9)),
    ]


def test_ignores_molecular_formula_as_not_signal_evidence():
    assert _extract_signal_mentions("N-carbamoyl-beta-alanine has molecular formula C4H8N2O3") == []


def test_ignores_qualitative_significance_without_value():
    assert _extract_signal_mentions("Xanthine did not reach significance in any tool") == []
