"""W8 D5 Path Z — RaMP-only baseline on sub6b-v3.

The simplest quad-report path: per task, run only `run_ramp_enrichment`
on the task's differential metabolites, and ask whether the task's
ground-truth pathway appears in RaMP's top-10. No LLM, no consensus
across paradigms, no feedback loop.

Why a separate file from path_w.py: Path W is a pure aggregation over
a frozen baseline JSONL; Path Z hits a live PA wrapper per task. They
share no IO surface.

Notes on the RaMP wrapper output shape (D5-surfaced):
- `ramp_wrapper.run_ramp_enrichment` returns a dict `{"report":
  EnrichmentReport, ...}` — NOT `{"pathways": [...]}` like
  mummichog. The `report.top_pathways` list contains
  `tools.benchmark.sub6.ramp_enrichment.EnrichmentResult` instances
  with fields {pathway_id (RAMP_P_...), pathway_name,
  pathway_external_id, pathway_source, p_value, fdr, ...}.
- The D2 ConcordMet tool dispatcher's `handle_run_ramp_enrichment`
  reads `raw.get("pathways")` which returns None on this shape →
  envelope reports `n_pathways=0` to the LLM. This is a D2 bug that
  D5 surfaces but does NOT fix (W9 candidate — see framework health
  report).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from concord.analyze.pathway_match import best_matching_rank


_DEFAULT_BENCHMARK = Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")


def _build_compound_refs(differential_metabolites: list[dict]) -> list[SimpleNamespace]:
    """Map sub6b-v3 differential_metabolites → duck-typed CompoundRef list.

    Sub6b-v3 metabolites carry `kegg_id` / `hmdb_id` / `inchikey`;
    ramp_wrapper reads attribute names `kegg_compound_id` / `hmdb_id`
    / `inchikey`. We construct a SimpleNamespace with the wrapper's
    expected attribute names.
    """
    refs: list[SimpleNamespace] = []
    for m in differential_metabolites:
        refs.append(SimpleNamespace(
            primary_id=f"KEGG:{m['kegg_id']}" if m.get("kegg_id") else "",
            chebi_id=None,
            hmdb_id=m.get("hmdb_id"),
            kegg_compound_id=m.get("kegg_id"),  # bare 'C00219', wrapper strips KEGG: prefix anyway
            lipidmaps_id=None,
            inchikey=m.get("inchikey", "") or "",
            display_name=m.get("name", "") or "",
        ))
    return refs


def _normalise_ramp_pathways(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a list of {pathway_id, pathway_name, pathway_external_id,
    pathway_source, p_value, fdr, rank} dicts from the RaMP wrapper's
    `{"report": EnrichmentReport}` output."""
    report = raw.get("report")
    if report is None:
        return []
    top = getattr(report, "top_pathways", None) or []
    return [
        {
            "pathway_id": getattr(p, "pathway_id", None),
            "pathway_name": getattr(p, "pathway_name", None),
            "pathway_external_id": getattr(p, "pathway_external_id", None),
            "pathway_source": getattr(p, "pathway_source", None),
            "p_value": getattr(p, "p_value", None),
            "fdr": getattr(p, "fdr", None),
            "rank": i,
        }
        for i, p in enumerate(top)
    ]


def _judge_hit(
    pathways: list[dict[str, Any]],
    gt_pathway_name: str,
    gt_external_id: str,
    *,
    top_n: int = 10,
    fuzzy_threshold: float = 0.5,
) -> tuple[bool, bool, int | None]:
    """Return (strict_hit, fuzzy_hit, fuzzy_rank).

    - strict: any top_n pathway's `pathway_external_id` equals
      gt_external_id (case-sensitive, source-namespace-agnostic).
    - fuzzy: token-Jaccard on pathway_name ≥ fuzzy_threshold against gt
      pathway_name (uses concord.analyze.pathway_match).
    """
    head = pathways[:top_n]
    strict = bool(gt_external_id) and any(
        (p.get("pathway_external_id") or "") == gt_external_id for p in head
    )
    names = [p.get("pathway_name") or "" for p in head]
    rank = best_matching_rank(gt_pathway_name, names, threshold=fuzzy_threshold)
    return strict, rank is not None, rank


def run_path_z_for_task(task: dict[str, Any]) -> dict[str, Any]:
    """Run RaMP-only baseline against one sub6b-v3 task. Never raises —
    on wrapper error the record carries an `error` string."""
    started = time.time()
    task_id = task.get("task_id", "unknown")
    gt = task.get("ground_truth_pathway") or {}
    gt_name = gt.get("pathway_name") or ""
    gt_ext = gt.get("external_id") or ""
    refs = _build_compound_refs(task.get("differential_metabolites") or [])

    error: str | None = None
    top_pathways: list[dict[str, Any]] = []
    n_input_resolved = 0
    try:
        from concord.wrappers import ramp_wrapper
        raw = ramp_wrapper.run_ramp_enrichment(refs, top_n=10)
        top_pathways = _normalise_ramp_pathways(raw)
        n_input_resolved = int(raw.get("n_input_resolved", 0) or 0)
    except (ImportError, ModuleNotFoundError, FileNotFoundError) as exc:
        error = f"ramp wrapper unavailable: {type(exc).__name__}: {exc}"
    except Exception as exc:
        error = f"ramp wrapper raised: {type(exc).__name__}: {exc}"

    strict_hit, fuzzy_hit, fuzzy_rank = _judge_hit(top_pathways, gt_name, gt_ext)

    return {
        "task_id": task_id,
        "ramp_top_pathways": top_pathways,
        "gt_pathway_name": gt_name,
        "gt_external_id": gt_ext,
        "strict_hit": strict_hit,
        "fuzzy_hit": fuzzy_hit,
        "fuzzy_rank": fuzzy_rank,
        "n_input": len(refs),
        "n_input_resolved": n_input_resolved,
        "wall_seconds": time.time() - started,
        "error": error,
    }


def aggregate_path_z(per_task: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-task records → precision@10 (strict + fuzzy)."""
    n_tasks = len(per_task)
    n_err = sum(1 for r in per_task if r.get("error"))
    n_strict = sum(1 for r in per_task if r.get("strict_hit"))
    n_fuzzy = sum(1 for r in per_task if r.get("fuzzy_hit"))
    return {
        "n_tasks": n_tasks,
        "n_error_tasks": n_err,
        "n_strict_hits": n_strict,
        "n_fuzzy_hits": n_fuzzy,
        "precision_at_10_strict": (n_strict / n_tasks) if n_tasks else 0.0,
        "precision_at_10_fuzzy": (n_fuzzy / n_tasks) if n_tasks else 0.0,
        "mean_wall_seconds": (
            sum(r.get("wall_seconds", 0.0) for r in per_task) / n_tasks
            if n_tasks else 0.0
        ),
    }


def run_path_z_batch(
    benchmark: Path = _DEFAULT_BENCHMARK,
    *,
    out_jsonl: Path,
    out_summary_json: Path,
) -> dict[str, Any]:
    """Sequential 63-task batch. Per-task records flushed as they
    complete so partial runs are usable."""
    if not benchmark.exists():
        raise FileNotFoundError(f"benchmark missing at {benchmark}")
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    out_summary_json.parent.mkdir(parents=True, exist_ok=True)

    per_task: list[dict[str, Any]] = []
    with benchmark.open() as f, out_jsonl.open("w") as out:
        for line in f:
            task = json.loads(line)
            rec = run_path_z_for_task(task)
            out.write(json.dumps({
                k: v for k, v in rec.items()
                # don't bloat jsonl with full pathway list per row
                if k != "ramp_top_pathways"
            }) + "\n")
            out.flush()
            per_task.append(rec)

    summary = aggregate_path_z(per_task)
    out_summary_json.write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=_DEFAULT_BENCHMARK)
    parser.add_argument("--out-jsonl", type=Path,
                         default=Path("data/concord/w8_llm_agent/path_z_ramp_only.jsonl"))
    parser.add_argument("--out-summary", type=Path,
                         default=Path("data/concord/w8_llm_agent/path_z_ramp_only_summary.json"))
    args = parser.parse_args()

    summary = run_path_z_batch(
        benchmark=args.benchmark,
        out_jsonl=args.out_jsonl,
        out_summary_json=args.out_summary,
    )
    print(f"Path Z (RaMP only) — {summary['n_tasks']} tasks")
    print(f"  errors:          {summary['n_error_tasks']}")
    print(f"  strict hits:     {summary['n_strict_hits']} → "
          f"precision@10 strict = {summary['precision_at_10_strict']:.3f}")
    print(f"  fuzzy  hits:     {summary['n_fuzzy_hits']} → "
          f"precision@10 fuzzy  = {summary['precision_at_10_fuzzy']:.3f}")
    print(f"  mean wall/task:  {summary['mean_wall_seconds']:.2f}s")
    print(f"jsonl  → {args.out_jsonl}")
    print(f"summary→ {args.out_summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
