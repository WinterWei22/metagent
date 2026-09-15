"""W7 D1-D2 — Gate-2 metric variants V1 / V2 / V3.

All three variants follow the W6 D4 cohort harness shape:

    metric_v{N}_cohort(rows, ...) -> {
        "cond_a_supported_pct": float,
        "cond_b_supported_pct": float,
        "delta_pp": float,
        "metric_pass": bool,                            # ≥ 3 pp lift
        "n_tasks": int,
        "cond_a": {"mean_precision": ..., "mean_recall": ..., "precision_ci95": (lo, hi)},
        "cond_b": {...},
        "delta_precision_mean": float,
        "delta_recall_mean": float,
        "sign_test_pos": int, "sign_test_neg": int,
        "sign_test_p": float,
        "metric_2_pass": bool,
        "per_task_deltas": [...],
    }

  V1: token-Jaccard ≥ 0.5 fuzzy intersection of pathway names across paradigms.
  V2: ground-truth pathway must be supported by a Cond B pathway whose
      *member-compound set* overlaps the input differential metabolites
      by ≥ min_overlap (paradigm-agnostic — uses pathway_members.sqlite).
  V3: paradigm-weighted soft score — rank-weighted sum across all 5 methods.
"""
from __future__ import annotations
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from concord.analyze.pathway_match import (
    pathway_name_overlap, best_matching_rank, _tokenize,
)
from concord.analyze.paradigm_consensus import (
    ALL_METHODS, ORA_METHODS, MZ_DIRECT_METHODS, NETWORK_METHODS,
    paradigm_for,
)
from concord.etl.pathway_members_etl import load_pathway_members


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()[:64]


def _top_pathway_names(row: dict, method: str) -> list[str]:
    block = row.get(method)
    if not block or block.get("error"):
        return []
    return [p["pathway_name"] for p in block.get("pathways", [])]


def _bootstrap_ci(xs: list[float], n_boot: int = 1000, seed: int = 42,
                  alpha: float = 0.05) -> tuple[float, float]:
    if not xs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(xs)
    boots = []
    for _ in range(n_boot):
        s = [rng.choice(xs) for _ in range(n)]
        boots.append(sum(s) / n)
    boots.sort()
    lo = boots[int(alpha / 2 * n_boot)]
    hi = boots[int((1 - alpha / 2) * n_boot)]
    return (lo, hi)


def _sign_test_two_sided(per_task_deltas: list[float]) -> tuple[int, int, float]:
    pos = sum(1 for d in per_task_deltas if d > 0)
    neg = sum(1 for d in per_task_deltas if d < 0)
    n_eff = pos + neg
    if n_eff == 0:
        return pos, neg, 1.0
    k = max(pos, neg)
    from math import comb
    tail = sum(comb(n_eff, i) for i in range(k, n_eff + 1)) / (2 ** n_eff)
    return pos, neg, min(1.0, 2 * tail)


def _aggregate_cohort(per_task: list[dict],
                      metric_label: str = "") -> dict:
    """Common cond_a / cond_b → cohort summary aggregation."""
    mean = lambda xs: (sum(xs) / len(xs)) if xs else 0.0
    a_prec = [t["a_precision"] for t in per_task]
    b_prec = [t["b_precision"] for t in per_task]
    a_rec = [t["a_recall"] for t in per_task]
    b_rec = [t["b_recall"] for t in per_task]
    pos, neg, p = _sign_test_two_sided([t["delta_precision"] for t in per_task])
    return {
        "metric_label": metric_label,
        "n_tasks": len(per_task),
        "cond_a": {"mean_precision": mean(a_prec), "mean_recall": mean(a_rec),
                    "precision_ci95": _bootstrap_ci(a_prec),
                    "recall_ci95": _bootstrap_ci(a_rec)},
        "cond_b": {"mean_precision": mean(b_prec), "mean_recall": mean(b_rec),
                    "precision_ci95": _bootstrap_ci(b_prec),
                    "recall_ci95": _bootstrap_ci(b_rec)},
        "delta_precision_mean": mean(b_prec) - mean(a_prec),
        "delta_recall_mean": mean(b_rec) - mean(a_rec),
        "sign_test_pos": pos, "sign_test_neg": neg, "sign_test_p": p,
        "metric_pass": (
            (mean(b_prec) - mean(a_prec)) * 100.0 >= 3.0
            and (mean(b_rec) - mean(a_rec)) * 100.0 >= -5.0
        ),
        "per_task_deltas": per_task,
    }


# ---------------------------------------------------------------------------
# V1 — token-Jaccard fuzzy intersection
# ---------------------------------------------------------------------------


def _fuzzy_consensus_top_v1(row: dict,
                              threshold: float = 0.5,
                              top_n: int = 10) -> list[str]:
    """Pathways whose name token-Jaccard ≥ threshold against at least one
    ORA top-10 *and* at least one non-ORA top-10 pathway name.
    Returned ranked by total method support count.
    """
    ora_names = []
    for m in ORA_METHODS:
        ora_names.extend(_top_pathway_names(row, m))
    nonora_names = []
    for m in MZ_DIRECT_METHODS + NETWORK_METHODS:
        nonora_names.extend(_top_pathway_names(row, m))
    if not ora_names or not nonora_names:
        return []

    # Candidate names = union of top-10 across all methods (dedupe).
    # For each candidate, check if it overlaps ≥1 ORA name AND ≥1 non-ORA name.
    all_names_unique = list({n for n in ora_names + nonora_names})
    chosen: list[tuple[str, int]] = []
    for cand in all_names_unique:
        if any(pathway_name_overlap(cand, a, threshold) for a in ora_names) \
           and any(pathway_name_overlap(cand, b, threshold) for b in nonora_names):
            # support = number of methods whose top-10 name set fuzzy-matches cand
            support = sum(
                1 for m in ALL_METHODS
                if any(pathway_name_overlap(cand, n, threshold) for n in _top_pathway_names(row, m))
            )
            chosen.append((cand, support))
    chosen.sort(key=lambda x: -x[1])
    return [c for c, _ in chosen[:top_n]]


def metric_v1_cohort(rows: list[dict], threshold: float = 0.5) -> dict:
    """V1 cond_a = RaMP top-10 vs GT (name-fuzzy);
       cond_b = V1 fuzzy consensus top-10 vs GT (name-fuzzy)."""
    per_task = []
    for row in rows:
        gt = row.get("ground_truth_pathway_name", "")
        a_top = _top_pathway_names(row, "ramp")[:10]
        b_top = _fuzzy_consensus_top_v1(row, threshold=threshold, top_n=10)
        a_hit = best_matching_rank(gt, a_top, threshold=threshold) is not None
        b_hit = best_matching_rank(gt, b_top, threshold=threshold) is not None
        per_task.append({
            "task_id": row.get("task_id"),
            "a_precision": 1.0 if a_hit else 0.0,
            "a_recall": 1.0 if a_hit else 0.0,
            "b_precision": 1.0 if b_hit else 0.0,
            "b_recall": 1.0 if b_hit else 0.0,
            "delta_precision": (1.0 if b_hit else 0.0) - (1.0 if a_hit else 0.0),
            "delta_recall": (1.0 if b_hit else 0.0) - (1.0 if a_hit else 0.0),
        })
    return _aggregate_cohort(per_task, metric_label="V1_fuzzy_intersection")


# ---------------------------------------------------------------------------
# V2 — compound-level pathway-membership overlap with input differentials
# ---------------------------------------------------------------------------


def _consensus_top_v2(row: dict, input_chebi_set: set[str],
                       min_overlap: int = 2, top_n: int = 10) -> list[str]:
    """Pathways in any method's top-10 whose stored member set overlaps
    the input differential metabolites by ≥ ``min_overlap`` ChEBI IDs.

    Pathway membership is loaded via ``load_pathway_members`` keyed on
    a *fuzzy* slug of the pathway_name (W6 D5 finding: pathway names
    vary across methods, so we try every candidate slug and union the
    matching member sets).
    """
    all_names = list({
        n for m in ALL_METHODS for n in _top_pathway_names(row, m)
    })
    # Use both HUMAN1 and RECON2 namespaces — coverage is union.
    chosen: list[tuple[str, int]] = []
    for cand in all_names:
        cand_slug = _slug(cand)
        members = (load_pathway_members("HUMAN1", cand_slug)
                   | load_pathway_members("RECON2", cand_slug))
        overlap = len(members & input_chebi_set)
        if overlap >= min_overlap:
            # support = methods endorsing this name in top-10
            support = sum(
                1 for m in ALL_METHODS
                if any(cand == n for n in _top_pathway_names(row, m))
            )
            chosen.append((cand, support * 10 + overlap))
    chosen.sort(key=lambda x: -x[1])
    return [c for c, _ in chosen[:top_n]]


def metric_v2_cohort(rows: list[dict],
                      task_input_chebi: dict[str, set[str]],
                      min_overlap: int = 2,
                      threshold: float = 0.5) -> dict:
    """V2 cond_a = RaMP top-10 vs GT (name-fuzzy, unchanged baseline);
       cond_b = V2 compound-supported pathways vs GT (name-fuzzy).

    Args:
        task_input_chebi: ``task_id → set of input differential metabolite
            CHEBI: IDs``. Used for the V2 pathway-membership overlap test.
    """
    per_task = []
    for row in rows:
        gt = row.get("ground_truth_pathway_name", "")
        tid = row.get("task_id", "")
        inp = task_input_chebi.get(tid, set())
        a_top = _top_pathway_names(row, "ramp")[:10]
        b_top = _consensus_top_v2(row, inp, min_overlap=min_overlap, top_n=10)
        a_hit = best_matching_rank(gt, a_top, threshold=threshold) is not None
        b_hit = best_matching_rank(gt, b_top, threshold=threshold) is not None
        per_task.append({
            "task_id": tid,
            "a_precision": 1.0 if a_hit else 0.0,
            "a_recall": 1.0 if a_hit else 0.0,
            "b_precision": 1.0 if b_hit else 0.0,
            "b_recall": 1.0 if b_hit else 0.0,
            "delta_precision": (1.0 if b_hit else 0.0) - (1.0 if a_hit else 0.0),
            "delta_recall": (1.0 if b_hit else 0.0) - (1.0 if a_hit else 0.0),
        })
    return _aggregate_cohort(per_task, metric_label="V2_compound_membership")


# ---------------------------------------------------------------------------
# V3 — paradigm-weighted soft score (rank-weighted union, no intersection)
# ---------------------------------------------------------------------------


def _weighted_top_v3(row: dict, top_n: int = 10) -> list[str]:
    """Each pathway gets a weighted score = Σ_method (1 / (rank + 1)).

    No paradigm-intersection requirement; this is a *soft union* — a
    pathway ranked #1 by even a single strong method can enter top-10.
    Paradigm coverage is implicit in the weights (more methods supporting
    → higher score), but no hard veto on single-paradigm pathways.
    """
    scores: dict[str, float] = defaultdict(float)
    for m in ALL_METHODS:
        for rank, name in enumerate(_top_pathway_names(row, m)[:10]):
            scores[name] += 1.0 / (rank + 1)
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [n for n, _ in ranked[:top_n]]


def metric_v3_cohort(rows: list[dict], threshold: float = 0.5) -> dict:
    """V3 cond_a = RaMP top-10 vs GT (name-fuzzy);
       cond_b = V3 rank-weighted soft union top-10 vs GT (name-fuzzy)."""
    per_task = []
    for row in rows:
        gt = row.get("ground_truth_pathway_name", "")
        a_top = _top_pathway_names(row, "ramp")[:10]
        b_top = _weighted_top_v3(row, top_n=10)
        a_hit = best_matching_rank(gt, a_top, threshold=threshold) is not None
        b_hit = best_matching_rank(gt, b_top, threshold=threshold) is not None
        per_task.append({
            "task_id": row.get("task_id"),
            "a_precision": 1.0 if a_hit else 0.0,
            "a_recall": 1.0 if a_hit else 0.0,
            "b_precision": 1.0 if b_hit else 0.0,
            "b_recall": 1.0 if b_hit else 0.0,
            "delta_precision": (1.0 if b_hit else 0.0) - (1.0 if a_hit else 0.0),
            "delta_recall": (1.0 if b_hit else 0.0) - (1.0 if a_hit else 0.0),
        })
    return _aggregate_cohort(per_task, metric_label="V3_weighted_soft_union")


def variant_verdict(m: dict) -> str:
    """One-variant cohort verdict: GREEN ≥ +3pp & sign p < 0.1; RED < 0; YELLOW else."""
    delta_pp = m["delta_precision_mean"] * 100
    p = m["sign_test_p"]
    if delta_pp >= 3.0 and p < 0.1:
        return "GREEN"
    if delta_pp < 0:
        return "RED"
    return "YELLOW"
