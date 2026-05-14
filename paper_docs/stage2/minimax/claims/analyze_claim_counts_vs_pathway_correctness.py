#!/usr/bin/env python3
"""Relate final claim verdict counts to MetAgent pathway top-1 correctness."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from scipy import stats


REPO_ROOT = Path(__file__).resolve().parents[4]
VERDICT_ROOT = REPO_ROOT / "data/eval/sub6/v4_a3_d3_with_lit/feedback"
CORRECTNESS_PATH = (
    REPO_ROOT
    / "paper_docs/stage2/minimax/semantic/figures/fig10_ground_truth_strict_transition_records.csv"
)
OUT_DIR = REPO_ROOT / "paper_docs/stage2/minimax/claims/pathway_correctness_correlation"

VERDICTS = ["supported", "unsupported", "contradicted", "unverifiable_v0"]
FEATURES = [
    "supported",
    "unsupported",
    "contradicted",
    "unverifiable_v0",
    "total_claims",
    "actionable_claims",
    "supported_fraction",
    "actionable_fraction",
    "unverifiable_fraction",
    "pathway_supported",
    "pathway_unsupported",
    "pathway_contradicted",
    "pathway_unverifiable_v0",
    "pathway_total_claims",
    "pathway_actionable_claims",
    "pathway_supported_fraction",
    "has_supported_pathway_claim",
]


def load_claim_counts() -> pd.DataFrame:
    rows: list[dict] = []
    for verdict_path in sorted(VERDICT_ROOT.glob("*/verdict.json")):
        task_id = verdict_path.parent.name
        payload = json.loads(verdict_path.read_text())
        claims = payload.get("claims", [])
        counts = Counter(claim.get("verdict") or "unknown" for claim in claims)
        pathway_claims = [
            claim for claim in claims
            if claim.get("claim_type") == "set_enrichment"
            or claim.get("claim_subtype") == "enrichment_pathway"
        ]
        pathway_counts = Counter(claim.get("verdict") or "unknown" for claim in pathway_claims)
        row = {"task_id": task_id}
        for verdict in VERDICTS:
            row[verdict] = int(counts.get(verdict, 0))
        row["total_claims"] = sum(row[v] for v in VERDICTS)
        row["actionable_claims"] = row["unsupported"] + row["contradicted"]
        row["supported_fraction"] = row["supported"] / row["total_claims"] if row["total_claims"] else 0.0
        row["actionable_fraction"] = (
            row["actionable_claims"] / row["total_claims"] if row["total_claims"] else 0.0
        )
        row["unverifiable_fraction"] = (
            row["unverifiable_v0"] / row["total_claims"] if row["total_claims"] else 0.0
        )
        for verdict in VERDICTS:
            row[f"pathway_{verdict}"] = int(pathway_counts.get(verdict, 0))
        row["pathway_total_claims"] = sum(row[f"pathway_{v}"] for v in VERDICTS)
        row["pathway_actionable_claims"] = row["pathway_unsupported"] + row["pathway_contradicted"]
        row["pathway_supported_fraction"] = (
            row["pathway_supported"] / row["pathway_total_claims"]
            if row["pathway_total_claims"]
            else 0.0
        )
        row["has_supported_pathway_claim"] = int(row["pathway_supported"] > 0)
        rows.append(row)
    return pd.DataFrame(rows)


def safe_corr(x: pd.Series, y: pd.Series, method: str) -> tuple[float, float]:
    if x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2:
        return float("nan"), float("nan")
    if method == "pearson":
        r, p = stats.pearsonr(x, y)
    elif method == "spearman":
        r, p = stats.spearmanr(x, y)
    else:
        raise ValueError(method)
    return float(r), float(p)


def make_analysis_table(df: pd.DataFrame) -> pd.DataFrame:
    y = df["pathway_correct"].astype(int)
    rows: list[dict] = []
    for feature in FEATURES:
        correct = df.loc[df["pathway_correct"], feature]
        incorrect = df.loc[~df["pathway_correct"], feature]
        pearson_r, pearson_p = safe_corr(df[feature], y, "pearson")
        spearman_r, spearman_p = safe_corr(df[feature], y, "spearman")
        if len(correct) and len(incorrect):
            u_stat, mw_p = stats.mannwhitneyu(correct, incorrect, alternative="two-sided")
        else:
            u_stat, mw_p = float("nan"), float("nan")
        rows.append(
            {
                "feature": feature,
                "mean_correct": float(correct.mean()),
                "mean_incorrect": float(incorrect.mean()),
                "median_correct": float(correct.median()),
                "median_incorrect": float(incorrect.median()),
                "delta_mean_correct_minus_incorrect": float(correct.mean() - incorrect.mean()),
                "point_biserial_r": pearson_r,
                "point_biserial_p": pearson_p,
                "spearman_r": spearman_r,
                "spearman_p": spearman_p,
                "mann_whitney_u": float(u_stat),
                "mann_whitney_p": float(mw_p),
            }
        )
    return pd.DataFrame(rows)


def plot_boxplots(df: pd.DataFrame) -> None:
    labels = ["incorrect", "correct"]
    fig, axes = plt.subplots(2, 2, figsize=(9, 7.2))
    for ax, feature in zip(axes.ravel(), VERDICTS):
        data = [
            df.loc[~df["pathway_correct"], feature].values,
            df.loc[df["pathway_correct"], feature].values,
        ]
        ax.boxplot(data, tick_labels=labels, patch_artist=True)
        ax.scatter(
            [1] * len(data[0]),
            data[0],
            color="#B91C1C",
            alpha=0.55,
            s=18,
            zorder=3,
        )
        ax.scatter(
            [2] * len(data[1]),
            data[1],
            color="#2E7D32",
            alpha=0.55,
            s=18,
            zorder=3,
        )
        ax.set_title(feature)
        ax.set_ylabel("claims per task")
        ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
        ax.set_axisbelow(True)
    fig.suptitle("Claim verdict counts by pathway top-1 correctness", y=0.995)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "claim_counts_by_pathway_correctness_boxplots.png", dpi=300)
    fig.savefig(OUT_DIR / "claim_counts_by_pathway_correctness_boxplots.pdf")
    plt.close(fig)


def plot_correlation_bars(analysis: pd.DataFrame) -> None:
    plot_df = analysis.set_index("feature").loc[FEATURES]
    fig, ax = plt.subplots(figsize=(8, 5.2))
    colors = ["#2E7D32" if v > 0 else "#B91C1C" for v in plot_df["point_biserial_r"]]
    ax.barh(plot_df.index, plot_df["point_biserial_r"], color=colors)
    ax.axvline(0, color="#334155", linewidth=0.9)
    ax.set_xlabel("Point-biserial r with pathway correctness")
    ax.set_title("Correlation between claim metrics and pathway correctness")
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "claim_metric_correlations_with_pathway_correctness.png", dpi=300)
    fig.savefig(OUT_DIR / "claim_metric_correlations_with_pathway_correctness.pdf")
    plt.close(fig)


def plot_supported_vs_actionable(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 5.4))
    for correct, label, color in [(False, "incorrect", "#B91C1C"), (True, "correct", "#2E7D32")]:
        sub = df[df["pathway_correct"] == correct]
        ax.scatter(
            sub["supported"],
            sub["actionable_claims"],
            label=label,
            color=color,
            alpha=0.75,
            s=36,
        )
    ax.set_xlabel("supported claims")
    ax.set_ylabel("unsupported + contradicted claims")
    ax.set_title("Supported vs actionable claims by pathway correctness")
    ax.legend(frameon=False)
    ax.grid(color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "supported_vs_actionable_by_pathway_correctness.png", dpi=300)
    fig.savefig(OUT_DIR / "supported_vs_actionable_by_pathway_correctness.pdf")
    plt.close(fig)


def write_summary(df: pd.DataFrame, analysis: pd.DataFrame) -> None:
    n_correct = int(df["pathway_correct"].sum())
    n_incorrect = int((~df["pathway_correct"]).sum())
    top_rows = analysis.reindex(analysis["point_biserial_r"].abs().sort_values(ascending=False).index)
    lines = [
        "# Claim Counts vs Pathway Correctness",
        "",
        f"Claim source: `{VERDICT_ROOT.relative_to(REPO_ROOT)}`",
        f"Correctness source: `{CORRECTNESS_PATH.relative_to(REPO_ROOT)}`",
        "",
        f"Tasks: {len(df)}",
        f"Pathway top-1 correct: {n_correct}",
        f"Pathway top-1 incorrect: {n_incorrect}",
        "",
        "Correctness label is `strict_top1_hit_metagent` from the semantic transition table.",
        "",
        "## Main Associations",
        "",
        "| feature | mean_correct | mean_incorrect | delta | point_biserial_r | p |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for _, row in top_rows.iterrows():
        lines.append(
            f"| {row['feature']} | {row['mean_correct']:.3f} | {row['mean_incorrect']:.3f} | "
            f"{row['delta_mean_correct_minus_incorrect']:.3f} | {row['point_biserial_r']:.3f} | "
            f"{row['point_biserial_p']:.4g} |"
        )
    lines += [
        "",
        "Pathway-prefixed features count only `set_enrichment` / `enrichment_pathway` claims.",
        "",
        "Interpretation: positive r means larger values are associated with correct pathway identification; negative r means larger values are associated with incorrect identification.",
        "",
        "Generated files:",
        "",
        "- `claim_counts_vs_pathway_correctness_by_task.csv`",
        "- `claim_count_correlation_stats.csv`",
        "- `claim_counts_by_pathway_correctness_boxplots.png/.pdf`",
        "- `claim_metric_correlations_with_pathway_correctness.png/.pdf`",
        "- `supported_vs_actionable_by_pathway_correctness.png/.pdf`",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n")
    summary = {
        "n_tasks": int(len(df)),
        "n_pathway_correct": n_correct,
        "n_pathway_incorrect": n_incorrect,
        "feature_stats": analysis.to_dict(orient="records"),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counts = load_claim_counts()
    correctness = pd.read_csv(CORRECTNESS_PATH)
    correctness = correctness.rename(columns={"strict_top1_hit_metagent": "pathway_correct"})
    merged = counts.merge(
        correctness[
            [
                "task_id",
                "pathway_correct",
                "predicted_top_pathway_metagent",
                "ground_truth_pathway_metagent",
                "transition",
            ]
        ],
        on="task_id",
        how="inner",
        validate="one_to_one",
    )
    if len(merged) != len(counts):
        raise SystemExit(f"Expected {len(counts)} merged rows, got {len(merged)}")
    merged["pathway_correct"] = merged["pathway_correct"].astype(bool)
    analysis = make_analysis_table(merged)

    merged.to_csv(OUT_DIR / "claim_counts_vs_pathway_correctness_by_task.csv", index=False)
    analysis.to_csv(OUT_DIR / "claim_count_correlation_stats.csv", index=False)
    plot_boxplots(merged)
    plot_correlation_bars(analysis)
    plot_supported_vs_actionable(merged)
    write_summary(merged, analysis)
    print(f"Wrote claim-count/pathway-correctness analysis for {len(merged)} tasks to {OUT_DIR}")


if __name__ == "__main__":
    main()
