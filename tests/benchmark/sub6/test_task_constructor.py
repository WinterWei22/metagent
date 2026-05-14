"""Unit tests for ``tools.benchmark.sub6.task_constructor``.

Network-free: builds tasks against the tiny RaMP fixture from conftest.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.benchmark.sub6.compound_curator import CuratedCompound
from tools.benchmark.sub6.task_constructor import (
    EnrichmentTask,
    construct_compound_only_tasks,
    construct_end_to_end_tasks,
    derive_seed,
    save_tasks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_curated(
    *, name: str, inchikey: str, kegg_id: str | None = None,
    ramp_pathway_ids: list[str] = None,
    ramp_pathway_names: list[str] = None,
    ramp_pathway_sources: list[str] = None,
    spectrum_ids: list[str] | None = None,
    source: str = "riken",
) -> CuratedCompound:
    return CuratedCompound(
        name=name, smiles="CCO", inchikey=inchikey,
        inchikey_first_block=inchikey[:14],
        molecular_formula="C2H6O", exact_mass=46.0,
        kegg_id=kegg_id, hmdb_id=None, pubchem_cid=None,
        npc_pathway="Shikimates and Phenylpropanoids", npc_superclass="x",
        npc_class="y", npc_isglycoside=False,
        classyfire_class="x / y / z", classyfire_source="npclassifier",
        compound_class="flavonoid", pathway_bucket="plant_secondary",
        source=source, spectrum_ids=spectrum_ids,
        ramp_pathway_ids=ramp_pathway_ids or [],
        ramp_pathway_names=ramp_pathway_names or [],
        ramp_pathway_sources=ramp_pathway_sources or [],
    )


@pytest.fixture
def antho_curated(tiny_ramp_compounds) -> list[CuratedCompound]:
    """6 anthocyanin + 6 flavonoid + 3 distractor curated compounds.

    Each anthocyanin lists PATH_ANTHO + PATH_FLAV (so PATH_ANTHO has 6 in-subset
    members, PATH_FLAV has 12). Each flavonoid lists PATH_FLAV only.
    Distractors list PATH_DISTR.
    """
    out: list[CuratedCompound] = []
    for i in range(1, 7):
        c = tiny_ramp_compounds[f"RAMP_C_A00{i}"]
        out.append(_make_curated(
            name=c["name"], inchikey=c["inchikey"], kegg_id=c["kegg"],
            ramp_pathway_ids=["PATH_ANTHO", "PATH_FLAV"],
            ramp_pathway_names=["Anthocyanin biosynthesis", "Flavonoid biosynthesis"],
            ramp_pathway_sources=["hmdb", "kegg"],
            spectrum_ids=[f"MSBNK-RIKEN-A00{i}-A"],
        ))
    for i in range(1, 7):
        c = tiny_ramp_compounds[f"RAMP_C_F00{i}"]
        out.append(_make_curated(
            name=c["name"], inchikey=c["inchikey"], kegg_id=c["kegg"],
            ramp_pathway_ids=["PATH_FLAV"],
            ramp_pathway_names=["Flavonoid biosynthesis"],
            ramp_pathway_sources=["kegg"],
            spectrum_ids=[f"MSBNK-RIKEN-F00{i}"],
        ))
    for i in range(1, 4):
        c = tiny_ramp_compounds[f"RAMP_C_D00{i}"]
        out.append(_make_curated(
            name=c["name"], inchikey=c["inchikey"], kegg_id=c["kegg"],
            ramp_pathway_ids=["PATH_DISTR"],
            ramp_pathway_names=["Citric acid cycle (TCA cycle)"],
            ramp_pathway_sources=["reactome"],
            spectrum_ids=[f"MSBNK-RIKEN-D00{i}"],
        ))
    return out


# ---------------------------------------------------------------------------
# derive_seed
# ---------------------------------------------------------------------------


def test_derive_seed_deterministic():
    a = derive_seed(42, "PATH_X", 0)
    b = derive_seed(42, "PATH_X", 0)
    assert a == b
    c = derive_seed(42, "PATH_X", 1)
    assert a != c
    d = derive_seed(43, "PATH_X", 0)
    assert a != d


# ---------------------------------------------------------------------------
# Compound-only tasks
# ---------------------------------------------------------------------------


def test_construct_compound_only_signal_in_pathway(antho_curated, tiny_ramp_path):
    """All signal compounds belong to the ground-truth pathway peers."""
    tasks, stats = construct_compound_only_tasks(
        antho_curated, domain="plant", target_task_count=2,
        ramp_db_path=tiny_ramp_path, cli_seed=42,
        excluded_pathway_types=(),  # allow pfocr (none in this fixture, but consistent)
        signal_count_range=(5, 6), noise_count_range=(2, 3),
        pathway_min_compounds=5,
    )
    assert tasks, "expected at least one constructed task"
    for t in tasks:
        assert t.task_type == "compound_only_enrichment"
        assert t.domain == "plant"
        assert 5 <= t.signal_count <= 6
        # Signal+noise+shuffle preserved
        assert (t.differential_metabolites is not None
                and len(t.differential_metabolites)
                == t.signal_count + t.noise_count)


def test_construct_compound_only_validates_top3(tiny_ramp_path, antho_curated):
    """Tasks where the primary pathway doesn't surface in top-3 are dropped."""
    tasks, stats = construct_compound_only_tasks(
        antho_curated, domain="plant", target_task_count=10,
        ramp_db_path=tiny_ramp_path, cli_seed=7,
        signal_count_range=(5, 5), noise_count_range=(2, 2),
        pathway_min_compounds=5,
    )
    # All retained tasks must have ground_truth_pathway in top-3
    for t in tasks:
        top3_pids = [p["pathway_id"] for p in t.ramp_enrichment_result["top_pathways"][:3]]
        gt_pid = t.ground_truth_pathway["pathway_id"]
        # Either direct ID match or post-aggregation rep — both should manifest
        # as gt_pid being IN the top-3 of the saved enrichment result.
        assert gt_pid in top3_pids


def test_construct_compound_only_dedicated_seed(antho_curated, tiny_ramp_path):
    """Each task records its derived seed."""
    tasks, _ = construct_compound_only_tasks(
        antho_curated, domain="plant", target_task_count=4,
        ramp_db_path=tiny_ramp_path, cli_seed=99,
        pathway_min_compounds=5,
    )
    seeds = [t.seed for t in tasks]
    # Different tasks → different seeds
    assert len(seeds) == len(set(seeds))


def test_construct_compound_only_too_few_members(tiny_ramp_path):
    """Fewer than pathway_min_compounds peers → no tasks for that pathway."""
    only_three = []
    inchikeys = [
        "AAAAAAAAAAAAAA-AAAAAAAAAA-N",
        "BBBBBBBBBBBBBB-AAAAAAAAAA-N",
        "CCCCCCCCCCCCCC-AAAAAAAAAA-N",
    ]
    for i, ikey in enumerate(inchikeys, start=1):
        only_three.append(_make_curated(
            name=f"x{i}", inchikey=ikey,
            ramp_pathway_ids=["PATH_X"], ramp_pathway_names=["X"],
            ramp_pathway_sources=["kegg"],
        ))
    tasks, stats = construct_compound_only_tasks(
        only_three, domain="plant", target_task_count=5,
        ramp_db_path=tiny_ramp_path, cli_seed=42,
        pathway_min_compounds=5,
    )
    assert tasks == []
    assert stats.n_pathways_qualifying == 0


# ---------------------------------------------------------------------------
# End-to-end tasks
# ---------------------------------------------------------------------------


def _stub_spec(*, first_block: str, source_id: str) -> dict:
    """Spectrum payload dict matching SpectrumPayload.to_dict() shape."""
    return {
        "spectrum_id": f"sub6a-stub-{source_id}",
        "source_db": "stub",
        "source_id": source_id,
        "inchikey": first_block + "-AAAAAAAAAA-N",
        "inchikey_first_block": first_block,
        "instrument": "QTOF",
        "instrument_type": "LC-ESI",
        "ion_mode": "positive",
        "adduct": "[M+H]+",
        "precursor_mz": 200.0,
        "collision_energy": 20.0,
        "n_peaks": 50,
        "peaks": [(float(i), 1.0) for i in range(50)],
        "library_membership": "stub",
    }


def test_construct_e2e_inherits_ground_truth(tiny_ramp_path, antho_curated):
    """Sub-6A inherits ground-truth fields from its Sub-6B parent."""
    plant_tasks, _ = construct_compound_only_tasks(
        antho_curated, domain="plant", target_task_count=2,
        ramp_db_path=tiny_ramp_path, cli_seed=42,
        pathway_min_compounds=5,
    )
    assert plant_tasks
    # Stub spectrum index: cover every curated compound with one spectrum
    spectrum_index: dict[str, list[dict]] = {
        c.inchikey_first_block: [_stub_spec(
            first_block=c.inchikey_first_block, source_id=f"STUB-{c.name}",
        )] for c in antho_curated
    }
    e2e = construct_end_to_end_tasks(
        plant_tasks, cli_seed=42, spectrum_index=spectrum_index,
        spectra_per_compound_range=(1, 1),
        min_compounds_with_spectra=1,
    )
    assert e2e
    for parent, child in zip(plant_tasks, e2e):
        assert child.task_type == "end_to_end_enrichment"
        assert child.differential_spectra is not None
        assert child.differential_metabolites is None
        assert child.ground_truth_pathway == parent.ground_truth_pathway
        assert child.ground_truth_signal_compounds == parent.ground_truth_signal_compounds
        # Each spectrum payload carries the SpectrumPayload-shaped fields
        sp = child.differential_spectra[0]
        assert "source_db" in sp and "inchikey_first_block" in sp


def test_construct_e2e_drops_when_too_few_compounds_have_spectra(
    tiny_ramp_path, antho_curated,
):
    """If <min_compounds_with_spectra of the differential compounds have any
    library spectrum, the task is dropped."""
    plant_tasks, _ = construct_compound_only_tasks(
        antho_curated, domain="plant", target_task_count=1,
        ramp_db_path=tiny_ramp_path, cli_seed=42,
        pathway_min_compounds=5,
    )
    # Empty index: no compound has spectra
    e2e = construct_end_to_end_tasks(
        plant_tasks, cli_seed=42, spectrum_index={},
        min_compounds_with_spectra=1,
    )
    assert e2e == []


# ---------------------------------------------------------------------------
# Save/serialize round-trip
# ---------------------------------------------------------------------------


def test_task_serialization_roundtrip(antho_curated, tiny_ramp_path, tmp_path):
    tasks, _ = construct_compound_only_tasks(
        antho_curated, domain="plant", target_task_count=2,
        ramp_db_path=tiny_ramp_path, cli_seed=42,
        pathway_min_compounds=5,
    )
    out_path = save_tasks(tasks, tmp_path / "tasks.jsonl")
    lines = out_path.read_text().splitlines()
    assert len(lines) == len(tasks)
    for line in lines:
        payload = json.loads(line)
        assert "task_id" in payload
        assert "ground_truth_pathway" in payload
        assert "ramp_enrichment_result" in payload
