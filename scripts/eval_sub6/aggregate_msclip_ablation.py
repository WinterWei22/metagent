"""Aggregate Phase 6.1 MS-CLIP ablation runs into a paper-ready CSV.

Reads two ablation narratives JSONL (Config A: gnps only; Config C:
gnps+inhouse fused) plus the v2 task JSONL (used for the
``pathway_source`` per-bucket stratification — v2 task JSON does not
carry a compound-level metabolic class, so ``pathway_source`` is the
most visible, unambiguous categorical field).

Emits ``data/paper_figures/phase6_msclip_ablation.csv`` with main metrics
+ per-bucket id_acc + per-spectrum win/loss vs Config A. Prints a
summary table to stdout.

Usage:
    python scripts/eval_sub6/aggregate_msclip_ablation.py \\
        --gnps-only data/eval/sub6/v2_msclip_ablation/gnps_only/sub6a_narratives.jsonl \\
        --fused     data/eval/sub6/v2_msclip_ablation/fused/sub6a_narratives.jsonl \\
        --tasks     data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \\
        --out-csv   data/paper_figures/phase6_msclip_ablation.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def _load_narratives(path: Path) -> dict[str, dict]:
    """Return ``{task_id: result_dict}`` from a Sub-6A narratives JSONL."""
    out: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["task_id"]] = r
    return out


def _load_tasks(path: Path) -> dict[str, dict]:
    """Return ``{task_id: task_dict}`` keyed for pathway_source lookup."""
    out: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            out[t["task_id"]] = t
    return out


def _identifications(rec: dict) -> list[dict]:
    """Per-spectrum identifications dicts as written by run_sub6a."""
    return rec.get("identifications") or []


def _spectrum_correct(rec: dict) -> dict[str, bool]:
    """Map ``spectrum_id`` → ``correct_top1`` (True / False / None)."""
    out: dict[str, bool | None] = {}
    for ident in _identifications(rec):
        sid = ident.get("spectrum_id")
        if sid:
            out[sid] = ident.get("correct_top1")
    return out


def _aggregate_overall(narrs: dict[str, dict]) -> dict:
    n_correct = n_spec = 0
    per_task = []
    for r in narrs.values():
        n_correct += int(r.get("n_correct_top1") or 0)
        n_spec += int(r.get("n_spectra") or 0)
        per_task.append(float(r.get("identification_accuracy") or 0.0))
    overall = (n_correct / n_spec) if n_spec else 0.0
    task_mean = (sum(per_task) / len(per_task)) if per_task else 0.0
    elapsed_id = sum(float(r.get("elapsed_id_seconds") or 0.0) for r in narrs.values())
    return {
        "n_tasks": len(narrs),
        "n_spectra": n_spec,
        "n_correct": n_correct,
        "overall_id_acc": overall,
        "task_mean_id_acc": task_mean,
        "elapsed_id_seconds_total": elapsed_id,
    }


def _aggregate_by_bucket(
    narrs: dict[str, dict], tasks: dict[str, dict],
) -> dict[str, dict]:
    """Stratify spectra by ``ground_truth_pathway.pathway_source``.

    Returns ``{bucket: {n_spectra, n_correct, id_acc}}``.
    """
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"n_spec": 0, "n_correct": 0})
    for tid, rec in narrs.items():
        task = tasks.get(tid)
        if task is None:
            continue
        bucket = (task.get("ground_truth_pathway") or {}).get("pathway_source") or "unknown"
        for ident in _identifications(rec):
            buckets[bucket]["n_spec"] += 1
            if ident.get("correct_top1") is True:
                buckets[bucket]["n_correct"] += 1
    out = {}
    for b, c in sorted(buckets.items()):
        n = c["n_spec"]
        out[b] = {
            "n_spectra": n,
            "n_correct": c["n_correct"],
            "id_acc": (c["n_correct"] / n) if n else 0.0,
        }
    return out


def _winloss(
    base: dict[str, dict], variant: dict[str, dict],
) -> dict[str, list]:
    """Compare per-spectrum correctness between base (gnps_only) and
    variant (fused). Returns:
      * ``gained`` — spectra that were wrong in base but correct in variant
      * ``lost``   — spectra that were correct in base but wrong in variant
      * ``unchanged_correct`` / ``unchanged_wrong``
    """
    gained: list[tuple[str, str]] = []
    lost: list[tuple[str, str]] = []
    unchanged_correct = 0
    unchanged_wrong = 0
    for tid, base_rec in base.items():
        v_rec = variant.get(tid)
        if v_rec is None:
            continue
        base_corr = _spectrum_correct(base_rec)
        v_corr = _spectrum_correct(v_rec)
        for sid, b in base_corr.items():
            v = v_corr.get(sid)
            if b is True and v is True:
                unchanged_correct += 1
            elif b is False and v is False:
                unchanged_wrong += 1
            elif b is False and v is True:
                gained.append((tid, sid))
            elif b is True and v is False:
                lost.append((tid, sid))
    return {
        "gained": gained,
        "lost": lost,
        "unchanged_correct": unchanged_correct,
        "unchanged_wrong": unchanged_wrong,
    }


def _write_csv(out_csv: Path, *, overall_a, overall_c, buckets_a, buckets_c, wl) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    # Block 1: overall config-level metrics
    rows.append({
        "section": "overall",
        "config": "gnps_only",
        "n_tasks": overall_a["n_tasks"],
        "n_spectra": overall_a["n_spectra"],
        "n_correct": overall_a["n_correct"],
        "id_acc": f"{overall_a['overall_id_acc']:.4f}",
        "task_mean_id_acc": f"{overall_a['task_mean_id_acc']:.4f}",
        "elapsed_id_s_total": f"{overall_a['elapsed_id_seconds_total']:.1f}",
    })
    rows.append({
        "section": "overall",
        "config": "fused",
        "n_tasks": overall_c["n_tasks"],
        "n_spectra": overall_c["n_spectra"],
        "n_correct": overall_c["n_correct"],
        "id_acc": f"{overall_c['overall_id_acc']:.4f}",
        "task_mean_id_acc": f"{overall_c['task_mean_id_acc']:.4f}",
        "elapsed_id_s_total": f"{overall_c['elapsed_id_seconds_total']:.1f}",
    })

    # Block 2: per-bucket breakdown (pathway_source)
    all_buckets = sorted(set(buckets_a) | set(buckets_c))
    for b in all_buckets:
        a = buckets_a.get(b, {"n_spectra": 0, "n_correct": 0, "id_acc": 0.0})
        c = buckets_c.get(b, {"n_spectra": 0, "n_correct": 0, "id_acc": 0.0})
        rows.append({
            "section": "bucket",
            "config": "gnps_only",
            "bucket": b,
            "n_spectra": a["n_spectra"],
            "n_correct": a["n_correct"],
            "id_acc": f"{a['id_acc']:.4f}",
        })
        rows.append({
            "section": "bucket",
            "config": "fused",
            "bucket": b,
            "n_spectra": c["n_spectra"],
            "n_correct": c["n_correct"],
            "id_acc": f"{c['id_acc']:.4f}",
            "delta_id_acc": f"{c['id_acc'] - a['id_acc']:+.4f}",
        })

    # Block 3: win/loss summary
    rows.append({
        "section": "winloss",
        "config": "fused_vs_gnps_only",
        "gained": len(wl["gained"]),
        "lost": len(wl["lost"]),
        "unchanged_correct": wl["unchanged_correct"],
        "unchanged_wrong": wl["unchanged_wrong"],
        "net_delta": len(wl["gained"]) - len(wl["lost"]),
    })

    fieldnames = [
        "section", "config", "bucket",
        "n_tasks", "n_spectra", "n_correct",
        "id_acc", "task_mean_id_acc", "delta_id_acc",
        "elapsed_id_s_total",
        "gained", "lost", "unchanged_correct", "unchanged_wrong", "net_delta",
    ]
    with out_csv.open("w") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _print_summary(*, overall_a, overall_c, buckets_a, buckets_c, wl) -> None:
    print("=" * 80)
    print("Phase 6.1 MS-CLIP ablation — summary")
    print("=" * 80)
    print()
    print(f"{'config':<20} {'tasks':>6} {'spectra':>8} {'correct':>8} {'overall%':>9} {'task-mean%':>11} {'id_t_total':>11}")
    for label, o in [("gnps_only", overall_a), ("fused (gnps+inhouse)", overall_c)]:
        print(f"{label:<20} {o['n_tasks']:>6} {o['n_spectra']:>8} {o['n_correct']:>8} "
              f"{o['overall_id_acc']*100:>8.2f}% {o['task_mean_id_acc']*100:>10.2f}% "
              f"{o['elapsed_id_seconds_total']:>10.1f}s")
    delta_overall = overall_c['overall_id_acc'] - overall_a['overall_id_acc']
    print(f"  Δ id_acc fused vs gnps_only: {delta_overall*100:+.2f} pp")
    print()
    print(f"{'bucket (pathway_source)':<24} {'gnps_only':>14} {'fused':>14} {'Δ pp':>8}")
    all_b = sorted(set(buckets_a) | set(buckets_c))
    for b in all_b:
        a = buckets_a.get(b, {"n_spectra": 0, "id_acc": 0.0})
        c = buckets_c.get(b, {"n_spectra": 0, "id_acc": 0.0})
        delta = (c["id_acc"] - a["id_acc"]) * 100
        a_str = f"{a['n_spectra']}@{a['id_acc']*100:.1f}%"
        c_str = f"{c['n_spectra']}@{c['id_acc']*100:.1f}%"
        print(f"{b:<24} {a_str:>14} {c_str:>14} {delta:+7.2f}")
    print()
    print(f"win/loss (fused vs gnps_only):")
    print(f"  gained ({len(wl['gained'])}): wrong→correct")
    print(f"  lost   ({len(wl['lost'])}): correct→wrong")
    print(f"  unchanged correct: {wl['unchanged_correct']}")
    print(f"  unchanged wrong:   {wl['unchanged_wrong']}")
    print(f"  net Δ: {len(wl['gained']) - len(wl['lost']):+d}")


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gnps-only", required=True, type=Path)
    ap.add_argument("--fused", required=True, type=Path)
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument(
        "--out-csv",
        type=Path,
        default=Path("data/paper_figures/phase6_msclip_ablation.csv"),
    )
    args = ap.parse_args(argv)

    narrs_a = _load_narratives(args.gnps_only)
    narrs_c = _load_narratives(args.fused)
    tasks = _load_tasks(args.tasks)

    if narrs_a.keys() != narrs_c.keys():
        sys.stderr.write(
            f"WARNING: task_id sets differ between configs. "
            f"gnps_only={len(narrs_a)} fused={len(narrs_c)} "
            f"only_in_A={list(narrs_a.keys() - narrs_c.keys())[:3]} "
            f"only_in_C={list(narrs_c.keys() - narrs_a.keys())[:3]}\n"
        )

    overall_a = _aggregate_overall(narrs_a)
    overall_c = _aggregate_overall(narrs_c)
    buckets_a = _aggregate_by_bucket(narrs_a, tasks)
    buckets_c = _aggregate_by_bucket(narrs_c, tasks)
    wl = _winloss(narrs_a, narrs_c)

    _write_csv(
        args.out_csv,
        overall_a=overall_a, overall_c=overall_c,
        buckets_a=buckets_a, buckets_c=buckets_c, wl=wl,
    )
    print(f"wrote {args.out_csv}")
    print()
    _print_summary(
        overall_a=overall_a, overall_c=overall_c,
        buckets_a=buckets_a, buckets_c=buckets_c, wl=wl,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
