"""Aggregate A3 LLM-single / MetAgent pathway accuracy.

This script adapts the existing Sub-6B pathway metric code to the A3
directory-tree outputs:

* LLM single: ``.../single/{task_id}/narrative.json`` -> ``narrative``
* MetAgent feedback: ``.../feedback/{task_id}/result.json`` -> ``final_narrative``

Outputs are written under ``data/eval/sub6/v4_a3_pathway_accuracy`` by
default.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.compound_lookup import CompoundLookup
from evaluation.sub6.metrics import compute_task_metrics, task_metrics_to_dict


@dataclass(frozen=True)
class DatasetSpec:
    label: str
    root: Path
    pipeline: str
    literature_mode: str
    phase: str
    run: str | None = None


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _iter_task_dirs(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def _load_narrative(task_dir: Path, pipeline: str) -> tuple[str, dict]:
    if pipeline == "single":
        payload = json.loads((task_dir / "narrative.json").read_text())
        return payload.get("narrative") or "", payload
    if pipeline == "feedback":
        payload = json.loads((task_dir / "result.json").read_text())
        return payload.get("final_narrative") or "", payload
    raise ValueError(f"unsupported pipeline: {pipeline}")


def _score_dataset(
    spec: DatasetSpec,
    *,
    tasks_by_id: dict[str, dict],
    lookup: CompoundLookup,
) -> list[dict]:
    records: list[dict] = []
    for task_dir in _iter_task_dirs(spec.root):
        tid = task_dir.name
        task = tasks_by_id.get(tid)
        if task is None:
            print(f"WARN: {spec.label} task {tid} not in tasks file, skipping")
            continue
        try:
            narrative, payload = _load_narrative(task_dir, spec.pipeline)
            error = payload.get("error")
        except FileNotFoundError as exc:
            print(f"WARN: {spec.label} missing file for {tid}: {exc}")
            continue

        m = compute_task_metrics(narrative, task, lookup)
        d = task_metrics_to_dict(m)
        gt = task.get("ground_truth_pathway") or {}
        d.update(
            {
                "dataset": spec.label,
                "phase": spec.phase,
                "run": spec.run,
                "pipeline": spec.pipeline,
                "literature_mode": spec.literature_mode,
                "ground_truth_pathway": gt.get("pathway_name"),
                "ground_truth_pathway_id": gt.get("pathway_id"),
                "ground_truth_pathway_source": gt.get("pathway_source"),
                "narrative_chars": len(narrative),
                "elapsed_seconds": payload.get("elapsed_seconds"),
                "error": error,
            }
        )
        if spec.pipeline == "feedback":
            d["final_iter_idx"] = payload.get("final_iter_idx")
            d["rollback_reason"] = payload.get("rollback_reason")
            d["n_feedback_iterations"] = payload.get("n_feedback_iterations")
            d["termination_reason"] = payload.get("termination_reason")
        records.append(d)
    return records


def _frac(records: list[dict], key: str) -> float:
    return sum(1 for r in records if r.get(key)) / len(records) if records else 0.0


def _mean(records: list[dict], key: str) -> float:
    vals = [r.get(key) for r in records if r.get(key) is not None]
    return statistics.fmean(vals) if vals else 0.0


def _summary(records: list[dict]) -> dict:
    n = len(records)
    n_error_marker = sum(1 for r in records if r.get("error"))
    n_with_narrative = sum(1 for r in records if (r.get("narrative_chars") or 0) > 0)
    return {
        "n_tasks": n,
        "n_with_narrative": n_with_narrative,
        "n_error_marker": n_error_marker,
        "top1_pathway_strict_rate": _frac(records, "top1_pathway_strict"),
        "top3_pathway_acceptance_rate": _frac(records, "top3_pathway_acceptance"),
        "off_pathway_count_mean": _mean(records, "off_pathway_count"),
        "driver_precision_mean": _mean(records, "driver_precision"),
        "driver_recall_mean": _mean(records, "driver_recall"),
        "false_noise_rate_mean": _mean(records, "false_noise_rate"),
        "narrative_chars_mean": _mean(records, "narrative_chars"),
        "elapsed_seconds_total": sum(r.get("elapsed_seconds") or 0.0 for r in records),
        "elapsed_seconds_mean": _mean(records, "elapsed_seconds"),
    }


def _ci95_t3(values: list[float]) -> dict:
    """Mean +/- CI95 across three rerun-level rates.

    Uses t critical 4.303 for df=2. For non-3 input, returns a best-effort
    normal-style field with ``ci95`` set to null when n < 2.
    """
    n = len(values)
    if not values:
        return {"n": 0, "mean": None, "ci95": None, "values": []}
    mean = statistics.fmean(values)
    if n < 2:
        return {"n": n, "mean": mean, "ci95": None, "values": values}
    tcrit = 4.303 if n == 3 else 1.96
    ci95 = tcrit * statistics.stdev(values) / math.sqrt(n)
    return {"n": n, "mean": mean, "ci95": ci95, "values": values}


def _write_csv(path: Path, records: list[dict]) -> None:
    cols = [
        "dataset",
        "phase",
        "run",
        "pipeline",
        "literature_mode",
        "task_id",
        "ground_truth_pathway",
        "ground_truth_pathway_source",
        "predicted_top_pathway",
        "top1_pathway_strict",
        "top3_pathway_acceptance",
        "off_pathway_count",
        "off_pathway_examples",
        "extracted_pathways",
        "driver_precision",
        "driver_recall",
        "false_noise_rate",
        "narrative_chars",
        "elapsed_seconds",
        "error",
        "final_iter_idx",
        "rollback_reason",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            row = dict(rec)
            for key in ("off_pathway_examples", "extracted_pathways"):
                if isinstance(row.get(key), list):
                    row[key] = "|".join(str(v) for v in row[key])
            writer.writerow(row)


def _format_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100.0 * x:.2f}%"


def _write_markdown(
    path: Path,
    *,
    summaries: dict[str, dict],
    d35_ci: dict[str, dict],
    records: list[dict],
) -> None:
    lines = [
        "# A3 Pathway Accuracy",
        "",
        "Metric definitions come from `evaluation/sub6/metrics.py`: first-mentioned pathway is extracted from the narrative, then fuzzy-matched to `ground_truth_pathway.pathway_name` for top-1 strict; top-3 acceptance matches the first mention against RaMP enrichment top-3.",
        "",
        "## D3 Full 63-Task Point Estimates",
        "",
        "| dataset | n | top1 strict | top3 acceptance | off-pathway mean |",
        "|---|---:|---:|---:|---:|",
    ]
    for label in (
        "d3_llm_single_no_lit",
        "d3_llm_single_with_lit",
        "d3_metagent_no_lit",
        "d3_metagent_with_lit",
    ):
        if label not in summaries:
            continue
        s = summaries[label]
        lines.append(
            f"| {label} | {s['n_tasks']} | {_format_pct(s['top1_pathway_strict_rate'])} | "
            f"{_format_pct(s['top3_pathway_acceptance_rate'])} | {s['off_pathway_count_mean']:.2f} |"
        )

    lines.extend(
        [
            "",
            "## D3.5 Rerun CI",
            "",
            "Mean +/- CI95 across run1/run2/run3 rates on the 10-task subset.",
            "",
            "| dataset | n runs | top1 strict | top3 acceptance |",
            "|---|---:|---:|---:|",
        ]
    )
    for label, ci in d35_ci.items():
        top1 = ci["top1_pathway_strict_rate"]
        top3 = ci["top3_pathway_acceptance_rate"]
        top1_txt = f"{_format_pct(top1['mean'])} +/- {_format_pct(top1['ci95'])}"
        top3_txt = f"{_format_pct(top3['mean'])} +/- {_format_pct(top3['ci95'])}"
        lines.append(f"| {label} | {top1['n']} | {top1_txt} | {top3_txt} |")

    lines.extend(
        [
            "",
            "## Per-Task D3 Errors",
            "",
            "Rows below are D3 full tasks where top1 strict failed for the two headline systems.",
            "",
        ]
    )
    headline = {
        "d3_llm_single_no_lit",
        "d3_metagent_with_lit",
    }
    misses = [
        r
        for r in records
        if r["dataset"] in headline and not r.get("top1_pathway_strict")
    ]
    for r in misses:
        lines.append(
            f"- `{r['dataset']}` `{r['task_id']}`: GT=`{r['ground_truth_pathway']}`; "
            f"pred=`{r['predicted_top_pathway']}`; top3={r['top3_pathway_acceptance']}"
        )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")
    ap.add_argument("--curated", default="data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl")
    ap.add_argument("--out-dir", default="data/eval/sub6/v4_a3_pathway_accuracy")
    args = ap.parse_args()

    tasks_by_id = {t["task_id"]: t for t in _load_jsonl(Path(args.tasks))}
    lookup = CompoundLookup.from_curated(Path(args.curated))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    specs: list[DatasetSpec] = [
        DatasetSpec(
            "d3_llm_single_no_lit",
            Path("data/eval/sub6/v4_a3_d3_no_lit/single"),
            "single",
            "no_lit",
            "D3",
        ),
        DatasetSpec(
            "d3_llm_single_with_lit",
            Path("data/eval/sub6/v4_a3_d3_with_lit/single"),
            "single",
            "with_lit_pass",
            "D3",
        ),
        DatasetSpec(
            "d3_metagent_no_lit",
            Path("data/eval/sub6/v4_a3_d3_no_lit/feedback"),
            "feedback",
            "no_lit",
            "D3",
        ),
        DatasetSpec(
            "d3_metagent_with_lit",
            Path("data/eval/sub6/v4_a3_d3_with_lit/feedback"),
            "feedback",
            "with_lit",
            "D3",
        ),
    ]
    for mode in ("no_lit", "with_lit"):
        for run_idx in (1, 2, 3):
            for pipeline in ("single", "feedback"):
                specs.append(
                    DatasetSpec(
                        f"d3_5_{pipeline}_{mode}_run{run_idx}",
                        Path(f"data/eval/sub6/v4_a3_d3_5/{mode}/run{run_idx}/{pipeline}"),
                        pipeline,
                        mode,
                        "D3.5",
                        f"run{run_idx}",
                    )
                )

    all_records: list[dict] = []
    summaries: dict[str, dict] = {}
    for spec in specs:
        records = _score_dataset(spec, tasks_by_id=tasks_by_id, lookup=lookup)
        if not records:
            continue
        all_records.extend(records)
        summaries[spec.label] = _summary(records)

    with (out_dir / "pathway_accuracy_records.jsonl").open("w") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _write_csv(out_dir / "pathway_accuracy_records.csv", all_records)

    d35_ci: dict[str, dict] = {}
    for pipeline in ("single", "feedback"):
        for mode in ("no_lit", "with_lit"):
            labels = [f"d3_5_{pipeline}_{mode}_run{i}" for i in (1, 2, 3)]
            present = [summaries[l] for l in labels if l in summaries]
            if not present:
                continue
            key = f"d3_5_{pipeline}_{mode}"
            d35_ci[key] = {
                "top1_pathway_strict_rate": _ci95_t3(
                    [s["top1_pathway_strict_rate"] for s in present]
                ),
                "top3_pathway_acceptance_rate": _ci95_t3(
                    [s["top3_pathway_acceptance_rate"] for s in present]
                ),
            }

    aggregate = {
        "tasks_path": args.tasks,
        "curated_path": args.curated,
        "summaries": summaries,
        "d3_5_ci": d35_ci,
    }
    (out_dir / "pathway_accuracy_summary.json").write_text(
        json.dumps(aggregate, indent=2, ensure_ascii=False) + "\n"
    )
    _write_markdown(
        out_dir / "pathway_accuracy_summary.md",
        summaries=summaries,
        d35_ci=d35_ci,
        records=all_records,
    )

    print(f"wrote {len(all_records)} scored records to {out_dir}")
    print(json.dumps(aggregate, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
