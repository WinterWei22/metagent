"""SapBERT semantic pathway accuracy for A3 MiniMax outputs.

Writes per-task similarity rows and aggregate reports under
``paper_docs/stage2/minimax/semantic`` by default.
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

from evaluation.sub6.metrics import is_pathway_hit
from evaluation.sub6.pathway_extract import extract_pathway_mentions


DEFAULT_MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
THRESHOLDS = (0.70, 0.75, 0.80, 0.85)


def _threshold_suffix(threshold: float) -> str:
    return f"{threshold:.2f}".replace(".", "_")


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


class SapBertEncoder:
    def __init__(self, model_name: str, batch_size: int = 32, device: str | None = None):
        try:
            import torch
            import torch.nn.functional as F
            from transformers import AutoModel, AutoTokenizer
        except Exception as exc:
            raise RuntimeError(
                "SapBERT semantic scoring requires torch and transformers. "
                "Use an environment containing both, e.g. install transformers "
                "in the existing diffms env or install torch in the active env."
            ) from exc

        self.torch = torch
        self.F = F
        self.batch_size = batch_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(self.device)
        self.model.eval()

    def encode_unique(self, texts: Iterable[str]) -> dict[str, list[float]]:
        unique = sorted({t for t in texts if t})
        out: dict[str, list[float]] = {}
        with self.torch.inference_mode():
            for start in range(0, len(unique), self.batch_size):
                batch = unique[start : start + self.batch_size]
                toks = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=64,
                    return_tensors="pt",
                )
                toks = {k: v.to(self.device) for k, v in toks.items()}
                hidden = self.model(**toks).last_hidden_state
                emb = hidden[:, 0, :]
                emb = self.F.normalize(emb, p=2, dim=1).detach().cpu().tolist()
                out.update(zip(batch, emb))
        return out


def _cos(a: list[float] | None, b: list[float] | None) -> float | None:
    if a is None or b is None:
        return None
    return float(sum(x * y for x, y in zip(a, b)))


def _best_match(
    pred: str | None,
    candidates: list[str],
    embeddings: dict[str, list[float]],
) -> tuple[str | None, float | None, int | None]:
    if not pred or not candidates:
        return None, None, None
    pred_emb = embeddings.get(pred)
    scored: list[tuple[int, str, float]] = []
    for idx, name in enumerate(candidates, start=1):
        score = _cos(pred_emb, embeddings.get(name))
        if score is not None:
            scored.append((idx, name, score))
    if not scored:
        return None, None, None
    idx, name, score = max(scored, key=lambda x: x[2])
    return name, score, idx


def _collect_rows(spec: DatasetSpec, tasks_by_id: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for task_dir in _iter_task_dirs(spec.root):
        tid = task_dir.name
        task = tasks_by_id.get(tid)
        if task is None:
            print(f"WARN: {spec.label} task {tid} not in tasks file, skipping")
            continue
        narrative, payload = _load_narrative(task_dir, spec.pipeline)
        top_pathways = task.get("ramp_enrichment_result", {}).get("top_pathways", []) or []
        gt = task.get("ground_truth_pathway") or {}
        gt_name = gt.get("pathway_name") or ""
        top3_names = [p.get("pathway_name", "") for p in top_pathways[:3] if p.get("pathway_name")]
        top10_names = [p.get("pathway_name", "") for p in top_pathways[:10] if p.get("pathway_name")]
        known_names = list({n for n in top10_names + [gt_name] if n})
        mentions = extract_pathway_mentions(narrative, known_pathway_names=known_names)
        predicted = mentions[0].text if mentions else None

        rows.append(
            {
                "dataset": spec.label,
                "phase": spec.phase,
                "run": spec.run,
                "pipeline": spec.pipeline,
                "literature_mode": spec.literature_mode,
                "task_id": tid,
                "ground_truth_pathway": gt_name,
                "ground_truth_pathway_id": gt.get("pathway_id"),
                "ground_truth_pathway_source": gt.get("pathway_source"),
                "predicted_top_pathway": predicted,
                "strict_top1_hit": bool(predicted) and is_pathway_hit(predicted, [gt_name]),
                "strict_top3_hit": bool(predicted) and is_pathway_hit(predicted, top3_names),
                "top3_candidates": top3_names,
                "top10_candidates": top10_names,
                "extracted_pathways": [m.text for m in mentions],
                "n_extracted_pathways": len(mentions),
                "narrative_chars": len(narrative),
                "elapsed_seconds": payload.get("elapsed_seconds"),
                "error": payload.get("error"),
            }
        )
    return rows


def _add_similarity(rows: list[dict], embeddings: dict[str, list[float]], model_name: str) -> None:
    for row in rows:
        pred = row.get("predicted_top_pathway")
        gt = row.get("ground_truth_pathway")
        row["sapbert_model"] = model_name
        row["semantic_gt_similarity"] = _cos(
            embeddings.get(pred or ""), embeddings.get(gt or "")
        )
        best3_name, best3_score, best3_rank = _best_match(
            pred, row["top3_candidates"], embeddings
        )
        best10_name, best10_score, best10_rank = _best_match(
            pred, row["top10_candidates"], embeddings
        )
        row["semantic_top3_best_name"] = best3_name
        row["semantic_top3_best_similarity"] = best3_score
        row["semantic_top3_best_rank"] = best3_rank
        row["semantic_top10_best_name"] = best10_name
        row["semantic_top10_best_similarity"] = best10_score
        row["semantic_top10_best_rank"] = best10_rank
        for threshold in THRESHOLDS:
            suffix = _threshold_suffix(threshold)
            gt_score = row["semantic_gt_similarity"]
            top3_score = row["semantic_top3_best_similarity"]
            top10_score = row["semantic_top10_best_similarity"]
            row[f"semantic_gt_hit_at_{suffix}"] = bool(
                gt_score is not None and gt_score >= threshold
            )
            row[f"semantic_top3_hit_at_{suffix}"] = bool(
                top3_score is not None and top3_score >= threshold
            )
            row[f"semantic_top10_hit_at_{suffix}"] = bool(
                top10_score is not None and top10_score >= threshold
            )


def _mean(vals: list[float]) -> float | None:
    return statistics.fmean(vals) if vals else None


def _rate(rows: list[dict], key: str) -> float:
    return sum(1 for r in rows if r.get(key)) / len(rows) if rows else 0.0


def _summarise(rows: list[dict]) -> dict:
    scores_gt = [r["semantic_gt_similarity"] for r in rows if r.get("semantic_gt_similarity") is not None]
    scores_top3 = [
        r["semantic_top3_best_similarity"]
        for r in rows
        if r.get("semantic_top3_best_similarity") is not None
    ]
    scores_top10 = [
        r["semantic_top10_best_similarity"]
        for r in rows
        if r.get("semantic_top10_best_similarity") is not None
    ]
    out = {
        "n_tasks": len(rows),
        "n_with_predicted_pathway": sum(1 for r in rows if r.get("predicted_top_pathway")),
        "n_error_marker": sum(1 for r in rows if r.get("error")),
        "strict_top1_rate": _rate(rows, "strict_top1_hit"),
        "strict_top3_rate": _rate(rows, "strict_top3_hit"),
        "semantic_gt_similarity_mean": _mean(scores_gt),
        "semantic_top3_best_similarity_mean": _mean(scores_top3),
        "semantic_top10_best_similarity_mean": _mean(scores_top10),
    }
    for threshold in THRESHOLDS:
        suffix = _threshold_suffix(threshold)
        out[f"semantic_gt_hit_rate_at_{suffix}"] = _rate(
            rows, f"semantic_gt_hit_at_{suffix}"
        )
        out[f"semantic_top3_hit_rate_at_{suffix}"] = _rate(
            rows, f"semantic_top3_hit_at_{suffix}"
        )
        out[f"semantic_top10_hit_rate_at_{suffix}"] = _rate(
            rows, f"semantic_top10_hit_at_{suffix}"
        )
    return out


def _ci95_t3(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "ci95": None, "values": []}
    mean = statistics.fmean(values)
    if len(values) < 2:
        return {"n": len(values), "mean": mean, "ci95": None, "values": values}
    tcrit = 4.303 if len(values) == 3 else 1.96
    return {
        "n": len(values),
        "mean": mean,
        "ci95": tcrit * statistics.stdev(values) / math.sqrt(len(values)),
        "values": values,
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    cols = [
        "dataset",
        "phase",
        "run",
        "pipeline",
        "literature_mode",
        "task_id",
        "ground_truth_pathway",
        "ground_truth_pathway_id",
        "ground_truth_pathway_source",
        "predicted_top_pathway",
        "strict_top1_hit",
        "strict_top3_hit",
        "semantic_gt_similarity",
        "semantic_top3_best_name",
        "semantic_top3_best_similarity",
        "semantic_top3_best_rank",
        "semantic_top10_best_name",
        "semantic_top10_best_similarity",
        "semantic_top10_best_rank",
        "semantic_gt_hit_at_0_80",
        "semantic_top3_hit_at_0_80",
        "semantic_top10_hit_at_0_80",
        "top3_candidates",
        "top10_candidates",
        "extracted_pathways",
        "n_extracted_pathways",
        "narrative_chars",
        "elapsed_seconds",
        "error",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            for key in ("top3_candidates", "top10_candidates", "extracted_pathways"):
                flat[key] = "|".join(flat.get(key) or [])
            writer.writerow(flat)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.2f}%"


def _score(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.4f}"


def _write_report(
    path: Path,
    summaries: dict[str, dict],
    d35_ci: dict[str, dict],
    model_name: str,
) -> None:
    lines = [
        "# SapBERT Semantic Pathway Accuracy",
        "",
        f"Model: `{model_name}`. The score is cosine similarity between the first extracted pathway mention and the ground-truth/top-k pathway names after SapBERT encoding.",
        "",
        "Thresholded semantic hits are reported at several cutoffs; `@0.80` is the default operating point for quick comparison, not a biologically calibrated boundary.",
        "",
        "## D3 Full 63-Task",
        "",
        "| dataset | n | strict top1 | sem GT mean | sem GT @0.80 | sem top3 @0.80 | sem top10 @0.80 |",
        "|---|---:|---:|---:|---:|---:|---:|",
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
            f"| {label} | {s['n_tasks']} | {_pct(s['strict_top1_rate'])} | "
            f"{_score(s['semantic_gt_similarity_mean'])} | "
            f"{_pct(s['semantic_gt_hit_rate_at_0_80'])} | "
            f"{_pct(s['semantic_top3_hit_rate_at_0_80'])} | "
            f"{_pct(s['semantic_top10_hit_rate_at_0_80'])} |"
        )

    lines.extend(
        [
            "",
            "## D3.5 Rerun CI",
            "",
            "Mean +/- CI95 across run1/run2/run3 rates on the 10-task subset.",
            "",
            "| dataset | semantic GT @0.80 | semantic top3 @0.80 | semantic GT mean score |",
            "|---|---:|---:|---:|",
        ]
    )
    for label, ci in d35_ci.items():
        gt = ci["semantic_gt_hit_rate_at_0_80"]
        top3 = ci["semantic_top3_hit_rate_at_0_80"]
        score_ci = ci["semantic_gt_similarity_mean"]
        lines.append(
            f"| {label} | {_pct(gt['mean'])} +/- {_pct(gt['ci95'])} | "
            f"{_pct(top3['mean'])} +/- {_pct(top3['ci95'])} | "
            f"{_score(score_ci['mean'])} +/- {_score(score_ci['ci95'])} |"
        )
    path.write_text("\n".join(lines) + "\n")


def _dataset_specs(include_d35: bool) -> list[DatasetSpec]:
    specs = [
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
            "d3_metagent_wo_feedback_no_lit",
            Path("data/eval/sub6/v4_a3_d3_no_lit/react"),
            "single",
            "no_lit",
            "D3",
        ),
        DatasetSpec(
            "d3_metagent_wo_feedback_with_lit",
            Path("data/eval/sub6/v4_a3_d3_with_lit/react"),
            "single",
            "with_lit",
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
    if include_d35:
        for mode in ("no_lit", "with_lit"):
            for run_idx in (1, 2, 3):
                for pipeline in ("single", "feedback"):
                    specs.append(
                        DatasetSpec(
                            f"d3_5_{pipeline}_{mode}_run{run_idx}",
                            Path(
                                f"data/eval/sub6/v4_a3_d3_5/{mode}/run{run_idx}/{pipeline}"
                            ),
                            pipeline,
                            mode,
                            "D3.5",
                            f"run{run_idx}",
                        )
                    )
    return specs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")
    ap.add_argument("--out-dir", default="paper_docs/stage2/minimax/semantic")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--device", default=None)
    ap.add_argument("--skip-d35", action="store_true")
    args = ap.parse_args()

    tasks_by_id = {t["task_id"]: t for t in _load_jsonl(Path(args.tasks))}
    rows: list[dict] = []
    for spec in _dataset_specs(include_d35=not args.skip_d35):
        rows.extend(_collect_rows(spec, tasks_by_id))

    texts: set[str] = set()
    for row in rows:
        for key in ("predicted_top_pathway", "ground_truth_pathway"):
            if row.get(key):
                texts.add(row[key])
        texts.update(row["top3_candidates"])
        texts.update(row["top10_candidates"])

    encoder = SapBertEncoder(args.model, batch_size=args.batch_size, device=args.device)
    embeddings = encoder.encode_unique(texts)
    _add_similarity(rows, embeddings, args.model)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "semantic_similarity_records.jsonl").open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    _write_csv(out_dir / "semantic_similarity_records.csv", rows)

    summaries: dict[str, dict] = {}
    for label in sorted({r["dataset"] for r in rows}):
        summaries[label] = _summarise([r for r in rows if r["dataset"] == label])

    d35_ci: dict[str, dict] = {}
    for pipeline in ("single", "feedback"):
        for mode in ("no_lit", "with_lit"):
            labels = [f"d3_5_{pipeline}_{mode}_run{i}" for i in (1, 2, 3)]
            present = [summaries[l] for l in labels if l in summaries]
            if not present:
                continue
            d35_ci[f"d3_5_{pipeline}_{mode}"] = {
                "semantic_gt_hit_rate_at_0_80": _ci95_t3(
                    [s["semantic_gt_hit_rate_at_0_80"] for s in present]
                ),
                "semantic_top3_hit_rate_at_0_80": _ci95_t3(
                    [s["semantic_top3_hit_rate_at_0_80"] for s in present]
                ),
                "semantic_gt_similarity_mean": _ci95_t3(
                    [s["semantic_gt_similarity_mean"] for s in present if s["semantic_gt_similarity_mean"] is not None]
                ),
            }

    aggregate = {
        "tasks_path": args.tasks,
        "model": args.model,
        "thresholds": list(THRESHOLDS),
        "embedding_device": encoder.device,
        "n_records": len(rows),
        "summaries": summaries,
        "d3_5_ci": d35_ci,
    }
    (out_dir / "semantic_similarity_summary.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n"
    )
    _write_report(out_dir / "semantic_similarity_report.md", summaries, d35_ci, args.model)
    print(f"wrote {len(rows)} semantic similarity records to {out_dir}")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
