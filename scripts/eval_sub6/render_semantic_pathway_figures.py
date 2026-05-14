"""Render semantic pathway-analysis figures for MiniMax A3.

Inputs:
  - paper_docs/stage2/minimax/semantic/semantic_similarity_records.csv
  - data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl

Outputs:
  - paper_docs/stage2/minimax/semantic/figures/*
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


LLM_DATASET = "d3_llm_single_with_lit"
METAGENT_DATASET = "d3_metagent_with_lit"
THRESHOLD = 0.90
BLUE = "#4C78A8"
ORANGE = "#F58518"
GREEN = "#54A24B"
RED = "#E45756"
GRAY = "#4A4A4A"


def _load_task_metadata(path: Path) -> pd.DataFrame:
    rows: list[dict] = []
    with path.open() as f:
        for line in f:
            task = json.loads(line)
            gt = task.get("ground_truth_pathway") or {}
            top = task.get("ramp_enrichment_result", {}).get("top_pathways", []) or []
            gt_rank = next(
                (
                    idx + 1
                    for idx, p in enumerate(top)
                    if p.get("pathway_id") == gt.get("pathway_id")
                ),
                None,
            )
            family = re.sub(r"_seed\d+$", "", task["task_id"]).replace(
                "compound_only_enrich_mammalian_", ""
            )
            rows.append(
                {
                    "task_id": task["task_id"],
                    "pathway_family": family,
                    "gt_pathway_name": gt.get("pathway_name"),
                    "gt_pathway_source": gt.get("pathway_source"),
                    "gt_rank": gt_rank,
                    "signal_count": task.get("signal_count"),
                    "noise_count": task.get("noise_count"),
                    "signal_ratio": task.get("signal_ratio"),
                    "metabolite_count": len(task.get("differential_metabolites") or []),
                }
            )
    return pd.DataFrame(rows)


def _load_pair(records_path: Path, tasks_path: Path) -> pd.DataFrame:
    records = pd.read_csv(records_path)
    records = records[records["dataset"].isin([LLM_DATASET, METAGENT_DATASET])].copy()
    records["semantic_gt_similarity"] = pd.to_numeric(
        records["semantic_gt_similarity"], errors="coerce"
    )
    meta = _load_task_metadata(tasks_path)
    records = records.merge(meta, on="task_id", how="left")

    llm = records[records["dataset"] == LLM_DATASET].copy()
    ma = records[records["dataset"] == METAGENT_DATASET].copy()
    keep_cols = [
        "task_id",
        "semantic_gt_similarity",
        "predicted_top_pathway",
        "strict_top1_hit",
        "strict_top3_hit",
    ]
    pair = llm.merge(
        ma,
        on="task_id",
        suffixes=("_llm", "_metagent"),
        validate="one_to_one",
    )
    # Metadata columns are duplicated by suffix because both sides carry them.
    for col in [
        "pathway_family",
        "gt_pathway_name",
        "gt_pathway_source",
        "gt_rank",
        "signal_count",
        "noise_count",
        "signal_ratio",
        "metabolite_count",
    ]:
        pair[col] = pair[f"{col}_llm"]
    pair["llm_score"] = pair["semantic_gt_similarity_llm"]
    pair["metagent_score"] = pair["semantic_gt_similarity_metagent"]
    pair["delta"] = pair["metagent_score"] - pair["llm_score"]
    pair["llm_hit_0_90"] = pair["llm_score"] >= THRESHOLD
    pair["metagent_hit_0_90"] = pair["metagent_score"] >= THRESHOLD
    return pair


def _save(fig: plt.Figure, out_dir: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(out_dir / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(out_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def _style(ax: plt.Axes) -> None:
    ax.grid(True, axis="y", alpha=0.25, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def plot_ecdf(pair: pd.DataFrame, out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for score_col, label, color in [
        ("llm_score", "LLM", BLUE),
        ("metagent_score", "MetAgent", ORANGE),
    ]:
        vals = np.sort(pair[score_col].dropna().to_numpy())
        y = np.arange(1, len(vals) + 1) / len(vals)
        hit = (vals >= THRESHOLD).mean()
        ax.step(vals, y, where="post", color=color, linewidth=2.4, label=f"{label} (>=0.90={hit:.1%})")
    ax.axvline(THRESHOLD, color=GRAY, linestyle="--", linewidth=1.8, label="Threshold = 0.90")
    ax.set_xlim(0.0, 1.02)
    ax.set_ylim(0.0, 1.02)
    ax.set_xlabel("SapBERT semantic similarity to ground-truth pathway")
    ax.set_ylabel("Cumulative fraction")
    ax.set_title("ECDF of semantic pathway similarity (D3 full, with_lit)")
    ax.legend(frameon=False, loc="upper left")
    _style(ax)
    _save(fig, out_dir, "fig01_ecdf_semantic_similarity_llm_vs_metagent")


def plot_paired_delta(pair: pd.DataFrame, out_dir: Path) -> None:
    ordered = pair.sort_values("delta").reset_index(drop=True)
    y = np.arange(len(ordered))
    colors = np.where(ordered["delta"] >= 0, GREEN, RED)
    fig, ax = plt.subplots(figsize=(7.2, 7.2))
    ax.barh(y, ordered["delta"], color=colors, alpha=0.86)
    ax.axvline(0, color=GRAY, linewidth=1.2)
    ax.axvline(ordered["delta"].mean(), color="black", linestyle="--", linewidth=1.4, label=f"Mean delta = {ordered['delta'].mean():.3f}")
    ax.set_xlabel("Delta semantic similarity (MetAgent - LLM)")
    ax.set_ylabel("Task, sorted by delta")
    ax.set_title("Paired task-level semantic gain")
    ax.legend(frameon=False, loc="lower right")
    _style(ax)
    _save(fig, out_dir, "fig02_paired_delta_semantic_similarity")

    ordered[
        [
            "task_id",
            "gt_pathway_name",
            "gt_pathway_source",
            "llm_score",
            "metagent_score",
            "delta",
            "predicted_top_pathway_llm",
            "predicted_top_pathway_metagent",
        ]
    ].to_csv(out_dir / "fig02_paired_delta_semantic_similarity.csv", index=False)


def _group_summary(pair: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows: list[dict] = []
    for key, sub in pair.groupby(group_col, dropna=False):
        rows.append(
            {
                group_col: key,
                "n": len(sub),
                "llm_mean": sub["llm_score"].mean(),
                "metagent_mean": sub["metagent_score"].mean(),
                "delta_mean": sub["delta"].mean(),
                "llm_hit_0_90": sub["llm_hit_0_90"].mean(),
                "metagent_hit_0_90": sub["metagent_hit_0_90"].mean(),
            }
        )
    return pd.DataFrame(rows)


def plot_group_bar(
    pair: pd.DataFrame,
    out_dir: Path,
    group_col: str,
    stem: str,
    title: str,
    xlabel: str,
    min_n: int = 1,
) -> None:
    summary = _group_summary(pair, group_col)
    summary = summary[summary["n"] >= min_n].copy()
    summary = summary.sort_values("delta_mean", ascending=True)
    summary.to_csv(out_dir / f"{stem}.csv", index=False)

    y = np.arange(len(summary))
    fig_h = max(4.8, 0.42 * len(summary) + 1.6)
    fig, ax = plt.subplots(figsize=(7.8, fig_h))
    ax.barh(y - 0.18, summary["llm_mean"], height=0.34, color=BLUE, alpha=0.86, label="LLM")
    ax.barh(y + 0.18, summary["metagent_mean"], height=0.34, color=ORANGE, alpha=0.86, label="MetAgent")
    labels = [f"{v} (n={n})" for v, n in zip(summary[group_col], summary["n"])]
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlim(0.0, 1.05)
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    ax.legend(frameon=False, loc="lower right")
    _style(ax)
    _save(fig, out_dir, stem)


def plot_gt_rank(pair: pd.DataFrame, out_dir: Path) -> None:
    summary = _group_summary(pair, "gt_rank").sort_values("gt_rank")
    summary.to_csv(out_dir / "fig05_gt_rank_stratified_semantic_similarity.csv", index=False)
    x = np.arange(len(summary))
    width = 0.36
    fig, ax = plt.subplots(figsize=(6.8, 4.6))
    ax.bar(x - width / 2, summary["llm_mean"], width, color=BLUE, label="LLM")
    ax.bar(x + width / 2, summary["metagent_mean"], width, color=ORANGE, label="MetAgent")
    ax.set_xticks(x)
    ax.set_xticklabels([f"rank {int(r)}\n(n={int(n)})" for r, n in zip(summary["gt_rank"], summary["n"])])
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("Mean SapBERT similarity to GT")
    ax.set_title("Performance by ground-truth enrichment rank")
    ax.legend(frameon=False)
    _style(ax)
    _save(fig, out_dir, "fig05_gt_rank_stratified_semantic_similarity")


def plot_noise_signal(pair: pd.DataFrame, out_dir: Path) -> None:
    for col, stem, title in [
        ("noise_count", "fig06_noise_count_stratified_semantic_similarity", "Performance by number of noise metabolites"),
        ("signal_count", "fig07_signal_count_stratified_semantic_similarity", "Performance by number of signal metabolites"),
    ]:
        summary = _group_summary(pair, col).sort_values(col)
        summary.to_csv(out_dir / f"{stem}.csv", index=False)
        x = np.arange(len(summary))
        width = 0.36
        fig, ax = plt.subplots(figsize=(7.0, 4.6))
        ax.bar(x - width / 2, summary["llm_mean"], width, color=BLUE, label="LLM")
        ax.bar(x + width / 2, summary["metagent_mean"], width, color=ORANGE, label="MetAgent")
        ax.set_xticks(x)
        ax.set_xticklabels([f"{int(v)}\n(n={int(n)})" for v, n in zip(summary[col], summary["n"])])
        ax.set_ylim(0.0, 1.05)
        ax.set_xlabel(col)
        ax.set_ylabel("Mean SapBERT similarity to GT")
        ax.set_title(title)
        ax.legend(frameon=False)
        _style(ax)
        _save(fig, out_dir, stem)

    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    sc = ax.scatter(
        pair["signal_ratio"],
        pair["delta"],
        c=pair["metagent_score"],
        cmap="viridis",
        s=58,
        alpha=0.86,
        edgecolor="white",
        linewidth=0.6,
    )
    ax.axhline(0, color=GRAY, linewidth=1.1)
    ax.set_xlabel("Signal ratio in differential metabolite set")
    ax.set_ylabel("Delta semantic similarity (MetAgent - LLM)")
    ax.set_title("Semantic gain vs input signal ratio")
    cbar = fig.colorbar(sc, ax=ax)
    cbar.set_label("MetAgent similarity")
    _style(ax)
    _save(fig, out_dir, "fig08_signal_ratio_vs_semantic_gain")


def plot_transition(pair: pd.DataFrame, out_dir: Path) -> None:
    def state(row: pd.Series) -> str:
        if row["llm_hit_0_90"] and row["metagent_hit_0_90"]:
            return "Both high"
        if (not row["llm_hit_0_90"]) and row["metagent_hit_0_90"]:
            return "Corrected by MetAgent"
        if row["llm_hit_0_90"] and (not row["metagent_hit_0_90"]):
            return "Lost by MetAgent"
        return "Both low"

    states = pair.apply(state, axis=1)
    order = ["Corrected by MetAgent", "Both high", "Both low", "Lost by MetAgent"]
    counts = states.value_counts().reindex(order, fill_value=0)
    frac = counts / len(pair)
    pd.DataFrame({"transition": counts.index, "n": counts.values, "fraction": frac.values}).to_csv(
        out_dir / "fig09_threshold_transition_0_90.csv", index=False
    )

    colors = [GREEN, "#72B7B2", "#BAB0AC", RED]
    fig, ax = plt.subplots(figsize=(7.2, 2.7))
    left = 0.0
    for label, value, color in zip(counts.index, frac.values, colors):
        ax.barh([0], [value], left=left, height=0.5, color=color, label=f"{label}: {int(counts[label])}")
        if value > 0.07:
            ax.text(left + value / 2, 0, f"{value:.0%}", ha="center", va="center", color="white", fontsize=10, fontweight="bold")
        left += value
    ax.set_xlim(0, 1)
    ax.set_yticks([])
    ax.set_xlabel("Fraction of tasks")
    ax.set_title("Threshold transition at SapBERT similarity >= 0.90")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    _save(fig, out_dir, "fig09_threshold_transition_0_90")


def write_failure_tables(pair: pd.DataFrame, out_dir: Path) -> None:
    cols = [
        "task_id",
        "gt_pathway_name",
        "gt_pathway_source",
        "gt_rank",
        "pathway_family",
        "llm_score",
        "metagent_score",
        "delta",
        "predicted_top_pathway_llm",
        "predicted_top_pathway_metagent",
    ]
    pair.sort_values("delta", ascending=False)[cols].head(15).to_csv(
        out_dir / "top15_metagent_improvements.csv", index=False
    )
    pair.sort_values("delta", ascending=True)[cols].head(15).to_csv(
        out_dir / "top15_metagent_regressions.csv", index=False
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="paper_docs/stage2/minimax/semantic/semantic_similarity_records.csv")
    ap.add_argument("--tasks", default="data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")
    ap.add_argument("--out-dir", default="paper_docs/stage2/minimax/semantic/figures")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pair = _load_pair(Path(args.records), Path(args.tasks))
    pair.to_csv(out_dir / "paired_llm_metagent_semantic_scores.csv", index=False)

    plot_ecdf(pair, out_dir)
    plot_paired_delta(pair, out_dir)
    plot_group_bar(
        pair,
        out_dir,
        "gt_pathway_name",
        "fig03_pathway_family_stratified_semantic_similarity",
        "Performance by ground-truth pathway family",
        "Mean SapBERT similarity to GT",
        min_n=1,
    )
    plot_group_bar(
        pair,
        out_dir,
        "gt_pathway_source",
        "fig04_pathway_source_stratified_semantic_similarity",
        "Performance by ground-truth pathway source",
        "Mean SapBERT similarity to GT",
        min_n=1,
    )
    plot_gt_rank(pair, out_dir)
    plot_noise_signal(pair, out_dir)
    plot_transition(pair, out_dir)
    write_failure_tables(pair, out_dir)

    print(f"wrote semantic pathway figures to {out_dir}")


if __name__ == "__main__":
    main()
