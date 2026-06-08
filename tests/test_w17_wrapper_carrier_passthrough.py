"""W17 D2 RED - wrapper output carriers pass into SubsixSourceReport."""
from __future__ import annotations

from typing import Any

from concord.agent.verifier_adapter import sub6b_task_to_subsix_source_report


def _base_task() -> dict[str, Any]:
    return {
        "task_id": "w17_passthrough_red",
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
        "ramp_enrichment_result": {"top_pathways": []},
        "differential_metabolites": [],
        "differential_spectra": None,
    }


def test_mummichog_wrapper_output_passes_to_source_report():
    task = {
        **_base_task(),
        "mummichog_enrichment_result": {"pathways": [{"pathway_id": "MUMM:test"}]},
    }

    report = sub6b_task_to_subsix_source_report(task)

    assert report.mummichog_enrichment_result == task["mummichog_enrichment_result"]


def test_metaboanalystr_psea_wrapper_output_passes_to_nested_source_report():
    task = {
        **_base_task(),
        "metaboanalystr_enrichment_result": {
            "psea": {"pathways": [{"pathway_id": "KEGG:test"}]},
            "msea": None,
            "mummichog": None,
        },
    }

    report = sub6b_task_to_subsix_source_report(task)

    assert report.metaboanalystr_enrichment_result["psea"] == task["metaboanalystr_enrichment_result"]["psea"]


def test_metaboanalystr_msea_and_mummichog_variants_pass_to_nested_source_report():
    task = {
        **_base_task(),
        "metaboanalystr_enrichment_result": {
            "psea": None,
            "msea": {"pathways": [{"pathway_id": "MSEA:test"}]},
            "mummichog": {"pathways": [{"pathway_id": "MA_MUMM:test"}]},
        },
    }

    report = sub6b_task_to_subsix_source_report(task)

    assert report.metaboanalystr_enrichment_result["msea"] == task["metaboanalystr_enrichment_result"]["msea"]
    assert report.metaboanalystr_enrichment_result["mummichog"] == task["metaboanalystr_enrichment_result"]["mummichog"]


def test_sspa_wrapper_output_passes_to_source_report():
    task = {
        **_base_task(),
        "sspa_enrichment_result": {"pathways": [{"pathway_id": "SSPA:test"}]},
    }

    report = sub6b_task_to_subsix_source_report(task)

    assert report.sspa_enrichment_result == task["sspa_enrichment_result"]


def test_fella_rwr_and_diffusion_outputs_pass_to_nested_source_report():
    task = {
        **_base_task(),
        "fella_enrichment_result": {
            "rwr": {"pathways": [{"pathway_id": "FELLA_RWR:test"}]},
            "diffusion": {"pathways": [{"pathway_id": "FELLA_DIFF:test"}]},
        },
    }

    report = sub6b_task_to_subsix_source_report(task)

    assert report.fella_enrichment_result["rwr"] == task["fella_enrichment_result"]["rwr"]
    assert report.fella_enrichment_result["diffusion"] == task["fella_enrichment_result"]["diffusion"]
