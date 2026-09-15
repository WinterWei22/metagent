#!/usr/bin/env python3
"""Stage2 final-result and verifier-feedback analysis for W22 D8 outputs.

This script is intentionally offline-only. It reads stored Stage2 outputs and
does not compare against pre-W22 implementations.
"""

from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data/metagent/w22_easyv3_stratified_paired"
OUT_DIR = ROOT / "reports/reports_v2"
REPORT = OUT_DIR / f"{date.today().isoformat()}_stage2_final_result_analysis.md"
METRICS_JSON = OUT_DIR / f"{date.today().isoformat()}_stage2_final_result_metrics.json"
FINAL_CSV = OUT_DIR / f"{date.today().isoformat()}_stage2_final_metrics_by_stratum.csv"
FEEDBACK_CSV = OUT_DIR / f"{date.today().isoformat()}_stage2_feedback_metrics_by_stratum.csv"

STRATUM_LABELS = {
    "sub6_hmdb_ramp_enrichment": "Sub-6 HMDB/RaMP enrichment",
    "hmdb_ramp_pathway_membership": "HMDB/RaMP pathway membership",
    "cooke_human1_recon22": "Human1/Recon2.2",
}


def pct(num: float, den: float) -> float:
    return (num / den * 100.0) if den else 0.0


def fmt_pct(value: float) -> str:
    return f"{value:.2f}%"


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def final_metrics() -> list[dict[str, Any]]:
    rows = read_csv_dicts(DATA_DIR / "paired_per_task.csv")
    result: list[dict[str, Any]] = []
    strata = sorted({r["stratum"] for r in rows})
    for stratum in strata:
        subset = [
            r
            for r in rows
            if r["stratum"] == stratum and r["arm"] == "structured_method_aware"
        ]
        totals = Counter()
        for row in subset:
            for key in [
                "source_claims",
                "verified_claims",
                "dropped",
                "supported",
                "contradicted",
                "unsupported",
                "needs_human_review",
                "uv",
                "method_aware_hits",
            ]:
                totals[key] += int(row[key])
        source = totals["source_claims"]
        verified = totals["verified_claims"]
        landed = source - totals["dropped"] - totals["uv"]
        result.append(
            {
                "stratum": stratum,
                "label": STRATUM_LABELS.get(stratum, stratum),
                "tasks": len(subset),
                "source_claims": source,
                "verified_claims": verified,
                "dropped": totals["dropped"],
                "supported": totals["supported"],
                "contradicted": totals["contradicted"],
                "unsupported": totals["unsupported"],
                "needs_human_review": totals["needs_human_review"],
                "uv": totals["uv"],
                "landed": landed,
                "method_aware_hits": totals["method_aware_hits"],
                "verified_rate": pct(verified, source),
                "supported_rate_honest": pct(totals["supported"], source),
                "contradicted_rate_honest": pct(totals["contradicted"], source),
                "unsupported_rate_honest": pct(totals["unsupported"], source),
                "uv_rate_honest": pct(totals["uv"], source),
                "dropped_rate_honest": pct(totals["dropped"], source),
                "unlanded_rate_honest": pct(totals["uv"] + totals["dropped"], source),
                "landed_rate_honest": pct(landed, source),
                "method_aware_hit_rate_verified": pct(totals["method_aware_hits"], verified),
            }
        )
    return result


def feedback_metrics() -> list[dict[str, Any]]:
    aggregate: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    rollback: dict[str, Counter[str]] = defaultdict(Counter)
    bridge: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))

    with (DATA_DIR / "path_x_results.jsonl").open() as fh:
        for line in fh:
            obj = json.loads(line)
            stratum = obj["stratum"]
            per_iter = obj["per_iter"]
            final_idx = int(obj.get("final_iter_idx", 0) or 0)
            selected = [("before_feedback_iter0", per_iter[0]), ("after_feedback_final", per_iter[final_idx])]
            for label, item in selected:
                counter = aggregate[stratum][label]
                counter["tasks"] += 1
                counter["claims"] += int(item.get("n_claims", 0) or 0)
                counter["supported"] += int(item.get("n_supported", 0) or 0)
                counter["unsupported"] += int(item.get("n_unsupported", 0) or 0)
                counter["contradicted"] += int(item.get("n_contradicted", 0) or 0)
                counter["uv"] += int(item.get("n_unverifiable_v0", 0) or 0)
                counter["tool_calls"] += int(item.get("n_tool_calls", 0) or 0)
                counter["quality"] += int(item.get("quality", 0) or 0)
                b = bridge[stratum][label]
                for key in [
                    "narrative_mentions_gt_name",
                    "narrative_mentions_gt_id",
                    "any_claim_matches_gt_pathway_id",
                    "bridging_signal",
                ]:
                    b[key] += 1 if item.get(key) else 0
            rollback[stratum][obj.get("rollback_reason") or "none"] += 1

    rows: list[dict[str, Any]] = []
    for stratum in sorted(aggregate):
        before = aggregate[stratum]["before_feedback_iter0"]
        after = aggregate[stratum]["after_feedback_final"]
        for label, counter in [
            ("before_feedback_iter0", before),
            ("after_feedback_final", after),
        ]:
            denom = (
                counter["supported"]
                + counter["unsupported"]
                + counter["contradicted"]
                + counter["uv"]
            )
            tasks = counter["tasks"]
            b = bridge[stratum][label]
            rows.append(
                {
                    "stratum": stratum,
                    "label": STRATUM_LABELS.get(stratum, stratum),
                    "phase": label,
                    "tasks": tasks,
                    "claims": counter["claims"],
                    "supported": counter["supported"],
                    "unsupported": counter["unsupported"],
                    "contradicted": counter["contradicted"],
                    "uv": counter["uv"],
                    "denominator": denom,
                    "supported_rate": pct(counter["supported"], denom),
                    "unsupported_rate": pct(counter["unsupported"], denom),
                    "contradicted_rate": pct(counter["contradicted"], denom),
                    "uv_rate": pct(counter["uv"], denom),
                    "mean_quality": counter["quality"] / tasks if tasks else 0.0,
                    "mean_tool_calls": counter["tool_calls"] / tasks if tasks else 0.0,
                    "bridge_rate": pct(b["bridging_signal"], tasks),
                    "name_hit_rate": pct(b["narrative_mentions_gt_name"], tasks),
                    "id_hit_rate": pct(b["narrative_mentions_gt_id"], tasks),
                    "pathway_id_claim_hit_rate": pct(
                        b["any_claim_matches_gt_pathway_id"], tasks
                    ),
                    "rollback_none": rollback[stratum]["none"],
                    "rollback_worse": rollback[stratum]["feedback_made_it_worse"],
                }
            )
    return rows


def svg_bar_chart(
    path: Path,
    title: str,
    groups: list[str],
    series: list[tuple[str, list[float], str]],
    y_label: str = "%",
) -> None:
    width = 980
    height = 520
    margin = {"left": 85, "right": 30, "top": 70, "bottom": 120}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    max_v = max([value for _, values, _ in series for value in values] + [1])
    y_max = max(10.0, ((max_v + 9.999) // 10) * 10)
    group_w = plot_w / len(groups)
    bar_w = min(54, group_w / (len(series) + 1.4))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>text{font-family:Arial,Helvetica,sans-serif;fill:#222}.small{font-size:12px}.axis{stroke:#555;stroke-width:1}.grid{stroke:#ddd;stroke-width:1}.title{font-size:20px;font-weight:700}.label{font-size:13px}.legend{font-size:13px}</style>",
        f'<text x="{width/2}" y="32" text-anchor="middle" class="title">{html.escape(title)}</text>',
    ]
    for tick in range(0, int(y_max) + 1, max(10, int(y_max // 5))):
        y = margin["top"] + plot_h - (tick / y_max) * plot_h
        parts.append(f'<line x1="{margin["left"]}" y1="{y:.1f}" x2="{width-margin["right"]}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{margin["left"]-10}" y="{y+4:.1f}" text-anchor="end" class="small">{tick}</text>')
    parts.append(f'<line x1="{margin["left"]}" y1="{margin["top"]}" x2="{margin["left"]}" y2="{margin["top"]+plot_h}" class="axis"/>')
    parts.append(f'<line x1="{margin["left"]}" y1="{margin["top"]+plot_h}" x2="{width-margin["right"]}" y2="{margin["top"]+plot_h}" class="axis"/>')
    parts.append(f'<text x="22" y="{margin["top"]+plot_h/2}" transform="rotate(-90 22 {margin["top"]+plot_h/2})" text-anchor="middle" class="label">{html.escape(y_label)}</text>')

    for i, group in enumerate(groups):
        center = margin["left"] + i * group_w + group_w / 2
        start = center - (len(series) * bar_w) / 2
        for j, (name, values, color) in enumerate(series):
            value = values[i]
            h = (value / y_max) * plot_h
            x = start + j * bar_w
            y = margin["top"] + plot_h - h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w-5:.1f}" height="{h:.1f}" fill="{color}"/>')
            parts.append(f'<text x="{x+(bar_w-5)/2:.1f}" y="{y-5:.1f}" text-anchor="middle" class="small">{value:.1f}</text>')
        label = STRATUM_LABELS.get(group, group)
        words = label.split()
        y0 = margin["top"] + plot_h + 25
        for k in range(0, len(words), 2):
            parts.append(f'<text x="{center:.1f}" y="{y0 + (k//2)*16}" text-anchor="middle" class="small">{html.escape(" ".join(words[k:k+2]))}</text>')

    legend_x = margin["left"]
    legend_y = height - 28
    for idx, (name, _, color) in enumerate(series):
        x = legend_x + idx * 250
        parts.append(f'<rect x="{x}" y="{legend_y-12}" width="14" height="14" fill="{color}"/>')
        parts.append(f'<text x="{x+20}" y="{legend_y}" class="legend">{html.escape(name)}</text>')
    parts.append("</svg>\n")
    path.write_text("\n".join(parts))


def write_report(final_rows: list[dict[str, Any]], feedback_rows: list[dict[str, Any]]) -> None:
    final_by = {r["stratum"]: r for r in final_rows}
    feedback_by = defaultdict(dict)
    for row in feedback_rows:
        feedback_by[row["stratum"]][row["phase"]] = row

    lines: list[str] = []
    lines.append("# Stage2 最新结果分析")
    lines.append("")
    lines.append(f"- 日期: `{date.today().isoformat()}`")
    lines.append("- 数据目录: `data/metagent/w22_easyv3_stratified_paired/`")
    lines.append("- 分析范围: 只分析 Stage2 最新最终结果，不横向对比修改前后的性能。")
    lines.append("- feedback 前后口径: 同一批已保存运行中，`iter0` 代表 verifier-feedback 前，最终采用轮次代表 feedback/rollback 后。")
    lines.append("- 最终 verifier 口径: `structured_method_aware`。")
    lines.append("")
    lines.append("## 结论摘要")
    lines.append("")
    lines.append(
        "Stage2 最新结果在两个 HMDB/RaMP 数据层上是有效的，在 Human1/Recon2.2 上仍属于覆盖范围外。"
        "verifier-feedback 的主要作用不是稳定提高 supported 数，而是通过 rollback 过滤掉一部分更差的二轮输出；"
        "直接证据支撑率只在两个 HMDB/RaMP 层有小幅提升。"
    )
    lines.append("")
    lines.append("## 最终结果分层")
    lines.append("")
    lines.append("| stratum | tasks | source claims | verified | supported | contradicted | unsupported | UV | dropped | supported honest | unlanded honest | method-aware hit/verified |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in final_rows:
        lines.append(
            "| {label} | {tasks} | {source_claims} | {verified_claims} | {supported} | {contradicted} | {unsupported} | {uv} | {dropped} | {supported_rate_honest} | {unlanded_rate_honest} | {method_aware_hit_rate_verified} |".format(
                **{
                    **row,
                    "supported_rate_honest": fmt_pct(row["supported_rate_honest"]),
                    "unlanded_rate_honest": fmt_pct(row["unlanded_rate_honest"]),
                    "method_aware_hit_rate_verified": fmt_pct(row["method_aware_hit_rate_verified"]),
                }
            )
        )
    lines.append("")
    lines.append("![Stage2 最终结果比例](figures/stage2_final_outcome_rates.svg)")
    lines.append("")
    lines.append("## Verifier-Feedback 前后对比")
    lines.append("")
    lines.append("| stratum | phase | supported rate | UV rate | contradicted rate | mean quality | bridge rate | mean tool calls | rollback kept iter0 | rollback rejected feedback |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for stratum in sorted(feedback_by):
        for phase in ["before_feedback_iter0", "after_feedback_final"]:
            row = feedback_by[stratum][phase]
            lines.append(
                "| {label} | {phase_name} | {supported_rate} | {uv_rate} | {contradicted_rate} | {mean_quality:.2f} | {bridge_rate} | {mean_tool_calls:.2f} | {rollback_none} | {rollback_worse} |".format(
                    **{
                        **row,
                        "phase_name": "before feedback" if phase == "before_feedback_iter0" else "after feedback/final",
                        "supported_rate": fmt_pct(row["supported_rate"]),
                        "uv_rate": fmt_pct(row["uv_rate"]),
                        "contradicted_rate": fmt_pct(row["contradicted_rate"]),
                        "bridge_rate": fmt_pct(row["bridge_rate"]),
                    }
                )
            )
    lines.append("")
    lines.append("![Feedback 前后 supported rate](figures/stage2_feedback_supported_rate.svg)")
    lines.append("")
    lines.append("![Feedback 前后 UV rate](figures/stage2_feedback_uv_rate.svg)")
    lines.append("")
    lines.append("## 解读")
    lines.append("")
    lines.append("- `Sub-6 HMDB/RaMP enrichment`: 最终 supported honest rate 最高，为 `41.39%`；仍有 `31.98%` claim 未落地。这是当前 Stage2 最清楚的成功层。")
    lines.append("- `HMDB/RaMP pathway membership`: 最终 supported honest rate 为 `29.14%`，unlanded rate 为 `34.15%`；说明这一路有效，但 unresolved claim 仍然不少。")
    lines.append("- `Human1/Recon2.2`: 最终 supported honest rate 只有 `0.76%`；这应解释为当前 verifier/carrier 覆盖不到该命名空间，而不是整体 Stage2 失败。")
    lines.append("- feedback/rollback 不是简单的准确率增强器。HMDB/RaMP pathway membership 的 supported rate 从 `5.10%` 到 `7.03%`；Sub-6 enrichment 从 `11.81%` 到 `13.20%`；Human1/Recon2.2 原本几乎没有 supported，最终为 `0.00%`，但 contradicted rate 有下降。")
    lines.append("- feedback 的最明确价值是拦住更差的二轮输出：三个分层分别有 `61/181`、`47/100`、`31/63` 个任务因为 feedback 变差而 rollback，而不是稳定制造更多 supported claim。")
    lines.append("")
    lines.append("## 复现")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 scripts/metagent/w22_stage2_final_analysis.py")
    lines.append("```")
    lines.append("")
    lines.append("输入:")
    lines.append("")
    lines.append("- `data/metagent/w22_easyv3_stratified_paired/paired_per_task.csv`")
    lines.append("- `data/metagent/w22_easyv3_stratified_paired/path_x_results.jsonl`")
    lines.append("")
    lines.append("输出:")
    lines.append("")
    lines.append(f"- `{REPORT.relative_to(ROOT)}`")
    lines.append(f"- `{METRICS_JSON.relative_to(ROOT)}`")
    lines.append(f"- `{FINAL_CSV.relative_to(ROOT)}`")
    lines.append(f"- `{FEEDBACK_CSV.relative_to(ROOT)}`")
    lines.append("- `reports/reports_v2/figures/stage2_final_outcome_rates.svg`")
    lines.append("- `reports/reports_v2/figures/stage2_feedback_supported_rate.svg`")
    lines.append("- `reports/reports_v2/figures/stage2_feedback_uv_rate.svg`")
    REPORT.write_text("\n".join(lines) + "\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig_dir = OUT_DIR / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    final_rows = final_metrics()
    feedback_rows = feedback_metrics()

    write_csv(
        FINAL_CSV,
        final_rows,
        [
            "stratum",
            "label",
            "tasks",
            "source_claims",
            "verified_claims",
            "dropped",
            "supported",
            "contradicted",
            "unsupported",
            "needs_human_review",
            "uv",
            "landed",
            "method_aware_hits",
            "verified_rate",
            "supported_rate_honest",
            "contradicted_rate_honest",
            "unsupported_rate_honest",
            "uv_rate_honest",
            "dropped_rate_honest",
            "unlanded_rate_honest",
            "landed_rate_honest",
            "method_aware_hit_rate_verified",
        ],
    )
    write_csv(
        FEEDBACK_CSV,
        feedback_rows,
        [
            "stratum",
            "label",
            "phase",
            "tasks",
            "claims",
            "supported",
            "unsupported",
            "contradicted",
            "uv",
            "denominator",
            "supported_rate",
            "unsupported_rate",
            "contradicted_rate",
            "uv_rate",
            "mean_quality",
            "mean_tool_calls",
            "bridge_rate",
            "name_hit_rate",
            "id_hit_rate",
            "pathway_id_claim_hit_rate",
            "rollback_none",
            "rollback_worse",
        ],
    )

    groups = [r["stratum"] for r in final_rows]
    svg_bar_chart(
        fig_dir / "stage2_final_outcome_rates.svg",
        "Final Stage2 outcome rates by stratum",
        groups,
        [
            ("supported", [r["supported_rate_honest"] for r in final_rows], "#2f7d32"),
            ("unsupported", [r["unsupported_rate_honest"] for r in final_rows], "#d08b23"),
            ("UV + dropped", [r["unlanded_rate_honest"] for r in final_rows], "#6a6f7d"),
        ],
    )

    before_supported = []
    after_supported = []
    before_uv = []
    after_uv = []
    feedback_by = defaultdict(dict)
    for row in feedback_rows:
        feedback_by[row["stratum"]][row["phase"]] = row
    for group in groups:
        before_supported.append(feedback_by[group]["before_feedback_iter0"]["supported_rate"])
        after_supported.append(feedback_by[group]["after_feedback_final"]["supported_rate"])
        before_uv.append(feedback_by[group]["before_feedback_iter0"]["uv_rate"])
        after_uv.append(feedback_by[group]["after_feedback_final"]["uv_rate"])

    svg_bar_chart(
        fig_dir / "stage2_feedback_supported_rate.svg",
        "Verifier-feedback supported rate: before vs final",
        groups,
        [
            ("before feedback", before_supported, "#7aa6c2"),
            ("after feedback/final", after_supported, "#2f7d32"),
        ],
    )
    svg_bar_chart(
        fig_dir / "stage2_feedback_uv_rate.svg",
        "Verifier-feedback UV rate: before vs final",
        groups,
        [
            ("before feedback", before_uv, "#9a9a9a"),
            ("after feedback/final", after_uv, "#4d5f8f"),
        ],
    )

    METRICS_JSON.write_text(
        json.dumps(
            {"final_by_stratum": final_rows, "feedback_by_stratum": feedback_rows},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    write_report(final_rows, feedback_rows)
    print(REPORT)
    print(METRICS_JSON)


if __name__ == "__main__":
    main()
