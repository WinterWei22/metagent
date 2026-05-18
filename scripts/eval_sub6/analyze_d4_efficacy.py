"""Phase B1 P0 Stage A1.6 Step 3 — D4 efficacy on D5 v2 corrected data.

The corrected aggregator (A1.5 audit + A1.6 re-emit) revealed that
D4 feedback iter fired 144/189 times in D5 v2 — NOT 0/189 as the
buggy old aggregator reported. The natural follow-up question
becomes: did those 144 iterations actually improve the result?

For each task with ``n_feedback_iterations > 0`` this script computes
three deltas between iter 0 (N0) and the final selected iter (N_final):

  - delta_quality      = quality_N0 - quality_final
                         (quality = contra + unsup + UV; >0 = improved)
  - delta_supported    = supported_final - supported_N0  (>0 = improved)
  - delta_top1_hybrid  = top1_final - top1_N0  (boolean delta in
                         {-1, 0, +1}; uses the hybrid extractor —
                         claims-first when any pathway_enrichment
                         claim exists, narrative-first otherwise)

Aggregates: N_improved / N_unchanged / N_worse, mean deltas, and
rollback occurrences (where ``rollback_reason`` fired and we kept N0).

Inputs:
  --input         root with seed_*/<task>/result.json
  --tasks         benchmark jsonl (for gt_name / RaMP top10)
  --curated       curated jsonl for CompoundLookup
  --report        output markdown path

Output:
  reports/agent/phase_b1_d4_efficacy.md  (per-seed + cross-seed tables)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.compound_lookup import CompoundLookup
from evaluation.sub6.metrics import compute_task_metrics, is_pathway_hit


# ---------------------------------------------------------------------------
# Hybrid extractor on a single (iter-or-final) narrative
# ---------------------------------------------------------------------------


def _parse_narrative_payload(narrative_raw: str) -> tuple[str, list[dict]]:
    """Parse the v2 JSON narrative string.

    Returns (narrative_text, claims). On parse failure returns ("", []).
    """
    if not narrative_raw:
        return "", []
    try:
        d = json.loads(narrative_raw)
    except Exception:
        # Some legacy iters may store plain text rather than JSON.
        return narrative_raw, []
    nt = d.get("narrative_text", "") or ""
    claims = d.get("claims", []) or []
    return nt, claims


def _method_a_top1(narrative_text: str, task: dict, lookup: CompoundLookup) -> bool:
    """A3-style: first-mentioned pathway in narrative_text."""
    if not narrative_text:
        return False
    return bool(compute_task_metrics(narrative_text, task, lookup).top1_pathway_strict)


def _method_b_top1(claims: list[dict], gt_name: str) -> tuple[bool | None, int]:
    """Claims-first: first pathway_enrichment claim's term_name vs gt.

    Returns (top1_b_or_None, n_pathway_enrichment_claims).
    None means "no pathway_enrichment claim emitted" — caller falls back.
    """
    pe = [c for c in claims if c.get("grammar") == "pathway_enrichment"]
    if not pe:
        return None, 0
    pred = pe[0].get("term_name") or pe[0].get("pathway_name") or ""
    if not pred:
        return False, len(pe)
    return is_pathway_hit(pred, [gt_name]), len(pe)


def hybrid_top1(narrative_raw: str, task: dict, lookup: CompoundLookup) -> dict:
    """Run all three methods on one narrative payload."""
    nt, claims = _parse_narrative_payload(narrative_raw)
    a = _method_a_top1(nt, task, lookup)
    b, n_pe = _method_b_top1(claims, task.get("ground_truth_pathway", {}).get("pathway_name", "") or "")
    c = b if b is not None else a
    return {
        "method_a_top1": a,
        "method_b_top1": b,
        "method_c_top1": c,
        "n_pathway_enrichment_claims": n_pe,
        "narrative_chars": len(nt),
    }


# ---------------------------------------------------------------------------
# Per-task efficacy: iter 0 vs final
# ---------------------------------------------------------------------------


def _quality_from_verdict_total(vt: dict) -> int:
    """Same formula as the P0-fixed _quality_score."""
    return (
        int(vt.get("contradicted", 0) or 0)
        + int(vt.get("unsupported", 0) or 0)
        + int(vt.get("unverifiable_v0", 0) or 0)
    )


def _supported_ratio(vt: dict) -> float:
    total = sum(int(v or 0) for v in vt.values())
    if total == 0:
        return 0.0
    return int(vt.get("supported", 0) or 0) / total


def per_task_efficacy(
    result: dict, task: dict, lookup: CompoundLookup
) -> dict | None:
    """Returns the efficacy record for one task, or None if not eligible.

    Eligible = ``n_feedback_iterations > 0`` AND at least 2 iterations
    were recorded in ``result.iterations``.
    """
    n_fb = int(result.get("n_feedback_iterations", 0) or 0)
    iters = result.get("iterations", []) or []
    if n_fb == 0 or len(iters) < 2:
        return None
    final_idx = int(result.get("final_iter_idx", len(iters) - 1) or 0)
    final_idx = max(0, min(final_idx, len(iters) - 1))
    n0 = iters[0]
    nF = iters[final_idx]

    q0 = _quality_from_verdict_total(n0.get("verdict_total", {}) or {})
    qF = _quality_from_verdict_total(nF.get("verdict_total", {}) or {})
    s0 = _supported_ratio(n0.get("verdict_total", {}) or {})
    sF = _supported_ratio(nF.get("verdict_total", {}) or {})

    h0 = hybrid_top1(n0.get("narrative", "") or "", task, lookup)
    hF = hybrid_top1(nF.get("narrative", "") or "", task, lookup)

    return {
        "task_id": result.get("task_id"),
        "n_feedback_iterations": n_fb,
        "final_iter_idx": final_idx,
        "rollback_reason": result.get("rollback_reason"),
        "termination_reason": result.get("termination_reason"),
        "quality_n0": q0,
        "quality_final": qF,
        "delta_quality": q0 - qF,
        "supported_n0": s0,
        "supported_final": sF,
        "delta_supported": sF - s0,
        "top1_n0": h0["method_c_top1"],
        "top1_final": hF["method_c_top1"],
        "delta_top1": int(hF["method_c_top1"]) - int(h0["method_c_top1"]),
        "n_pe_claims_n0": h0["n_pathway_enrichment_claims"],
        "n_pe_claims_final": hF["n_pathway_enrichment_claims"],
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _bucket(deltas: list[int | float]) -> dict:
    if not deltas:
        return {"n": 0, "improved": 0, "unchanged": 0, "worse": 0, "mean": 0.0}
    return {
        "n": len(deltas),
        "improved": sum(1 for d in deltas if d > 0),
        "unchanged": sum(1 for d in deltas if d == 0),
        "worse": sum(1 for d in deltas if d < 0),
        "mean": sum(deltas) / len(deltas),
        "median": statistics.median(deltas),
    }


def aggregate(per_task: list[dict]) -> dict:
    qd = [t["delta_quality"] for t in per_task]
    sd = [t["delta_supported"] for t in per_task]
    td = [t["delta_top1"] for t in per_task]
    return {
        "n_with_feedback": len(per_task),
        "quality": _bucket(qd),
        "supported": _bucket(sd),
        "top1_hybrid": _bucket(td),
        "rollback_count": sum(1 for t in per_task if t["rollback_reason"]),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _fmt_bucket(b: dict, *, pct: bool = False) -> str:
    if b["n"] == 0:
        return "n=0"
    mean = b["mean"] * 100 if pct else b["mean"]
    unit = " pp" if pct else ""
    return (f"n={b['n']} · ↑{b['improved']} / ={b['unchanged']} / "
            f"↓{b['worse']} · mean Δ={mean:+.2f}{unit}")


def render_markdown(per_seed_results: dict[str, dict], overall: dict,
                    per_task_seed0_sample: list[dict]) -> str:
    L = []
    L.append("# Phase B1 D4 — Feedback efficacy on D5 v2 corrected data\n")
    L.append("**Source:** `data/eval/sub6/b1_d5_v2_full_feedback_lit/` "
             "(post A1.6 aggregator correction)\n")
    L.append("**Stage:** Phase B1 P0 Stage A1.6 Step 3\n")
    L.append("**Question:** the corrected aggregator showed D4 feedback "
             "fired **144/189** times in D5 v2 (not 0/189 as previously "
             "reported). Did those iterations actually improve the "
             "result?\n")
    L.append("**Method:** per task with `n_feedback_iterations > 0`, "
             "compute iter-0 vs final-iter delta on three metrics:\n")
    L.append("- **quality** = contradicted + unsupported + unverifiable_v0 "
             "(per the P0-fixed `_quality_score`). Positive Δ = improved.\n")
    L.append("- **supported ratio** = #supported / total_verdicts. "
             "Positive Δ = improved.\n")
    L.append("- **top1 hybrid** = Step Z hybrid extractor (claims-first "
             "when any `pathway_enrichment` claim exists, else "
             "narrative-first via `evaluation/sub6/metrics.py`). Δ in "
             "`{-1, 0, +1}` per task.\n")
    L.append("---\n")

    L.append("## Per-seed breakdown\n")
    L.append("| seed | n_fb_iter>0 | Δ quality | Δ supported | Δ top1 | rollbacks |")
    L.append("|---|---|---|---|---|---|")
    for seed, agg in sorted(per_seed_results.items()):
        L.append(
            f"| {seed} | {agg['n_with_feedback']} | "
            f"{_fmt_bucket(agg['quality'])} | "
            f"{_fmt_bucket(agg['supported'], pct=True)} | "
            f"{_fmt_bucket(agg['top1_hybrid'])} | "
            f"{agg['rollback_count']} |"
        )
    L.append("")

    L.append("## Overall (all 3 seeds pooled)\n")
    L.append(f"- **n tasks with feedback fired:** {overall['n_with_feedback']}")
    L.append(f"- **quality:** {_fmt_bucket(overall['quality'])}")
    L.append(f"- **supported ratio:** {_fmt_bucket(overall['supported'], pct=True)}")
    L.append(f"- **top1 hybrid:** {_fmt_bucket(overall['top1_hybrid'])}")
    L.append(f"- **rollback (quality_N0 better → kept N0):** "
             f"{overall['rollback_count']}\n")

    L.append("## Interpretation guidance\n")
    L.append("Decision rules for downstream P0 rerun planning:\n")
    L.append("- If **mean Δ quality > 0 with N improved > N worse** → "
             "D4 has real signal; the P0 fix (adding UV to `_quality_score`) "
             "should expand the effective trigger surface and is worth a "
             "rerun.\n")
    L.append("- If **mean Δ quality ≈ 0 and improved ≈ worse** → "
             "feedback triggers but doesn't move the needle; investigate "
             "hint quality (feedback_hints.py) before any rerun.\n")
    L.append("- If **mean Δ quality < 0 and rollback_count is high** → "
             "rollback is the only thing protecting outcomes; investigate "
             "rollback logic in `_select_final_iteration`.\n")

    L.append("---\n")
    L.append("## Sample (seed 0, first 5 eligible tasks)\n")
    L.append("| task | n_fb | qN0→qF | suppN0→suppF | top1 N0→F | term |")
    L.append("|---|---|---|---|---|---|")
    for r in per_task_seed0_sample[:5]:
        L.append(
            f"| `{r['task_id'][-30:]}` | {r['n_feedback_iterations']} | "
            f"{r['quality_n0']}→{r['quality_final']} "
            f"(Δ{r['delta_quality']:+d}) | "
            f"{r['supported_n0']*100:.1f}→{r['supported_final']*100:.1f} "
            f"(Δ{r['delta_supported']*100:+.1f}pp) | "
            f"{int(r['top1_n0'])}→{int(r['top1_final'])} | "
            f"{r['termination_reason']} |"
        )
    L.append("")
    L.append("Full per-task records (all seeds) are written alongside as "
             "`d4_efficacy_per_task.json` in the input root.\n")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument(
        "--tasks", type=Path,
        default=Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl"),
    )
    ap.add_argument(
        "--curated", type=Path,
        default=Path("data/benchmark/sub6/curated_hmdb_mammalian.jsonl"),
    )
    ap.add_argument("--report", required=True, type=Path)
    args = ap.parse_args(argv)

    # Load benchmark for gt lookup.
    tasks_by_id: dict[str, dict] = {}
    with args.tasks.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            tasks_by_id[t["task_id"]] = t

    lookup = CompoundLookup.from_curated(args.curated)

    seed_dirs = sorted(d for d in args.input.iterdir()
                       if d.is_dir() and d.name.startswith("seed_"))

    all_records: list[dict] = []
    per_seed_records: dict[str, list[dict]] = {}
    for sd in seed_dirs:
        seed_recs: list[dict] = []
        for td in sorted(d for d in sd.iterdir() if d.is_dir()):
            rf = td / "result.json"
            if not rf.exists():
                continue
            result = json.loads(rf.read_text())
            tid = result.get("task_id")
            # task_id in result is e.g. "compound_only_enrich_mammalian_RAMP_..._seed1"
            # Benchmark uses just the suffix piece. Try direct then strip prefix.
            task = tasks_by_id.get(tid)
            if task is None:
                # Try stripping the "compound_only_enrich_mammalian_" prefix.
                for prefix in (
                    "compound_only_enrich_mammalian_",
                    "compound_only_enrich_lipid_",
                ):
                    if tid and tid.startswith(prefix):
                        task = tasks_by_id.get(tid[len(prefix):])
                        if task:
                            break
            if task is None:
                # Fall back to a minimal stub so extraction can still
                # parse (gt_name will be empty so top1 will be False).
                task = {"ground_truth_pathway": {}, "differential_metabolites": []}
            rec = per_task_efficacy(result, task, lookup)
            if rec is not None:
                rec["seed"] = sd.name
                seed_recs.append(rec)
                all_records.append(rec)
        per_seed_records[sd.name] = seed_recs

    per_seed_results = {s: aggregate(recs) for s, recs in per_seed_records.items()}
    overall = aggregate(all_records)

    md = render_markdown(per_seed_results, overall,
                         per_task_seed0_sample=per_seed_records.get("seed_0", []))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(md)

    raw_out = args.input / "d4_efficacy_per_task.json"
    raw_out.write_text(json.dumps(all_records, indent=2))

    print(f"Wrote report to {args.report}")
    print(f"Wrote per-task JSON to {raw_out}")
    print(f"Overall: {overall['n_with_feedback']} tasks with feedback fired")
    print(f"  quality:   {_fmt_bucket(overall['quality'])}")
    print(f"  supported: {_fmt_bucket(overall['supported'], pct=True)}")
    print(f"  top1:      {_fmt_bucket(overall['top1_hybrid'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
