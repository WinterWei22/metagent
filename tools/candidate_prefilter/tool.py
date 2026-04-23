"""candidate_prefilter — fast pre-screening before library_search / molecule_generate.

Given a precursor m/z + adduct (+ optional formula), back-calculates the
neutral exact mass and returns a narrowed pool of candidate structures from
the configured indices (GNPS in-memory + PubChem Lite SQLite).

No MS/MS spectrum is used here. No LLM call is made. Everything is local.

Main entry point: `prefilter(req: PrefilterRequest) -> PrefilterResponse`.
"""
from __future__ import annotations

import logging

from schemas.common import PrefilteredCandidate
from schemas.prefilter import PrefilterRequest, PrefilterResponse

from tools.candidate_prefilter.adducts import neutral_mass_from_precursor
from tools.candidate_prefilter.errors import PubChemLiteNotBuiltError
from tools.candidate_prefilter import gnps_index as _gnps_index_mod
from tools.candidate_prefilter import pubchem_index as _pubchem_index_mod

logger = logging.getLogger(__name__)


def prefilter(req: PrefilterRequest) -> PrefilterResponse:
    """Narrow the candidate search space by precursor mass / formula.

    Steps:
      1. Back-calculate neutral exact mass M from `precursor_mz` + `adduct`.
         Unsupported adducts raise InvalidAdductError.
      2. For each pool in `req.pools`, query its index for records with
         exact_mass within `mass_tolerance_ppm` of M, optionally filtered
         by `molecular_formula`.
      3. Stamp `has_reference_spectrum=True` on every candidate whose
         InChIKey is present in the GNPS pool (regardless of source_pool).
      4. Sort all candidates by `mass_error_ppm` ascending.
      5. Cap at `req.max_candidates`.
      6. Return a PrefilterResponse with a templated `explain` string.

    Notes on pools:
      - "gnps" and "pubchem_lite" are the two active pools in v0.
      - "hmdb" is declared in the schema for forward compatibility; v0 serves
        HMDB content via the pubchem_lite SQLite DB, so a request that lists
        only "hmdb" returns an empty n_by_pool["hmdb"]=0 (not an error). The
        explain string makes this observable to the LLM.
    """
    # 1. Neutral mass (may raise InvalidAdductError)
    neutral_mass = neutral_mass_from_precursor(req.precursor_mz, req.adduct)

    # 2a. GNPS index is always loaded (we need its inchikey set even if
    #     "gnps" isn't in the requested pools). Empty index is acceptable —
    #     has_reference_spectrum just stays False for everything.
    gnps_idx = _gnps_index_mod.get_default_index()
    gnps_inchikeys = gnps_idx.inchikey_set

    all_candidates: list[PrefilteredCandidate] = []
    n_by_pool: dict[str, int] = {}

    # 2b. GNPS pool
    if "gnps" in req.pools:
        gnps_candidates = gnps_idx.search(
            neutral_mass=neutral_mass,
            tolerance_ppm=req.mass_tolerance_ppm,
            formula=req.molecular_formula,
        )
        n_by_pool["gnps"] = len(gnps_candidates)
        all_candidates.extend(gnps_candidates)

    # 2c. pubchem_lite pool
    if "pubchem_lite" in req.pools:
        try:
            pc_idx = _pubchem_index_mod.get_default_index()
            pc_candidates = pc_idx.search(
                neutral_mass=neutral_mass,
                tolerance_ppm=req.mass_tolerance_ppm,
                formula=req.molecular_formula,
                limit=req.max_candidates,
                gnps_inchikeys=gnps_inchikeys,
            )
        except PubChemLiteNotBuiltError:
            # Propagate — operator must set up the DB. No silent fallback.
            raise
        n_by_pool["pubchem_lite"] = len(pc_candidates)
        all_candidates.extend(pc_candidates)

    # 2d. hmdb pool — intentionally a no-op in v0 (see docstring).
    if "hmdb" in req.pools:
        n_by_pool["hmdb"] = 0

    # 3. Re-stamp has_reference_spectrum across pools. The per-index search
    #    methods already set this for their own rows; this loop guarantees
    #    consistency if an index ever forgets (defensive, cheap).
    # Cross-pool matching uses InChIKey first-block (connectivity only) —
    # see gnps_index.inchikey_first_block for why.
    if gnps_inchikeys:
        from tools.candidate_prefilter.gnps_index import inchikey_first_block
        for c in all_candidates:
            if c.has_reference_spectrum:
                continue
            ik = _inchikey_for(c.smiles)
            block = inchikey_first_block(ik)
            if block and block in gnps_inchikeys:
                # Pydantic BaseModel is mutable by default (no frozen). If
                # PrefilteredCandidate becomes frozen later, switch to
                # model_copy(update=...) here.
                c.has_reference_spectrum = True

    # 4. Sort ascending by mass_error_ppm
    all_candidates.sort(key=lambda c: c.mass_error_ppm)

    # 5. Cap
    if len(all_candidates) > req.max_candidates:
        all_candidates = all_candidates[: req.max_candidates]

    # 6. Templated explain
    explain = _build_explain(
        neutral_mass=neutral_mass,
        req=req,
        final_count=len(all_candidates),
        n_by_pool=n_by_pool,
    )

    return PrefilterResponse(
        candidates=all_candidates,
        neutral_mass_computed=neutral_mass,
        n_by_pool=n_by_pool,
        explain=explain,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _inchikey_for(smiles: str) -> str | None:
    """Compute InChIKey from SMILES, silently returning None on any RDKit error."""
    try:
        from rdkit import Chem
    except ImportError:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        key = Chem.MolToInchiKey(mol)
        return key or None
    except Exception:
        return None


def _build_explain(
    *,
    neutral_mass: float,
    req: PrefilterRequest,
    final_count: int,
    n_by_pool: dict[str, int],
) -> str:
    """Factual one-sentence summary of the prefilter run. No LLM."""
    formula_clause = (
        f" Formula constraint {req.molecular_formula} applied."
        if req.molecular_formula
        else ""
    )

    # Pool breakdown — include zero-count pools so the caller sees what was
    # queried. Stable order: match req.pools ordering.
    pool_bits = [f"{n_by_pool.get(p, 0)} from {p}" for p in req.pools]
    pool_breakdown = ", ".join(pool_bits) if pool_bits else "no pools queried"

    return (
        f"Neutral mass {neutral_mass:.4f} (from {req.adduct} at {req.precursor_mz:.4f})."
        f"{formula_clause} "
        f"Returned {final_count} candidates within {req.mass_tolerance_ppm:g} ppm "
        f"({pool_breakdown})."
    )
