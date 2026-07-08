"""Score a perturbation-benchmark run with the graded pathway matcher (A1/A3).

Reads one or more seed run directories (each with path_x_full/<task_id>.json),
extracts each task's predicted pathway, grades it against the gold pathway with
the RaMP-backed graded matcher, and reports per-task tiers + strict/lenient
accuracy aggregated across seeds.

Deterministic and zero-LLM: the same run dirs always produce the same scorecard.

Usage:
  PYTHONPATH=. RAMP_DB_PATH=/data/.../ramp.sqlite python scripts/metagent/score_perturbation_bench.py \
      --benchmark /data/.../metagent_bench_final.jsonl \
      --runs /data/.../run_v13_seed1 /data/.../run_v13_seed2 /data/.../run_v13_seed3 \
      --registry data/benchmark/pathway_registry/gold_registry.json \
      --out /data/.../scorecard
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.metagent.pathway_match_rubric import MatchTier, build_matcher


def _react_results(task_json: dict) -> list[dict]:
    """All react results in chronological order: per-iteration then final.

    The post-feedback (final) iteration sometimes collapses to an empty
    narrative/claims/prediction; the pre-feedback iterations carry the
    complete prediction. We therefore scan them all.
    """
    out = []
    for it in task_json.get("iterations") or []:
        rr = it.get("react_result")
        if isinstance(rr, dict):
            out.append(rr)
    fr = task_json.get("final_react_result")
    if isinstance(fr, dict):
        out.append(fr)
    return out


def _primary_name(rr: dict) -> str:
    pp = rr.get("pathway_prediction") or {}
    primary = pp.get("primary") or {}
    name = (primary.get("pathway_name") or "").strip()
    if name:
        return name
    for alt in pp.get("alternatives") or []:
        alt_name = (alt.get("pathway_name") or "").strip()
        if alt_name:
            return alt_name
    return ""


def extract_predicted(task_json: dict, iteration: str = "iter0") -> str:
    """Deterministic predicted pathway name from an agent output trace.

    `iteration` selects which ReAct pass is scored:
      - "iter0"        : the pre-feedback (single-shot) prediction. CANONICAL
                         baseline — verifier feedback is documented to degrade the
                         pathway pick (W13/W14, 2026-06-29 §4.4), so the pathway
                         metric is reported single-shot.
      - "final"        : the post-feedback final prediction.
      - "last_nonempty": last non-empty primary across all iterations (legacy;
                         used to salvage collapsed cascade runs).

    Falls back to the top-ranked RaMP enrichment carrier only if no primary is
    declared. Returns '' when there is no signal at all.
    """
    results = _react_results(task_json)
    if not results:
        return ""
    if iteration == "iter0":
        candidates = [results[0]]
    elif iteration == "final":
        candidates = [results[-1]]
    else:  # last_nonempty
        candidates = list(reversed(results))
    for rr in candidates:
        name = _primary_name(rr)
        if name:
            return name
    for rr in candidates:  # fallback: top enrichment carrier
        ec = rr.get("enrichment_carriers") or {}
        ramp = ec.get("ramp_enrichment_result") or {}
        pw = ramp.get("pathways") or []
        if pw:
            top = (pw[0].get("pathway_name") or pw[0].get("name") or "").strip()
            if top:
                return top
    return ""


def load_benchmark(path: str) -> dict[str, dict]:
    rows = {}
    for line in open(path):
        row = json.loads(line)
        rows[row["task_id"]] = {
            "gold": row["ground_truth"]["perturbed_pathway"]["name"],
            "family": row.get("pathway_family", "?"),
            "gold_provenance": row.get("gold_provenance", "measured_cohort"),
        }
    return rows


def score(benchmark: str, run_dirs: list[str], registry: str, iteration: str = "iter0") -> dict:
    rows = load_benchmark(benchmark)
    matcher = build_matcher(os.environ["RAMP_DB_PATH"], registry)
    per_task: dict[str, dict] = {}
    for task_id, meta in rows.items():
        gold = meta["gold"]
        seeds = []
        for run in run_dirs:
            p = Path(run) / "path_x_full" / f"{task_id}.json"
            if not p.exists():
                continue
            predicted = extract_predicted(json.loads(p.read_text()), iteration=iteration)
            result = matcher.match(predicted=predicted, gold=gold)
            seeds.append({
                "run": Path(run).name,
                "predicted": predicted,
                "tier": result.tier.value,
                "strict": result.strict_credit,
                "lenient": result.lenient_credit,
                "evidence": result.evidence,
            })
        per_task[task_id] = {
            "gold": gold,
            "family": meta["family"],
            "gold_provenance": meta["gold_provenance"],
            "seeds": seeds,
            # A task counts (per-seed mean) toward strict/lenient; report the fraction.
            "strict_frac": _frac(seeds, "strict"),
            "lenient_frac": _frac(seeds, "lenient"),
        }
    n = len(per_task)
    summary = {
        "n_tasks": n,
        "n_seeds": len(run_dirs),
        "strict_mean": round(sum(t["strict_frac"] for t in per_task.values()) / n, 4) if n else 0.0,
        "lenient_mean": round(sum(t["lenient_frac"] for t in per_task.values()) / n, 4) if n else 0.0,
    }
    return {"summary": summary, "per_task": per_task}


def _frac(seeds: list[dict], key: str) -> float:
    if not seeds:
        return 0.0
    return sum(1 for s in seeds if s[key]) / len(seeds)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--registry", default="data/benchmark/pathway_registry/gold_registry.json")
    ap.add_argument("--out", default=None, help="output path prefix (.json)")
    args = ap.parse_args()

    result = score(args.benchmark, args.runs, args.registry)
    s = result["summary"]
    print(f"tasks={s['n_tasks']} seeds={s['n_seeds']}  "
          f"strict={s['strict_mean']:.1%}  lenient={s['lenient_mean']:.1%}")
    print(f"{'task':34s} {'strict':>7s} {'lenient':>8s}  gold / example predicted")
    for tid, t in result["per_task"].items():
        ex = t["seeds"][0]["predicted"] if t["seeds"] else "(none)"
        print(f"{tid:34s} {t['strict_frac']:>7.2f} {t['lenient_frac']:>8.2f}  "
              f"{t['gold'][:28]:28s} <- {ex[:34]}")
    if args.out:
        Path(args.out + ".json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"written {args.out}.json")


if __name__ == "__main__":
    main()
