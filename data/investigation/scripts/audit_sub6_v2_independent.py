"""Independent read-only audit of Sub-6 v2 benchmark data.

Black-box reimplementation of the 8 original audit checks (P0-1..P0-5,
P1-1..P1-3) without referring to the original audit script. Adds 5
extended checks (E-1..E-5) plus two deep dives (P1-1 independence,
P1-2 spectra sparsity).

Strictly read-only. Does NOT modify any benchmark file. Outputs go to
reports/audit/ + data/audit/v2_test/.
"""
from __future__ import annotations
import csv
import hashlib
import json
import re
import statistics
import subprocess
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

WORKTREE = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5_investigation")
SIBLING = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
OUT_DATA = WORKTREE / "data/audit/v2_test"
OUT_REPORTS = WORKTREE / "reports/audit"
OUT_DATA.mkdir(parents=True, exist_ok=True)
OUT_REPORTS.mkdir(parents=True, exist_ok=True)


# -- File paths + expected MD5s -------------------------------------------

EXPECTED_MD5 = {
    "data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl":      "23594c0a3c6ab7a906baad1e0cd622dc",
    "data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl":            "73f0f3a336dc3d0be87571d15cfc6831",
    "data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl":     "2a8a9f35e8cf84a9c1e2a452eb00561e",
    "data/processed/hmdb_candidates_npc_classified_v2.jsonl":  "8824f112a1a63e2f91fcc451ce157244",
    "data/processed/nm002_excluded_gnps_ids.json":             "b5176477fa803c3c2a3c13eeae1f7638",
}


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _resolve_path(relpath: str) -> Path:
    """Resolve a benchmark-relative path. Prefer audit worktree; fall back
    to sibling main worktree if missing (anomaly: hmdb_candidates lives
    only on the v2-integrated branch). Verify MD5 either way."""
    p_audit = WORKTREE / relpath
    if p_audit.exists():
        return p_audit
    p_sibling = SIBLING / relpath
    if p_sibling.exists():
        return p_sibling
    raise FileNotFoundError(f"{relpath} not found in either worktree")


def check_md5_provenance() -> dict:
    out = {"per_file": {}, "all_match": True, "anomalies": []}
    for rel, exp in EXPECTED_MD5.items():
        try:
            resolved = _resolve_path(rel)
            act = _md5(resolved)
            anom = (resolved == SIBLING / rel)
            out["per_file"][rel] = {
                "expected_md5": exp, "actual_md5": act,
                "match": act == exp,
                "resolved_from": "sibling" if anom else "audit_worktree",
                "size_bytes": resolved.stat().st_size,
            }
            if not (act == exp):
                out["all_match"] = False
            if anom:
                out["anomalies"].append(
                    f"{rel} resolved from sibling worktree (audit worktree branch lacks file)")
        except FileNotFoundError as e:
            out["per_file"][rel] = {"error": str(e), "match": False}
            out["all_match"] = False
    return out


def load_jsonl(rel: str) -> list[dict]:
    return [json.loads(line) for line in _resolve_path(rel).read_text().splitlines()]


def load_json(rel: str):
    return json.loads(_resolve_path(rel).read_text())


# -- Original 8 checks (independent reimplementation) ----------------------


def check_p0_1(sub6a: list[dict], sub6b: list[dict]) -> dict:
    """noise_count distribution + noise==0 task count."""
    def _stats(tasks):
        nc = [t.get("noise_count", 0) for t in tasks]
        return {
            "n_tasks": len(tasks),
            "noise_count_min": min(nc) if nc else None,
            "noise_count_median": statistics.median(nc) if nc else None,
            "noise_count_max": max(nc) if nc else None,
            "noise_zero_count": sum(1 for n in nc if n == 0),
            "noise_zero_pct": (100 * sum(1 for n in nc if n == 0) / len(nc)) if nc else 0,
        }
    return {"sub6a": _stats(sub6a), "sub6b": _stats(sub6b)}


def _pathway_id(task: dict) -> str | None:
    """Use `pathway_id` (RaMP-normalised) which is the post-aggregation
    canonical key (audit grouped to 13 pathways → 13 distinct
    pathway_id, not external_id which would be the source-DB code)."""
    gp = task.get("ground_truth_pathway") or {}
    if isinstance(gp, dict):
        return gp.get("pathway_id") or gp.get("external_id")
    return None


def _pathway_external_id(task: dict) -> str | None:
    gp = task.get("ground_truth_pathway") or {}
    if isinstance(gp, dict):
        return gp.get("external_id")
    return None


def check_p0_2(sub6b: list[dict]) -> dict:
    """pathway → tasks grouping; singleton count."""
    by = defaultdict(list)
    for t in sub6b:
        pid = _pathway_id(t)
        if pid:
            by[pid].append(t.get("task_id"))
    return {
        "n_pathways": len(by),
        "n_tasks_per_pathway": {pid: len(tids) for pid, tids in by.items()},
        "n_singletons": sum(1 for tids in by.values() if len(tids) == 1),
    }


def check_p0_3(sub6a: list[dict], excluded: list[str]) -> dict:
    """sub6a spectra.source_id ∩ nm002 exclusion list."""
    excl_set = set(excluded)
    sids: set[str] = set()
    n_spectra = 0
    for t in sub6a:
        for sp in t.get("differential_spectra", []) or []:
            sid = sp.get("source_id")
            if sid:
                sids.add(sid)
                n_spectra += 1
    overlap = sids & excl_set
    return {
        "n_unique_source_ids": len(sids),
        "n_spectra_total": n_spectra,
        "n_excluded_overlap": len(overlap),
        "sample_excluded": list(overlap)[:10],
        "exclusion_list_size": len(excl_set),
    }


def check_p0_4(upstream: list[dict], curated: list[dict],
                sub6b: list[dict], sub6a: list[dict]) -> dict:
    """Three-layer KEGG cpd id utilisation. Task-used KEGG = union of
    sub6b dm + (sub6a ground_truth_signal_compounds which are KEGG strings)."""
    def _kegg_set(items):
        out = set()
        for it in items:
            k = (it.get("kegg_id") or it.get("kegg_compound_id")) if isinstance(it, dict) else None
            if k:
                out.add(k.replace("KEGG:", ""))
        return out

    upstream_k = _kegg_set(upstream)
    curated_k = _kegg_set(curated)
    task_used = set()
    for t in sub6b:
        for m in t.get("differential_metabolites", []) or []:
            k = m.get("kegg_id")
            if k:
                task_used.add(k.replace("KEGG:", ""))
    # sub6a signal compounds are KEGG strings (no dm)
    for t in sub6a:
        for c in t.get("ground_truth_signal_compounds") or []:
            if isinstance(c, str) and c.strip():
                task_used.add(c.replace("KEGG:", ""))
    return {
        "upstream_size": len(upstream),
        "curated_size": len(curated),
        "upstream_unique_kegg": len(upstream_k),
        "curated_unique_kegg": len(curated_k),
        "task_used_unique_kegg": len(task_used),
        "curated_subset_of_upstream": curated_k.issubset(upstream_k),
        "task_used_subset_of_curated": task_used.issubset(curated_k),
        "task_used_pct_of_curated": (100 * len(task_used) / len(curated_k)) if curated_k else 0,
        "curated_pct_of_upstream": (100 * len(curated_k) / len(upstream_k)) if upstream_k else 0,
    }


def check_p0_5(sub6a: list[dict], excluded: list[str]) -> dict:
    """leakage_filter call check + sub6a source_id falling in exclusion."""
    grep_result = "not_run"
    try:
        # grep for leakage_filter usage in tools/benchmark/sub6/
        r = subprocess.run(
            ["grep", "-rn", "leakage_filter",
             str(WORKTREE / "tools/benchmark/sub6/")],
            capture_output=True, text=True, timeout=10,
        )
        grep_result = r.stdout[:1500] if r.returncode == 0 else "no_match"
    except Exception as e:
        grep_result = f"grep_error:{e}"

    excl_set = set(excluded)
    n_excluded = 0
    n_total = 0
    sample_leaks: list[str] = []
    for t in sub6a:
        for sp in t.get("differential_spectra", []) or []:
            sid = sp.get("source_id")
            if sid:
                n_total += 1
                if sid in excl_set:
                    n_excluded += 1
                    if len(sample_leaks) < 5:
                        sample_leaks.append(sid)
    return {
        "grep_leakage_filter": grep_result,
        "n_spectra_in_sub6a": n_total,
        "n_spectra_in_exclusion_list": n_excluded,
        "leak_rate_pct": (100 * n_excluded / n_total) if n_total else 0,
        "sample_leaks": sample_leaks,
    }


def _signal_set(task: dict) -> frozenset[str]:
    """Return frozenset of canonical signal-compound IDs for the task.
    v2 schema: ground_truth_signal_compounds is a list of strings
    (KEGG cpd IDs like 'C00951')."""
    sigs = task.get("ground_truth_signal_compounds") or []
    out = set()
    for c in sigs:
        if isinstance(c, str) and c.strip():
            out.add(c.strip())
        elif isinstance(c, dict):
            k = (c.get("inchikey_first_block") or c.get("inchikey") or
                 c.get("kegg_id") or c.get("hmdb_id") or c.get("name"))
            if k:
                out.add(str(k).strip())
    return frozenset(out)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def check_p1_1(sub6b: list[dict]) -> dict:
    """63×63 cross-task signal Jaccard matrix; high-overlap stats."""
    sets = {t["task_id"]: _signal_set(t) for t in sub6b}
    tids = list(sets.keys())
    n = len(tids)

    # Save matrix
    mat_path = OUT_DATA / "jaccard_matrix_63x63.csv"
    with mat_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id"] + tids)
        for ti in tids:
            row = [ti] + [f"{_jaccard(sets[ti], sets[tj]):.4f}" for tj in tids]
            w.writerow(row)

    # High-overlap stats
    n_identical = 0
    n_jaccard_ge_09 = 0
    n_jaccard_ge_07 = 0
    identical_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            j_val = _jaccard(sets[tids[i]], sets[tids[j]])
            if j_val == 1.0:
                n_identical += 1
                identical_pairs.append((tids[i], tids[j]))
            if j_val >= 0.9:
                n_jaccard_ge_09 += 1
            if j_val >= 0.7:
                n_jaccard_ge_07 += 1

    # identical-set clusters (transitive closure)
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

    # Save identical clusters
    clu_path = OUT_DATA / "identical_signal_set_groups.csv"
    with clu_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cluster_id", "size", "task_ids", "signal_set_size", "signal_sample"])
        for ci, members in enumerate(multi_clusters):
            sig = sets[members[0]]
            w.writerow([f"clu_{ci+1}", len(members),
                          ";".join(members), len(sig),
                          ";".join(list(sig)[:5])])

    total_pairs = n * (n - 1) // 2
    # 79.4% replication check — "high-correlation pairs"
    pct_ge_09 = 100 * n_jaccard_ge_09 / total_pairs if total_pairs else 0
    pct_ge_07 = 100 * n_jaccard_ge_07 / total_pairs if total_pairs else 0

    # "tasks involved in any Jaccard ≥ 0.7 pair"
    involved = set()
    for i in range(n):
        for j in range(i + 1, n):
            if _jaccard(sets[tids[i]], sets[tids[j]]) >= 0.7:
                involved.add(tids[i]); involved.add(tids[j])
    pct_tasks_in_high_overlap = 100 * len(involved) / n if n else 0

    # N_eff estimates
    n_unique_signal_sets = len(set(sets.values()))
    n_eff_by_pathway = len(set(_pathway_id(t) for t in sub6b if _pathway_id(t)))

    return {
        "n_tasks": n,
        "n_total_pairs": total_pairs,
        "n_identical_pairs": n_identical,
        "n_jaccard_ge_09_pairs": n_jaccard_ge_09,
        "n_jaccard_ge_07_pairs": n_jaccard_ge_07,
        "pct_pairs_ge_09": pct_ge_09,
        "pct_pairs_ge_07": pct_ge_07,
        "n_tasks_in_high_overlap_clusters": len(involved),
        "pct_tasks_in_high_overlap": pct_tasks_in_high_overlap,
        "n_identical_multi_clusters": len(multi_clusters),
        "n_unique_signal_sets": n_unique_signal_sets,
        "n_pathway_clusters": n_eff_by_pathway,
        "identical_clusters_sample": multi_clusters[:5],
    }


def check_p1_2(sub6a: list[dict], curated: list[dict]) -> dict:
    """Per-signal-compound spectra distribution.

    sub6a: signals are KEGG cpd strings; differential_spectra carry
    inchikey_first_block. To map: build KEGG → inchikey_first_block dict
    from curated mammalian pool, then count per (task, signal) the
    spectra in that task whose inchikey_first_block matches the signal's
    inchikey.
    """
    kegg2ik = {}
    for c in curated:
        k = c.get("kegg_id"); ik = c.get("inchikey_first_block")
        if k and ik:
            kegg2ik[k.replace("KEGG:", "")] = ik

    instance_spectra_counts = []
    instance_tasks: list[tuple[str, str, int]] = []   # (task_id, signal_kegg, n_spec)
    n_signal_no_ik_mapping = 0
    for t in sub6a:
        sigs = t.get("ground_truth_signal_compounds") or []
        spectra = t.get("differential_spectra") or []
        spec_iks = [sp.get("inchikey_first_block") for sp in spectra
                     if sp.get("inchikey_first_block")]
        spec_ik_counts = Counter(spec_iks)
        for s in sigs:
            if not isinstance(s, str): continue
            s_clean = s.replace("KEGG:", "")
            ik = kegg2ik.get(s_clean)
            if not ik:
                n_signal_no_ik_mapping += 1
                instance_spectra_counts.append(0)
                instance_tasks.append((t.get("task_id"), s_clean, 0))
                continue
            n = spec_ik_counts.get(ik, 0)
            instance_spectra_counts.append(n)
            instance_tasks.append((t.get("task_id"), s_clean, n))

    if not instance_spectra_counts:
        return {"n_instances": 0, "median_spectra": 0}

    n = len(instance_spectra_counts)
    return {
        "n_instances": n,
        "n_spectra_total": sum(instance_spectra_counts),
        "n_signal_no_ik_mapping": n_signal_no_ik_mapping,
        "mean_spectra_per_instance": sum(instance_spectra_counts) / n,
        "median_spectra": statistics.median(instance_spectra_counts),
        "max_spectra": max(instance_spectra_counts),
        "n_eq_0": sum(1 for c in instance_spectra_counts if c == 0),
        "pct_eq_0": 100 * sum(1 for c in instance_spectra_counts if c == 0) / n,
        "n_eq_1": sum(1 for c in instance_spectra_counts if c == 1),
        "pct_eq_1": 100 * sum(1 for c in instance_spectra_counts if c == 1) / n,
        "n_ge_3": sum(1 for c in instance_spectra_counts if c >= 3),
        "pct_ge_3": 100 * sum(1 for c in instance_spectra_counts if c >= 3) / n,
        "instance_tasks": instance_tasks,
    }


def check_p1_3(sub6b: list[dict]) -> dict:
    """Same-pathway tasks — ground-truth pathway consistency."""
    by = defaultdict(list)
    for t in sub6b:
        pid = _pathway_id(t)
        if pid:
            gp = t.get("ground_truth_pathway") or {}
            by[pid].append({
                "task_id": t.get("task_id"),
                "name": gp.get("name") if isinstance(gp, dict) else None,
                "source": gp.get("source") if isinstance(gp, dict) else None,
            })
    inconsistent = []
    for pid, entries in by.items():
        names = set(e["name"] for e in entries if e["name"])
        if len(names) > 1:
            inconsistent.append({"pathway_id": pid, "names": list(names)})
    return {
        "n_pathway_groups": len(by),
        "n_inconsistent_groups": len(inconsistent),
        "inconsistent_sample": inconsistent[:5],
    }


# -- Extended checks E-1..E-5 ---------------------------------------------


def check_e1(sub6a_path: Path, sub6b_path: Path) -> dict:
    """JSONL structure integrity."""
    def _scan(p: Path, label: str) -> dict:
        ok_lines, err_lines = 0, []
        task_ids, dups = set(), set()
        with p.open() as f:
            for i, line in enumerate(f, 1):
                try:
                    obj = json.loads(line)
                except Exception as e:
                    err_lines.append((i, str(e)))
                    continue
                ok_lines += 1
                tid = obj.get("task_id")
                if tid and tid in task_ids:
                    dups.add(tid)
                if tid:
                    task_ids.add(tid)
        return {
            "label": label,
            "n_lines": ok_lines + len(err_lines),
            "n_valid_json": ok_lines,
            "n_parse_errors": len(err_lines),
            "parse_error_sample": err_lines[:3],
            "n_unique_task_ids": len(task_ids),
            "n_dup_task_ids": len(dups),
            "sample_dups": list(dups)[:3],
        }
    return {"sub6a": _scan(sub6a_path, "sub6a"),
            "sub6b": _scan(sub6b_path, "sub6b")}


def check_e2(sub6b: list[dict]) -> dict:
    """signal compounds (KEGG strings) should be subset of differential
    metabolites' KEGG ID set."""
    n_mismatch = 0
    mismatch_sample = []
    for t in sub6b:
        sigs = {s.replace("KEGG:", "") for s in (t.get("ground_truth_signal_compounds") or [])
                  if isinstance(s, str)}
        dm = t.get("differential_metabolites") or []
        diff_keggs = {m.get("kegg_id", "").replace("KEGG:", "") for m in dm
                       if isinstance(m, dict) and m.get("kegg_id")}
        not_in = sigs - diff_keggs
        if not_in:
            n_mismatch += 1
            if len(mismatch_sample) < 3:
                mismatch_sample.append({"task_id": t.get("task_id"),
                                          "n_orphan": len(not_in),
                                          "sample": list(not_in)[:3]})
    return {
        "n_tasks": len(sub6b),
        "n_mismatch_tasks": n_mismatch,
        "pct_mismatch": 100 * n_mismatch / len(sub6b) if sub6b else 0,
        "mismatch_sample": mismatch_sample,
    }


def check_e3(sub6b: list[dict]) -> dict:
    """Ground-truth pathway external_id presence diagnostic.

    Read-only — count distinct external_id values + check the prefix
    distribution (RAMP_P_, hsa, R-HSA-, SMP, WP). Actual queries to
    KEGG/Reactome are out of scope here (would require network)."""
    pids = [_pathway_id(t) for t in sub6b]
    pids = [p for p in pids if p]
    prefix = Counter()
    for p in pids:
        # Crude prefix classifier
        if p.startswith("RAMP_P_"): prefix["RaMP"] += 1
        elif p.startswith("hsa") or "KEGG" in p: prefix["KEGG"] += 1
        elif p.startswith("R-HSA-") or p.startswith("REACT"): prefix["Reactome"] += 1
        elif p.startswith("SMP"): prefix["SMPDB"] += 1
        elif p.startswith("WP"): prefix["WikiPathways"] += 1
        else: prefix["other"] += 1
    return {
        "n_pids_total": len(pids),
        "n_pids_unique": len(set(pids)),
        "prefix_distribution": dict(prefix),
        "sample_unique_pids": list(set(pids))[:5],
    }


def check_e4(sub6b: list[dict]) -> dict:
    """noise compounds (KEGG strings) should not overlap signal compounds (KEGG strings)."""
    n_violate = 0
    samples = []
    for t in sub6b:
        sigs = {s.replace("KEGG:", "") for s in (t.get("ground_truth_signal_compounds") or [])
                  if isinstance(s, str)}
        noises = {s.replace("KEGG:", "") for s in (t.get("ground_truth_noise_compounds") or [])
                    if isinstance(s, str)}
        ovl = sigs & noises
        if ovl:
            n_violate += 1
            if len(samples) < 3:
                samples.append({"task_id": t.get("task_id"),
                                  "overlap_size": len(ovl),
                                  "sample": list(ovl)[:3]})
    return {
        "n_tasks": len(sub6b),
        "n_violating_tasks": n_violate,
        "pct_violating": 100 * n_violate / len(sub6b) if sub6b else 0,
        "sample_violations": samples,
    }


def check_e5(sub6a: list[dict], sub6b: list[dict]) -> dict:
    """Sub-6A ground_truth_pathway ∩ Sub-6B ground_truth_pathway."""
    a_pids = {_pathway_id(t) for t in sub6a if _pathway_id(t)}
    b_pids = {_pathway_id(t) for t in sub6b if _pathway_id(t)}
    overlap = a_pids & b_pids
    return {
        "n_sub6a_pids": len(a_pids),
        "n_sub6b_pids": len(b_pids),
        "n_overlap_pids": len(overlap),
        "overlap_sample": list(overlap)[:10],
    }


# -- Deep dives ----------------------------------------------------------


def deep_p1_1(sub6b: list[dict], p1_1: dict) -> dict:
    """P1-1 independence analysis: N_eff variants + SE multipliers."""
    n = p1_1["n_tasks"]
    n_uniq = p1_1["n_unique_signal_sets"]
    n_pw = p1_1["n_pathway_clusters"]
    # If we treat each pathway cluster as a single sample
    # SE multiplier ≈ sqrt(N_naive / N_eff)
    import math
    se_mult_pw = math.sqrt(n / n_pw) if n_pw else None
    se_mult_uniq = math.sqrt(n / n_uniq) if n_uniq else None
    return {
        "n_naive": n,
        "n_eff_by_unique_signal_set": n_uniq,
        "n_eff_by_pathway_cluster": n_pw,
        "n_identical_multi_clusters": p1_1["n_identical_multi_clusters"],
        "se_multiplier_under_pathway_cluster": se_mult_pw,
        "se_multiplier_under_unique_set": se_mult_uniq,
        "pct_tasks_in_high_overlap": p1_1["pct_tasks_in_high_overlap"],
    }


def deep_p1_2(sub6a: list[dict], p1_2: dict, curated: list[dict]) -> dict:
    """P1-2 sparsity deep dive on the v2 schema (per-task aggregate)."""
    kegg2ik = {}
    for c in curated:
        k = c.get("kegg_id"); ik = c.get("inchikey_first_block")
        if k and ik:
            kegg2ik[k.replace("KEGG:", "")] = ik

    by_task = []
    for t in sub6a:
        sigs = [s.replace("KEGG:", "") for s in (t.get("ground_truth_signal_compounds") or [])
                 if isinstance(s, str)]
        spec_iks = Counter(sp.get("inchikey_first_block") for sp in (t.get("differential_spectra") or [])
                              if sp.get("inchikey_first_block"))
        per_signal_counts = []
        for s in sigs:
            ik = kegg2ik.get(s)
            per_signal_counts.append(spec_iks.get(ik, 0) if ik else 0)
        by_task.append({
            "task_id": t.get("task_id"),
            "n_signal_inst": len(sigs),
            "n_inst_with_ge1_spectrum": sum(1 for c in per_signal_counts if c >= 1),
            "n_inst_with_ge3_spectra": sum(1 for c in per_signal_counts if c >= 3),
            "total_spectra_in_task": sum(per_signal_counts),
            "n_total_spectra_in_task_dispersal": len(t.get("differential_spectra") or []),
        })

    sorted_by_count = sorted(by_task, key=lambda r: r["total_spectra_in_task"])
    worst_5 = sorted_by_count[:5]
    n_task_ok_ge1 = sum(1 for r in by_task if r["n_inst_with_ge1_spectrum"] >= 3)
    n_task_ok_ge3 = sum(1 for r in by_task if r["n_inst_with_ge3_spectra"] >= 3)
    n_task_all_ge2 = sum(
        1 for r in by_task
        if r["n_signal_inst"] > 0 and r["n_inst_with_ge1_spectrum"] == r["n_signal_inst"]
        and r["total_spectra_in_task"] >= 2 * r["n_signal_inst"]
    )

    return {
        "n_total_instances": p1_2["n_instances"],
        "n_inst_eq_0_spectra": p1_2.get("n_eq_0", 0),
        "n_inst_eq_1_spectrum": p1_2.get("n_eq_1", 0),
        "n_inst_ge_3_spectra": p1_2.get("n_ge_3", 0),
        "n_signal_no_ik_mapping": p1_2.get("n_signal_no_ik_mapping", 0),
        "n_tasks_total": len(sub6a),
        "n_tasks_3plus_compound_with_ge1_spectrum": n_task_ok_ge1,
        "n_tasks_3plus_compound_with_ge3_spectra": n_task_ok_ge3,
        "n_tasks_all_instances_avg_ge2_spectra": n_task_all_ge2,
        "worst_5_tasks_by_total_spectra": worst_5,
    }


# -- Main runner ----------------------------------------------------------


def main() -> None:
    print("=" * 60)
    print("Sub-6 v2 Benchmark — INDEPENDENT AUDIT")
    print("=" * 60)

    # 0. MD5
    md5 = check_md5_provenance()
    print("\n[0] MD5 provenance")
    for f, info in md5["per_file"].items():
        if info.get("error"):
            print(f"  ERROR {f}: {info['error']}")
        else:
            mark = "✓" if info["match"] else "✗"
            print(f"  {mark} {f}  src={info['resolved_from']}  size={info['size_bytes']}")
    print(f"  all_match: {md5['all_match']}")
    for a in md5["anomalies"]:
        print(f"  ANOMALY: {a}")

    if not md5["all_match"]:
        print("\nMD5 not all-match. Halting per stop condition #1.")
        return

    # 1. Load
    sub6a = load_jsonl("data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl")
    sub6b = load_jsonl("data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl")
    upstream = load_jsonl("data/processed/hmdb_candidates_npc_classified_v2.jsonl")
    curated = load_jsonl("data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl")
    excluded = load_json("data/processed/nm002_excluded_gnps_ids.json")
    if isinstance(excluded, dict):
        excluded = excluded.get("excluded_ids") or list(excluded.keys())
    print(f"\nLoaded sub6a={len(sub6a)} sub6b={len(sub6b)} "
          f"upstream={len(upstream)} curated={len(curated)} excluded={len(excluded)}")

    results = {"md5": md5}

    print("\n[1] Original 8 checks (independent re-implementation)")
    results["p0_1"] = check_p0_1(sub6a, sub6b)
    print(f"  P0-1 noise:        sub6b zero={results['p0_1']['sub6b']['noise_zero_count']}/{results['p0_1']['sub6b']['n_tasks']}  sub6a zero={results['p0_1']['sub6a']['noise_zero_count']}/{results['p0_1']['sub6a']['n_tasks']}")

    results["p0_2"] = check_p0_2(sub6b)
    print(f"  P0-2 pathway:      n_pathways={results['p0_2']['n_pathways']}  singletons={results['p0_2']['n_singletons']}")

    results["p0_3"] = check_p0_3(sub6a, excluded)
    print(f"  P0-3 gnps excl:    n_spec={results['p0_3']['n_spectra_total']}  excluded_overlap={results['p0_3']['n_excluded_overlap']}")

    results["p0_4"] = check_p0_4(upstream, curated, sub6b, sub6a)
    print(f"  P0-4 pool util:    upstream={results['p0_4']['upstream_unique_kegg']} curated={results['p0_4']['curated_unique_kegg']} task_used={results['p0_4']['task_used_unique_kegg']}")

    results["p0_5"] = check_p0_5(sub6a, excluded)
    print(f"  P0-5 leakage:      grep_match={'leakage_filter' in str(results['p0_5']['grep_leakage_filter'])}  leaks={results['p0_5']['n_spectra_in_exclusion_list']}/{results['p0_5']['n_spectra_in_sub6a']}")

    results["p1_1"] = check_p1_1(sub6b)
    print(f"  P1-1 cross-task:   identical_pairs={results['p1_1']['n_identical_pairs']}  ge09_pairs={results['p1_1']['n_jaccard_ge_09_pairs']}  pct_tasks_high={results['p1_1']['pct_tasks_in_high_overlap']:.1f}%")

    results["p1_2"] = check_p1_2(sub6a, curated)
    print(f"  P1-2 spectra:      n_inst={results['p1_2']['n_instances']}  median={results['p1_2'].get('median_spectra')}  pct_ge_3={results['p1_2'].get('pct_ge_3', 0):.1f}%")

    results["p1_3"] = check_p1_3(sub6b)
    print(f"  P1-3 same-pw GT:   n_pw_groups={results['p1_3']['n_pathway_groups']}  inconsistent={results['p1_3']['n_inconsistent_groups']}")

    print("\n[2] Extended checks (E-1 to E-5)")
    results["e1"] = check_e1(
        _resolve_path("data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl"),
        _resolve_path("data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl"),
    )
    print(f"  E-1 jsonl structure: 6a={results['e1']['sub6a']['n_valid_json']}/{results['e1']['sub6a']['n_lines']}  6b={results['e1']['sub6b']['n_valid_json']}/{results['e1']['sub6b']['n_lines']}  dups_6a={results['e1']['sub6a']['n_dup_task_ids']}  dups_6b={results['e1']['sub6b']['n_dup_task_ids']}")

    results["e2"] = check_e2(sub6b)
    print(f"  E-2 signal⊆diff:   mismatch={results['e2']['n_mismatch_tasks']}/{results['e2']['n_tasks']} ({results['e2']['pct_mismatch']:.1f}%)")

    results["e3"] = check_e3(sub6b)
    print(f"  E-3 gt_pid:        n_unique={results['e3']['n_pids_unique']}  prefixes={results['e3']['prefix_distribution']}")

    results["e4"] = check_e4(sub6b)
    print(f"  E-4 noise⊥signal:  violating={results['e4']['n_violating_tasks']}/{results['e4']['n_tasks']} ({results['e4']['pct_violating']:.1f}%)")

    results["e5"] = check_e5(sub6a, sub6b)
    print(f"  E-5 6a⊥6b pids:    overlap={results['e5']['n_overlap_pids']}  (6a={results['e5']['n_sub6a_pids']} 6b={results['e5']['n_sub6b_pids']})")

    print("\n[3] Deep dives")
    results["deep_p1_1"] = deep_p1_1(sub6b, results["p1_1"])
    print(f"  P1-1 N_eff:        naive={results['deep_p1_1']['n_naive']}  unique_set={results['deep_p1_1']['n_eff_by_unique_signal_set']}  pathway={results['deep_p1_1']['n_eff_by_pathway_cluster']}  SE_mult_pw={results['deep_p1_1']['se_multiplier_under_pathway_cluster']:.2f}×")

    results["deep_p1_2"] = deep_p1_2(sub6a, results["p1_2"], curated)
    print(f"  P1-2 task-level:   3+cmp_with_spec={results['deep_p1_2']['n_tasks_3plus_compound_with_ge1_spectrum']}/{len(sub6a)}  robust(3+cmp_w_3spec)={results['deep_p1_2']['n_tasks_3plus_compound_with_ge3_spectra']}/{len(sub6a)}")

    # Dump
    out_json = OUT_DATA / "check_results.json"
    out_json.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nwrote {out_json}")


if __name__ == "__main__":
    main()
