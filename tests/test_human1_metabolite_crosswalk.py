from __future__ import annotations

from pathlib import Path

from verifier.helpers.human1_metabolite_crosswalk import (
    Human1Crosswalk,
    apply_human1_crosswalk_to_task,
)


def _write_reference(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "mets\tmetsNoComp\tmetBiGGID\tmetKEGGID\tmetHMDBID\tmetChEBIID\tmetPubChemID\tmetChEMBLID",
                "MAM00001c\tMAM00001\talpha\tC00001\tHMDB0000001\tCHEBI:1\t123\tCHEMBL1",
                "MAM00002c\tMAM00002\tbeta\t\tHMDB0000002\tCHEBI:2\t456\tCHEMBL2",
                "MAM00003c\tMAM00003\tgamma\t\t\tCHEBI:3\t789\tCHEMBL3",
                "MAM00004c\tMAM00004\tdelta\t\t\t\t999\tCHEMBL4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_crosswalk_uses_kegg_hmdb_chebi_pubchem_cascade_without_chembl(tmp_path: Path) -> None:
    reference = tmp_path / "human_gem_metabolites.tsv"
    _write_reference(reference)
    crosswalk = Human1Crosswalk.from_tsv(reference)

    assert crosswalk.resolve("MAM00001").chosen_namespace == "KEGG"
    assert crosswalk.resolve("MAM00001").chosen_id == "KEGG:C00001"
    assert crosswalk.resolve("MAM00002").chosen_namespace == "HMDB"
    assert crosswalk.resolve("MAM00002").chosen_id == "HMDB:HMDB0000002"
    assert crosswalk.resolve("MAM00003").chosen_namespace == "CHEBI"
    assert crosswalk.resolve("MAM00003").chosen_id == "CHEBI:3"
    assert crosswalk.resolve("MAM00004").chosen_namespace == "PUBCHEM"
    assert crosswalk.resolve("MAM00004").chosen_id == "999"
    assert crosswalk.resolve("CHEMBL1") is None


def test_apply_crosswalk_default_off_preserves_task(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "human_gem_metabolites.tsv"
    _write_reference(reference)
    monkeypatch.delenv("METAGENT_ENABLE_HUMAN1_CROSSWALK", raising=False)
    task = {
        "ground_truth_pathway": {"ontology": "Human1"},
        "differential_metabolites": [{"id": "MAM00001", "id_type": "Human1"}],
    }

    out = apply_human1_crosswalk_to_task(task, reference_path=reference)

    assert out is task
    assert out["differential_metabolites"][0]["id"] == "MAM00001"


def test_apply_crosswalk_flag_on_only_for_human1_and_keeps_unmapped_denominator(
    tmp_path: Path, monkeypatch
) -> None:
    reference = tmp_path / "human_gem_metabolites.tsv"
    _write_reference(reference)
    monkeypatch.setenv("METAGENT_ENABLE_HUMAN1_CROSSWALK", "1")
    task = {
        "ground_truth_pathway": {"ontology": "Human1"},
        "differential_metabolites": [
            {"id": "MAM00001", "id_type": "Human1"},
            {"id": "MAM99999", "id_type": "Human1"},
        ],
    }

    out = apply_human1_crosswalk_to_task(task, reference_path=reference)

    assert out is not task
    assert [m["id"] for m in out["differential_metabolites"]] == ["KEGG:C00001", "MAM99999"]
    assert [m["id_type"] for m in out["differential_metabolites"]] == ["KEGG", "Human1"]
    assert out["human1_crosswalk"]["n_input"] == 2
    assert out["human1_crosswalk"]["n_mapped"] == 1
    assert out["human1_crosswalk"]["n_unmapped"] == 1
    assert out["human1_crosswalk"]["namespace_counts"] == {
        "KEGG": 1,
        "HMDB": 0,
        "CHEBI": 0,
        "PUBCHEM": 0,
    }


def test_apply_crosswalk_flag_on_ignores_non_human1(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "human_gem_metabolites.tsv"
    _write_reference(reference)
    monkeypatch.setenv("METAGENT_ENABLE_HUMAN1_CROSSWALK", "1")
    task = {
        "ground_truth_pathway": {"ontology": "Recon2.2"},
        "differential_metabolites": [{"id": "MAM00001", "id_type": "Human1"}],
    }

    out = apply_human1_crosswalk_to_task(task, reference_path=reference)

    assert out is task
