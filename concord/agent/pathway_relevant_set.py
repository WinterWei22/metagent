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
