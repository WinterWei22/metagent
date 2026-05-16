"""W6 D3/D4 — paradigm-consensus + cross-paradigm Gate-2 metrics.

Paradigm assignment (W6 prompt §D3):
  - ORA:        {sspa_ora, ramp, PSEA}
  - m/z-direct: {mummichog}
  - Network:    {FELLA}

Consensus level per (task, pathway-name):
  - Level 0  unsupported
  - Level 1  ORA-only support
  - Level 2  m/z-direct only
  - Level 3  Network only
  - Level 4  cross-paradigm (≥ 2 paradigms support)
  - Level 5  all-3-paradigm consensus

Metric 1 reports the Level distribution / supported %.
Metric 2 uses Cooke ground truth (name-fuzzy via
``concord.analyze.pathway_match``) to score precision@10 / recall@10
for two conditions:
  A: RaMP only top-10
  B: cross-paradigm consensus top-10 (pathways in ORA-top10 ∩ non-ORA-top10),
     ranked by total method support count.
"""
from __future__ import annotations
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable

from concord.analyze.pathway_match import pathway_name_overlap, best_matching_rank

ORA_METHODS = ("sspa_ora", "ramp", "PSEA")
MZ_DIRECT_METHODS = ("mummichog",)
NETWORK_METHODS = ("FELLA",)
ALL_METHODS = ORA_METHODS + MZ_DIRECT_METHODS + NETWORK_METHODS


def paradigm_for(method: str) -> str:
    if method in ORA_METHODS:
        return "ora"
    if method in MZ_DIRECT_METHODS:
        return "mz"
    if method in NETWORK_METHODS:
        return "net"
    raise ValueError(method)


def _top_pathways(task_row: dict, method: str) -> list[dict]:
    block = task_row.get(method)
    if not block or block.get("error"):
        return []
    return block.get("pathways", []) or []


def consensus_levels(task_row: dict) -> dict[str, int]:
    """For each pathway *name* appearing in any method's top-10, return
    its consensus level (0-5). Returns dict ``pathway_name → level``.
    """
    paradigm_support: dict[str, set[str]] = {}
    for method in ALL_METHODS:
        for p in _top_pathways(task_row, method):
            pname = p["pathway_name"]
            paradigm_support.setdefault(pname, set()).add(paradigm_for(method))
    out = {}
    for pname, paradigms in paradigm_support.items():
        if len(paradigms) == 3:
            out[pname] = 5
        elif len(paradigms) >= 2:
            out[pname] = 4
        elif "ora" in paradigms:
            out[pname] = 1
        elif "mz" in paradigms:
            out[pname] = 2
        elif "net" in paradigms:
            out[pname] = 3
        else:
            out[pname] = 0
    return out


# ---------------------------------------------------------------------------
# Metric 1 — paradigm-aware supported %
# ---------------------------------------------------------------------------


def metric_1_ground_truth_consensus_level(task_row: dict) -> int:
    """Return the maximum consensus level reached by any pathway in any
    method's top-10 whose name fuzzy-matches the ground-truth pathway.

    0 = ground truth not supported by any method
    1 = supported by ORA only
    2 = supported by m/z-direct only
    3 = supported by Network only
    4 = supported by ≥ 2 paradigms (cross-paradigm)
    5 = supported by all 3 paradigms
    """
    gt_name = task_row.get("ground_truth_pathway_name", "")
    if not gt_name:
        return 0
    levels = consensus_levels(task_row)
    best = 0
    for pname, lvl in levels.items():
        if pathway_name_overlap(gt_name, pname):
            best = max(best, lvl)
    return best


def metric_1_cohort(rows: list[dict]) -> dict:
    """Per-cohort Metric 1: distribution of ground-truth support levels.

    Condition A: Level 1 ratio (ORA-only support — proxy for the RaMP baseline,
                 since RaMP itself is in ORA cluster).
    Condition B: (Level 4 + Level 5) ratio (cross-paradigm consensus
                 includes the ground-truth pathway).
    """
    levels = [metric_1_ground_truth_consensus_level(r) for r in rows]
    n = len(levels) or 1
    counts = {lvl: levels.count(lvl) for lvl in range(6)}
    cond_a = counts[1] / n
    cond_b = (counts[4] + counts[5]) / n
    return {
        "n_tasks": len(rows),
        "level_counts": counts,
        "cond_a_supported_pct": cond_a,
        "cond_b_supported_pct": cond_b,
        "delta_pp": (cond_b - cond_a) * 100.0,
        "metric_1_pass": (cond_b * 100.0) >= (cond_a * 100.0 + 3.0),
    }


# ---------------------------------------------------------------------------
# Metric 2 — precision/recall vs Cooke ground truth (name-fuzzy)
# ---------------------------------------------------------------------------


def ramp_top10_names(row: dict) -> list[str]:
    return [p["pathway_name"] for p in _top_pathways(row, "ramp")]


def cross_paradigm_consensus_top10(row: dict) -> list[str]:
    """Top-10 pathways supported by ≥ 2 paradigms (Level 4/5), ranked
    by total method support count (more methods = higher rank).
    """
    levels = consensus_levels(row)
    # pathways in Level 4 or 5
    candidates = [pname for pname, lvl in levels.items() if lvl >= 4]
    if not candidates:
        return []
    # method-support count
    n_methods_supporting: dict[str, int] = {}
    for method in ALL_METHODS:
        names = [p["pathway_name"] for p in _top_pathways(row, method)]
        for pname in candidates:
            if pname in names:
                n_methods_supporting[pname] = n_methods_supporting.get(pname, 0) + 1
    return sorted(candidates,
                  key=lambda p: -n_methods_supporting.get(p, 0))[:10]


def per_task_precision_recall(top_names: list[str], gt_name: str) -> tuple[float, float, bool]:
    """precision@10 = (1 if any top10 name fuzzy-matches gt else 0)
       recall@10 = same (single ground-truth pathway).
       Both are 0/1 here because Cooke ground truth is single-pathway.

    Returns (precision, recall, hit).
    """
    if not top_names:
        return 0.0, 0.0, False
    rank = best_matching_rank(gt_name, top_names)
    hit = rank is not None
    return (1.0 if hit else 0.0,
            1.0 if hit else 0.0,
            hit)


def metric_2_cohort(rows: list[dict], n_bootstrap: int = 1000,
                     seed: int = 42) -> dict:
    """Per-cohort Metric 2: precision/recall + bootstrap CI + sign test.

    Condition A: RaMP top-10 (baseline)
    Condition B: cross-paradigm consensus top-10
    """
    per_task = []
    for row in rows:
        gt = row.get("ground_truth_pathway_name", "")
        a_top = ramp_top10_names(row)
        b_top = cross_paradigm_consensus_top10(row)
        pa, ra, ha = per_task_precision_recall(a_top, gt)
        pb, rb, hb = per_task_precision_recall(b_top, gt)
        per_task.append({"task_id": row.get("task_id"),
                          "a_hit": ha, "b_hit": hb,
                          "a_precision": pa, "b_precision": pb,
                          "a_recall": ra, "b_recall": rb,
                          "delta_precision": pb - pa,
                          "delta_recall": rb - ra})

    n = len(per_task) or 1
    a_prec = [t["a_precision"] for t in per_task]
    b_prec = [t["b_precision"] for t in per_task]
    a_rec = [t["a_recall"] for t in per_task]
    b_rec = [t["b_recall"] for t in per_task]
    mean = lambda xs: sum(xs)/len(xs) if xs else 0.0

    # Bootstrap CIs
    rng = random.Random(seed)
    def _boot(xs, k=n_bootstrap):
        if not xs:
            return (0.0, 0.0)
        means = [mean([rng.choice(xs) for _ in range(len(xs))]) for _ in range(k)]
        means.sort()
        lo = means[int(0.025 * k)]
        hi = means[int(0.975 * k)]
        return (lo, hi)

    # Sign test on per-task delta_precision (only non-zero deltas count)
    pos = sum(1 for t in per_task if t["delta_precision"] > 0)
    neg = sum(1 for t in per_task if t["delta_precision"] < 0)
    n_eff = pos + neg
    # Two-sided sign test approximation via binomial P[X ≥ max(pos,neg)] under H0=0.5
    if n_eff == 0:
        sign_p = 1.0
    else:
        k = max(pos, neg)
        # binomial CDF tail
        from math import comb
        tail = sum(comb(n_eff, i) for i in range(k, n_eff+1)) / (2 ** n_eff)
        sign_p = min(1.0, 2 * tail)

    return {
        "n_tasks": n,
        "cond_a": {"mean_precision": mean(a_prec), "mean_recall": mean(a_rec),
                    "precision_ci95": _boot(a_prec), "recall_ci95": _boot(a_rec)},
        "cond_b": {"mean_precision": mean(b_prec), "mean_recall": mean(b_rec),
                    "precision_ci95": _boot(b_prec), "recall_ci95": _boot(b_rec)},
        "delta_precision_mean": mean(b_prec) - mean(a_prec),
        "delta_recall_mean": mean(b_rec) - mean(a_rec),
        "sign_test_pos": pos, "sign_test_neg": neg,
        "sign_test_n_eff": n_eff, "sign_test_p": sign_p,
        "metric_2_pass": (
            (mean(b_prec) - mean(a_prec)) * 100.0 >= 3.0
            and (mean(b_rec) - mean(a_rec)) * 100.0 >= -5.0
        ),
        "per_task_deltas": per_task,
    }


def cohort_verdict(m1: dict, m2: dict) -> str:
    """Combine Metric 1 + Metric 2 pass into a cohort-level GREEN/YELLOW/RED."""
    p1, p2 = m1["metric_1_pass"], m2["metric_2_pass"]
    if p1 and p2:
        return "GREEN"
    if p1 or p2:
        return "YELLOW"
    return "RED"
