"""RaMP-DB SQLite backend for pathway_context.

RaMP integrates KEGG / Reactome / SMPDB / WikiPathways into one relational
store. The dump is distributed as a SQLite file at
https://github.com/ncats/RaMP-DB/releases — we point at it via
METAGENT_RAMP_PATH.

RaMP's schema carries a lot of biology we do not need (genes, proteins,
enzymes, ontology classes). This backend reads only the four tables the
tool actually uses:

- `source(sourceId TEXT, rampId TEXT, commonName TEXT, dataSource TEXT, ...)`
  Maps an external ID (HMDB0000122, C00031, CHEBI:17234, …) to RaMP's
  internal analyte id. One compound usually has several source rows, one
  per data source.

- `pathway(pathwayRampId TEXT PRIMARY KEY, sourceId TEXT, pathwayName TEXT, type TEXT)`
  Pathway metadata. `type` is one of {kegg, reactome, smpdb, wiki}.
  `sourceId` is the external pathway ID (hsa00010 for KEGG,
  R-HSA-70171 for Reactome, etc.) which we turn into a URL.

- `analytehaspathway(rampId TEXT, pathwayRampId TEXT)`
  Many-to-many linking analytes to pathways. `pathwaySource` may also be
  present on the real RaMP schema; we do not rely on it.

- `reaction2met(rxnRampId TEXT, rampId TEXT, isSubstrate INTEGER)`
  Many-to-many linking metabolites to reactions with a direction flag.
  `isSubstrate=1` means the metabolite is a substrate in that reaction;
  `isSubstrate=0` means a product. We infer network neighbours by joining
  this table to itself through rxnRampId.

We avoid using features that vary between RaMP releases (the exact
column names around pathway sources, the reaction table spelling). The
four tables above are stable across RaMP v2.x.
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
    "kegg": "kegg",
    "KEGG": "kegg",
    "reactome": "reactome",
    "Reactome": "reactome",
    "REACTOME": "reactome",
    "smpdb": "smpdb",
    "SMPDB": "smpdb",
    "wiki": "wikipathways",
    "Wikipathways": "wikipathways",
    "wikipathways": "wikipathways",
    "WIKIPATHWAYS": "wikipathways",
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
    """Resolve an external ID (HMDB, KEGG, ChEBI) to RaMP's internal rampIds.

    We do NOT strip prefixes — RaMP stores IDs verbatim (e.g. 'hmdb:HMDB0000122'
    in older releases, 'HMDB0000122' in newer). We try both forms.
    """
    ident = external_id.strip()
    # Try the bare id first.
    candidates = [ident]
    # RaMP v2 sometimes stores KEGG / HMDB IDs with a `prefix:` scheme.
    if not ident.startswith(("kegg:", "hmdb:", "chebi:", "chemspider:")):
        candidates.extend(
            f"{prefix}:{ident}" for prefix in ("hmdb", "kegg", "chebi")
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

    `direction='downstream'` returns products of reactions where focal is a
    substrate; `direction='upstream'` is the reverse. IDs are de-duplicated
    and we prefer HMDB > KEGG > anything else when one rampId has multiple
    external identifiers.
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

    placeholders = ",".join("?" for _ in ramp_ids)
    sql = (
        "SELECT DISTINCT s.sourceId AS sid, s.dataSource AS ds "
        "FROM reaction2met r1 "
        "JOIN reaction2met r2 ON r1.rxnRampId = r2.rxnRampId "
        "JOIN source s ON s.rampId = r2.rampId "
        f"WHERE r1.rampId IN ({placeholders}) "
        "  AND r1.isSubstrate = ? "
        "  AND r2.isSubstrate = ? "
        "  AND r2.rampId NOT IN ({ph})".format(ph=placeholders)
    )
    cur = conn.execute(
        sql,
        (*ramp_ids, focal_is_substrate, neighbour_is_substrate, *ramp_ids),
    )

    # Group by rampId → pick preferred external ID.
    best: dict[str, str] = {}
    for row in cur.fetchall():
        sid = (row["sid"] or "").strip()
        ds = (row["ds"] or "").lower()
        if not sid:
            continue
        key = sid  # already dedup on sourceId
        # Prefer HMDB > KEGG > anything else if we've seen this sid before.
        incumbent = best.get(key)
        if incumbent is None or _source_priority(ds) < _source_priority(incumbent):
            best[sid] = ds
    return sorted(best.keys())


def _source_priority(datasource: str) -> int:
    ds = (datasource or "").lower()
    if "hmdb" in ds:
        return 0
    if "kegg" in ds:
        return 1
    if "chebi" in ds:
        return 2
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

    This supports the plausibility score: a co-observed metabolite that
    sits in the same pathway as the focal is evidence that the focal ID is
    biologically reasonable for this sample. We compute at pathway level
    rather than reaction level because pathway co-membership is the
    stronger and more interpretable signal.
    """
    if not candidate_ids or not focal.ramp_ids:
        return set()

    # Focal's pathway set.
    focal_placeholders = ",".join("?" for _ in focal.ramp_ids)
    cur = conn.execute(
        f"SELECT DISTINCT pathwayRampId FROM analytehaspathway WHERE rampId IN ({focal_placeholders})",
        focal.ramp_ids,
    )
    focal_pathways = {r["pathwayRampId"] for r in cur.fetchall()}
    if not focal_pathways:
        return set()

    # For each candidate, resolve analyte → pathways and check overlap.
    matches: set[str] = set()
    for cid in candidate_ids:
        cand = resolve_analyte(conn, cid)
        if cand is None:
            continue
        cand_placeholders = ",".join("?" for _ in cand.ramp_ids)
        cur = conn.execute(
            f"SELECT DISTINCT pathwayRampId FROM analytehaspathway WHERE rampId IN ({cand_placeholders})",
            cand.ramp_ids,
        )
        cand_pathways = {r["pathwayRampId"] for r in cur.fetchall()}
        if cand_pathways & focal_pathways:
            matches.add(cid)
    return matches
