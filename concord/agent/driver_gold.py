"""Deterministic gold-driver construction for driver precision/recall.

Decision② (locked 2026-06-22): gold drivers (sub6 + hmdb_ramp only) =
input metabolites that are members of the ground-truth RaMP pathway.
human1/recon2 have no gold driver subset -> caller emits null (N/A).
Identity key is the RaMP compound id (RAMP_C_*).
"""

from __future__ import annotations

import sqlite3


def _kegg_source_id(compound_id: str) -> str | None:
    s = compound_id.strip()
    low = s.lower()
    if low.startswith("kegg:"):
        s = s.split(":", 1)[1]
    if s and s[0] in {"C", "c"} and s[1:].isdigit():
        return f"kegg:{s.upper()}"
    return None


def _chebi_source_id(compound_id: str) -> str | None:
    low = compound_id.strip().lower()
    if low.startswith("chebi:"):
        num = low.split(":", 1)[1]
        if num.isdigit():
            return f"chebi:{num}"
    return None


def resolve_to_ramp_id(conn: sqlite3.Connection, compound_id: str) -> str | None:
    for source_id in (_kegg_source_id(compound_id), _chebi_source_id(compound_id)):
        if source_id is None:
            continue
        row = conn.execute(
            "SELECT rampId FROM source WHERE sourceId=? AND geneOrCompound='compound' LIMIT 1",
            (source_id,),
        ).fetchone()
        if row:
            return row[0]
    return None


def _pathway_member_ramp_ids(
    conn: sqlite3.Connection, gt_pathway_ramp_id: str
) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT rampId FROM analytehaspathway WHERE pathwayRampId=?",
            (gt_pathway_ramp_id,),
        )
    }


def build_gold_drivers_ramp(
    conn: sqlite3.Connection,
    input_metabolite_ids: list[str],
    gt_pathway_ramp_id: str,
) -> set[str]:
    members = _pathway_member_ramp_ids(conn, gt_pathway_ramp_id)
    gold: set[str] = set()
    for cid in input_metabolite_ids:
        ramp_id = resolve_to_ramp_id(conn, cid)
        if ramp_id is not None and ramp_id in members:
            gold.add(ramp_id)
    return gold
