#!/usr/bin/env python3
"""Analyze ReAct and feedback-stage tool-call usage for MetAgent D3 v4."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
REACT_ROOT = REPO_ROOT / "data/eval/sub6/v4_a3_d3_no_lit/react"
FEEDBACK_ROOT = REPO_ROOT / "data/eval/sub6/v4_a3_d3_with_lit/feedback"
OUT_DIR = REPO_ROOT / "paper_docs/stage2/minimax/claims/tool_calls"


TOOL_GROUPS = {
    "query_ramp_enrichment": "Enrichment",
    "query_pathway_membership": "Pathway evidence",
    "query_kegg_path": "Pathway evidence",
    "lookup_compound_info": "Compound lookup",
    "search_literature": "Literature",
}

GROUP_COLORS = {
    "Enrichment": "#8DBDD6",
    "Pathway evidence": "#6FA8C8",
    "Compound lookup": "#CFE7DF",
    "Literature": "#D5E8E1",
    "Other": "#D8DEE9",
}

MODE_COLORS = {
    "MetAgent-ReAct": "#2563EB",
    "Feedback revision": "#0F766E",
}


def normalize_tool_name(name: str | None) -> str:
    if not name:
        return "unknown"
    # One MiniMax tool call has a malformed function name in the trace.
    if name == "query_ramp_en Enrichment":
        return "query_ramp_enrichment"
    return name


def group_for_tool(name: str) -> str:
    return TOOL_GROUPS.get(name, "Other")


def collect_react_calls() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []
    per_task: list[dict] = []
    for path in sorted(REACT_ROOT.glob("*/narrative.json")):
        task_id = path.parent.name
        payload = json.loads(path.read_text())
        tool_calls = payload.get("tool_calls_log") or []
        per_task.append(
            {
                "mode": "MetAgent-ReAct",
                "task_id": task_id,
                "n_tool_calls": len(tool_calls),
                "n_turns": payload.get("n_turns"),
            }
        )
        for call_idx, call in enumerate(tool_calls):
            raw_name = call.get("name")
            name = normalize_tool_name(raw_name)
            rows.append(
                {
                    "mode": "MetAgent-ReAct",
                    "task_id": task_id,
                    "iter_idx": 0,
                    "turn_idx": call.get("turn"),
                    "call_idx": call_idx,
                    "raw_tool_name": raw_name,
                    "tool_name": name,
                    "tool_group": group_for_tool(name),
                    "arguments": call.get("arguments"),
                    "cached": call.get("cached"),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(per_task)


def collect_feedback_revision_calls() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []
    per_task_counts: defaultdict[str, int] = defaultdict(int)
    for task_dir in sorted(p for p in FEEDBACK_ROOT.iterdir() if p.is_dir()):
        task_id = task_dir.name
        for turns_path in task_dir.glob("persist/*/turns.jsonl"):
            for line in turns_path.read_text().splitlines():
                if not line.strip():
                    continue
                turn = json.loads(line)
                for call_idx, call in enumerate(turn.get("tool_calls_log") or []):
                    raw_name = call.get("name")
                    name = normalize_tool_name(raw_name)
                    per_task_counts[task_id] += 1
                    rows.append(
                        {
                            "mode": "Feedback revision",
                            "task_id": task_id,
                            "iter_idx": turn.get("iter_idx"),
                            "turn_idx": turn.get("turn_idx"),
                            "call_idx": call_idx,
                            "raw_tool_name": raw_name,
                            "tool_name": name,
                            "tool_group": group_for_tool(name),
                            "arguments": call.get("arguments"),
                            "cached": call.get("cached"),
                        }
                    )

    per_task: list[dict] = []
    iter_rows: list[dict] = []
    for result_path in sorted(FEEDBACK_ROOT.glob("*/result.json")):
        task_id = result_path.parent.name
        result = json.loads(result_path.read_text())
        per_task.append(
            {
                "mode": "Feedback revision",
                "task_id": task_id,
                "n_tool_calls": int(per_task_counts.get(task_id, 0)),
                "n_turns": None,
            }
        )
        for it in result.get("iterations") or []:
            iter_rows.append(
                {
                    "task_id": task_id,
                    "iter_idx": int(it.get("iter_idx")),
                    "n_tool_calls": int(it.get("n_tool_calls") or 0),
                    "n_turns": int(it.get("n_turns") or 0),
                    "feedback_prompt_used": bool(it.get("feedback_prompt_used")),
                    "selected_final": int(result.get("final_iter_idx", -1)) == int(it.get("iter_idx")),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(per_task), pd.DataFrame(iter_rows)


def summarize_calls(calls: pd.DataFrame) -> pd.DataFrame:
    if calls.empty:
        return pd.DataFrame(columns=["mode", "tool_group", "tool_name", "n_calls", "n_tasks"])
    return (
        calls.groupby(["mode", "tool_group", "tool_name"], dropna=False)
        .agg(n_calls=("tool_name", "size"), n_tasks=("task_id", "nunique"))
        .reset_index()
        .sort_values(["mode", "tool_group", "n_calls"], ascending=[True, True, False])
    )


def plot_tool_usage(summary: pd.DataFrame) -> None:
    modes = ["MetAgent-ReAct", "Feedback revision"]
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 5.6), sharex=False)
    for ax, mode in zip(axes, modes):
        sub = summary[summary["mode"] == mode].copy()
        sub = sub.sort_values(["tool_group", "n_calls"], ascending=[True, False])
        x = list(range(len(sub)))
        max_y = max(sub["n_calls"].max() if len(sub) else 1, 1)
        start = 0
        for group, group_df in sub.groupby("tool_group", sort=False):
            end = start + len(group_df)
            ax.axvspan(start - 0.48, end - 0.52, color=GROUP_COLORS.get(group, "#D8DEE9"), alpha=0.25)
            ax.text(
                (start + end - 1) / 2,
                max_y * 1.13,
                group,
                ha="center",
                va="bottom",
                fontsize=10,
                color="#2F5597",
            )
            start = end
        bars = ax.bar(
            x,
            sub["n_calls"],
            color=[GROUP_COLORS.get(g, "#D8DEE9") for g in sub["tool_group"]],
            edgecolor="#1F2937",
            linewidth=0.6,
        )
        for bar, value in zip(bars, sub["n_calls"]):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max_y * 0.03,
                f"{int(value):,}",
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold",
            )
        ax.set_title(mode, loc="left", fontsize=12, color="#1F3A8A")
        ax.set_ylabel("Tool calls")
        ax.set_xticks(x, sub["tool_name"], rotation=15, ha="right")
        ax.set_ylim(0, max_y * 1.28)
        ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.suptitle("MetAgent tool utilization by stage", fontsize=15)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "tool_calls_react_vs_feedback_by_tool.png", dpi=300)
    fig.savefig(OUT_DIR / "tool_calls_react_vs_feedback_by_tool.pdf")
    plt.close(fig)


def plot_feedback_iteration(iter_summary: pd.DataFrame) -> None:
    by_iter = (
        iter_summary.groupby("iter_idx", dropna=False)
        .agg(n_tool_calls=("n_tool_calls", "sum"), n_turns=("n_turns", "sum"), n_tasks=("task_id", "nunique"))
        .reset_index()
        .sort_values("iter_idx")
    )
    labels = [f"iter {int(i)}" for i in by_iter["iter_idx"]]
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    bars = ax.bar(labels, by_iter["n_tool_calls"], color=["#94A3B8", "#0F766E", "#0F766E"], edgecolor="#1F2937", linewidth=0.6)
    max_y = max(by_iter["n_tool_calls"].max(), 1)
    for bar, value in zip(bars, by_iter["n_tool_calls"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + max_y * 0.03, f"{int(value):,}", ha="center", va="bottom", fontweight="bold")
    ax.set_ylabel("Tool calls")
    ax.set_title("Feedback run total tool calls by iteration")
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "feedback_tool_calls_by_iteration.png", dpi=300)
    fig.savefig(OUT_DIR / "feedback_tool_calls_by_iteration.pdf")
    plt.close(fig)
    by_iter.to_csv(OUT_DIR / "feedback_tool_calls_by_iteration.csv", index=False)


def write_readme(
    summary: pd.DataFrame,
    raw_summary: pd.DataFrame,
    react_task: pd.DataFrame,
    feedback_task: pd.DataFrame,
    feedback_iter: pd.DataFrame,
) -> None:
    def mode_lines(mode: str) -> list[str]:
        sub = summary[summary["mode"] == mode].sort_values("n_calls", ascending=False)
        lines = ["", f"## {mode}", "", "| tool | group | calls | tasks with call |", "|---|---|---:|---:|"]
        for _, row in sub.iterrows():
            lines.append(f"| {row['tool_name']} | {row['tool_group']} | {int(row['n_calls'])} | {int(row['n_tasks'])} |")
        return lines

    fb_total = int(feedback_iter["n_tool_calls"].sum())
    fb_revision = int(feedback_task["n_tool_calls"].sum())
    lines = [
        "# MetAgent Tool Call Usage",
        "",
        f"ReAct source: `{REACT_ROOT.relative_to(REPO_ROOT)}`",
        f"Feedback source: `{FEEDBACK_ROOT.relative_to(REPO_ROOT)}`",
        "",
        "Name-level ReAct counts come from `narrative.json.tool_calls_log`.",
        "Name-level feedback counts come from `persist/*/turns.jsonl`, which records feedback revision turns. `result.json` also records feedback-run total tool calls by iteration, including iter0.",
        "",
        f"- ReAct standalone: {int(react_task['n_tool_calls'].sum())} calls across {len(react_task)} tasks.",
        f"- Feedback revision turns with tool names: {fb_revision} calls across {int((feedback_task['n_tool_calls'] > 0).sum())}/{len(feedback_task)} tasks.",
        f"- Feedback full run total from `result.json`: {fb_total} calls; iter0 tool names are not fully persisted in `turns.jsonl`.",
    ]
    lines += mode_lines("MetAgent-ReAct")
    lines += mode_lines("Feedback revision")
    lines += [
        "",
        "Generated files:",
        "",
        "- `tool_calls_raw.csv`",
        "- `tool_calls_by_tool.csv`",
        "- `tool_calls_by_tool_raw_names.csv`",
        "- `tool_calls_per_task.csv`",
        "- `feedback_tool_calls_by_iteration.csv`",
        "- `tool_calls_react_vs_feedback_by_tool.png/.pdf`",
        "- `feedback_tool_calls_by_iteration.png/.pdf`",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n")

    payload = {
        "react_total_tool_calls": int(react_task["n_tool_calls"].sum()),
        "react_tasks": int(len(react_task)),
        "feedback_revision_named_tool_calls": fb_revision,
        "feedback_revision_tasks": int(len(feedback_task)),
        "feedback_revision_tasks_with_calls": int((feedback_task["n_tool_calls"] > 0).sum()),
        "feedback_full_result_json_tool_calls": fb_total,
        "tool_counts": summary.to_dict(orient="records"),
        "raw_tool_counts": raw_summary.to_dict(orient="records"),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(payload, indent=2))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    react_calls, react_task = collect_react_calls()
    feedback_calls, feedback_task, feedback_iter = collect_feedback_revision_calls()
    calls = pd.concat([react_calls, feedback_calls], ignore_index=True)
    per_task = pd.concat([react_task, feedback_task], ignore_index=True)
    summary = summarize_calls(calls)
    raw_summary = (
        calls.groupby(["mode", "raw_tool_name"], dropna=False)
        .size()
        .reset_index(name="n_calls")
        .sort_values(["mode", "n_calls"], ascending=[True, False])
    )

    calls.to_csv(OUT_DIR / "tool_calls_raw.csv", index=False)
    summary.to_csv(OUT_DIR / "tool_calls_by_tool.csv", index=False)
    raw_summary.to_csv(OUT_DIR / "tool_calls_by_tool_raw_names.csv", index=False)
    per_task.to_csv(OUT_DIR / "tool_calls_per_task.csv", index=False)
    feedback_iter.to_csv(OUT_DIR / "feedback_tool_calls_by_task_iteration.csv", index=False)
    plot_tool_usage(summary)
    plot_feedback_iteration(feedback_iter)
    write_readme(summary, raw_summary, react_task, feedback_task, feedback_iter)
    print(f"Wrote tool-call analysis to {OUT_DIR}")


if __name__ == "__main__":
    main()
