"""fetch_metabolite_info — Track D, Tool 5.

Resolves a single metabolite identifier into a structured metadata bundle.
The lookup order is:

    HMDB local SQLite   →   MoNA metadata supplement   →   PubChem PUG-REST

HMDB is the primary source because its annotation richness (tissue,
disease, cross-refs) is what the orchestrator and verifier rely on. MoNA
is a second chance for the ~7400 HMDB compounds where the local dump is
incomplete — it provides structural fields (SMILES, InChIKey, formula,
mass) but no tissue/disease context, so those stay empty. PubChem is the
last resort for non-HMDB compounds and is GATED on an explicit opt-in env
var so that tests and air-gapped deployments never leak traffic.

Contract reminders (see docs/TOOL_CONTRACTS.md § Tool 5):
  - A valid-looking identifier with no match returns `found=False`, not a raise.
  - The only raise is IdentifierFormatError for malformed input.
  - Unknown fields are None or []. NEVER invent a value.
  - `source` is one of {hmdb, pubchem, kegg, cached, None}. MoNA-sourced
    records map to "hmdb" since MoNA-HMDB is literally HMDB metadata.
"""
from __future__ import annotations

import logging
from typing import Literal

from schemas.molecule import MetaboliteInfoRequest, MetaboliteInfoResponse
from tools.metabolite_info import hmdb_backend, mona_supplement, pubchem_backend
from tools.metabolite_info.hmdb_backend import HmdbRow
from tools.metabolite_info.id_detect import resolve_id_type
from tools.metabolite_info.mona_supplement import MonaCompound
from tools.metabolite_info.pubchem_backend import PubChemHit

logger = logging.getLogger(__name__)

SourceLiteral = Literal["hmdb", "pubchem", "kegg", "cached"]


# ---------------------------------------------------------------------------
# HMDB path
# ---------------------------------------------------------------------------


def _try_hmdb(identifier: str, id_type: str) -> HmdbRow | None:
    """Attempt an HMDB SQLite lookup by id_type. Returns None on any miss
    (absent DB, empty result, or id_type the DB cannot serve directly)."""
    db_path = hmdb_backend.resolve_db_path()
    if db_path is None:
        return None
    conn = hmdb_backend.open_connection(db_path)
    try:
        if id_type == "hmdb":
            return hmdb_backend.lookup_by_hmdb(conn, identifier)
        if id_type == "kegg":
            return hmdb_backend.lookup_by_kegg(conn, identifier)
        if id_type == "inchikey":
            return hmdb_backend.lookup_by_inchikey(conn, identifier)
        if id_type == "name":
            return hmdb_backend.lookup_by_name(conn, identifier)
        if id_type == "smiles":
            return hmdb_backend.lookup_by_smiles(conn, identifier)
    finally:
        conn.close()
    return None


def _hmdb_row_to_response(row: HmdbRow) -> MetaboliteInfoResponse:
    """Project an HmdbRow into the shared response schema."""
    cross_refs = _build_cross_refs(
        hmdb=row.hmdb_id,
        kegg=row.kegg_id,
        chebi=row.chebi_id,
        pubchem_cid=row.pubchem_cid,
        chembl=row.chembl_id,
    )
    explain = _explain_hit(row.primary_name or row.hmdb_id, source="hmdb")
    return MetaboliteInfoResponse(
        found=True,
        primary_name=row.primary_name,
        synonyms=row.synonyms,
        molecular_formula=row.molecular_formula,
        exact_mass=row.exact_mass,
        smiles=row.smiles,
        inchikey=row.inchikey,
        chemical_class=row.chemical_class,
        tissue_locations=row.tissue_locations,
        disease_associations=row.disease_associations,
        cross_refs=cross_refs,
        source="hmdb",
        explain=explain,
    )


# ---------------------------------------------------------------------------
# MoNA supplement path
# ---------------------------------------------------------------------------


def _try_mona(identifier: str, id_type: str) -> MonaCompound | None:
    """MoNA supplement supports HMDB and InChIKey lookups only.

    Name / SMILES / KEGG go through HMDB or PubChem. MoNA's per-record name
    is unreliable for name queries (it's sometimes a synonym, sometimes the
    IUPAC name).
    """
    if id_type == "hmdb":
        return mona_supplement.lookup_by_hmdb(identifier)
    if id_type == "inchikey":
        return mona_supplement.lookup_by_inchikey(identifier)
    return None


def _mona_row_to_response(row: MonaCompound) -> MetaboliteInfoResponse:
    cross_refs = _build_cross_refs(hmdb=row.hmdb_id)
    explain = _explain_hit(row.primary_name or row.hmdb_id, source="mona")
    return MetaboliteInfoResponse(
        found=True,
        primary_name=row.primary_name,
        synonyms=[],
        molecular_formula=row.molecular_formula,
        exact_mass=row.exact_mass,
        smiles=row.smiles,
        inchikey=row.inchikey,
        chemical_class=None,
        tissue_locations=[],
        disease_associations=[],
        cross_refs=cross_refs,
        # MoNA-HMDB is a curated slice of HMDB, so the schema-allowed source
        # is "hmdb". We distinguish MoNA-origin from primary-HMDB-origin in
        # the explain string, not in the `source` field (which is constrained).
        source="hmdb",
        explain=explain,
    )


# ---------------------------------------------------------------------------
# PubChem fallback
# ---------------------------------------------------------------------------


def _try_pubchem(identifier: str, id_type: str) -> PubChemHit | None:
    return pubchem_backend.lookup(identifier, id_type)


def _pubchem_hit_to_response(hit: PubChemHit) -> MetaboliteInfoResponse:
    cross_refs = _build_cross_refs(pubchem_cid=hit.pubchem_cid)
    explain = _explain_hit(hit.primary_name or f"CID {hit.pubchem_cid}", source="pubchem")
    return MetaboliteInfoResponse(
        found=True,
        primary_name=hit.primary_name,
        synonyms=hit.synonyms,
        molecular_formula=hit.molecular_formula,
        exact_mass=hit.exact_mass,
        smiles=hit.smiles,
        inchikey=hit.inchikey,
        chemical_class=None,
        tissue_locations=[],
        disease_associations=[],
        cross_refs=cross_refs,
        source="pubchem",
        explain=explain,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_cross_refs(
    *,
    hmdb: str | None = None,
    kegg: str | None = None,
    chebi: str | None = None,
    pubchem_cid: str | None = None,
    chembl: str | None = None,
) -> dict[str, str]:
    """Assemble a cross_refs dict, omitting any key whose value is None/empty."""
    refs: dict[str, str] = {}
    if hmdb:
        refs["hmdb"] = hmdb
    if kegg:
        refs["kegg"] = kegg
    if chebi:
        refs["chebi"] = chebi
    if pubchem_cid:
        refs["pubchem_cid"] = str(pubchem_cid)
    if chembl:
        refs["chembl"] = chembl
    return refs


def _explain_hit(display_name: str, *, source: str) -> str:
    return f"Resolved '{display_name}' via {source} metadata source."


def _explain_miss(identifier: str, id_type: str) -> str:
    return (
        f"No record found for identifier '{identifier}' (treated as {id_type}). "
        "Local HMDB, MoNA supplement, and PubChem fallback all returned nothing."
    )


def _empty_response(identifier: str, id_type: str) -> MetaboliteInfoResponse:
    return MetaboliteInfoResponse(
        found=False,
        primary_name=None,
        synonyms=[],
        molecular_formula=None,
        exact_mass=None,
        smiles=None,
        inchikey=None,
        chemical_class=None,
        tissue_locations=[],
        disease_associations=[],
        cross_refs={},
        source=None,
        explain=_explain_miss(identifier, id_type),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fetch_metabolite_info(req: MetaboliteInfoRequest) -> MetaboliteInfoResponse:
    """Resolve one metabolite identifier to a metadata bundle.

    Raises:
        IdentifierFormatError: `req.identifier` is empty / whitespace / null.

    Never raises on an honest miss. Callers distinguish "unknown compound"
    from "bad input" by inspecting the `found` field vs. catching the error.
    """
    id_type = resolve_id_type(req.identifier, req.id_type)
    identifier = req.identifier.strip()

    # 1. HMDB local SQLite — richest annotation, preferred.
    hmdb_row = _try_hmdb(identifier, id_type)
    if hmdb_row is not None:
        return _hmdb_row_to_response(hmdb_row)

    # 2. MoNA supplement — structural fields only, for HMDB/InChIKey queries.
    mona_row = _try_mona(identifier, id_type)
    if mona_row is not None:
        return _mona_row_to_response(mona_row)

    # 3. PubChem PUG-REST — network-gated last resort.
    pubchem_hit = _try_pubchem(identifier, id_type)
    if pubchem_hit is not None:
        return _pubchem_hit_to_response(pubchem_hit)

    return _empty_response(identifier, id_type)
