"""W6 D1.3 mummichog wrapper upgrade — 4 unit tests.

Covers: peak synthesis port, MUMM namespace, metabolites_hit via id_resolve,
and W3-hotfix vacuous-pathway validator non-regression.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs
from concord.schema.enrichment import (
    EnrichmentResult, PATHWAY_NAMESPACES, PathwayHit,
)
from concord.schema.peak import PeakRecord
from concord.wrappers.mummichog_wrapper import (
    synthesize_peaks, _ADDUCTS_POS, _ADDUCTS_NEG,
)
from concord.normalize.mummichog_norm import (
    normalize_mummichog_output, _namespace_pathway_id, _slug,
)


@pytest.fixture(scope="module")
def chebi():
    return ChebiLookup()


@pytest.fixture(scope="module")
def toy_refs(chebi):
    """Mainstream compounds with known monoisotopic masses."""
    hmdb_ids = ["HMDB0000122", "HMDB0000094", "HMDB0000538",
                "HMDB0001935", "HMDB0000151"]
    refs, _ = resolve_ids_to_compound_refs(hmdb_ids, "HMDB", chebi)
    return refs


def test_synthesize_peaks_positive_adducts_and_background(toy_refs):
    """Each input compound emits one PeakRecord per positive adduct
    (M+H, M+Na), plus ``n_background`` non-significant noise features.
    """
    n_bg = 50
    peaks = synthesize_peaks(toy_refs, n_background=n_bg, mode="positive", seed=42)
    # n compounds with monoisotopic_mass × 2 adducts + n_background
    diff_peaks = [p for p in peaks if p.feature_id.startswith("diff_")]
    bg_peaks = [p for p in peaks if p.feature_id.startswith("bg_")]
    assert len(bg_peaks) == n_bg, f"expected {n_bg} bg, got {len(bg_peaks)}"
    assert len(diff_peaks) > 0, "no significant peaks built — ChebiLookup mass missing?"
    # Each diff peak must encode one of the M+H / M+Na adducts in its feature_id
    for p in diff_peaks:
        adduct = p.feature_id.split("_")[-1]
        assert adduct in _ADDUCTS_POS, f"unexpected adduct tag {adduct!r}"
        assert p.p_value < 0.01, "diff peak must be significant"
    # Background peaks have non-significant p
    for p in bg_peaks:
        assert p.p_value >= 0.1, "bg peak should be non-significant"


def test_synthesize_peaks_negative_mode_uses_negative_adducts(toy_refs):
    """Switching to negative mode emits M-H + M+Cl adducts only."""
    peaks = synthesize_peaks(toy_refs, n_background=20, mode="negative", seed=42)
    diff_peaks = [p for p in peaks if p.feature_id.startswith("diff_")]
    for p in diff_peaks:
        adduct = p.feature_id.split("_")[-1]
        assert adduct in _ADDUCTS_NEG, f"unexpected adduct {adduct!r} in negative mode"


def test_pathway_id_mumm_namespace():
    """human_mfn pathway name → MUMM:<slug>; namespace is whitelisted."""
    raw = "Vitamin D3 (cholecalciferol) metabolism"
    ns_id = _namespace_pathway_id(raw)
    assert ns_id == f"MUMM:{_slug(raw)}"
    assert ns_id.startswith("MUMM:vitamin_d3")
    ns = ns_id.split(":", 1)[0]
    assert ns in PATHWAY_NAMESPACES, f"{ns!r} not whitelisted"


def test_normalize_no_vacuous_when_hits_present(chebi):
    """W3 hotfix non-regression: if a pathway has hits_kegg_ids, the
    normalizer must populate ``metabolites_hit`` (via id_resolve) so that
    the v0.3 vacuous-pathways validator does not trip.
    """
    fake_result = {
        "pathways": [
            {"pathway_id": "Glycolysis / Gluconeogenesis",
             "pathway_name": "Glycolysis / Gluconeogenesis",
             "p_value": 0.001,
             "overlap_size": 3, "pathway_size": 20,
             "hits_kegg_ids": ["C00031", "C00022", "C00094"]},
        ],
        "stats": {"n_features_in": 250, "n_significant": 5,
                  "n_pathways_tested": 119, "wall_time_sec": 4.2},
        "errors": [], "wall_time_sec": 4.2,
        "tool_version": "mummichog-2.7.0",
        "parameters": {"mode": "positive", "ref_db": "mfn"},
    }
    er = normalize_mummichog_output(fake_result, top_n=10, chebi_lookup=chebi)
    assert isinstance(er, EnrichmentResult)
    assert len(er.pathways) == 1
    h = er.pathways[0]
    assert h.pathway_id.startswith("MUMM:")
    assert len(h.metabolites_hit) >= 2, "id_resolve should map ≥ 2 KEGG cpds → ChEBI"
    n_chebi = sum(1 for r in h.metabolites_hit if r.primary_id.startswith("CHEBI:"))
    assert n_chebi == len(h.metabolites_hit), "all hits should be CHEBI primary"
    assert er.schema_version == "concordmet_v0.3.1"
