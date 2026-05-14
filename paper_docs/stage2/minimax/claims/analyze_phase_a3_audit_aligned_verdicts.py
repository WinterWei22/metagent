#!/usr/bin/env python3
"""Reproduce Phase A3 audit D3 full verdict table and figures."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = REPO_ROOT / "paper_docs/stage2/minimax/claims/audit_aligned"

VARIANTS = [
    ("single", "data/eval/sub6/v4_a3_d3_no_lit/single"),
    ("react", "data/eval/sub6/v4_a3_d3_no_lit/react"),
    ("fb_nolit", "data/eval/sub6/v4_a3_d3_no_lit/feedback"),
    ("+literature", "data/eval/sub6/v4_a3_d3_with_lit/feedback"),
]
MAIN_VARIANTS = [
    ("MetAgent-single", "data/eval/sub6/v4_a3_d3_no_lit/single"),
    ("MetAgent-ReAct", "data/eval/sub6/v4_a3_d3_no_lit/react"),
    ("MetAgent-feedback", "data/eval/sub6/v4_a3_d3_with_lit/feedback"),
]
VERDICTS = ["supported", "unsupported", "contradicted", "unverifiable_v0"]
COLORS = {
    "single": "#94A3B8",
    "react": "#2563EB",
    "fb_nolit": "#2E7D32",
    "+literature": "#0F766E",
    "MetAgent-single": "#94A3B8",
    "MetAgent-ReAct": "#2563EB",
    "MetAgent-feedback": "#0F766E",
}


def collect_counts(variants: list[tuple[str, str]] = VARIANTS) -> pd.DataFrame:
    rows: list[dict] = []
    for variant, rel_root in variants:
        root = REPO_ROOT / rel_root
        verdict_paths = sorted(root.glob("*/verdict.json"))
        counts = Counter()
        for verdict_path in verdict_paths:
            payload = json.loads(verdict_path.read_text())
            counts.update(payload.get("verdicts_total") or {})
        row = {
            "variant": variant,
            "path": rel_root,
            "n_tasks": len(verdict_paths),
        }
        for verdict in VERDICTS:
            row[verdict] = int(counts.get(verdict, 0))
        row["total_claims"] = sum(row[v] for v in VERDICTS)
        for verdict in VERDICTS:
            row[f"{verdict}_pct"] = (
                row[verdict] / row["total_claims"] * 100.0
                if row["total_claims"]
                else 0.0
            )
        rows.append(row)
    return pd.DataFrame(rows)


def plot_counts(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    x = range(len(VERDICTS))
    width = 0.18
    offsets = [-1.5 * width, -0.5 * width, 0.5 * width, 1.5 * width]
    for offset, (variant, _) in zip(offsets, VARIANTS):
        sub = df[df["variant"] == variant].iloc[0]
        ax.bar(
            [i + offset for i in x],
            [sub[v] for v in VERDICTS],
            width=width,
            label=variant,
            color=COLORS[variant],
        )
    ax.set_xticks(list(x), VERDICTS)
    ax.set_ylabel("Number of claims")
    ax.set_title("Phase A3 D3 full verdict totals by pipeline")
    ax.legend(frameon=False)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "phase_a3_audit_aligned_verdict_counts.png", dpi=300)
    fig.savefig(OUT_DIR / "phase_a3_audit_aligned_verdict_counts.pdf")
    plt.close(fig)


def plot_percent(df: pd.DataFrame) -> None:
    pct_cols = [f"{v}_pct" for v in VERDICTS]
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    left = pd.Series(0.0, index=df.index)
    verdict_colors = {
        "supported": "#2E7D32",
        "unsupported": "#D97706",
        "contradicted": "#B91C1C",
        "unverifiable_v0": "#64748B",
    }
    for verdict, pct_col in zip(VERDICTS, pct_cols):
        ax.barh(
            df["variant"],
            df[pct_col],
            left=left,
            label=verdict,
            color=verdict_colors[verdict],
            edgecolor="white",
            linewidth=0.5,
        )
        left += df[pct_col]
    ax.set_xlim(0, 100)
    ax.set_xlabel("Percent of claims")
    ax.set_title("Phase A3 D3 full verdict composition by pipeline")
    ax.legend(loc="lower right", frameon=False)
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "phase_a3_audit_aligned_verdict_percent.png", dpi=300)
    fig.savefig(OUT_DIR / "phase_a3_audit_aligned_verdict_percent.pdf")
    plt.close(fig)


def plot_main_three_counts(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    x = range(len(VERDICTS))
    width = 0.24
    offsets = [-width, 0, width]
    for offset, (variant, _) in zip(offsets, MAIN_VARIANTS):
        sub = df[df["variant"] == variant].iloc[0]
        ax.bar(
            [i + offset for i in x],
            [sub[v] for v in VERDICTS],
            width=width,
            label=variant,
            color=COLORS[variant],
        )
    ax.set_xticks(list(x), VERDICTS)
    ax.set_ylabel("Number of claims")
    ax.set_title("MetAgent verdict totals by architecture")
    ax.legend(frameon=False)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "metagent_three_architecture_verdict_counts.png", dpi=300)
    fig.savefig(OUT_DIR / "metagent_three_architecture_verdict_counts.pdf")
    plt.close(fig)


def write_main_three_readme(df: pd.DataFrame) -> None:
    lines = [
        "# MetAgent Three-Architecture Verdict Summary",
        "",
        "This figure collapses the literature ablation and treats the final `v4_a3_d3_with_lit/feedback` output as `MetAgent-feedback`.",
        "",
        "| variant | source | total claims | supported % | unsupported % | contradicted % | unverifiable_v0 % |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for _, row in df.iterrows():
        lines.append(
            f"| {row['variant']} | `{row['path']}` | {int(row['total_claims'])} | "
            f"{row['supported_pct']:.2f} | {row['unsupported_pct']:.2f} | "
            f"{row['contradicted_pct']:.2f} | {row['unverifiable_v0_pct']:.2f} |"
        )
    (OUT_DIR / "metagent_three_architecture_README.md").write_text("\n".join(lines) + "\n")


def write_readme(df: pd.DataFrame) -> None:
    lines = [
        "# Phase A3 Audit-Aligned Verdict Summary",
        "",
        "This reproduces `reports/agent/phase_a3_audit.md` section 1.2 for D3 full v4, using final `verdict.json` files only.",
        "",
        "| variant | source | total claims | supported % | unsupported % | contradicted % | unverifiable_v0 % |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for _, row in df.iterrows():
        lines.append(
            f"| {row['variant']} | `{row['path']}` | {int(row['total_claims'])} | "
            f"{row['supported_pct']:.2f} | {row['unsupported_pct']:.2f} | "
            f"{row['contradicted_pct']:.2f} | {row['unverifiable_v0_pct']:.2f} |"
        )
    lines += [
        "",
        "Important distinction: this is pipeline-level comparison (`single`, `react`, `fb_nolit`, `+literature`). It is not the same as the internal feedback iteration comparison inside `result.json`.",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = collect_counts()
    main_df = collect_counts(MAIN_VARIANTS)
    df.to_csv(OUT_DIR / "phase_a3_audit_aligned_verdict_summary.csv", index=False)
    main_df.to_csv(OUT_DIR / "metagent_three_architecture_verdict_summary.csv", index=False)
    plot_counts(df)
    plot_percent(df)
    plot_main_three_counts(main_df)
    write_readme(df)
    write_main_three_readme(main_df)
    print(f"Wrote Phase A3 audit-aligned verdict summary to {OUT_DIR}")


if __name__ == "__main__":
    main()
