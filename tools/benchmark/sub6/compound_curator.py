"""Curate the RIKEN-Plant and HMDB-Mammalian compound subsets for Sub-6.

Two outputs:

* :func:`curate_riken_plant_subset` — RIKEN compounds suitable for
  Sub-6A (end-to-end MS/MS) and Sub-6B-Plant. Allows ``pfocr`` pathway
  annotations (RIKEN's anthocyanin/flavonoid coverage in RaMP is almost
  exclusively pfocr).
* :func:`curate_hmdb_mammalian_subset` — HMDB compounds with KEGG IDs
  for Sub-6B-Mammalian. Reads the pre-curated NPClassifier-stratified
  candidate file (300 compounds × 5 ``pathway_domain`` buckets); the
  300 already passed KEGG / RaMP-pathway gates upstream.

NPClassifier policy:
Both inputs (RIKEN pool + HMDB candidates) ship with a populated
``ground_truth.npclassifier`` field (or top-level ``npclassifier`` for
HMDB) carrying ``superclass[] / class_[] / pathway[] / isglycoside``.
``CuratedCompound`` exposes those four as first-class fields. The
``classyfire_class`` / ``classyfire_source`` fields are retained as a
back-compat shim — populated best-effort from NPClassifier (preferred)
or HMDB ``chemical_class`` (fallback).

CE filter (RIKEN-specific, see Q-CE in session brief):
RIKEN MassBank's normalizer outputs ``CE=6.0`` for the dominant
"Ramp 5-60 V" cohort and ``CE=None`` for explicit ramp annotations.
Filtering on ``CE >= 10`` strictly (per protocol §2.3) drops 99% of
RIKEN spectra. The compromise: per-spectrum gate is
``peaks >= require_peaks_min AND (CE >= require_ce_min OR ce_is_ramp)``,
where ``ce_is_ramp`` is detected from ``normalization_warnings``.
Default ``require_ce_min=5.0``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rdkit import Chem
from rdkit import RDLogger

from schemas.common import ToolError

logger = logging.getLogger(__name__)
RDLogger.DisableLog("rdApp.*")  # silence RDKit warnings on bad SMILES


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CurationError(ToolError):
    code = "CURATION_ERROR"
    recoverable = False


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


@dataclass
class CuratedCompound:
    """One curated compound. JSONL serializable via :meth:`to_json`."""

    name: str
    smiles: str
    inchikey: str
    inchikey_first_block: str
    molecular_formula: str
    exact_mass: float
    kegg_id: str | None
    hmdb_id: str | None
    pubchem_cid: int | None
    # NPClassifier (preferred): primary pathway/superclass/class + glycoside flag
    npc_pathway: str | None
    npc_superclass: str | None
    npc_class: str | None
    npc_isglycoside: bool | None
    # ClassyFire-compat fields (NPC-derived label or HMDB chemical_class)
    classyfire_class: str | None
    classyfire_source: str  # "npclassifier" | "hmdb_chemical_class" | "cache" | "missing"
    compound_class: str    # RIKEN-style class for plant set; pathway-bucket for mammalian
    pathway_bucket: str    # NPC pathway (plant) or mammalian bucket
    source: str             # "riken" | "hmdb"
    spectrum_ids: list[str] | None     # RIKEN: list of MSBNK accessions
    ramp_pathway_ids: list[str]
    ramp_pathway_names: list[str]
    ramp_pathway_sources: list[str]    # parallel to ramp_pathway_ids: kegg/pfocr/...

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class CurationStats:
    """Drop counts at each filter step + final composition stats."""

    input_size: int = 0
    after_dedup: int = 0
    after_quality: int = 0
    after_leakage: int = 0
    after_pathway: int = 0
    final: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    classyfire_source_counts: dict[str, int] = field(default_factory=dict)
    class_distribution: dict[str, int] = field(default_factory=dict)
    bucket_distribution: dict[str, int] = field(default_factory=dict)

    def bump(self, reason: str) -> None:
        self.drop_reasons[reason] = self.drop_reasons.get(reason, 0) + 1


# ---------------------------------------------------------------------------
# Pathway bucket taxonomy (mammalian)
#
# Substring matching against pathway.pathwayName. First match wins.
# Anything that doesn't match falls into "other_metabolism".
# ---------------------------------------------------------------------------


_MAMMALIAN_BUCKETS: list[tuple[str, list[str]]] = [
    ("central_metabolism", [
        "glycolysis", "gluconeogenesis", "tca cycle", "citric acid cycle",
        "citrate cycle", "krebs cycle", "pentose phosphate", "fructose and mannose",
        "starch and sucrose", "galactose metabolism", "pyruvate metabolism",
        "oxidative phosphorylation", "carbohydrate digestion",
    ]),
    ("lipid_metabolism", [
        "fatty acid", "beta-oxidation", "β-oxidation", "lipid metabolism",
        "phospholipid", "sphingolipid", "glycerophospholipid", "glycerolipid",
        "steroid biosynthesis", "cholesterol", "bile acid",
        "arachidonic acid", "linoleic acid", "ether lipid", "eicosanoid",
        "omega-3", "omega-6", "omega-9", "sterol", "oxysterol", "ceramide",
        "triacylglyceride", "triglyceride", "phosphoinositide",
    ]),
    ("nucleotide_metabolism", [
        "purine metabolism", "pyrimidine metabolism", "nucleotide", "nucleoside",
    ]),
    ("amino_acid_metabolism", [
        "amino acid", "alanine", "arginine", "asparagine", "aspartate",
        "cysteine", "glutamate", "glutamine", "glycine, serine and threonine",
        "histidine", "isoleucine", "leucine", "lysine", "methionine",
        "phenylalanine", "proline", "serine", "threonine", "tryptophan",
        "tyrosine", "valine", "urea cycle",
    ]),
]


def _classify_pathway_bucket(pathway_name: str) -> str:
    """Map a pathway name to one of the mammalian buckets."""
    name = (pathway_name or "").lower()
    for bucket, needles in _MAMMALIAN_BUCKETS:
        for needle in needles:
            if needle in name:
                return bucket
    return "other_metabolism"


# ---------------------------------------------------------------------------
# ClassyFire helper
# ---------------------------------------------------------------------------


def _open_classyfire_cache(path: Path | str | None) -> sqlite3.Connection | None:
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        logger.info("classyfire cache not found at %s — skipping", p)
        return None
    uri = f"file:{p.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _classyfire_lookup(
    conn: sqlite3.Connection | None,
    inchikey: str,
) -> tuple[str | None, str]:
    """Return (classyfire_class, source) tuple.

    Source is one of: "cache" (hit in classyfire_cache.sqlite) or "missing"
    (caller is expected to fallback to HMDB chemical_class).
    """
    if not conn or not inchikey:
        return None, "missing"
    try:
        cur = conn.execute(
            "SELECT response_json FROM classyfire_cache WHERE inchikey = ?",
            (inchikey,),
        )
        row = cur.fetchone()
    except sqlite3.OperationalError:
        return None, "missing"
    if row is None:
        return None, "missing"
    try:
        payload = json.loads(row["response_json"])
    except (json.JSONDecodeError, TypeError):
        return None, "missing"
    classifications = payload.get("all_classifications") or []
    if not classifications:
        return None, "missing"
    # Heuristic per session brief: " / ".join(all_classifications[:3])
    label = " / ".join(str(c) for c in classifications[:3] if c)
    return (label or None), ("cache" if label else "missing")


# ---------------------------------------------------------------------------
# RIKEN pool loading + grouping
# ---------------------------------------------------------------------------


@dataclass
class _RikenSpectrumLite:
    """Minimal per-spectrum fields needed for curation filters."""

    accession: str
    n_peaks: int
    collision_energy: float | None
    ce_is_ramp: bool
    ion_mode: str | None


@dataclass
class _NpcLabels:
    pathway: str | None = None
    superclass: str | None = None
    class_: str | None = None
    isglycoside: bool | None = None


@dataclass
class _RikenCompound:
    """One RIKEN compound aggregated from all its spectra."""

    inchikey: str
    inchikey_first_block: str
    name: str
    smiles: str
    molecular_formula: str
    exact_mass: float
    pubchem_cid: int | None
    compound_class: str
    npc: _NpcLabels
    spectra: list[_RikenSpectrumLite]


def _norm_warnings_say_ramp(warnings: list[str] | None) -> bool:
    if not warnings:
        return False
    needles = ("ramp", "stepwave")
    return any(any(n in (w or "").lower() for n in needles) for w in warnings)


def _extract_npc(payload: dict | None) -> _NpcLabels:
    """Extract NPClassifier primary labels from the response dict."""
    if not isinstance(payload, dict):
        return _NpcLabels()

    def _first(key: str) -> str | None:
        v = payload.get(key)
        if isinstance(v, list) and v:
            return str(v[0])
        if isinstance(v, str) and v:
            return v
        return None

    return _NpcLabels(
        pathway=_first("pathway"),
        superclass=_first("superclass"),
        class_=_first("class_"),
        isglycoside=payload.get("isglycoside") if isinstance(payload.get("isglycoside"), bool) else None,
    )


def _load_riken_pool(path: Path | str) -> list[_RikenCompound]:
    """Read the RIKEN spectrum JSONL and group by InChIKey first-block.

    Accepts both the original ``compound_pool_riken.jsonl`` shape and the
    NPClassifier-augmented shape (``ground_truth.npclassifier``).
    """
    grouped: dict[str, _RikenCompound] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            gt = r.get("ground_truth") or {}
            ikey = (gt.get("inchikey") or "").strip()
            if len(ikey) < 14:
                continue
            first = ikey[:14]
            sp = r.get("spectrum") or {}
            ce = sp.get("collision_energy")
            mz = sp.get("mz") or []
            md = r.get("metadata") or {}
            acc = md.get("accession") or ""
            if not acc:
                continue
            warns = r.get("normalization_warnings") or []

            spectrum_lite = _RikenSpectrumLite(
                accession=acc,
                n_peaks=len(mz),
                collision_energy=float(ce) if isinstance(ce, (int, float)) else None,
                ce_is_ramp=_norm_warnings_say_ramp(warns),
                ion_mode=sp.get("ionization_mode"),
            )

            existing = grouped.get(first)
            if existing is None:
                grouped[first] = _RikenCompound(
                    inchikey=ikey,
                    inchikey_first_block=first,
                    name=gt.get("primary_compound_name") or (gt.get("compound_names") or [first])[0],
                    smiles=gt.get("smiles") or "",
                    molecular_formula=gt.get("molecular_formula") or "",
                    exact_mass=float(gt.get("exact_mass") or 0.0),
                    pubchem_cid=gt.get("pubchem_cid"),
                    compound_class=gt.get("compound_class") or "other",
                    npc=_extract_npc(gt.get("npclassifier")),
                    spectra=[spectrum_lite],
                )
            else:
                existing.spectra.append(spectrum_lite)
    logger.info("riken: loaded %d unique compounds from %s", len(grouped), path)
    return list(grouped.values())


# ---------------------------------------------------------------------------
# RaMP queries (curation-internal; reuses the same db connection)
# ---------------------------------------------------------------------------


def _open_ramp_ro(path: Path | str) -> sqlite3.Connection:
    p = Path(path)
    if not p.is_file():
        raise CurationError(f"RaMP DB not found: {p}")
    uri = f"file:{p.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _open_hmdb_ro(path: Path | str) -> sqlite3.Connection:
    p = Path(path)
    if not p.is_file():
        raise CurationError(f"HMDB DB not found: {p}")
    uri = f"file:{p.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _resolve_inchikeys_batch(
    conn: sqlite3.Connection, inchikeys: list[str],
) -> dict[str, set[str]]:
    """Map full InChIKey or first-block → set of ramp_compound_ids."""
    out: dict[str, set[str]] = {}
    chunk = 500
    for i in range(0, len(inchikeys), chunk):
        batch = inchikeys[i : i + chunk]
        full_keys = [k for k in batch if len(k) >= 27]
        first_blocks = [k for k in batch if len(k) < 27]
        if full_keys:
            ph = ",".join("?" for _ in full_keys)
            cur = conn.execute(
                f"SELECT inchi_key, ramp_id FROM chem_props WHERE inchi_key IN ({ph})",
                full_keys,
            )
            for row in cur:
                if row["ramp_id"]:
                    out.setdefault(row["inchi_key"], set()).add(row["ramp_id"])
        if first_blocks:
            ph = ",".join("?" for _ in first_blocks)
            cur = conn.execute(
                f"SELECT inchi_key_prefix, ramp_id FROM chem_props "
                f"WHERE inchi_key_prefix IN ({ph})",
                first_blocks,
            )
            for row in cur:
                if row["ramp_id"]:
                    out.setdefault(row["inchi_key_prefix"], set()).add(row["ramp_id"])
    return out


def _resolve_kegg_batch(
    conn: sqlite3.Connection, kegg_ids: list[str],
) -> dict[str, set[str]]:
    """Map KEGG compound ID → set of ramp_compound_ids."""
    out: dict[str, set[str]] = {}
    candidates_to_inputs: dict[str, str] = {}
    for k in kegg_ids:
        candidates_to_inputs[f"kegg:{k}"] = k
        candidates_to_inputs[k] = k  # rare bare-id rows
    cands = list(candidates_to_inputs.keys())
    chunk = 500
    for i in range(0, len(cands), chunk):
        batch = cands[i : i + chunk]
        ph = ",".join("?" for _ in batch)
        cur = conn.execute(
            f"SELECT sourceId, rampId FROM source "
            f"WHERE sourceId IN ({ph}) AND geneOrCompound='compound'",
            batch,
        )
        for row in cur:
            iid = candidates_to_inputs[row["sourceId"]]
            if row["rampId"]:
                out.setdefault(iid, set()).add(row["rampId"])
    return out


def _pathways_for_ramp_ids(
    conn: sqlite3.Connection,
    ramp_ids: Iterable[str],
    *,
    excluded_types: tuple[str, ...] = (),
) -> dict[str, list[dict]]:
    """For each ramp_id, return a list of {pid, name, type, sourceId} dicts.

    Excludes pathways whose type is in ``excluded_types``.
    """
    ramp_list = list({r for r in ramp_ids if r})
    if not ramp_list:
        return {}
    out: dict[str, list[dict]] = defaultdict(list)
    chunk = 500
    type_filter = ""
    type_args: list[str] = []
    if excluded_types:
        ph = ",".join("?" for _ in excluded_types)
        type_filter = f" AND p.type NOT IN ({ph})"
        type_args = list(excluded_types)
    for i in range(0, len(ramp_list), chunk):
        batch = ramp_list[i : i + chunk]
        ph = ",".join("?" for _ in batch)
        sql = (
            "SELECT ahp.rampId AS rid, p.pathwayRampId AS pid, "
            "       p.pathwayName AS name, p.type AS type, p.sourceId AS sid "
            "FROM analytehaspathway ahp "
            "JOIN pathway p ON p.pathwayRampId = ahp.pathwayRampId "
            f"WHERE ahp.rampId IN ({ph}){type_filter}"
        )
        cur = conn.execute(sql, [*batch, *type_args])
        for row in cur:
            out[row["rid"]].append({
                "pid": row["pid"],
                "name": row["name"] or "",
                "type": (row["type"] or "").strip(),
                "sourceId": row["sid"] or "",
            })
    return out


# ---------------------------------------------------------------------------
# Public: RIKEN-Plant curation
# ---------------------------------------------------------------------------


def curate_riken_plant_subset(
    riken_pool_path: Path | str,
    leakage_excluded_ids_path: Path | str | None,
    *,
    ramp_db_path: Path | str,
    hmdb_db_path: Path | str | None = None,
    classyfire_cache_path: Path | str | None = None,
    require_peaks_min: int = 30,
    require_ce_min: float = 5.0,  # see Q-CE: RIKEN normalizer outputs CE=6.0 for ramp data
    allow_ce_none_if_ramp: bool = True,
    require_ramp_pathway: bool = True,
    pathway_min_compounds: int = 5,
    excluded_pathway_types: tuple[str, ...] = (),  # plant: allow pfocr
    target_size: int = 150,
    require_classyfire: bool = False,
    min_classes_represented: int = 4,
) -> tuple[list[CuratedCompound], CurationStats]:
    """Curate RIKEN compounds suitable for Sub-6A and Sub-6B-Plant.

    Filters in order; every drop is counted in :class:`CurationStats`.
    The leakage filter exclusion list (NM-002) is consumed for audit
    purposes only — no compounds are dropped on its account (per the
    "loose" semantics chosen in session Q2).
    """
    stats = CurationStats()
    compounds = _load_riken_pool(riken_pool_path)
    stats.input_size = sum(len(c.spectra) for c in compounds)  # spectra count
    stats.after_dedup = len(compounds)

    # Step 1: spectrum-quality filter
    #   peaks >= require_peaks_min AND
    #   ((CE != None AND CE >= require_ce_min) OR (allow_ce_none_if_ramp AND ce_is_ramp))
    quality_passed: list[_RikenCompound] = []
    for c in compounds:
        good = []
        for s in c.spectra:
            if s.n_peaks < require_peaks_min:
                continue
            if s.collision_energy is not None and s.collision_energy >= require_ce_min:
                good.append(s)
            elif allow_ce_none_if_ramp and s.ce_is_ramp:
                good.append(s)
        if good:
            c.spectra = good
            quality_passed.append(c)
        else:
            stats.bump("no_qualifying_spectrum")
    stats.after_quality = len(quality_passed)

    # Step 2: leakage filter — record only, don't drop (Q2-b)
    leaked_lookup: set[str] = set()
    if leakage_excluded_ids_path:
        try:
            with open(leakage_excluded_ids_path, encoding="utf-8") as f:
                payload = json.load(f)
            leaked_lookup = set(payload.get("excluded_ids") or [])
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "could not load leakage exclusion file at %s",
                leakage_excluded_ids_path,
            )
    n_potentially_leaked = sum(
        1 for c in quality_passed
        if any(s.accession in leaked_lookup for s in c.spectra)
    )
    stats.after_leakage = stats.after_quality  # no drops; just audit metric
    stats.drop_reasons["_leakage_audit_potentially_leaked"] = n_potentially_leaked

    # Step 3: RaMP pathway resolution
    ramp_conn = _open_ramp_ro(ramp_db_path)
    try:
        full_keys = [c.inchikey for c in quality_passed]
        ikey_to_ramp = _resolve_inchikeys_batch(ramp_conn, full_keys)
        # Fallback to first-block for compounds that didn't resolve fully
        first_blocks_to_lookup = [
            c.inchikey_first_block for c in quality_passed
            if c.inchikey not in ikey_to_ramp
        ]
        prefix_to_ramp = _resolve_inchikeys_batch(ramp_conn, first_blocks_to_lookup)

        # Build per-compound ramp_ids
        compound_ramp_ids: dict[str, set[str]] = {}
        for c in quality_passed:
            ramps = ikey_to_ramp.get(c.inchikey) or set()
            if not ramps:
                ramps = prefix_to_ramp.get(c.inchikey_first_block) or set()
            if ramps:
                compound_ramp_ids[c.inchikey_first_block] = ramps

        # Pathway membership
        all_ramp_ids = set().union(*compound_ramp_ids.values()) if compound_ramp_ids else set()
        ramp_to_pathways = _pathways_for_ramp_ids(
            ramp_conn, all_ramp_ids, excluded_types=excluded_pathway_types,
        )
    finally:
        ramp_conn.close()

    # Step 4: ≥1 pathway (after type filter)
    pathway_passed: list[tuple[_RikenCompound, set[str], list[dict]]] = []
    for c in quality_passed:
        ramps = compound_ramp_ids.get(c.inchikey_first_block, set())
        if not ramps:
            stats.bump("no_ramp_resolution")
            continue
        pathways: list[dict] = []
        seen_pids: set[str] = set()
        for r in ramps:
            for pw in ramp_to_pathways.get(r, []):
                if pw["pid"] not in seen_pids:
                    seen_pids.add(pw["pid"])
                    pathways.append(pw)
        if require_ramp_pathway and not pathways:
            stats.bump("no_ramp_pathway")
            continue
        pathway_passed.append((c, ramps, pathways))

    # Step 5: ≥pathway_min_compounds peers in at least one pathway
    # Build pathway → set of inchikey_first_blocks (within current candidate pool)
    pathway_members: dict[str, set[str]] = defaultdict(set)
    for c, _ramps, pathways in pathway_passed:
        for pw in pathways:
            pathway_members[pw["pid"]].add(c.inchikey_first_block)

    qualifying_pathways = {
        pid for pid, members in pathway_members.items()
        if len(members) >= pathway_min_compounds
    }
    pathway_qualified: list[tuple[_RikenCompound, set[str], list[dict]]] = []
    for c, ramps, pathways in pathway_passed:
        if any(pw["pid"] in qualifying_pathways for pw in pathways):
            pathway_qualified.append((c, ramps, pathways))
        else:
            stats.bump("pathway_too_small")
    stats.after_pathway = len(pathway_qualified)

    # Step 6: stratified down-sampling to target_size, ensuring ≥min_classes
    classyfire_conn = _open_classyfire_cache(classyfire_cache_path)
    hmdb_conn = _open_hmdb_ro(hmdb_db_path) if hmdb_db_path else None
    try:
        curated: list[CuratedCompound] = []
        # Stratify by NPC pathway (falls back to RIKEN compound_class if NPC empty)
        by_class: dict[str, list[tuple]] = defaultdict(list)
        for tup in pathway_qualified:
            riken_compound = tup[0]
            key = riken_compound.npc.pathway or riken_compound.compound_class or "other"
            by_class[key].append(tup)

        n_classes = len(by_class)
        if n_classes == 0:
            return curated, stats
        # Round-robin pick to guarantee diversity
        order = sorted(by_class.keys(), key=lambda k: -len(by_class[k]))
        # Sort within class by spectrum count desc for richer pickings
        for k in order:
            by_class[k].sort(key=lambda tup: -len(tup[0].spectra))

        picked_count = 0
        round_idx = 0
        # Round-robin until we hit target_size or run out
        while picked_count < target_size:
            advanced = False
            for k in order:
                if round_idx < len(by_class[k]):
                    tup = by_class[k][round_idx]
                    cc = _build_curated_riken(
                        tup, classyfire_conn=classyfire_conn,
                        hmdb_conn=hmdb_conn, leaked_lookup=leaked_lookup,
                    )
                    curated.append(cc)
                    picked_count += 1
                    advanced = True
                    if picked_count >= target_size:
                        break
            if not advanced:
                break
            round_idx += 1
    finally:
        if classyfire_conn:
            classyfire_conn.close()
        if hmdb_conn:
            hmdb_conn.close()

    stats.final = len(curated)
    stats.classyfire_source_counts = dict(Counter(c.classyfire_source for c in curated))
    stats.class_distribution = dict(Counter(c.compound_class for c in curated))
    stats.bucket_distribution = dict(Counter(c.pathway_bucket for c in curated))
    return curated, stats


def _build_curated_riken(
    tup: tuple[_RikenCompound, set[str], list[dict]],
    *,
    classyfire_conn: sqlite3.Connection | None,
    hmdb_conn: sqlite3.Connection | None,
    leaked_lookup: set[str],
) -> CuratedCompound:
    c, _ramps, pathways = tup
    # NPClassifier (preferred) → cache → HMDB chemical_class → None
    cf_label: str | None = None
    cf_source = "missing"
    npc_parts = [v for v in (c.npc.superclass, c.npc.class_, c.npc.pathway) if v]
    if npc_parts:
        cf_label = " / ".join(npc_parts)
        cf_source = "npclassifier"
    else:
        cached_label, _ = _classyfire_lookup(classyfire_conn, c.inchikey)
        if cached_label:
            cf_label = cached_label
            cf_source = "cache"

    kegg_id: str | None = None
    hmdb_id: str | None = None
    if hmdb_conn is not None:
        try:
            cur = hmdb_conn.execute(
                "SELECT hmdb_id, kegg_id, chemical_class "
                "FROM metabolites WHERE inchikey = ? LIMIT 1",
                (c.inchikey,),
            )
            row = cur.fetchone()
            if row:
                hmdb_id = row["hmdb_id"]
                kegg_id = row["kegg_id"] or None
                if cf_source == "missing" and row["chemical_class"]:
                    cf_label = row["chemical_class"]
                    cf_source = "hmdb_chemical_class"
        except sqlite3.OperationalError:
            pass

    # Spectrum_ids: only the qualifying ones (already narrowed)
    spectrum_ids = [s.accession for s in c.spectra]
    if any(s.accession in leaked_lookup for s in c.spectra):
        logger.debug("riken: %s has GNPS-leaked spectra", c.inchikey_first_block)

    # Stratification key: NPC pathway if present, else compound_class
    pathway_bucket = c.npc.pathway or c.compound_class or "other"

    return CuratedCompound(
        name=c.name,
        smiles=c.smiles,
        inchikey=c.inchikey,
        inchikey_first_block=c.inchikey_first_block,
        molecular_formula=c.molecular_formula,
        exact_mass=c.exact_mass,
        kegg_id=kegg_id,
        hmdb_id=hmdb_id,
        pubchem_cid=c.pubchem_cid,
        npc_pathway=c.npc.pathway,
        npc_superclass=c.npc.superclass,
        npc_class=c.npc.class_,
        npc_isglycoside=c.npc.isglycoside,
        classyfire_class=cf_label,
        classyfire_source=cf_source,
        compound_class=c.compound_class,
        pathway_bucket=pathway_bucket,
        source="riken",
        spectrum_ids=spectrum_ids,
        ramp_pathway_ids=[pw["pid"] for pw in pathways],
        ramp_pathway_names=[pw["name"] for pw in pathways],
        ramp_pathway_sources=[pw["type"] for pw in pathways],
    )


# ---------------------------------------------------------------------------
# Public: HMDB-Mammalian curation
# ---------------------------------------------------------------------------


def curate_hmdb_mammalian_subset(
    *,
    candidates_jsonl_path: Path | str,
    ramp_db_path: Path | str,
    classyfire_cache_path: Path | str | None = None,
    require_ramp_pathway: bool = True,
    pathway_min_compounds: int = 5,
    excluded_pathway_types: tuple[str, ...] = ("pfocr",),
    target_size: int = 150,
    enable_lipidmaps: bool = False,
    lipidmaps_lmsd_path: Path | str | None = None,
    lipidmaps_pathway_path: Path | str | None = None,
) -> tuple[list[CuratedCompound], CurationStats]:
    """Curate HMDB compounds for Sub-6B-Mammalian.

    Reads from the pre-curated NPClassifier-stratified candidate JSONL
    (typically ``data/processed/hmdb_candidates_npc_classified.jsonl``).
    Each input record has already passed:
      * KEGG ID present
      * SMILES present
      * RaMP pathway annotation present
      * stratified across 5 ``pathway_domain`` buckets (60 each)

    This function only re-validates SMILES (RDKit) + re-resolves RaMP
    pathways with the requested ``excluded_pathway_types`` filter (so
    Mammalian gets pfocr-free ground truth), then round-robin samples
    to ``target_size``.
    """
    stats = CurationStats()

    # Step 1: load candidates from JSONL
    candidates: list[dict] = []
    with open(candidates_jsonl_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            candidates.append(json.loads(line))
    stats.input_size = len(candidates)

    # Step 2: SMILES validity + first-block dedup
    seen_first: set[str] = set()
    valid_rows: list[dict] = []
    for r in candidates:
        smi = r.get("smiles") or ""
        if not smi:
            stats.bump("missing_smiles")
            continue
        try:
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                stats.bump("smiles_unparseable")
                continue
        except Exception:  # noqa: BLE001
            stats.bump("smiles_unparseable")
            continue
        first = (r.get("inchikey") or "")[:14]
        if not first:
            stats.bump("missing_inchikey")
            continue
        if first in seen_first:
            stats.bump("dedup_first_block")
            continue
        seen_first.add(first)
        r["_first"] = first
        valid_rows.append(r)
    stats.after_quality = len(valid_rows)
    stats.after_dedup = len(valid_rows)
    stats.after_leakage = stats.after_dedup  # n/a for HMDB

    # Step 3: re-resolve RaMP pathways with requested excluded_types filter.
    # The candidates carry ``pathway_names`` from upstream curation, but those
    # were collected without our pfocr exclusion policy — we need RaMP IDs.
    ramp_conn = _open_ramp_ro(ramp_db_path)
    try:
        kegg_inputs = [r["kegg_id"] for r in valid_rows if r.get("kegg_id")]
        kegg_to_ramp = _resolve_kegg_batch(ramp_conn, kegg_inputs)
        unresolved_keys = [
            r["inchikey"] for r in valid_rows
            if not (r.get("kegg_id") and r.get("kegg_id") in kegg_to_ramp)
        ]
        ikey_to_ramp = _resolve_inchikeys_batch(ramp_conn, unresolved_keys)

        compound_ramp_ids: dict[str, set[str]] = {}
        for r in valid_rows:
            ramps: set[str] = set()
            if r.get("kegg_id"):
                ramps |= kegg_to_ramp.get(r["kegg_id"], set())
            if not ramps:
                ramps |= ikey_to_ramp.get(r.get("inchikey"), set())
            if ramps:
                compound_ramp_ids[r["_first"]] = ramps

        all_ramps = set().union(*compound_ramp_ids.values()) if compound_ramp_ids else set()
        ramp_to_pathways = _pathways_for_ramp_ids(
            ramp_conn, all_ramps, excluded_types=excluded_pathway_types,
        )
    finally:
        ramp_conn.close()

    lipidmaps_client = None
    if enable_lipidmaps:
        if lipidmaps_lmsd_path is None or lipidmaps_pathway_path is None:
            raise ValueError(
                "enable_lipidmaps requires lipidmaps_lmsd_path and "
                "lipidmaps_pathway_path"
            )
        from tools.lipidmaps import LipidMapsClient
        lipidmaps_client = LipidMapsClient(lipidmaps_lmsd_path, lipidmaps_pathway_path)

    # Step 4: pathway gate
    candidate_with_pathways: list[tuple[dict, list[dict]]] = []
    for r in valid_rows:
        ramps = compound_ramp_ids.get(r["_first"], set())
        is_lipid_bucket = (r.get("pathway_domain") == "lipid_metabolism")
        if not ramps and not (lipidmaps_client and is_lipid_bucket):
            stats.bump("no_ramp_resolution")
            continue
        pathways: list[dict] = []
        seen_pids: set[str] = set()
        for rid in ramps:
            for pw in ramp_to_pathways.get(rid, []):
                if pw["pid"] not in seen_pids:
                    seen_pids.add(pw["pid"])
                    pathways.append(pw)
        if lipidmaps_client and is_lipid_bucket:
            for lpw in lipidmaps_client.lookup_compound_to_pathways(r.get("inchikey") or ""):
                pid = lpw.get("id")
                if not pid or pid in seen_pids:
                    continue
                seen_pids.add(pid)
                pathways.append({
                    "pid": pid,
                    "name": lpw.get("name") or pid,
                    "type": "lipidmaps",
                    "sourceId": lpw.get("external_id") or pid.removeprefix("lm_pathway:"),
                })
        if require_ramp_pathway and not pathways:
            stats.bump("no_ramp_pathway")
            continue
        candidate_with_pathways.append((r, pathways))

    # ≥pathway_min_compounds peers in at least one pathway
    pathway_members: dict[str, set[str]] = defaultdict(set)
    for r, pathways in candidate_with_pathways:
        for pw in pathways:
            pathway_members[pw["pid"]].add(r["_first"])
    qualifying_pathways = {
        pid for pid, members in pathway_members.items()
        if len(members) >= pathway_min_compounds
    }
    pathway_qualified: list[tuple[dict, list[dict]]] = []
    for r, pathways in candidate_with_pathways:
        if any(pw["pid"] in qualifying_pathways for pw in pathways):
            pathway_qualified.append((r, pathways))
        else:
            stats.bump("pathway_too_small")
    stats.after_pathway = len(pathway_qualified)

    # Step 5: bucket from ``pathway_domain`` field (already stratified upstream)
    by_bucket: dict[str, list[tuple[dict, list[dict], str]]] = defaultdict(list)
    for r, pathways in pathway_qualified:
        bucket = r.get("pathway_domain") or "other_metabolism"
        by_bucket[bucket].append((r, pathways, bucket))

    classyfire_conn = _open_classyfire_cache(classyfire_cache_path)
    try:
        curated: list[CuratedCompound] = []
        buckets_sorted = sorted(by_bucket.keys(), key=lambda b: -len(by_bucket[b]))
        for b in buckets_sorted:
            by_bucket[b].sort(key=lambda t: (t[0].get("exact_mass") or 0.0, t[0].get("hmdb_id", "")))

        round_idx = 0
        while len(curated) < target_size:
            advanced = False
            for b in buckets_sorted:
                if round_idx < len(by_bucket[b]):
                    cc = _build_curated_hmdb(by_bucket[b][round_idx], classyfire_conn=classyfire_conn)
                    curated.append(cc)
                    advanced = True
                    if len(curated) >= target_size:
                        break
            if not advanced:
                break
            round_idx += 1
    finally:
        if classyfire_conn:
            classyfire_conn.close()

    stats.final = len(curated)
    stats.classyfire_source_counts = dict(Counter(c.classyfire_source for c in curated))
    stats.class_distribution = dict(Counter(c.compound_class for c in curated))
    stats.bucket_distribution = dict(Counter(c.pathway_bucket for c in curated))
    return curated, stats


def _build_curated_hmdb(
    tup: tuple[dict, list[dict], str],
    *,
    classyfire_conn: sqlite3.Connection | None,
) -> CuratedCompound:
    r, pathways, bucket = tup
    npc_payload = r.get("npclassifier") or {}
    npc = _extract_npc(npc_payload)

    cf_label: str | None = None
    cf_source = "missing"
    npc_parts = [v for v in (npc.superclass, npc.class_, npc.pathway) if v]
    if npc_parts:
        cf_label = " / ".join(npc_parts)
        cf_source = "npclassifier"
    elif r.get("chemical_class"):
        cf_label = r["chemical_class"]
        cf_source = "hmdb_chemical_class"
    elif classyfire_conn:
        cached_label, _ = _classyfire_lookup(classyfire_conn, r.get("inchikey", ""))
        if cached_label:
            cf_label = cached_label
            cf_source = "cache"

    pubchem_cid = None
    raw = r.get("pubchem_cid")
    if raw:
        try:
            pubchem_cid = int(str(raw).strip())
        except (TypeError, ValueError):
            pubchem_cid = None
    return CuratedCompound(
        name=r.get("primary_name") or r.get("hmdb_id") or "",
        smiles=r.get("smiles") or "",
        inchikey=r.get("inchikey") or "",
        inchikey_first_block=r["_first"],
        molecular_formula=r.get("molecular_formula") or "",
        exact_mass=float(r.get("exact_mass") or 0.0),
        kegg_id=r.get("kegg_id") or None,
        hmdb_id=r.get("hmdb_id"),
        pubchem_cid=pubchem_cid,
        npc_pathway=npc.pathway,
        npc_superclass=npc.superclass,
        npc_class=npc.class_,
        npc_isglycoside=npc.isglycoside,
        classyfire_class=cf_label,
        classyfire_source=cf_source,
        compound_class=bucket,  # for HMDB, compound_class = pathway bucket
        pathway_bucket=bucket,
        source="hmdb",
        spectrum_ids=None,
        ramp_pathway_ids=[pw["pid"] for pw in pathways],
        ramp_pathway_names=[pw["name"] for pw in pathways],
        ramp_pathway_sources=[pw["type"] for pw in pathways],
    )


# ---------------------------------------------------------------------------
# Save + audit
# ---------------------------------------------------------------------------


def save_curated_subsets(
    riken_subset: list[CuratedCompound],
    hmdb_subset: list[CuratedCompound],
    output_dir: Path | str,
    *,
    riken_stats: CurationStats | None = None,
    hmdb_stats: CurationStats | None = None,
) -> dict[str, Path]:
    """Write JSONL subsets + curation_audit.md. Returns paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    riken_path = out / "curated_riken_plant.jsonl"
    hmdb_path = out / "curated_hmdb_mammalian.jsonl"
    audit_path = out / "curation_audit.md"

    _write_jsonl(riken_path, riken_subset)
    _write_jsonl(hmdb_path, hmdb_subset)

    audit_path.write_text(
        _render_audit(riken_subset, hmdb_subset, riken_stats, hmdb_stats),
        encoding="utf-8",
    )
    return {"riken": riken_path, "hmdb": hmdb_path, "audit": audit_path}


def _write_jsonl(path: Path, compounds: list[CuratedCompound]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for c in compounds:
            f.write(json.dumps(c.to_json(), ensure_ascii=False))
            f.write("\n")


def _render_audit(
    riken: list[CuratedCompound],
    hmdb: list[CuratedCompound],
    riken_stats: CurationStats | None,
    hmdb_stats: CurationStats | None,
) -> str:
    def _section(title: str, subset: list[CuratedCompound], stats: CurationStats | None) -> str:
        lines = [f"## {title}", ""]
        lines.append(f"- Final compounds: **{len(subset)}**")
        if stats is not None:
            lines.append(f"- Input size: {stats.input_size}")
            lines.append(f"- After dedup (first-block): {stats.after_dedup}")
            lines.append(f"- After spectrum-quality filter: {stats.after_quality}")
            lines.append(f"- After leakage audit (no drops): {stats.after_leakage}")
            lines.append(f"- After pathway filter: {stats.after_pathway}")
            lines.append("- Drop reasons:")
            for k, v in sorted(stats.drop_reasons.items()):
                lines.append(f"  - `{k}`: {v}")
            lines.append("- ClassyFire source distribution:")
            for k, v in sorted(stats.classyfire_source_counts.items()):
                lines.append(f"  - `{k}`: {v}")
            lines.append("- Compound-class distribution:")
            for k, v in sorted(stats.class_distribution.items(), key=lambda x: -x[1]):
                lines.append(f"  - `{k}`: {v}")
            lines.append("- Pathway-bucket distribution:")
            for k, v in sorted(stats.bucket_distribution.items(), key=lambda x: -x[1]):
                lines.append(f"  - `{k}`: {v}")
        lines.append("")
        return "\n".join(lines)

    out = ["# Sub-6 curation audit", ""]
    out.append(_section("RIKEN-Plant subset", riken, riken_stats))
    out.append(_section("HMDB-Mammalian subset", hmdb, hmdb_stats))
    return "\n".join(out)
