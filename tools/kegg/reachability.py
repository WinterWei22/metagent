"""KEGG reaction-graph reachability queries.

Two query entry points, picked by Layer 6d at verification time:

* ``is_compound_a_upstream_of_compound_b`` — **primary**. Used when the
  claim is compound→compound ("Methionine is upstream of homocysteine").
  Resolves each endpoint to a KEGG ``cpd:C<NNNNN>`` ID via the alias
  table, runs a directed BFS over the substrate→product graph (with
  reverse edges added for ``type="reversible"`` reactions). Default
  ``max_path_length=6`` per session-intake decision Q4.

* ``is_pathway_a_upstream_of_pathway_b`` — **fallback**. Used when the
  claim phrases two pathways ("Pyrimidine biosynthesis is upstream of
  glycolysis"). Computes pathway compound sets, BFS from any source
  pathway compound to any target pathway compound, with shared
  compounds excluded from targets. Default ``max_path_length=4``.

Both entry points return the same ``ReachabilityResult`` so Layer 6d's
verdict logic can ignore which path produced it.

Implementation notes
--------------------

* The reaction graph is small (~2k unique reactions, ~4k compounds) so
  BFS at query time is fast (<10 ms typical). No precomputed
  reachability matrix.

* Reversible reactions are NOT pre-expanded in the DB — the layer
  reads the ``reactions.reversible`` flag and adds reverse edges on the
  fly. This keeps the audit trail (DB shows the original substrate→
  product direction from KGML) and lets us flip the reversibility
  policy later without rebuilding.

* "Currency metabolites" (ATP, NAD, water, CO₂, etc.) are NOT excluded
  in v0. Excluding them would tighten path semantics but introduces a
  hand-curated list; first see the v3 numbers and decide whether the
  overhead is worth it.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ReachabilityResult:
    """Outcome of one reachability query.

    ``source_compounds`` / ``target_compounds`` are the resolved
    cpd:C-IDs that bound the BFS (after alias resolution + pathway
    expansion when applicable). ``is_reachable`` is True iff the BFS
    found a path of length ≤ ``max_path_length`` from any source to
    any non-source target.
    """
    source_compounds: list[str]
    target_compounds: list[str]
    is_reachable: bool
    shortest_path: list[str] | None
    path_length: int | None
    direction: Literal["forward", "reverse", "bidirectional", "none"]
    max_path_length: int
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------


_KEGG_CPD_RE = re.compile(r"^cpd:C\d{5}$")
_BARE_CPD_RE = re.compile(r"^C\d{5}$")
_INCHIKEY14_RE = re.compile(r"^[A-Z]{14}$")
_INCHIKEY_FULL_RE = re.compile(r"^([A-Z]{14})-[A-Z]{10}-[A-Z]$")
_HMDB_RE = re.compile(r"^HMDB\d{6,}$", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _normalise_alias(s: str) -> str:
    """Same canonicalisation graph_builder uses at index time."""
    return _WS.sub(" ", str(s).strip()).lower()


def resolve_compound_to_kegg(
    query: str,
    *,
    conn: sqlite3.Connection,
) -> tuple[str | None, str | None]:
    """Resolve a free-text compound query to a ``cpd:C<NNNNN>`` ID.

    Recognised inputs (any case, leading/trailing whitespace ignored):
      * ``cpd:C00073``      — already canonical, returns as-is
      * ``C00073``          — bare KEGG ID, prepend ``cpd:``
      * ``OUYCCCASQSFEME``  — InChIKey first-block (14 chars, A–Z)
      * ``OUYCCCASQSFEME-X-Y`` — full InChIKey, takes first block
      * ``HMDB0000696``     — HMDB ID
      * any other string    — looked up case-insensitively against
                               compound_aliases.alias

    Returns ``(cpd_id, source)`` where ``source`` is the alias source
    that matched (``'kegg'`` / ``'inchikey14'`` / ``'hmdb'`` / ``'name'``).
    Returns ``(None, None)`` when nothing resolves.
    """
    q = query.strip()
    if not q:
        return None, None

    # 1. KEGG ID forms — no DB hit needed.
    if _KEGG_CPD_RE.match(q):
        return q, "kegg"
    if _BARE_CPD_RE.match(q):
        return f"cpd:{q}", "kegg"

    # 2. InChIKey forms — prefer 14-char first block.
    full = _INCHIKEY_FULL_RE.match(q.upper())
    if full:
        first = full.group(1)
        return _resolve_alias_table(conn, first.lower(), "inchikey14")
    if _INCHIKEY14_RE.match(q.upper()):
        return _resolve_alias_table(conn, q.upper().lower(), "inchikey14")

    # 3. HMDB.
    if _HMDB_RE.match(q):
        return _resolve_alias_table(conn, q.lower(), "hmdb")

    # 4. Free-text name. Try exact alias first; then "starts-with"
    # fallback to handle decorations like "L-Methionine" vs alias
    # "methionine".
    norm = _normalise_alias(q)
    cpd_id, src = _resolve_alias_table(conn, norm, None)
    if cpd_id is not None:
        return cpd_id, src

    # Strip 'L-' / 'D-' stereodescriptors and retry — curated pool sometimes
    # stores both forms; LLM may say either.
    stripped = re.sub(r"^[ldDL][-\s]+", "", norm).strip()
    if stripped and stripped != norm:
        cpd_id, src = _resolve_alias_table(conn, stripped, None)
        if cpd_id is not None:
            return cpd_id, src

    return None, None


def _resolve_alias_table(
    conn: sqlite3.Connection,
    alias_norm: str,
    expected_source: str | None,
) -> tuple[str | None, str | None]:
    if expected_source is not None:
        row = conn.execute(
            "SELECT compound_id, source FROM compound_aliases "
            "WHERE alias = ? AND source = ? LIMIT 1",
            (alias_norm, expected_source),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT compound_id, source FROM compound_aliases "
            "WHERE alias = ? LIMIT 1",
            (alias_norm,),
        ).fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


# ---------------------------------------------------------------------------
# Graph access
# ---------------------------------------------------------------------------


def _load_directed_edges(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Build the substrate→product adjacency. Reversible reactions add
    both directions. The result is keyed by compound_id; values are the
    set of compound_ids reachable in one hop.

    The adjacency is materialised once per query to keep the layer
    free of stale-cache bugs across multi-process verifier runs.
    """
    edges: dict[str, set[str]] = {}
    rows = conn.execute(
        "SELECT r.reaction_id, MIN(r.reversible) "
        "FROM reactions r GROUP BY r.reaction_id"
    ).fetchall()
    rxn_reversible = {rid: bool(rev) for rid, rev in rows}

    sub_rows = conn.execute(
        "SELECT reaction_id, compound_id FROM reaction_substrates"
    ).fetchall()
    prod_rows = conn.execute(
        "SELECT reaction_id, compound_id FROM reaction_products"
    ).fetchall()

    sub_by_rxn: dict[str, list[str]] = {}
    prod_by_rxn: dict[str, list[str]] = {}
    for rid, cid in sub_rows:
        sub_by_rxn.setdefault(rid, []).append(cid)
    for rid, cid in prod_rows:
        prod_by_rxn.setdefault(rid, []).append(cid)

    for rid, subs in sub_by_rxn.items():
        prods = prod_by_rxn.get(rid, [])
        if not prods:
            continue
        rev = rxn_reversible.get(rid, False)
        for s in subs:
            edges.setdefault(s, set()).update(prods)
        if rev:
            for p in prods:
                edges.setdefault(p, set()).update(subs)
    return edges


def _shortest_path_bfs(
    edges: dict[str, set[str]],
    sources: set[str],
    targets: set[str],
    max_path_length: int,
) -> list[str] | None:
    """Standard BFS, returns the first compound chain (length ≤
    max_path_length+1 nodes) reaching any target, or None.

    The "shared compounds" exclusion (sources ∩ targets) is the
    caller's responsibility — at this layer ``sources`` and ``targets``
    are already disjoint when needed.
    """
    if not sources or not targets:
        return None
    # Trivially reachable in 0 hops if any source is a target. Caller
    # decides whether that's meaningful (compound-level: yes; pathway-
    # level: caller filters out shared first).
    intersect = sources & targets
    if intersect:
        first = sorted(intersect)[0]
        return [first]

    # Multi-source BFS — track parent for reconstruction.
    parent: dict[str, str | None] = {s: None for s in sorted(sources)}
    queue: deque[tuple[str, int]] = deque((s, 0) for s in sorted(sources))
    while queue:
        node, depth = queue.popleft()
        if depth >= max_path_length:
            continue
        for nxt in sorted(edges.get(node, ())):  # sort for determinism
            if nxt in parent:
                continue
            parent[nxt] = node
            if nxt in targets:
                # Reconstruct path
                path = [nxt]
                cur = nxt
                while parent[cur] is not None:
                    cur = parent[cur]  # type: ignore[assignment]
                    path.append(cur)
                path.reverse()
                return path
            queue.append((nxt, depth + 1))
    return None


# ---------------------------------------------------------------------------
# Public entry: compound-level
# ---------------------------------------------------------------------------


def is_compound_a_upstream_of_compound_b(
    compound_a: str,
    compound_b: str,
    *,
    conn: sqlite3.Connection,
    max_path_length: int = 6,
) -> ReachabilityResult:
    """Compound→compound reachability.

    'A is upstream of B' is true iff there is a directed path from any
    KEGG ID resolved from ``compound_a`` to any KEGG ID resolved from
    ``compound_b``, length ≤ ``max_path_length``. Reversible reactions
    contribute both directions.

    The result also reports the reverse direction (B → A) so Layer 6d
    can flag bidirectional cycles ("methionine and homocysteine are in
    a cycle, neither is strictly upstream of the other").
    """
    notes: list[str] = []
    cpd_a, src_a = resolve_compound_to_kegg(compound_a, conn=conn)
    cpd_b, src_b = resolve_compound_to_kegg(compound_b, conn=conn)
    if cpd_a is None:
        notes.append(f"could not resolve subject {compound_a!r} to a KEGG cpd: ID")
    if cpd_b is None:
        notes.append(f"could not resolve object {compound_b!r} to a KEGG cpd: ID")
    if cpd_a is None or cpd_b is None:
        return ReachabilityResult(
            source_compounds=[cpd_a] if cpd_a else [],
            target_compounds=[cpd_b] if cpd_b else [],
            is_reachable=False,
            shortest_path=None,
            path_length=None,
            direction="none",
            max_path_length=max_path_length,
            notes=notes,
        )
    notes.append(f"resolved subject via alias source={src_a!r}, object via {src_b!r}")
    if cpd_a == cpd_b:
        notes.append("subject and object resolve to the same compound")
        return ReachabilityResult(
            source_compounds=[cpd_a],
            target_compounds=[cpd_b],
            is_reachable=True,
            shortest_path=[cpd_a],
            path_length=0,
            direction="forward",
            max_path_length=max_path_length,
            notes=notes,
        )

    edges = _load_directed_edges(conn)
    forward = _shortest_path_bfs(edges, {cpd_a}, {cpd_b}, max_path_length)
    reverse = _shortest_path_bfs(edges, {cpd_b}, {cpd_a}, max_path_length)
    direction: Literal["forward", "reverse", "bidirectional", "none"]
    if forward and reverse:
        direction = "bidirectional"
    elif forward:
        direction = "forward"
    elif reverse:
        direction = "reverse"
    else:
        direction = "none"

    return ReachabilityResult(
        source_compounds=[cpd_a],
        target_compounds=[cpd_b],
        is_reachable=forward is not None,
        shortest_path=forward,
        path_length=(len(forward) - 1) if forward else None,
        direction=direction,
        max_path_length=max_path_length,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Public entry: pathway-level (fallback)
# ---------------------------------------------------------------------------


def get_pathway_compounds(
    pathway_kegg_id: str,
    *,
    conn: sqlite3.Connection,
) -> list[str]:
    """All KEGG compound IDs in a pathway (sorted, deterministic)."""
    rows = conn.execute(
        "SELECT compound_id FROM pathway_compounds WHERE pathway_id = ? "
        "ORDER BY compound_id",
        (pathway_kegg_id,),
    ).fetchall()
    return [r[0] for r in rows]


def is_pathway_a_upstream_of_pathway_b(
    pathway_a_kegg_id: str,
    pathway_b_kegg_id: str,
    *,
    conn: sqlite3.Connection,
    max_path_length: int = 4,
) -> ReachabilityResult:
    """Pathway→pathway reachability.

    Source set: compounds in pathway A; target set: compounds in
    pathway B *minus* compounds shared with A. BFS depth bounded by
    ``max_path_length=4`` (session decision: pathway-level claims
    shouldn't traverse half the metabolome).
    """
    notes: list[str] = []
    src_compounds = set(get_pathway_compounds(pathway_a_kegg_id, conn=conn))
    tgt_compounds = set(get_pathway_compounds(pathway_b_kegg_id, conn=conn))
    if not src_compounds:
        notes.append(f"no compounds for source pathway {pathway_a_kegg_id}")
    if not tgt_compounds:
        notes.append(f"no compounds for target pathway {pathway_b_kegg_id}")
    if not src_compounds or not tgt_compounds:
        return ReachabilityResult(
            source_compounds=sorted(src_compounds),
            target_compounds=sorted(tgt_compounds),
            is_reachable=False,
            shortest_path=None,
            path_length=None,
            direction="none",
            max_path_length=max_path_length,
            notes=notes,
        )

    shared = src_compounds & tgt_compounds
    if shared:
        notes.append(f"{len(shared)} compounds shared between the two pathways; excluded from BFS targets")
    targets = tgt_compounds - src_compounds
    if not targets:
        notes.append("no exclusive target compounds — pathways fully overlap")
        return ReachabilityResult(
            source_compounds=sorted(src_compounds),
            target_compounds=[],
            is_reachable=False,
            shortest_path=None,
            path_length=None,
            direction="none",
            max_path_length=max_path_length,
            notes=notes,
        )

    edges = _load_directed_edges(conn)
    forward = _shortest_path_bfs(edges, src_compounds, targets, max_path_length)
    # Reverse direction (B → A) excludes shared from sources too
    rev_targets = src_compounds - tgt_compounds
    reverse = _shortest_path_bfs(edges, tgt_compounds - src_compounds, rev_targets, max_path_length) if rev_targets else None
    direction: Literal["forward", "reverse", "bidirectional", "none"]
    if forward and reverse:
        direction = "bidirectional"
    elif forward:
        direction = "forward"
    elif reverse:
        direction = "reverse"
    else:
        direction = "none"

    return ReachabilityResult(
        source_compounds=sorted(src_compounds),
        target_compounds=sorted(targets),
        is_reachable=forward is not None,
        shortest_path=forward,
        path_length=(len(forward) - 1) if forward else None,
        direction=direction,
        max_path_length=max_path_length,
        notes=notes,
    )
