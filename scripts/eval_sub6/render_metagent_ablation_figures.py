"""Render LLM -> MetAgent w/o feedback -> MetAgent ablation figures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


STAGES = [
    ("LLM", "d3_llm_single_with_lit", "#4C78A8"),
    ("MetAgent w/o feedback", "d3_metagent_wo_feedback_with_lit", "#72B7B2"),
    ("MetAgent", "d3_metagent_with_lit", "#F58518"),
]
THRESHOLD = 0.90


def _bool_series(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.lower().map({"true": True, "false": False}).fillna(False)


def _load_task_meta(tasks_path: Path) -> pd.DataFrame:
    rows = []
    with tasks_path.open() as f:
        for line in f:
            task = json.loads(line)
            gt = task.get("ground_truth_pathway") or {}
            rows.append(
                {
                    "task_id": task["task_id"],
                    "gt_pathway_name": gt.get("pathway_name"),
                    "gt_pathway_source": gt.get("pathway_source"),
                    "signal_count": task.get("signal_count"),
                    "noise_count": task.get("noise_count"),
                    "signal_ratio": task.get("signal_ratio"),
                }
            )
    return pd.DataFrame(rows)


def _load(records_path: Path, tasks_path: Path) -> pd.DataFrame:
    df = pd.read_csv(records_path)
    df = df[df["dataset"].isin([d for _, d, _ in STAGES])].copy()
    for col in [
        "semantic_gt_similarity",
        "semantic_top3_best_similarity",
        "semantic_top10_best_similarity",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["strict_top1_hit"] = _bool_series(df["strict_top1_hit"])
    df["strict_top3_hit"] = _bool_series(df["strict_top3_hit"])
    df["semantic_gt_hit_0_90"] = df["semantic_gt_similarity"] >= THRESHOLD
    df["semantic_top3_hit_0_90"] = df["semantic_top3_best_similarity"] >= THRESHOLD
    df["semantic_top10_hit_0_90"] = df["semantic_top10_best_similarity"] >= THRESHOLD
    return df.merge(_load_task_meta(tasks_path), on="task_id", how="left")


def _summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for stage, dataset, _ in STAGES:
        sub = df[df["dataset"] == dataset]
        rows.append(
            {
                "stage": stage,
                "dataset": dataset,
                "n": len(sub),
                "strict_top1_acc": sub["strict_top1_hit"].mean(),
                "strict_top3_acc": sub["strict_top3_hit"].mean(),
                "semantic_gt_mean": sub["semantic_gt_similarity"].mean(),
                "semantic_gt_ge_0_90": sub["semantic_gt_hit_0_90"].mean(),
                "semantic_top3_mean": sub["semantic_top3_best_similarity"].mean(),
                "semantic_top3_ge_0_90": sub["semantic_top3_hit_0_90"].mean(),
                "semantic_top10_ge_0_90": sub["semantic_top10_hit_0_90"].mean(),
            }
        )
    return pd.DataFrame(rows)


def _paired(df: pd.DataFrame) -> pd.DataFrame:
    out = None
    for stage, dataset, _ in STAGES:
        sub = df[df["dataset"] == dataset][
            [
                "task_id",
                "gt_pathway_name",
                "gt_pathway_source",
                "semantic_gt_similarity",
                "semantic_top3_best_similarity",
                "strict_top1_hit",
                "strict_top3_hit",
                "predicted_top_pathway",
            ]
        ].copy()
        sub = sub.rename(
            columns={
                "semantic_gt_similarity": f"{stage}_semantic_gt",
                "semantic_top3_best_similarity": f"{stage}_semantic_top3",
                "strict_top1_hit": f"{stage}_strict_top1",
                "strict_top3_hit": f"{stage}_strict_top3",
                "predicted_top_pathway": f"{stage}_predicted_top_pathway",
            }
        )
        if out is None:
            out = sub
        else:
            out = out.merge(
                sub,
                on=["task_id", "gt_pathway_name", "gt_pathway_source"],
                how="inner",
                validate="one_to_one",
            )
    assert out is not None
    out["delta_llm_to_wo_feedback"] = (
        out["MetAgent w/o feedback_semantic_gt"] - out["LLM_semantic_gt"]
    )
    out["delta_wo_feedback_to_full"] = (
        out["MetAgent_semantic_gt"] - out["MetAgent w/o feedback_semantic_gt"]
    )
    out["delta_llm_to_full"] = out["MetAgent_semantic_gt"] - out["LLM_semantic_gt"]
    return out


def _save(fig: plt.Figure, out_dir: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(out_dir / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(out_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def _style(ax: plt.Axes) -> None:
    ax.grid(True, axis="y", alpha=0.25, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def plot_key_metrics(summary: pd.DataFrame, out_dir: Path) -> None:
    metrics = [
        ("strict_top1_acc", "Strict GT top-1 acc"),
        ("strict_top3_acc", "Strict top-3 acc"),
        ("semantic_gt_ge_0_90", "Semantic GT >= 0.90"),
        ("semantic_top3_ge_0_90", "Semantic top-3 >= 0.90"),
        ("semantic_gt_mean", "Mean semantic GT score"),
    ]
    x = np.arange(len(metrics))
    width = 0.25
    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    for idx, (stage, _, color) in enumerate(STAGES):
        vals = [summary.loc[summary["stage"] == stage, m].iloc[0] for m, _ in metrics]
        ax.bar(x + (idx - 1) * width, vals, width=width, label=stage, color=color)
    ax.set_xticks(x)
    ax.set_xticklabels([label for _, label in metrics], rotation=18, ha="right")
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Value")
    ax.set_title("Ablation: LLM vs tool-use vs verifier-feedback MetAgent")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    _style(ax)
    _save(fig, out_dir, "fig11_ablation_key_metrics")


def plot_trajectory(paired: pd.DataFrame, summary: pd.DataFrame, out_dir: Path) -> None:
    cols = ["LLM_semantic_gt", "MetAgent w/o feedback_semantic_gt", "MetAgent_semantic_gt"]
    x = np.arange(3)
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    for _, row in paired.iterrows():
        y = [row[c] for c in cols]
        color = "#54A24B" if y[-1] >= y[0] else "#E45756"
        ax.plot(x, y, color=color, alpha=0.24, linewidth=1.1)
    means = [
        summary.loc[summary["stage"] == stage, "semantic_gt_mean"].iloc[0]
        for stage, _, _ in STAGES
    ]
    ax.plot(x, means, color="black", marker="o", linewidth=3.0, label="Mean")
    ax.set_xticks(x)
    ax.set_xticklabels([stage for stage, _, _ in STAGES], rotation=12)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("SapBERT similarity to GT")
    ax.set_title("Per-task semantic trajectory across ablation stages")
    ax.legend(frameon=False)
    _style(ax)
    _save(fig, out_dir, "fig12_ablation_paired_semantic_trajectories")


def plot_incremental_gains(paired: pd.DataFrame, out_dir: Path) -> None:
    data = [
        paired["delta_llm_to_wo_feedback"],
        paired["delta_wo_feedback_to_full"],
        paired["delta_llm_to_full"],
    ]
    labels = ["LLM -> w/o feedback", "w/o feedback -> full", "LLM -> full"]
    colors = ["#72B7B2", "#F58518", "#54A24B"]
    fig, ax = plt.subplots(figsize=(7.4, 4.8))
    parts = ax.violinplot(data, showmeans=False, showmedians=True, widths=0.72)
    for body, color in zip(parts["bodies"], colors):
        body.set_facecolor(color)
        body.set_edgecolor("none")
        body.set_alpha(0.35)
    for key in ["cmedians", "cbars", "cmins", "cmaxes"]:
        parts[key].set_color("#333333")
        parts[key].set_linewidth(1.1)
    rng = np.random.default_rng(42)
    for idx, vals in enumerate(data, start=1):
        jitter = rng.normal(0, 0.035, len(vals))
        ax.scatter(np.full(len(vals), idx) + jitter, vals, s=18, color=colors[idx - 1], alpha=0.65)
        ax.text(idx, max(vals) + 0.05, f"mean={vals.mean():.3f}", ha="center", fontsize=9)
    ax.axhline(0, color="#4A4A4A", linewidth=1.1)
    ax.set_xticks([1, 2, 3])
    ax.set_xticklabels(labels, rotation=10)
    ax.set_ylabel("Delta SapBERT similarity to GT")
    ax.set_title("Incremental semantic gains from tools and feedback")
    _style(ax)
    _save(fig, out_dir, "fig13_ablation_incremental_gain_distribution")


def plot_source_ablation(df: pd.DataFrame, out_dir: Path) -> None:
    rows = []
    for (source, stage), sub in df.groupby(["gt_pathway_source", "dataset"]):
        stage_name = next(s for s, d, _ in STAGES if d == stage)
        rows.append(
            {
                "gt_pathway_source": source,
                "stage": stage_name,
                "n": len(sub),
                "semantic_gt_mean": sub["semantic_gt_similarity"].mean(),
                "semantic_gt_ge_0_90": sub["semantic_gt_hit_0_90"].mean(),
            }
        )
    summary = pd.DataFrame(rows)
    summary.to_csv(out_dir / "fig14_ablation_by_pathway_source.csv", index=False)
    sources = (
        summary.groupby("gt_pathway_source")["n"].max().sort_values(ascending=False).index.tolist()
    )
    x = np.arange(len(sources))
    width = 0.25
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    for idx, (stage, _, color) in enumerate(STAGES):
        vals = []
        for source in sources:
            sub = summary[(summary["stage"] == stage) & (summary["gt_pathway_source"] == source)]
            vals.append(sub["semantic_gt_mean"].iloc[0] if len(sub) else np.nan)
        ax.bar(x + (idx - 1) * width, vals, width=width, label=stage, color=color)
    labels = [
        f"{s}\n(n={int(summary[summary['gt_pathway_source'] == s]['n'].max())})"
        for s in sources
    ]
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Mean SapBERT similarity to GT")
    ax.set_title("Ablation by ground-truth pathway source")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    _style(ax)
    _save(fig, out_dir, "fig14_ablation_by_pathway_source")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="paper_docs/stage2/minimax/semantic/semantic_similarity_records.csv")
    ap.add_argument("--tasks", default="data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")
    ap.add_argument("--out-dir", default="paper_docs/stage2/minimax/semantic/figures")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = _load(Path(args.records), Path(args.tasks))
    summary = _summary(df)
    paired = _paired(df)
    summary.to_csv(out_dir / "ablation_key_metrics_summary.csv", index=False)
    paired.to_csv(out_dir / "ablation_paired_task_scores.csv", index=False)

    plot_key_metrics(summary, out_dir)
    plot_trajectory(paired, summary, out_dir)
    plot_incremental_gains(paired, out_dir)
    plot_source_ablation(df, out_dir)

    print(f"wrote ablation figures to {out_dir}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
