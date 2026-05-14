"""Aggregate Phase 6.2 SIRIUS+CFM-ID rerank ablation across 4 configs.

Reads:
  data/eval/sub6/v2_phase6_2/{gnps_only,cfmid,full,sirius}/sub6a_narratives.jsonl
  data/eval/sub6/v2_phase6_2/{cfmid,full,sirius}/peak_evidence/*.json

Writes:
  data/paper_figures/phase6_2_sirius_cfmid_ablation.csv         (main table)
  data/paper_figures/phase6_2_per_bucket.csv                    (per pathway_source)
  data/paper_figures/phase6_2_winloss.csv                       (vs gnps_only)
  data/paper_figures/phase6_2_peak_evidence_quality.csv         (sirius/cfm coverage)

The ground-truth pathway_source bucket is taken from the Sub-6A v2 task
JSONL (`ground_truth_pathway.pathway_source`), matching Phase 6.1 msclip
ablation §4 stratification.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
ABL_DIR = ROOT / "data/eval/sub6/v2_phase6_2"
TASKS = ROOT / "data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl"
OUT = ROOT / "data/paper_figures"
OUT.mkdir(parents=True, exist_ok=True)

CONFIGS = [
    ("gnps_only", ""),
    ("cfmid",     "cfmid"),
    ("full",      "sirius,cfmid"),
    ("sirius",    "sirius"),
]


def load_narratives(name: str) -> list[dict]:
    path = ABL_DIR / name / "sub6a_narratives.jsonl"
    return [json.loads(line) for line in path.open()]


def load_task_meta() -> dict[str, dict]:
    """task_id → {bucket: pathway_source, gt_inchikey: per-spectrum-set}."""
    out = {}
    for line in TASKS.open():
        t = json.loads(line)
        gt = t.get("ground_truth_pathway") or {}
        out[t["task_id"]] = {
            "pathway_source": gt.get("pathway_source") or "unknown",
            "n_spectra": len(t.get("differential_spectra") or []),
        }
    return out


def overall_id_acc(rows: list[dict]) -> tuple[int, int, float, float]:
    """Return (n_correct_total, n_spectra_total, overall_acc, taskmean_acc)."""
    n_correct = sum(r.get("n_correct_top1", 0) for r in rows)
    n_spec = sum(r.get("n_spectra", 0) for r in rows)
    overall = n_correct / n_spec if n_spec else 0.0
    taskmean = mean(r.get("identification_accuracy", 0.0) for r in rows) if rows else 0.0
    return n_correct, n_spec, overall, taskmean


def total_id_wall(rows: list[dict]) -> float:
    return sum(r.get("elapsed_id_seconds", 0.0) for r in rows)


def per_spectrum_correct(rows: list[dict]) -> dict[str, bool]:
    """spectrum_id → correct_top1 bool."""
    out = {}
    for r in rows:
        for ident in r.get("identifications", []):
            sid = ident.get("spectrum_id")
            if sid:
                out[sid] = bool(ident.get("correct_top1"))
    return out


def per_spectrum_bucket(rows: list[dict], task_meta: dict[str, dict]) -> dict[str, str]:
    """spectrum_id → bucket (pathway_source)."""
    out = {}
    for r in rows:
        bucket = task_meta.get(r["task_id"], {}).get("pathway_source", "unknown")
        for ident in r.get("identifications", []):
            sid = ident.get("spectrum_id")
            if sid:
                out[sid] = bucket
    return out


def main() -> int:
    task_meta = load_task_meta()

    # ---- Main table ----
    main_rows = []
    config_corrects: dict[str, dict[str, bool]] = {}
    config_buckets: dict[str, dict[str, str]] = {}
    for name, rerank in CONFIGS:
        if not (ABL_DIR / name / "sub6a_narratives.jsonl").exists():
            print(f"  WARN: {name} not yet present, skipping in main table")
            continue
        rows = load_narratives(name)
        n_tasks = len(rows)
        nc, ns, overall, taskmean = overall_id_acc(rows)
        wall = total_id_wall(rows)
        peak_dir = ABL_DIR / name / "peak_evidence"
        n_pe = len(list(peak_dir.glob("*.json"))) if peak_dir.exists() else 0
        main_rows.append({
            "config": name,
            "rerank_with": rerank,
            "n_tasks": n_tasks,
            "n_spectra": ns,
            "n_correct": nc,
            "id_acc_overall": round(overall * 100, 4),
            "id_acc_taskmean": round(taskmean * 100, 4),
            "wall_id_seconds": round(wall, 1),
            "peak_evidence_files": n_pe,
        })
        config_corrects[name] = per_spectrum_correct(rows)
        config_buckets[name] = per_spectrum_bucket(rows, task_meta)

    main_csv = OUT / "phase6_2_sirius_cfmid_ablation.csv"
    with main_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(main_rows[0].keys()))
        w.writeheader(); w.writerows(main_rows)
    print(f"wrote {main_csv} rows={len(main_rows)}")

    # ---- Per-bucket breakdown ----
    if "gnps_only" in config_corrects:
        baseline_correct = config_corrects["gnps_only"]
        baseline_buckets = config_buckets["gnps_only"]
        bucket_rows = []
        for name in [c for c, _ in CONFIGS if c in config_corrects]:
            cur = config_corrects[name]
            by_bucket: dict[str, list[bool]] = defaultdict(list)
            for sid, ok in cur.items():
                bucket = baseline_buckets.get(sid, "unknown")
                by_bucket[bucket].append(ok)
            for bucket, oks in sorted(by_bucket.items()):
                bucket_rows.append({
                    "config": name, "bucket": bucket, "n_spectra": len(oks),
                    "n_correct": sum(oks),
                    "id_acc": round(100 * sum(oks) / len(oks), 2) if oks else 0.0,
                })
        bucket_csv = OUT / "phase6_2_per_bucket.csv"
        with bucket_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(bucket_rows[0].keys()))
            w.writeheader(); w.writerows(bucket_rows)
        print(f"wrote {bucket_csv} rows={len(bucket_rows)}")

        # ---- Win/loss vs gnps_only ----
        winloss_rows = []
        for name in [c for c, _ in CONFIGS if c in config_corrects and c != "gnps_only"]:
            cur = config_corrects[name]
            gained = lost = same_correct = same_wrong = 0
            for sid, base_ok in baseline_correct.items():
                cur_ok = cur.get(sid)
                if cur_ok is None:
                    continue
                if base_ok and not cur_ok:
                    lost += 1
                elif not base_ok and cur_ok:
                    gained += 1
                elif base_ok and cur_ok:
                    same_correct += 1
                else:
                    same_wrong += 1
            winloss_rows.append({
                "config": name, "gained": gained, "lost": lost,
                "same_correct": same_correct, "same_wrong": same_wrong,
                "net_delta_spectra": gained - lost,
            })
        winloss_csv = OUT / "phase6_2_winloss.csv"
        with winloss_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(winloss_rows[0].keys()))
            w.writeheader(); w.writerows(winloss_rows)
        print(f"wrote {winloss_csv} rows={len(winloss_rows)}")

    # ---- Peak-evidence quality ----
    pe_rows = []
    for name, _ in CONFIGS:
        peak_dir = ABL_DIR / name / "peak_evidence"
        if not peak_dir.exists():
            continue
        files = sorted(peak_dir.glob("*.json"))
        n = len(files)
        if n == 0:
            continue
        sirius_ok = 0
        sirius_top1_correct_formula = 0
        cfmid_ok = 0
        cfmid_high_cosine = 0  # predicted_cosine > 0.5
        sirius_gate_applied_total = 0
        for f in files:
            pe = json.loads(f.read_text())
            sir = pe.get("sirius") or {}
            cfm = pe.get("cfmid_top1") or {}
            if sir.get("top_formulas"):
                sirius_ok += 1
            if cfm.get("predicted_peaks"):
                cfmid_ok += 1
                if (cfm.get("cosine_vs_experimental") or 0) > 0.5:
                    cfmid_high_cosine += 1
            for c in pe.get("candidates_evaluated", []):
                if c.get("sirius_gate_applied"):
                    sirius_gate_applied_total += 1
        pe_rows.append({
            "config": name, "n_spectra_with_pe": n,
            "sirius_top1_returned": sirius_ok,
            "sirius_top1_returned_pct": round(100 * sirius_ok / n, 2),
            "cfmid_predicted_returned": cfmid_ok,
            "cfmid_predicted_returned_pct": round(100 * cfmid_ok / n, 2),
            "cfmid_predicted_cosine_gt_0.5_pct": round(100 * cfmid_high_cosine / n, 2),
            "sirius_gate_applied_total_claims": sirius_gate_applied_total,
        })
    if pe_rows:
        pe_csv = OUT / "phase6_2_peak_evidence_quality.csv"
        with pe_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(pe_rows[0].keys()))
            w.writeheader(); w.writerows(pe_rows)
        print(f"wrote {pe_csv} rows={len(pe_rows)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
