"""Phase B1 canonical aggregator for D5 v2-style runs.

Re-derives ``seed_summary.json`` and ``d5_aggregate.json`` directly
from per-task ``result.json`` + ``verdict_final.json``. Replaces the
unrecoverable ad-hoc script that produced the original on-disk
summaries (``git log -S "seed_summary"`` returns 0 hits, so the
original code is lost). Phase B1 P0 Stage A1.6.

Three known silent bugs in the original ad-hoc script — re-emitting
through this canonical aggregator corrects all three:

1. ``n_feedback_iter_above_zero`` was always 0 or None. Truth: 144/189
   across D5 v2 (50 / 43 / 51). This bug led ``phase_b1_d5_eval.md``
   §4 to incorrectly claim "D4 dormant; prevention > correction".
2. ``feedback_iter_distribution`` always reported ``{0: n_task, 1: 0,
   2: 0}`` regardless of truth.
3. ``metrics_normal_only.unsupported_mean`` was omitted entirely.

Schema preserved from the legacy summary so reports continue to read
the same keys; new fields are additive (superset). ``wall_seconds``
keeps ``{min, max, mean, median}`` and gains ``{p95, total, n}``.

Modes:
  ``--mode audit``  diff each on-disk ``seed_summary.json`` against
                    the re-derived truth and write a markdown report.
                    Does not touch the JSON files. (A1.5 behavior.)
  ``--mode write``  back up each ``seed_summary.json`` and
                    ``d5_aggregate.json`` to ``*.bak`` then re-emit
                    the canonical version. Idempotent — re-running
                    does NOT re-backup (a ``*.bak`` already on disk
                    is preserved as audit trail).

Example:
    # Audit only (writes report + JSON, leaves data alone):
    python scripts/eval_sub6/aggregate_seed_summary.py \
        --input data/eval/sub6/b1_d5_v2_full_feedback_lit/ \
        --mode audit \
        --report reports/agent/phase_b1_aggregator_audit.md

    # Re-emit corrected JSON in-place (with .bak audit trail):
    python scripts/eval_sub6/aggregate_seed_summary.py \
        --input data/eval/sub6/b1_d5_v2_full_feedback_lit/ \
        --mode write
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import statistics
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Per-task loaders
# ---------------------------------------------------------------------------


def _load_result(task_dir: Path) -> dict | None:
    f = task_dir / "result.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception as e:
        return {"_load_error": str(e)}


def _load_verdict(task_dir: Path) -> dict | None:
    f = task_dir / "verdict_final.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-seed aggregation
# ---------------------------------------------------------------------------


def compute_seed_summary(seed_dir: Path, prior_summary: dict | None = None) -> dict:
    """Re-derive every aggregator field from per-task files.

    ``prior_summary`` is the on-disk seed_summary.json if it exists;
    used only to pass through fields the runner emitted but per-task
    files do not record (currently: ``deprecation_warnings``).
    """
    task_dirs = sorted(d for d in seed_dir.iterdir() if d.is_dir())
    n_task = len(task_dirs)

    outcome_counts: dict[str, int] = {}
    fb_iter_dist: dict[int, int] = {0: 0, 1: 0, 2: 0}
    n_fb_above_zero = 0
    termination_dist: dict[str, int] = {}
    rollback_count = 0
    inner_retry_count = 0
    tool_call_total = 0
    wall_seconds: list[float] = []

    normal_ratios = {
        "supported": [],
        "contradicted": [],
        "unsupported": [],
        "unverifiable_v0": [],
        "dropped_by_grammar": [],
    }

    for td in task_dirs:
        r = _load_result(td)
        v = _load_verdict(td)
        if r is None:
            continue
        outcome = (v or {}).get("task_outcome") or r.get("task_outcome") or "unknown"
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

        n_fb = int(r.get("n_feedback_iterations", 0) or 0)
        fb_iter_dist[n_fb] = fb_iter_dist.get(n_fb, 0) + 1
        if n_fb > 0:
            n_fb_above_zero += 1

        term = r.get("termination_reason") or "none"
        termination_dist[term] = termination_dist.get(term, 0) + 1

        if r.get("rollback_reason"):
            rollback_count += 1

        for it in r.get("iterations", []) or []:
            if it.get("force_finalised"):
                inner_retry_count += 1
            tool_call_total += int(it.get("n_tool_calls", 0) or 0)

        if r.get("elapsed_seconds") is not None:
            wall_seconds.append(float(r["elapsed_seconds"]))

        if outcome == "normal" and v is not None:
            vt = v.get("verdicts_total", {}) or {}
            n_emitted = int(v.get("n_emitted", 0) or 0)
            n_post = int(v.get("n_post_grammar", 0) or 0)
            n_drop = int(v.get("n_dropped", 0) or 0)
            denom = n_post or sum(vt.values()) or 1
            for k in ("supported", "contradicted", "unsupported", "unverifiable_v0"):
                normal_ratios[k].append(int(vt.get(k, 0) or 0) / denom)
            if n_emitted > 0:
                normal_ratios["dropped_by_grammar"].append(n_drop / n_emitted)
            else:
                normal_ratios["dropped_by_grammar"].append(0.0)

    metrics_normal_only = {
        f"{k}_mean": (sum(vals) / len(vals)) if vals else 0.0
        for k, vals in normal_ratios.items()
    }

    if wall_seconds:
        ws_sorted = sorted(wall_seconds)
        p95_idx = max(0, int(round(0.95 * (len(ws_sorted) - 1))))
        wall_stats = {
            "n": len(wall_seconds),
            "min": min(wall_seconds),
            "max": max(wall_seconds),
            "mean": statistics.mean(wall_seconds),
            "median": statistics.median(wall_seconds),
            "p95": ws_sorted[p95_idx],
            "total": sum(wall_seconds),
        }
    else:
        wall_stats = {"n": 0, "min": 0.0, "max": 0.0, "mean": 0.0,
                      "median": 0.0, "p95": 0.0, "total": 0.0}

    if prior_summary is not None and "deprecation_warnings" in prior_summary:
        depr = prior_summary["deprecation_warnings"]
    else:
        depr = 0

    return {
        "seed": int(seed_dir.name.replace("seed_", "")),
        "n_task": n_task,
        "outcome_counts": outcome_counts,
        "metrics_normal_only": metrics_normal_only,
        "wall_seconds": wall_stats,
        "feedback_iter_distribution": {str(k): v for k, v in sorted(fb_iter_dist.items())},
        "n_feedback_iter_above_zero": n_fb_above_zero,
        "deprecation_warnings": depr,
        # Net-new fields (additive superset):
        "termination_reason_distribution": termination_dist,
        "quality_rollback_count": rollback_count,
        "inner_retry_count": inner_retry_count,
        "tool_call_total": tool_call_total,
    }


# ---------------------------------------------------------------------------
# Cross-seed N=k aggregation
# ---------------------------------------------------------------------------


def _ci95(values: list[float]) -> float:
    """95% CI half-width using t≈1.96 (sample SD). Returns 0 for n<2."""
    if len(values) < 2:
        return 0.0
    sd = statistics.stdev(values)
    return 1.96 * sd / math.sqrt(len(values))


def compute_cross_seed(per_seed: dict[str, dict]) -> dict:
    """N=k cross-seed aggregate matching the legacy d5_aggregate.json shape."""
    seeds = sorted(per_seed.values(), key=lambda s: s["seed"])
    n = len(seeds)
    if n == 0:
        return {"n_seeds": 0}

    metric_keys = sorted(seeds[0]["metrics_normal_only"].keys())
    metrics_n3 = {}
    for mk in metric_keys:
        vals = [s["metrics_normal_only"].get(mk, 0.0) for s in seeds]
        metrics_n3[mk] = {
            "mean": statistics.mean(vals),
            "ci95": _ci95(vals),
            "n": n,
            "values": vals,
        }

    outcome_names = sorted({k for s in seeds for k in s["outcome_counts"]})
    outcome_counts_n3 = {}
    for name in outcome_names:
        vals = [s["outcome_counts"].get(name, 0) for s in seeds]
        outcome_counts_n3[name] = {
            "mean": statistics.mean(vals),
            "ci95": _ci95([float(v) for v in vals]),
            "values": vals,
        }

    wall_n3 = {
        "mean_per_seed": [s["wall_seconds"]["mean"] for s in seeds],
        "max_per_seed": [s["wall_seconds"]["max"] for s in seeds],
        "max_overall": max(s["wall_seconds"]["max"] for s in seeds),
    }

    fb_keys = sorted({k for s in seeds for k in s["feedback_iter_distribution"]})
    feedback_iter_n3 = {
        k: sum(s["feedback_iter_distribution"].get(k, 0) for s in seeds)
        for k in fb_keys
    }
    feedback_iter_n3["n_above_zero_total"] = sum(
        s["n_feedback_iter_above_zero"] for s in seeds
    )

    termination_n3: dict[str, int] = {}
    for s in seeds:
        for k, v in s["termination_reason_distribution"].items():
            termination_n3[k] = termination_n3.get(k, 0) + v

    return {
        "n_seeds": n,
        "metrics_n3": metrics_n3,
        "outcome_counts_n3": outcome_counts_n3,
        "wall_seconds_n3": wall_n3,
        "feedback_iter_n3": feedback_iter_n3,
        "termination_reason_n3": termination_n3,
        "quality_rollback_n3": sum(s["quality_rollback_count"] for s in seeds),
        "inner_retry_n3": sum(s["inner_retry_count"] for s in seeds),
        "tool_call_n3": sum(s["tool_call_total"] for s in seeds),
    }


# ---------------------------------------------------------------------------
# Audit mode (diff vs on-disk summary)
# ---------------------------------------------------------------------------


def _diff_scalar(name: str, on_disk, truth) -> dict:
    is_num = isinstance(on_disk, (int, float)) and isinstance(truth, (int, float))
    if is_num:
        delta = truth - on_disk
        denom = abs(truth) if truth else 1.0
        pct = abs(delta) / denom * 100 if denom else 0.0
        return {
            "field": name,
            "on_disk": on_disk,
            "truth": truth,
            "delta": delta,
            "pct_off": pct,
            "mismatch": abs(delta) > 1e-9,
        }
    return {
        "field": name,
        "on_disk": on_disk,
        "truth": truth,
        "mismatch": on_disk != truth,
    }


def _diff_dict(name: str, on_disk: dict, truth: dict) -> list[dict]:
    out = []
    for k in sorted(set(on_disk.keys()) | set(truth.keys())):
        out.append(_diff_scalar(
            f"{name}.{k}",
            on_disk.get(k, "MISSING"),
            truth.get(k, "MISSING"),
        ))
    return out


def audit_seed(seed_dir: Path) -> dict:
    summary_f = seed_dir / "seed_summary.json"
    on_disk = json.loads(summary_f.read_text()) if summary_f.exists() else {}
    truth = compute_seed_summary(seed_dir, prior_summary=on_disk)

    diffs: list[dict] = []
    diffs.append(_diff_scalar("seed", on_disk.get("seed"), truth["seed"]))
    diffs.append(_diff_scalar("n_task", on_disk.get("n_task"), truth["n_task"]))
    diffs.append(_diff_scalar(
        "n_feedback_iter_above_zero",
        on_disk.get("n_feedback_iter_above_zero"),
        truth["n_feedback_iter_above_zero"],
    ))
    diffs.append(_diff_scalar(
        "deprecation_warnings",
        on_disk.get("deprecation_warnings"),
        truth["deprecation_warnings"],
    ))
    diffs.extend(_diff_dict("outcome_counts",
                            on_disk.get("outcome_counts", {}) or {},
                            truth["outcome_counts"]))
    diffs.extend(_diff_dict("metrics_normal_only",
                            on_disk.get("metrics_normal_only", {}) or {},
                            truth["metrics_normal_only"]))
    diffs.extend(_diff_dict("feedback_iter_distribution",
                            on_disk.get("feedback_iter_distribution", {}) or {},
                            truth["feedback_iter_distribution"]))
    diffs.extend(_diff_dict("wall_seconds",
                            on_disk.get("wall_seconds", {}) or {},
                            truth["wall_seconds"]))

    return {"on_disk": on_disk, "truth": truth, "diffs": diffs}


def _fmt_val(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def render_audit_markdown(per_seed: dict[str, dict], input_root: Path) -> str:
    lines: list[str] = []
    lines.append("# Phase B1 — Aggregator audit (D5 v2 seed summaries)\n")
    lines.append("**Generated:** Phase B1 P0 Stage A1.5\n")
    lines.append(f"**Source:** `{input_root}`\n")
    lines.append("**Purpose:** verify every field in each `seed_summary.json` "
                 "by re-deriving from per-task `result.json` + `verdict_final.json`. "
                 "The aggregator script that wrote these summaries is not in "
                 "the committed repo (`git log -S \"seed_summary\"` returns 0 "
                 "hits), so any mismatch below is a silent bug in a lost "
                 "ad-hoc script — downstream reports (`phase_b1_d5_eval.md` "
                 "§1 / §4) inherit those bugs verbatim.\n")
    lines.append("---\n")

    all_diffs: list[tuple[str, dict]] = []
    for seed_name, audit in sorted(per_seed.items()):
        lines.append(f"## {seed_name}\n")
        diffs = audit["diffs"]
        mismatches = [d for d in diffs if d.get("mismatch")]
        lines.append(f"- total fields checked: **{len(diffs)}**")
        lines.append(f"- mismatched: **{len(mismatches)}**\n")
        if mismatches:
            lines.append("### Mismatches\n")
            lines.append("| field | on_disk | truth | delta | %off |")
            lines.append("|---|---|---|---|---|")
            for d in mismatches:
                delta = _fmt_val(d.get("delta", "—"))
                pct = f"{d.get('pct_off', 0):.2f}" if "pct_off" in d else "—"
                lines.append(f"| `{d['field']}` | `{_fmt_val(d['on_disk'])}` "
                             f"| `{_fmt_val(d['truth'])}` | `{delta}` | `{pct}` |")
            lines.append("")
            all_diffs.extend((seed_name, d) for d in mismatches)
        else:
            lines.append("_no mismatches._\n")

        truth = audit["truth"]
        lines.append("### Derived fields not in on-disk summary\n")
        lines.append("| field | truth |")
        lines.append("|---|---|")
        for k in ("termination_reason_distribution", "quality_rollback_count",
                  "inner_retry_count", "tool_call_total"):
            lines.append(f"| `{k}` | `{_fmt_val(truth[k])}` |")
        lines.append("")

    lines.append("---\n")
    lines.append("## Summary across seeds\n")
    if all_diffs:
        by_field: dict[str, list[tuple[str, dict]]] = {}
        for seed_name, d in all_diffs:
            by_field.setdefault(d["field"], []).append((seed_name, d))
        lines.append(f"**Total mismatched (field, seed) pairs:** {len(all_diffs)}\n")
        lines.append("| field | seeds affected |")
        lines.append("|---|---|")
        for field, occurrences in sorted(by_field.items()):
            seeds = ", ".join(s for s, _ in occurrences)
            lines.append(f"| `{field}` | {seeds} |")
        lines.append("")

        lines.append("## Headline narrative impact\n")
        feedback_mismatched = [
            (s, d) for s, d in all_diffs
            if d["field"] in {
                "n_feedback_iter_above_zero",
                "feedback_iter_distribution.0",
                "feedback_iter_distribution.1",
                "feedback_iter_distribution.2",
            }
        ]
        if feedback_mismatched:
            lines.append("**Feedback-trigger metric is wrong.** The on-disk "
                         "summary reports `n_feedback_iter_above_zero = 0` "
                         "across seeds. The truth derived from "
                         "`result.json:n_feedback_iterations` shows actual "
                         "non-zero triggers per seed:\n")
            for s, d in feedback_mismatched:
                if d["field"] == "n_feedback_iter_above_zero":
                    lines.append(f"- {s}: reported `{d['on_disk']}` / "
                                 f"truth `{d['truth']}`")
            lines.append("\nThis directly invalidates `phase_b1_d5_eval.md` "
                         "§4 claim that '0/189 feedback iter triggered'.\n")
    else:
        lines.append("All seeds match — no aggregator bug detected.\n")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Write mode (re-emit with .bak audit trail)
# ---------------------------------------------------------------------------


def _backup_once(path: Path) -> None:
    """Make ``path.bak`` if not already present. Idempotent."""
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists() and path.exists():
        shutil.copy2(path, bak)


def write_mode(input_root: Path) -> dict[str, dict]:
    seed_dirs = sorted(d for d in input_root.iterdir()
                       if d.is_dir() and d.name.startswith("seed_"))
    per_seed: dict[str, dict] = {}
    for sd in seed_dirs:
        summary_f = sd / "seed_summary.json"
        prior = json.loads(summary_f.read_text()) if summary_f.exists() else {}
        truth = compute_seed_summary(sd, prior_summary=prior)
        _backup_once(summary_f)
        summary_f.write_text(json.dumps(truth, indent=2))
        per_seed[sd.name] = truth
        print(f"  rewrote {summary_f} (backup at {summary_f}.bak)")

    cross = compute_cross_seed(per_seed)
    agg_f = input_root / "d5_aggregate.json"
    _backup_once(agg_f)
    agg_f.write_text(json.dumps(cross, indent=2))
    print(f"  rewrote {agg_f} (backup at {agg_f}.bak)")

    return per_seed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path,
                    help="Root containing seed_0/ seed_1/ seed_2/")
    ap.add_argument("--mode", choices=("audit", "write"), default="audit")
    ap.add_argument("--report", type=Path, default=None,
                    help="(audit mode) markdown output path")
    ap.add_argument("--json", type=Path, default=None,
                    help="(audit mode) optional raw audit JSON dump")
    args = ap.parse_args(argv)

    if args.mode == "audit":
        if args.report is None:
            sys.stderr.write("--report required in audit mode\n")
            return 2
        seed_dirs = sorted(d for d in args.input.iterdir()
                           if d.is_dir() and d.name.startswith("seed_"))
        if not seed_dirs:
            sys.stderr.write(f"No seed_* subdirs in {args.input}\n")
            return 2
        per_seed = {sd.name: audit_seed(sd) for sd in seed_dirs}
        md = render_audit_markdown(per_seed, args.input)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(md)
        print(f"Wrote audit report to {args.report}")
        if args.json:
            args.json.write_text(json.dumps(per_seed, indent=2, default=str))
            print(f"Wrote raw JSON to {args.json}")
        total_mismatches = sum(
            sum(1 for d in a["diffs"] if d.get("mismatch"))
            for a in per_seed.values()
        )
        print(f"Total mismatched fields across seeds: {total_mismatches}")
        return 0 if total_mismatches == 0 else 1

    write_mode(args.input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
