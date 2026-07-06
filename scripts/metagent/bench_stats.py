"""Statistics + scorecard for a perturbation-benchmark run (Phase A).

Consumes the deterministic per-task tiers from score_perturbation_bench.score()
and reports, for our own model only:
  - overall strict / lenient accuracy (task-level mean) + 95% percentile-bootstrap CI
  - seed stability (min/max across seeds)
  - per-family (stratum) accuracy + n
  - tier distribution (exact / parent_child / adjacent / miss)

Bootstrap resampling uses a fixed seed for reproducibility. No baseline
comparison / permutation test (that is Phase B).
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict

from scripts.metagent.score_perturbation_bench import score

BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20260707


def _bootstrap_ci(values: list[float], reps: int = BOOTSTRAP_REPS) -> tuple[float, float]:
    """95% percentile bootstrap CI of the mean over task-level values."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(values)
    means = []
    for _ in range(reps):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * reps)]
    hi = means[int(0.975 * reps)]
    return (round(lo, 4), round(hi, 4))


def compute_stats(scored: dict) -> dict:
    per_task = scored["per_task"]
    strict_vals = [t["strict_frac"] for t in per_task.values()]
    lenient_vals = [t["lenient_frac"] for t in per_task.values()]
    n = len(per_task)

    # seed stability: per-seed overall strict accuracy across tasks.
    seed_names, seed_strict = _per_seed_overall(per_task)

    # per-family.
    fam_tasks: dict[str, list] = defaultdict(list)
    for t in per_task.values():
        fam_tasks[t["family"]].append(t)
    per_family = {}
    for fam, tasks in sorted(fam_tasks.items()):
        per_family[fam] = {
            "n": len(tasks),
            "strict": round(sum(x["strict_frac"] for x in tasks) / len(tasks), 4),
            "lenient": round(sum(x["lenient_frac"] for x in tasks) / len(tasks), 4),
        }

    # tier distribution over all task-seed judgements.
    tiers = Counter()
    for t in per_task.values():
        for s in t["seeds"]:
            tiers[s["tier"]] += 1

    return {
        "n_tasks": n,
        "n_seeds": scored["summary"]["n_seeds"],
        "strict_mean": round(sum(strict_vals) / n, 4) if n else 0.0,
        "strict_ci95": _bootstrap_ci(strict_vals),
        "lenient_mean": round(sum(lenient_vals) / n, 4) if n else 0.0,
        "lenient_ci95": _bootstrap_ci(lenient_vals),
        "seed_strict_overall": dict(zip(seed_names, seed_strict)),
        "seed_strict_range": [min(seed_strict), max(seed_strict)] if seed_strict else [0, 0],
        "per_family": per_family,
        "tier_distribution": dict(tiers),
    }


def _per_seed_overall(per_task: dict) -> tuple[list[str], list[float]]:
    by_seed: dict[str, list[bool]] = defaultdict(list)
    for t in per_task.values():
        for s in t["seeds"]:
            by_seed[s["run"]].append(bool(s["strict"]))
    names = sorted(by_seed)
    vals = [round(sum(by_seed[nm]) / len(by_seed[nm]), 4) for nm in names]
    return names, vals


def render_markdown(stats: dict, title: str = "Perturbation benchmark scorecard") -> str:
    L = [f"# {title}", ""]
    L.append(f"- Tasks: **{stats['n_tasks']}** · seeds: {stats['n_seeds']} · "
             f"deterministic graded matcher (RaMP registry)")
    sl, sh = stats["strict_ci95"]
    ll, lh = stats["lenient_ci95"]
    L.append(f"- **Strict accuracy: {stats['strict_mean']:.1%}** "
             f"(95% bootstrap CI {sl:.1%}–{sh:.1%})")
    L.append(f"- **Lenient accuracy: {stats['lenient_mean']:.1%}** "
             f"(95% bootstrap CI {ll:.1%}–{lh:.1%})")
    lo, hi = stats["seed_strict_range"]
    L.append(f"- Seed stability (strict, per-seed overall): {lo:.1%}–{hi:.1%} "
             f"({stats['seed_strict_overall']})")
    L.append("")
    L.append("## Per-family (stratum)")
    L.append("")
    L.append("| family | n | strict | lenient |")
    L.append("|---|---:|---:|---:|")
    for fam, v in stats["per_family"].items():
        L.append(f"| {fam} | {v['n']} | {v['strict']:.1%} | {v['lenient']:.1%} |")
    L.append("")
    L.append("## Tier distribution (all task-seed judgements)")
    L.append("")
    L.append("| tier | count |")
    L.append("|---|---:|")
    for tier in ("exact", "parent_child", "adjacent", "miss"):
        L.append(f"| {tier} | {stats['tier_distribution'].get(tier, 0)} |")
    L.append("")
    L.append("> Strict = exact + parent_child. Lenient adds adjacent. Miss always wrong. "
             "Denominator never drops a task. Descriptive benchmark — not a method-level "
             "significance claim; CIs are wide at this N.")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--registry", default="data/benchmark/pathway_registry/gold_registry.json")
    ap.add_argument("--out", default=None, help="output path prefix (.json + .md)")
    ap.add_argument("--title", default="Perturbation benchmark scorecard")
    args = ap.parse_args()

    scored = score(args.benchmark, args.runs, args.registry)
    stats = compute_stats(scored)
    md = render_markdown(stats, args.title)
    print(md)
    if args.out:
        from pathlib import Path
        Path(args.out + ".json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))
        Path(args.out + ".md").write_text(md)
        print(f"\nwritten {args.out}.json / .md")


if __name__ == "__main__":
    main()
