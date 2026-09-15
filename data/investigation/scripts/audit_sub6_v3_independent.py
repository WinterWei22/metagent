"""Independent audit of Sub-6B v3 benchmark + side-by-side vs v2.

v3 scope (no Sub-6A v3 exists in this worktree):
  data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl   (md5 331b30a64017deb...)
  data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl  (md5 3f6227a21b9a...)
  data/processed/nm002_excluded_gnps_ids.json          (unchanged from v2)

Re-implements the sub6b-applicable subset of the original 8 checks
(P0-1 / P0-2 / P0-4 / P1-1 / P1-3) plus 5 extended checks (E-1..E-4 and
a new E-6 LIPID MAPS bucket analysis), and writes a side-by-side
v3 vs v2 delta table.

Strictly read-only.
"""
from __future__ import annotations
import csv
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

WORKTREE = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5_investigation")
sys.path.insert(0, str(WORKTREE / "data/investigation/scripts"))
from audit_sub6_v2_independent import (
    _md5, _pathway_id, _signal_set, _jaccard, check_e1,
)

OUT_DATA = WORKTREE / "data/audit/v3_test"
OUT_REPORTS = WORKTREE / "reports/audit"
OUT_DATA.mkdir(parents=True, exist_ok=True)


# v3 expected MD5s (from comparison report Section 6)
V3_EXPECTED_MD5 = {
    "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl":  "331b30a64017debe9d5ce07ed238e4f5",
    # curated_v3 not in comparison report; we record actual + audit it
}


def check_md5_v3() -> dict:
    out = {"per_file": {}, "all_match": True}
    for rel, exp in V3_EXPECTED_MD5.items():
        p = WORKTREE / rel
        act = _md5(p) if p.exists() else None
        m = (act == exp)
        out["per_file"][rel] = {"expected_md5": exp, "actual_md5": act, "match": m}
        if not m:
            out["all_match"] = False
    # Also record curated_v3 md5 (no expected reference)
    cur_path = WORKTREE / "data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl"
    out["per_file"]["data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl"] = {
        "actual_md5": _md5(cur_path), "note": "v3-only, no original-audit expected MD5",
    }
    return out


def load_jsonl(rel: str) -> list[dict]:
    return [json.loads(l) for l in (WORKTREE / rel).read_text().splitlines()]


# -- v3 versions of the checks --------------------------------------------


def check_p0_1_v3(sub6b: list[dict]) -> dict:
    nc = [t.get("noise_count", 0) for t in sub6b]
    return {
        "n_tasks": len(sub6b),
        "noise_zero_count": sum(1 for n in nc if n == 0),
        "noise_min": min(nc) if nc else None,
        "noise_max": max(nc) if nc else None,
        "noise_mean": (sum(nc) / len(nc)) if nc else 0,
    }


def check_p0_2_v3(sub6b: list[dict]) -> dict:
    by = defaultdict(list)
    for t in sub6b:
        pid = _pathway_id(t)
        if pid:
            by[pid].append(t.get("task_id"))
    counts = {pid: len(tids) for pid, tids in by.items()}
    return {
        "n_pathways": len(by),
        "n_tasks_per_pathway": counts,
        "n_singletons": sum(1 for tids in by.values() if len(tids) == 1),
    }


def check_p0_4_v3(curated: list[dict], sub6b: list[dict]) -> dict:
    def _kegg_set(items):
        out = set()
        for it in items:
            k = it.get("kegg_id") if isinstance(it, dict) else None
            if k:
                out.add(k.replace("KEGG:", ""))
        return out
    curated_k = _kegg_set(curated)
    task_used = set()
    for t in sub6b:
        for m in t.get("differential_metabolites") or []:
            k = m.get("kegg_id")
            if k: task_used.add(k.replace("KEGG:", ""))
    return {
        "curated_size": len(curated),
        "curated_unique_kegg": len(curated_k),
        "task_used_unique_kegg": len(task_used),
        "task_used_subset_of_curated": task_used.issubset(curated_k),
        "task_used_pct_of_curated": (100 * len(task_used) / len(curated_k)) if curated_k else 0,
    }


def check_p1_1_v3(sub6b: list[dict]) -> dict:
    sets = {t["task_id"]: _signal_set(t) for t in sub6b}
    tids = list(sets.keys())
    n = len(tids)
    n_identical, n_ge_09, n_ge_07 = 0, 0, 0
    identical_pairs = []
    involved_ge_07 = set()
    for i in range(n):
        for j in range(i + 1, n):
            j_val = _jaccard(sets[tids[i]], sets[tids[j]])
            if j_val == 1.0: n_identical += 1; identical_pairs.append((tids[i], tids[j]))
            if j_val >= 0.9: n_ge_09 += 1
            if j_val >= 0.7: n_ge_07 += 1; involved_ge_07.update([tids[i], tids[j]])

    # Save matrix
    mat_path = OUT_DATA / "jaccard_matrix_63x63_v3.csv"
    with mat_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id"] + tids)
        for ti in tids:
            w.writerow([ti] + [f"{_jaccard(sets[ti], sets[tj]):.4f}" for tj in tids])

    # Identical clusters (union-find)
    parent = {t: t for t in tids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for a, b in identical_pairs:
        union(a, b)
    clusters = defaultdict(list)
    for t in tids:
        clusters[find(t)].append(t)
    multi_clusters = [members for members in clusters.values() if len(members) > 1]

    clu_path = OUT_DATA / "identical_signal_set_groups_v3.csv"
    with clu_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cluster_id", "size", "task_ids", "signal_set_size"])
        for ci, members in enumerate(multi_clusters):
            sig = sets[members[0]]
            w.writerow([f"clu_{ci+1}", len(members),
                         ";".join(members), len(sig)])

    return {
        "n_tasks": n,
        "n_identical_pairs": n_identical,
        "n_jaccard_ge_09_pairs": n_ge_09,
        "n_jaccard_ge_07_pairs": n_ge_07,
        "n_tasks_in_high_overlap_clusters": len(involved_ge_07),
        "pct_tasks_in_high_overlap": 100 * len(involved_ge_07) / n if n else 0,
        "n_identical_multi_clusters": len(multi_clusters),
        "n_unique_signal_sets": len(set(sets.values())),
        "n_pathway_clusters": len(set(_pathway_id(t) for t in sub6b if _pathway_id(t))),
    }


def check_p1_3_v3(sub6b: list[dict]) -> dict:
    by = defaultdict(list)
    for t in sub6b:
        pid = _pathway_id(t)
        if pid:
            gp = t.get("ground_truth_pathway") or {}
            by[pid].append({
                "task_id": t.get("task_id"),
                "name": gp.get("pathway_name"),
                "source": gp.get("pathway_source"),
            })
    inconsistent = []
    for pid, entries in by.items():
        names = set(e["name"] for e in entries if e["name"])
        if len(names) > 1:
            inconsistent.append({"pathway_id": pid, "names": list(names)})
    return {
        "n_pathway_groups": len(by),
        "n_inconsistent_groups": len(inconsistent),
    }


def check_e2_v3(sub6b: list[dict]) -> dict:
    n_mis = 0
    samples = []
    for t in sub6b:
        sigs = {s.replace("KEGG:", "") for s in (t.get("ground_truth_signal_compounds") or [])
                  if isinstance(s, str)}
        dm = t.get("differential_metabolites") or []
        diffs = {m.get("kegg_id", "").replace("KEGG:", "") for m in dm
                   if isinstance(m, dict) and m.get("kegg_id")}
        orphan = sigs - diffs
        if orphan:
            n_mis += 1
            if len(samples) < 3:
                samples.append({"task_id": t.get("task_id"),
                                  "n_orphan": len(orphan),
                                  "sample": list(orphan)[:3]})
    return {"n_tasks": len(sub6b), "n_mismatch": n_mis, "samples": samples}


def check_e3_v3(sub6b: list[dict]) -> dict:
    pids = [_pathway_id(t) for t in sub6b]
    pids = [p for p in pids if p]
    sources = Counter(t.get("ground_truth_pathway", {}).get("pathway_source") for t in sub6b)
    prefix = Counter()
    for p in pids:
        if p.startswith("RAMP_P_"): prefix["RaMP"] += 1
        elif p.startswith("lm_pathway:"): prefix["LIPID_MAPS"] += 1
        elif p.startswith("hsa") or p.startswith("map"): prefix["KEGG_native"] += 1
        elif p.startswith("R-HSA-") or p.startswith("REACT"): prefix["Reactome"] += 1
        elif p.startswith("SMP"): prefix["SMPDB"] += 1
        elif p.startswith("WP"): prefix["WikiPathways"] += 1
        else: prefix["other"] += 1
    return {
        "n_pids_total": len(pids),
        "n_pids_unique": len(set(pids)),
        "ramp_pid_prefix_distribution": dict(prefix),
        "pathway_source_distribution": dict(sources),
    }


def check_e4_v3(sub6b: list[dict]) -> dict:
    n_v = 0; samples = []
    for t in sub6b:
        sigs = {s.replace("KEGG:", "") for s in (t.get("ground_truth_signal_compounds") or [])
                  if isinstance(s, str)}
        noises = {s.replace("KEGG:", "") for s in (t.get("ground_truth_noise_compounds") or [])
                    if isinstance(s, str)}
        ovl = sigs & noises
        if ovl:
            n_v += 1
            if len(samples) < 3:
                samples.append({"task_id": t.get("task_id"),
                                  "overlap_size": len(ovl)})
    return {"n_tasks": len(sub6b), "n_violating": n_v}


def check_e6_lipid_bucket(sub6b: list[dict]) -> dict:
    """LIPID MAPS bucket — replicate vs unique pathway diversity."""
    lm = [t for t in sub6b if (t.get("ground_truth_pathway", {}).get("pathway_source") == "lipidmaps")]
    pids = Counter((t.get("ground_truth_pathway", {}).get("pathway_id"),
                      t.get("ground_truth_pathway", {}).get("external_id"),
                      t.get("ground_truth_pathway", {}).get("pathway_name"))
                     for t in lm)
    return {
        "n_lipid_tasks": len(lm),
        "n_unique_lipid_pathways": len(pids),
        "pathway_replication_counts": {f"{pid[2]} ({pid[1]})": c for pid, c in pids.items()},
        "lipid_task_ids_sample": [t["task_id"] for t in lm[:5]],
    }


# -- Deep dive (P1-1 v3 N_eff) ---


def deep_p1_1_v3(p1_1: dict) -> dict:
    import math
    n = p1_1["n_tasks"]
    n_uniq = p1_1["n_unique_signal_sets"]
    n_pw = p1_1["n_pathway_clusters"]
    return {
        "n_naive": n,
        "n_eff_by_unique_signal_set": n_uniq,
        "n_eff_by_pathway_cluster": n_pw,
        "n_identical_multi_clusters": p1_1["n_identical_multi_clusters"],
        "se_multiplier_under_pathway_cluster": math.sqrt(n / n_pw) if n_pw else None,
        "se_multiplier_under_unique_set": math.sqrt(n / n_uniq) if n_uniq else None,
    }


# -- Main runner ----------------------------------------------------------


def _load_v2_results():
    """Reuse the W7 v2 audit result JSON (already computed)."""
    p = WORKTREE / "data/audit/v2_test/check_results.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def main():
    print("=" * 60)
    print("Sub-6B v3 — INDEPENDENT AUDIT + v2 COMPARISON")
    print("=" * 60)

    md5 = check_md5_v3()
    print("\n[0] MD5")
    for f, info in md5["per_file"].items():
        if "expected_md5" in info:
            mark = "✓" if info["match"] else "✗"
            print(f"  {mark} {f}  exp={info['expected_md5'][:8]}  act={info.get('actual_md5','None')[:8]}")
        else:
            print(f"  ·  {f}  md5={info['actual_md5'][:8]}  ({info['note']})")
    if not md5["all_match"]:
        print("MD5 fail → halt"); return

    sub6b = load_jsonl("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")
    curated = load_jsonl("data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl")
    print(f"\nLoaded sub6b_v3={len(sub6b)} curated_v3={len(curated)}")

    r = {"md5": md5}
    r["p0_1"] = check_p0_1_v3(sub6b)
    r["p0_2"] = check_p0_2_v3(sub6b)
    r["p0_4"] = check_p0_4_v3(curated, sub6b)
    r["p1_1"] = check_p1_1_v3(sub6b)
    r["p1_3"] = check_p1_3_v3(sub6b)
    r["deep_p1_1"] = deep_p1_1_v3(r["p1_1"])

    r["e1"] = check_e1(WORKTREE / "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl",
                       WORKTREE / "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")["sub6b"]
    r["e2"] = check_e2_v3(sub6b)
    r["e3"] = check_e3_v3(sub6b)
    r["e4"] = check_e4_v3(sub6b)
    r["e6_lipid"] = check_e6_lipid_bucket(sub6b)

    out_json = OUT_DATA / "check_results_v3.json"
    out_json.write_text(json.dumps(r, indent=2, default=str))

    # Print + compare to v2
    v2 = _load_v2_results()

    def get_v2(*keys):
        if not v2: return "(v2 N/A)"
        cur = v2
        for k in keys:
            if not isinstance(cur, dict): return "(missing)"
            cur = cur.get(k, "(missing)")
        return cur

    print("\n[1] v3 results + v2 comparison")
    print(f"\n  P0-1 noise:")
    print(f"    v3: zero={r['p0_1']['noise_zero_count']}/{r['p0_1']['n_tasks']}, mean={r['p0_1']['noise_mean']:.2f}, range=[{r['p0_1']['noise_min']},{r['p0_1']['noise_max']}]")
    print(f"    v2: zero={get_v2('p0_1','sub6b','noise_zero_count')}/{get_v2('p0_1','sub6b','n_tasks')}, mean={get_v2('p0_1','sub6b','noise_count_median')} (median)")

    print(f"\n  P0-2 pathways:")
    print(f"    v3: n_pathways={r['p0_2']['n_pathways']}  singletons={r['p0_2']['n_singletons']}")
    print(f"    v2: n_pathways={get_v2('p0_2','n_pathways')}  singletons={get_v2('p0_2','n_singletons')}")

    print(f"\n  P0-4 pool util (v3 has no upstream; only curated→task):")
    print(f"    v3: curated={r['p0_4']['curated_unique_kegg']}  task_used={r['p0_4']['task_used_unique_kegg']}  pct={r['p0_4']['task_used_pct_of_curated']:.1f}%  subset={r['p0_4']['task_used_subset_of_curated']}")
    print(f"    v2: curated={get_v2('p0_4','curated_unique_kegg')}  task_used={get_v2('p0_4','task_used_unique_kegg')}")

    print(f"\n  P1-1 cross-task:")
    print(f"    v3: identical_pairs={r['p1_1']['n_identical_pairs']}  ge09={r['p1_1']['n_jaccard_ge_09_pairs']}  pct_high={r['p1_1']['pct_tasks_in_high_overlap']:.1f}%  unique_sets={r['p1_1']['n_unique_signal_sets']}  pathway_clusters={r['p1_1']['n_pathway_clusters']}")
    print(f"    v2: identical_pairs={get_v2('p1_1','n_identical_pairs')}  ge09={get_v2('p1_1','n_jaccard_ge_09_pairs')}  pct_high={get_v2('p1_1','pct_tasks_in_high_overlap')}  unique_sets={get_v2('p1_1','n_unique_signal_sets')}  pathway_clusters={get_v2('p1_1','n_pathway_clusters')}")

    print(f"\n  P1-3 GT consistency:")
    print(f"    v3: n_pathway_groups={r['p1_3']['n_pathway_groups']}  inconsistent={r['p1_3']['n_inconsistent_groups']}")
    print(f"    v2: n_pathway_groups={get_v2('p1_3','n_pathway_groups')}  inconsistent={get_v2('p1_3','n_inconsistent_groups')}")

    print(f"\n  Deep P1-1 N_eff (v3): naive={r['deep_p1_1']['n_naive']}  unique_set={r['deep_p1_1']['n_eff_by_unique_signal_set']}  pathway={r['deep_p1_1']['n_eff_by_pathway_cluster']}  SE_mult_pw={r['deep_p1_1']['se_multiplier_under_pathway_cluster']:.2f}×")
    if v2:
        d2 = v2.get("deep_p1_1", {})
        print(f"  Deep P1-1 N_eff (v2): naive={d2.get('n_naive')}  unique_set={d2.get('n_eff_by_unique_signal_set')}  pathway={d2.get('n_eff_by_pathway_cluster')}  SE_mult_pw={d2.get('se_multiplier_under_pathway_cluster')}")

    print(f"\n  E-1 jsonl integrity v3: lines={r['e1']['n_lines']} valid={r['e1']['n_valid_json']} dups={r['e1']['n_dup_task_ids']}")
    print(f"  E-2 signal⊆diff v3: mismatch={r['e2']['n_mismatch']}/{r['e2']['n_tasks']}")
    print(f"  E-3 pathway ns v3: unique_pids={r['e3']['n_pids_unique']}  prefixes={r['e3']['ramp_pid_prefix_distribution']}  sources={r['e3']['pathway_source_distribution']}")
    print(f"  E-4 noise⊥signal v3: violating={r['e4']['n_violating']}/{r['e4']['n_tasks']}")
    print(f"  E-6 LIPID MAPS bucket: n_lipid={r['e6_lipid']['n_lipid_tasks']}  unique_lipid_pathways={r['e6_lipid']['n_unique_lipid_pathways']}")
    for k, c in r["e6_lipid"]["pathway_replication_counts"].items():
        print(f"    {k}: {c} tasks")

    print(f"\nwrote {out_json}")


if __name__ == "__main__":
    main()
