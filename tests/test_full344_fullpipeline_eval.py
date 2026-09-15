from __future__ import annotations

from pathlib import Path

from scripts.metagent import full344_fullpipeline_eval as full344


def test_stratum_of_splits_human1_recon_and_ramp_home_turf() -> None:
    assert full344.stratum_of(
        {"ground_truth": {"perturbed_pathway": {"ontology": "Human1"}}}
    ) == "human1"
    assert full344.stratum_of(
        {"ground_truth": {"perturbed_pathway": {"ontology": "Recon2.2"}}}
    ) == "recon22"
    assert full344.stratum_of(
        {"ground_truth": {"perturbed_pathway": {"ontology": "RaMP:kegg"}}}
    ) == "hmdb_ramp"


def test_to_sub6_shape_applies_human1_crosswalk_only_when_enabled(tmp_path: Path) -> None:
    reference = tmp_path / "human_gem_metabolites.tsv"
    reference.write_text(
        "\n".join(
            [
                "mets\tmetsNoComp\tmetBiGGID\tmetKEGGID\tmetHMDBID\tmetChEBIID\tmetPubChemID\tmetChEMBLID",
                "MAM00001c\tMAM00001\talpha\tC00001\tHMDB0000001\tCHEBI:1\t123\tCHEMBL1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    raw = {
        "task_id": "human1_test",
        "difficulty": "easy",
        "ground_truth": {
            "perturbed_pathway": {
                "id": "group1",
                "name": "Acyl-CoA hydrolysis",
                "ontology": "Human1",
            }
        },
        "input": {
            "differential_metabolites": [
                {"id": "MAM00001", "id_type": "Human1", "name": "alpha"}
            ]
        },
        "provenance": {"source": "Cooke 2025 simulatedPA"},
    }

    off = full344.to_sub6_shape(raw, enable_human1_crosswalk=False, crosswalk_reference=reference)
    on = full344.to_sub6_shape(raw, enable_human1_crosswalk=True, crosswalk_reference=reference)

    assert off["differential_metabolites"][0]["id"] == "MAM00001"
    assert "human1_crosswalk" not in off
    assert on["differential_metabolites"][0]["id"] == "KEGG:C00001"
    assert on["differential_metabolites"][0]["id_type"] == "KEGG"
    assert on["human1_crosswalk"]["n_mapped"] == 1


def test_llm_config_supports_openai_gpt55_without_minimax_override(tmp_path: Path, monkeypatch) -> None:
    key_file = tmp_path / "api_key_gpt.txt"
    key_file.write_text("gpt-test-key\n", encoding="utf-8")
    monkeypatch.delenv("METAGENT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    env = full344.llm_env_for_child(
        provider="openai",
        model="gpt-5.5",
        log_path=tmp_path / "gpt55.jsonl",
        openai_key_file=key_file,
    )

    assert env["METAGENT_LLM_PROVIDER"] == "openai"
    assert env["METAGENT_OPENAI_MODEL"] == "gpt-5.5"
    assert env["METAGENT_OPENAI_API_KEY"] == "gpt-test-key"
    assert env["METAGENT_LLM_LOG_PATH"].endswith("gpt55.jsonl")
    assert "METAGENT_MINIMAX_MODEL" not in env
