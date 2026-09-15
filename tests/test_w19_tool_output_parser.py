from __future__ import annotations

import importlib


def _parser():
    return importlib.import_module("verifier.helpers.tool_output_claim_parser")


def test_detects_ramp_fdr_claim():
    parsed = _parser().parse_tool_output_claim(
        "RaMP-DB over-representation analysis has FDR 1.42e-8"
    )
    assert parsed.method == "ramp"
    assert parsed.metric == "fdr"
    assert parsed.value == 1.42e-8


def test_detects_hyphenated_fold_enrichment_claim():
    parsed = _parser().parse_tool_output_claim(
        "RaMP ORA produces a fold-enrichment of 1801"
    )
    assert parsed.method == "ramp"
    assert parsed.metric == "fold_enrichment"
    assert parsed.value == 1801.0


def test_detects_mummichog_rank_claim():
    parsed = _parser().parse_tool_output_claim(
        "MUMM:xenobiotics_metabolism ranked 3 in mummichog"
    )
    assert parsed.method == "mummichog"
    assert parsed.metric == "rank"
    assert parsed.pathway_hint == "MUMM:xenobiotics_metabolism"
    assert parsed.value == 3


def test_detects_mummichog_p_value_claim():
    parsed = _parser().parse_tool_output_claim(
        "MUMM:vitamin_b6_pyridoxine_metabolism has p=0.031 in mummichog"
    )
    assert parsed.method == "mummichog"
    assert parsed.metric == "p_value"
    assert parsed.pathway_hint == "MUMM:vitamin_b6_pyridoxine_metabolism"
    assert parsed.value == 0.031


def test_detects_overlap_claim():
    parsed = _parser().parse_tool_output_claim(
        "mummichog has an overlap of 10 out of 11 compounds"
    )
    assert parsed.method == "mummichog"
    assert parsed.metric == "overlap"
    assert parsed.value == (10, 11)


def test_detects_top_hit_claim():
    parsed = _parser().parse_tool_output_claim(
        "RaMP multi-database over-representation analysis returned Pyrimidine catabolism as the top hit"
    )
    assert parsed.method == "ramp"
    assert parsed.metric == "rank"
    assert parsed.pathway_hint == "Pyrimidine catabolism"
    assert parsed.value == 0


def test_rejects_interpretive_tool_confirmation():
    parsed = _parser().parse_tool_output_claim(
        "Mummichog provides orthogonal empirical-compound confirmation"
    )
    assert parsed is None


def test_rejects_multi_tool_convergence_claim():
    parsed = _parser().parse_tool_output_claim(
        "RaMP, MetaboAnalystR, and Mummichog converged on two metabolic modules"
    )
    assert parsed is None


def test_rejects_interpretive_adjective_without_isolating_subclaim():
    parsed = _parser().parse_tool_output_claim(
        "L-tyrosine and norepinephrine are cornerstone compounds matching the RaMP hit list"
    )
    assert parsed is None
