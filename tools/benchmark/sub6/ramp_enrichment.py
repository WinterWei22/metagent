"""RaMP-DB hypergeometric pathway enrichment for Sub-6 ground truth.

This module is the **single source of truth** for pathway enrichment results
used in Sub-6 task ground truth. Both Sub-6A (end-to-end) and Sub-6B
(compound-only) tasks consult :func:`compute_enrichment` to compute the
ground-truth pathway ranking against which LLM narratives will later be
evaluated.

Hypergeometric model
--------------------
For each pathway P in RaMP-DB::

    N = total compounds in RaMP background (with ≥1 pathway annotation)
    K = compounds in pathway P
    n = input compounds successfully resolved to RaMP
    k = input compounds that also belong to P

    p_value = scipy.stats.hypergeom.sf(k - 1, N, K, n)

Multiple-testing correction is Benjamini-Hochberg across all pathways
that have ≥1 input hit. Pathways with k = 0 do not contribute to the
multiple-testing burden (they are not "tested").

Pathway-source filter
---------------------
RaMP-DB ``pathway.type`` includes ``pfocr`` (~69k pathways auto-extracted
from figure OCR) which is too noisy for benchmark ground truth. By
default we exclude ``pfocr`` from both the test set and the background
size. Override via ``excluded_pathway_types``.

Caching
-------
First call against a given ``(db_path, excluded_types)`` performs two
aggregate queries (background size + per-pathway compound counts).
Results are cached in a module-level dict, so subsequent calls
(e.g. constructing 50 tasks back-to-back) reuse the same aggregation.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from scipy.stats import hypergeom

from schemas.common import ToolError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAMP_ENV_VAR = "RAMP_DB_PATH"

# RaMP pathway.type values that are *actionable* for ground truth.
# pfocr (Pathway Figure OCR) is excluded by default; it's noisy.
_DEFAULT_EXCLUDED_TYPES: tuple[str, ...] = ("pfocr",)

# RaMP source-table prefixes per id_type
_ID_TYPE_PREFIXES: dict[str, tuple[str, ...]] = {
    "kegg":     ("kegg",),
    "hmdb":     ("hmdb",),
}

# pathway.type → benchmark-facing source label
_TYPE_TO_SOURCE: dict[str, str] = {
    "kegg":     "kegg",
    "reactome": "reactome",
    "wiki":     "wikipathways",
    "hmdb":     "smpdb",  # RaMP stores SMPDB pathways under type='hmdb'
}

# All known RaMP pathway.type values (source labels map back via _TYPE_TO_SOURCE;
# pfocr is figure-OCR noise, always excluded).
_ALL_PATHWAY_TYPES: frozenset[str] = frozenset(_TYPE_TO_SOURCE) | {"pfocr"}
# source label → pathway.type (reverse of _TYPE_TO_SOURCE)
_SOURCE_TO_TYPE: dict[str, str] = {v: k for k, v in _TYPE_TO_SOURCE.items()}


def _sources_to_excluded_types(sources: Iterable[str]) -> tuple[str, ...]:
    """Translate INCLUDE-semantics source labels → excluded ``pathway.type`` list.

    LLM-facing API uses source labels (``"kegg"`` / ``"reactome"`` /
    ``"wikipathways"`` / ``"smpdb"``); the enrichment core filters by
    ``excluded_pathway_types``. Requesting ``["kegg"]`` therefore excludes
    every other type (incl. always-noisy ``pfocr``), so only KEGG canonical
    metabolic pathways are returned. Unknown labels are ignored.
    """
    wanted_types = {
        _SOURCE_TO_TYPE[s.strip().lower()]
        for s in sources
        if s and s.strip().lower() in _SOURCE_TO_TYPE
    }
    return tuple(sorted(_ALL_PATHWAY_TYPES - wanted_types))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EnrichmentError(ToolError):
    """Unrecoverable error during enrichment computation."""

    code = "RAMP_ENRICHMENT_ERROR"
    recoverable = False


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EnrichmentResult:
    """One pathway's enrichment result for a single input compound set."""

    pathway_id: str               # RaMP internal pathwayRampId
    pathway_name: str
    pathway_source: str           # "kegg" | "reactome" | "wikipathways" | "smpdb"
    pathway_external_id: str | None  # e.g. "C00031" (kegg), "SMP0000038" (smpdb)
    total_pathway_compounds: int  # K
    matched_compounds: list[str]  # input IDs that matched this pathway
    p_value: float
    fdr: float
    fold_enrichment: float

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class EnrichmentReport:
    """Output of :func:`compute_enrichment` for one input compound set."""

    input_compounds: list[str]                     # input identifiers, deduped
    resolved_compounds: list[str]                  # subset that mapped to ≥1 ramp_id
    unresolved_compounds: list[str]                # input IDs that didn't resolve
    background_size: int                            # N
    n_input_resolved: int                          # n
    top_pathways: list[EnrichmentResult]            # sorted by FDR ascending
    ramp_snapshot_date: str
    excluded_pathway_types: list[str]
    fdr_threshold: float

    def to_json(self) -> dict:
        d = asdict(self)
        d["top_pathways"] = [r.to_json() if isinstance(r, EnrichmentResult) else r
                             for r in self.top_pathways]
        return d


# ---------------------------------------------------------------------------
# Path / connection plumbing
# ---------------------------------------------------------------------------


def resolve_db_path(explicit: str | os.PathLike | None = None) -> Path:
    """Resolve RaMP DB path: explicit > env > error."""
    if explicit is not None:
        p = Path(explicit)
        if not p.is_file():
            raise EnrichmentError(f"RaMP DB not found: {p}")
        return p
    env = os.environ.get(RAMP_ENV_VAR)
    if env:
        p = Path(env)
        if p.is_file():
            return p
    raise EnrichmentError(
        f"RaMP DB path not provided and ${RAMP_ENV_VAR} unset / invalid"
    )


def _open_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Aggregate cache (background size + per-pathway compound counts)
# ---------------------------------------------------------------------------


@dataclass
class _RampAggregates:
    """Per-(db, excluded_types) aggregates, computed once and cached."""

    background_size: int
    pathway_size: dict[str, int]                  # pathwayRampId → K
    pathway_meta: dict[str, dict[str, str]]        # pathwayRampId → {name, type, sourceId}
    snapshot_date: str


_AGG_CACHE: dict[tuple[str, tuple[str, ...]], _RampAggregates] = {}


def _aggregates(
    conn: sqlite3.Connection,
    db_path: Path,
    excluded_types: tuple[str, ...],
) -> _RampAggregates:
    """Compute (or fetch from cache) RaMP aggregates filtered by pathway type."""
    cache_key = (str(db_path.resolve()), tuple(sorted(excluded_types)))
    cached = _AGG_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Pathway metadata (name/type/sourceId), filtered to non-excluded types.
    placeholders = ",".join("?" for _ in excluded_types) or "''"
    pathway_meta: dict[str, dict[str, str]] = {}
    if excluded_types:
        cur = conn.execute(
            f"SELECT pathwayRampId, pathwayName, type, sourceId "
            f"FROM pathway WHERE type NOT IN ({placeholders})",
            excluded_types,
        )
    else:
        cur = conn.execute(
            "SELECT pathwayRampId, pathwayName, type, sourceId FROM pathway"
        )
    for row in cur:
        pathway_meta[row["pathwayRampId"]] = {
            "name": row["pathwayName"] or "",
            "type": (row["type"] or "").strip(),
            "sourceId": row["sourceId"] or "",
        }

    # Per-pathway unique compound counts. Compound rampIds start with 'RAMP_C'.
    pathway_size: dict[str, int] = {}
    cur = conn.execute(
        "SELECT pathwayRampId, COUNT(DISTINCT rampId) AS k "
        "FROM analytehaspathway "
        "WHERE rampId LIKE 'RAMP_C%' "
        "GROUP BY pathwayRampId"
    )
    for row in cur:
        pid = row["pathwayRampId"]
        if pid in pathway_meta:  # only keep non-excluded pathways
            pathway_size[pid] = int(row["k"])

    # Background size: unique compound rampIds that participate in *any*
    # non-excluded pathway. We compute by union of compound IDs across
    # the kept pathways.
    if pathway_size:
        kept_ids = list(pathway_size.keys())
        # Chunk to keep IN-clause manageable for sqlite
        seen: set[str] = set()
        chunk = 500
        for i in range(0, len(kept_ids), chunk):
            batch = kept_ids[i : i + chunk]
            ph = ",".join("?" for _ in batch)
            sub = conn.execute(
                f"SELECT DISTINCT rampId FROM analytehaspathway "
                f"WHERE rampId LIKE 'RAMP_C%' AND pathwayRampId IN ({ph})",
                batch,
            )
            for r in sub:
                seen.add(r["rampId"])
        background_size = len(seen)
    else:
        background_size = 0

    # Snapshot date: prefer db_version table if present, else file mtime.
    snapshot_date = _read_snapshot_date(conn, db_path)

    agg = _RampAggregates(
        background_size=background_size,
        pathway_size=pathway_size,
        pathway_meta=pathway_meta,
        snapshot_date=snapshot_date,
    )
    _AGG_CACHE[cache_key] = agg
    logger.info(
        "ramp_enrichment: aggregates cached for %s (excluded=%s) — "
        "background=%d, n_pathways=%d",
        db_path.name, excluded_types, background_size, len(pathway_size),
    )
    return agg


def _read_snapshot_date(conn: sqlite3.Connection, db_path: Path) -> str:
    """Best-effort RaMP version label."""
    try:
        cur = conn.execute("SELECT * FROM db_version LIMIT 1")
        row = cur.fetchone()
        if row is not None:
            keys = row.keys()
            for k in ("version_date", "load_timestamp", "ramp_version", "version"):
                if k in keys and row[k]:
                    return str(row[k])
    except sqlite3.OperationalError:
        pass
    # Fallback: file mtime
    try:
        ts = db_path.stat().st_mtime
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    except OSError:
        return "unknown"


def clear_aggregate_cache() -> None:
    """Clear the module-level aggregates cache (test hook)."""
    _AGG_CACHE.clear()


# ---------------------------------------------------------------------------
# Compound resolution: external id → set of ramp compound IDs
# ---------------------------------------------------------------------------


def _resolve_compounds(
    conn: sqlite3.Connection,
    compound_ids: list[str],
    *,
    id_type: str,
) -> tuple[dict[str, set[str]], list[str]]:
    """Return (input_to_ramp_ids, unresolved_inputs).

    input_to_ramp_ids only contains entries that resolved to ≥1 ramp_id.
    """
    input_to_ramp: dict[str, set[str]] = {}
    unresolved: list[str] = []

    if id_type == "inchikey":
        for cid in compound_ids:
            ikey = (cid or "").strip()
            if not ikey:
                unresolved.append(cid)
                continue
            ramps = _resolve_inchikey(conn, ikey)
            if ramps:
                input_to_ramp[cid] = ramps
            else:
                unresolved.append(cid)
        return input_to_ramp, unresolved

    if id_type not in _ID_TYPE_PREFIXES:
        raise EnrichmentError(f"Unsupported id_type: {id_type!r}")

    prefixes = _ID_TYPE_PREFIXES[id_type]
    for cid in compound_ids:
        bare = (cid or "").strip()
        if not bare:
            unresolved.append(cid)
            continue
        # Try each candidate form: bare, prefixed
        candidates: list[str] = [bare]
        for p in prefixes:
            if not bare.lower().startswith(f"{p}:"):
                candidates.append(f"{p}:{bare}")
        ph = ",".join("?" for _ in candidates)
        cur = conn.execute(
            f"SELECT DISTINCT rampId FROM source "
            f"WHERE sourceId IN ({ph}) AND geneOrCompound='compound'",
            candidates,
        )
        ramps = {r["rampId"] for r in cur if r["rampId"]}
        if ramps:
            input_to_ramp[cid] = ramps
        else:
            unresolved.append(cid)
    return input_to_ramp, unresolved


def _resolve_inchikey(conn: sqlite3.Connection, ikey: str) -> set[str]:
    """Resolve an InChIKey via chem_props. Accept full key or first-block."""
    ikey = ikey.strip()
    if not ikey:
        return set()
    # Full InChIKey is 27 chars (XXXXXXXXXXXXXX-YYYYYYYYYY-Z). First-block
    # alone is 14 chars. We try full-key first (more specific), then prefix.
    full_match: set[str] = set()
    if len(ikey) >= 27:
        cur = conn.execute(
            "SELECT DISTINCT ramp_id FROM chem_props WHERE inchi_key = ?",
            (ikey,),
        )
        full_match = {r["ramp_id"] for r in cur if r["ramp_id"]}
    if full_match:
        return full_match
    # Fallback: first-block (prefix)
    prefix = ikey[:14]
    cur = conn.execute(
        "SELECT DISTINCT ramp_id FROM chem_props WHERE inchi_key_prefix = ?",
        (prefix,),
    )
    return {r["ramp_id"] for r in cur if r["ramp_id"]}


# ---------------------------------------------------------------------------
# Pathway membership: which non-excluded pathways do these ramp_ids hit?
# ---------------------------------------------------------------------------


def _pathway_hits(
    conn: sqlite3.Connection,
    input_to_ramp: dict[str, set[str]],
    kept_pathways: set[str],
) -> dict[str, list[str]]:
    """For each pathway in kept_pathways that has ≥1 input hit, return the
    list of input identifiers that hit it.
    """
    if not input_to_ramp:
        return {}
    # Reverse map: ramp_id → list[input_id]
    ramp_to_inputs: dict[str, list[str]] = {}
    for iid, ramps in input_to_ramp.items():
        for r in ramps:
            ramp_to_inputs.setdefault(r, []).append(iid)

    all_ramp_ids = list(ramp_to_inputs.keys())
    if not all_ramp_ids:
        return {}

    pathway_to_inputs: dict[str, set[str]] = {}
    chunk = 500
    for i in range(0, len(all_ramp_ids), chunk):
        batch = all_ramp_ids[i : i + chunk]
        ph = ",".join("?" for _ in batch)
        cur = conn.execute(
            f"SELECT rampId, pathwayRampId FROM analytehaspathway "
            f"WHERE rampId IN ({ph})",
            batch,
        )
        for row in cur:
            pid = row["pathwayRampId"]
            if pid not in kept_pathways:
                continue
            for iid in ramp_to_inputs[row["rampId"]]:
                pathway_to_inputs.setdefault(pid, set()).add(iid)

    # Preserve input order in the output for determinism
    input_order = {iid: idx for idx, iid in enumerate(input_to_ramp.keys())}
    return {
        pid: sorted(iids, key=lambda x: input_order.get(x, 1 << 30))
        for pid, iids in pathway_to_inputs.items()
    }


# ---------------------------------------------------------------------------
# BH FDR
# ---------------------------------------------------------------------------


def _bh_fdr(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR (step-up). Returns adjusted q-values in the
    same order as the input. Returns empty list for empty input.
    """
    n = len(p_values)
    if n == 0:
        return []
    # Sort ascending, keep original indices
    order = sorted(range(n), key=lambda i: p_values[i])
    sorted_p = [p_values[i] for i in order]
    # BH adjusted: q_i = min over k>=i of (n / rank_k) * p_k
    q_sorted = [0.0] * n
    running_min = 1.0
    for k in range(n - 1, -1, -1):
        rank = k + 1
        adj = sorted_p[k] * n / rank
        if adj < running_min:
            running_min = adj
        q_sorted[k] = min(running_min, 1.0)
    # Restore original order
    out = [0.0] * n
    for sorted_idx, orig_idx in enumerate(order):
        out[orig_idx] = q_sorted[sorted_idx]
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_enrichment(
    compound_ids: Iterable[str],
    *,
    id_type: Literal["inchikey", "kegg", "hmdb"] = "inchikey",
    background: Literal["ramp_full"] = "ramp_full",
    top_n: int = 10,
    fdr_threshold: float = 0.05,
    ramp_db_path: Path | str | None = None,
    excluded_pathway_types: Iterable[str] = _DEFAULT_EXCLUDED_TYPES,
    aggregate_pfocr: bool = True,
) -> EnrichmentReport:
    """Run hypergeometric pathway enrichment on a compound list.

    Args:
        compound_ids: input compounds. Duplicates are deduped.
        id_type: which ID space the inputs belong to. ``"inchikey"`` accepts
            full InChIKeys or 14-char first-blocks (resolved via chem_props).
            ``"kegg"`` and ``"hmdb"`` go through the source table.
        background: only ``"ramp_full"`` is supported (RaMP does not carry
            species labels). The argument is kept for forward-compat.
        top_n: how many pathways to return, sorted by FDR ascending.
        fdr_threshold: stored on the report (used by callers for filtering).
            Does NOT affect the returned ranking.
        ramp_db_path: explicit path to RaMP sqlite. If ``None``, falls back
            to ``$RAMP_DB_PATH``.
        excluded_pathway_types: pathway.type values to skip in BOTH the
            background size and the pathway test set. Default
            ``("pfocr",)``.
        aggregate_pfocr: when pfocr is *not* in ``excluded_pathway_types``,
            multiple pfocr pathways that match the *exact same* set of
            input compounds are aggregated into a single representative
            (the one with smallest K — highest fold enrichment). This
            avoids inflating the BH multiple-testing burden with hundreds
            of redundant figure-OCR'd copies of the same biological
            concept. Default True.

    Returns:
        :class:`EnrichmentReport`. ``top_pathways`` is sorted by FDR ascending.

    Raises:
        EnrichmentError: DB not found, unsupported background mode, or
            empty input.
    """
    if background != "ramp_full":
        raise EnrichmentError(
            f"background={background!r} not supported (only 'ramp_full')"
        )

    db_path = resolve_db_path(ramp_db_path)
    excluded_tuple = tuple(sorted(set(excluded_pathway_types)))

    # Dedupe inputs while preserving order
    seen: set[str] = set()
    inputs: list[str] = []
    for cid in compound_ids:
        if cid is None:
            continue
        s = str(cid).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        inputs.append(s)
    if not inputs:
        raise EnrichmentError("compound_ids was empty")

    conn = _open_ro(db_path)
    try:
        agg = _aggregates(conn, db_path, excluded_tuple)
        if agg.background_size == 0:
            raise EnrichmentError(
                "RaMP background is empty after filtering pathway types "
                f"{excluded_tuple!r}"
            )

        input_to_ramp, unresolved = _resolve_compounds(conn, inputs, id_type=id_type)
        if unresolved:
            logger.warning(
                "ramp_enrichment: %d/%d input compounds did not resolve to RaMP "
                "(id_type=%s); examples=%s",
                len(unresolved), len(inputs), id_type, unresolved[:5],
            )

        n = len(input_to_ramp)  # input compounds successfully resolved
        if n == 0:
            return EnrichmentReport(
                input_compounds=inputs,
                resolved_compounds=[],
                unresolved_compounds=unresolved,
                background_size=agg.background_size,
                n_input_resolved=0,
                top_pathways=[],
                ramp_snapshot_date=agg.snapshot_date,
                excluded_pathway_types=list(excluded_tuple),
                fdr_threshold=fdr_threshold,
            )

        kept_pathways = set(agg.pathway_size.keys())
        hits = _pathway_hits(conn, input_to_ramp, kept_pathways)

        # Optionally aggregate pfocr hits by exact matched_compounds set.
        # Same matched-compound fingerprint → same biological concept (just
        # different figures); keep the representative with smallest K
        # (highest fold enrichment). Non-pfocr hits are never aggregated.
        n_pfocr_in = n_pfocr_out = 0
        if aggregate_pfocr and "pfocr" not in excluded_tuple:
            pfocr_groups: dict[tuple[str, ...], list[tuple[str, list[str], int]]] = {}
            non_pfocr_pairs: list[tuple[str, list[str]]] = []
            for pid, matched in hits.items():
                meta = agg.pathway_meta.get(pid, {})
                if (meta.get("type") or "") == "pfocr":
                    n_pfocr_in += 1
                    K = agg.pathway_size.get(pid, 0)
                    if K == 0:
                        continue
                    key = tuple(sorted(matched))
                    pfocr_groups.setdefault(key, []).append((pid, matched, K))
                else:
                    non_pfocr_pairs.append((pid, matched))
            # Pick representative per group (min K = highest fold)
            kept_hits: dict[str, list[str]] = dict(non_pfocr_pairs)
            for key, candidates in pfocr_groups.items():
                rep_pid, rep_matched, _ = min(candidates, key=lambda x: x[2])
                kept_hits[rep_pid] = rep_matched
            n_pfocr_out = len(pfocr_groups)
            hits = kept_hits

        # Compute hypergeom p-values for every pathway with ≥1 hit
        N = agg.background_size
        rows: list[tuple[str, list[str], int, float]] = []  # (pid, matched, K, p)
        for pid, matched in hits.items():
            K = agg.pathway_size.get(pid, 0)
            if K == 0:
                continue
            k = len(matched)
            # hypergeom.sf(k-1) = P(X >= k); k>=1 always since pid had a hit
            p = float(hypergeom.sf(k - 1, N, K, n))
            rows.append((pid, matched, K, p))

        if n_pfocr_in:
            logger.info(
                "ramp_enrichment: pfocr aggregation %d → %d (saved %d redundant tests)",
                n_pfocr_in, n_pfocr_out, n_pfocr_in - n_pfocr_out,
            )

        if not rows:
            return EnrichmentReport(
                input_compounds=inputs,
                resolved_compounds=list(input_to_ramp.keys()),
                unresolved_compounds=unresolved,
                background_size=N,
                n_input_resolved=n,
                top_pathways=[],
                ramp_snapshot_date=agg.snapshot_date,
                excluded_pathway_types=list(excluded_tuple),
                fdr_threshold=fdr_threshold,
            )

        # BH FDR across all tested pathways
        p_values = [r[3] for r in rows]
        fdrs = _bh_fdr(p_values)

        results: list[EnrichmentResult] = []
        for (pid, matched, K, p), q in zip(rows, fdrs, strict=True):
            meta = agg.pathway_meta.get(pid, {})
            ptype = meta.get("type", "")
            source_label = _TYPE_TO_SOURCE.get(ptype, ptype or "unknown")
            k = len(matched)
            # fold = (k/n) / (K/N)
            fold = (k / n) / (K / N) if K > 0 and n > 0 else 0.0
            results.append(EnrichmentResult(
                pathway_id=pid,
                pathway_name=meta.get("name", "") or pid,
                pathway_source=source_label,
                pathway_external_id=meta.get("sourceId") or None,
                total_pathway_compounds=K,
                matched_compounds=matched,
                p_value=p,
                fdr=q,
                fold_enrichment=fold,
            ))

        # Sort by FDR ascending; tie-break by p, then by pathway_id for determinism
        results.sort(key=lambda r: (r.fdr, r.p_value, r.pathway_id))
        top = results[:top_n]

        return EnrichmentReport(
            input_compounds=inputs,
            resolved_compounds=list(input_to_ramp.keys()),
            unresolved_compounds=unresolved,
            background_size=N,
            n_input_resolved=n,
            top_pathways=top,
            ramp_snapshot_date=agg.snapshot_date,
            excluded_pathway_types=list(excluded_tuple),
            fdr_threshold=fdr_threshold,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Convenience: JSON serialization round-trip
# ---------------------------------------------------------------------------


def report_to_json_str(report: EnrichmentReport) -> str:
    """Serialize an EnrichmentReport to a JSON string (deterministic key order)."""
    return json.dumps(report.to_json(), sort_keys=True, ensure_ascii=False)
