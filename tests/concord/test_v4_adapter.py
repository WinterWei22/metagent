"""RED → GREEN tests for v4_task_to_subsix_source_report (Task 2 D0.2).

v4 benchmark row shape:
  {"task_id": str,
   "input": {"context": str, "differential_metabolites": [{name, smiles, inchikey}, ...]},
   "ground_truth": {"perturbed_pathway": {id, name, ontology}, "mechanism_evidence": {...}}}

v3 row uses flat keys like ground_truth_pathway, ramp_enrichment_result etc.
"""
from concord.agent.verifier_adapter import v4_task_to_subsix_source_report


class _FakeReact:
    enrichment_carriers = {
        "ramp_enrichment_result": {
            "top_pathways": [
                {"pathway_id": "KEGG:hsa00350", "pathway_name": "Tyrosine metabolism"}
            ]
        },
        "mummichog_enrichment_result": {
            "pathways": [{"pathway_id": "MUMM:tyrosine_metabolism"}]
        },
    }


def _v4_task():
    return {
        "task_id": "t1",
        "input": {
            "context": "",
            "differential_metabolites": [
                {
                    "name": "L-tyrosine",
                    "smiles": "N[C@@H](Cc1ccc(O)cc1)C(=O)O",
                    "inchikey": "OUYCCCASQSFEME-QMMMGPOBSA-N",
                }
            ],
        },
        "ground_truth": {
            "perturbed_pathway": {
                "id": "hsa00350",
                "name": "Tyrosine metabolism",
                "ontology": "KEGG",
            },
            "mechanism_evidence": {},
        },
    }


def test_v4_adapter_builds_report():
    r = v4_task_to_subsix_source_report(_v4_task(), _FakeReact())
    assert r.task_id == "t1"
    assert r.task_type == "compound_only_enrichment"
    assert r.ground_truth_pathway["pathway_name"] == "Tyrosine metabolism"
    assert r.ramp_enrichment_result["top_pathways"][0]["pathway_id"] == "KEGG:hsa00350"
    assert r.mummichog_enrichment_result is not None
    assert r.differential_metabolites[0]["name"] == "L-tyrosine"


def test_v4_adapter_empty_ground_truth_compounds():
    r = v4_task_to_subsix_source_report(_v4_task(), _FakeReact())
    assert r.ground_truth_signal_compounds == []
    assert r.ground_truth_noise_compounds == []


def test_v4_adapter_domain_from_ontology():
    r = v4_task_to_subsix_source_report(_v4_task(), _FakeReact())
    assert r.domain == "KEGG"


def test_v4_adapter_ground_truth_pathway_id_mapping():
    r = v4_task_to_subsix_source_report(_v4_task(), _FakeReact())
    assert r.ground_truth_pathway["pathway_id"] == "hsa00350"
    assert r.ground_truth_pathway["pathway_source"] == "KEGG"


def test_v4_adapter_missing_optional_carriers():
    """Carriers not in enrichment_carriers should be None, not raise."""

    class _NoMumm:
        enrichment_carriers = {
            "ramp_enrichment_result": {"top_pathways": []},
        }

    r = v4_task_to_subsix_source_report(_v4_task(), _NoMumm())
    assert r.mummichog_enrichment_result is None
    assert r.metaboanalystr_enrichment_result is None
    assert r.sspa_enrichment_result is None
    assert r.fella_enrichment_result is None
