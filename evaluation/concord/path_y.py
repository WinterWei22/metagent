"""W8 D5 Path Y — V3 rank-weighted soft union baseline on sub6b-v3.

Driver-mode (no LLM): per task, run all 5 PA wrappers, normalise each
to V3-ready row form, then call `_weighted_top_v3` to get the top-10
consensus pathways. Match against task's ground truth.

D5 minimum-viable scope (per "framework health, not paper data"):
- ramp + mummichog have native shapes V3 can read (after the
  per-wrapper normaliser below).
- sspa / PSEA / FELLA normalisation is BEST-EFFORT — if the wrapper is
  unavailable (env missing sspa / Docker R) or its output's nested
  structure is opaque, the per-method block records an `error` and
  V3 sees empty pathways for that method. `_weighted_top_v3` is
  zero-tolerant (absent method → 0 score contribution).

The W9 backlog (D5-surfaced) includes fleshing out the sspa / PSEA /
FELLA output normalisers and re-running Path Y; that's not D5 scope.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from concord.analyze.gate2_variants import _weighted_top_v3
from concord.analyze.pathway_match import best_matching_rank


_DEFAULT_BENCHMARK = Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")


# ---------------------------------------------------------------------------
# Per-wrapper output → V3 row block normalisers
# ---------------------------------------------------------------------------


def _build_compound_refs(differential_metabolites: list[dict]) -> list[SimpleNamespace]:
    """sub6b-v3 metabolite list → duck-typed CompoundRef list."""
    refs: list[SimpleNamespace] = []
    for m in differential_metabolites:
        refs.append(SimpleNamespace(
            primary_id=f"KEGG:{m['kegg_id']}" if m.get("kegg_id") else "",
            chebi_id=None,
            hmdb_id=m.get("hmdb_id"),
            kegg_compound_id=m.get("kegg_id"),
            lipidmaps_id=None,
            inchikey=m.get("inchikey", "") or "",
            display_name=m.get("name", "") or "",
        ))
    return refs


def _ramp_block(refs: list[SimpleNamespace]) -> tuple[dict[str, Any], str]:
    """Return (V3 block, status). Status is 'ok' on success, 'error:...' otherwise."""
    try:
        from concord.wrappers import ramp_wrapper
        raw = ramp_wrapper.run_ramp_enrichment(refs, top_n=10)
        report = raw.get("report")
        if report is None:
            return ({"pathways": []}, "ok_no_report")
        pathways = [
            {
                "pathway_id": getattr(p, "pathway_id", None),
                "pathway_name": getattr(p, "pathway_name", None),
                "pathway_external_id": getattr(p, "pathway_external_id", None),
                "pathway_source": getattr(p, "pathway_source", None),
                "p_value": getattr(p, "p_value", None),
                "fdr": getattr(p, "fdr", None),
            }
            for p in (report.top_pathways or [])
        ]
        return ({"pathways": pathways}, "ok")
    except (ImportError, ModuleNotFoundError, FileNotFoundError) as exc:
        return ({"error": f"unavailable: {exc}", "pathways": []}, f"error: {type(exc).__name__}")
    except Exception as exc:
        return ({"error": f"raised: {exc!r}", "pathways": []}, f"error: {type(exc).__name__}")


def _mummichog_block(refs: list[SimpleNamespace]) -> tuple[dict[str, Any], str]:
    try:
        from concord.wrappers import mummichog_wrapper
        raw = mummichog_wrapper.run_mummichog_for_compound_set(refs)
        # native shape already has `pathways` list with pathway_name/id
        pathways = list(raw.get("pathways") or [])
        return ({"pathways": pathways}, "ok")
    except (ImportError, ModuleNotFoundError, FileNotFoundError) as exc:
        return ({"error": f"unavailable: {exc}", "pathways": []}, f"error: {type(exc).__name__}")
    except Exception as exc:
        return ({"error": f"raised: {exc!r}", "pathways": []}, f"error: {type(exc).__name__}")


def _sspa_block(refs: list[SimpleNamespace]) -> tuple[dict[str, Any], str]:
    """sspa wrapper not normalised for D5 — the wrapper's output is a
    method-key dict (ora / gsva / kpca / ...) without a unified
    `pathways` field, and the local env has the sspa pkg uninstalled
    anyway. D5 records this gap as a W9 candidate."""
    return (
        {"error": "sspa wrapper output shape not yet normalised for V3 driver mode (W9 candidate); env also lacks sspa pkg",
         "pathways": []},
        "deferred_w9",
    )


def _psea_block(refs: list[SimpleNamespace]) -> tuple[dict[str, Any], str]:
    """MetaboAnalystR PSEA — wrapper returns `{"raw": <R subprocess JSON>}`
    whose internal structure is library-specific. D5 records as W9
    candidate; uses the wrapper as-is and tries best-effort parse."""
    try:
        from concord.wrappers import metaboanalystr_wrapper
        raw = metaboanalystr_wrapper.run_metaboanalystr_psea(refs)
        if raw.get("error"):
            return ({"error": raw["error"], "pathways": []}, f"error: {raw['error']}")
        # Best-effort: R subprocess JSON sometimes carries `pathways`
        r_inner = raw.get("raw") or {}
        if isinstance(r_inner, dict) and r_inner.get("pathways"):
            return ({"pathways": list(r_inner["pathways"])}, "ok_partial")
        # No normaliser yet
        return ({"error": "PSEA output shape not yet normalised for V3 (W9)", "pathways": []},
                "deferred_w9")
    except (ImportError, ModuleNotFoundError, FileNotFoundError) as exc:
        return ({"error": f"unavailable: {exc}", "pathways": []}, f"error: {type(exc).__name__}")
    except Exception as exc:
        return ({"error": f"raised: {exc!r}", "pathways": []}, f"error: {type(exc).__name__}")


def _fella_block(refs: list[SimpleNamespace]) -> tuple[dict[str, Any], str]:
    """FELLA — same story as PSEA: R subprocess JSON output, no
    unified pathways list yet."""
    try:
        from concord.wrappers import fella_wrapper
        raw = fella_wrapper.run_fella_rwr(refs)
        if raw.get("error"):
            return ({"error": raw["error"], "pathways": []}, f"error: {raw['error']}")
        r_inner = raw.get("raw") or {}
        if isinstance(r_inner, dict) and r_inner.get("pathways"):
            return ({"pathways": list(r_inner["pathways"])}, "ok_partial")
        return ({"error": "FELLA output shape not yet normalised for V3 (W9)", "pathways": []},
                "deferred_w9")
    except (ImportError, ModuleNotFoundError, FileNotFoundError) as exc:
        return ({"error": f"unavailable: {exc}", "pathways": []}, f"error: {type(exc).__name__}")
    except Exception as exc:
        return ({"error": f"raised: {exc!r}", "pathways": []}, f"error: {type(exc).__name__}")


# ---------------------------------------------------------------------------
# V3 row builder + runner
# ---------------------------------------------------------------------------


def build_v3_row(task: dict[str, Any]) -> dict[str, Any]:
    """Run all 5 PA wrappers + normalise to V3 row format.

    Row shape matches what concord.analyze.gate2_variants._weighted_top_v3
    expects: method keys `sspa_ora` / `ramp` / `PSEA` / `mummichog` /
    `FELLA`, each carrying a dict with `pathways: [{pathway_name, ...}]`
    or an `error` block.
    """
    refs = _build_compound_refs(task.get("differential_metabolites") or [])
    gt = task.get("ground_truth_pathway") or {}

    ramp_block, ramp_status = _ramp_block(refs)
    mum_block, mum_status = _mummichog_block(refs)
    sspa_block, sspa_status = _sspa_block(refs)
    psea_block, psea_status = _psea_block(refs)
    fella_block, fella_status = _fella_block(refs)

    return {
        "task_id": task.get("task_id"),
        "ground_truth_pathway_name": gt.get("pathway_name") or "",
        "ground_truth_external_id": gt.get("external_id") or "",
        "sspa_ora": sspa_block,
        "ramp": ramp_block,
        "PSEA": psea_block,
        "mummichog": mum_block,
        "FELLA": fella_block,
        "per_method_status": {
            "sspa_ora": sspa_status, "ramp": ramp_status,
            "PSEA": psea_status, "mummichog": mum_status, "FELLA": fella_status,
        },
    }


def run_path_y_for_task(task: dict[str, Any]) -> dict[str, Any]:
    """Build V3 row + apply soft union → top-10 + match ground truth."""
    started = time.time()
    row = build_v3_row(task)
    top10_names = _weighted_top_v3(row, top_n=10)

    gt_name = row["ground_truth_pathway_name"]
    gt_ext = row["ground_truth_external_id"]
    fuzzy_rank = best_matching_rank(gt_name, top10_names, threshold=0.5)
    fuzzy_hit = fuzzy_rank is not None
    # Strict: external_id match against any of the original method's
    # pathway_external_id. Pull only from ramp (the only method we
    # normalised that carries external_id).
    ramp_paths = row["ramp"].get("pathways") or []
    strict_hit = bool(gt_ext) and any(
        (p.get("pathway_external_id") or "") == gt_ext for p in ramp_paths[:10]
    )

    return {
        "task_id": row["task_id"],
        "v3_top_pathways": top10_names,
        "gt_pathway_name": gt_name,
        "gt_external_id": gt_ext,
        "fuzzy_hit": fuzzy_hit,
        "fuzzy_rank": fuzzy_rank,
        "strict_hit": strict_hit,
        "per_method_status": row["per_method_status"],
        "wall_seconds": time.time() - started,
        "error": None,
    }


def aggregate_path_y(per_task: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(per_task)
    n_err = sum(1 for r in per_task if r.get("error"))
    n_strict = sum(1 for r in per_task if r.get("strict_hit"))
    n_fuzzy = sum(1 for r in per_task if r.get("fuzzy_hit"))
    return {
        "n_tasks": n,
        "n_error_tasks": n_err,
        "n_strict_hits": n_strict,
        "n_fuzzy_hits": n_fuzzy,
        "precision_at_10_strict": (n_strict / n) if n else 0.0,
        "precision_at_10_fuzzy": (n_fuzzy / n) if n else 0.0,
        "mean_wall_seconds": (
            sum(r.get("wall_seconds", 0.0) for r in per_task) / n if n else 0.0
        ),
    }


def run_path_y_batch(
    benchmark: Path = _DEFAULT_BENCHMARK,
    *,
    out_jsonl: Path,
    out_summary_json: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    if not benchmark.exists():
        raise FileNotFoundError(f"benchmark missing at {benchmark}")
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    out_summary_json.parent.mkdir(parents=True, exist_ok=True)

    per_task: list[dict[str, Any]] = []
    with benchmark.open() as f, out_jsonl.open("w") as out:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            task = json.loads(line)
            rec = run_path_y_for_task(task)
            out.write(json.dumps({k: v for k, v in rec.items()
                                   if k != "v3_top_pathways"} |
                                  {"v3_top_pathways": rec["v3_top_pathways"]}) + "\n")
            out.flush()
            per_task.append(rec)

    summary = aggregate_path_y(per_task)
    out_summary_json.write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=_DEFAULT_BENCHMARK)
    parser.add_argument("--out-jsonl", type=Path,
                         default=Path("data/concord/w8_llm_agent/path_y_v3_algorithm_results.jsonl"))
    parser.add_argument("--out-summary", type=Path,
                         default=Path("data/concord/w8_llm_agent/path_y_v3_algorithm_summary.json"))
    parser.add_argument("--limit", type=int, default=None,
                         help="Optional cap on number of tasks (sample mode).")
    args = parser.parse_args()

    summary = run_path_y_batch(
        benchmark=args.benchmark,
        out_jsonl=args.out_jsonl,
        out_summary_json=args.out_summary,
        limit=args.limit,
    )
    print(f"Path Y (V3 algorithm) — {summary['n_tasks']} tasks")
    print(f"  errors:          {summary['n_error_tasks']}")
    print(f"  strict hits:     {summary['n_strict_hits']} → precision@10 strict = {summary['precision_at_10_strict']:.3f}")
    print(f"  fuzzy  hits:     {summary['n_fuzzy_hits']} → precision@10 fuzzy  = {summary['precision_at_10_fuzzy']:.3f}")
    print(f"  mean wall/task:  {summary['mean_wall_seconds']:.2f}s")
    print(f"jsonl  → {args.out_jsonl}")
    print(f"summary→ {args.out_summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
