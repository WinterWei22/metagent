#!/usr/bin/env python3
"""Analyze pathway-identification accuracy before vs after feedback."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import binomtest


REPO_ROOT = Path(__file__).resolve().parents[4]
RECORDS_PATH = REPO_ROOT / "paper_docs/stage2/minimax/semantic/semantic_similarity_records.csv"
OUT_DIR = REPO_ROOT / "paper_docs/stage2/minimax/claims/pathway_feedback_accuracy"

BEFORE_DATASET = "d3_metagent_wo_feedback_no_lit"
AFTER_DATASET = "d3_metagent_with_lit"
BEFORE_LABEL = "MetAgent-ReAct"
AFTER_LABEL = "MetAgent-feedback"

METRICS = [
    ("strict_top1_hit", "Strict GT top-1"),
    ("strict_top3_hit", "Strict top-3"),
    ("semantic_gt_hit_at_0_80", "Semantic GT >= 0.80"),
    ("semantic_top3_hit_at_0_80", "Semantic top-3 >= 0.80"),
    ("semantic_top10_hit_at_0_80", "Semantic top-10 >= 0.80"),
]


def _bool_series(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.lower().map({"true": True, "false": False}).fillna(False)


def load_pair() -> pd.DataFrame:
    records = pd.read_csv(RECORDS_PATH)
    before = records[records["dataset"] == BEFORE_DATASET].copy()
    after = records[records["dataset"] == AFTER_DATASET].copy()
    keep = [
        "task_id",
        "ground_truth_pathway",
        "ground_truth_pathway_source",
        "predicted_top_pathway",
        "strict_top1_hit",
        "strict_top3_hit",
        "semantic_gt_similarity",
        "semantic_top3_best_similarity",
        "semantic_top10_best_similarity",
        "semantic_gt_hit_at_0_80",
        "semantic_top3_hit_at_0_80",
        "semantic_top10_hit_at_0_80",
    ]
    before = before[keep].rename(
        columns={c: f"before_{c}" for c in keep if c != "task_id"}
    )
    after = after[keep].rename(
        columns={c: f"after_{c}" for c in keep if c != "task_id"}
    )
    pair = before.merge(after, on="task_id", how="inner", validate="one_to_one")
    for metric, _ in METRICS:
        pair[f"before_{metric}"] = _bool_series(pair[f"before_{metric}"])
        pair[f"after_{metric}"] = _bool_series(pair[f"after_{metric}"])
    pair["delta_semantic_gt_similarity"] = (
        pair["after_semantic_gt_similarity"] - pair["before_semantic_gt_similarity"]
    )
    pair["delta_semantic_top3_similarity"] = (
        pair["after_semantic_top3_best_similarity"]
        - pair["before_semantic_top3_best_similarity"]
    )
    return pair


def transition_label(before: bool, after: bool) -> str:
    if before and after:
        return "kept_correct"
    if (not before) and after:
        return "corrected"
    if before and not after:
        return "lost"
    return "kept_incorrect"


def summarize(pair: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    transition_rows = []
    n = len(pair)
    for metric, label in METRICS:
        b = pair[f"before_{metric}"]
        a = pair[f"after_{metric}"]
        corrected = int((~b & a).sum())
        lost = int((b & ~a).sum())
        kept_correct = int((b & a).sum())
        kept_incorrect = int((~b & ~a).sum())
        discordant = corrected + lost
        p_value = (
            float(binomtest(corrected, discordant, 0.5).pvalue)
            if discordant
            else 1.0
        )
        summary_rows.append(
            {
                "metric": metric,
                "label": label,
                "n": n,
                "before_correct": int(b.sum()),
                "after_correct": int(a.sum()),
                "before_accuracy": float(b.mean()),
                "after_accuracy": float(a.mean()),
                "delta_correct": int(a.sum() - b.sum()),
                "delta_accuracy": float(a.mean() - b.mean()),
                "corrected": corrected,
                "lost": lost,
                "kept_correct": kept_correct,
                "kept_incorrect": kept_incorrect,
                "mcnemar_exact_p": p_value,
            }
        )
        for _, row in pair.iterrows():
            transition_rows.append(
                {
                    "task_id": row["task_id"],
                    "metric": metric,
                    "label": label,
                    "before_correct": bool(row[f"before_{metric}"]),
                    "after_correct": bool(row[f"after_{metric}"]),
                    "transition": transition_label(
                        bool(row[f"before_{metric}"]),
                        bool(row[f"after_{metric}"]),
                    ),
                    "ground_truth_pathway": row["before_ground_truth_pathway"],
                    "before_predicted_top_pathway": row["before_predicted_top_pathway"],
                    "after_predicted_top_pathway": row["after_predicted_top_pathway"],
                }
            )
    return pd.DataFrame(summary_rows), pd.DataFrame(transition_rows)


def plot_accuracy(summary: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    x = range(len(summary))
    width = 0.34
    before_vals = summary["before_accuracy"] * 100
    after_vals = summary["after_accuracy"] * 100
    before_bars = ax.bar(
        [i - width / 2 for i in x],
        before_vals,
        width=width,
        label=BEFORE_LABEL,
        color="#2563EB",
    )
    after_bars = ax.bar(
        [i + width / 2 for i in x],
        after_vals,
        width=width,
        label=AFTER_LABEL,
        color="#0F766E",
    )
    for i, row in summary.reset_index(drop=True).iterrows():
        y = max(before_vals.iloc[i], after_vals.iloc[i]) + 2.2
        delta_pp = row["delta_accuracy"] * 100
        text = f"{delta_pp:+.1f} pp"
        color = "#0F766E" if delta_pp > 0 else ("#B91C1C" if delta_pp < 0 else "#334155")
        ax.plot(
            [i - width / 2, i + width / 2],
            [y - 0.8, y - 0.8],
            color="#64748B",
            linewidth=0.8,
        )
        ax.text(i, y, text, ha="center", va="bottom", fontsize=10, color=color)
    ax.set_xticks(list(x), summary["label"], rotation=18, ha="right")
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("Pathway-identification accuracy before vs after feedback")
    ax.legend(frameon=False)
    ax.set_ylim(0, 100)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "pathway_accuracy_before_after_feedback.png", dpi=300)
    fig.savefig(OUT_DIR / "pathway_accuracy_before_after_feedback.pdf")
    plt.close(fig)


def plot_transitions(summary: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    labels = summary["label"].tolist()
    parts = [
        ("kept_correct", "kept_correct", "#2E7D32"),
        ("corrected", "corrected", "#0F766E"),
        ("lost", "lost", "#B91C1C"),
        ("kept_incorrect", "kept_incorrect", "#94A3B8"),
    ]
    left = pd.Series(0, index=summary.index, dtype=float)
    for col, label, color in parts:
        vals = summary[col]
        ax.barh(labels, vals, left=left, label=label, color=color)
        left += vals
    ax.set_xlabel("Tasks")
    ax.set_title("Task-level transitions after feedback")
    ax.legend(frameon=False, ncol=2, loc="lower right")
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "pathway_accuracy_transition_counts.png", dpi=300)
    fig.savefig(OUT_DIR / "pathway_accuracy_transition_counts.pdf")
    plt.close(fig)


def plot_semantic_delta(pair: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(6.8, 4.8))
    vals = pair["delta_semantic_gt_similarity"].dropna()
    ax.hist(vals, bins=18, color="#0F766E", alpha=0.8, edgecolor="white")
    ax.axvline(0, color="#334155", linewidth=1.0)
    ax.axvline(vals.mean(), color="#B45309", linewidth=1.4, linestyle="--", label=f"mean={vals.mean():.3f}")
    ax.set_xlabel(f"Delta semantic similarity ({AFTER_LABEL} - {BEFORE_LABEL})")
    ax.set_ylabel("Tasks")
    ax.set_title("Semantic pathway-similarity change after feedback")
    ax.legend(frameon=False)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "semantic_gt_similarity_delta_after_feedback.png", dpi=300)
    fig.savefig(OUT_DIR / "semantic_gt_similarity_delta_after_feedback.pdf")
    plt.close(fig)


def write_readme(summary: pd.DataFrame, pair: pd.DataFrame) -> None:
    lines = [
        "# Pathway Accuracy Before vs After Feedback",
        "",
        f"Before feedback: `{BEFORE_DATASET}` as `{BEFORE_LABEL}`",
        f"After feedback: `{AFTER_DATASET}` as `{AFTER_LABEL}`",
        "",
        "This follows the three-model paper/audit-aligned architecture framing: `MetAgent-single`, `MetAgent-ReAct`, `MetAgent-feedback`.",
        "",
        "| metric | before | after | delta | corrected | lost | kept_correct | kept_incorrect | McNemar exact p |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"| {row['label']} | {int(row['before_correct'])}/{int(row['n'])} "
            f"({row['before_accuracy']*100:.1f}%) | {int(row['after_correct'])}/{int(row['n'])} "
            f"({row['after_accuracy']*100:.1f}%) | {int(row['delta_correct'])} "
            f"({row['delta_accuracy']*100:+.1f} pp) | {int(row['corrected'])} | "
            f"{int(row['lost'])} | {int(row['kept_correct'])} | "
            f"{int(row['kept_incorrect'])} | {row['mcnemar_exact_p']:.4g} |"
        )
    lines += [
        "",
        f"Mean semantic GT similarity: {pair['before_semantic_gt_similarity'].mean():.3f} -> {pair['after_semantic_gt_similarity'].mean():.3f} "
        f"(delta {pair['delta_semantic_gt_similarity'].mean():+.3f}).",
        "",
        "Generated files:",
        "",
        "- `pathway_accuracy_feedback_summary.csv`",
        "- `pathway_accuracy_feedback_transitions.csv`",
        "- `pathway_accuracy_feedback_paired_tasks.csv`",
        "- `pathway_accuracy_before_after_feedback.png/.pdf`",
        "- `pathway_accuracy_transition_counts.png/.pdf`",
        "- `semantic_gt_similarity_delta_after_feedback.png/.pdf`",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n")
    payload = {
        "before_dataset": BEFORE_DATASET,
        "after_dataset": AFTER_DATASET,
        "n_tasks": int(len(pair)),
        "summary": summary.to_dict(orient="records"),
        "mean_before_semantic_gt_similarity": float(pair["before_semantic_gt_similarity"].mean()),
        "mean_after_semantic_gt_similarity": float(pair["after_semantic_gt_similarity"].mean()),
        "mean_delta_semantic_gt_similarity": float(pair["delta_semantic_gt_similarity"].mean()),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(payload, indent=2))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pair = load_pair()
    summary, transitions = summarize(pair)
    pair.to_csv(OUT_DIR / "pathway_accuracy_feedback_paired_tasks.csv", index=False)
    summary.to_csv(OUT_DIR / "pathway_accuracy_feedback_summary.csv", index=False)
    transitions.to_csv(OUT_DIR / "pathway_accuracy_feedback_transitions.csv", index=False)
    plot_accuracy(summary)
    plot_transitions(summary)
    plot_semantic_delta(pair)
    write_readme(summary, pair)
    print(f"Wrote pathway feedback accuracy analysis for {len(pair)} tasks to {OUT_DIR}")


if __name__ == "__main__":
    main()
