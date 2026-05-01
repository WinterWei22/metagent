"""Aggregate verifier verdicts (output of grade_with_verifier.py) into a
results-shaped directory mirroring ``results/sub6/`` for Sub-6B.

Reads:
  - <verdicts.jsonl>   (one record per task: task_id, verdicts_total,
                        verdicts_by_type, claims, ...)
  - <narratives.jsonl> (the narratives that were graded — used to enrich
                        the per-task markdown so the reader sees the
                        narrative + verdicts side-by-side)
  - <tasks.jsonl>      (source tasks for GT pathway / signal / noise context)

Writes (under <out-dir>):
  - <track>_verdicts.jsonl   (raw verifier output, copied)
  - <track>_verdicts.md      (per-task verdict scorecard + claim list + narrative)
  - <track>_verdicts.csv     (flat per-task: verdict counts + headline metrics)
  - <track>_verdicts_summary.json   (aggregated rates / counters)
  - README.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_jsonl(p: Path) -> list[dict]:
    out: list[dict] = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# Verifier emits lowercase enum values (verdict.value, claim_type.value).
_VERDICT_KEYS = ("supported", "unsupported", "contradicted", "unverifiable_v0")
_CLAIM_TYPE_KEYS = (
    "set_enrichment", "driver_metabolite", "pathway_relationship",
    "biological_claim", "grounded_claim", "factual_claim",
    "literature_claim", "peak_mechanistic", "consistency",
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True, help="Output of grade_with_verifier.py")
    ap.add_argument("--narratives", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--track", required=True, help="Logical track label (sub6b / sub6a_perfect_id / ...)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    verdicts = _load_jsonl(Path(args.verdicts))
    narratives = {r["task_id"]: r for r in _load_jsonl(Path(args.narratives))}
    tasks = {t["task_id"]: t for t in _load_jsonl(Path(args.tasks))}

    # 1. Copy raw verdicts.
    shutil.copyfile(args.verdicts, out_dir / f"{args.track}_verdicts.jsonl")

    # 2. Per-task aggregation.
    n = len(verdicts)
    n_ok = sum(1 for r in verdicts if r.get("error") is None)

    # Aggregate counters across all tasks.
    agg_total = Counter()
    agg_by_type: dict[str, Counter] = {}
    n_with_supported_set_enrichment = 0
    n_with_contradicted_driver = 0
    total_claims = 0
    total_claims_by_type = Counter()
    verifier_llm_calls_total = 0

    rows_csv: list[dict] = []

    for r in verdicts:
        tid = r["task_id"]
        verdicts_total = r.get("verdicts_total") or {}
        verdicts_by_type = r.get("verdicts_by_type") or {}
        for v, cnt in verdicts_total.items():
            agg_total[v] += cnt
            total_claims += cnt
        for ct, vmap in verdicts_by_type.items():
            agg_by_type.setdefault(ct, Counter())
            for v, cnt in vmap.items():
                agg_by_type[ct][v] += cnt
                total_claims_by_type[ct] += cnt
        # Headline-friendly bool flags.
        se_supp = (verdicts_by_type.get("set_enrichment", {}) or {}).get("supported", 0) > 0
        dm_contra = (verdicts_by_type.get("driver_metabolite", {}) or {}).get("contradicted", 0) > 0
        if se_supp:
            n_with_supported_set_enrichment += 1
        if dm_contra:
            n_with_contradicted_driver += 1
        verifier_llm_calls_total += int(r.get("verifier_llm_calls") or 0)

        rows_csv.append({
            "task_id": tid,
            "track": r.get("track"),
            "n_claims": sum(verdicts_total.values()) if verdicts_total else 0,
            "supported": verdicts_total.get("supported", 0),
            "unsupported": verdicts_total.get("unsupported", 0),
            "contradicted": verdicts_total.get("contradicted", 0),
            "unverifiable_v0": verdicts_total.get("unverifiable_v0", 0),
            "set_enrichment_supported_any": int(se_supp),
            "driver_metabolite_contradicted_any": int(dm_contra),
            "elapsed_seconds": r.get("elapsed_seconds"),
            "verifier_llm_calls": r.get("verifier_llm_calls"),
            "warnings": "; ".join(r.get("warnings") or []),
            "error": r.get("error"),
        })

    # CSV.
    csv_cols = [
        "task_id", "track",
        "n_claims",
        "supported", "unsupported", "contradicted", "unverifiable_v0",
        "set_enrichment_supported_any",
        "driver_metabolite_contradicted_any",
        "elapsed_seconds", "verifier_llm_calls",
        "warnings", "error",
    ]
    with (out_dir / f"{args.track}_verdicts.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for row in rows_csv:
            w.writerow(row)

    # Summary JSON.
    def _verdict_rate(v: str) -> float:
        return (agg_total.get(v, 0) / total_claims) if total_claims else 0.0

    summary = {
        "track": args.track,
        "n_tasks": n,
        "n_ok": n_ok,
        "n_error": n - n_ok,
        "total_claims": total_claims,
        "verifier_llm_calls_total": verifier_llm_calls_total,
        "verdicts_total": {k: agg_total.get(k, 0) for k in _VERDICT_KEYS},
        "verdict_rates": {k: _verdict_rate(k) for k in _VERDICT_KEYS},
        "claims_by_type": {k: total_claims_by_type.get(k, 0) for k in _CLAIM_TYPE_KEYS},
        "verdicts_by_type": {
            k: {v: agg_by_type.get(k, Counter()).get(v, 0) for v in _VERDICT_KEYS}
            for k in _CLAIM_TYPE_KEYS
            if total_claims_by_type.get(k, 0) > 0
        },
        "tasks_with_any_supported_set_enrichment": n_with_supported_set_enrichment,
        "tasks_with_any_contradicted_driver": n_with_contradicted_driver,
    }
    with (out_dir / f"{args.track}_verdicts_summary.json").open("w") as f:
        json.dump(summary, f, indent=2)

    # 3. Markdown.
    md: list[str] = [f"# Verifier Verdicts — `{args.track}`", ""]
    md.append(f"- **n_tasks**: {n}")
    md.append(f"- **errors**: {summary['n_error']}")
    md.append(f"- **total claims**: {total_claims}")
    md.append(f"- **verifier LLM calls (total)**: {verifier_llm_calls_total}")
    md.append("")
    md.append("## Aggregate verdict counts")
    md.append("")
    md.append("| Verdict | Count | Rate |")
    md.append("|---|---:|---:|")
    for v in _VERDICT_KEYS:
        cnt = agg_total.get(v, 0)
        rate = _verdict_rate(v)
        md.append(f"| {v} | {cnt} | {rate:.2%} |")
    md.append("")
    md.append("## Verdicts by claim type")
    md.append("")
    md.append("| Claim type | Total | supported | unsupported | contradicted | unverifiable_v0 |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for ct in _CLAIM_TYPE_KEYS:
        total = total_claims_by_type.get(ct, 0)
        if total == 0:
            continue
        c = agg_by_type.get(ct, Counter())
        md.append(
            f"| {ct} | {total} | {c.get('supported',0)} | "
            f"{c.get('unsupported',0)} | {c.get('contradicted',0)} | "
            f"{c.get('unverifiable_v0',0)} |"
        )
    md.append("")
    md.append("---")
    md.append("")

    for r in verdicts:
        tid = r["task_id"]
        narr_rec = narratives.get(tid, {})
        task = tasks.get(tid, {})
        gt = task.get("ground_truth_pathway", {}).get("pathway_name", "?")
        md.append(f"## {tid}")
        md.append("")
        md.append(f"- **GT pathway**: `{gt}`")
        vt = r.get("verdicts_total") or {}
        md.append(
            f"- **verdicts**: SUPP={vt.get('supported',0)}, "
            f"UNSUPP={vt.get('unsupported',0)}, "
            f"CONTRA={vt.get('contradicted',0)}, "
            f"UV0={vt.get('unverifiable_v0',0)}"
        )
        md.append(
            f"- **verifier_llm_calls**: {r.get('verifier_llm_calls')}, "
            f"elapsed: {r.get('elapsed_seconds', 0):.1f}s"
        )
        if r.get("error"):
            md.append(f"- **error**: `{r['error']}`")
        if r.get("warnings"):
            md.append(f"- **warnings**: {r['warnings']}")

        md.append("")
        md.append("### Claims")
        md.append("")
        md.append("| # | type | verdict | claim text (head) | correction |")
        md.append("|---:|---|---|---|---|")
        for i, c in enumerate(r.get("claims") or []):
            ct = c.get("claim_type") or "?"
            verdict = c.get("verdict") or "?"
            ctext = (c.get("claim_text") or "").replace("\n", " ").replace("|", "\\|")[:120]
            corr = (c.get("correction") or "").replace("\n", " ").replace("|", "\\|")[:80]
            md.append(f"| {i+1} | {ct} | {verdict} | {ctext} | {corr} |")
        md.append("")

        narrative = (narr_rec.get("narrative") or "").strip()
        if narrative:
            md.append("### Source narrative")
            md.append("")
            md.append(narrative)
            md.append("")
        md.append("---")
        md.append("")

    (out_dir / f"{args.track}_verdicts.md").write_text("\n".join(md))

    # 4. README.
    readme = f"""# Verifier-graded results — `{args.track}`

Output of `verifier.agent.verify_sub6` applied to the Sub-6 narratives
under track `{args.track}`. Mirrors the layout of `results/sub6/` (the
extractor-graded baseline) so the two scorings can be diffed.

## Files

- `{args.track}_verdicts.jsonl`         — raw verifier output (one record per task)
- `{args.track}_verdicts.csv`           — flat per-task verdict counts
- `{args.track}_verdicts_summary.json`  — aggregate verdict counters / rates
- `{args.track}_verdicts.md`            — per-task scorecard + claim list + narrative
- `README.md`                            — this file

## Headline numbers

| Metric | Value |
|---|---:|
| n_tasks               | {summary['n_tasks']} |
| n_error               | {summary['n_error']} |
| total claims          | {summary['total_claims']} |
| verifier LLM calls    | {summary['verifier_llm_calls_total']} |
| supported             | {summary['verdicts_total']['supported']} ({summary['verdict_rates']['supported']:.2%}) |
| unsupported           | {summary['verdicts_total']['unsupported']} ({summary['verdict_rates']['unsupported']:.2%}) |
| contradicted          | {summary['verdicts_total']['contradicted']} ({summary['verdict_rates']['contradicted']:.2%}) |
| unverifiable_v0       | {summary['verdicts_total']['unverifiable_v0']} ({summary['verdict_rates']['unverifiable_v0']:.2%}) |
| tasks w/ ≥1 SUPPORTED set_enrichment | {summary['tasks_with_any_supported_set_enrichment']} / {summary['n_tasks']} |
| tasks w/ ≥1 CONTRADICTED driver_metabolite | {summary['tasks_with_any_contradicted_driver']} / {summary['n_tasks']} |

## How to reproduce

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python scripts/eval_sub6/grade_with_verifier.py \\
    --narratives results/sub6/sub6b_narratives.jsonl \\
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \\
    --out data/eval/sub6/sub6b_verdicts.jsonl \\
    --track {args.track}
python scripts/eval_sub6/aggregate_verifier.py \\
    --verdicts data/eval/sub6/sub6b_verdicts.jsonl \\
    --narratives results/sub6/sub6b_narratives.jsonl \\
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \\
    --track {args.track} \\
    --out-dir {args.out_dir}
```
"""
    (out_dir / "README.md").write_text(readme)

    print(f"wrote {n} task records to {out_dir}/")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
