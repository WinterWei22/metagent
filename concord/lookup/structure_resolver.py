"""Unified metabolite ID → structure resolver (V3 Part 2, 2A finalisation).

Resolves a benchmark metabolite identifier to a canonical SMILES + InChIKey
using a three-stage, offline-first chain:

    1. Local ChEBI sqlite   (all namespace xrefs; returns smiles + inchikey)
    2. MetaNetX struct db   (metanetx_struct.sqlite; bigg_mnx + xref_mnx → mnx_structure)
    3. Online last-mile     (static JSON overlay; keyed "{stratum}|{id_type}|{id}")

Namespace bridging:
    - KEGG / HMDB / ChEBI / PubChem  → direct ChEBI xref lookup
    - Human1 (MAM id)               → Human-GEM annotation table → xref set
    - Recon2.2 (BiGG slug)          → bigg_mnx → MNX, plus GEM back-lookup

Exclusion overlay (sidecar JSON):
    non_single_structure  → excluded=True   (polymers / complexes / pseudo-nodes)
    structure_unavailable → excluded=False  (real molecules, structure not yet in DB)
    No stratum / no hit   → excluded=False, exclusion_class=None

Thread safety:
    sqlite connections are opened fresh per call (uri=?mode=ro).
    GEM table, exclusion sidecar, and lastmile overlay are loaded once in
    __init__ as immutable dicts — safe for concurrent reads.

Usage::

    from concord.lookup.structure_resolver import StructureResolver

    resolver = StructureResolver()

    # Single id
    r = resolver.resolve("C00031", "KEGG")
    # → StructureResolution(resolved=True, source="chebi", smiles="OC[C@H]1…", …)

    # From benchmark differential_metabolites element
    r = resolver.resolve_metabolite({"id": "txa2", "id_type": "Recon2.2"}, stratum="recon22")

See also:
    reports/unifying_id/2026-06-23_structure_namespace_unification.md  (design)
    concord/lookup/chebi.py                                             (ChebiLookup)
    scripts/metagent/v3_build_exclusion_sidecar.py                     (reference impl)
"""
from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from concord.lookup.chebi import ChebiLookup

# Silence RDKit SMILES-parse warnings
try:
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
    _RDKIT_AVAILABLE = True
except ImportError:
    _RDKIT_AVAILABLE = False

# ── GEM column → canonical namespace ─────────────────────────────────────────
_GEM_COL_TO_NS: dict[str, str] = {
    "metKEGGID":      "KEGG",
    "metHMDBID":      "HMDB",
    "metChEBIID":     "CHEBI",
    "metPubChemID":   "PUBCHEM",
    "metLipidMapsID": "LIPIDMAPS",
    "metMetaNetXID":  "MNX",
    "metBiGGID":      "BIGG",
}

# id_type strings used in benchmark → canonical namespace key
_ID_TYPE_TO_NS: dict[str, str] = {
    "KEGG":    "KEGG",
    "HMDB":    "HMDB",
    "ChEBI":   "CHEBI",
    "PubChem": "PUBCHEM",
}

# ChEBI lookup_by_xref namespace strings
_CHEBI_XREF_NS: dict[str, str] = {
    "KEGG":     "KEGG",
    "HMDB":     "HMDB",
    "PUBCHEM":  "PUBCHEM",
    "LIPIDMAPS": "LIPIDMAPS",
}


@dataclass(frozen=True)
class StructureResolution:
    """Result of resolving one metabolite ID to structure."""

    id: str
    id_type: str
    inchikey: str | None
    smiles: str | None
    resolved: bool            # True iff smiles is not None
    source: str | None        # "chebi" | "mnx_struct" | "lastmile" | None
    excluded: bool            # True iff non_single_structure
    exclusion_class: str | None  # "non_single_structure" | "structure_unavailable" | None


class StructureResolver:
    """Resolve benchmark metabolite IDs to canonical SMILES + InChIKey.

    Parameters
    ----------
    chebi_db:
        Path to ``chebi.sqlite`` (built by ``concord.etl.chebi_etl``).
    struct_db:
        Path to ``metanetx_struct.sqlite`` (built by
        ``scripts/metagent/v3_build_structure_index.py``).
    gem_tsv:
        Path to Human-GEM metabolite annotation TSV
        (``data/reference/human_gem_metabolites.tsv``).
    exclusion_sidecar:
        Path to exclusion JSON sidecar (``excluded_metabolites_easy_v3.json``).
        May be None to skip exclusion overlay.
    lastmile:
        Path to online last-mile resolved JSON (``lastmile_resolved.json``).
        May be None to skip last-mile overlay.
    """

    def __init__(
        self,
        *,
        chebi_db: Path | str = "data/concord/chebi.sqlite",
        struct_db: Path | str = "data/concord/metanetx_struct.sqlite",
        gem_tsv: Path | str = "data/reference/human_gem_metabolites.tsv",
        exclusion_sidecar: Path | str | None = (
            "data/benchmark/metagent_bench_v2/excluded_metabolites_easy_v3.json"
        ),
        lastmile: Path | str | None = (
            "data/metagent/v3_part2_coverage/lastmile_resolved.json"
        ),
    ) -> None:
        self._chebi = ChebiLookup(chebi_db)
        self._struct_db = Path(struct_db).resolve()
        if not self._struct_db.exists():
            raise FileNotFoundError(
                f"metanetx_struct.sqlite not found at {self._struct_db}. "
                "Run `python scripts/metagent/v3_build_structure_index.py` first."
            )
        # Load GEM table once (immutable dict, safe for concurrent reads)
        self._gem, self._bigg_index = _load_gem(Path(gem_tsv))
        # Load exclusion sidecar
        if exclusion_sidecar is not None:
            p = Path(exclusion_sidecar)
            if p.exists():
                raw: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
                self._exclusions: dict[str, dict[str, str]] = raw.get("excluded", {})
            else:
                self._exclusions = {}
        else:
            self._exclusions = {}
        # Load lastmile overlay
        if lastmile is not None:
            p = Path(lastmile)
            self._lastmile: dict[str, str | None] = (
                json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            )
        else:
            self._lastmile = {}

    # ── public API ────────────────────────────────────────────────────────────

    def resolve(
        self,
        met_id: str,
        id_type: str,
        *,
        stratum: str | None = None,
    ) -> StructureResolution:
        """Resolve one (met_id, id_type) pair.

        Parameters
        ----------
        met_id:
            The metabolite identifier string (e.g. "C00031", "txa2", "MAM01610").
        id_type:
            Namespace string as used in the benchmark
            ("KEGG" | "HMDB" | "ChEBI" | "PubChem" | "Human1" | "Recon2.2").
        stratum:
            Task stratum ("human1" | "recon22" | "sub6_enrich" |
            "hmdb_ramp_membership").  Required for exclusion overlay and
            lastmile lookup.  If None, both overlays are skipped.
        """
        # 1. Exclusion overlay (requires stratum)
        excluded, exclusion_class = self._exclusion_check(met_id, id_type, stratum)

        # 2. Collect candidate xrefs
        cands = _collect_cands(met_id, id_type, self._gem, self._bigg_index)

        # 3. Resolution chain: ChEBI → MNX struct → lastmile
        smiles, inchikey, source = self._resolve_chain(
            cands, met_id, id_type, stratum
        )

        resolved = smiles is not None
        # Derive InChIKey from smiles when missing
        if smiles is not None and inchikey is None:
            inchikey = _inchikey_from_smiles(smiles)

        return StructureResolution(
            id=met_id,
            id_type=id_type,
            inchikey=inchikey,
            smiles=smiles,
            resolved=resolved,
            source=source,
            excluded=excluded,
            exclusion_class=exclusion_class,
        )

    def resolve_metabolite(
        self,
        met: dict[str, str],
        *,
        stratum: str | None = None,
    ) -> StructureResolution:
        """Convenience wrapper for benchmark differential_metabolites elements.

        Parameters
        ----------
        met:
            Dict with at least ``"id"`` and ``"id_type"`` keys.
        stratum:
            Forwarded to :meth:`resolve`.
        """
        return self.resolve(str(met["id"]), str(met["id_type"]), stratum=stratum)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _exclusion_check(
        self,
        met_id: str,
        id_type: str,
        stratum: str | None,
    ) -> tuple[bool, str | None]:
        """Return (excluded, exclusion_class) from the sidecar overlay."""
        if stratum is None or not self._exclusions:
            return False, None
        entry = self._exclusions.get(f"{stratum}|{id_type}|{met_id}")
        if entry is None:
            return False, None
        cls = entry.get("exclusion_class")
        excluded = cls == "non_single_structure"
        return excluded, cls

    def _struct_conn(self) -> sqlite3.Connection:
        """Fresh read-only connection to metanetx_struct.sqlite."""
        conn = sqlite3.connect(f"file:{self._struct_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _resolve_chain(
        self,
        cands: dict[str, str],
        met_id: str,
        id_type: str,
        stratum: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Run ChEBI → MNX struct → lastmile and return (smiles, inchikey, source)."""

        # Stage 1: local ChEBI
        smiles, inchikey = self._resolve_via_chebi(cands)
        if smiles:
            return smiles, inchikey, "chebi"

        # Stage 2: MetaNetX struct db
        smiles, inchikey = self._resolve_via_mnx(cands)
        if smiles:
            return smiles, inchikey, "mnx_struct"

        # Stage 3: lastmile overlay (only when stratum is given)
        if stratum is not None:
            key = f"{stratum}|{id_type}|{met_id}"
            lm_smiles = self._lastmile.get(key)
            if lm_smiles:
                return lm_smiles, None, "lastmile"

        return None, None, None

    def _resolve_via_chebi(
        self, cands: dict[str, str]
    ) -> tuple[str | None, str | None]:
        """Try ChEBI direct + xref lookups; return (smiles, inchikey) or (None, None)."""
        chebi_id = cands.get("CHEBI")
        if chebi_id:
            try:
                rec = self._chebi.get_compound(chebi_id)
            except (ValueError, TypeError):
                rec = None
            if rec and rec.smiles:
                return rec.smiles, rec.inchikey

        for ns in ("KEGG", "HMDB", "PUBCHEM", "LIPIDMAPS"):
            ext = cands.get(ns)
            if not ext:
                continue
            try:
                rec = self._chebi.lookup_by_xref(ns, ext)
            except Exception:
                rec = None
            if rec and rec.smiles:
                return rec.smiles, rec.inchikey

        return None, None

    def _resolve_via_mnx(
        self, cands: dict[str, str]
    ) -> tuple[str | None, str | None]:
        """Try MetaNetX struct db; return (smiles, inchikey) or (None, None)."""
        mnx_id = self._find_mnx(cands)
        if mnx_id is None:
            return None, None
        with self._struct_conn() as conn:
            row = conn.execute(
                "SELECT smiles, inchikey FROM mnx_structure WHERE mnx_id = ?",
                (mnx_id,),
            ).fetchone()
        if row and row["smiles"]:
            return row["smiles"], row["inchikey"] or None
        return None, None

    def _find_mnx(self, cands: dict[str, str]) -> str | None:
        """Determine MNX id from candidate xrefs using bigg_mnx + xref_mnx."""
        # Direct MNX
        mnx = cands.get("MNX")
        if mnx:
            return mnx

        with self._struct_conn() as conn:
            # BiGG → bigg_mnx table
            bigg = cands.get("BIGG")
            if bigg:
                row = conn.execute(
                    "SELECT mnx_id FROM bigg_mnx WHERE bigg_id = ?", (bigg,)
                ).fetchone()
                if row:
                    return row["mnx_id"]

            # KEGG / HMDB / LIPIDMAPS → xref_mnx table
            for ns in ("KEGG", "HMDB", "LIPIDMAPS"):
                ext = cands.get(ns)
                if not ext:
                    continue
                row = conn.execute(
                    "SELECT mnx_id FROM xref_mnx WHERE ns = ? AND ext_id = ?",
                    (ns, ext),
                ).fetchone()
                if row:
                    return row["mnx_id"]

        return None


# ── module-level helpers ───────────────────────────────────────────────────────

def _load_gem(
    gem_tsv: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Load Human-GEM metabolite annotation into two lookup dicts.

    Returns
    -------
    gem:
        {base_MAM_id: {namespace: ext_id, …}}
    bigg_index:
        {bigg_id: base_MAM_id}  (reverse index for Recon2.2 BiGG lookup)
    """
    gem: dict[str, dict[str, str]] = {}
    bigg_index: dict[str, str] = {}

    if not gem_tsv.exists():
        return gem, bigg_index

    with gem_tsv.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            mam = (row.get("mets") or "").strip()
            if not mam:
                continue
            # strip trailing lowercase compartment letter (e.g. "MAM01234c" → "MAM01234")
            base = mam[:-1] if mam[-1:].islower() else mam
            if base in gem:
                continue
            xrefs: dict[str, str] = {}
            for col, ns in _GEM_COL_TO_NS.items():
                raw = (row.get(col) or "").split(";")[0].strip()
                if raw.lower() not in ("", "na", "nan"):
                    xrefs[ns] = raw
            gem[base] = xrefs
            if xrefs.get("BIGG"):
                bigg_index.setdefault(xrefs["BIGG"], base)

    return gem, bigg_index


def _collect_cands(
    met_id: str,
    id_type: str,
    gem: dict[str, dict[str, str]],
    bigg_index: dict[str, str],
) -> dict[str, str]:
    """Collect candidate xref dict for (met_id, id_type).

    Rules:
    - KEGG/HMDB/ChEBI/PubChem  → single-entry dict keyed by canonical NS
    - Human1 (MAM id)          → GEM xref row for that MAM
    - Recon2.2 (BiGG slug)     → {BIGG: slug} + GEM back-lookup via bigg_index
    """
    if id_type == "Human1":
        return dict(gem.get(met_id, {}))

    if id_type == "Recon2.2":
        cands: dict[str, str] = {"BIGG": met_id}
        mam = bigg_index.get(met_id)
        if mam:
            for k, v in gem.get(mam, {}).items():
                cands.setdefault(k, v)
        return cands

    # Direct namespace
    ns = _ID_TYPE_TO_NS.get(id_type, id_type)
    return {ns: met_id}


def _inchikey_from_smiles(smiles: str) -> str | None:
    """Derive InChIKey from SMILES using RDKit; return None on failure."""
    if not _RDKIT_AVAILABLE:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        return Chem.inchi.MolToInchiKey(mol)
    except Exception:
        return None
