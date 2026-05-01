"""Aggregate Sub-6A narratives + tasks into per-task metrics + summary.

Mirrors aggregate_sub6b.py but reads sub6a-style narratives (which carry
identification logs and metabolite_count from spectrum-derived
identifications, not from differential_metabolites). The grading metrics
(top1/top3/driver-prec/recall etc.) reuse compute_task_metrics — Sub-6A
narratives are evaluated identically once the metabolite list is in
hand.

Reads:
  - data/benchmark/sub6/sub6a_e2e_tasks.jsonl
  - <narratives>  (jsonl from run_sub6a_batch)
  - data/benchmark/sub6/curated_hmdb_mammalian.jsonl

Writes (under <out_dir>):
  - sub6a_narratives.jsonl  (raw, copied verbatim)
  - sub6a_metrics.jsonl     (one record per task, full TaskMetrics flat dict)
  - sub6a_metrics.csv       (flat per-task table)
  - sub6a_summary.json      (aggregate over all tasks)
  - sub6a_narratives.md     (per-task scorecard + identifications + narrative)
  - sub6a_identifications.csv (per-spectrum identification audit)
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
    ap.add_argument("--tasks", default="data/benchmark/sub6/sub6a_e2e_tasks.jsonl")
    ap.add_argument(
        "--narratives",
        default="data/eval/sub6/sub6a_narratives_perfect_id.jsonl",
        help="Sub-6A runner output (perfect_id or library_search variant)",
    )
    ap.add_argument("--curated", default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl")
    ap.add_argument("--out-dir", default="results/sub6a_perfect_id")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = {t["task_id"]: t for t in _load_jsonl(Path(args.tasks))}
    narratives = _load_jsonl(Path(args.narratives))
    lookup = CompoundLookup.from_curated(Path(args.curated))

    # 1. Copy raw narratives.
    shutil.copyfile(args.narratives, out_dir / "sub6a_narratives.jsonl")

    # 2. Per-task metrics. Sub-6A's "differential_metabolites" comes from
    #    the runner's identified_metabolites field (already deduped by
    #    InChIKey first-block); compute_task_metrics expects this on
    #    task["differential_metabolites"], so we splice it in.
    metrics_records: list[dict] = []
    for rec in narratives:
        tid = rec["task_id"]
        if tid not in tasks:
            print(f"WARN: narrative {tid} not in tasks file, skipping")
            continue
        task = dict(tasks[tid])
        # Inject runner's identified compounds as the LLM-visible compound list.
        identified = rec.get("identified_metabolites") or []
        task["differential_metabolites"] = identified

        m = compute_task_metrics(rec["narrative"], task, lookup)
        d = task_metrics_to_dict(m)
        d["narrative_chars"] = len(rec["narrative"] or "")
        d["elapsed_seconds"] = rec.get("elapsed_seconds")
        d["elapsed_id_seconds"] = rec.get("elapsed_id_seconds")
        d["elapsed_llm_seconds"] = rec.get("elapsed_llm_seconds")
        d["llm_model"] = rec.get("llm_model")
        d["error"] = rec.get("error")
        d["id_strategy"] = rec.get("id_strategy", "library_search")
        d["n_spectra"] = rec.get("n_spectra")
        d["n_identified"] = rec.get("n_identified")
        d["n_correct_top1"] = rec.get("n_correct_top1")
        d["identification_accuracy"] = rec.get("identification_accuracy")
        d["ground_truth_pathway"] = (
            tasks[tid].get("ground_truth_pathway", {}).get("pathway_name")
        )
        d["signal_count"] = tasks[tid].get("signal_count")
        d["noise_count"] = tasks[tid].get("noise_count")
        metrics_records.append(d)

    # Write per-task metrics JSONL.
    with (out_dir / "sub6a_metrics.jsonl").open("w") as f:
        for r in metrics_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Metrics CSV.
    csv_cols = [
        "task_id",
        "id_strategy",
        "ground_truth_pathway",
        "predicted_top_pathway",
        "top1_pathway_strict",
        "top3_pathway_acceptance",
        "driver_precision",
        "driver_recall",
        "false_noise_rate",
        "off_pathway_count",
        "n_spectra",
        "n_identified",
        "identification_accuracy",
        "narrative_chars",
        "elapsed_seconds",
        "elapsed_id_seconds",
        "elapsed_llm_seconds",
        "signal_count",
        "noise_count",
        "error",
    ]
    with (out_dir / "sub6a_metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for r in metrics_records:
            w.writerow(r)

    # Per-spectrum identification audit (one row per spectrum across all tasks).
    id_cols = [
        "task_id", "spectrum_id", "source_id", "strategy",
        "gt_inchikey_first_block", "predicted_inchikey_first_block",
        "predicted_name", "predicted_score", "correct_top1",
        "n_candidates_returned", "n_after_exclusion",
        "n_excluded_hits", "error",
    ]
    with (out_dir / "sub6a_identifications.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=id_cols, extrasaction="ignore")
        w.writeheader()
        for rec in narratives:
            tid = rec["task_id"]
            for ident in rec.get("identifications") or []:
                w.writerow({
                    "task_id": tid,
                    "spectrum_id": ident.get("spectrum_id"),
                    "source_id": ident.get("source_id"),
                    "strategy": ident.get("strategy", "library_search"),
                    "gt_inchikey_first_block": ident.get("gt_inchikey_first_block"),
                    "predicted_inchikey_first_block": ident.get("predicted_inchikey_first_block"),
                    "predicted_name": ident.get("predicted_name"),
                    "predicted_score": ident.get("predicted_score"),
                    "correct_top1": ident.get("correct_top1"),
                    "n_candidates_returned": ident.get("n_candidates_returned"),
                    "n_after_exclusion": ident.get("n_after_exclusion"),
                    "n_excluded_hits": len(ident.get("excluded_source_ids_hit") or []),
                    "error": ident.get("error"),
                })

    # 3. Summary.
    n = len(metrics_records)
    n_ok = sum(1 for r in metrics_records if r["error"] is None)

    def _frac(key: str) -> float:
        return sum(1 for r in metrics_records if r.get(key)) / n if n else 0.0

    def _mean(key: str) -> float:
        vals = [r[key] for r in metrics_records if r.get(key) is not None]
        return statistics.fmean(vals) if vals else 0.0

    summary = {
        "n_tasks": n,
        "n_ok": n_ok,
        "n_error": n - n_ok,
        "id_strategy": metrics_records[0].get("id_strategy") if metrics_records else None,
        "top1_pathway_strict_rate": _frac("top1_pathway_strict"),
        "top3_pathway_acceptance_rate": _frac("top3_pathway_acceptance"),
        "driver_precision_mean": _mean("driver_precision"),
        "driver_recall_mean": _mean("driver_recall"),
        "false_noise_rate_mean": _mean("false_noise_rate"),
        "off_pathway_count_mean": _mean("off_pathway_count"),
        "narrative_chars_mean": _mean("narrative_chars"),
        "identification_accuracy_mean": _mean("identification_accuracy"),
        "elapsed_id_seconds_total": sum(r.get("elapsed_id_seconds") or 0.0 for r in metrics_records),
        "elapsed_llm_seconds_total": sum(r.get("elapsed_llm_seconds") or 0.0 for r in metrics_records),
        "elapsed_seconds_total": sum(r.get("elapsed_seconds") or 0.0 for r in metrics_records),
        "elapsed_seconds_mean": _mean("elapsed_seconds"),
    }
    with (out_dir / "sub6a_summary.json").open("w") as f:
        json.dump(summary, f, indent=2)

    # 4. Markdown.
    md_lines: list[str] = ["# Sub-6A Baseline LLM Narratives — Per-Task Output", ""]
    md_lines.append(f"- **id_strategy**: `{summary['id_strategy']}`")
    md_lines.append(f"- **n_tasks**: {n}")
    md_lines.append(f"- **errors**: {summary['n_error']}")
    md_lines.append(f"- **identification accuracy (mean)**: {summary['identification_accuracy_mean']:.2%}")
    md_lines.append(f"- **top1 strict rate**: {summary['top1_pathway_strict_rate']:.2%}")
    md_lines.append(f"- **top3 acceptance rate**: {summary['top3_pathway_acceptance_rate']:.2%}")
    md_lines.append(f"- **driver precision (mean)**: {summary['driver_precision_mean']:.3f}")
    md_lines.append(f"- **driver recall (mean)**: {summary['driver_recall_mean']:.3f}")
    md_lines.append(f"- **false noise rate (mean)**: {summary['false_noise_rate_mean']:.3f}")
    md_lines.append(f"- **off-pathway mentions (mean)**: {summary['off_pathway_count_mean']:.2f}")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    narr_by_id = {r["task_id"]: r for r in narratives}
    for r in metrics_records:
        tid = r["task_id"]
        gt = r["ground_truth_pathway"]
        narr = narr_by_id[tid]["narrative"]
        idents = narr_by_id[tid].get("identifications") or []
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
        md_lines.append(
            f"- **identification**: strategy=`{r['id_strategy']}`, "
            f"id_acc={r['identification_accuracy']}, "
            f"n_id={r['n_identified']}/{r['n_spectra']}"
        )
        md_lines.append(f"- **claimed drivers**: {r['claimed_drivers']}")
        md_lines.append(f"- **extracted pathways**: {r['extracted_pathways']}")
        if r["off_pathway_examples"]:
            md_lines.append(f"- **off-pathway examples**: {r['off_pathway_examples']}")
        md_lines.append("")
        md_lines.append("### Per-spectrum identifications")
        md_lines.append("")
        md_lines.append("| spectrum_id | GT InChIKey | predicted | name | correct |")
        md_lines.append("|---|---|---|---|:---:|")
        for ident in idents:
            md_lines.append(
                f"| `{ident.get('spectrum_id','')}` | "
                f"`{ident.get('gt_inchikey_first_block','')}` | "
                f"`{ident.get('predicted_inchikey_first_block','')}` | "
                f"{ident.get('predicted_name','')} | "
                f"{ident.get('correct_top1')} |"
            )
        md_lines.append("")
        md_lines.append("### LLM Narrative")
        md_lines.append("")
        md_lines.append(narr)
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")
    (out_dir / "sub6a_narratives.md").write_text("\n".join(md_lines))

    # 5. README
    readme = f"""# Sub-6A Baseline LLM Evaluation Results — `{summary['id_strategy']}`

End-to-end (spectra → identification → narrative) pathway-enrichment results
for {n} tasks under the **{summary['id_strategy']}** identification strategy.

## Files

- `sub6a_narratives.jsonl`     — raw runner output, one JSON record per task
- `sub6a_metrics.jsonl`        — per-task TaskMetrics + identification summary
- `sub6a_metrics.csv`          — same metrics, flat CSV
- `sub6a_summary.json`         — aggregated rates / means
- `sub6a_narratives.md`        — human-readable per-task scorecard + narrative
- `sub6a_identifications.csv` — per-spectrum top-1 audit (one row per spectrum)
- `README.md`                  — this file

## Headline numbers

| Metric | Value |
|---|---:|
| n_tasks                  | {summary['n_tasks']} |
| errors                   | {summary['n_error']} |
| identification acc (mean)| {summary['identification_accuracy_mean']:.2%} |
| top1 strict rate         | {summary['top1_pathway_strict_rate']:.2%} |
| top3 acceptance rate     | {summary['top3_pathway_acceptance_rate']:.2%} |
| driver precision (mean)  | {summary['driver_precision_mean']:.3f} |
| driver recall (mean)     | {summary['driver_recall_mean']:.3f} |
| false noise rate (mean)  | {summary['false_noise_rate_mean']:.3f} |
| off-pathway count (mean) | {summary['off_pathway_count_mean']:.2f} |
| narrative chars (mean)   | {summary['narrative_chars_mean']:.0f} |
| total identification time| {summary['elapsed_id_seconds_total']:.1f} s |
| total LLM time           | {summary['elapsed_llm_seconds_total']:.1f} s |
| total elapsed            | {summary['elapsed_seconds_total']:.1f} s |

## Notes on `{summary['id_strategy']}`

- **`perfect_id`** — bypasses library_search and uses each spectrum's GT
  InChIKey as the prediction. Identification accuracy is trivially 1.0;
  the resulting metric is the **upper-bound baseline** for LLM reasoning
  on Sub-6A inputs (i.e. "what would the LLM achieve if identification
  were perfect").
- **`library_search`** — runs real spectrum identification with per-task
  GNPS exclusion (eval guide §3 pitfall 1). Used to measure end-to-end
  baseline including identification noise.

## Reproduce

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python scripts/eval_sub6/run_baseline.py --sub6a --id-strategy {summary['id_strategy']}
python scripts/eval_sub6/aggregate_sub6a.py --out-dir {args.out_dir}
```
"""
    (out_dir / "README.md").write_text(readme)

    print(f"wrote {n} task records to {out_dir}/")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
