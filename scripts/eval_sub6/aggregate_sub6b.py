"""Aggregate Sub-6B narratives + tasks into per-task metrics + summary.

Reads:
  - data/benchmark/sub6/sub6b_mammalian_tasks.jsonl
  - data/eval/sub6/sub6b_narratives.jsonl
  - data/benchmark/sub6/curated_hmdb_mammalian.jsonl

Writes (under <out_dir>):
  - sub6b_narratives.jsonl  (raw narratives, copied verbatim)
  - sub6b_metrics.jsonl     (one record per task, full TaskMetrics flat dict)
  - sub6b_summary.json      (aggregate over all tasks)
  - sub6b_narratives.md     (human-readable rendering)
  - sub6b_metrics.csv       (flat per-task table)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import statistics
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.compound_lookup import CompoundLookup
from evaluation.sub6.metrics import compute_task_metrics, task_metrics_to_dict


def _load_jsonl(p: Path) -> list[dict]:
    out: list[dict] = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="data/benchmark/sub6/sub6b_mammalian_tasks.jsonl")
    ap.add_argument("--narratives", default="data/eval/sub6/sub6b_narratives.jsonl")
    ap.add_argument("--curated", default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl")
    ap.add_argument("--out-dir", default="results/sub6")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = {t["task_id"]: t for t in _load_jsonl(Path(args.tasks))}
    narratives = _load_jsonl(Path(args.narratives))
    lookup = CompoundLookup.from_curated(Path(args.curated))

    # 1. Copy raw narratives.
    shutil.copyfile(args.narratives, out_dir / "sub6b_narratives.jsonl")

    # 2. Compute metrics per task.
    metrics_records: list[dict] = []
    for rec in narratives:
        tid = rec["task_id"]
        if tid not in tasks:
            print(f"WARN: narrative {tid} not in tasks file, skipping")
            continue
        m = compute_task_metrics(rec["narrative"], tasks[tid], lookup)
        d = task_metrics_to_dict(m)
        d["narrative_chars"] = len(rec["narrative"])
        d["elapsed_seconds"] = rec.get("elapsed_seconds")
        d["llm_model"] = rec.get("llm_model")
        d["error"] = rec.get("error")
        d["ground_truth_pathway"] = (
            tasks[tid].get("ground_truth_pathway", {}).get("pathway_name")
        )
        d["signal_count"] = tasks[tid].get("signal_count")
        d["noise_count"] = tasks[tid].get("noise_count")
        metrics_records.append(d)

    # Write per-task metrics JSONL.
    with (out_dir / "sub6b_metrics.jsonl").open("w") as f:
        for r in metrics_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write metrics CSV (flat columns, easy for Excel).
    csv_cols = [
        "task_id",
        "ground_truth_pathway",
        "predicted_top_pathway",
        "top1_pathway_strict",
        "top3_pathway_acceptance",
        "driver_precision",
        "driver_recall",
        "false_noise_rate",
        "off_pathway_count",
        "narrative_chars",
        "elapsed_seconds",
        "signal_count",
        "noise_count",
        "error",
    ]
    with (out_dir / "sub6b_metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for r in metrics_records:
            w.writerow(r)

    # 3. Aggregate summary.
    n = len(metrics_records)
    n_ok = sum(1 for r in metrics_records if r["error"] is None)

    def _frac(key: str) -> float:
        return sum(1 for r in metrics_records if r[key]) / n if n else 0.0

    def _mean(key: str) -> float:
        vals = [r[key] for r in metrics_records if r[key] is not None]
        return statistics.fmean(vals) if vals else 0.0

    summary = {
        "n_tasks": n,
        "n_ok": n_ok,
        "n_error": n - n_ok,
        "top1_pathway_strict_rate": _frac("top1_pathway_strict"),
        "top3_pathway_acceptance_rate": _frac("top3_pathway_acceptance"),
        "driver_precision_mean": _mean("driver_precision"),
        "driver_recall_mean": _mean("driver_recall"),
        "false_noise_rate_mean": _mean("false_noise_rate"),
        "off_pathway_count_mean": _mean("off_pathway_count"),
        "narrative_chars_mean": _mean("narrative_chars"),
        "elapsed_seconds_total": sum(
            r.get("elapsed_seconds") or 0.0 for r in metrics_records
        ),
        "elapsed_seconds_mean": _mean("elapsed_seconds"),
    }
    with (out_dir / "sub6b_summary.json").open("w") as f:
        json.dump(summary, f, indent=2)

    # 4. Human-readable markdown.
    md_lines: list[str] = ["# Sub-6B Baseline LLM Narratives — Per-Task Output", ""]
    md_lines.append(f"- **n_tasks**: {n}")
    md_lines.append(f"- **errors**: {n - n_ok}")
    md_lines.append(f"- **top1 strict rate**: {summary['top1_pathway_strict_rate']:.2%}")
    md_lines.append(f"- **top3 acceptance rate**: {summary['top3_pathway_acceptance_rate']:.2%}")
    md_lines.append(f"- **driver precision (mean)**: {summary['driver_precision_mean']:.3f}")
    md_lines.append(f"- **driver recall (mean)**: {summary['driver_recall_mean']:.3f}")
    md_lines.append(f"- **false noise rate (mean)**: {summary['false_noise_rate_mean']:.3f}")
    md_lines.append(f"- **off-pathway mentions (mean)**: {summary['off_pathway_count_mean']:.2f}")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    # Build narrative-by-id index
    narr_by_id = {r["task_id"]: r for r in narratives}
    for r in metrics_records:
        tid = r["task_id"]
        gt = r["ground_truth_pathway"]
        narr = narr_by_id[tid]["narrative"]
        md_lines.append(f"## {tid}")
        md_lines.append("")
        md_lines.append(f"- **GT pathway**: `{gt}`")
        md_lines.append(f"- **predicted top pathway**: `{r['predicted_top_pathway']}`")
        md_lines.append(
            f"- **top1_strict**: {r['top1_pathway_strict']} | "
            f"**top3_acc**: {r['top3_pathway_acceptance']} | "
            f"**driver_prec**: {r['driver_precision']:.2f} | "
            f"**driver_recall**: {r['driver_recall']:.2f} | "
            f"**false_noise**: {r['false_noise_rate']:.2f} | "
            f"**off_pathway**: {r['off_pathway_count']}"
        )
        md_lines.append(f"- **claimed drivers**: {r['claimed_drivers']}")
        md_lines.append(f"- **extracted pathways**: {r['extracted_pathways']}")
        if r["off_pathway_examples"]:
            md_lines.append(f"- **off-pathway examples**: {r['off_pathway_examples']}")
        md_lines.append("")
        md_lines.append("### LLM Narrative")
        md_lines.append("")
        md_lines.append(narr)
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")
    (out_dir / "sub6b_narratives.md").write_text("\n".join(md_lines))

    # 5. README
    readme = f"""# Sub-6B Baseline LLM Evaluation Results

Naked LLM (no verifier) pathway-enrichment narratives for {n} compound-only tasks.

## Files

- `sub6b_narratives.jsonl` — raw LLM outputs, one JSON record per task
- `sub6b_metrics.jsonl`    — per-task TaskMetrics + provenance, JSON Lines
- `sub6b_metrics.csv`      — same metrics, flat CSV
- `sub6b_summary.json`     — aggregated rates / means across all tasks
- `sub6b_narratives.md`    — human-readable per-task narrative + scorecards
- `README.md`              — this file

## Headline numbers

| Metric | Value |
|---|---:|
| n_tasks                  | {summary['n_tasks']} |
| errors                   | {summary['n_error']} |
| top1 strict rate         | {summary['top1_pathway_strict_rate']:.2%} |
| top3 acceptance rate     | {summary['top3_pathway_acceptance_rate']:.2%} |
| driver precision (mean)  | {summary['driver_precision_mean']:.3f} |
| driver recall (mean)     | {summary['driver_recall_mean']:.3f} |
| false noise rate (mean)  | {summary['false_noise_rate_mean']:.3f} |
| off-pathway count (mean) | {summary['off_pathway_count_mean']:.2f} |
| narrative chars (mean)   | {summary['narrative_chars_mean']:.0f} |
| total LLM time           | {summary['elapsed_seconds_total']:.1f} s |
| per-task LLM time (mean) | {summary['elapsed_seconds_mean']:.1f} s |

## How metrics are computed

See `evaluation/sub6/metrics.py` (`compute_task_metrics`) and
`reports/benchmark/sub6_evaluation_guide.md` §4. Briefly:

- **top1_pathway_strict**: the LLM's first-mentioned pathway is a fuzzy match
  to `ground_truth_pathway.pathway_name`. Fuzzy = case-insensitive substring,
  or content-token-subset after stripping suffix words ("metabolism",
  "catabolism", "biosynthesis", ...).
- **top3_pathway_acceptance**: the LLM's first-mentioned pathway matches any
  of the top-3 RaMP enrichment pathways.
- **driver_precision / recall**: drivers cited in the narrative
  (sentence-level co-occurrence with markers like "key driver", "drives")
  are resolved to InChIKey first-block via the curated pool, then compared
  to `ground_truth_signal_compounds` (KEGG → InChIKey).
- **false_noise_rate**: fraction of cited drivers that are in
  `ground_truth_noise_compounds`.
- **off_pathway_count**: pathway mentions that don't match any of the top-10
  RaMP candidates — proxy for hallucination.

## Reproduce

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python -c "from evaluation.sub6.run_sub6b import run_sub6b_batch; \\
  run_sub6b_batch( \\
    'data/benchmark/sub6/sub6b_mammalian_tasks.jsonl', \\
    'data/eval/sub6/sub6b_narratives.jsonl', \\
    caller='sub6b_baseline')"
python scripts/eval_sub6/aggregate_sub6b.py --out-dir results/sub6
```

The runner is idempotent: already-completed `task_id`s in the output JSONL
are skipped. Delete the JSONL to force a full re-run.
"""
    (out_dir / "README.md").write_text(readme)

    print(f"wrote {n} task records to {out_dir}/")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
