"""Phase 6.7-D — aggregate MSG ablation results into a paper-ready CSV.

Reads 6 output dirs (2 pools × 3 rerankers), computes per-config Top-1 /
Top-5 / MRR, emits ``data/paper_figures/phase6_7d_msg_results.csv``.

Usage:
    python scripts/eval_sub6/aggregate_msg_ablation.py \\
        --base-dir data/eval/msg \\
        --out-csv  data/paper_figures/phase6_7d_msg_results.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterator


CONFIGS = [
    ("formula", "none"),
    ("formula", "conditional"),
    ("formula", "llm"),
    ("mass",    "none"),
    ("mass",    "conditional"),
    ("mass",    "llm"),
]

RERANKER_LABEL = {
    "none":        "msclip_only",
    "conditional": "conditional",
    "llm":         "llm_reranker",
}


# ---------------------------------------------------------------------------
# MRR helpers
# ---------------------------------------------------------------------------


def _effective_ranking(rec: dict) -> list[str]:
    """Return the effective per-spec ranking as a list of ik14 strings.

    For ``reranker_mode='llm'``: ``ranked_candidates`` holds the pre-LLM
    MS-CLIP snapshot; we apply ``llm_rerank.ranked_indices`` to reconstruct
    the LLM's preferred order, then append any unranked tail candidates.

    For all other modes: ``ranked_candidates`` already reflects the final
    order.
    """
    ranked = rec.get("ranked_candidates") or []
    iks = [c.get("ik14") or c.get("inchikey_first_block") or "" for c in ranked]

    if rec.get("reranker_mode") == "llm":
        llm = rec.get("llm_rerank") or {}
        indices = llm.get("ranked_indices") or []
        if indices:
            head: list[str] = []
            seen: set[int] = set()
            for j in indices:
                if 0 <= j < len(iks) and j not in seen:
                    head.append(iks[j])
                    seen.add(j)
            tail = [ik for i, ik in enumerate(iks) if i not in seen]
            return head + tail

    return iks


def _mrr_from_ranked_candidates(
    records: list[dict],
) -> tuple[float, float, float, int]:
    """Compute Top-1 acc, Top-5 acc, MRR from per-spec JSONL records.

    For ``none``/``conditional`` configs uses ``ranked_candidates`` directly
    (MS-CLIP order). For the ``llm`` config, reconstructs the LLM-preferred
    order via ``llm_rerank.ranked_indices`` before computing metrics.

    Falls back to ``correct_top1`` when no ranked list is present.

    Returns (top1_acc, top5_acc, mrr, n_with_rank).
    """
    top1_hits = top5_hits = mrr_sum = 0
    n_ranked = n_total = 0

    for rec in records:
        gt = rec.get("gt_inchikey_first_block")
        if not gt:
            continue
        n_total += 1

        iks = _effective_ranking(rec)
        if iks:
            n_ranked += 1
            rank = None
            for i, ik in enumerate(iks):
                if ik and ik == gt:
                    rank = i + 1
                    break
            if rank is not None:
                if rank == 1:
                    top1_hits += 1
                if rank <= 5:
                    top5_hits += 1
                mrr_sum += 1.0 / rank
        else:
            # Fallback: correct_top1 only (no ranked list available).
            if rec.get("correct_top1") is True:
                top1_hits += 1
                top5_hits += 1
                mrr_sum += 1.0

    n = n_total
    return (
        top1_hits / n if n else 0.0,
        top5_hits / n if n else 0.0,
        mrr_sum / n if n else 0.0,
        n_ranked,
    )


def _load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _iter_configs(base_dir: Path) -> Iterator[tuple[str, str, Path, Path | None]]:
    """Yield (pool, reranker, jsonl_path, summary_path) for each config dir."""
    for pool, reranker in CONFIGS:
        label = RERANKER_LABEL[reranker]
        d = base_dir / f"{pool}_{reranker}"
        jsonl = d / "msg_identifications.jsonl"
        summary = d / "summary.json"
        if not jsonl.exists():
            yield pool, reranker, jsonl, None
        else:
            yield pool, reranker, jsonl, summary if summary.exists() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-dir", type=Path,
                    default=Path("data/eval/msg"))
    ap.add_argument("--out-csv", type=Path,
                    default=Path("data/paper_figures/phase6_7d_msg_results.csv"))
    args = ap.parse_args(argv)

    rows = []
    for pool, reranker, jsonl_path, summary_path in _iter_configs(args.base_dir):
        label = RERANKER_LABEL[reranker]
        if not jsonl_path.exists():
            print(f"MISSING: {jsonl_path}", file=sys.stderr)
            rows.append({
                "pool": pool, "reranker": label,
                "n": "", "n_correct": "", "top1_acc": "MISSING",
                "top5_acc": "", "mrr": "", "mrr_delta_vs_msclip_only": "",
                "elapsed_s": "",
            })
            continue

        records = _load_jsonl(jsonl_path)
        top1, top5, mrr, n_ranked = _mrr_from_ranked_candidates(records)
        n = len(records)
        n_correct = sum(1 for r in records if r.get("correct_top1") is True)

        elapsed = ""
        if summary_path:
            try:
                s = json.loads(summary_path.read_text())
                elapsed = s.get("elapsed_seconds", "")
            except Exception:
                pass

        rows.append({
            "pool": pool,
            "reranker": label,
            "n": n,
            "n_correct": n_correct,
            "top1_acc": f"{top1:.4f}",
            "top5_acc": f"{top5:.4f}",
            "mrr": f"{mrr:.4f}",
            "mrr_delta_vs_msclip_only": "",  # filled below
            "elapsed_s": elapsed,
        })
        print(f"{pool:8s} {label:16s}  n={n}  top1={top1*100:.2f}%  "
              f"top5={top5*100:.2f}%  mrr={mrr:.4f}  ranked={n_ranked}")

    # Fill in MRR delta vs msclip_only baseline for each pool
    baseline: dict[str, float] = {}
    for r in rows:
        if r["reranker"] == "msclip_only" and r["mrr"] not in ("MISSING", ""):
            baseline[r["pool"]] = float(r["mrr"])
    for r in rows:
        if r["mrr"] not in ("MISSING", "") and r["pool"] in baseline:
            delta = float(r["mrr"]) - baseline[r["pool"]]
            r["mrr_delta_vs_msclip_only"] = f"{delta:+.4f}"

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["pool", "reranker", "n", "n_correct",
                  "top1_acc", "top5_acc", "mrr",
                  "mrr_delta_vs_msclip_only", "elapsed_s"]
    with args.out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {args.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
