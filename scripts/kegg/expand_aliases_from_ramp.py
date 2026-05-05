"""Expand the KEGG reaction-graph compound_aliases table from RaMP-DB.

The graph builder's curated pool covers only 150 mammalian compounds
(925 alias rows). Real-data Sub-6A narratives reference compounds
outside this pool (e.g. terpenes, urate derivatives, lipids), causing
Layer 6d's compound resolver to return None and fall through to
UNVERIFIABLE_V0 — independent of the extractor LLM.

This script enlarges ``compound_aliases`` in-place by joining the
existing reaction-graph compound IDs against RaMP-DB's
``source`` / ``analyte`` / ``analytesynonym`` tables. RaMP is the
canonical aggregator across HMDB / ChEBI / KEGG / RefMet, so it gives
us:

* multiple human-readable common names per compound
* ~15 synonyms per compound on average (RaMP analytesynonym)
* HMDB ID variants (e.g. HMDB0000696 vs HMDB00696)

We **do NOT change the reactions / compounds tables** — only
``compound_aliases`` is expanded, with INSERT OR IGNORE so the
script is idempotent. The reaction graph itself is untouched.

Usage::

    METAGENT_RAMP_PATH=/data/.../ramp.sqlite \
        python scripts/kegg/expand_aliases_from_ramp.py

Outputs a summary line (rows added, distinct cpd: IDs touched) and
optionally writes ``data/kegg/alias_expansion_audit.json`` so D7-style
provenance reports can cite numbers + ramp.sqlite md5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")


def _normalise_alias(s: str) -> str:
    return _WS.sub(" ", str(s).strip()).lower()


def _md5(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 — non-security checksum
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def expand_from_ramp(
    graph_db_path: Path,
    ramp_db_path: Path,
) -> dict:
    """Read graph compounds + RaMP aliases, INSERT OR IGNORE into
    graph.compound_aliases. Returns a summary dict."""
    if not graph_db_path.is_file():
        raise FileNotFoundError(f"graph DB not found: {graph_db_path}")
    if not ramp_db_path.is_file():
        raise FileNotFoundError(f"RaMP DB not found: {ramp_db_path}")

    g = sqlite3.connect(str(graph_db_path))
    r = sqlite3.connect(f"file:{ramp_db_path}?mode=ro", uri=True)
    try:
        # Existing graph compounds (only these matter — RaMP has many KEGG
        # IDs that aren't in our 95-pathway reaction graph).
        existing = {row[0] for row in g.execute(
            "SELECT compound_id FROM compounds"
        ).fetchall()}
        existing_bare = {cid.split(":", 1)[1] for cid in existing if ":" in cid}
        # also keep the cpd: prefix for INSERT
        bare_to_full = {cid.split(":", 1)[1]: cid for cid in existing if ":" in cid}

        # Aliases already present (so we can report Δ accurately)
        n_alias_before = g.execute(
            "SELECT COUNT(*) FROM compound_aliases"
        ).fetchone()[0]

        # 1. Build RaMP cpd → rampId map (one cpd may map to multiple rampIds
        # because RaMP aggregates redundantly; we collect all).
        # Use parameterised IN clause in chunks of 500 (sqlite limit).
        cpd_to_rampids: dict[str, set[str]] = {}
        bare_list = sorted(existing_bare)
        chunk = 500
        for i in range(0, len(bare_list), chunk):
            batch = bare_list[i:i + chunk]
            placeholders = ",".join("?" * len(batch))
            params = [f"kegg:{b}" for b in batch]
            for sid, ramp_id in r.execute(
                f"SELECT sourceId, rampId FROM source "
                f"WHERE IDtype='kegg' AND sourceId IN ({placeholders})",
                params,
            ):
                bare = sid.replace("kegg:", "")
                cpd_to_rampids.setdefault(bare, set()).add(ramp_id)

        n_compounds_with_ramp = len(cpd_to_rampids)
        all_ramp_ids = {rid for rids in cpd_to_rampids.values() for rid in rids}

        # 2. Collect aliases for those rampIds via 3 SQL passes.
        new_rows: list[tuple[str, str, str]] = []

        # 2a. analyte.common_name → name alias
        if all_ramp_ids:
            ramp_id_list = sorted(all_ramp_ids)
            for i in range(0, len(ramp_id_list), chunk):
                batch = ramp_id_list[i:i + chunk]
                placeholders = ",".join("?" * len(batch))
                for ramp_id, common_name in r.execute(
                    f"SELECT rampId, common_name FROM analyte "
                    f"WHERE rampId IN ({placeholders})",
                    batch,
                ):
                    if not common_name:
                        continue
                    # which cpd: ID(s) does this rampId map to?
                    for bare, rids in cpd_to_rampids.items():
                        if ramp_id in rids:
                            new_rows.append((
                                _normalise_alias(common_name),
                                bare_to_full[bare],
                                "name",
                            ))

        # 2b. analytesynonym.Synonym → name alias
        if all_ramp_ids:
            for i in range(0, len(ramp_id_list), chunk):
                batch = ramp_id_list[i:i + chunk]
                placeholders = ",".join("?" * len(batch))
                for ramp_id, syn in r.execute(
                    f"SELECT rampId, Synonym FROM analytesynonym "
                    f"WHERE rampId IN ({placeholders}) "
                    f"AND geneOrCompound='compound'",
                    batch,
                ):
                    if not syn or len(syn) > 200:
                        # skip absurdly long synonyms (RaMP has some
                        # full IUPAC names ~500 chars that are useless
                        # as lookup keys)
                        continue
                    for bare, rids in cpd_to_rampids.items():
                        if ramp_id in rids:
                            new_rows.append((
                                _normalise_alias(syn),
                                bare_to_full[bare],
                                "name",
                            ))

        # 2c. source.sourceId for HMDB IDs + source.commonName as name
        if all_ramp_ids:
            for i in range(0, len(ramp_id_list), chunk):
                batch = ramp_id_list[i:i + chunk]
                placeholders = ",".join("?" * len(batch))
                for ramp_id, idtype, source_id, common in r.execute(
                    f"SELECT rampId, IDtype, sourceId, commonName FROM source "
                    f"WHERE rampId IN ({placeholders})",
                    batch,
                ):
                    matching_bares = [
                        bare for bare, rids in cpd_to_rampids.items()
                        if ramp_id in rids
                    ]
                    if not matching_bares:
                        continue
                    for bare in matching_bares:
                        cpd_full = bare_to_full[bare]
                        # the commonName field on every source row
                        if common:
                            new_rows.append((
                                _normalise_alias(common),
                                cpd_full,
                                "name",
                            ))
                        # HMDB IDs — strip 'hmdb:' prefix
                        if idtype == "hmdb" and source_id.startswith("hmdb:"):
                            new_rows.append((
                                source_id[5:].lower(),
                                cpd_full,
                                "hmdb",
                            ))

        # 3. INSERT OR IGNORE — dedup at SQL level via PK
        n_attempted = len(new_rows)
        if new_rows:
            g.executemany(
                "INSERT OR IGNORE INTO compound_aliases(alias, compound_id, source) "
                "VALUES (?, ?, ?)",
                new_rows,
            )
            g.commit()

        n_alias_after = g.execute(
            "SELECT COUNT(*) FROM compound_aliases"
        ).fetchone()[0]

        return {
            "graph_db_path": str(graph_db_path),
            "ramp_db_path": str(ramp_db_path),
            "ramp_db_md5": _md5(ramp_db_path),
            "n_graph_compounds": len(existing),
            "n_compounds_with_ramp_kegg": n_compounds_with_ramp,
            "n_unique_ramp_ids_touched": len(all_ramp_ids),
            "n_alias_rows_attempted": n_attempted,
            "n_alias_rows_before": n_alias_before,
            "n_alias_rows_after": n_alias_after,
            "n_alias_rows_added": n_alias_after - n_alias_before,
        }
    finally:
        g.close()
        r.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--graph-db", default="data/kegg/reaction_graph.sqlite",
        help="Path to KEGG reaction-graph sqlite (will be modified in-place)",
    )
    p.add_argument(
        "--ramp-db",
        default=os.environ.get(
            "METAGENT_RAMP_PATH",
            "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
        ),
        help="Path to RaMP-DB sqlite (read-only)",
    )
    p.add_argument(
        "--audit",
        default="data/kegg/alias_expansion_audit.json",
        help="Where to write the summary",
    )
    args = p.parse_args(argv)

    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")
    t0 = time.perf_counter()
    summary = expand_from_ramp(Path(args.graph_db), Path(args.ramp_db))
    summary["elapsed_seconds"] = time.perf_counter() - t0

    Path(args.audit).parent.mkdir(parents=True, exist_ok=True)
    Path(args.audit).write_text(json.dumps(summary, indent=2))

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
