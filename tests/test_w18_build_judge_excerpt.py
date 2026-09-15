from __future__ import annotations

import importlib


def _builder():
    return importlib.import_module("verifier.helpers.build_judge_excerpt")


def _pathway(idx: int, *, pathway_id: str | None = None) -> dict:
    return {
        "pathway_id": pathway_id or f"MUMM:pathway_{idx}",
        "pathway_name": f"Carrier pathway {idx}",
        "rank": idx,
        "p_value": 1.5e-16,
        "fdr": 2.5e-12,
        "score": 3.25e-8,
    }


def _source_report(**overrides) -> dict:
    report = {
        "task_id": "task-1",
        "subject_name": "WP167",
        "mummichog_enrichment_result": None,
        "ramp_enrichment_result": None,
        "metaboanalystr_enrichment_result": None,
        "sspa_enrichment_result": None,
        "fella_enrichment_result": None,
        "differential_metabolites": [
            {
                "name": "15-HETE",
                "hmdb_id": "HMDB0000001",
                "kegg_id": "C04805",
                "log2fc": 1.25,
                "p_value": 4.2e-9,
                "ramp_pathway_names": ["Arachidonic acid metabolism"] * 500,
            }
        ],
        "curated_hmdb": [{"hmdb_id": "HMDB0000001"}],
    }
    report.update(overrides)
    return report


def test_excerpt_includes_mummichog_carrier_when_populated():
    excerpt = _builder().build_judge_excerpt(
        _source_report(
            mummichog_enrichment_result={
                "top_pathways": [_pathway(1, pathway_id="MUMM:arachidonic_acid_metabolism")]
            }
        )
    )
    assert "mummichog_enrichment_result" in excerpt
    assert "MUMM:arachidonic_acid_metabolism" in excerpt
    assert "Carrier pathway 1" in excerpt


def test_excerpt_includes_ramp_carrier_when_populated():
    excerpt = _builder().build_judge_excerpt(
        _source_report(
            ramp_enrichment_result={
                "top_pathways": [_pathway(1, pathway_id="RAMP_P_000025699")]
            }
        )
    )
    assert "ramp_enrichment_result" in excerpt
    assert "RAMP_P_000025699" in excerpt
    assert "2.5e-12" in excerpt


def test_excerpt_includes_all_five_carrier_families_when_populated():
    excerpt = _builder().build_judge_excerpt(
        _source_report(
            mummichog_enrichment_result={"top_pathways": [_pathway(1)]},
            ramp_enrichment_result={"top_pathways": [_pathway(2, pathway_id="RAMP_P_2")]},
            metaboanalystr_enrichment_result={"psea": {"top_pathways": [_pathway(3, pathway_id="KEGG:hsa00590")]}},
            sspa_enrichment_result={"top_pathways": [_pathway(4, pathway_id="REACT:R-HSA-1")]},
            fella_enrichment_result={"rwr": {"top_pathways": [_pathway(5, pathway_id="KEGG:hsa00010")]}},
        )
    )
    assert "mummichog_enrichment_result" in excerpt
    assert "ramp_enrichment_result" in excerpt
    assert "metaboanalystr_enrichment_result.psea" in excerpt
    assert "sspa_enrichment_result" in excerpt
    assert "fella_enrichment_result.rwr" in excerpt


def test_excerpt_marks_absent_carriers_explicitly():
    excerpt = _builder().build_judge_excerpt(_source_report())
    assert "mummichog_enrichment_result: (not populated)" in excerpt
    assert "ramp_enrichment_result: (not populated)" in excerpt
    assert "metaboanalystr_enrichment_result: (not populated)" in excerpt
    assert "sspa_enrichment_result: (not populated)" in excerpt
    assert "fella_enrichment_result: (not populated)" in excerpt


def test_excerpt_truncates_differential_metabolites_section():
    huge = [
        {
            "name": f"metabolite-{idx}",
            "hmdb_id": f"HMDB{idx:07d}",
            "kegg_id": f"C{idx:05d}",
            "description": "x" * 1000,
        }
        for idx in range(300)
    ]
    excerpt = _builder().build_judge_excerpt(_source_report(differential_metabolites=huge))
    start = excerpt.index("### Differential metabolites")
    end = excerpt.index("### Auxiliary")
    assert end - start <= 3200
    assert "metabolite-0" in excerpt
    assert "metabolite-299" not in excerpt


def test_excerpt_size_is_bounded_to_prompt_budget():
    report = _source_report(
        mummichog_enrichment_result={"top_pathways": [_pathway(i) for i in range(200)]},
        ramp_enrichment_result={"top_pathways": [_pathway(i, pathway_id=f"RAMP_P_{i}") for i in range(200)]},
        differential_metabolites=[{"name": f"m-{i}", "description": "y" * 1000} for i in range(300)],
        auxiliary_blob="z" * 50_000,
    )
    excerpt = _builder().build_judge_excerpt(report)
    assert len(excerpt) <= 10_500


def test_excerpt_orders_carriers_before_metabolites():
    excerpt = _builder().build_judge_excerpt(
        _source_report(
            mummichog_enrichment_result={"top_pathways": [_pathway(1)]}
        )
    )
    assert excerpt.index("### Mummichog enrichment") < excerpt.index("### Differential metabolites")


def test_excerpt_includes_metaboanalystr_psea_sub_carrier():
    excerpt = _builder().build_judge_excerpt(
        _source_report(
            metaboanalystr_enrichment_result={
                "psea": {"top_pathways": [_pathway(1, pathway_id="KEGG:hsa00590")]}
            }
        )
    )
    assert "metaboanalystr_enrichment_result.psea" in excerpt
    assert "KEGG:hsa00590" in excerpt


def test_excerpt_preserves_complete_carrier_section_before_truncating_metabolites():
    long_metabolites = [{"name": f"m-{idx}", "description": "z" * 2000} for idx in range(300)]
    excerpt = _builder().build_judge_excerpt(
        _source_report(
            mummichog_enrichment_result={"top_pathways": [_pathway(1), _pathway(2)]},
            differential_metabolites=long_metabolites,
        )
    )
    assert "MUMM:pathway_1" in excerpt
    assert "MUMM:pathway_2" in excerpt
    assert excerpt.index("MUMM:pathway_2") < excerpt.index("### Differential metabolites")
