"""Refresh the ``classyfire_class`` field on already-built Sub-6 JSONLs.

Use this after the user's ClassyFire run lands data in
``data/classyfire_cache.sqlite`` (schema unchanged: ``inchikey →
response_json`` with ``all_classifications`` array).

The fill heuristic mirrors the curator's:
``classyfire_class = " / ".join(all_classifications[:3])``.

Skips entries whose existing ``classyfire_source`` is ``"npclassifier"``
(those carry NPC-derived labels we explicitly preferred at build time).

Run::

    python -m scripts.build_sub6.refresh_classyfire \\
        --classyfire-cache data/classyfire_cache.sqlite \\
        data/benchmark/sub6/curated_riken_plant.jsonl \\
        data/benchmark/sub6/curated_hmdb_mammalian.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path


def _open_cache(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _label_from_cache(conn: sqlite3.Connection, inchikey: str) -> str | None:
    if not inchikey:
        return None
    cur = conn.execute(
        "SELECT response_json FROM classyfire_cache WHERE inchikey = ?",
        (inchikey,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["response_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    classifications = payload.get("all_classifications") or []
    label = " / ".join(str(c) for c in classifications[:3] if c)
    return label or None


def refresh_file(
    path: Path, conn: sqlite3.Connection, *,
    overwrite_npc: bool = False,
) -> tuple[int, int]:
    """Returns (n_records, n_updated)."""
    records: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    n_updated = 0
    for r in records:
        if (not overwrite_npc) and r.get("classyfire_source") == "npclassifier":
            continue
        ikey = r.get("inchikey") or ""
        label = _label_from_cache(conn, ikey)
        if label:
            r["classyfire_class"] = label
            r["classyfire_source"] = "cache"
            n_updated += 1

    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False))
            f.write("\n")
    return len(records), n_updated


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--classyfire-cache", default="data/classyfire_cache.sqlite")
    p.add_argument("--overwrite-npc", action="store_true",
                    help="If set, overwrite even compounds whose classyfire_source "
                         "is 'npclassifier' (default: keep NPC-derived labels).")
    p.add_argument("paths", nargs="+", help="JSONL files to refresh in place")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger("refresh_classyfire")
    cache_path = Path(args.classyfire_cache)
    conn = _open_cache(cache_path)
    if conn is None:
        log.error("classyfire cache not found at %s", cache_path)
        return 1
    try:
        for path_str in args.paths:
            path = Path(path_str)
            if not path.is_file():
                log.warning("skipping missing %s", path)
                continue
            n, updated = refresh_file(path, conn, overwrite_npc=args.overwrite_npc)
            log.info("%s: %d/%d records updated", path, updated, n)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
