"""RaMP-DB SQLite backend for pathway_context.

RaMP integrates KEGG / Reactome / SMPDB (surfaced as `type='hmdb'` in
RaMP's pathway table) / WikiPathways into one relational store. The dump
is distributed as a SQLite at https://github.com/ncats/RaMP-DB — we
point at it via METAGENT_RAMP_PATH.

RaMP's schema carries much more biology than we need (genes, proteins,
enzymes, ontology). This backend reads only four tables, keyed against
RaMP v3.0.x column names:

- `source(sourceId, rampId, IDtype, commonName, dataSource, ...)`
  Maps an external ID to RaMP's internal analyte id. `sourceId` is
  lowercase-prefixed (e.g. `hmdb:HMDB0000122`, `kegg:C00031`,
  `chebi:4167`). One compound commonly has many source rows.

- `pathway(pathwayRampId, sourceId, type, pathwayName)`
  `type` is one of {hmdb, kegg, reactome, wiki, pfocr}. We map `hmdb`
  → `smpdb` (its `sourceId` column carries SMPDB IDs like SMP00044),
  `wiki` → `wikipathways`, and silently drop `pfocr` because our
  schema Literal does not include it (forward-compat with a future
  schema bump).

- `analytehaspathway(rampId, pathwayRampId, pathwaySource)`
  Many-to-many with an extra pathwaySource column we ignore.

- `reaction2met(ramp_rxn_id, ramp_cmpd_id, substrate_product,
                met_source_id, met_name, is_cofactor, ...)`
  `substrate_product=1` means the metabolite is a substrate; `0` is a
  product. We self-join this table on ramp_rxn_id to find network
  neighbours, then JOIN `source` back to render preferred external IDs
  (HMDB > KEGG > the raw met_source_id).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

RAMP_ENV_VAR = "METAGENT_RAMP_PATH"

# Mapping from RaMP pathway `type` strings to the Literal values the
# schema (PathwayEntry.source) accepts. Any value outside this table is
# skipped — it is not a schema violation to have a RaMP type we don't
# understand, it's a forward-compat event.
_TYPE_TO_SOURCE = {
    # Canonical RaMP v3 values — lowercase.
    "kegg": "kegg",
    "reactome": "reactome",
    # `hmdb` in RaMP's pathway.type column is actually SMPDB content — its
    # sourceId values are SMP00xxx. Our schema Literal is `smpdb`.
    "hmdb": "smpdb",
    "smpdb": "smpdb",
    "wiki": "wikipathways",
    "wikipathways": "wikipathways",
    # Case-variant keys kept for robustness across RaMP releases.
    "KEGG": "kegg",
    "Reactome": "reactome",
    "SMPDB": "smpdb",
    "HMDB": "smpdb",
    "Wiki": "wikipathways",
    "Wikipathways": "wikipathways",
}

_PATHWAY_URL_TEMPLATES = {
    "kegg": "https://www.kegg.jp/entry/{sid}",
    "reactome": "https://reactome.org/content/detail/{sid}",
    "smpdb": "https://smpdb.ca/view/{sid}",
    "wikipathways": "https://www.wikipathways.org/pathways/{sid}",
}


# ---------------------------------------------------------------------------
# Typed rollups
# ---------------------------------------------------------------------------


@dataclass
class Analyte:
    """The set of RaMP rampIds that correspond to one external identifier.

    RaMP occasionally has multiple rampIds for the same compound (curation
    artefact where e.g. HMDB vs KEGG point at distinct internal rows); we
    carry all of them and union-query downstream.
    """

    external_id: str
    ramp_ids: tuple[str, ...]
    common_name: str | None


@dataclass
class PathwayRow:
    """One pathway belonging to an analyte. Maps 1:1 to schemas.PathwayEntry."""

    pathway_ramp_id: str
    external_id: str | None
    name: str
    source: str            # schema literal
    url: str


# ---------------------------------------------------------------------------
# Path / connection plumbing
# ---------------------------------------------------------------------------


def resolve_db_path(explicit: str | os.PathLike | None = None) -> Path | None:
    if explicit is not None:
        p = Path(explicit)
        return p if p.exists() else None
    env = os.environ.get(RAMP_ENV_VAR)
    if not env:
        return None
    p = Path(env)
    return p if p.exists() else None


def open_connection(path: str | os.PathLike) -> sqlite3.Connection:
    p = Path(path).resolve()
    uri = f"file:{p}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Analyte resolution
# ---------------------------------------------------------------------------


def resolve_analyte(conn: sqlite3.Connection, external_id: str) -> Analyte | None:
    """Resolve an external ID (HMDB, KEGG, ChEBI, PubChem) to RaMP rampIds.

    RaMP v3 stores source IDs with a lowercase prefix (`hmdb:HMDB0000122`,
    `kegg:C00031`). We accept both prefixed and bare forms from the
    caller and try a small set of candidates against the source table.
    """
    ident = external_id.strip()
    # Try the bare id first — covers the rare case where RaMP has stored
    # an ID without a prefix (older releases, or odd source rows).
    candidates = [ident]
    if not ident.startswith(("kegg:", "hmdb:", "chebi:", "chemspider:", "pubchem:")):
        candidates.extend(
            f"{prefix}:{ident}" for prefix in ("hmdb", "kegg", "chebi", "pubchem")
        )

    placeholders = ",".join("?" for _ in candidates)
    cur = conn.execute(
        f"SELECT rampId, commonName FROM source WHERE sourceId IN ({placeholders})",
        candidates,
    )
    rows = cur.fetchall()
    if not rows:
        return None
    ramp_ids = tuple(sorted({r["rampId"] for r in rows if r["rampId"]}))
    if not ramp_ids:
        return None
    # First non-null commonName wins for display.
    common_name: str | None = None
    for r in rows:
        if r["commonName"]:
            common_name = r["commonName"]
            break
    return Analyte(external_id=ident, ramp_ids=ramp_ids, common_name=common_name)


# ---------------------------------------------------------------------------
# Pathway queries
# ---------------------------------------------------------------------------


def pathways_for_analyte(
    conn: sqlite3.Connection,
    analyte: Analyte,
    *,
    limit: int = 50,
) -> list[PathwayRow]:
    """Return all pathways for any of the analyte's rampIds."""
    if not analyte.ramp_ids:
        return []
    placeholders = ",".join("?" for _ in analyte.ramp_ids)
    sql = (
        "SELECT DISTINCT p.pathwayRampId AS pid, p.sourceId AS sid, "
        "       p.pathwayName AS pname, p.type AS ptype "
        "FROM analytehaspathway ahp "
        "JOIN pathway p ON p.pathwayRampId = ahp.pathwayRampId "
        f"WHERE ahp.rampId IN ({placeholders}) "
        "LIMIT ?"
    )
    cur = conn.execute(sql, (*analyte.ramp_ids, limit))
    out: list[PathwayRow] = []
    for row in cur.fetchall():
        source = _TYPE_TO_SOURCE.get((row["ptype"] or "").strip())
        if source is None:
            # Unknown pathway type — skip rather than violate the schema.
            continue
        sid = row["sid"] or row["pid"]
        url = _PATHWAY_URL_TEMPLATES[source].format(sid=sid)
        out.append(
            PathwayRow(
                pathway_ramp_id=row["pid"],
                external_id=row["sid"],
                name=row["pname"] or sid,
                source=source,
                url=url,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Neighbour queries
# ---------------------------------------------------------------------------


def _neighbour_external_ids(
    conn: sqlite3.Connection,
    ramp_ids: tuple[str, ...],
    *,
    direction: str,
) -> list[str]:
    """Return external IDs one reaction hop away from the focal rampIds.

    `direction='downstream'` returns products of reactions where focal is
    a substrate; `direction='upstream'` is the reverse. For each
    neighbour rampId we pick the preferred external ID (HMDB > KEGG >
    ChEBI > other), so the returned list reads the same as what the
    orchestrator would pass to `fetch_metabolite_info`.
    """
    if not ramp_ids:
        return []
    if direction == "downstream":
        focal_is_substrate = 1
        neighbour_is_substrate = 0
    elif direction == "upstream":
        focal_is_substrate = 0
        neighbour_is_substrate = 1
    else:
        raise ValueError(f"unknown direction: {direction}")

    # Step 1: find all reactions where focal plays the required role. SQLite
    # hits rxn2met_met_ramp_id_idx cleanly for this.
    placeholders = ",".join("?" for _ in ramp_ids)
    cur = conn.execute(
        f"SELECT DISTINCT ramp_rxn_id FROM reaction2met "
        f"WHERE ramp_cmpd_id IN ({placeholders}) AND substrate_product = ?",
        (*ramp_ids, focal_is_substrate),
    )
    rxn_ids = [r["ramp_rxn_id"] for r in cur.fetchall() if r["ramp_rxn_id"]]
    if not rxn_ids:
        return []

    # Step 2: find every metabolite participating in those reactions with
    # the neighbour role. Chunked so we never blow past SQLite's 999 bound
    # variables — pyruvate routinely participates in >1000 reactions.
    neighbour_ramps: set[str] = set()
    focal_set = set(ramp_ids)
    for chunk in _chunks(rxn_ids, 800):
        qph = ",".join("?" for _ in chunk)
        cur = conn.execute(
            f"SELECT DISTINCT ramp_cmpd_id FROM reaction2met "
            f"WHERE ramp_rxn_id IN ({qph}) AND substrate_product = ?",
            (*chunk, neighbour_is_substrate),
        )
        for r in cur.fetchall():
            rid = r["ramp_cmpd_id"]
            if rid and rid not in focal_set:
                neighbour_ramps.add(rid)

    if not neighbour_ramps:
        return []

    mapping = _preferred_external_ids_batch(conn, neighbour_ramps)
    return sorted(v for v in mapping.values() if v)


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _preferred_external_ids_batch(
    conn: sqlite3.Connection,
    ramp_ids: set[str] | list[str],
) -> dict[str, str | None]:
    """Batch-resolve rampIds to their preferred external IDs.

    One SQL per call instead of one per rampId — turns an O(N) round-trip
    pattern into O(1). For a typical 200-neighbour query that is a ~200×
    reduction in SQLite overhead.
    """
    ramp_ids = list({r for r in ramp_ids if r})
    if not ramp_ids:
        return {}
    placeholders = ",".join("?" for _ in ramp_ids)
    cur = conn.execute(
        f"SELECT rampId, sourceId, IDtype, dataSource "
        f"FROM source WHERE rampId IN ({placeholders})",
        ramp_ids,
    )
    best: dict[str, tuple[int, str]] = {}
    for r in cur.fetchall():
        rid = r["rampId"]
        sid = (r["sourceId"] or "").strip()
        if not rid or not sid:
            continue
        rank = _source_priority(r["IDtype"] or r["dataSource"] or "")
        incumbent = best.get(rid)
        if incumbent is None or rank < incumbent[0]:
            best[rid] = (rank, sid)
    return {rid: val[1] for rid, val in best.items()}


def _source_priority(datasource: str) -> int:
    ds = (datasource or "").lower()
    if "hmdb" in ds:
        return 0
    if "kegg" in ds:
        return 1
    if "chebi" in ds:
        return 2
    if "pubchem" in ds:
        return 3
    return 99


def network_neighbours(
    conn: sqlite3.Connection,
    analyte: Analyte,
    *,
    depth: int,
) -> tuple[list[str], list[str]]:
    """BFS-by-depth over the reaction graph. Returns (upstream, downstream).

    `depth=0` short-circuits to empty lists — this is a documented contract
    of the outer tool. For v0 we implement depth=1 exactly; deeper values
    (≤3) fall back to a simple iterative expansion that unions hops.
    """
    if depth <= 0:
        return [], []

    # Resolve external IDs back to rampIds at each expansion frontier so
    # that deeper queries re-use the same join.
    def _external_to_ramp(ext_ids: list[str]) -> tuple[str, ...]:
        if not ext_ids:
            return ()
        placeholders = ",".join("?" for _ in ext_ids)
        cur = conn.execute(
            f"SELECT DISTINCT rampId FROM source WHERE sourceId IN ({placeholders})",
            ext_ids,
        )
        return tuple(sorted({r["rampId"] for r in cur.fetchall() if r["rampId"]}))

    up_ids, down_ids = set(), set()
    frontier_up_ramps = analyte.ramp_ids
    frontier_down_ramps = analyte.ramp_ids
    for _ in range(depth):
        step_up = _neighbour_external_ids(conn, frontier_up_ramps, direction="upstream")
        step_down = _neighbour_external_ids(conn, frontier_down_ramps, direction="downstream")
        new_up = [x for x in step_up if x not in up_ids and x not in analyte.ramp_ids]
        new_down = [x for x in step_down if x not in down_ids and x not in analyte.ramp_ids]
        up_ids.update(new_up)
        down_ids.update(new_down)
        frontier_up_ramps = _external_to_ramp(new_up)
        frontier_down_ramps = _external_to_ramp(new_down)
        if not frontier_up_ramps and not frontier_down_ramps:
            break
    return sorted(up_ids), sorted(down_ids)


# ---------------------------------------------------------------------------
# Pathway co-occurrence
# ---------------------------------------------------------------------------


def cooccurring_with_focal(
    conn: sqlite3.Connection,
    focal: Analyte,
    candidate_ids: list[str],
) -> set[str]:
    """Return the subset of `candidate_ids` that share ≥1 pathway with focal.

    ONLY pathways of schema-supported type are counted: `kegg`, `reactome`,
    `hmdb` (surfaced as smpdb), and `wiki` (surfaced as wikipathways).
    RaMP's `pfocr` content is an OCR-derived figure scrape that pairs
    metabolites from unrelated papers — including it in co-occurrence
    completely washes out the signal (glucose and caffeine share three
    pfocr entries that are each about some tangential review). The
    schema Literal already excludes pfocr for output rows; we apply the
    same filter to the scoring numerator so output and score agree.
    """
    if not candidate_ids or not focal.ramp_ids:
        return set()

    supported_types = tuple(_TYPE_TO_SOURCE.keys())
    type_placeholders = ",".join("?" for _ in supported_types)

    # Focal's supported-type pathway set.
    focal_placeholders = ",".join("?" for _ in focal.ramp_ids)
    cur = conn.execute(
        f"SELECT DISTINCT ahp.pathwayRampId "
        f"FROM analytehaspathway ahp "
        f"JOIN pathway p ON p.pathwayRampId = ahp.pathwayRampId "
        f"WHERE ahp.rampId IN ({focal_placeholders}) "
        f"  AND p.type IN ({type_placeholders})",
        (*focal.ramp_ids, *supported_types),
    )
    focal_pathways = {r["pathwayRampId"] for r in cur.fetchall()}
    if not focal_pathways:
        return set()

    matches: set[str] = set()
    for cid in candidate_ids:
        cand = resolve_analyte(conn, cid)
        if cand is None:
            continue
        cand_placeholders = ",".join("?" for _ in cand.ramp_ids)
        cur = conn.execute(
            f"SELECT DISTINCT ahp.pathwayRampId "
            f"FROM analytehaspathway ahp "
            f"JOIN pathway p ON p.pathwayRampId = ahp.pathwayRampId "
            f"WHERE ahp.rampId IN ({cand_placeholders}) "
            f"  AND p.type IN ({type_placeholders})",
            (*cand.ramp_ids, *supported_types),
        )
        cand_pathways = {r["pathwayRampId"] for r in cur.fetchall()}
        if cand_pathways & focal_pathways:
            matches.add(cid)
    return matches
