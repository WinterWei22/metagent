from concord.agent.react_runner import _store_enrichment_carrier


def test_ramp_enrichment_carrier_captured():
    carriers = {}
    payload = {"ok": True, "result": {"top_pathways": [{"pathway_id": "KEGG:hsa00350", "pathway_name": "Tyrosine metabolism"}]}}
    _store_enrichment_carrier(carriers, "run_ramp_enrichment", payload)
    assert "ramp_enrichment_result" in carriers
    assert carriers["ramp_enrichment_result"]["top_pathways"][0]["pathway_id"] == "KEGG:hsa00350"


def test_ramp_carrier_skips_failed_payload():
    carriers = {}
    _store_enrichment_carrier(carriers, "run_ramp_enrichment", {"ok": False})
    assert "ramp_enrichment_result" not in carriers
