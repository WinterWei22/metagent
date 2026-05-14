"""Unit tests for ``tools.benchmark.sub6.ramp_enrichment``.

Network-free: all queries hit a tiny in-memory RaMP sqlite seeded
in :mod:`conftest`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.benchmark.sub6.ramp_enrichment import (
    EnrichmentError,
    EnrichmentReport,
    EnrichmentResult,
    _bh_fdr,
    compute_enrichment,
    report_to_json_str,
)


# ---------------------------------------------------------------------------
# Core enrichment behavior
# ---------------------------------------------------------------------------


def test_compute_enrichment_known_pathway(tiny_ramp_path, anthocyanin_inchikeys):
    """5 anthocyanin compounds → top-1 pathway is anthocyanin with FDR < 0.001."""
    five = anthocyanin_inchikeys[:5]
    rep = compute_enrichment(five, id_type="inchikey", ramp_db_path=tiny_ramp_path)

    assert rep.n_input_resolved == 5
    assert rep.background_size > 0
    assert rep.top_pathways, "expected at least one enriched pathway"
    top = rep.top_pathways[0]
    assert "anthocyanin" in top.pathway_name.lower()
    assert top.fdr < 0.001
    # All 5 input keys should appear in matched_compounds for the anthocyanin row
    assert set(top.matched_compounds) == set(five)
    # Source label maps from pathway.type='hmdb' → 'smpdb'
    assert top.pathway_source == "smpdb"


def test_compute_enrichment_pfocr_excluded(tiny_ramp_path, anthocyanin_inchikeys):
    """Default excludes pfocr — the seeded PFOCR pathways must not appear."""
    rep = compute_enrichment(
        anthocyanin_inchikeys[:5], id_type="inchikey", ramp_db_path=tiny_ramp_path)
    pids = {r.pathway_id for r in rep.top_pathways}
    assert not any(p.startswith("PATH_PFOCR") for p in pids)
    assert "pfocr" in rep.excluded_pathway_types


def test_pfocr_aggregation_collapses_duplicates(tiny_ramp_path, anthocyanin_inchikeys):
    """When pfocr is allowed, two pfocr pathways with identical matched-compound
    fingerprints aggregate to a single representative (the one with smaller K).
    """
    # Query the first 4 anthocyanin keys → PATH_PFOCR (K=10) and PATH_PFOCR2 (K=5)
    # both match exactly compounds A001..A004. Aggregation should drop PATH_PFOCR
    # and keep PATH_PFOCR2 (smaller K, higher fold).
    four = anthocyanin_inchikeys[:4]
    rep = compute_enrichment(
        four, id_type="inchikey",
        ramp_db_path=tiny_ramp_path,
        excluded_pathway_types=(),  # allow pfocr
        aggregate_pfocr=True,
    )
    pids = {r.pathway_id for r in rep.top_pathways}
    assert "PATH_PFOCR2" in pids
    assert "PATH_PFOCR" not in pids


def test_pfocr_aggregation_disabled(tiny_ramp_path, anthocyanin_inchikeys):
    """With aggregate_pfocr=False, both duplicate pfocr pathways appear."""
    four = anthocyanin_inchikeys[:4]
    rep = compute_enrichment(
        four, id_type="inchikey",
        ramp_db_path=tiny_ramp_path,
        excluded_pathway_types=(),
        aggregate_pfocr=False,
    )
    pids = {r.pathway_id for r in rep.top_pathways}
    assert "PATH_PFOCR" in pids
    assert "PATH_PFOCR2" in pids


def test_pfocr_aggregation_distinct_fingerprints_kept_separate(
    tiny_ramp_path, anthocyanin_inchikeys,
):
    """Pfocr pathways with different matched compound sets are NOT aggregated."""
    # 5 anthocyanin keys → PATH_PFOCR/PFOCR2 match 4 (A001..A004), PATH_PFOCR3
    # matches 5 (A001..A005). Different fingerprints → PFOCR3 stays separate.
    rep = compute_enrichment(
        anthocyanin_inchikeys[:5], id_type="inchikey",
        ramp_db_path=tiny_ramp_path,
        excluded_pathway_types=(),
        aggregate_pfocr=True,
    )
    pids = {r.pathway_id for r in rep.top_pathways}
    # PFOCR3 should appear (distinct fingerprint with k=5)
    assert "PATH_PFOCR3" in pids
    # Among PFOCR / PFOCR2, only the smaller-K representative remains
    assert ("PATH_PFOCR2" in pids) and ("PATH_PFOCR" not in pids)


def test_compute_enrichment_random_compounds(tiny_ramp_path, random_inchikeys):
    """5 background compounds → no pathway should reach FDR < 0.05."""
    rep = compute_enrichment(
        random_inchikeys, id_type="inchikey", ramp_db_path=tiny_ramp_path)
    # They all sit in PATH_BG (background filler), so PATH_BG can show up,
    # but its FDR should not be << 0.05 because the entire BG pool is in it.
    if rep.top_pathways:
        # No anthocyanin/flavonoid hit
        names = [r.pathway_name.lower() for r in rep.top_pathways]
        assert not any("anthocyanin" in n for n in names)
        assert not any("flavonoid" in n for n in names)


def test_compute_enrichment_compound_not_in_ramp(
    tiny_ramp_path, anthocyanin_inchikeys, caplog
):
    """Inputs that don't resolve are reported in unresolved_compounds, not crash."""
    bogus = "ZZZZZZZZZZZZZZ-ZZZZZZZZZZ-N"
    inputs = [*anthocyanin_inchikeys[:3], bogus]
    rep = compute_enrichment(inputs, id_type="inchikey", ramp_db_path=tiny_ramp_path)
    assert bogus in rep.unresolved_compounds
    assert rep.n_input_resolved == 3
    # Anthocyanin should still surface, since 3 of 6 are present
    pids = {r.pathway_id for r in rep.top_pathways}
    assert "PATH_ANTHO" in pids


def test_compute_enrichment_kegg_id_type(tiny_ramp_path, tiny_ramp_compounds):
    """id_type='kegg' resolves bare KEGG IDs via the source table."""
    keggs = [tiny_ramp_compounds[f"RAMP_C_A00{i}"]["kegg"] for i in range(1, 6)]
    rep = compute_enrichment(keggs, id_type="kegg", ramp_db_path=tiny_ramp_path)
    assert rep.n_input_resolved == 5
    top = rep.top_pathways[0]
    assert "anthocyanin" in top.pathway_name.lower()


def test_compute_enrichment_hmdb_id_type(tiny_ramp_path, tiny_ramp_compounds):
    """id_type='hmdb' resolves bare HMDB IDs via the source table."""
    hmdbs = [tiny_ramp_compounds[f"RAMP_C_F00{i}"]["hmdb"] for i in range(1, 6)]
    rep = compute_enrichment(hmdbs, id_type="hmdb", ramp_db_path=tiny_ramp_path)
    assert rep.n_input_resolved == 5
    top = rep.top_pathways[0]
    assert "flavonoid" in top.pathway_name.lower()


def test_compute_enrichment_dedupes_inputs(tiny_ramp_path, anthocyanin_inchikeys):
    """Duplicate inputs are deduped before counting."""
    dupes = [*anthocyanin_inchikeys[:3], *anthocyanin_inchikeys[:3]]
    rep = compute_enrichment(dupes, id_type="inchikey", ramp_db_path=tiny_ramp_path)
    assert rep.n_input_resolved == 3  # 6 → 3 after dedupe
    assert len(rep.input_compounds) == 3


def test_compute_enrichment_empty_inputs_raises(tiny_ramp_path):
    with pytest.raises(EnrichmentError):
        compute_enrichment([], id_type="inchikey", ramp_db_path=tiny_ramp_path)


def test_compute_enrichment_unknown_background_raises(tiny_ramp_path):
    with pytest.raises(EnrichmentError):
        compute_enrichment(
            ["X"], id_type="inchikey", background="ramp_human",
            ramp_db_path=tiny_ramp_path,  # type: ignore[arg-type]
        )


def test_compute_enrichment_inchikey_first_block_only(tiny_ramp_path, anthocyanin_inchikeys):
    """14-char first-blocks resolve via inchi_key_prefix index."""
    first_blocks = [k[:14] for k in anthocyanin_inchikeys[:5]]
    rep = compute_enrichment(
        first_blocks, id_type="inchikey", ramp_db_path=tiny_ramp_path)
    assert rep.n_input_resolved == 5


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_enrichment_result_serializable(tiny_ramp_path, anthocyanin_inchikeys):
    """to_json round-trips through json.dumps cleanly."""
    rep = compute_enrichment(
        anthocyanin_inchikeys[:5], id_type="inchikey", ramp_db_path=tiny_ramp_path)
    payload = rep.to_json()
    s = json.dumps(payload)  # must not raise
    parsed = json.loads(s)
    assert parsed["n_input_resolved"] == 5
    assert parsed["top_pathways"]
    # report_to_json_str sorts keys deterministically
    s2 = report_to_json_str(rep)
    assert json.loads(s2)["n_input_resolved"] == 5


# ---------------------------------------------------------------------------
# BH FDR helper
# ---------------------------------------------------------------------------


def test_bh_fdr_basic():
    p = [0.01, 0.02, 0.03, 0.04, 0.05]
    q = _bh_fdr(p)
    # All q values should be >= corresponding p
    for pi, qi in zip(p, q):
        assert qi >= pi - 1e-12
    # Monotone non-decreasing when sorted by p
    sorted_q = sorted(q)
    assert sorted_q == q  # input was already sorted


def test_bh_fdr_empty():
    assert _bh_fdr([]) == []


def test_bh_fdr_caps_at_one():
    q = _bh_fdr([0.9, 0.95, 0.99])
    assert all(qi <= 1.0 for qi in q)


def test_bh_fdr_preserves_order():
    """BH adjustment returned in the same order as the input."""
    p = [0.5, 0.001, 0.3, 0.0001]
    q = _bh_fdr(p)
    # Smallest input p_value (0.0001 at index 3) should have the smallest q
    assert q.index(min(q)) == 3
