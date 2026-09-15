"""Apply RDKit Uncharger to Session 4 cross-source disagreement data,
quantify reconciliation lift for D5 Fig 3 v2 Panel B (W4 Background F).

**Patch A (W4 sanity fix 2026-05-16)** — switched from pair-level to
**compound-level metric** so Panel B matches Session 4's reported 59.1%
baseline:

  raw disagreement(compound-level)= fraction of compounds whose sources have
  ≥2 distinct stored full InChIKeys = Session 4 metric (110-compound denom).

  reconciled disagreement(compound-level)= same fraction AFTER mapping each
  source's stored InChIKey to canonical if its block14 matches canonical
  block14(HMDB SMILES → Uncharger + tautomer canonicalizer with Patch B2
  safeguards).

  Caveat: only HMDB SMILES available — reconciled is an **upper-bound estimate**
  (assumes same-block14 sources canonicalize identically). Per-source
  canonicalization is W5 follow-up.

Reads:
    data/investigation/fig3_toy/id_disagreement_cross_source.csv (Session 4)
Writes:
    data/concord/fig3/cross_source_reconciled.csv
    data/concord/fig3/uncharger_summary.json (compound-level aggregate + per-pair)
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
            "safeguards": rec.safeguards_triggered,
        }
    hmdb_conn.close()
    print(f"Reconciled {len(canonical_by_hmdb)} compounds via HMDB SMILES + Uncharger")
    n_layer_changed = sum(1 for v in canonical_by_hmdb.values() if v["layers_changed"])
    n_safeguard = sum(1 for v in canonical_by_hmdb.values() if v["safeguards"])
    print(f"  {n_layer_changed} compounds had Uncharger/tautomer-induced change")
    print(f"  {n_safeguard} compounds had Patch B2 safeguards triggered (rejected tautomer)")

    # Build per-source InChIKey SET map: hmdb_id → {source: {stored_inchikeys}}
    # (NOT just first — Patch A: compound-level metric uses ALL stored rows)
    by_compound: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for _, row in df.iterrows():
        hmdb_id = row["hmdb_id"]
        src = row["chem_data_source"]
        ik = row["inchi_key"]
        if pd.isna(hmdb_id) or pd.isna(ik) or not ik:
            continue
        by_compound[hmdb_id][src].add(ik)

    # ===== Compound-level metric (Patch A) =====
    # raw_disagree(compound) = ≥2 distinct stored full InChIKeys across all its sources
    # block14_disagree(compound) = ≥2 distinct stored block14s across its sources
    # reconciled_*_disagree(compound) = same after mapping ik with block14==canonical_blk14
    #     to canonical (effectively assuming Uncharger pulls those to canonical)

    out_rows = []
    n_compounds_total = len(by_compound)
    agg_raw_full_dis = 0
    agg_raw_blk_dis = 0
    agg_rec_full_dis = 0
    agg_rec_blk_dis = 0

    def _reconcile_iks(iks: set[str], canon_ik: str, canon_blk: str) -> set[str]:
        """Map any ik with block14==canon_blk to canon_ik; keep others."""
        if not canon_blk:
            return set(iks)
        out: set[str] = set()
        for ik in iks:
            if _block14(ik) == canon_blk and canon_ik:
                out.add(canon_ik)
            else:
                out.add(ik)
        return out

    # Per-compound aggregate
    for hmdb_id, src_map in by_compound.items():
        canon = canonical_by_hmdb.get(hmdb_id, {})
        canon_ik = canon.get("reconciled_inchikey")
        canon_blk = canon.get("reconciled_block14", "")

        # All stored InChIKey union (across sources)
        all_iks = set()
        for s_iks in src_map.values():
            all_iks |= s_iks
        all_blks = {_block14(ik) for ik in all_iks}
        raw_full_dis = len(all_iks) >= 2
        raw_blk_dis = len(all_blks) >= 2

        # Reconciled union
        rec_iks: set[str] = set()
        for s_iks in src_map.values():
            rec_iks |= _reconcile_iks(s_iks, canon_ik or "", canon_blk)
        rec_blks = {_block14(ik) for ik in rec_iks}
        rec_full_dis = len(rec_iks) >= 2
        rec_blk_dis = len(rec_blks) >= 2

        agg_raw_full_dis += int(raw_full_dis)
        agg_raw_blk_dis += int(raw_blk_dis)
        agg_rec_full_dis += int(rec_full_dis)
        agg_rec_blk_dis += int(rec_blk_dis)

        # Per source-pair rows for the CSV
        sources = sorted(src_map.keys())
        for i, sa in enumerate(sources):
            for sb in sources[i + 1:]:
                # pair-level for this compound: sources agree iff their stored
                # InChIKey sets are identical
                set_a = src_map[sa]; set_b = src_map[sb]
                pair_raw_blk_dis = ({_block14(x) for x in set_a}
                                    != {_block14(x) for x in set_b})
                pair_raw_full_dis = set_a != set_b
                rec_a = _reconcile_iks(set_a, canon_ik or "", canon_blk)
                rec_b = _reconcile_iks(set_b, canon_ik or "", canon_blk)
                pair_rec_blk_dis = ({_block14(x) for x in rec_a}
                                    != {_block14(x) for x in rec_b})
                pair_rec_full_dis = rec_a != rec_b
                out_rows.append({
                    "hmdb_id": hmdb_id,
                    "source_a": sa, "source_b": sb,
                    "stored_a": "|".join(sorted(set_a)),
                    "stored_b": "|".join(sorted(set_b)),
                    "raw_block14_disagree": pair_raw_blk_dis,
                    "raw_full_disagree": pair_raw_full_dis,
                    "reconciled_block14_disagree": pair_rec_blk_dis,
                    "reconciled_full_disagree": pair_rec_full_dis,
                    "canonical_inchikey": canon_ik or "",
                })

    out_df = pd.DataFrame(out_rows)
    out_df.to_csv(OUTPUT_CSV, index=False)
    print(f"  → {OUTPUT_CSV} ({len(out_df)} pairs across {n_compounds_total} compounds)")

    # ===== Aggregate (compound-level, Session 4-compatible) =====
    print()
    print(f"Compound-level aggregate over {n_compounds_total} compounds:")
    for label, num in (
        ("raw_full_disagree (≥2 distinct InChIKey)", agg_raw_full_dis),
        ("raw_block14_disagree", agg_raw_blk_dis),
        ("reconciled_full_disagree", agg_rec_full_dis),
        ("reconciled_block14_disagree", agg_rec_blk_dis),
    ):
        pct = 100 * num / max(n_compounds_total, 1)
        print(f"  {label:50s} {num:>3d}/{n_compounds_total} ({pct:5.1f}%)")

    # Per source-pair lift (compound-level: # compounds with this pair disagreeing)
    print()
    print("Per source-pair compound-level disagreement (raw → reconciled):")
    by_pair: dict[str, dict] = {}
    for (sa, sb), grp in out_df.groupby(["source_a", "source_b"]):
        # Each row in grp is a compound with this source pair
        n_pair_compounds = grp["hmdb_id"].nunique()
        raw_dis = int(grp["raw_full_disagree"].sum())
        rec_dis = int(grp["reconciled_full_disagree"].sum())
        raw_blk = int(grp["raw_block14_disagree"].sum())
        rec_blk = int(grp["reconciled_block14_disagree"].sum())
        print(f"  {sa:10s} vs {sb:10s}: "
              f"full raw {raw_dis}/{n_pair_compounds} ({100*raw_dis/n_pair_compounds:.1f}%) → "
              f"reconciled {rec_dis}/{n_pair_compounds} ({100*rec_dis/n_pair_compounds:.1f}%)")
        by_pair[f"{sa}__{sb}"] = {
            "n_compounds": int(n_pair_compounds),
            "raw_full_disagreement_pct": 100 * raw_dis / max(n_pair_compounds, 1),
            "reconciled_full_disagreement_pct": 100 * rec_dis / max(n_pair_compounds, 1),
            "raw_block14_disagreement_pct": 100 * raw_blk / max(n_pair_compounds, 1),
            "reconciled_block14_disagreement_pct": 100 * rec_blk / max(n_pair_compounds, 1),
        }

    # Count safeguard activations during canonicalization
    n_safeguard_block14 = sum(
        1 for v in canonical_by_hmdb.values()
        if "block14_changed" in (v.get("safeguards") or ())
    )
    n_safeguard_stereo = sum(
        1 for v in canonical_by_hmdb.values()
        if "stereo_dropped" in (v.get("safeguards") or ())
    )

    summary_path = WORKTREE / "data" / "concord" / "fig3" / "uncharger_summary.json"
    summary_path.write_text(json.dumps({
        "metric": "compound-level (Patch A 2026-05-16): denom = unique HMDB compounds, "
                  "numerator = compounds with ≥2 distinct stored InChIKey across sources",
        "n_compounds": int(n_compounds_total),
        "n_pair_records": int(len(out_df)),
        "n_safeguard_block14_changed": int(n_safeguard_block14),
        "n_safeguard_stereo_dropped": int(n_safeguard_stereo),
        "by_source_pair": by_pair,
        "aggregate_compound_level": {
            "raw_full_disagreement_pct": 100 * agg_raw_full_dis / max(n_compounds_total, 1),
            "raw_block14_disagreement_pct": 100 * agg_raw_blk_dis / max(n_compounds_total, 1),
            "reconciled_full_disagreement_pct": 100 * agg_rec_full_dis / max(n_compounds_total, 1),
            "reconciled_block14_disagreement_pct": 100 * agg_rec_blk_dis / max(n_compounds_total, 1),
        },
        "caveat": "Reconciled values are an upper-bound estimate; only HMDB SMILES is "
                  "canonicalized, with the assumption that same-block14 cross-source pairs "
                  "would canonicalize identically. Per-source canonicalization is W5 follow-up.",
        "safeguards_note": "Patch B2 safeguards (block14_changed, stereo_dropped) reject "
                           "tautomer canonicalization output if (1) connectivity layer changes "
                           "or (2) stereo info silently dropped.",
    }, indent=2))
    print()
    print(f"  Safeguards: block14_changed n={n_safeguard_block14}, "
          f"stereo_dropped n={n_safeguard_stereo}")
    print(f"  → {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
