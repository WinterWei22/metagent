#!/usr/bin/env python3
"""Analyze claim-type distributions for MetAgent D3 v4 final verdicts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
INPUT_ROOT = REPO_ROOT / "data/eval/sub6/v4_a3_d3_with_lit/feedback"
OUT_DIR = REPO_ROOT / "paper_docs/stage2/minimax/claims"

VERDICT_ORDER = ["supported", "unsupported", "contradicted", "unverifiable_v0"]
VERDICT_COLORS = {
    "supported": "#2E7D32",
    "unsupported": "#D97706",
    "contradicted": "#B91C1C",
    "unverifiable_v0": "#64748B",
}


def load_claims() -> pd.DataFrame:
    rows: list[dict] = []
    verdict_paths = sorted(INPUT_ROOT.glob("*/verdict.json"))
    for verdict_path in verdict_paths:
        task_id = verdict_path.parent.name
        payload = json.loads(verdict_path.read_text())
        for idx, claim in enumerate(payload.get("claims", [])):
            extracted = claim.get("extracted_fields") or {}
            rows.append(
                {
                    "task_id": task_id,
                    "claim_index": idx,
                    "claim_id": claim.get("claim_id"),
                    "claim_text": claim.get("claim_text"),
                    "claim_type": claim.get("claim_type") or "unknown",
                    "claim_subtype": claim.get("claim_subtype") or "unknown",
                    "subject": claim.get("subject"),
                    "subject_kind": claim.get("subject_kind"),
                    "candidate_ref": claim.get("candidate_ref"),
                    "verdict": claim.get("verdict") or "unknown",
                    "source_field": claim.get("source_field"),
                    "verifier_layer": claim.get("verifier_layer"),
                    "tool_called": claim.get("tool_called"),
                    "severity": claim.get("severity"),
                    "pathway_name": extracted.get("pathway_name"),
                    "pathway_id": extracted.get("pathway_id"),
                    "candidate_name": extracted.get("candidate_name"),
                    "database_id": extracted.get("database_id"),
                    "pmid": extracted.get("pmid"),
                    "doi": extracted.get("doi"),
                }
            )
    return pd.DataFrame(rows)


def add_percentages(table: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    out = table.copy()
    denom = out.groupby(group_cols, dropna=False)["n"].transform("sum")
    out["pct_within_group"] = out["n"] / denom * 100.0
    out["pct_all_claims"] = out["n"] / out["n"].sum() * 100.0
    return out


def crosstab_counts(df: pd.DataFrame, index_col: str) -> pd.DataFrame:
    table = (
        pd.crosstab(df[index_col], df["verdict"])
        .reindex(columns=VERDICT_ORDER, fill_value=0)
        .astype(int)
    )
    table["total"] = table[VERDICT_ORDER].sum(axis=1)
    table = table.sort_values("total", ascending=False)
    return table


def save_stacked_bar(table: pd.DataFrame, title: str, xlabel: str, path_base: Path) -> None:
    plot_table = table[VERDICT_ORDER].copy()
    fig_height = max(4.5, 0.42 * len(plot_table) + 1.5)
    fig, ax = plt.subplots(figsize=(8.5, fig_height))
    left = pd.Series(0, index=plot_table.index, dtype=float)
    for verdict in VERDICT_ORDER:
        ax.barh(
            plot_table.index,
            plot_table[verdict],
            left=left,
            color=VERDICT_COLORS[verdict],
            label=verdict,
            edgecolor="white",
            linewidth=0.4,
        )
        left += plot_table[verdict]
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("")
    ax.legend(loc="lower right", frameon=False)
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path_base.with_suffix(".png"), dpi=300)
    fig.savefig(path_base.with_suffix(".pdf"))
    plt.close(fig)


def save_percent_bar(table: pd.DataFrame, title: str, path_base: Path) -> None:
    pct = table[VERDICT_ORDER].div(table["total"], axis=0).fillna(0) * 100.0
    fig_height = max(4.5, 0.42 * len(pct) + 1.5)
    fig, ax = plt.subplots(figsize=(8.5, fig_height))
    left = pd.Series(0, index=pct.index, dtype=float)
    for verdict in VERDICT_ORDER:
        ax.barh(
            pct.index,
            pct[verdict],
            left=left,
            color=VERDICT_COLORS[verdict],
            label=verdict,
            edgecolor="white",
            linewidth=0.4,
        )
        left += pct[verdict]
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_title(title)
    ax.set_xlabel("Percent of claims within type")
    ax.set_ylabel("")
    ax.legend(loc="lower right", frameon=False)
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path_base.with_suffix(".png"), dpi=300)
    fig.savefig(path_base.with_suffix(".pdf"))
    plt.close(fig)


def save_task_distribution(df: pd.DataFrame) -> None:
    per_task = (
        df.groupby(["task_id", "claim_type"], dropna=False)
        .size()
        .reset_index(name="n")
        .pivot(index="task_id", columns="claim_type", values="n")
        .fillna(0)
        .astype(int)
    )
    per_task["total"] = per_task.sum(axis=1)
    cols = sorted([c for c in per_task.columns if c != "total"])
    per_task = per_task[cols + ["total"]].sort_values("total", ascending=False)
    per_task.to_csv(OUT_DIR / "claims_per_task_by_type.csv")

    top_types = df["claim_type"].value_counts().head(8).index.tolist()
    box_data = [
        per_task[t].values if t in per_task.columns else [0]
        for t in top_types
    ]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.boxplot(box_data, tick_labels=top_types, vert=True, patch_artist=True)
    ax.set_title("Per-task claim count distribution by claim type")
    ax.set_ylabel("Claims per task")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "per_task_claim_type_boxplot.png", dpi=300)
    fig.savefig(OUT_DIR / "per_task_claim_type_boxplot.pdf")
    plt.close(fig)


def write_markdown_summary(df: pd.DataFrame, type_table: pd.DataFrame) -> None:
    verdict_counts = df["verdict"].value_counts().reindex(VERDICT_ORDER, fill_value=0)
    type_counts = df["claim_type"].value_counts()
    lines = [
        "# MetAgent D3 v4 Claim Distribution",
        "",
        f"Input: `{INPUT_ROOT.relative_to(REPO_ROOT)}`",
        "",
        f"Tasks: {df['task_id'].nunique()}",
        f"Claims: {len(df)}",
        "",
        "## Verdict Totals",
        "",
        "| verdict | n | pct |",
        "|---|---:|---:|",
    ]
    for verdict, n in verdict_counts.items():
        lines.append(f"| {verdict} | {int(n)} | {n / len(df) * 100:.1f}% |")
    lines += [
        "",
        "## Claim Type Totals",
        "",
        "| claim_type | n | pct | supported | unsupported | contradicted | unverifiable_v0 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for claim_type, n in type_counts.items():
        row = type_table.loc[claim_type]
        lines.append(
            f"| {claim_type} | {int(n)} | {n / len(df) * 100:.1f}% | "
            f"{int(row['supported'])} | {int(row['unsupported'])} | "
            f"{int(row['contradicted'])} | {int(row['unverifiable_v0'])} |"
        )
    lines += [
        "",
        "Figures:",
        "",
        "- `claim_type_by_verdict_counts.png/.pdf`",
        "- `claim_type_by_verdict_percent.png/.pdf`",
        "- `claim_subtype_by_verdict_counts.png/.pdf`",
        "- `per_task_claim_type_boxplot.png/.pdf`",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_claims()
    if df.empty:
        raise SystemExit(f"No claims found under {INPUT_ROOT}")

    df.to_csv(OUT_DIR / "claims_long.csv", index=False)

    type_table = crosstab_counts(df, "claim_type")
    subtype_table = crosstab_counts(df, "claim_subtype")
    type_table.to_csv(OUT_DIR / "claim_type_by_verdict_counts.csv")
    subtype_table.to_csv(OUT_DIR / "claim_subtype_by_verdict_counts.csv")

    type_long = (
        df.groupby(["claim_type", "verdict"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    type_long = add_percentages(type_long, ["claim_type"])
    type_long.to_csv(OUT_DIR / "claim_type_by_verdict_long.csv", index=False)

    subtype_long = (
        df.groupby(["claim_subtype", "verdict"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    subtype_long = add_percentages(subtype_long, ["claim_subtype"])
    subtype_long.to_csv(OUT_DIR / "claim_subtype_by_verdict_long.csv", index=False)

    summary = {
        "input_root": str(INPUT_ROOT.relative_to(REPO_ROOT)),
        "n_tasks": int(df["task_id"].nunique()),
        "n_claims": int(len(df)),
        "verdict_counts": Counter(df["verdict"]).most_common(),
        "claim_type_counts": Counter(df["claim_type"]).most_common(),
        "claim_subtype_counts": Counter(df["claim_subtype"]).most_common(),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))

    save_stacked_bar(
        type_table,
        "MetAgent D3 v4 final claims by type and verdict",
        "Number of claims",
        OUT_DIR / "claim_type_by_verdict_counts",
    )
    save_percent_bar(
        type_table,
        "MetAgent D3 v4 verdict composition by claim type",
        OUT_DIR / "claim_type_by_verdict_percent",
    )
    save_stacked_bar(
        subtype_table,
        "MetAgent D3 v4 final claims by subtype and verdict",
        "Number of claims",
        OUT_DIR / "claim_subtype_by_verdict_counts",
    )
    save_task_distribution(df)
    write_markdown_summary(df, type_table)

    print(f"Wrote {len(df)} claims from {df['task_id'].nunique()} tasks to {OUT_DIR}")


if __name__ == "__main__":
    main()
