"""W5 D3: K=10 concurrent docker-exec spike.

Launches K=10 parallel MetaboAnalystR PSEA calls against the persistent
container, measures wall time vs sequential baseline, computes speedup.
Target per W5 spec: speedup > 6×.

Memory budget gate (per status file §4.5): GREEN — system has 165 GiB
available, 10 × ~1.2 GiB = ~12 GiB worst-case, 13.7× headroom.
"""
from __future__ import annotations
import concurrent.futures
import json
import sys
import time
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs
from concord.wrappers.metaboanalystr_wrapper import run_metaboanalystr_psea

BENCHMARK = WORKTREE / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks_v3.jsonl"
K = 10


def _build_refs() -> list:
    tasks = [json.loads(line) for line in BENCHMARK.read_text().splitlines()]
    task = next(t for t in tasks if "RAMP_P_000052855" not in t["task_id"])
    hmdb_ids = [m["hmdb_id"] for m in task["differential_metabolites"]
                if m.get("hmdb_id")]
    chebi = ChebiLookup()
    refs, _ = resolve_ids_to_compound_refs(
        hmdb_ids, source_namespace="HMDB", chebi_lookup=chebi)
    return refs


def _one_call(refs) -> tuple[float, int]:
    t0 = time.time()
    raw = run_metaboanalystr_psea(refs, library="kegg", id_type="hmdb",
                                   timeout=180)
    return time.time() - t0, len(raw.get("raw", []))


def main() -> int:
    refs = _build_refs()
    print(f"refs: {len(refs)}")

    # Warm-up call — fills any per-process state (cmpd_db cache should
    # already be in image, but R bytecode warm-up still helps).
    print("\n=== warm-up ===")
    w, n = _one_call(refs)
    print(f"warm-up wall: {w:.2f}s, pathways: {n}")

    # Sequential baseline (3 sequential calls, take median)
    print("\n=== sequential x3 ===")
    seq_walls = []
    for i in range(3):
        w, n = _one_call(refs)
        print(f"  seq[{i}]: {w:.2f}s, pathways: {n}")
        seq_walls.append(w)
    seq_median = sorted(seq_walls)[1]
    print(f"  sequential median: {seq_median:.2f}s")

    # K=10 concurrent
    print(f"\n=== K={K} concurrent ===")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=K) as exe:
        futures = [exe.submit(_one_call, refs) for _ in range(K)]
        per_call = [f.result() for f in concurrent.futures.as_completed(futures)]
    total_wall = time.time() - t0
    walls = [w for w, _ in per_call]
    print(f"  K={K} total wall: {total_wall:.2f}s")
    print(f"  per-call walls: min={min(walls):.2f}s median={sorted(walls)[K//2]:.2f}s max={max(walls):.2f}s")

    # Speedup vs sequential
    seq_equiv = seq_median * K
    speedup = seq_equiv / total_wall
    print(f"\n=== summary ===")
    print(f"  sequential x{K} equivalent: {seq_equiv:.2f}s")
    print(f"  K={K} actual:               {total_wall:.2f}s")
    print(f"  speedup:                    {speedup:.2f}×")
    target = 6.0
    print(f"  target:                     > {target}×")
    if speedup >= target:
        print(f"  D3 spike: PASS (speedup {speedup:.2f}× >= {target}×)")
        return 0
    print(f"  D3 spike: SOFT-FAIL (speedup {speedup:.2f}× < {target}×) "
          f"— investigate GIL / docker exec serialization")
    return 1


if __name__ == "__main__":
    sys.exit(main())
