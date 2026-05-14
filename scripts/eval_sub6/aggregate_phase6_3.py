"""Phase 6.3 aggregator — combines:
  - Config A (reused verbatim from Phase 6.2 Config D / 'full')
  - Config B (msclip + weighted) from data/eval/sub6/v2_phase6_3/B_msclip_weighted/
  - Config C (msclip + LLM) from data/eval/sub6/v2_phase6_3/C_msclip_llm/

Writes:
  - data/paper_figures/phase6_3_main.csv         (4 columns × 3 rows)
  - data/paper_figures/phase6_3_per_bucket.csv   (per pathway_source)
  - data/paper_figures/phase6_3_winloss.csv      (vs Config A baseline)
  - data/paper_figures/phase6_3_layer_f.csv      (peak_mechanistic claim count)
  - data/paper_figures/phase6_3_llm_quality.csv  (fallback rate, peak_claims/spec)
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
P63 = ROOT / "data/eval/sub6/v2_phase6_3"
P62 = ROOT / "data/eval/sub6/v2_phase6_2"
TASKS = ROOT / "data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl"
OUT = ROOT / "data/paper_figures"
OUT.mkdir(parents=True, exist_ok=True)


def _load_narratives(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def _gt_bucket() -> dict[str, str]:
    out = {}
    for line in TASKS.open():
        t = json.loads(line)
        gt = t.get("ground_truth_pathway") or {}
        out[t["task_id"]] = gt.get("pathway_source") or "unknown"
    return out


def _summary_for(rows: list[dict], label: str, primary: str, reranker: str):
    n_tasks = len(rows)
    n_correct = sum(r.get("n_correct_top1", 0) for r in rows)
    n_spectra = sum(r.get("n_spectra", 0) for r in rows)
    overall = (n_correct / n_spectra) if n_spectra else 0.0
    taskmean = mean(r.get("identification_accuracy", 0.0) for r in rows) if rows else 0.0
    wall = sum(r.get("elapsed_seconds", 0.0) for r in rows)
    llm_calls = sum(r.get("llm_calls", 0) for r in rows)
    return {
        "config": label,
        "primary_retriever": primary,
        "reranker": reranker,
        "n_tasks": n_tasks,
        "n_spectra": n_spectra,
        "n_correct": n_correct,
        "id_acc_overall": round(overall * 100, 4),
        "id_acc_taskmean": round(taskmean * 100, 4),
        "wall_seconds": round(wall, 1),
        "llm_calls_total": llm_calls,
    }


def _per_spectrum_correct(rows: list[dict]) -> dict[str, bool]:
    out = {}
    for r in rows:
        for ident in r.get("identifications", []):
            sid = ident.get("spectrum_id")
            if sid:
                out[sid] = bool(ident.get("correct_top1"))
    return out


def _per_spectrum_bucket(rows: list[dict], bucket_map: dict[str, str]) -> dict[str, str]:
    out = {}
    for r in rows:
        b = bucket_map.get(r["task_id"], "unknown")
        for ident in r.get("identifications", []):
            sid = ident.get("spectrum_id")
            if sid:
                out[sid] = b
    return out


def _llm_quality(rows: list[dict]) -> dict:
    """Aggregate LLM-rerank-specific stats (only meaningful when reranker_mode='llm')."""
    n_spec = 0
    fb = 0
    n_peak_claims = 0
    confidence_counts = {"low": 0, "medium": 0, "high": 0}
    for r in rows:
        for ident in r.get("identifications", []):
            if ident.get("reranker_mode") != "llm":
                continue
            n_spec += 1
            if ident.get("llm_rerank_fallback_used"):
                fb += 1
            n_peak_claims += len(ident.get("llm_rerank_peak_claims") or [])
            cc = ident.get("llm_rerank_confidence")
            if cc in confidence_counts:
                confidence_counts[cc] += 1
    return {
        "n_spectra_with_llm_rerank": n_spec,
        "n_fallback_used": fb,
        "fallback_rate_pct": round(100 * fb / n_spec, 2) if n_spec else 0.0,
        "n_peak_claims_total": n_peak_claims,
        "peak_claims_per_spectrum": round(n_peak_claims / n_spec, 2) if n_spec else 0.0,
        "confidence_low": confidence_counts["low"],
        "confidence_medium": confidence_counts["medium"],
        "confidence_high": confidence_counts["high"],
    }


def main() -> int:
    bucket_map = _gt_bucket()

    # Config A: reused from Phase 6.2 'full' (modcos + weighted with sirius+cfmid)
    a_path = P62 / "full/sub6a_narratives.jsonl"
    if not a_path.exists():
        print(f"WARN: Phase 6.2 Config A source missing at {a_path}")
        return 1
    rows_A = _load_narratives(a_path)
    sum_A = _summary_for(rows_A, "A_modcos_weighted (reused 6.2 Config D)", "modcos", "weighted")

    # Config B
    b_path = P63 / "B_msclip_weighted/sub6a_narratives.jsonl"
    sum_B = None
    if b_path.exists():
        rows_B = _load_narratives(b_path)
        sum_B = _summary_for(rows_B, "B_msclip_weighted", "msclip", "weighted")
    else:
        print(f"WARN: Config B not yet present ({b_path})")
        rows_B = None

    # Config C
    c_path = P63 / "C_msclip_llm/sub6a_narratives.jsonl"
    sum_C = None
    if c_path.exists():
        rows_C = _load_narratives(c_path)
        sum_C = _summary_for(rows_C, "C_msclip_llm", "msclip", "llm")
    else:
        print(f"WARN: Config C not yet present ({c_path})")
        rows_C = None

    main_rows = [r for r in (sum_A, sum_B, sum_C) if r]
    main_csv = OUT / "phase6_3_main.csv"
    with main_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(main_rows[0].keys()))
        w.writeheader(); w.writerows(main_rows)
    print(f"wrote {main_csv} rows={len(main_rows)}")

    # Per-bucket
    bucket_rows = []
    A_correct = _per_spectrum_correct(rows_A)
    A_buckets = _per_spectrum_bucket(rows_A, bucket_map)
    for label, rows in [
        ("A_modcos_weighted", rows_A),
        ("B_msclip_weighted", rows_B),
        ("C_msclip_llm", rows_C),
    ]:
        if not rows:
            continue
        per_correct = _per_spectrum_correct(rows)
        by_bucket = defaultdict(list)
        for sid, ok in per_correct.items():
            b = A_buckets.get(sid, bucket_map.get(rows[0]["task_id"], "unknown"))
            by_bucket[b].append(ok)
        for b, oks in sorted(by_bucket.items()):
            bucket_rows.append({
                "config": label, "bucket": b, "n_spectra": len(oks),
                "n_correct": sum(oks),
                "id_acc": round(100 * sum(oks) / len(oks), 2) if oks else 0.0,
            })
    bucket_csv = OUT / "phase6_3_per_bucket.csv"
    if bucket_rows:
        with bucket_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(bucket_rows[0].keys()))
            w.writeheader(); w.writerows(bucket_rows)
        print(f"wrote {bucket_csv} rows={len(bucket_rows)}")

    # Win/loss vs Config A
    wl_rows = []
    for label, rows in [("B_msclip_weighted", rows_B), ("C_msclip_llm", rows_C)]:
        if not rows:
            continue
        per = _per_spectrum_correct(rows)
        gained = lost = same_correct = same_wrong = 0
        for sid, base_ok in A_correct.items():
            cur_ok = per.get(sid)
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
        wl_rows.append({
            "config": label, "gained": gained, "lost": lost,
            "same_correct": same_correct, "same_wrong": same_wrong,
            "net_delta": gained - lost,
        })
    wl_csv = OUT / "phase6_3_winloss.csv"
    if wl_rows:
        with wl_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(wl_rows[0].keys()))
            w.writeheader(); w.writerows(wl_rows)
        print(f"wrote {wl_csv} rows={len(wl_rows)}")

    # LLM rerank quality (Config C only)
    if rows_C:
        q = _llm_quality(rows_C)
        q_csv = OUT / "phase6_3_llm_quality.csv"
        with q_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(q.keys()))
            w.writeheader(); w.writerow(q)
        print(f"wrote {q_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
