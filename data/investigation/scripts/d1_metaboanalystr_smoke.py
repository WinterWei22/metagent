"""W5 D1下: MetaboAnalystR PSEA real-task smoke (single task).

Validates the full docker-exec → R PSEA → Python normalize → v0.3
EnrichmentResult round-trip on one task from the Gate-1 mammalian
panel. Sanity bar from W5 spec:
  - pathway_ids namespace-prefixed (KEGG: / SMPDB:)
  - chebi_canonicalized == True (≥30% of refs have CHEBI: primary)
  - wall_time < 30s
  - metabolites_hit non-empty across pathways (not vacuous)
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs
from concord.schema.enrichment import PATHWAY_NAMESPACES
from concord.wrappers.metaboanalystr_wrapper import run_metaboanalystr_psea
from concord.normalize.metaboanalystr_norm import normalize_metaboanalystr_output

BENCHMARK = WORKTREE / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks_v3.jsonl"


def main() -> int:
    tasks = [json.loads(line) for line in BENCHMARK.read_text().splitlines()]
    # Skip the first one (RAMP_P_000052855) which we excluded in W4
    task = next(t for t in tasks if "RAMP_P_000052855" not in t["task_id"])
    print(f"task: {task['task_id']}")
    diff_metab = task["differential_metabolites"]
    print(f"n_differential: {len(diff_metab)}")

    hmdb_ids = [m["hmdb_id"] for m in diff_metab if m.get("hmdb_id")]
    print(f"hmdb_ids: {hmdb_ids[:5]}... ({len(hmdb_ids)} total)")

    chebi = ChebiLookup()
    refs, unresolved = resolve_ids_to_compound_refs(
        hmdb_ids, source_namespace="HMDB", chebi_lookup=chebi,
    )
    print(f"resolved CompoundRefs: {len(refs)}, unresolved: {len(unresolved)}")
    if not refs:
        print("ERROR: no CompoundRefs resolved", file=sys.stderr)
        return 2

    print("\n=== run_metaboanalystr_psea(library=kegg, id_type=hmdb) ===")
    t0 = time.time()
    raw = run_metaboanalystr_psea(
        refs, library="kegg", id_type="hmdb", timeout=120,
    )
    wall = time.time() - t0
    print(f"wall_time_sec: {wall:.2f}")
    print(f"raw keys: {list(raw.keys())}")
    print(f"raw['method']: {raw.get('method')}")
    print(f"raw['n_input']: {raw.get('n_input')}")
    print(f"raw['n_input_resolved']: {raw.get('n_input_resolved')}")
    pathways_raw = raw.get("raw", [])
    print(f"raw['raw'] (pathway rows): {len(pathways_raw)}")
    if pathways_raw:
        print(f"  sample pathway[0]: {pathways_raw[0]}")
    if raw.get("error"):
        print(f"PSEA ERROR: {raw['error']}", file=sys.stderr)
        return 3

    print("\n=== normalize → v0.3 ===")
    er = normalize_metaboanalystr_output(raw, top_n=10, chebi_lookup=chebi)
    print(f"schema_version: {er.schema_version}")
    print(f"method: {er.method}")
    print(f"pathway_db: {er.pathway_db}")
    print(f"n pathways: {len(er.pathways)}")
    print(f"chebi_canonicalized: {er.chebi_canonicalized}")
    print(f"wall_time_sec (recorded): {er.wall_time_sec:.2f}")

    if er.pathways:
        for h in er.pathways[:3]:
            print(f"  {h.pathway_id} ({h.pathway_name[:30]}) "
                  f"score={h.score:.4g} mhit={len(h.metabolites_hit)}")

    # Sanity checks
    print("\n=== sanity ===")
    fails = []
    # 1. pathway_id namespace
    bad_ns = [h.pathway_id for h in er.pathways
              if h.pathway_id.split(":", 1)[0] not in PATHWAY_NAMESPACES]
    if bad_ns:
        fails.append(f"non-whitelisted ns in {len(bad_ns)} pathway_ids: {bad_ns[:3]}")
    else:
        print("[OK] all pathway_ids namespace-prefixed (KEGG/SMPDB/...)")

    # 2. wall < 30s
    if wall > 30:
        fails.append(f"wall_time {wall:.2f}s > 30s budget")
    else:
        print(f"[OK] wall_time {wall:.2f}s < 30s")

    # 3. metabolites_hit non-vacuous
    total_hits = sum(len(h.metabolites_hit) for h in er.pathways)
    if er.pathways and total_hits == 0:
        fails.append("vacuous: pathways > 0 but total metabolites_hit == 0")
    else:
        print(f"[OK] metabolites_hit total = {total_hits} across {len(er.pathways)} pathways")

    # 4. chebi_canonicalized %
    if er.pathways:
        n_refs = sum(len(h.metabolites_hit) for h in er.pathways)
        n_chebi = sum(1 for h in er.pathways for r in h.metabolites_hit
                      if r.primary_id.startswith("CHEBI:"))
        pct = n_chebi / max(n_refs, 1) * 100
        print(f"CHEBI primary in metabolites_hit: {n_chebi}/{n_refs} = {pct:.1f}%")
        if pct < 30:
            fails.append(f"CHEBI primary {pct:.1f}% < 30%")
        else:
            print("[OK] CHEBI primary ≥ 30%")

    if fails:
        print("\n=== SANITY FAILS ===")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nD1 末 sanity: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
