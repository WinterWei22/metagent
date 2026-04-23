"""Unit tests for tools.metabolite_info (Track D, Tool 5).

Covers every case listed in docs/TOOL_CONTRACTS.md § Tool 5 and every test
listed in prompts/track_D_metabolite_info_pathway_context.md.

Uses a tmp_path mini HMDB SQLite built from the curated HMDB IDs in
tests/fixtures/hmdb_ids/expected.json (10 central metabolites). No real
HMDB dump, no real PubChem traffic, no MoNA dump required — all three
backends are either populated in-process (HMDB) or monkey-patched off
(MoNA, PubChem). A runtime assertion hook is installed on the PubChem
backend to fail loudly if any test accidentally triggers a network call.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from schemas import MetaboliteInfoRequest

from tools.metabolite_info import fetch_metabolite_info
from tools.metabolite_info import hmdb_backend, mona_supplement, pubchem_backend
from tools.metabolite_info.errors import IdentifierFormatError
from tools.metabolite_info.id_detect import detect_id_type


# ---------------------------------------------------------------------------
# Curated rows for the tmp HMDB SQLite. Values from tests/fixtures/hmdb_ids/
# expected.json plus SMILES taken from PubChem/HMDB public pages. Each row
# is a full HmdbRow projection so we can drive every lookup path.
# ---------------------------------------------------------------------------


_FIXTURE_PATH = Path(_REPO_ROOT) / "tests" / "fixtures" / "hmdb_ids" / "expected.json"

# hmdb_id -> extra fields not in expected.json (smiles, class, chebi, cid).
# Kept hand-curated in the test rather than invented by the tool — no risk
# of overwriting other tracks' fixtures.
_EXTRA = {
    "HMDB0000122": {
        "smiles": "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        "chemical_class": "Hexose monosaccharide",
        "chebi_id": "CHEBI:17234",
        "pubchem_cid": "5793",
        "synonyms": ["glucose", "dextrose", "D-(+)-glucose"],
        "tissue_locations": ["Blood", "Liver", "Kidney"],
        "disease_associations": ["Diabetes mellitus"],
    },
    "HMDB0000062": {
        "smiles": "C[N+](C)(C)C[C@H](O)CC([O-])=O",
        "chemical_class": "Quaternary ammonium",
        "chebi_id": "CHEBI:16347",
        "pubchem_cid": "10917",
        "synonyms": ["L-carnitine", "levocarnitine"],
        "tissue_locations": ["Skeletal muscle", "Heart"],
        "disease_associations": [],
    },
    "HMDB0001847": {
        "smiles": "CN1C=NC2=C1C(=O)N(C)C(=O)N2C",
        "chemical_class": "Xanthine",
        "chebi_id": "CHEBI:27732",
        "pubchem_cid": "2519",
        "synonyms": ["caffeine", "1,3,7-trimethylxanthine"],
        "tissue_locations": ["Blood", "Urine"],
        "disease_associations": [],
    },
    "HMDB0000243": {
        "smiles": "CC(=O)C(=O)O",
        "chemical_class": "Alpha-keto acid",
        "chebi_id": "CHEBI:32816",
        "pubchem_cid": "1060",
        "synonyms": ["pyruvic acid", "2-oxopropanoic acid"],
        "tissue_locations": ["Blood", "Liver"],
        "disease_associations": [],
    },
    "HMDB0000161": {
        "smiles": "C[C@H](N)C(=O)O",
        "chemical_class": "Amino acid",
        "chebi_id": "CHEBI:16977",
        "pubchem_cid": "5950",
        "synonyms": ["alanine", "L-alanine"],
        "tissue_locations": ["Blood"],
        "disease_associations": [],
    },
    "HMDB0000289": {
        "smiles": "O=c1[nH]c(=O)c2[nH]c(=O)[nH]c2[nH]1",
        "chemical_class": "Purine",
        "chebi_id": "CHEBI:27226",
        "pubchem_cid": "1175",
        "synonyms": ["uric acid", "2,6,8-trioxypurine"],
        "tissue_locations": ["Blood", "Urine"],
        "disease_associations": ["Gout"],
    },
    "HMDB0000050": {
        "smiles": "Nc1ncnc2c1ncn2[C@@H]1O[C@H](CO)[C@@H](O)[C@H]1O",
        "chemical_class": "Nucleoside",
        "chebi_id": "CHEBI:16335",
        "pubchem_cid": "60961",
        "synonyms": ["adenosine"],
        "tissue_locations": ["Blood", "Brain"],
        "disease_associations": [],
    },
    "HMDB0000073": {
        "smiles": "NCCc1ccc(O)c(O)c1",
        "chemical_class": "Catecholamine",
        "chebi_id": "CHEBI:18243",
        "pubchem_cid": "681",
        "synonyms": ["dopamine"],
        "tissue_locations": ["Brain"],
        "disease_associations": [],
    },
    "HMDB0000619": {
        "smiles": "C[C@H](CCC(=O)O)[C@H]1CC[C@H]2[C@@H]3CC[C@@H]4C[C@H](O)CC[C@]4(C)[C@H]3C[C@H](O)[C@@]12C",
        "chemical_class": "Bile acid",
        "chebi_id": "CHEBI:16359",
        "pubchem_cid": "221493",
        "synonyms": ["cholic acid"],
        "tissue_locations": ["Liver", "Bile"],
        "disease_associations": [],
    },
    "HMDB0000220": {
        "smiles": "CCCCCCCCCCCCCCCC(=O)O",
        "chemical_class": "Fatty acid",
        "chebi_id": "CHEBI:15756",
        "pubchem_cid": "985",
        "synonyms": ["palmitic acid", "hexadecanoic acid"],
        "tissue_locations": ["Adipose"],
        "disease_associations": [],
    },
}


def _load_expected_rows() -> list[dict]:
    with open(_FIXTURE_PATH) as f:
        data = json.load(f)
    return data["entries"]


def _build_mini_hmdb_db(db_path: Path) -> None:
    """Build a 10-row HMDB SQLite mirroring the production schema."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE metabolites (
                hmdb_id TEXT PRIMARY KEY,
                primary_name TEXT,
                molecular_formula TEXT,
                exact_mass REAL,
                smiles TEXT,
                inchikey TEXT,
                chemical_class TEXT,
                kegg_id TEXT,
                chebi_id TEXT,
                pubchem_cid TEXT,
                chembl_id TEXT,
                synonyms_json TEXT,
                tissue_locations_json TEXT,
                disease_associations_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX idx_inchikey ON metabolites(inchikey)")
        conn.execute("CREATE INDEX idx_kegg ON metabolites(kegg_id)")
        conn.execute(
            "CREATE INDEX idx_name ON metabolites(primary_name COLLATE NOCASE)"
        )

        for entry in _load_expected_rows():
            hmdb_id = entry["hmdb_id"]
            extra = _EXTRA.get(hmdb_id, {})
            conn.execute(
                """
                INSERT INTO metabolites VALUES (
                    :hmdb_id, :primary_name, :molecular_formula, :exact_mass,
                    :smiles, :inchikey, :chemical_class, :kegg_id, :chebi_id,
                    :pubchem_cid, :chembl_id, :synonyms_json,
                    :tissue_locations_json, :disease_associations_json
                )
                """,
                {
                    "hmdb_id": hmdb_id,
                    "primary_name": entry["primary_name"],
                    "molecular_formula": entry["molecular_formula"],
                    "exact_mass": entry["exact_mass"],
                    "smiles": extra.get("smiles"),
                    "inchikey": entry["inchikey"],
                    "chemical_class": extra.get("chemical_class"),
                    "kegg_id": entry["kegg_id"],
                    "chebi_id": extra.get("chebi_id"),
                    "pubchem_cid": extra.get("pubchem_cid"),
                    "chembl_id": None,
                    "synonyms_json": json.dumps(extra.get("synonyms", [])),
                    "tissue_locations_json": json.dumps(
                        extra.get("tissue_locations", [])
                    ),
                    "disease_associations_json": json.dumps(
                        extra.get("disease_associations", [])
                    ),
                },
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_backends(tmp_path, monkeypatch):
    """Point the HMDB backend at an in-tmp SQLite; neuter MoNA and PubChem.

    The returned object is just the db_path for tests that want to assert
    on it; side effects (monkeypatches) are what matter.
    """
    db_path = tmp_path / "hmdb_mini.sqlite"
    _build_mini_hmdb_db(db_path)

    # Redirect HMDB resolver to our tmp DB regardless of env.
    monkeypatch.setattr(
        hmdb_backend,
        "resolve_db_path",
        lambda explicit=None: db_path,
    )

    # MoNA supplement off: tests that need it will monkey-patch per test.
    monkeypatch.setattr(mona_supplement, "get_index", lambda path=None: None)
    mona_supplement.clear_cache()

    # Ensure PubChem stays quiet. The backend already gates on
    # METAGENT_ALLOW_PUBCHEM, but we also clear the env var and install a
    # tripwire at the HTTP layer so any future regression that tries to
    # bypass the gate blows up loudly instead of making a real request.
    monkeypatch.delenv(pubchem_backend.PUBCHEM_ALLOW_ENV_VAR, raising=False)

    def _forbid_network(url):
        raise AssertionError(
            f"PubChem HTTP call attempted during unit test: {url!r}. "
            "Tests must not rely on network access."
        )

    monkeypatch.setattr(pubchem_backend, "_get_json", _forbid_network)

    return db_path


# ---------------------------------------------------------------------------
# Contract tests — each test case corresponds to a bullet in
# docs/TOOL_CONTRACTS.md § Tool 5 or in the Track D brief.
# ---------------------------------------------------------------------------


def test_hmdb_glucose_lookup(patched_backends):
    """HMDB0000122 → found=True, formula=C6H12O6, exact_mass≈180.06."""
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB0000122", id_type="hmdb")
    )
    assert resp.found is True
    assert resp.primary_name == "D-Glucose"
    assert resp.molecular_formula == "C6H12O6"
    assert resp.exact_mass is not None
    assert abs(resp.exact_mass - 180.0634) < 1e-3
    assert resp.source == "hmdb"
    # cross_refs must include both HMDB and the curated KEGG link.
    assert resp.cross_refs["hmdb"] == "HMDB0000122"
    assert resp.cross_refs["kegg"] == "C00031"


def test_unknown_hmdb_returns_not_found(patched_backends):
    """A well-formed but non-existent HMDB ID returns found=False, never raises."""
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB9999999", id_type="hmdb")
    )
    assert resp.found is False
    assert resp.primary_name is None
    assert resp.molecular_formula is None
    assert resp.exact_mass is None
    assert resp.synonyms == []
    assert resp.tissue_locations == []
    assert resp.disease_associations == []
    assert resp.cross_refs == {}
    assert resp.source is None


def test_auto_detect_id_types():
    """id_type='auto' discriminates HMDB / InChIKey / SMILES / name."""
    assert detect_id_type("HMDB0000122") == "hmdb"
    assert detect_id_type("hmdb0000122") == "hmdb"  # case-insensitive
    assert detect_id_type("C00031") == "kegg"
    assert detect_id_type("WQZGKKKJIJFFOK-GASJEMHNSA-N") == "inchikey"
    assert detect_id_type("OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O") == "smiles"
    # A plain English name should not match any strict pattern.
    assert detect_id_type("glucose") == "name"


def test_kegg_crossref_roundtrip(patched_backends):
    """Fetching by KEGG C00031 yields the same HMDB0000122 cross-ref."""
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="C00031", id_type="kegg")
    )
    assert resp.found is True
    assert resp.cross_refs["hmdb"] == "HMDB0000122"
    assert resp.cross_refs["kegg"] == "C00031"
    # And going the other direction — by HMDB — returns the same KEGG ID.
    resp2 = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB0000122", id_type="hmdb")
    )
    assert resp2.cross_refs["kegg"] == resp.cross_refs["kegg"]


def test_empty_identifier_raises():
    """Empty string must raise IdentifierFormatError."""
    with pytest.raises(IdentifierFormatError):
        fetch_metabolite_info(
            MetaboliteInfoRequest.model_construct(identifier="", id_type="auto")
        )


def test_whitespace_identifier_raises():
    with pytest.raises(IdentifierFormatError):
        fetch_metabolite_info(
            MetaboliteInfoRequest.model_construct(identifier="   ", id_type="auto")
        )


def test_no_disease_hallucination(patched_backends):
    """Compounds with no HMDB-listed disease association return [], never
    a plausible-sounding fake. Caffeine (HMDB0001847) is seeded with an
    empty disease list in the fixture — the tool must propagate that."""
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB0001847", id_type="hmdb")
    )
    assert resp.found is True
    assert resp.primary_name == "Caffeine"
    assert resp.disease_associations == []
    # Tissue data is present, so we also check it — the tool must not
    # blank it out by mistake when only some annotations are missing.
    assert "Blood" in resp.tissue_locations


def test_auto_detect_routes_hmdb(patched_backends):
    """id_type='auto' drives an HMDB id to the HMDB backend transparently."""
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB0000243", id_type="auto")
    )
    assert resp.found is True
    assert resp.primary_name == "Pyruvic acid"
    assert resp.source == "hmdb"


def test_legacy_hmdb_padding(patched_backends):
    """Legacy 5-digit HMDB IDs get zero-padded to the stored 7-digit form."""
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB00122", id_type="hmdb")
    )
    assert resp.found is True
    assert resp.cross_refs["hmdb"] == "HMDB0000122"


def test_inchikey_lookup(patched_backends):
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(
            identifier="WQZGKKKJIJFFOK-GASJEMHNSA-N",
            id_type="inchikey",
        )
    )
    assert resp.found is True
    assert resp.cross_refs["hmdb"] == "HMDB0000122"


def test_smiles_lookup(patched_backends):
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(
            identifier="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
            id_type="smiles",
        )
    )
    assert resp.found is True
    assert resp.primary_name == "D-Glucose"


def test_name_lookup_case_insensitive(patched_backends):
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="d-glucose", id_type="name")
    )
    assert resp.found is True
    assert resp.cross_refs["hmdb"] == "HMDB0000122"


def test_name_lookup_via_synonym(patched_backends):
    """Name queries fall through to the synonyms_json column when the
    primary_name doesn't match exactly."""
    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="dextrose", id_type="name")
    )
    assert resp.found is True
    assert resp.cross_refs["hmdb"] == "HMDB0000122"


def test_missing_db_returns_not_found(monkeypatch):
    """If the local HMDB DB isn't configured, and MoNA/PubChem are off,
    the tool reports found=False rather than crashing."""
    monkeypatch.setattr(hmdb_backend, "resolve_db_path", lambda explicit=None: None)
    monkeypatch.setattr(mona_supplement, "get_index", lambda path=None: None)
    monkeypatch.setattr(pubchem_backend, "lookup", lambda identifier, id_type: None)

    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB0000122", id_type="hmdb")
    )
    assert resp.found is False
    assert resp.source is None


# ---------------------------------------------------------------------------
# D-1 regression: zwitterion / protonated-cation HMDB entries
# ---------------------------------------------------------------------------


def _build_cation_hmdb_db(db_path: Path) -> None:
    """Build a 1-row HMDB SQLite carrying L-carnitine's HMDB 5.0 cation form.

    Values come directly from the audit's R-4 reproduction against the
    production dump at /data/weiwentao/llm_agent_metabolomics/hmdb.sqlite:
      molecular_formula = C7H16NO3
      exact_mass        = 162.113  (cation, +1 H compared to neutral 161.105)
      inchikey          = PHIQHXFUZVPYII-ZCFIWIBFSA-O  (terminal -O = proton layer)

    The mini DB is deliberately a separate fixture from _build_mini_hmdb_db
    so it does not contaminate the other 14 tests that predate the D-1
    fixture-vs-real divergence.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE metabolites (
                hmdb_id TEXT PRIMARY KEY,
                primary_name TEXT,
                molecular_formula TEXT,
                exact_mass REAL,
                smiles TEXT,
                inchikey TEXT,
                chemical_class TEXT,
                kegg_id TEXT,
                chebi_id TEXT,
                pubchem_cid TEXT,
                chembl_id TEXT,
                synonyms_json TEXT,
                tissue_locations_json TEXT,
                disease_associations_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO metabolites VALUES (
                'HMDB0000062', 'L-Carnitine', 'C7H16NO3', 162.113018383,
                'C[N+](C)(C)C[C@H](O)CC(=O)[O-]', 'PHIQHXFUZVPYII-ZCFIWIBFSA-O',
                'Quaternary ammonium', 'C00318', 'CHEBI:16347', '10917',
                NULL, '[]', '[]', '[]'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_d1_lcarnitine_returns_hmdb_cation_form(tmp_path, monkeypatch):
    """HMDB 5.0's curated L-carnitine entry is the protonated cation, NOT
    the neutral zwitterion. The tool must propagate HMDB verbatim — no
    silent renormalisation to the neutral form — so downstream consumers
    can detect the built-in +1 H mass offset when matching experimental
    [M+H]⁺ precursors.

    This is the D-1 data-characteristic the audit (R-4) flagged and the
    tool description's 'Zwitterion / protonation hazard' section documents.
    Propagating HMDB verbatim is the correct behaviour; the verifier /
    orchestrator are the ones that must back-compute the neutral mass
    from `smiles` via RDKit when precursor matching is load-bearing.

    Reference values from /data/weiwentao/llm_agent_metabolomics/hmdb.sqlite
    (HMDB 5.0, 217,920 rows) and reproduced here in a 1-row mini DB:

        molecular_formula = C7H16NO3    (cation, not neutral C7H15NO3)
        exact_mass        = 162.113     (cation, not neutral 161.105)
        inchikey          = PHIQHXFUZVPYII-ZCFIWIBFSA-O   (trailing -O = proton layer)
    """
    db_path = tmp_path / "hmdb_carnitine_cation.sqlite"
    _build_cation_hmdb_db(db_path)
    monkeypatch.setattr(
        hmdb_backend, "resolve_db_path", lambda explicit=None: db_path
    )
    monkeypatch.setattr(mona_supplement, "get_index", lambda path=None: None)
    monkeypatch.delenv(pubchem_backend.PUBCHEM_ALLOW_ENV_VAR, raising=False)
    monkeypatch.setattr(
        pubchem_backend, "_get_json",
        lambda url: pytest.fail(f"PubChem call during D-1 test: {url}"),
    )

    resp = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB0000062", id_type="hmdb")
    )
    assert resp.found is True
    assert resp.primary_name == "L-Carnitine"
    # Formula carries the extra H — this is the cation, NOT the neutral zwitterion.
    assert resp.molecular_formula == "C7H16NO3", (
        "L-carnitine must be propagated as HMDB's cation C7H16NO3; "
        "any neutral C7H15NO3 means the tool silently renormalised and "
        "broke the trust-anchor contract."
    )
    # Mass carries the extra proton (~+1.008 Da vs neutral 161.105).
    assert resp.exact_mass is not None
    assert abs(resp.exact_mass - 162.113) < 0.01, (
        f"expected cation mass ≈ 162.113, got {resp.exact_mass}; "
        "the tool must NOT convert cation mass to neutral."
    )
    # InChIKey's terminal -O is the protonation layer; silently flipping
    # it to -N would be a structural lie.
    assert resp.inchikey == "PHIQHXFUZVPYII-ZCFIWIBFSA-O", (
        f"InChIKey protonation layer must be preserved verbatim; got {resp.inchikey!r}"
    )
