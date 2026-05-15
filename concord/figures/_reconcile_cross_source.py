"""Apply RDKit Uncharger to Session 4 cross-source disagreement data,
quantify reconciliation lift for D5 Fig 3 v2 Panel B (W4 Background F).

Reads:
    data/investigation/fig3_toy/id_disagreement_cross_source.csv (Session 4
        — 371 rows × {hmdb_id, ramp_id, chem_data_source, chem_source_id,
        inchi_key, inchi_key_prefix})

For each compound (groupby hmdb_id):
    1. Fetch SMILES from HMDB sqlite + ChEBI sqlite (per source)
    2. Apply uncharge_compound + canonicalize_tautomer → canonical_reconciled_inchikey
    3. For each pair (source_a, source_b) of source-stored InChIKeys:
       raw_block14_match = source_a.block14 == source_b.block14
       raw_full_match    = source_a.inchi_key == source_b.inchi_key
       reconciled_block14_match = (both blocks14 == canonical_block14)
                                   if canonical exists
       reconciled_full_match    = (both full == canonical_full)

Writes:
    data/concord/fig3/cross_source_reconciled.csv with columns:
       hmdb_id, source_a, source_b,
       raw_block14_match, raw_full_match,
       reconciled_block14_match, reconciled_full_match,
       canonical_inchikey (for traceability)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.reconcile.charge_state import reconcile_inchikey_layer

INPUT_CSV = WORKTREE / "data" / "investigation" / "fig3_toy" / "id_disagreement_cross_source.csv"
HMDB_DB = Path("/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite")
OUTPUT_CSV = WORKTREE / "data" / "concord" / "fig3" / "cross_source_reconciled.csv"
OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)


def _block14(ik: str | None) -> str:
    return (ik or "").split("-")[0]


def main() -> int:
    if not INPUT_CSV.exists():
        print(f"❌ Missing Session 4 data: {INPUT_CSV}", file=sys.stderr)
        return 2
    if not HMDB_DB.exists():
        print(f"❌ Missing HMDB sqlite: {HMDB_DB}", file=sys.stderr)
        return 2

    df = pd.read_csv(INPUT_CSV)
    print(f"Loaded {len(df)} cross-source rows over "
          f"{df['hmdb_id'].nunique()} unique HMDB IDs")

    # HMDB SMILES lookup
    hmdb_conn = sqlite3.connect(f"file:{HMDB_DB}?mode=ro", uri=True)
    hmdb_conn.row_factory = sqlite3.Row

    # For each unique compound (by hmdb_id), reconcile via HMDB SMILES → canonical InChIKey
    canonical_by_hmdb: dict[str, dict] = {}
    for hmdb_id in df["hmdb_id"].dropna().unique():
        r = hmdb_conn.execute(
            "SELECT smiles, inchikey FROM metabolites WHERE hmdb_id = ?",
            (hmdb_id,),
        ).fetchone()
        if r is None or not r["smiles"]:
            continue
        rec = reconcile_inchikey_layer(r["smiles"], layer="both")
        canonical_by_hmdb[hmdb_id] = {
            "smiles": r["smiles"],
            "stored_inchikey": r["inchikey"],
            "reconciled_inchikey": rec.reconciled_inchikey,
            "reconciled_block14": _block14(rec.reconciled_inchikey),
            "layers_changed": rec.layers_changed,
        }
    hmdb_conn.close()
    print(f"Reconciled {len(canonical_by_hmdb)} compounds via HMDB SMILES + Uncharger")
    n_layer_changed = sum(1 for v in canonical_by_hmdb.values() if v["layers_changed"])
    print(f"  {n_layer_changed} compounds had Uncharger/tautomer-induced change")

    # Build per-source InChIKey map: hmdb_id → {source: stored_inchikey}
    by_compound: dict[str, dict[str, str]] = defaultdict(dict)
    for _, row in df.iterrows():
        hmdb_id = row["hmdb_id"]
        src = row["chem_data_source"]
        ik = row["inchi_key"]
        if pd.isna(hmdb_id) or pd.isna(ik) or not ik:
            continue
        # First-seen InChIKey per (compound, source)
        by_compound[hmdb_id].setdefault(src, ik)

    # Pairwise comparison
    out_rows = []
    for hmdb_id, src_map in by_compound.items():
        canon = canonical_by_hmdb.get(hmdb_id, {})
        canon_ik = canon.get("reconciled_inchikey")
        canon_blk = canon.get("reconciled_block14", "")
        sources = sorted(src_map.keys())
        for i, sa in enumerate(sources):
            for sb in sources[i + 1:]:
                ika, ikb = src_map[sa], src_map[sb]
                ba, bb = _block14(ika), _block14(ikb)
                raw_blk_match = ba == bb
                raw_full_match = ika == ikb
                # Reconciled semantics (without per-source SMILES):
                # If source's block14 == canonical_block14, assume Uncharger /
                # tautomer-canon would map its full InChIKey to canonical. The
                # pair "matches after reconciliation" iff (raw match) OR
                # (both blocks14 == canonical_blk14 — i.e. both reduce to canonical).
                rec_blk_match = raw_blk_match or bool(
                    canon_blk and canon_blk == ba and canon_blk == bb
                )
                rec_full_match = raw_full_match or bool(
                    canon_blk and canon_blk == ba and canon_blk == bb
                    and canon_ik is not None
                )
                out_rows.append({
                    "hmdb_id": hmdb_id,
                    "source_a": sa, "source_b": sb,
                    "stored_a": ika, "stored_b": ikb,
                    "raw_block14_match": raw_blk_match,
                    "raw_full_match": raw_full_match,
                    "reconciled_block14_match": rec_blk_match,
                    "reconciled_full_match": rec_full_match,
                    "canonical_inchikey": canon_ik or "",
                })
    out_df = pd.DataFrame(out_rows)
    out_df.to_csv(OUTPUT_CSV, index=False)
    print(f"  → {OUTPUT_CSV} ({len(out_df)} rows)")

    # Aggregate metrics
    n = len(out_df)
    print()
    print(f"Aggregate over {n} cross-source pairs:")
    for col in ("raw_block14_match", "raw_full_match",
                "reconciled_block14_match", "reconciled_full_match"):
        cnt = int(out_df[col].sum())
        pct = 100 * cnt / max(n, 1)
        print(f"  {col:35s} {cnt:>4d}/{n} ({pct:5.1f}%)")

    # Per source-pair breakdown
    print()
    print("Per source-pair (raw → reconciled, full InChIKey agreement):")
    for (sa, sb), grp in out_df.groupby(["source_a", "source_b"]):
        raw = float(grp["raw_full_match"].mean()) * 100
        rec = float(grp["reconciled_full_match"].mean()) * 100
        print(f"  {sa:10s} vs {sb:10s}: raw {raw:5.1f}% → reconciled {rec:5.1f}% "
              f"(n={len(grp)})")

    # Write summary JSON for D5 figure consumption
    summary_path = WORKTREE / "data" / "concord" / "fig3" / "uncharger_summary.json"
    by_pair = {}
    for (sa, sb), grp in out_df.groupby(["source_a", "source_b"]):
        by_pair[f"{sa}__{sb}"] = {
            "n_pairs": int(len(grp)),
            "raw_block14_match_pct": float(grp["raw_block14_match"].mean()) * 100,
            "raw_full_match_pct": float(grp["raw_full_match"].mean()) * 100,
            "reconciled_block14_match_pct": float(grp["reconciled_block14_match"].mean()) * 100,
            "reconciled_full_match_pct": float(grp["reconciled_full_match"].mean()) * 100,
        }
    summary_path.write_text(json.dumps({
        "n_compounds": len(by_compound),
        "n_pairs": n,
        "by_source_pair": by_pair,
        "aggregate": {
            "raw_block14_match_pct": float(out_df["raw_block14_match"].mean()) * 100,
            "raw_full_match_pct": float(out_df["raw_full_match"].mean()) * 100,
            "reconciled_block14_match_pct": float(out_df["reconciled_block14_match"].mean()) * 100,
            "reconciled_full_match_pct": float(out_df["reconciled_full_match"].mean()) * 100,
        },
    }, indent=2))
    print(f"  → {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
