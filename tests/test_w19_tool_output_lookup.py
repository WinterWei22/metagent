from __future__ import annotations

import importlib


def _lookup():
    return importlib.import_module("verifier.helpers.tool_output_lookup")


def _source_report() -> dict:
    return {
        "ramp_enrichment_result": {
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_1",
                    "pathway_name": "Pyrimidine catabolism",
                    "rank": 0,
                    "p_value": 8.93e-11,
                    "fdr": 1.42e-8,
                    "fold_enrichment": 1801.0,
                    "metabolites_hit": [{"display_name": "5,6-dihydrouracil"}],
                }
            ]
        },
        "mummichog_enrichment_result": {
            "pathways": [
                {
                    "pathway_id": "MUMM:xenobiotics_metabolism",
                    "pathway_name": "Xenobiotics metabolism",
                    "rank": 3,
                    "score": 0.031,
                    "score_type": "p_value",
                    "metabolites_hit": [
                        {"display_name": "coumarin"},
                        {"display_name": "4-Pyridoxic acid"},
                    ],
                    "auxiliary_scores": {"overlap_size": 10, "pathway_size": 11},
                }
            ]
        },
        "metaboanalystr_enrichment_result": {
            "psea": {
                "pathways": [
                    {
                        "pathway_name": "Arachidonic acid metabolism",
                        "p_value": 9.53e-10,
                        "rank": 0,
                    }
                ]
            }
        },
    }


def test_ramp_numeric_match_returns_supported_evidence():
    evidence = _lookup().lookup_tool_output_evidence(
        "RaMP-DB over-representation analysis has FDR 1.42e-8",
        _source_report(),
    )
    assert evidence.status == "match"
    assert evidence.method == "ramp"
    assert evidence.source_field == "ramp_enrichment_result.top_pathways[0].fdr"


def test_ramp_numeric_mismatch_returns_contradiction_evidence():
    evidence = _lookup().lookup_tool_output_evidence(
        "RaMP-DB over-representation analysis has FDR 9.99e-9",
        _source_report(),
    )
    assert evidence.status == "mismatch"
    assert evidence.observed == 1.42e-8


def test_mummichog_rank_match_uses_mummichog_carrier_only():
    evidence = _lookup().lookup_tool_output_evidence(
        "MUMM:xenobiotics_metabolism ranked 3 in mummichog",
        _source_report(),
    )
    assert evidence.status == "match"
    assert evidence.method == "mummichog"
    assert evidence.source_field == "mummichog_enrichment_result.pathways[0].rank"


def test_metaboanalystr_psea_numeric_match_uses_psea_subcarrier():
    evidence = _lookup().lookup_tool_output_evidence(
        "MetaboAnalystR PSEA produces a p-value of 9.53e-10",
        _source_report(),
    )
    assert evidence.status == "match"
    assert evidence.method == "metaboanalystr"
    assert evidence.source_field == "metaboanalystr_enrichment_result.psea.pathways[0].p_value"


def test_missing_matching_carrier_returns_absent_not_contradicted():
    report = {"ramp_enrichment_result": {"top_pathways": []}}
    evidence = _lookup().lookup_tool_output_evidence(
        "MUMM:xenobiotics_metabolism ranked 3 in mummichog",
        report,
    )
    assert evidence.status == "absent"
    assert evidence.method == "mummichog"


def test_source_mismatch_does_not_fallback_to_ramp():
    report = {
        "ramp_enrichment_result": {"top_pathways": [{"pathway_name": "Xenobiotics metabolism", "rank": 3}]},
        "mummichog_enrichment_result": None,
    }
    evidence = _lookup().lookup_tool_output_evidence(
        "MUMM:xenobiotics_metabolism ranked 3 in mummichog",
        report,
    )
    assert evidence.status == "absent"


def test_parse_failure_returns_unparsed():
    evidence = _lookup().lookup_tool_output_evidence(
        "Mummichog provides orthogonal empirical-compound confirmation",
        _source_report(),
    )
    assert evidence.status == "unparsed"


def test_overlap_match_uses_auxiliary_scores():
    evidence = _lookup().lookup_tool_output_evidence(
        "mummichog has an overlap of 10 out of 11 compounds",
        _source_report(),
    )
    assert evidence.status == "match"
    assert evidence.source_field == "mummichog_enrichment_result.pathways[0].auxiliary_scores.overlap_size"
