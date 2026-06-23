"""Tests for concord/lookup/structure_resolver.py (TDD RED → GREEN).

Fixture data verified against real databases (2026-06-23):
  - KEGG C00031: D-glucose, resolved via ChEBI xref
  - Recon2.2 txa2: Thromboxane A2, resolved via bigg_mnx -> mnx_structure
  - Recon2.2 cysam: cysteamine, resolved via bigg_mnx -> mnx_structure
  - Human1 MAM03595: Beta glucan-glycocholate complex -> non_single_structure excluded
  - Human1 MAM01111: pseudo-node no xref -> non_single_structure excluded
  - Human1 MAM01610: Core5 g -> structure_unavailable, not excluded
  - ("ZZZ999","KEGG"): non-existent -> resolved=False
"""
from __future__ import annotations

import pytest

from concord.lookup.structure_resolver import StructureResolution, StructureResolver

# ──────────────────────────────────────────────────────────────────────────────
# Shared resolver instance (loaded once for the module)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def resolver() -> StructureResolver:
    return StructureResolver()


# ──────────────────────────────────────────────────────────────────────────────
# StructureResolution dataclass sanity
# ──────────────────────────────────────────────────────────────────────────────

class TestStructureResolutionDataclass:
    def test_fields_present(self):
        r = StructureResolution(
            id="C00031",
            id_type="KEGG",
            inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N",
            smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
            resolved=True,
            source="chebi",
            excluded=False,
            exclusion_class=None,
        )
        assert r.id == "C00031"
        assert r.resolved is True
        assert r.excluded is False

    def test_frozen(self):
        r = StructureResolution(
            id="x", id_type="KEGG", inchikey=None, smiles=None,
            resolved=False, source=None, excluded=False, exclusion_class=None,
        )
        with pytest.raises(Exception):
            r.resolved = True  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────────
# Fixture 1 — KEGG C00031 (D-glucose, resolved via ChEBI, no stratum)
# ──────────────────────────────────────────────────────────────────────────────

class TestKeggDGlucose:
    def test_resolved(self, resolver):
        r = resolver.resolve("C00031", "KEGG")
        assert r.resolved is True

    def test_smiles_nonempty(self, resolver):
        r = resolver.resolve("C00031", "KEGG")
        assert r.smiles and len(r.smiles) > 5

    def test_inchikey_nonempty(self, resolver):
        r = resolver.resolve("C00031", "KEGG")
        assert r.inchikey and len(r.inchikey) > 10

    def test_not_excluded(self, resolver):
        r = resolver.resolve("C00031", "KEGG")
        assert r.excluded is False
        assert r.exclusion_class is None

    def test_source_chebi(self, resolver):
        r = resolver.resolve("C00031", "KEGG")
        assert r.source == "chebi"

    def test_id_and_id_type_preserved(self, resolver):
        r = resolver.resolve("C00031", "KEGG")
        assert r.id == "C00031"
        assert r.id_type == "KEGG"


# ──────────────────────────────────────────────────────────────────────────────
# Fixture 2 — Recon2.2 txa2 (Thromboxane A2, via bigg_mnx -> MNXM1445)
# ──────────────────────────────────────────────────────────────────────────────

class TestRecon22Txa2:
    def test_resolved(self, resolver):
        r = resolver.resolve("txa2", "Recon2.2", stratum="recon22")
        assert r.resolved is True

    def test_source_is_chebi_or_mnx_struct(self, resolver):
        # txa2 has a full GEM xref set (KEGG C02198, CHEBI:15627 etc.);
        # ChEBI carries the structure, so source="chebi" is the expected fast
        # path. mnx_struct is also valid if ChEBI misses it.
        r = resolver.resolve("txa2", "Recon2.2", stratum="recon22")
        assert r.source in ("chebi", "mnx_struct")

    def test_smiles_contains_carboxyl_group(self, resolver):
        r = resolver.resolve("txa2", "Recon2.2", stratum="recon22")
        # Both ChEBI (neutral C(=O)O) and MNX (anionic C(=O)[O-]) forms
        assert r.smiles and ("C(=O)O" in r.smiles or "C(=O)[O-]" in r.smiles)

    def test_not_excluded(self, resolver):
        r = resolver.resolve("txa2", "Recon2.2", stratum="recon22")
        assert r.excluded is False


# ──────────────────────────────────────────────────────────────────────────────
# Fixture 3 — Recon2.2 cysam (cysteamine, via bigg_mnx)
# ──────────────────────────────────────────────────────────────────────────────

class TestRecon22Cysam:
    def test_resolved(self, resolver):
        r = resolver.resolve("cysam", "Recon2.2", stratum="recon22")
        assert r.resolved is True

    def test_source_mnx_or_chebi(self, resolver):
        r = resolver.resolve("cysam", "Recon2.2", stratum="recon22")
        assert r.source in ("mnx_struct", "chebi")


# ──────────────────────────────────────────────────────────────────────────────
# Fixture 4 — Human1 MAM03595 (Beta glucan-glycocholate complex, non_single_structure)
# ──────────────────────────────────────────────────────────────────────────────

class TestHuman1MAM03595:
    def test_excluded_true(self, resolver):
        r = resolver.resolve("MAM03595", "Human1", stratum="human1")
        assert r.excluded is True

    def test_exclusion_class(self, resolver):
        r = resolver.resolve("MAM03595", "Human1", stratum="human1")
        assert r.exclusion_class == "non_single_structure"

    def test_resolved_false(self, resolver):
        r = resolver.resolve("MAM03595", "Human1", stratum="human1")
        assert r.resolved is False


# ──────────────────────────────────────────────────────────────────────────────
# Fixture 5 — Human1 MAM01111 (pseudo-node, no xref -> non_single_structure)
# ──────────────────────────────────────────────────────────────────────────────

class TestHuman1MAM01111:
    def test_excluded_true(self, resolver):
        r = resolver.resolve("MAM01111", "Human1", stratum="human1")
        assert r.excluded is True

    def test_exclusion_class(self, resolver):
        r = resolver.resolve("MAM01111", "Human1", stratum="human1")
        assert r.exclusion_class == "non_single_structure"


# ──────────────────────────────────────────────────────────────────────────────
# Fixture 6 — Human1 MAM01610 (Core5 g, structure_unavailable, NOT excluded)
# ──────────────────────────────────────────────────────────────────────────────

class TestHuman1MAM01610:
    def test_not_excluded(self, resolver):
        r = resolver.resolve("MAM01610", "Human1", stratum="human1")
        assert r.excluded is False

    def test_exclusion_class(self, resolver):
        r = resolver.resolve("MAM01610", "Human1", stratum="human1")
        assert r.exclusion_class == "structure_unavailable"

    def test_resolved_false(self, resolver):
        r = resolver.resolve("MAM01610", "Human1", stratum="human1")
        assert r.resolved is False


# ──────────────────────────────────────────────────────────────────────────────
# Fixture 7 — Non-existent id ("ZZZ999", "KEGG")
# ──────────────────────────────────────────────────────────────────────────────

class TestNonExistentId:
    def test_resolved_false(self, resolver):
        r = resolver.resolve("ZZZ999", "KEGG")
        assert r.resolved is False

    def test_smiles_none(self, resolver):
        r = resolver.resolve("ZZZ999", "KEGG")
        assert r.smiles is None

    def test_inchikey_none(self, resolver):
        r = resolver.resolve("ZZZ999", "KEGG")
        assert r.inchikey is None

    def test_source_none(self, resolver):
        r = resolver.resolve("ZZZ999", "KEGG")
        assert r.source is None

    def test_not_excluded(self, resolver):
        r = resolver.resolve("ZZZ999", "KEGG")
        assert r.excluded is False


# ──────────────────────────────────────────────────────────────────────────────
# resolve_metabolite convenience wrapper
# ──────────────────────────────────────────────────────────────────────────────

class TestResolveMetabolite:
    def test_same_as_resolve_kegg(self, resolver):
        r1 = resolver.resolve("C00031", "KEGG")
        r2 = resolver.resolve_metabolite({"id": "C00031", "id_type": "KEGG"})
        assert r1 == r2

    def test_same_as_resolve_with_stratum(self, resolver):
        r1 = resolver.resolve("txa2", "Recon2.2", stratum="recon22")
        r2 = resolver.resolve_metabolite(
            {"id": "txa2", "id_type": "Recon2.2"}, stratum="recon22"
        )
        assert r1 == r2


# ──────────────────────────────────────────────────────────────────────────────
# No-stratum: exclusion overlay should be skipped
# ──────────────────────────────────────────────────────────────────────────────

class TestNoStratumSkipsExclusion:
    def test_mam03595_no_stratum_not_excluded(self, resolver):
        # Without stratum, sidecar is not consulted
        r = resolver.resolve("MAM03595", "Human1")
        assert r.excluded is False
        assert r.exclusion_class is None


# ──────────────────────────────────────────────────────────────────────────────
# InChIKey derivation from SMILES (mnx_struct path only has smiles usually)
# ──────────────────────────────────────────────────────────────────────────────

class TestInchiKeyDerivation:
    def test_txa2_has_inchikey(self, resolver):
        r = resolver.resolve("txa2", "Recon2.2", stratum="recon22")
        # Either from mnx_structure.inchikey or derived from smiles
        assert r.inchikey is not None and len(r.inchikey) > 10

    def test_kegg_c00031_inchikey_matches_known(self, resolver):
        r = resolver.resolve("C00031", "KEGG")
        # D-glucose InChIKey first block
        assert r.inchikey and r.inchikey.startswith("WQZGKKKJIJFFOK")
