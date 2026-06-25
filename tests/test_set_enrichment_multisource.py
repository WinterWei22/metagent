"""Test: verify_set_enrichment uses multisource pool — Task 4 (D1.2).

A claim whose pathway appears in a non-RaMP paradigm (e.g. mummichog) must be
SUPPORTED even when ramp_enrichment_result.top_pathways is empty.
"""
from verifier.layers.set_enrichment import verify_set_enrichment
from verifier.schemas import ClaimVerdict, ClaimType, ClaimSubtype, ClassifiedClaim, ClaimExtractedFields
from schemas.sub6_report import SubsixSourceReport


def _claim(name):
    return ClassifiedClaim(claim_text=f"enriched in {name}", claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY, classifier_source="rule",
        extracted_fields=ClaimExtractedFields(pathway_name=name))


def _src(**c):
    base = dict(task_id="t", task_type="compound_only_enrichment", domain="KEGG",
        ground_truth_pathway={}, ground_truth_signal_compounds=[], ground_truth_noise_compounds=[],
        ramp_enrichment_result={"top_pathways": []})
    base.update(c); return SubsixSourceReport(**base)


def test_hit_in_mummichog_only_supported():
    src = _src(mummichog_enrichment_result={"pathways": [{"pathway_id": "MUMM:histidine", "pathway_name": "Histidine metabolism"}]})
    r = verify_set_enrichment(_claim("Histidine metabolism"), src)
    assert r.verdict == ClaimVerdict.SUPPORTED
