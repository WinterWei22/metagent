from __future__ import annotations

import json
from pathlib import Path

from tools.lipidmaps import LipidMapsClient


def _write_fixture(root: Path) -> tuple[Path, Path]:
    lmsd = root / "lmsd.tsv"
    lmsd.write_text(
        "05/08/26\n"
        "regno\tlm_id\tname\tsys_name\tcore\tmain_class\tsub_class\tclass_level4\t"
        "exactmass\tformula\tinchi\tinchi_key\tkegg_id\thmdb_id\tchebi_id\t"
        "lipidbank_id\tpubchem_cid\tsmiles\n"
        "1\tLMST01010001\tCholesterol\tcholest-5-en-3beta-ol\tSterols [ST]\t"
        "Sterols [ST01]\tCholesterol and derivatives [ST0101]\t\t386.354866\t"
        "C27H46O\tInChI=stub\tHVYWMOMLDIMFJA-DPAQBDIFSA-N\tC00187\t"
        "HMDB0000067\t16113\t\t5997\tC[C@H](CCCC(C)C)...\n",
        encoding="utf-8",
    )
    manifest = root / "lipid_pathways.json"
    manifest.write_text(
        json.dumps({
            "pathways": [
                {
                    "pathway_id": "WP4346",
                    "name": "Cholesterol metabolism",
                    "species": "Mus musculus",
                }
            ]
        }),
        encoding="utf-8",
    )
    json_dir = root / "wikipathways_json"
    json_dir.mkdir()
    (json_dir / "WP4346.json").write_text(
        json.dumps({
            "pathway": {
                "name": "Cholesterol metabolism",
                "organism": "Mus musculus",
                "dataSourceVersion": "WP4346_r1",
            },
            "entitiesById": {
                "n1": {
                    "gpmlElementName": "DataNode",
                    "wpType": "Metabolite",
                    "textContent": "Cholesterol",
                    "xrefDataSource": "LIPID MAPS",
                    "xrefIdentifier": "LMST01010001",
                    "type": [
                        "DataNode",
                        "Metabolite",
                        "LIPID MAPS:LMST01010001",
                    ],
                }
            },
        }),
        encoding="utf-8",
    )
    return lmsd, manifest


def test_lipidmaps_client_lookup_full_and_first_block(tmp_path):
    lmsd, manifest = _write_fixture(tmp_path)
    client = LipidMapsClient(lmsd, manifest)

    full = client.lookup_by_inchikey("HVYWMOMLDIMFJA-DPAQBDIFSA-N")
    first = client.lookup_by_inchikey("HVYWMOMLDIMFJA")

    assert full is not None
    assert first is not None
    assert full["lm_id"] == "LMST01010001"
    assert first["lm_id"] == "LMST01010001"
    assert full["category"] == "Sterols [ST]"


def test_lipidmaps_client_lookup_compound_to_pathways(tmp_path):
    lmsd, manifest = _write_fixture(tmp_path)
    client = LipidMapsClient(lmsd, manifest)

    pathways = client.lookup_compound_to_pathways("HVYWMOMLDIMFJA")

    assert len(pathways) == 1
    assert pathways[0]["id"] == "lm_pathway:WP4346"
    assert pathways[0]["source"] == "lipidmaps"
