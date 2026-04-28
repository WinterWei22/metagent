"""GNPS-RIKEN cross-reference leakage filter (NM-002).

Identifies GNPS reference records that would self-match a benchmark query
extracted from MassBank-RIKEN. Used by the benchmark layer; the
``tools/library_search`` tool itself remains untouched and continues to
return all matches.

Three independent triggers (all on by default):

1. **InChIKey first-block match** — same compound (any stereo/salt). Catches
   re-imports of the same molecule from any contributor.
2. **Cross-reference match** — GNPS metadata fields contain a substring
   resembling an MSBNK-RIKEN identifier that matches a query source_id.
   Tolerates the canonical ``MSBNK-RIKEN-PR309407`` form plus
   ``MassBank:PR309407`` / ``RIKEN PR309407`` variants.
3. **Exact source-id match** — GNPS primary id (``spectrum_id``) literally
   equals a query source_id.

Two optional safety nets, off by default:

- ``exclude_massbank_ml_export`` — wholesale-exclude every GNPS record
  whose ``GNPS_library_membership == "MassBank_ML_Export"``. Stricter
  than the per-query xref check; useful for paper-final benchmark builds.
- ``additional_excluded_libraries`` — same wholesale logic for an
  arbitrary list of library_membership values (e.g. ``["MONA_ML_Export"]``).

The audit log is the deliverable: every excluded GNPS id has at least one
explicit reason recorded in :attr:`LeakageFilterResult.exclusion_reasons`.

Supported library formats
-------------------------
- ``.csv`` — GNPS enriched dump (preferred). Carries
  ``GNPS_library_membership``, ``InChIKey_smiles``, ``Compound_Name``,
  ``spectrum_id``.
- ``.mgf`` — fallback via :func:`common.gnps_loader.iter_records`.
  Note that the MGF dump has no ``GNPS_library_membership`` field, so
  the wholesale-library exclusion options become no-ops.
"""
from __future__ import annotations

import csv
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from schemas.common import ToolError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LeakageFilterError(ToolError):
    """Unrecoverable error while building the leakage filter."""

    code = "LEAKAGE_FILTER_ERROR"
    recoverable = False


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class LeakageFilterResult:
    """Outcome of running :func:`build_leakage_filter`."""

    excluded_gnps_ids: set[str] = field(default_factory=set)
    """GNPS ``spectrum_id`` values that downstream library_search must skip."""

    exclusion_reasons: dict[str, list[str]] = field(default_factory=dict)
    """``{gnps_id: [reason, …]}``. Reasons are human-readable strings whose
    prefix encodes the trigger type::

        "shares_inchikey_first_block_with_query:<query_source_id>"
        "cross_reference_to_riken:<MSBNK-RIKEN-...>"
        "exact_source_match:<query_source_id>"
        "library_membership_excluded:<MassBank_ML_Export>"
    """

    stats: dict[str, int] = field(default_factory=dict)
    """Summary counts (see :func:`build_leakage_filter` docstring for keys)."""


# ---------------------------------------------------------------------------
# Cross-reference extraction
# ---------------------------------------------------------------------------

_RIKEN_PATTERNS = (
    re.compile(r"MSBNK-RIKEN-(\w+)", re.IGNORECASE),
    re.compile(r"\bMassBank[:\s]+(PR\w+)", re.IGNORECASE),
    re.compile(r"\bRIKEN[:\s\-]+(PR\w+)", re.IGNORECASE),
)


def _extract_riken_ids(*texts: str | None) -> list[str]:
    """Pull every plausible MSBNK-RIKEN identifier out of free-form text.

    Returned ids are normalised to the canonical ``MSBNK-RIKEN-{suffix}``
    form regardless of which input pattern matched. Duplicates (the same
    id matched by multiple regexes or in multiple input strings) are
    de-duplicated while preserving first-seen order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for txt in texts:
        if not txt:
            continue
        for pat in _RIKEN_PATTERNS:
            for m in pat.finditer(txt):
                ident = f"MSBNK-RIKEN-{m.group(1)}"
                if ident in seen:
                    continue
                seen.add(ident)
                out.append(ident)
    return out


# ---------------------------------------------------------------------------
# Query-side prep
# ---------------------------------------------------------------------------


@dataclass
class _QueryIndex:
    """Hash-set view of the benchmark pool used as the leakage probe set."""

    source_ids: set[str]
    inchikey_first_blocks: set[str]
    n_records: int
    n_inchikey_kept: int
    n_inchikey_malformed: int


def _build_query_index(records: Iterable[dict]) -> _QueryIndex:
    """Extract source_id and InChIKey first-block from each query record.

    Tolerates two record layouts (per maintainer Q1):

    1. ``record["source_id"]`` (brief's documented contract)
    2. ``record["metadata"]["accession"]`` (current
       ``compound_pool_riken.jsonl`` layout)

    InChIKey is read from ``record["ground_truth"]["inchikey"]``.
    """
    source_ids: set[str] = set()
    inchikey_first: set[str] = set()
    n = 0
    n_kept = 0
    n_bad = 0
    for rec in records:
        n += 1
        sid = rec.get("source_id")
        if not sid:
            meta = rec.get("metadata") or {}
            sid = meta.get("accession")
        if sid:
            source_ids.add(str(sid).strip())

        gt = rec.get("ground_truth") or {}
        ikey = gt.get("inchikey") or ""
        if isinstance(ikey, str) and len(ikey) >= 14:
            inchikey_first.add(ikey[:14])
            n_kept += 1
        else:
            n_bad += 1
            if n_bad <= 5:  # avoid log spam
                logger.warning(
                    "leakage_filter: query record missing/short inchikey: %r (sid=%r)",
                    ikey, sid,
                )
    return _QueryIndex(
        source_ids=source_ids,
        inchikey_first_blocks=inchikey_first,
        n_records=n,
        n_inchikey_kept=n_kept,
        n_inchikey_malformed=n_bad,
    )


# ---------------------------------------------------------------------------
# GNPS-side iteration
# ---------------------------------------------------------------------------


_CSV_FIELD_MAP = {
    # canonical_name -> list of CSV column names to try (in order)
    "spectrum_id": ("spectrum_id", "SpectrumID", "TITLE"),
    "inchikey": ("InChIKey_smiles", "InChIKey", "INCHIKEY"),
    "compound_name": ("Compound_Name",),
    "compound_source": ("Compound_Source",),
    "library_membership": ("GNPS_library_membership", "library_membership"),
}


def _pick(row: dict, *names: str) -> str | None:
    for n in names:
        v = row.get(n)
        if v not in (None, "", "N/A", "n/a"):
            return str(v).strip()
    return None


def _iter_gnps_csv(path: Path) -> Iterable[dict[str, Any]]:
    """Stream the GNPS enriched CSV as canonical-keyed dicts."""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            yield {
                "spectrum_id": _pick(row, *_CSV_FIELD_MAP["spectrum_id"]),
                "inchikey": _pick(row, *_CSV_FIELD_MAP["inchikey"]),
                "compound_name": _pick(row, *_CSV_FIELD_MAP["compound_name"]),
                "compound_source": _pick(row, *_CSV_FIELD_MAP["compound_source"]),
                "library_membership": _pick(row, *_CSV_FIELD_MAP["library_membership"]),
                "_raw": row,
            }


def _iter_gnps_mgf(path: Path) -> Iterable[dict[str, Any]]:
    """Stream an MGF dump as canonical-keyed dicts via gnps_loader."""
    from common.gnps_loader import iter_records

    for rec in iter_records(path):
        yield {
            "spectrum_id": rec.spectrum_id or None,
            "inchikey": rec.inchikey or None,
            "compound_name": rec.compound_name or None,
            "compound_source": None,
            "library_membership": rec.library_membership or None,
            "_raw": rec,
        }


def _iter_gnps_library(path: Path) -> Iterable[dict[str, Any]]:
    """Dispatch to the right iterator based on file extension."""
    ext = path.suffix.lower()
    if ext == ".csv":
        return _iter_gnps_csv(path)
    if ext in (".mgf", ".mgf.gz"):
        return _iter_gnps_mgf(path)
    raise LeakageFilterError(
        f"unsupported GNPS library extension {ext!r} (path={path}); "
        "use .csv (preferred) or .mgf"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_leakage_filter(
    benchmark_records: Iterable[dict],
    gnps_library_path: Path | str,
    *,
    match_inchikey_first_block: bool = True,
    match_cross_references: bool = True,
    match_exact_source_id: bool = True,
    additional_excluded_libraries: list[str] | None = None,
    exclude_massbank_ml_export: bool = False,
) -> LeakageFilterResult:
    """Identify GNPS records that would cause leakage for the given queries.

    Args:
        benchmark_records: iterable of RIKEN-derived benchmark records.
            Each record must carry, at minimum, a source_id (under either
            ``"source_id"`` or ``"metadata"["accession"]``) and
            ``"ground_truth"["inchikey"]``.
        gnps_library_path: path to the GNPS library (``.csv`` enriched
            dump preferred; ``.mgf`` also accepted via gnps_loader).
        match_inchikey_first_block: see module docstring trigger 1.
        match_cross_references: see module docstring trigger 2.
        match_exact_source_id: see module docstring trigger 3.
        additional_excluded_libraries: optional whitelist of library
            membership labels to wholesale-exclude (e.g.
            ``["MONA_ML_Export"]``). ``None`` (default) → only RIKEN
            cross-references via the per-query triggers.
        exclude_massbank_ml_export: if ``True``, wholesale-exclude every
            GNPS record with ``GNPS_library_membership == "MassBank_ML_Export"``.
            Default ``False`` (per-query xref is the primary mechanism).

    Returns:
        :class:`LeakageFilterResult` populated with the exclusion set,
        per-record audit log, and summary stats. Stats keys::

            total_gnps_records_scanned
            total_query_records
            excluded_by_inchikey_match
            excluded_by_cross_reference
            excluded_by_source_match
            excluded_by_library_wholesale
            total_excluded
            gnps_with_malformed_inchikey
            queries_with_malformed_inchikey
    """
    path = Path(gnps_library_path)
    if not path.is_file():
        raise LeakageFilterError(f"GNPS library not found: {path}")

    qidx = _build_query_index(benchmark_records)
    if qidx.n_records == 0:
        raise LeakageFilterError("benchmark_records was empty")
    logger.info(
        "leakage_filter: %d query records, %d unique inchikey first-blocks, "
        "%d unique source_ids",
        qidx.n_records, len(qidx.inchikey_first_blocks), len(qidx.source_ids),
    )

    wholesale_libs: set[str] = set()
    if exclude_massbank_ml_export:
        wholesale_libs.add("MassBank_ML_Export")
    if additional_excluded_libraries:
        wholesale_libs.update(additional_excluded_libraries)

    excluded: set[str] = set()
    reasons: dict[str, list[str]] = {}
    n_inchikey_hits = 0
    n_xref_hits = 0
    n_source_hits = 0
    n_wholesale_hits = 0
    n_gnps = 0
    n_gnps_bad_ikey = 0

    for rec in _iter_gnps_library(path):
        n_gnps += 1
        gnps_id = rec.get("spectrum_id")
        if not gnps_id:
            continue  # skip records with no usable primary id

        # Trigger 1 — InChIKey first-block match
        ikey = rec.get("inchikey") or ""
        ikey_first = ikey[:14] if isinstance(ikey, str) and len(ikey) >= 14 else None
        if not ikey_first:
            n_gnps_bad_ikey += 1
        if match_inchikey_first_block and ikey_first and ikey_first in qidx.inchikey_first_blocks:
            n_inchikey_hits += 1
            excluded.add(gnps_id)
            reasons.setdefault(gnps_id, []).append(
                f"shares_inchikey_first_block_with_query:{ikey_first}"
            )

        # Trigger 3 — Exact source-id match (run before xref because
        # cross-ref scanning is more expensive)
        if match_exact_source_id and gnps_id in qidx.source_ids:
            n_source_hits += 1
            excluded.add(gnps_id)
            reasons.setdefault(gnps_id, []).append(
                f"exact_source_match:{gnps_id}"
            )

        # Trigger 2 — Cross-reference scan (free-form RIKEN ids in any
        # plausible field)
        if match_cross_references:
            xref_ids = _extract_riken_ids(
                rec.get("spectrum_id"),
                rec.get("compound_name"),
                rec.get("compound_source"),
                rec.get("library_membership"),
            )
            matched = [x for x in xref_ids if x in qidx.source_ids]
            if matched:
                n_xref_hits += 1
                excluded.add(gnps_id)
                # Dedupe per record so a record matched by 3 fields only
                # logs each unique id once.
                seen = set()
                for x in matched:
                    if x in seen:
                        continue
                    seen.add(x)
                    reasons.setdefault(gnps_id, []).append(
                        f"cross_reference_to_riken:{x}"
                    )

        # Wholesale library exclusion (off by default)
        if wholesale_libs:
            lib = rec.get("library_membership") or ""
            if lib in wholesale_libs:
                n_wholesale_hits += 1
                excluded.add(gnps_id)
                reasons.setdefault(gnps_id, []).append(
                    f"library_membership_excluded:{lib}"
                )

    stats = {
        "total_gnps_records_scanned": n_gnps,
        "total_query_records": qidx.n_records,
        "excluded_by_inchikey_match": n_inchikey_hits,
        "excluded_by_cross_reference": n_xref_hits,
        "excluded_by_source_match": n_source_hits,
        "excluded_by_library_wholesale": n_wholesale_hits,
        "total_excluded": len(excluded),
        "gnps_with_malformed_inchikey": n_gnps_bad_ikey,
        "queries_with_malformed_inchikey": qidx.n_inchikey_malformed,
    }
    logger.info(
        "leakage_filter: excluded %d / %d GNPS records "
        "(inchikey=%d, xref=%d, source=%d, wholesale=%d)",
        len(excluded), n_gnps,
        n_inchikey_hits, n_xref_hits, n_source_hits, n_wholesale_hits,
    )
    return LeakageFilterResult(
        excluded_gnps_ids=excluded,
        exclusion_reasons=reasons,
        stats=stats,
    )
