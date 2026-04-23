"""Shared fixtures for the day-1 end-to-end integration tests.

Responsibilities kept narrow on purpose:

- Put the repo root on sys.path once (tracks' unit tests each do this
  themselves; the integration suite does it centrally).
- Expose the three JSON fixture spectra under ``tests/fixtures/spectra/``
  as parametrised pytest fixtures with their ground-truth metadata.
- Build canonical ``PreprocessRequest`` objects from those fixtures so
  each e2e test starts from the same deterministic raw input.
- Register the skip markers used by the pipeline tests
  (``requires_gnps``, ``requires_pubchem_lite``, ``requires_inhouse_model``)
  so pytest does not complain about unknown marks.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "spectra"
_FIXTURE_NAMES = ["glucose_pos", "caffeine_pos", "lcarnitine_pos"]


@dataclass(frozen=True)
class FixtureSpectrum:
    """One parsed spectrum fixture + its ground-truth metadata.

    The JSON on disk stores peaks as ``[[mz, raw_intensity], ...]``; we
    flatten them into the two arrays ``PreprocessRequest`` expects.
    """

    name: str
    compound_name: str
    smiles: str
    inchikey: str
    hmdb_id: str
    precursor_mz: float
    adduct: str
    ionization_mode: str
    collision_energy: float | None
    raw_mz: list[float]
    raw_intensity: list[float]

    @classmethod
    def from_json(cls, path: Path) -> "FixtureSpectrum":
        data = json.loads(path.read_text())
        peaks = data["peaks"]
        return cls(
            name=path.stem,
            compound_name=data["compound_name"],
            smiles=data["smiles"],
            inchikey=data["inchikey"],
            hmdb_id=data["hmdb_id"],
            precursor_mz=float(data["precursor_mz"]),
            adduct=data["adduct"],
            ionization_mode=data["ionization_mode"],
            collision_energy=(
                float(data["collision_energy"])
                if data.get("collision_energy") is not None
                else None
            ),
            raw_mz=[float(p[0]) for p in peaks],
            raw_intensity=[float(p[1]) for p in peaks],
        )

    def to_preprocess_request(self):
        """Build a schemas.PreprocessRequest matching this fixture."""
        from schemas import PreprocessRequest

        return PreprocessRequest(
            raw_mz=self.raw_mz,
            raw_intensity=self.raw_intensity,
            precursor_mz=self.precursor_mz,
            adduct=self.adduct,
            ionization_mode=self.ionization_mode,
            collision_energy=self.collision_energy,
        )


def pytest_configure(config):
    """Register the env-gated marks so pytest does not warn."""
    for mark in (
        "requires_gnps",
        "requires_pubchem_lite",
        "requires_inhouse_model",
        # Tracks D / E — added by the D-E integration audit session.
        "requires_hmdb_db",
        "requires_ramp_db",
        "requires_cfm_id",
        "requires_pubchem_online",
    ):
        config.addinivalue_line(
            "markers",
            f"{mark}: integration test that requires an external resource "
            f"(env var / checkpoint). Skipped by default when the resource is absent.",
        )


@pytest.fixture(params=_FIXTURE_NAMES)
def fixture_spectrum(request) -> FixtureSpectrum:
    """Parametrised: yields each of the three fixture spectra in turn."""
    return FixtureSpectrum.from_json(_FIXTURE_DIR / f"{request.param}.json")


@pytest.fixture
def all_fixtures() -> list[FixtureSpectrum]:
    """All three fixtures as a list — used by the top-10 union assertion."""
    return [FixtureSpectrum.from_json(_FIXTURE_DIR / f"{n}.json") for n in _FIXTURE_NAMES]


@pytest.fixture
def has_gnps_env() -> bool:
    return bool(os.environ.get("METAGENT_GNPS_PATH"))


@pytest.fixture
def has_pubchem_lite_env() -> bool:
    return bool(os.environ.get("METAGENT_PUBCHEM_LITE_PATH"))


@pytest.fixture
def has_inhouse_model_env() -> bool:
    """True iff at least one of the real model checkpoints is configured."""
    return bool(os.environ.get("METAGENT_MSCLIP_CKPT")) or bool(
        os.environ.get("METAGENT_MSBART_CKPT")
    )


# ---------------------------------------------------------------------------
# Tracks D / E — shared helpers and env-gated fixtures.
#
# Philosophy: each test comes in two flavours. The mock flavour builds an
# in-tmp SQLite or canned HTTP response and always runs — it verifies the
# tool's structural contract, not data correctness. The real flavour skips
# unless the corresponding env var points at a reachable backend, and it
# verifies data correctness against whichever dump is installed.
# ---------------------------------------------------------------------------


import json as _json
import sqlite3 as _sqlite3


# --- env availability ------------------------------------------------------


def _path_exists(env_var: str) -> bool:
    val = os.environ.get(env_var, "")
    return bool(val) and os.path.exists(val)


def _cfm_reachable() -> bool:
    """True iff METAGENT_CFM_URL is set and responds 200 on /healthz.

    We do the probe lazily at fixture evaluation time, not import time, so
    that a flapping container does not wedge pytest collection.
    """
    url = os.environ.get("METAGENT_CFM_URL", "").strip()
    if not url:
        return False
    try:
        import requests

        r = requests.get(url.rstrip("/") + "/healthz", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture
def has_hmdb_db() -> bool:
    return _path_exists("METAGENT_HMDB_PATH")


@pytest.fixture
def has_ramp_db() -> bool:
    return _path_exists("METAGENT_RAMP_PATH")


@pytest.fixture
def has_cfm_id() -> bool:
    return _cfm_reachable()


@pytest.fixture
def has_pubchem_online() -> bool:
    """True iff the operator has explicitly opted into PubChem network traffic."""
    val = os.environ.get("METAGENT_ALLOW_PUBCHEM", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


# --- skip-or-fail when --integration is passed -----------------------------
#
# Mirror of the existing `_respect_integration_flag` autouse fixture in
# test_pipeline_e2e.py: when `--integration` is explicitly asked for, a
# required-env marker whose resource is absent should FAIL rather than skip,
# so CI cannot silently let a regression through. Kept local to D / E
# markers to avoid disturbing the existing A/B/C autouse.


@pytest.fixture(autouse=True)
def _respect_integration_flag_de(
    request,
    has_hmdb_db,
    has_ramp_db,
    has_cfm_id,
    has_pubchem_online,
):
    if not request.config.getoption("--integration", default=False):
        return
    marker_env_map: dict[str, bool] = {
        "requires_hmdb_db": has_hmdb_db,
        "requires_ramp_db": has_ramp_db,
        "requires_cfm_id": has_cfm_id,
        "requires_pubchem_online": has_pubchem_online,
    }
    for mark in request.node.iter_markers():
        want = marker_env_map.get(mark.name)
        if want is False:
            pytest.fail(
                f"--integration was passed but @pytest.mark.{mark.name} "
                "requires a resource that is not configured. "
                "Check METAGENT_HMDB_PATH / METAGENT_RAMP_PATH / "
                "METAGENT_CFM_URL / METAGENT_ALLOW_PUBCHEM."
            )


# --- Mini HMDB SQLite builder ---------------------------------------------
#
# Mirrors the production schema in tools/metabolite_info/hmdb_backend.py so
# the real backend code can drive the in-tmp DB unchanged. Extra fields that
# the fixture JSON does not carry (smiles, chemical_class, chebi, pubchem
# CID, synonyms, tissue, disease) come from a hand-curated map embedded
# here; we do NOT pull them from the real HMDB dump even when it is
# available — a tiny DB that a human can audit line-by-line is the whole
# point of the mock path.


_HMDB_FIXTURE_JSON = (
    _REPO_ROOT / "tests" / "fixtures" / "hmdb_ids" / "expected.json"
)

# Hand-curated extension of the fixture, keyed by hmdb_id. Kept minimal on
# purpose — only add a key if one of the D/E tests actually asserts on it.
# These values are from public HMDB/PubChem pages as of the fixture date;
# they intentionally use the generic (non-stereo-specific) forms so mock-
# path tests do not have to mirror HMDB's latest curation choices.
_HMDB_MOCK_EXTRA: dict[str, dict] = {
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
        # PubChem CID 221493 canonical SMILES. RDKit InChIKey on this one
        # matches the fixture's BHQCQFFYRZLCQQ-OELDTZBJSA-N; the earlier
        # variant we had encoded a different stereoisomer and tripped the
        # cross-tool consistency test.
        "smiles": "C[C@H](CCC(=O)O)[C@H]1CC[C@@H]2[C@@]1([C@H](C[C@H]3[C@H]2[C@@H](C[C@H]4[C@@]3(CC[C@H](C4)O)C)O)O)C",
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


def build_mini_hmdb_sqlite(db_path: Path) -> None:
    """Build a 10-row HMDB SQLite mirroring the production column layout.

    Uses the fixture JSON as the source of primary_name / formula / exact_mass
    / inchikey / kegg_id, and the _HMDB_MOCK_EXTRA map for the ancillary
    fields. The real hmdb_backend module can query this DB unchanged — the
    `resolve_db_path` shim in the test then redirects lookups here.
    """
    fixture = _json.loads(_HMDB_FIXTURE_JSON.read_text())
    conn = _sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE metabolites (
                hmdb_id                   TEXT PRIMARY KEY,
                primary_name              TEXT,
                molecular_formula         TEXT,
                exact_mass                REAL,
                smiles                    TEXT,
                inchikey                  TEXT,
                chemical_class            TEXT,
                kegg_id                   TEXT,
                chebi_id                  TEXT,
                pubchem_cid               TEXT,
                chembl_id                 TEXT,
                synonyms_json             TEXT,
                tissue_locations_json     TEXT,
                disease_associations_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX idx_inchikey ON metabolites(inchikey)")
        conn.execute("CREATE INDEX idx_kegg ON metabolites(kegg_id)")
        conn.execute("CREATE INDEX idx_name ON metabolites(primary_name COLLATE NOCASE)")

        for entry in fixture["entries"]:
            hid = entry["hmdb_id"]
            extra = _HMDB_MOCK_EXTRA.get(hid, {})
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
                    "hmdb_id": hid,
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
                    "synonyms_json": _json.dumps(extra.get("synonyms", [])),
                    "tissue_locations_json": _json.dumps(extra.get("tissue_locations", [])),
                    "disease_associations_json": _json.dumps(extra.get("disease_associations", [])),
                },
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def mock_hmdb_db(tmp_path, monkeypatch):
    """Build an in-tmp HMDB SQLite and wire the backend to use it.

    The returned value is the db path. Side effect: `hmdb_backend.resolve_db_path`
    always returns this path, MoNA is neutered, and PubChem network access is
    trip-wired to raise on any attempt.
    """
    from tools.metabolite_info import hmdb_backend, mona_supplement, pubchem_backend

    db_path = tmp_path / "hmdb_mini.sqlite"
    build_mini_hmdb_sqlite(db_path)
    monkeypatch.setattr(hmdb_backend, "resolve_db_path", lambda explicit=None: db_path)

    monkeypatch.setattr(mona_supplement, "get_index", lambda path=None: None)
    mona_supplement.clear_cache()

    monkeypatch.delenv(pubchem_backend.PUBCHEM_ALLOW_ENV_VAR, raising=False)

    def _forbid_network(url):  # pragma: no cover - tripwire, not expected to fire
        raise AssertionError(
            f"PubChem HTTP call attempted during unit test: {url!r}. "
            "Mock-path tests must not leak network traffic."
        )

    monkeypatch.setattr(pubchem_backend, "_get_json", _forbid_network)
    return db_path


# --- Mini RaMP SQLite builder ---------------------------------------------
#
# Mirrors the RaMP v3 columns the current `ramp_backend.py` queries:
#   source(sourceId, rampId, IDtype, commonName, dataSource, ...)
#   pathway(pathwayRampId, sourceId, pathwayName, type)
#   analytehaspathway(rampId, pathwayRampId, pathwaySource)
#   reaction2met(ramp_rxn_id, ramp_cmpd_id, substrate_product,
#                met_source_id, met_name, is_cofactor)
#   reaction(ramp_rxn_id, rxn_source_id, direction, ...)
#
# The mini-graph covers glucose / pyruvate / alanine / caffeine plus an
# orphan (adenosine, resolvable but no pathway rows). Glycolysis is laid out
# so pyruvate is downstream of glucose (reaction RXN_GLYCO_1 with glucose
# as substrate, pyruvate as product); transamination so alanine is
# downstream of pyruvate (RXN_ALA).


def build_mini_ramp_sqlite(db_path: Path) -> None:
    conn = _sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            -- Minimal subset of the RaMP v3 schema. Column types and names
            -- match production so ramp_backend.py's SQL runs unchanged.
            CREATE TABLE source (
                sourceId    TEXT,
                rampId      TEXT,
                IDtype      TEXT,
                commonName  TEXT,
                dataSource  TEXT
            );
            CREATE TABLE pathway (
                pathwayRampId  TEXT PRIMARY KEY,
                sourceId       TEXT,
                pathwayName    TEXT,
                type           TEXT
            );
            CREATE TABLE analytehaspathway (
                rampId         TEXT,
                pathwayRampId  TEXT,
                pathwaySource  TEXT
            );
            CREATE TABLE reaction2met (
                ramp_rxn_id        TEXT,
                rxn_source_id      TEXT,
                ramp_cmpd_id       TEXT,
                substrate_product  INTEGER,
                met_source_id      TEXT,
                met_name           TEXT,
                is_cofactor        INTEGER DEFAULT 0
            );
            CREATE TABLE reaction (
                ramp_rxn_id   TEXT PRIMARY KEY,
                rxn_source_id TEXT,
                direction     TEXT
            );
            """
        )

        sources = [
            # (sourceId, rampId, IDtype, commonName, dataSource)
            ("hmdb:HMDB0000122", "RAMP_C_GLUC", "hmdb", "D-Glucose", "hmdb"),
            ("kegg:C00031",       "RAMP_C_GLUC", "kegg", "D-Glucose", "kegg"),
            ("hmdb:HMDB0000243", "RAMP_C_PYR",  "hmdb", "Pyruvate",  "hmdb"),
            ("kegg:C00022",       "RAMP_C_PYR",  "kegg", "Pyruvate",  "kegg"),
            ("hmdb:HMDB0000161", "RAMP_C_ALA",  "hmdb", "L-Alanine", "hmdb"),
            ("kegg:C00041",       "RAMP_C_ALA",  "kegg", "L-Alanine", "kegg"),
            ("hmdb:HMDB0001847", "RAMP_C_CAFF", "hmdb", "Caffeine",  "hmdb"),
            # Orphan: resolves, no pathway rows.
            ("hmdb:HMDB0000050", "RAMP_C_ADEN_ORPHAN", "hmdb", "Adenosine", "hmdb"),
            # ChEBI-only metabolite (water) to exercise the P-3 dead-end case.
            ("chebi:15377",       "RAMP_C_H2O",  "chebi", "water",   "chebi"),
        ]
        conn.executemany(
            "INSERT INTO source VALUES (?, ?, ?, ?, ?)",
            sources,
        )

        pathways = [
            ("RAMP_P_GLYC_KEGG", "hsa00010",    "Glycolysis / Gluconeogenesis", "kegg"),
            ("RAMP_P_GLYC_REAC", "R-HSA-70171", "Glycolysis",                   "reactome"),
            ("RAMP_P_ALA_KEGG",  "hsa00250",    "Alanine, aspartate and glutamate metabolism", "kegg"),
            ("RAMP_P_CAFF_KEGG", "hsa00232",    "Caffeine metabolism",          "kegg"),
        ]
        conn.executemany(
            "INSERT INTO pathway VALUES (?, ?, ?, ?)",
            pathways,
        )

        analyte_pathways = [
            ("RAMP_C_GLUC", "RAMP_P_GLYC_KEGG", "kegg"),
            ("RAMP_C_GLUC", "RAMP_P_GLYC_REAC", "reactome"),
            ("RAMP_C_PYR",  "RAMP_P_GLYC_KEGG", "kegg"),
            ("RAMP_C_PYR",  "RAMP_P_GLYC_REAC", "reactome"),
            ("RAMP_C_PYR",  "RAMP_P_ALA_KEGG",  "kegg"),
            ("RAMP_C_ALA",  "RAMP_P_ALA_KEGG",  "kegg"),
            ("RAMP_C_CAFF", "RAMP_P_CAFF_KEGG", "kegg"),
        ]
        conn.executemany(
            "INSERT INTO analytehaspathway VALUES (?, ?, ?)",
            analyte_pathways,
        )

        # Reactions: glucose -> pyruvate, pyruvate -> alanine, plus a
        # cofactor-laden reaction (water participates) to stress the P-4
        # cofactor-filter question. Direction column is populated so a
        # future tool fix that consults it has data to work with.
        reactions = [
            ("RAMP_R_GLYCO_1", "rhea:10001", "left-to-right"),
            ("RAMP_R_ALA",     "rhea:10002", "left-to-right"),
        ]
        conn.executemany("INSERT INTO reaction VALUES (?, ?, ?)", reactions)

        # substrate_product: 1 = substrate, 0 = product.
        reaction_rows = [
            # glucose -> pyruvate
            ("RAMP_R_GLYCO_1", "rhea:10001", "RAMP_C_GLUC", 1, "hmdb:HMDB0000122", "D-Glucose", 0),
            ("RAMP_R_GLYCO_1", "rhea:10001", "RAMP_C_PYR",  0, "hmdb:HMDB0000243", "Pyruvate",  0),
            # cofactor (water, is_cofactor=1) participates as a product —
            # feeds the P-4 test
            ("RAMP_R_GLYCO_1", "rhea:10001", "RAMP_C_H2O",  0, "chebi:15377",       "H2O",       1),
            # pyruvate -> alanine
            ("RAMP_R_ALA", "rhea:10002", "RAMP_C_PYR", 1, "hmdb:HMDB0000243", "Pyruvate", 0),
            ("RAMP_R_ALA", "rhea:10002", "RAMP_C_ALA", 0, "hmdb:HMDB0000161", "L-Alanine", 0),
        ]
        conn.executemany(
            "INSERT INTO reaction2met VALUES (?, ?, ?, ?, ?, ?, ?)",
            reaction_rows,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def mock_ramp_db(tmp_path, monkeypatch):
    from tools.pathway_context import ramp_backend

    db_path = tmp_path / "ramp_mini.sqlite"
    build_mini_ramp_sqlite(db_path)
    monkeypatch.setattr(ramp_backend, "resolve_db_path", lambda explicit=None: db_path)
    return db_path


# --- Canned CFM-ID stdout for the mock path --------------------------------
#
# Keyed by SMILES. Values are realistic CFM-ID 4.x stdout blocks for the
# same SMILES the test_verifier_e.py tests use. Synthesising these here
# rather than pulling from the real container keeps the mock path
# deterministic and offline.


CFM_MOCK_STDOUTS: dict[str, str] = {
    # Glucose [M+H]+ — three energy ramps. Intensities are shaped so the
    # [M+H-H2O]+ fragment at 163.060 survives the union.
    "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O": (
        "#In-silico ESI-MS/MS [M+H]+ Spectra\n"
        "#PREDICTED BY cfm-predict 4.0.0 (mock)\n"
        "#SMILES=OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O\n"
        "#Formula=C6H12O6\n"
        "#PMass=181.07066\n"
        "energy0\n"
        "163.06010 92.64\n"
        "181.07066 100.00\n"
        "energy1\n"
        "61.02841 35.00\n"
        "85.02841 20.00\n"
        "145.04954 55.00\n"
        "163.06010 80.00\n"
        "181.07066 100.00\n"
        "energy2\n"
        "43.01784 60.00\n"
        "61.02841 100.00\n"
        "85.02841 30.00\n"
        "127.03897 25.00\n"
        "163.06010 20.00\n"
    ),
    # Caffeine [M+H]+ — includes the canonical 138.07 loss (CH3N=C=O).
    "CN1C=NC2=C1C(=O)N(C)C(=O)N2C": (
        "#In-silico ESI-MS/MS [M+H]+ Spectra\n"
        "#PREDICTED BY cfm-predict 4.0.0 (mock)\n"
        "#SMILES=CN1C=NC2=C1C(=O)N(C)C(=O)N2C\n"
        "#Formula=C8H10N4O2\n"
        "#PMass=195.08765\n"
        "energy0\n"
        "138.06619 55.00\n"
        "195.08765 100.00\n"
        "energy1\n"
        "110.07127 25.00\n"
        "138.06619 100.00\n"
        "195.08765 80.00\n"
        "energy2\n"
        "83.06037 30.00\n"
        "110.07127 60.00\n"
        "138.06619 100.00\n"
        "195.08765 40.00\n"
    ),
}


# Default mock stdout for any SMILES not explicitly enumerated: a 3-peak
# block so the tool has valid output without resembling any real molecule.
_CFM_MOCK_DEFAULT: str = (
    "#In-silico ESI-MS/MS [M+H]+ Spectra\n"
    "#PREDICTED BY cfm-predict 4.0.0 (mock)\n"
    "energy0\n"
    "50.00000 100.00\n"
    "energy1\n"
    "50.00000 50.00\n"
    "75.00000 100.00\n"
    "energy2\n"
    "50.00000 25.00\n"
    "75.00000 50.00\n"
    "100.00000 100.00\n"
)


def cfm_mock_body(smiles: str, model_version: str = "cfm-id-4.0.0-mock") -> dict:
    """Return the JSON body the CFM-ID shim would return for this SMILES.

    Used by requests_mock adapters in test_verifier_e.py. The test sets
    `m.post(url, json=cfm_mock_body(smiles))`.
    """
    stdout = CFM_MOCK_STDOUTS.get(smiles, _CFM_MOCK_DEFAULT)
    return {"model_version": model_version, "cfm_stdout": stdout}
