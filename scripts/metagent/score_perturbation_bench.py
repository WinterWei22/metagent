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


def extract_predicted(task_json: dict) -> str:
    """Best-available structured predicted pathway name from an agent output.

    Prefers the agent's declared `pathway_prediction.primary`; falls back to the
    first alternative. Returns '' when the agent emitted no structured prediction.
    """
    fr = task_json.get("final_react_result") or {}
    pp = fr.get("pathway_prediction") or {}
    primary = pp.get("primary") or {}
    name = (primary.get("pathway_name") or "").strip()
    if name:
        return name
    for alt in pp.get("alternatives") or []:
        alt_name = (alt.get("pathway_name") or "").strip()
        if alt_name:
            return alt_name
    return ""


def load_benchmark(path: str) -> dict[str, str]:
    golds = {}
    for line in open(path):
        row = json.loads(line)
        golds[row["task_id"]] = row["ground_truth"]["perturbed_pathway"]["name"]
    return golds


def score(benchmark: str, run_dirs: list[str], registry: str) -> dict:
    golds = load_benchmark(benchmark)
    matcher = build_matcher(os.environ["RAMP_DB_PATH"], registry)
    per_task: dict[str, dict] = {}
    for task_id, gold in golds.items():
        seeds = []
        for run in run_dirs:
            p = Path(run) / "path_x_full" / f"{task_id}.json"
            if not p.exists():
                continue
            predicted = extract_predicted(json.loads(p.read_text()))
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
