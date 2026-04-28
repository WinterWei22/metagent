"""Unit tests for tools.candidate_prefilter (Track A2).

Covers every case listed in docs/TOOL_CONTRACTS.md § Tool 2 and every test
listed in prompts/track_A2_candidate_prefilter.md. Uses:

  - A tiny SQLite DB built in tmp_path with 10 curated metabolites — lets the
    pubchem_lite pool run without the real 220k-row HMDB DB.
  - A hand-constructed GnpsIndex with 5 fake records — lets the gnps pool
    and has_reference_spectrum cross-stamping run without METAGENT_GNPS_PATH.

No real GNPS dump or built PubChem Lite DB is required. Integration tests
that need those resources are marked @pytest.mark.integration and skipped
when the corresponding env var is unset.
"""
from __future__ import annotations

import os
import sqlite3
import sys

# Allow running `pytest tests/tool_tests/test_candidate_prefilter.py` from the
# repo root without a shared conftest.py.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors

from schemas import PrefilterRequest
from schemas.common import PrefilteredCandidate

from tools.candidate_prefilter import prefilter
from tools.candidate_prefilter import gnps_index as gnps_mod
from tools.candidate_prefilter import pubchem_index as pubchem_mod
from tools.candidate_prefilter.adducts import neutral_mass_from_precursor
from tools.candidate_prefilter.errors import (
    InvalidAdductError,
    PubChemLiteNotBuiltError,
)
from tools.candidate_prefilter.gnps_index import (
    GnpsIndex,
    GnpsIndexRecord,
    inchikey_first_block,
)
from tools.candidate_prefilter.pubchem_index import PubChemLiteIndex


# ---------------------------------------------------------------------------
# Curated compound set shared by fixtures. Mass / formula / inchikey are
# derived from SMILES via RDKit inside the fixture — no hand-typed numbers
# that could drift from RDKit's canonical values.
# ---------------------------------------------------------------------------


_COMPOUNDS = [
    # (hmdb_id, name, smiles)  — 10 real metabolites + distractors
    ("HMDB0000122", "D-Glucose",      "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"),
    ("HMDB0000161", "L-Alanine",      "C[C@H](N)C(=O)O"),
    ("HMDB0000220", "Palmitic acid",  "CCCCCCCCCCCCCCCC(=O)O"),
    ("HMDB0001847", "Caffeine",       "CN1C=NC2=C1C(=O)N(C)C(=O)N2C"),
    ("HMDB0000050", "Adenosine",      "Nc1ncnc2c1ncn2[C@@H]1O[C@H](CO)[C@@H](O)[C@H]1O"),
    ("HMDB0000619", "Cholic acid",    "C[C@H](CCC(=O)O)[C@H]1CC[C@H]2[C@@H]3CC[C@@H]4C[C@H](O)CC[C@]4(C)[C@H]3C[C@H](O)[C@@]12C"),
    ("HMDB0000062", "L-Carnitine",    "C[N+](C)(C)C[C@H](O)CC([O-])=O"),
    ("HMDB0000063", "Cortisol",       "C[C@]12CC[C@H]3[C@@H](CCC4=CC(=O)CC[C@]34C)[C@@H]1C[C@H](O)[C@@]2(O)C(=O)CO"),
    ("HMDB0000073", "Dopamine",       "NCCc1ccc(O)c(O)c1"),
    ("HMDB0000289", "Uric acid",      "O=C1NC2=C(N1)C(=O)NC(=O)N2"),
    # Distractors: fructose shares C6H12O6 with glucose, used by the formula
    # filter test as a same-mass same-formula alternate.
    ("HMDB0000660", "D-Fructose",     "OC[C@@H](O)[C@@H](O)[C@H](O)C(=O)CO"),
    # A compound ~2 ppm off glucose's neutral mass to probe the tolerance
    # boundary. We'll pick one by sliding a synthetic SMILES with very close
    # but distinct mass — in practice "methyl formate sugar analog" isn't
    # real; instead we just pick another real metabolite whose mass happens
    # to be near glucose (galactitol, C6H14O6, mass ~182 — not within 5 ppm
    # of 180, so it *should not* match glucose queries).
    ("HMDB0000107", "Galactitol",     "OC[C@H](O)[C@@H](O)[C@@H](O)[C@H](O)CO"),
]


def _exact_mass_formula_inchikey(smiles: str) -> tuple[float, str, str]:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"RDKit failed to parse {smiles!r}"
    return (
        float(Descriptors.ExactMolWt(mol)),
        rdMolDescriptors.CalcMolFormula(mol),
        Chem.MolToInchiKey(mol),
    )


# ---------------------------------------------------------------------------
# PubChem Lite mini DB fixture
# ---------------------------------------------------------------------------


def _build_mini_sqlite(db_path: str) -> None:
    """Build a minimal pubchem_lite DB schema-identical to the real build.

    Schema must match pubchem_index.py's SELECT exactly, otherwise queries
    will fail with column-missing errors.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE pubchem_lite (
                compound_id       TEXT PRIMARY KEY,
                source            TEXT NOT NULL,
                name              TEXT,
                smiles            TEXT NOT NULL,
                canonical_smiles  TEXT,
                inchikey          TEXT,
                molecular_formula TEXT NOT NULL,
                exact_mass        REAL NOT NULL,
                pubchem_cid       INTEGER,
                hmdb_id           TEXT
            );
            CREATE INDEX idx_exact_mass ON pubchem_lite(exact_mass);
            CREATE INDEX idx_formula    ON pubchem_lite(molecular_formula);
            CREATE INDEX idx_inchikey   ON pubchem_lite(inchikey);
            """
        )
        for hmdb_id, name, smiles in _COMPOUNDS:
            exact, formula, inchikey = _exact_mass_formula_inchikey(smiles)
            conn.execute(
                "INSERT INTO pubchem_lite "
                "(compound_id, source, name, smiles, canonical_smiles, "
                " inchikey, molecular_formula, exact_mass, pubchem_cid, hmdb_id) "
                "VALUES (?, 'hmdb', ?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    hmdb_id,
                    name,
                    smiles,
                    Chem.MolToSmiles(Chem.MolFromSmiles(smiles)),
                    inchikey,
                    formula,
                    exact,
                    hmdb_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def mini_pubchem_db(tmp_path) -> str:
    db_path = tmp_path / "pubchem_lite_mini.sqlite"
    _build_mini_sqlite(str(db_path))
    return str(db_path)


# ---------------------------------------------------------------------------
# Fake GNPS index fixture
# ---------------------------------------------------------------------------


def _gnps_records_for(
    compounds: list[tuple[str, str, str]],
    ion_mode: str = "positive",
) -> list[GnpsIndexRecord]:
    """Build GnpsIndexRecords from (ccmslib_id, name, smiles) triples.

    All records share the given ion_mode; pass "negative" to build a fake
    negative-mode index for mode-specific tests.
    """
    out: list[GnpsIndexRecord] = []
    for ccmslib_id, name, smiles in compounds:
        exact, formula, inchikey = _exact_mass_formula_inchikey(smiles)
        out.append(
            GnpsIndexRecord(
                spectrum_id=ccmslib_id,
                compound_name=name,
                smiles=smiles,
                inchikey=inchikey,
                molecular_formula=formula,
                exact_mass=exact,
                ion_mode=ion_mode,
            )
        )
    return out


# GNPS has SOME but not all of the compounds in pubchem_lite. Used to test
# the has_reference_spectrum cross-stamp: caffeine is in GNPS → pubchem_lite
# caffeine candidate gets has_reference_spectrum=True. L-carnitine is NOT
# in GNPS → stays False.
_GNPS_COMPOUNDS = [
    ("CCMSLIB00000000001", "D-Glucose",  "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"),
    ("CCMSLIB00000000002", "Caffeine",   "CN1C=NC2=C1C(=O)N(C)C(=O)N2C"),
    ("CCMSLIB00000000003", "Adenosine",  "Nc1ncnc2c1ncn2[C@@H]1O[C@H](CO)[C@@H](O)[C@H]1O"),
    ("CCMSLIB00000000004", "Dopamine",   "NCCc1ccc(O)c(O)c1"),
    ("CCMSLIB00000000005", "Uric acid",  "O=C1NC2=C(N1)C(=O)NC(=O)N2"),
]


@pytest.fixture
def fake_gnps_index() -> GnpsIndex:
    return GnpsIndex(_gnps_records_for(_GNPS_COMPOUNDS))


# ---------------------------------------------------------------------------
# Autouse: install the fake indices as module defaults for every test,
# then reset. This replaces what production reads out of env vars.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _install_indices(fake_gnps_index, mini_pubchem_db):
    gnps_mod.set_default_index(fake_gnps_index)
    pubchem_mod.set_default_index(PubChemLiteIndex(mini_pubchem_db))
    yield
    gnps_mod.set_default_index(None)
    pubchem_mod.set_default_index(None)


# ---------------------------------------------------------------------------
# adducts.py
# ---------------------------------------------------------------------------


class TestAdducts:
    """Test case 1 in the contract + adduct-table correctness."""

    def test_m_plus_h_back_calculates_neutral_mass_for_glucose(self):
        # [M+H]+ at 181.0707 → glucose neutral ~180.0634, within 0.001 Da.
        m = neutral_mass_from_precursor(181.0707, "[M+H]+")
        assert abs(m - 180.0634) < 0.001

    def test_m_minus_h_is_consistent_with_m_plus_h(self):
        # Same neutral mass, two ionisations: both should back-calculate
        # within ~0.001 Da of each other for glucose.
        m_pos = neutral_mass_from_precursor(181.0707, "[M+H]+")
        m_neg = neutral_mass_from_precursor(179.0561, "[M-H]-")
        assert abs(m_pos - m_neg) < 0.001

    def test_m_plus_na_gives_reasonable_glucose_mass(self):
        m = neutral_mass_from_precursor(203.0526, "[M+Na]+")
        assert abs(m - 180.0634) < 0.01

    def test_dimer_adduct_halves_the_effective_mass(self):
        # [2M+H]+ at 361.1341 → M ≈ 180.0634 (glucose)
        m = neutral_mass_from_precursor(361.1341, "[2M+H]+")
        assert abs(m - 180.0634) < 0.01

    def test_unknown_adduct_raises(self):
        with pytest.raises(InvalidAdductError):
            neutral_mass_from_precursor(181.0707, "banana")


# ---------------------------------------------------------------------------
# prefilter() main flow
# ---------------------------------------------------------------------------


class TestPrefilter:
    def test_glucose_in_top_candidates_for_m_plus_h_at_181_0707(self):
        """Contract test #2: glucose appears among the top candidates for its
        [M+H]+ precursor.
        """
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707,
                adduct="[M+H]+",
                mass_tolerance_ppm=5.0,
            )
        )
        assert any("HMDB0000122" in c.source_id for c in resp.candidates), (
            "Glucose (HMDB0000122) should be in prefilter results for its own "
            "precursor m/z."
        )
        # And it should be at or near the top (mass error < 5 ppm, which is
        # already guaranteed, so we just check it's in the first few).
        top_ids = [c.source_id for c in resp.candidates[:5]]
        assert any("HMDB0000122" in tid for tid in top_ids), (
            f"Glucose should be in top-5 but top ids were {top_ids}"
        )

    def test_formula_hard_constraint_filters_non_matching(self):
        """Contract test #3: formula=C6H12O6 returns only C6H12O6 candidates.

        At 5 ppm around 180.0634, several non-C6H12O6 isomers could in theory
        sneak in. With the constraint, the formula filter must be absolute.
        """
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707,
                adduct="[M+H]+",
                molecular_formula="C6H12O6",
                mass_tolerance_ppm=20.0,  # wider → more chances to drag in non-matches
            )
        )
        assert resp.candidates, "Expected at least one C6H12O6 candidate (glucose)."
        for c in resp.candidates:
            assert c.molecular_formula == "C6H12O6", (
                f"Formula filter violated: got {c.molecular_formula} for {c.source_id}"
            )
        ids = {c.source_id for c in resp.candidates}
        # Both glucose and fructose are C6H12O6 and should show up when pools
        # include pubchem_lite (our mini DB has both).
        assert any("HMDB0000122" in i for i in ids)  # glucose
        assert any("HMDB0000660" in i for i in ids)  # fructose

    def test_narrow_ppm_returns_strict_subset_of_wide_ppm(self):
        """Contract test #4: 0.5 ppm is a subset of 20 ppm."""
        wide = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707, adduct="[M+H]+", mass_tolerance_ppm=20.0,
            )
        )
        narrow = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707, adduct="[M+H]+", mass_tolerance_ppm=0.5,
            )
        )
        wide_ids = {(c.source_pool, c.source_id) for c in wide.candidates}
        narrow_ids = {(c.source_pool, c.source_id) for c in narrow.candidates}
        assert narrow_ids.issubset(wide_ids)
        assert len(narrow.candidates) <= len(wide.candidates)

    def test_empty_candidate_list_does_not_raise(self):
        """Contract test #5: nonsense precursor → empty list, no exception."""
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=1.5, adduct="[M+H]+", mass_tolerance_ppm=5.0,
            )
        )
        assert resp.candidates == []
        # neutral_mass can be ~0.5; response still valid because the schema
        # requires neutral_mass_computed > 0 — at 1.5 [M+H]+ we get M≈0.49.
        assert resp.neutral_mass_computed > 0
        # n_by_pool still reports the pools queried (with zeros).
        assert resp.n_by_pool.get("gnps", 0) == 0
        assert resp.n_by_pool.get("pubchem_lite", 0) == 0

    def test_candidates_sorted_by_mass_error_ascending(self):
        """Contract test #6."""
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707,
                adduct="[M+H]+",
                mass_tolerance_ppm=20.0,
            )
        )
        errors = [c.mass_error_ppm for c in resp.candidates]
        assert errors == sorted(errors), f"Candidates not sorted: {errors}"

    def test_invalid_adduct_raises_invalid_adduct_error(self):
        """Contract test #7."""
        with pytest.raises(InvalidAdductError):
            prefilter(
                PrefilterRequest(
                    precursor_mz=181.0707, adduct="banana", mass_tolerance_ppm=5.0,
                )
            )

    def test_has_reference_spectrum_matches_gnps_membership(self):
        """Contract test #8: has_reference_spectrum=True iff InChIKey is in GNPS.

        Our fake GNPS index contains caffeine and glucose but NOT L-carnitine.
        So the pubchem_lite caffeine candidate must be has_reference_spectrum=True,
        while pubchem_lite L-carnitine must be has_reference_spectrum=False.
        """
        # Caffeine: [M+H]+ at 195.0877
        resp_caffeine = prefilter(
            PrefilterRequest(
                precursor_mz=195.0877, adduct="[M+H]+", mass_tolerance_ppm=5.0,
            )
        )
        pubchem_caffeine = [
            c for c in resp_caffeine.candidates
            if c.source_pool == "pubchem_lite" and "HMDB0001847" in c.source_id
        ]
        assert pubchem_caffeine, "Caffeine pubchem_lite candidate missing"
        assert all(c.has_reference_spectrum for c in pubchem_caffeine), (
            "Caffeine is in GNPS; its pubchem_lite counterpart should have "
            "has_reference_spectrum=True"
        )

        # L-carnitine: [M+H]+ at ~162.1125 (M=161.1052)
        resp_carn = prefilter(
            PrefilterRequest(
                precursor_mz=162.1125, adduct="[M+H]+", mass_tolerance_ppm=5.0,
            )
        )
        pubchem_carn = [
            c for c in resp_carn.candidates
            if c.source_pool == "pubchem_lite" and "HMDB0000062" in c.source_id
        ]
        assert pubchem_carn, "L-carnitine pubchem_lite candidate missing"
        assert all(not c.has_reference_spectrum for c in pubchem_carn), (
            "L-carnitine is NOT in fake GNPS; pubchem_lite counterpart should "
            "have has_reference_spectrum=False"
        )

    def test_all_mass_errors_within_requested_tolerance(self):
        """Contract: mass_error_ppm values in the result must all be <= requested."""
        tol = 5.0
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707, adduct="[M+H]+", mass_tolerance_ppm=tol,
            )
        )
        for c in resp.candidates:
            assert c.mass_error_ppm <= tol + 1e-9

    # -----------------------------------------------------------------------
    # Additional behavioural coverage beyond the minimum contract list.
    # -----------------------------------------------------------------------

    def test_neutral_mass_computed_matches_adduct_backcalc(self):
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707, adduct="[M+H]+", mass_tolerance_ppm=5.0,
            )
        )
        expected = neutral_mass_from_precursor(181.0707, "[M+H]+")
        assert abs(resp.neutral_mass_computed - expected) < 1e-9

    def test_max_candidates_caps_output_length(self):
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707,
                adduct="[M+H]+",
                mass_tolerance_ppm=100.0,   # wide — pulls in as many as possible
                max_candidates=2,
            )
        )
        assert len(resp.candidates) <= 2

    def test_n_by_pool_counts_are_consistent_with_final_candidates(self):
        """n_by_pool reports raw per-pool counts before the cap; sum >= final."""
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707,
                adduct="[M+H]+",
                mass_tolerance_ppm=20.0,
            )
        )
        # In this test case (no cap hit), sum should equal final length.
        total = sum(resp.n_by_pool.values())
        assert total == len(resp.candidates)

    def test_gnps_only_pool_request_skips_pubchem(self):
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707,
                adduct="[M+H]+",
                pools=["gnps"],
                mass_tolerance_ppm=5.0,
            )
        )
        assert all(c.source_pool == "gnps" for c in resp.candidates)
        assert "pubchem_lite" not in resp.n_by_pool

    def test_hmdb_pool_in_v0_is_noop(self):
        """v0 serves HMDB via pubchem_lite. Requesting only 'hmdb' yields 0."""
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707,
                adduct="[M+H]+",
                pools=["hmdb"],
                mass_tolerance_ppm=20.0,
            )
        )
        assert resp.candidates == []
        assert resp.n_by_pool.get("hmdb") == 0

    def test_explain_mentions_adduct_and_ppm(self):
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707, adduct="[M+H]+", mass_tolerance_ppm=5.0,
            )
        )
        assert "[M+H]+" in resp.explain
        assert "181.0707" in resp.explain
        assert "5" in resp.explain  # ppm value

    def test_response_candidates_are_prefiltered_candidate_instances(self):
        """Schema-level sanity: the response is actually PrefilteredCandidate objects."""
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=181.0707, adduct="[M+H]+", mass_tolerance_ppm=5.0,
            )
        )
        for c in resp.candidates:
            assert isinstance(c, PrefilteredCandidate)
            assert c.source_pool in ("gnps", "pubchem_lite", "hmdb")
            assert c.mass_error_ppm >= 0
            assert c.exact_mass > 0
            assert c.smiles  # non-empty


# ---------------------------------------------------------------------------
# GNPS CSV loader (alternative to the JSON path via common.gnps_loader)
# ---------------------------------------------------------------------------


class TestGnpsCsvLoader:
    """gnps_index.py also reads the GNPS2 ALL_GNPS_cleaned_enriched CSV dump.

    The autouse fixture in this module installs a hand-built GnpsIndex as the
    default, so this class explicitly goes through build_index_from_path() to
    exercise the CSV code path rather than the injected default.
    """

    def _write_mini_gnps_csv(self, path, rows):
        """Write a minimal CSV matching the GNPS2 enriched schema."""
        import csv
        header = [
            "scan", "spectrum_id", "collision_energy", "Adduct",
            "Compound_Source", "Compound_Name", "Precursor_MZ", "ExactMass",
            "Charge", "Ion_Mode", "Smiles", "INCHI", "InChIKey_smiles",
            "msManufacturer", "msMassAnalyzer", "msIonisation",
        ]
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            for i, r in enumerate(rows, 1):
                w.writerow([
                    i, r["spectrum_id"], "", "[M+H]1+", "isolated",
                    r["compound_name"], "100.0", "100.0", "1",
                    r["ion_mode"], r["smiles"], "", "", "", "",
                    r["ms_ionisation"],
                ])

    def test_csv_loader_builds_index_with_positive_soft_ionisation_rows(self, tmp_path):
        csv_path = tmp_path / "gnps_mini.csv"
        self._write_mini_gnps_csv(csv_path, [
            dict(spectrum_id="CCMSLIB00000000001", compound_name="glucose",
                 smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
                 ion_mode="positive", ms_ionisation="ESI"),
            dict(spectrum_id="CCMSLIB00000000002", compound_name="caffeine",
                 smiles="CN1C=NC2=C1C(=O)N(C)C(=O)N2C",
                 ion_mode="positive", ms_ionisation="ESI"),
        ])
        idx = gnps_mod.build_index_from_path(csv_path)
        assert len(idx) == 2
        # Positive-mode partition holds both; negative is empty.
        assert len(idx.inchikey_set_for("positive")) == 2
        assert len(idx.inchikey_set_for("negative")) == 0

    def test_csv_loader_keeps_negative_mode_rejects_maldi(self, tmp_path):
        """v0.2: negative mode is now KEPT. MALDI / unknown ionisation are rejected."""
        csv_path = tmp_path / "gnps_mini.csv"
        self._write_mini_gnps_csv(csv_path, [
            dict(spectrum_id="CCMSLIB00000000003", compound_name="neg-mode",
                 smiles="CCO", ion_mode="negative", ms_ionisation="ESI"),
            dict(spectrum_id="CCMSLIB00000000004", compound_name="maldi-run",
                 smiles="CCO", ion_mode="positive", ms_ionisation="MALDI"),
            dict(spectrum_id="CCMSLIB00000000005", compound_name="kept-pos",
                 smiles="CCO", ion_mode="positive", ms_ionisation="ESI"),
        ])
        idx = gnps_mod.build_index_from_path(csv_path)
        # 1 positive (kept-pos) + 1 negative (neg-mode); MALDI dropped.
        assert idx.count_for("positive") == 1
        assert idx.count_for("negative") == 1
        # Mode-specific search returns the right one.
        pos_hits = idx.search(neutral_mass=46.04186, tolerance_ppm=5.0,
                              ion_mode="positive")
        assert [h.source_id for h in pos_hits] == ["CCMSLIB00000000005"]
        neg_hits = idx.search(neutral_mass=46.04186, tolerance_ppm=5.0,
                              ion_mode="negative")
        assert [h.source_id for h in neg_hits] == ["CCMSLIB00000000003"]

    def test_csv_loader_skips_unparseable_smiles(self, tmp_path):
        csv_path = tmp_path / "gnps_mini.csv"
        self._write_mini_gnps_csv(csv_path, [
            dict(spectrum_id="CCMSLIB00000000006", compound_name="garbage",
                 smiles="NOT_A_SMILES_STRING[](",
                 ion_mode="positive", ms_ionisation="ESI"),
            dict(spectrum_id="CCMSLIB00000000007", compound_name="valid",
                 smiles="CCO", ion_mode="positive", ms_ionisation="ESI"),
        ])
        idx = gnps_mod.build_index_from_path(csv_path)
        assert len(idx) == 1

    def test_unsupported_extension_raises(self, tmp_path):
        bad = tmp_path / "gnps.txt"
        bad.write_text("")
        with pytest.raises(ValueError, match="Unsupported GNPS file extension"):
            gnps_mod.build_index_from_path(bad)


class TestInchikeyFirstBlockCrossStamp:
    """Cross-pool has_reference_spectrum matches on connectivity (first 14
    chars) not the full InChIKey, so stereoisomers of the same compound
    (e.g. alpha vs beta glucose) still stamp each other as has_ref=True.
    """

    def test_first_block_helper_handles_edge_cases(self):
        assert inchikey_first_block("WQZGKKKJIJFFOK-GASJEMHNSA-N") == "WQZGKKKJIJFFOK"
        assert inchikey_first_block("WQZGKKKJIJFFOK") == "WQZGKKKJIJFFOK"
        assert inchikey_first_block("") is None
        assert inchikey_first_block(None) is None

    def test_gnps_index_inchikey_set_returns_first_blocks(self):
        # Caffeine — two records with the same connectivity but different
        # middle blocks (simulated stereo variation).
        recs = [
            GnpsIndexRecord(
                spectrum_id="CCMSLIB00000000001",
                compound_name="caffeine-v1",
                smiles="CN1C=NC2=C1C(=O)N(C)C(=O)N2C",
                inchikey="RYYVLZVUVIJVGH-UHFFFAOYSA-N",
                molecular_formula="C8H10N4O2",
                exact_mass=194.0804,
                ion_mode="positive",
            ),
            GnpsIndexRecord(
                spectrum_id="CCMSLIB00000000002",
                compound_name="caffeine-v2",
                smiles="CN1C=NC2=C1C(=O)N(C)C(=O)N2C",
                inchikey="RYYVLZVUVIJVGH-FAKEMIDL3Y-K",  # same first block
                molecular_formula="C8H10N4O2",
                exact_mass=194.0804,
                ion_mode="positive",
            ),
        ]
        idx = GnpsIndex(recs)
        # inchikey_set_for("positive") stores first-block values, so the two
        # records collapse to one entry in the set.
        assert idx.inchikey_set_for("positive") == frozenset({"RYYVLZVUVIJVGH"})
        # Negative mode partition is independent and empty.
        assert idx.inchikey_set_for("negative") == frozenset()

    def test_pubchem_candidate_stereo_variant_stamps_has_ref(self, tmp_path):
        """A pubchem_lite row with a different stereo variant than GNPS must
        still be flagged has_reference_spectrum=True.
        """
        # Mini pubchem_lite with one row: caffeine with a MADE-UP stereo middle.
        db = tmp_path / "mini.sqlite"
        conn = sqlite3.connect(str(db))
        try:
            conn.executescript(
                """
                CREATE TABLE pubchem_lite (
                    compound_id TEXT PRIMARY KEY, source TEXT NOT NULL,
                    name TEXT, smiles TEXT NOT NULL, canonical_smiles TEXT,
                    inchikey TEXT, molecular_formula TEXT NOT NULL,
                    exact_mass REAL NOT NULL, pubchem_cid INTEGER, hmdb_id TEXT
                );
                CREATE INDEX idx_exact_mass ON pubchem_lite(exact_mass);
                """
            )
            conn.execute(
                "INSERT INTO pubchem_lite VALUES "
                "('CID:99999', 'pubchem', 'caffeine-stereo-variant', "
                " 'CN1C=NC2=C1C(=O)N(C)C(=O)N2C', NULL, "
                " 'RYYVLZVUVIJVGH-FAKEMIDL3Y-K',"
                " 'C8H10N4O2', 194.0804, 99999, NULL)"
            )
            conn.commit()
        finally:
            conn.close()

        # GNPS index holds the "canonical" caffeine InChIKey (different middle).
        gnps_mod.set_default_index(GnpsIndex([
            GnpsIndexRecord(
                spectrum_id="CCMSLIB_ref",
                compound_name="caffeine",
                smiles="CN1C=NC2=C1C(=O)N(C)C(=O)N2C",
                inchikey="RYYVLZVUVIJVGH-UHFFFAOYSA-N",
                molecular_formula="C8H10N4O2",
                exact_mass=194.0804,
                ion_mode="positive",
            ),
        ]))
        pubchem_mod.set_default_index(PubChemLiteIndex(db))

        resp = prefilter(PrefilterRequest(
            precursor_mz=195.0877, adduct="[M+H]+",
            pools=["pubchem_lite"], mass_tolerance_ppm=5.0,
        ))
        pc = [c for c in resp.candidates if c.source_id == "CID:99999"]
        assert pc, "Stereo-variant pubchem row should still surface"
        assert pc[0].has_reference_spectrum, (
            "Stereo-variant caffeine should match GNPS caffeine on InChIKey "
            "first-block and therefore has_reference_spectrum=True"
        )


# ---------------------------------------------------------------------------
# Negative-mode (v0.2): mode-aware queries and has_reference_spectrum
# ---------------------------------------------------------------------------


class TestNegativeMode:
    """v0.2 changes: GnpsIndex partitions by mode; tool.py derives mode
    from req.adduct; has_reference_spectrum is True only when GNPS has
    same-mode coverage of the candidate's connectivity.
    """

    def test_polarity_for_known_adducts(self):
        from tools.candidate_prefilter.adducts import polarity_for
        assert polarity_for("[M+H]+") == "positive"
        assert polarity_for("[M+Na]+") == "positive"
        assert polarity_for("[M-H]-") == "negative"
        assert polarity_for("[M+FA-H]-") == "negative"

    def test_polarity_for_unknown_adduct_raises(self):
        from tools.candidate_prefilter.adducts import polarity_for
        with pytest.raises(InvalidAdductError):
            polarity_for("banana")

    def test_negative_adduct_query_returns_candidates(self):
        """Glucose [M-H]- at 179.0561 → neutral 180.0634 → pubchem_lite still
        finds it (the SQLite is mode-agnostic). GNPS pool only sees
        negative-mode records, which our autouse fixture has none of, so
        gnps count is 0 — but pubchem_lite delivers regardless.
        """
        resp = prefilter(PrefilterRequest(
            precursor_mz=179.0561, adduct="[M-H]-",
            mass_tolerance_ppm=5.0,
        ))
        # Same neutral mass as the [M+H]+ test → same pubchem_lite hits.
        ids = {c.source_id for c in resp.candidates if c.source_pool == "pubchem_lite"}
        assert any("HMDB0000122" in i for i in ids)
        # Fake GNPS in autouse fixture is positive-only, so under [M-H]-
        # the gnps pool is empty.
        assert resp.n_by_pool.get("gnps", 0) == 0

    def test_has_reference_spectrum_is_mode_specific(self):
        """A pubchem candidate matches has_ref=True only against same-mode
        GNPS data. Same connectivity but only in opposite-mode GNPS → False.
        """
        # Build a GNPS index with caffeine in NEGATIVE mode only.
        idx = GnpsIndex([
            GnpsIndexRecord(
                spectrum_id="CCMSLIB_neg",
                compound_name="caffeine-neg",
                smiles="CN1C=NC2=C1C(=O)N(C)C(=O)N2C",
                inchikey="RYYVLZVUVIJVGH-UHFFFAOYSA-N",
                molecular_formula="C8H10N4O2",
                exact_mass=194.0804,
                ion_mode="negative",
            ),
        ])
        gnps_mod.set_default_index(idx)

        # Caffeine [M+H]+ → positive query. GNPS only has it in negative.
        resp = prefilter(PrefilterRequest(
            precursor_mz=195.0877, adduct="[M+H]+",
            pools=["pubchem_lite"], mass_tolerance_ppm=5.0,
        ))
        caffeine_pc = [c for c in resp.candidates
                       if c.source_pool == "pubchem_lite"
                       and "HMDB0001847" in c.source_id]
        assert caffeine_pc
        # Cross-pool stamp should NOT trigger because GNPS has caffeine in
        # the WRONG mode.
        assert all(not c.has_reference_spectrum for c in caffeine_pc)

        # Same query under [M-H]- → should now stamp has_ref=True.
        resp_neg = prefilter(PrefilterRequest(
            precursor_mz=193.0731, adduct="[M-H]-",
            pools=["pubchem_lite"], mass_tolerance_ppm=5.0,
        ))
        caffeine_pc_neg = [c for c in resp_neg.candidates
                           if c.source_pool == "pubchem_lite"
                           and "HMDB0001847" in c.source_id]
        assert caffeine_pc_neg
        assert all(c.has_reference_spectrum for c in caffeine_pc_neg)

    def test_records_with_unknown_mode_are_dropped_from_index(self):
        # ion_mode='unknown' → ignored at construction.
        idx = GnpsIndex([
            GnpsIndexRecord(
                spectrum_id="CCMSLIB_unknown",
                compound_name="ethanol-unknown-mode",
                smiles="CCO",
                inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
                molecular_formula="C2H6O",
                exact_mass=46.04186,
                ion_mode="unknown",
            ),
            GnpsIndexRecord(
                spectrum_id="CCMSLIB_pos",
                compound_name="ethanol",
                smiles="CCO",
                inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
                molecular_formula="C2H6O",
                exact_mass=46.04186,
                ion_mode="positive",
            ),
        ])
        # Only the positive one survives.
        assert len(idx) == 1
        assert idx.count_for("positive") == 1
        assert idx.count_for("negative") == 0


# ---------------------------------------------------------------------------
# PubChemLiteIndex error path
# ---------------------------------------------------------------------------


class TestPubChemLiteNotBuilt:
    def test_missing_sqlite_raises_on_query(self, tmp_path):
        """A path that doesn't exist should raise PubChemLiteNotBuiltError
        when queried, not when constructed (lazy check is by design)."""
        idx = PubChemLiteIndex(tmp_path / "nonexistent.sqlite")
        with pytest.raises(PubChemLiteNotBuiltError):
            idx.search(neutral_mass=180.0, tolerance_ppm=5.0)

    def test_unset_env_var_raises_in_get_default_index(self, monkeypatch):
        # Clear the cached default and env var, then call get_default_index.
        pubchem_mod.set_default_index(None)
        monkeypatch.delenv(pubchem_mod.ENV_PATH_VAR, raising=False)
        with pytest.raises(PubChemLiteNotBuiltError):
            pubchem_mod.get_default_index()


# ---------------------------------------------------------------------------
# Integration — real data. Skip unless env vars are set. Kept minimal.
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("METAGENT_PUBCHEM_LITE_PATH"),
    reason="METAGENT_PUBCHEM_LITE_PATH not set",
)
def test_integration_real_pubchem_lite_finds_glucose():
    # Reset the mocked defaults for this test and let production lazy-load.
    pubchem_mod.set_default_index(None)
    gnps_mod.set_default_index(None)

    resp = prefilter(
        PrefilterRequest(
            precursor_mz=181.0707,
            adduct="[M+H]+",
            mass_tolerance_ppm=5.0,
        )
    )
    ids = {c.source_id for c in resp.candidates}
    # At least one HMDB/PubChem glucose variant should surface.
    assert any("glucose" in (c.name or "").lower() for c in resp.candidates) or (
        any("HMDB0000122" in i for i in ids)
    )
