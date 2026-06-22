"""Deterministic relevant-pathway-set construction for recall@k metrics.

Decision① (locked 2026-06-22): relevant set = GT pathway
+ RaMP pathway_duplicates + member-overlap (Jaccard >= threshold) neighbors.
Returned as a set of normalized pathway names (via norm_name).
"""

from __future__ import annotations

import sqlite3

from concord.agent.pathway_prediction import norm_name


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _members_ramp(conn: sqlite3.Connection, pathway_ramp_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT rampId FROM analytehaspathway WHERE pathwayRampId=?",
        (pathway_ramp_id,),
    )
    return {r[0] for r in rows}


def _name_ramp(conn: sqlite3.Connection, pathway_ramp_id: str) -> str | None:
    row = conn.execute(
        "SELECT pathwayName FROM pathway WHERE pathwayRampId=?",
        (pathway_ramp_id,),
    ).fetchone()
    return row[0] if row else None


def build_relevant_set_ramp(
    conn: sqlite3.Connection,
    gt_pathway_ramp_id: str,
    *,
    jaccard_threshold: float = 0.3,
) -> set[str]:
    relevant: set[str] = set()
    gt_name = _name_ramp(conn, gt_pathway_ramp_id)
    if gt_name:
        relevant.add(norm_name(gt_name))
    gt_members = _members_ramp(conn, gt_pathway_ramp_id)
    if not gt_members:
        return relevant

    # duplicates (cross-source equivalents)
    for col_self, col_other in (
        ("pathwayRampId1", "pathwayRampId2"),
        ("pathwayRampId2", "pathwayRampId1"),
    ):
        for (other_id,) in conn.execute(
            f"SELECT {col_other} FROM pathway_duplicates WHERE {col_self}=?",
            (gt_pathway_ramp_id,),
        ):
            nm = _name_ramp(conn, other_id)
            if nm:
                relevant.add(norm_name(nm))

    # member-overlap neighbors: only pathways sharing >=1 member with GT
    placeholders = ",".join("?" * len(gt_members))
    candidate_ids = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT pathwayRampId FROM analytehaspathway "
            f"WHERE rampId IN ({placeholders})",
            tuple(gt_members),
        )
    }
    for cand in candidate_ids:
        if cand == gt_pathway_ramp_id:
            continue
        if jaccard(gt_members, _members_ramp(conn, cand)) >= jaccard_threshold:
            nm = _name_ramp(conn, cand)
            if nm:
                relevant.add(norm_name(nm))
    return relevant


def _member_key(chebi_id: "str | None", mam_id: "str | None") -> "str | None":
    return (chebi_id or mam_id) or None


def _members_by_name(
    conn: sqlite3.Connection, pathway_name_norm: str, source: str
) -> "dict[str, set[str]]":
    """Return {normalized_pathway_name: member-key set} for one source."""
    grouped: "dict[str, set[str]]" = {}
    for nm, chebi, mam in conn.execute(
        "SELECT pathway_name, member_chebi_id, member_mam_id "
        "FROM pathway_member WHERE source=?",
        (source,),
    ):
        key = _member_key(chebi, mam)
        if key is None:
            continue
        grouped.setdefault(norm_name(nm), set()).add(key)
    return grouped


def build_relevant_set_modelorg(
    conn: sqlite3.Connection,
    gt_pathway_name: str,
    source: str,
    *,
    jaccard_threshold: float = 0.3,
) -> "set[str]":
    gt_norm = norm_name(gt_pathway_name)
    relevant: "set[str]" = {gt_norm}
    grouped = _members_by_name(conn, gt_norm, source)
    gt_members = grouped.get(gt_norm, set())
    if not gt_members:
        return relevant
    for name_norm, members in grouped.items():
        if name_norm == gt_norm:
            continue
        if jaccard(gt_members, members) >= jaccard_threshold:
            relevant.add(name_norm)
    return relevant
