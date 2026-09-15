"""Tests for verifier/helpers/multisource_enrichment.py — Task 3 TDD RED→GREEN."""
from verifier.helpers.multisource_enrichment import build_pathway_pool, match_in_pool
from schemas.sub6_report import SubsixSourceReport


def _src(**carriers):
    base = dict(task_id="t", task_type="compound_only_enrichment", domain="KEGG",
                ground_truth_pathway={}, ground_truth_signal_compounds=[],
                ground_truth_noise_compounds=[], ramp_enrichment_result={"top_pathways": []})
    base.update(carriers)
    return SubsixSourceReport(**base)


def test_pool_merges_all_paradigms():
    src = _src(
        ramp_enrichment_result={"top_pathways": [{"pathway_id": "KEGG:hsa00350", "pathway_name": "Tyrosine metabolism"}]},
        mummichog_enrichment_result={"pathways": [{"pathway_id": "MUMM:histidine", "pathway_name": "Histidine metabolism"}]},
    )
    pool = build_pathway_pool(src)
    paradigms = {row["_paradigm"] for row in pool}
    assert "ramp" in paradigms and "mummichog" in paradigms


def test_match_hits_any_paradigm():
    src = _src(mummichog_enrichment_result={"pathways": [{"pathway_id": "MUMM:histidine", "pathway_name": "Histidine metabolism"}]})
    pool = build_pathway_pool(src)
    hit = match_in_pool(pool, None, "Histidine metabolism")
    assert hit is not None and hit["_paradigm"] == "mummichog"


def test_match_returns_none_when_absent():
    src = _src(ramp_enrichment_result={"top_pathways": [{"pathway_id": "KEGG:hsa00350", "pathway_name": "Tyrosine metabolism"}]})
    pool = build_pathway_pool(src)
    assert match_in_pool(pool, None, "Glycolysis") is None
