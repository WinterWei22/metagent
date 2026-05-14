"""Unit tests for ``tools.benchmark.sub6.compound_curator``.

Network-free: tiny RaMP from the conftest fixture + tiny HMDB built ad-hoc.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.benchmark.sub6.compound_curator import (
    CuratedCompound,
    CurationStats,
    _classify_pathway_bucket,
    curate_hmdb_mammalian_subset,
    curate_riken_plant_subset,
    save_curated_subsets,
)


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


def _write_riken_jsonl(path: Path, records: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def _riken_record(
    *, accession: str, inchikey: str, name: str, smiles: str = "C",
    formula: str = "C", mass: float = 100.0, peaks: int = 50,
    ce: float | None = 20.0, compound_class: str = "flavonoid",
    npc_pathway: str = "Shikimates and Phenylpropanoids",
    ce_warnings: list[str] | None = None,
) -> dict:
    rec = {
        "spectrum": {
            "mz": list(range(peaks)),
            "intensity": [1.0] * peaks,
            "precursor_mz": 200.0,
            "adduct": "[M+H]+",
            "ionization_mode": "positive",
            "collision_energy": ce,
        },
        "ground_truth": {
            "smiles": smiles,
            "inchikey": inchikey,
            "molecular_formula": formula,
            "exact_mass": mass,
            "primary_compound_name": name,
            "compound_names": [name],
            "compound_class": compound_class,
            "pubchem_cid": None,
            "npclassifier": {
                "pathway": [npc_pathway],
                "superclass": ["Flavonoids"],
                "class_": ["Flavones"],
                "isglycoside": False,
            },
        },
        "metadata": {
            "accession": accession,
            "instrument": "QTOF",
            "ms_level": "MS2",
        },
    }
    if ce_warnings:
        rec["normalization_warnings"] = ce_warnings
    return rec


@pytest.fixture
def tiny_riken_pool(tmp_path, tiny_ramp_compounds) -> Path:
    """Build a RIKEN pool that maps onto tiny_ramp.

    For each anthocyanin compound, we emit two spectra (one with peaks=50/CE=20
    that should pass; one with peaks=10/CE=5 that should fail). For each
    flavonoid compound, one passing spectrum. Plus 3 organic-acid distractors.
    """
    records = []
    for i in range(1, 7):
        c = tiny_ramp_compounds[f"RAMP_C_A00{i}"]
        records.append(_riken_record(
            accession=f"MSBNK-RIKEN-A00{i}-A",
            inchikey=c["inchikey"], name=c["name"],
            peaks=50, ce=20.0, compound_class="flavonoid",
        ))
        records.append(_riken_record(  # this one should be filtered out
            accession=f"MSBNK-RIKEN-A00{i}-B",
            inchikey=c["inchikey"], name=c["name"],
            peaks=10, ce=5.0, compound_class="flavonoid",
        ))
    for i in range(1, 7):
        c = tiny_ramp_compounds[f"RAMP_C_F00{i}"]
        records.append(_riken_record(
            accession=f"MSBNK-RIKEN-F00{i}",
            inchikey=c["inchikey"], name=c["name"],
            peaks=50, ce=20.0, compound_class="flavonoid",
        ))
    for i in range(1, 4):
        c = tiny_ramp_compounds[f"RAMP_C_D00{i}"]
        records.append(_riken_record(
            accession=f"MSBNK-RIKEN-D00{i}",
            inchikey=c["inchikey"], name=c["name"],
            peaks=50, ce=20.0, compound_class="organic_acid",
        ))
    return _write_riken_jsonl(tmp_path / "riken.jsonl", records)


@pytest.fixture
def empty_hmdb(tmp_path) -> Path:
    """Empty HMDB sqlite (just schema) — used when curate_riken doesn't need HMDB."""
    p = tmp_path / "hmdb_empty.sqlite"
    conn = sqlite3.connect(p)
    conn.executescript("""
        CREATE TABLE metabolites (
            hmdb_id TEXT PRIMARY KEY, primary_name TEXT,
            molecular_formula TEXT, exact_mass REAL, smiles TEXT,
            inchikey TEXT, chemical_class TEXT, kegg_id TEXT,
            chebi_id TEXT, pubchem_cid TEXT, chembl_id TEXT,
            synonyms_json TEXT, tissue_locations_json TEXT,
            disease_associations_json TEXT
        );
    """)
    conn.commit()
    conn.close()
    return p


def _hmdb_candidate_record(
    *, hmdb_id: str, kegg_id: str, inchikey: str, name: str = "Test compound",
    smiles: str = "CCO", mass: float = 100.0, formula: str = "C2H6O",
    pathway_domain: str = "central_metabolism",
    npc_pathway: str = "Carbohydrates",
    chemical_class: str | None = None,
) -> dict:
    return {
        "hmdb_id": hmdb_id,
        "kegg_id": kegg_id,
        "inchikey": inchikey,
        "primary_name": name,
        "smiles": smiles,
        "exact_mass": mass,
        "molecular_formula": formula,
        "chemical_class": chemical_class,
        "pubchem_cid": None,
        "pathway_domain": pathway_domain,
        "pathway_count": 5,
        "pathway_names": ["Test pathway"],
        "npclassifier": {
            "pathway": [npc_pathway],
            "superclass": ["Some superclass"],
            "class_": ["Some class"],
            "isglycoside": False,
        },
    }


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


@pytest.fixture
def tiny_hmdb_candidates(tmp_path, tiny_ramp_compounds) -> Path:
    """HMDB candidates JSONL covering every tiny_ramp compound that has a KEGG ID."""
    records = []
    for ramp_id, info in tiny_ramp_compounds.items():
        if not info["kegg"]:
            continue
        records.append(_hmdb_candidate_record(
            hmdb_id=info["hmdb"], kegg_id=info["kegg"], inchikey=info["inchikey"],
            name=info["name"], pathway_domain="central_metabolism",
            npc_pathway="Carbohydrates",
        ))
    return _write_jsonl(tmp_path / "hmdb_candidates.jsonl", records)


# ---------------------------------------------------------------------------
# RIKEN-Plant tests
# ---------------------------------------------------------------------------


def test_curate_riken_filters_by_peaks_min(
    tiny_riken_pool, tiny_ramp_path, empty_hmdb,
):
    """Spectra with peaks<30 OR CE<10 are dropped; compound only kept if ≥1 passes."""
    curated, stats = curate_riken_plant_subset(
        tiny_riken_pool, leakage_excluded_ids_path=None,
        ramp_db_path=tiny_ramp_path, hmdb_db_path=empty_hmdb,
        require_peaks_min=30, require_ce_min=10.0,
        target_size=100, pathway_min_compounds=5,
    )
    # All anthocyanin compounds have one passing + one failing spectrum;
    # they should still be kept and only the passing accession should appear.
    antho = [c for c in curated if c.compound_class == "flavonoid"
             and any("RIKEN-A" in s for s in (c.spectrum_ids or []))]
    assert antho, "expected anthocyanin compounds to survive quality filter"
    for c in antho:
        for sid in c.spectrum_ids or []:
            assert sid.endswith("-A"), f"unexpected sub-quality spectrum kept: {sid}"
    # Distractors (D00*) are alone in PATH_DISTR with K=3 → fail pathway gate
    assert all(c.compound_class != "organic_acid" for c in curated), \
        "distractors should fail the ≥5 pathway-peers gate"


def test_curate_riken_dedups_by_inchikey_first_block(
    tmp_path, tiny_ramp_path, empty_hmdb, tiny_ramp_compounds,
):
    """Two spectra with the same first-block but different stereo blocks dedupe."""
    c = tiny_ramp_compounds["RAMP_C_A001"]
    full = c["inchikey"]
    # Synthesize a different stereo-block variant
    alt = full[:14] + "-XXXXXXXXXX-N"
    records = [
        _riken_record(accession="A1", inchikey=full, name=c["name"]),
        _riken_record(accession="A2", inchikey=alt, name=c["name"]),
        # plus enough peers in PATH_ANTHO to clear the pathway-min-5 gate
    ]
    for i in range(2, 7):
        c2 = tiny_ramp_compounds[f"RAMP_C_A00{i}"]
        records.append(_riken_record(
            accession=f"A{i}", inchikey=c2["inchikey"], name=c2["name"]))
    pool = _write_riken_jsonl(tmp_path / "riken.jsonl", records)
    curated, stats = curate_riken_plant_subset(
        pool, leakage_excluded_ids_path=None,
        ramp_db_path=tiny_ramp_path, hmdb_db_path=empty_hmdb,
        target_size=100, pathway_min_compounds=5,
    )
    first_blocks = [c.inchikey_first_block for c in curated]
    # Same first-block must appear at most once
    assert len(first_blocks) == len(set(first_blocks))


def test_curate_riken_ce_ramp_exempt(tmp_path, tiny_ramp_path, empty_hmdb,
                                       tiny_ramp_compounds):
    """RIKEN spectra with CE=None but normalization_warnings indicating ramp/stepwave
    are NOT dropped by the CE filter."""
    records = []
    for i in range(1, 6):  # 5 anthocyanin compounds → enough for pathway gate
        c = tiny_ramp_compounds[f"RAMP_C_A00{i}"]
        records.append(_riken_record(
            accession=f"RAMP-{i}",
            inchikey=c["inchikey"], name=c["name"],
            peaks=50, ce=None,  # CE missing
            ce_warnings=["collision_energy: ramp/stepwave — cannot single-value: 'Ramp 5-60 V'"],
        ))
    pool = _write_jsonl(tmp_path / "riken_ramp.jsonl", records)
    curated, stats = curate_riken_plant_subset(
        pool, leakage_excluded_ids_path=None,
        ramp_db_path=tiny_ramp_path, hmdb_db_path=empty_hmdb,
        target_size=20, pathway_min_compounds=5,
        allow_ce_none_if_ramp=True, require_ce_min=10.0,
    )
    # All 5 should survive thanks to the ramp exemption
    assert len(curated) >= 5


def test_curate_riken_ce_ramp_exempt_off(tmp_path, tiny_ramp_path, empty_hmdb,
                                          tiny_ramp_compounds):
    """With allow_ce_none_if_ramp=False, ramp CE=None spectra are dropped."""
    records = []
    for i in range(1, 6):
        c = tiny_ramp_compounds[f"RAMP_C_A00{i}"]
        records.append(_riken_record(
            accession=f"RAMP-{i}",
            inchikey=c["inchikey"], name=c["name"],
            peaks=50, ce=None,
            ce_warnings=["collision_energy: ramp/stepwave — cannot single-value: 'Ramp 5-60 V'"],
        ))
    pool = _write_jsonl(tmp_path / "riken_ramp.jsonl", records)
    curated, stats = curate_riken_plant_subset(
        pool, leakage_excluded_ids_path=None,
        ramp_db_path=tiny_ramp_path, hmdb_db_path=empty_hmdb,
        target_size=20, pathway_min_compounds=5,
        allow_ce_none_if_ramp=False, require_ce_min=10.0,
    )
    # All dropped — no qualifying spectrum
    assert len(curated) == 0
    assert stats.drop_reasons.get("no_qualifying_spectrum", 0) == 5


def test_curate_riken_npc_fields_populated(tiny_riken_pool, tiny_ramp_path, empty_hmdb):
    """NPC pathway/superclass/class flow into CuratedCompound."""
    curated, _ = curate_riken_plant_subset(
        tiny_riken_pool, leakage_excluded_ids_path=None,
        ramp_db_path=tiny_ramp_path, hmdb_db_path=empty_hmdb,
        target_size=20, pathway_min_compounds=5,
    )
    assert curated
    assert any(c.npc_pathway == "Shikimates and Phenylpropanoids" for c in curated)
    assert any(c.classyfire_source == "npclassifier" for c in curated)


def test_curate_riken_leakage_filter_does_not_drop(
    tiny_riken_pool, tiny_ramp_path, empty_hmdb, tmp_path,
):
    """Q2-b: leakage filter is informational, no compounds dropped."""
    leak_path = tmp_path / "leak.json"
    leak_path.write_text(json.dumps({
        "excluded_ids": ["MSBNK-RIKEN-A001-A", "MSBNK-RIKEN-A002-A"]
    }))
    curated_with, _ = curate_riken_plant_subset(
        tiny_riken_pool, leakage_excluded_ids_path=leak_path,
        ramp_db_path=tiny_ramp_path, hmdb_db_path=empty_hmdb,
        target_size=100, pathway_min_compounds=5,
    )
    curated_without, _ = curate_riken_plant_subset(
        tiny_riken_pool, leakage_excluded_ids_path=None,
        ramp_db_path=tiny_ramp_path, hmdb_db_path=empty_hmdb,
        target_size=100, pathway_min_compounds=5,
    )
    # Same compound counts — leakage filter doesn't drop
    assert len(curated_with) == len(curated_without)


# ---------------------------------------------------------------------------
# HMDB-Mammalian tests
# ---------------------------------------------------------------------------


def test_curate_hmdb_drops_unparseable_smiles(tmp_path, tiny_ramp_path):
    """Rows with garbage SMILES are dropped + counted in drop_reasons."""
    rows = [_hmdb_candidate_record(
        hmdb_id="HMDB-bad", kegg_id="C00001",
        inchikey="AAAAAAAAAAAAAA-AAAAAAAAAA-N",
        smiles="this-is-not-smiles!@#",
    )]
    p = _write_jsonl(tmp_path / "hmdb_cands.jsonl", rows)
    curated, stats = curate_hmdb_mammalian_subset(
        candidates_jsonl_path=p, ramp_db_path=tiny_ramp_path,
        require_ramp_pathway=False, target_size=10,
    )
    assert stats.drop_reasons.get("smiles_unparseable", 0) >= 1


def test_curate_hmdb_dedupes_by_first_block(tmp_path, tiny_ramp_path):
    """Two records with the same first-block dedupe."""
    rows = [
        _hmdb_candidate_record(hmdb_id="A", kegg_id="C00001",
                                inchikey="AAAAAAAAAAAAAA-XXXXXXXXXX-N"),
        _hmdb_candidate_record(hmdb_id="B", kegg_id="C00002",
                                inchikey="AAAAAAAAAAAAAA-YYYYYYYYYY-N"),
    ]
    p = _write_jsonl(tmp_path / "hmdb_cands.jsonl", rows)
    curated, stats = curate_hmdb_mammalian_subset(
        candidates_jsonl_path=p, ramp_db_path=tiny_ramp_path,
        require_ramp_pathway=False, target_size=10,
    )
    assert stats.drop_reasons.get("dedup_first_block", 0) == 1


def test_curate_hmdb_pathway_domain_passthrough(tiny_hmdb_candidates, tiny_ramp_path):
    """The bucket field comes straight from the candidate record's pathway_domain."""
    curated, stats = curate_hmdb_mammalian_subset(
        candidates_jsonl_path=tiny_hmdb_candidates,
        ramp_db_path=tiny_ramp_path,
        target_size=20, pathway_min_compounds=3,
    )
    # All seeded records used pathway_domain="central_metabolism"
    assert curated  # something passed
    assert all(c.pathway_bucket == "central_metabolism" for c in curated)


def test_curate_hmdb_npc_fields_populated(tiny_hmdb_candidates, tiny_ramp_path):
    """CuratedCompound carries NPC pathway/superclass/class from the input record."""
    curated, _ = curate_hmdb_mammalian_subset(
        candidates_jsonl_path=tiny_hmdb_candidates,
        ramp_db_path=tiny_ramp_path,
        target_size=20, pathway_min_compounds=3,
    )
    assert curated
    c = curated[0]
    assert c.npc_pathway == "Carbohydrates"
    assert c.npc_superclass == "Some superclass"
    assert c.classyfire_source == "npclassifier"


# ---------------------------------------------------------------------------
# Bucket classifier helper
# ---------------------------------------------------------------------------


def test_classify_pathway_bucket():
    assert _classify_pathway_bucket("Citric acid cycle (TCA cycle)") == "central_metabolism"
    assert _classify_pathway_bucket("Fatty acid β-oxidation") == "lipid_metabolism"
    assert _classify_pathway_bucket("Purine metabolism") == "nucleotide_metabolism"
    assert _classify_pathway_bucket("Lysine biosynthesis") == "amino_acid_metabolism"
    assert _classify_pathway_bucket("Anthocyanin biosynthesis") == "other_metabolism"
    assert _classify_pathway_bucket("") == "other_metabolism"
    assert _classify_pathway_bucket(None) == "other_metabolism"


# ---------------------------------------------------------------------------
# Save / audit
# ---------------------------------------------------------------------------


def test_save_curated_subsets_writes_audit(tmp_path, tiny_riken_pool,
                                            tiny_ramp_path, empty_hmdb):
    riken, riken_stats = curate_riken_plant_subset(
        tiny_riken_pool, None,
        ramp_db_path=tiny_ramp_path, hmdb_db_path=empty_hmdb,
        target_size=20, pathway_min_compounds=5,
    )
    paths = save_curated_subsets(
        riken, [], output_dir=tmp_path / "out",
        riken_stats=riken_stats, hmdb_stats=CurationStats(),
    )
    assert paths["riken"].is_file()
    assert paths["audit"].is_file()
    audit_text = paths["audit"].read_text(encoding="utf-8")
    assert "RIKEN-Plant" in audit_text
    assert "ClassyFire source" in audit_text
    # JSONL is well-formed
    for line in paths["riken"].read_text().splitlines():
        json.loads(line)
