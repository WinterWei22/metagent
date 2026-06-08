"""W17 D2 RED - SubsixSourceReport schema carrier extension."""
from __future__ import annotations

import json
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

import pytest
from pydantic import ValidationError

from schemas.sub6_report import SubsixSourceReport
from verifier.helpers.enrichment_lookup import lookup_signal_evidence
from verifier.helpers.signal_extractor import SignalMention


NEW_CARRIER_FIELDS = (
    "mummichog_enrichment_result",
    "metaboanalystr_enrichment_result",
    "sspa_enrichment_result",
    "fella_enrichment_result",
)

BENCHMARK_TASK = Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")


def _minimal_payload() -> dict[str, Any]:
    return {
        "task_id": "w17_schema_red",
        "task_type": "compound_only_enrichment",
        "domain": "mammalian",
        "ground_truth_pathway": {
            "pathway_id": "RAMP_P_TEST",
            "pathway_name": "Test pathway",
            "pathway_source": "RaMP",
            "external_id": "TEST:1",
        },
        "ground_truth_signal_compounds": ["C00001"],
        "ground_truth_noise_compounds": ["C00002"],
        "ramp_enrichment_result": {
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_TEST",
                    "pathway_name": "Test pathway",
                    "pathway_external_id": "TEST:1",
                    "p_value": 0.01,
                    "fdr": 0.02,
                    "fold_enrichment": 3.0,
                    "matched_compounds": ["C00001"],
                    "total_pathway_compounds": 1,
                }
            ]
        },
        "differential_metabolites": [],
        "differential_spectra": None,
        "compound_lookup": None,
    }


def _first_benchmark_task() -> dict[str, Any]:
    with BENCHMARK_TASK.open(encoding="utf-8") as handle:
        return json.loads(next(handle))


def _is_optional_dict_any(annotation: Any) -> bool:
    if get_origin(annotation) not in {Union, UnionType}:
        return False
    args = get_args(annotation)
    return NoneType in args and any(get_origin(arg) is dict and get_args(arg) == (str, Any) for arg in args)


def test_new_carriers_default_to_none_on_minimal_valid_constructor():
    report = SubsixSourceReport(**_minimal_payload())

    for field in NEW_CARRIER_FIELDS:
        assert getattr(report, field) is None


def test_new_carriers_accept_dict_values():
    payload = {
        **_minimal_payload(),
        "mummichog_enrichment_result": {"pathways": [{"id": "MUMM:test"}]},
        "metaboanalystr_enrichment_result": {"psea": {"pathways": []}, "msea": {}, "mummichog": {}},
        "sspa_enrichment_result": {"pathways": [{"id": "SSPA:test"}]},
        "fella_enrichment_result": {"rwr": {"pathways": []}, "diffusion": {"pathways": []}},
    }

    report = SubsixSourceReport(**payload)

    assert report.mummichog_enrichment_result == payload["mummichog_enrichment_result"]
    assert report.metaboanalystr_enrichment_result == payload["metaboanalystr_enrichment_result"]
    assert report.sspa_enrichment_result == payload["sspa_enrichment_result"]
    assert report.fella_enrichment_result == payload["fella_enrichment_result"]


def test_existing_sub6b_benchmark_task_loads_with_new_carriers_defaulted_none():
    row = _first_benchmark_task()
    original_ramp = row["ramp_enrichment_result"]

    report = SubsixSourceReport(**row)

    assert report.ramp_enrichment_result == original_ramp
    for field in NEW_CARRIER_FIELDS:
        assert getattr(report, field) is None


def test_model_dump_includes_new_carrier_field():
    report = SubsixSourceReport(
        **{
            **_minimal_payload(),
            "mummichog_enrichment_result": {"pathways": [{"pathway_id": "MUMM:test"}]},
        }
    )

    dumped = report.model_dump()

    assert dumped["mummichog_enrichment_result"] == {"pathways": [{"pathway_id": "MUMM:test"}]}


def test_new_carrier_type_hints_are_optional_dict_str_any():
    hints = get_type_hints(SubsixSourceReport)

    for field in NEW_CARRIER_FIELDS:
        assert _is_optional_dict_any(hints[field])


def test_existing_ramp_lookup_still_works_when_new_carriers_are_none():
    report = SubsixSourceReport(**_minimal_payload())
    for field in NEW_CARRIER_FIELDS:
        assert getattr(report, field) is None
    mention = SignalMention(
        metric="fdr",
        value=0.02,
        operator="eq",
        pathway_hint="Test pathway",
    )

    result = lookup_signal_evidence(mention, report)

    assert result is not None
    assert result.matched is True
    assert result.pathway_name == "Test pathway"


def test_new_carrier_rejects_invalid_type():
    with pytest.raises(ValidationError):
        SubsixSourceReport(**{**_minimal_payload(), "mummichog_enrichment_result": 42})
