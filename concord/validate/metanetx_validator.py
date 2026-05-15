"""MetaNetX cross-namespace ID consistency validator (W4 D3).

Given a list of CompoundRef (each may carry several secondary IDs across
namespaces), check whether all those IDs resolve to the SAME MetaNetX MNX_ID.
Disagreement is flagged as a conflict:
    critical = different inchikey_block14 (connectivity)
    warning  = same block14, different stereo/charge layer

Run on Session 4 R-NEW-16 110-compound cross-source dataset to quantify
reconciliation gain (Background F Uncharger pipeline consumes these numbers).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/concord/metanetx.sqlite")
ConflictSeverity = Literal["critical", "warning"]


@dataclass(frozen=True)
class ConflictRecord:
    compound_ref: Any                       # CompoundRef
    conflicting_namespaces: dict[str, str]   # {"CHEBI": "MNXM01", "HMDB": "MNXM02"}
    severity: ConflictSeverity
    # Optional auxiliary info
    inchikey_block14s: tuple[str, ...] = ()


@dataclass
class ValidationReport:
    n_total: int = 0
    n_consistent: int = 0
    n_inconsistent: int = 0
    n_uncoverable: int = 0
    conflicts: list[ConflictRecord] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "n_total": self.n_total,
            "n_consistent": self.n_consistent,
            "n_inconsistent": self.n_inconsistent,
            "n_uncoverable": self.n_uncoverable,
            "n_critical_conflicts": sum(1 for c in self.conflicts if c.severity == "critical"),
            "n_warning_conflicts": sum(1 for c in self.conflicts if c.severity == "warning"),
        }


def _xref_query(conn: sqlite3.Connection, ns: str, ext_id: str) -> tuple[str | None, str | None]:
    """Return (mnx_id, inchikey_block14) or (None, None) if not in MetaNetX."""
    row = conn.execute(
        "SELECT m.mnx_id, m.inchikey_block14 FROM mnx_xref x "
        "JOIN mnx_compound m ON x.mnx_id = m.mnx_id "
        "WHERE x.external_ns = ? AND x.external_id = ? LIMIT 1",
        (ns.upper(), ext_id),
    ).fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def _strip_ns(value: str | None, ns: str) -> str | None:
    """Strip ``NS:`` prefix from values like ``CHEBI:17234`` → ``17234``."""
    if not value:
        return None
    s = value
    pfx = f"{ns}:"
    if s.startswith(pfx):
        s = s[len(pfx):]
    return s.strip() or None


def _extract_xrefs(ref: Any) -> dict[str, str]:
    """Pull (namespace → raw external id) from a CompoundRef, stripping any
    NS prefix the v0.3 schema may carry on secondary IDs."""
    out: dict[str, str] = {}
    chebi = _strip_ns(getattr(ref, "chebi_id", None), "CHEBI")
    if chebi:
        out["CHEBI"] = chebi
    kegg = _strip_ns(getattr(ref, "kegg_compound_id", None), "KEGG")
    if kegg:
        out["KEGG"] = kegg
    hmdb = _strip_ns(getattr(ref, "hmdb_id", None), "HMDB")
    if hmdb:
        out["HMDB"] = hmdb
    lm = _strip_ns(getattr(ref, "lipidmaps_id", None), "LIPIDMAPS")
    if lm:
        out["LIPIDMAPS"] = lm
    return out


def validate_cross_namespace_consistency(
    refs: list[Any],
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> ValidationReport:
    """For each ref:lookup each secondary ID in MetaNetX,collect distinct
    MNX_IDs。If > 1 distinct MNX_IDs → conflict(severity by block14 match).

    Args:
        refs: list of CompoundRef-like objects (chebi_id / kegg_compound_id /
              hmdb_id / lipidmaps_id attributes;v0.3 NS-prefixed strs).

    Returns:
        ValidationReport with aggregate counts + per-ref ConflictRecord list.
    """
    db_path = Path(db_path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(
            f"MetaNetX sqlite not found at {db_path}. "
            f"Run `python -m concord.etl.metanetx_etl` first."
        )
    report = ValidationReport()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for ref in refs:
            report.n_total += 1
            xrefs = _extract_xrefs(ref)
            if len(xrefs) <= 1:
                # Single namespace ref — trivially "consistent" but record
                # whether MetaNetX covers it.
                if xrefs:
                    ns, ext = next(iter(xrefs.items()))
                    mnx, _ = _xref_query(conn, ns, ext)
                    if mnx is None:
                        report.n_uncoverable += 1
                        continue
                report.n_consistent += 1
                continue

            mnx_by_ns: dict[str, str] = {}
            block14s_by_mnx: dict[str, str | None] = {}
            uncovered = 0
            for ns, ext in xrefs.items():
                mnx, block14 = _xref_query(conn, ns, ext)
                if mnx is None:
                    uncovered += 1
                    continue
                mnx_by_ns[ns] = mnx
                block14s_by_mnx.setdefault(mnx, block14)

            distinct_mnx = set(mnx_by_ns.values())
            if not distinct_mnx:
                report.n_uncoverable += 1
                continue
            if len(distinct_mnx) == 1:
                report.n_consistent += 1
                continue

            # Conflict — assess severity by InChIKey block14 diversity
            block14s = {b for b in block14s_by_mnx.values() if b}
            severity: ConflictSeverity = (
                "critical" if len(block14s) > 1 else "warning"
            )
            report.n_inconsistent += 1
            report.conflicts.append(ConflictRecord(
                compound_ref=ref,
                conflicting_namespaces=mnx_by_ns,
                severity=severity,
                inchikey_block14s=tuple(sorted(block14s)),
            ))
    finally:
        conn.close()
    return report
