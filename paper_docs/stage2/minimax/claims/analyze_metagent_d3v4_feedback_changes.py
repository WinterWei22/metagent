#!/usr/bin/env python3
"""Analyze internal verifier-feedback iteration changes for MetAgent D3 v4."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
INPUT_ROOT = REPO_ROOT / "data/eval/sub6/v4_a3_d3_with_lit/feedback"
OUT_DIR = REPO_ROOT / "paper_docs/stage2/minimax/claims/feedback_changes"

VERDICTS = ["supported", "unsupported", "contradicted", "unverifiable_v0"]
COLORS = {
    "supported": "#2E7D32",
    "unsupported": "#D97706",
    "contradicted": "#B91C1C",
    "unverifiable_v0": "#64748B",
}

PATHWAY_ID_RE = re.compile(r"\b(?:RAMP_P_\d{9}|WP\d+|map\d{5})\b")
PATHWAY_NAME_WITH_ID_RE = re.compile(
    r"([A-Z][A-Za-z0-9α-ωΑ-ΩΔδβγκ'’,/+\- ]{2,90}?)\s*"
    r"\((?:KEGG\s+)?(?:map\d{5}|WikiPathways\s+WP\d+|WP\d+|RAMP_P_\d{9})",
)


def norm_counts(verdict_total: dict) -> dict[str, int]:
    return {v: int(verdict_total.get(v, 0)) for v in VERDICTS}


def quality(counts: dict[str, int]) -> int:
    return counts["unsupported"] + counts["contradicted"]


def clean_pathway_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" -*:;,.()[]")
    name = re.sub(r"^(?:the|a|an)\s+", "", name, flags=re.IGNORECASE)
    return name


def extract_pathways_from_text(text: str) -> tuple[list[str], list[str]]:
    ids = sorted(set(PATHWAY_ID_RE.findall(text or "")))
    names: set[str] = set()
    for match in PATHWAY_NAME_WITH_ID_RE.findall(text or ""):
        cleaned = clean_pathway_name(match)
        if cleaned:
            names.add(cleaned)
    return sorted(names), ids


def extract_final_pathway_claims(verdict_path: Path) -> tuple[list[str], list[str], list[str]]:
    payload = json.loads(verdict_path.read_text())
    names: set[str] = set()
    ids: set[str] = set()
    verdicts: list[str] = []
    for claim in payload.get("claims", []):
        ctype = claim.get("claim_type")
        subtype = claim.get("claim_subtype")
        if not (ctype == "set_enrichment" or subtype == "enrichment_pathway"):
            continue
        fields = claim.get("extracted_fields") or {}
        if fields.get("pathway_name"):
            names.add(str(fields["pathway_name"]))
        if fields.get("pathway_id"):
            ids.add(str(fields["pathway_id"]))
        verdicts.append(str(claim.get("verdict") or "unknown"))
    return sorted(names), sorted(ids), verdicts


def norm_name_set(names: list[str]) -> set[str]:
    return {re.sub(r"\s+", " ", n).strip().casefold() for n in names if str(n).strip()}


def load_rows() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    count_rows: list[dict] = []
    pathway_rows: list[dict] = []
    summary_rows: list[dict] = []

    for result_path in sorted(INPUT_ROOT.glob("*/result.json")):
        task_dir = result_path.parent
        task_id = task_dir.name
        result = json.loads(result_path.read_text())
        iterations = result.get("iterations") or []
        if not iterations:
            continue
        iter_by_idx = {int(it["iter_idx"]): it for it in iterations}
        before = iter_by_idx[min(iter_by_idx)]
        final_idx = int(result.get("final_iter_idx", before["iter_idx"]))
        final = iter_by_idx[final_idx]

        before_counts = norm_counts(before.get("verdict_total") or {})
        final_counts = norm_counts(final.get("verdict_total") or {})
        final_verdict_payload = json.loads((task_dir / "verdict.json").read_text())
        final_rescored_counts = norm_counts(final_verdict_payload.get("verdicts_total") or {})
        for phase, iter_rec, counts in [
            ("before_feedback_iter0", before, before_counts),
            ("after_feedback_final", final, final_counts),
            (
                "after_feedback_final_rescored_verdict_json",
                {"iter_idx": final["iter_idx"]},
                final_rescored_counts,
            ),
        ]:
            row = {
                "task_id": task_id,
                "phase": phase,
                "iter_idx": int(iter_rec["iter_idx"]),
                "total_claims": sum(counts.values()),
                "quality_unsupported_plus_contradicted": quality(counts),
            }
            row.update(counts)
            count_rows.append(row)

        delta = {f"delta_{v}": final_counts[v] - before_counts[v] for v in VERDICTS}
        before_names, before_ids = extract_pathways_from_text(before.get("narrative") or "")
        final_names, final_ids = extract_pathways_from_text(final.get("narrative") or "")
        claim_names, claim_ids, claim_verdicts = extract_final_pathway_claims(task_dir / "verdict.json")

        before_name_set = norm_name_set(before_names)
        final_name_set = norm_name_set(final_names)
        before_id_set = set(before_ids)
        final_id_set = set(final_ids)
        pathway_id_changed = before_id_set != final_id_set
        pathway_name_changed = before_name_set != final_name_set
        pathway_changed = pathway_id_changed or pathway_name_changed

        summary_rows.append(
            {
                "task_id": task_id,
                "final_iter_idx": final_idx,
                "n_iterations": len(iterations),
                "rollback_reason": result.get("rollback_reason"),
                "termination_reason": result.get("termination_reason"),
                "before_total_claims": sum(before_counts.values()),
                "final_total_claims": sum(final_counts.values()),
                "final_rescored_total_claims": sum(final_rescored_counts.values()),
                "delta_total_claims": sum(final_counts.values()) - sum(before_counts.values()),
                "delta_rescored_total_claims": sum(final_rescored_counts.values()) - sum(before_counts.values()),
                "before_quality": quality(before_counts),
                "final_quality": quality(final_counts),
                "final_rescored_quality": quality(final_rescored_counts),
                "delta_quality": quality(final_counts) - quality(before_counts),
                "delta_rescored_quality": quality(final_rescored_counts) - quality(before_counts),
                "before_pathway_names": "; ".join(before_names),
                "final_pathway_names": "; ".join(final_names),
                "added_pathway_names": "; ".join(sorted(set(final_names) - set(before_names))),
                "removed_pathway_names": "; ".join(sorted(set(before_names) - set(final_names))),
                "before_pathway_ids": "; ".join(before_ids),
                "final_pathway_ids": "; ".join(final_ids),
                "added_pathway_ids": "; ".join(sorted(final_id_set - before_id_set)),
                "removed_pathway_ids": "; ".join(sorted(before_id_set - final_id_set)),
                "pathway_identification_changed": pathway_changed,
                "pathway_id_changed": pathway_id_changed,
                "pathway_name_changed": pathway_name_changed,
                "final_verdict_pathway_claim_names": "; ".join(claim_names),
                "final_verdict_pathway_claim_ids": "; ".join(claim_ids),
                "final_pathway_claim_supported": claim_verdicts.count("supported"),
                "final_pathway_claim_unsupported": claim_verdicts.count("unsupported"),
                "final_pathway_claim_contradicted": claim_verdicts.count("contradicted"),
                "final_pathway_claim_unverifiable_v0": claim_verdicts.count("unverifiable_v0"),
                **delta,
                **{f"delta_rescored_{v}": final_rescored_counts[v] - before_counts[v] for v in VERDICTS},
            }
        )

        for phase, names, ids in [
            ("before_feedback_iter0", before_names, before_ids),
            ("after_feedback_final", final_names, final_ids),
        ]:
            pathway_rows.append(
                {
                    "task_id": task_id,
                    "phase": phase,
                    "pathway_names": "; ".join(names),
                    "pathway_ids": "; ".join(ids),
                    "n_pathway_names": len(names),
                    "n_pathway_ids": len(ids),
                }
            )

    return pd.DataFrame(count_rows), pd.DataFrame(summary_rows), pd.DataFrame(pathway_rows)


def plot_verdict_totals(counts_df: pd.DataFrame) -> None:
    totals = counts_df.groupby("phase")[VERDICTS].sum().loc[
        [
            "before_feedback_iter0",
            "after_feedback_final",
            "after_feedback_final_rescored_verdict_json",
        ]
    ]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    x = range(len(VERDICTS))
    width = 0.25
    ax.bar(
        [i - width for i in x],
        totals.loc["before_feedback_iter0", VERDICTS],
        width=width,
        label="Feedback run internal iter 0",
        color="#94A3B8",
    )
    ax.bar(
        [i for i in x],
        totals.loc["after_feedback_final", VERDICTS],
        width=width,
        label="Feedback run final selected",
        color="#2E7D32",
    )
    ax.bar(
        [i + width for i in x],
        totals.loc["after_feedback_final_rescored_verdict_json", VERDICTS],
        width=width,
        label="Final narrative verdict.json",
        color="#0F766E",
    )
    ax.set_xticks(list(x), VERDICTS)
    ax.set_ylabel("Number of claims")
    ax.set_title("Internal feedback-run verdict totals")
    ax.legend(frameon=False)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "verdict_totals_before_after.png", dpi=300)
    fig.savefig(OUT_DIR / "verdict_totals_before_after.pdf")
    plt.close(fig)

    deltas = (
        totals.loc["after_feedback_final_rescored_verdict_json", VERDICTS]
        - totals.loc["before_feedback_iter0", VERDICTS]
    )
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(VERDICTS, deltas.values, color=[COLORS[v] for v in VERDICTS])
    ax.axhline(0, color="#334155", linewidth=0.9)
    ax.set_ylabel("Final verdict.json - internal iter0 claims")
    ax.set_title("Net verdict-count change within feedback run")
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "verdict_delta_totals.png", dpi=300)
    fig.savefig(OUT_DIR / "verdict_delta_totals.pdf")
    plt.close(fig)

    total_claims = totals[VERDICTS].sum(axis=1)
    phase_labels = ["Before\niter 0", "Final\nselected", "Final\nverdict.json"]
    fig, ax = plt.subplots(figsize=(6.2, 4.5))
    ax.bar(phase_labels, total_claims.values, color=["#94A3B8", "#2E7D32", "#0F766E"])
    ax.set_ylabel("Total claims")
    ax.set_title("Total extracted claims within feedback run")
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    for i, value in enumerate(total_claims.values):
        ax.text(i, value + 25, str(int(value)), ha="center", va="bottom", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "total_claims_before_after.png", dpi=300)
    fig.savefig(OUT_DIR / "total_claims_before_after.pdf")
    plt.close(fig)

    pct = totals[VERDICTS].div(total_claims, axis=0) * 100.0
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    left = pd.Series(0.0, index=pct.index)
    for verdict in VERDICTS:
        ax.barh(
            phase_labels,
            pct[verdict].values,
            left=left.values,
            color=COLORS[verdict],
            label=verdict,
            edgecolor="white",
            linewidth=0.5,
        )
        left += pct[verdict]
    ax.set_xlim(0, 100)
    ax.set_xlabel("Percent of extracted claims")
    ax.set_title("Verifier verdict composition within feedback run")
    ax.legend(loc="lower right", frameon=False)
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "verdict_composition_percent_before_after.png", dpi=300)
    fig.savefig(OUT_DIR / "verdict_composition_percent_before_after.pdf")
    plt.close(fig)


def plot_quality(summary_df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(6.2, 6))
    ax.scatter(summary_df["before_quality"], summary_df["final_quality"], s=28, color="#2563EB", alpha=0.75)
    max_q = int(max(summary_df["before_quality"].max(), summary_df["final_quality"].max()))
    ax.plot([0, max_q], [0, max_q], color="#64748B", linestyle="--", linewidth=1)
    ax.set_xlabel("Before feedback actionable claims")
    ax.set_ylabel("After feedback actionable claims")
    ax.set_title("Per-task verifier quality change")
    ax.grid(color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "quality_before_after_scatter.png", dpi=300)
    fig.savefig(OUT_DIR / "quality_before_after_scatter.pdf")
    plt.close(fig)


def plot_pathway_change(summary_df: pd.DataFrame) -> None:
    counts = summary_df["pathway_identification_changed"].value_counts().rename(index={True: "changed", False: "unchanged"})
    counts = counts.reindex(["unchanged", "changed"], fill_value=0)
    fig, ax = plt.subplots(figsize=(5.5, 4.4))
    ax.bar(counts.index, counts.values, color=["#64748B", "#2563EB"])
    ax.set_ylabel("Tasks")
    ax.set_title("Pathway identification before vs after feedback")
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "pathway_identification_changed_counts.png", dpi=300)
    fig.savefig(OUT_DIR / "pathway_identification_changed_counts.pdf")
    plt.close(fig)


def write_summary(counts_df: pd.DataFrame, summary_df: pd.DataFrame) -> None:
    totals = counts_df.groupby("phase")[VERDICTS].sum().loc[
        [
            "before_feedback_iter0",
            "after_feedback_final",
            "after_feedback_final_rescored_verdict_json",
        ]
    ]
    delta = totals.loc["after_feedback_final"] - totals.loc["before_feedback_iter0"]
    delta_rescored = (
        totals.loc["after_feedback_final_rescored_verdict_json"]
        - totals.loc["before_feedback_iter0"]
    )
    improved = int((summary_df["delta_quality"] < 0).sum())
    unchanged = int((summary_df["delta_quality"] == 0).sum())
    worsened = int((summary_df["delta_quality"] > 0).sum())
    improved_rescored = int((summary_df["delta_rescored_quality"] < 0).sum())
    unchanged_rescored = int((summary_df["delta_rescored_quality"] == 0).sum())
    worsened_rescored = int((summary_df["delta_rescored_quality"] > 0).sum())
    changed = int(summary_df["pathway_identification_changed"].sum())

    lines = [
        "# MetAgent D3 v4 Internal Feedback Iteration Changes",
        "",
        f"Input: `{INPUT_ROOT.relative_to(REPO_ROOT)}`",
        "",
        "This file compares `result.json` internal iteration 0 against the selected final narrative from the same feedback run, plus final `verdict.json` rescoring. It is not the Phase A3 audit pipeline comparison (`react` -> `fb_nolit` -> `+literature`).",
        "",
        f"Tasks: {summary_df['task_id'].nunique()}",
        "",
        "## Verdict Totals",
        "",
        "| verdict | before_iter0 | final_selected_internal | final_verdict_json | delta_json_minus_before |",
        "|---|---:|---:|---:|---:|",
    ]
    for verdict in VERDICTS:
        lines.append(
            f"| {verdict} | {int(totals.loc['before_feedback_iter0', verdict])} | "
            f"{int(totals.loc['after_feedback_final', verdict])} | "
            f"{int(totals.loc['after_feedback_final_rescored_verdict_json', verdict])} | "
            f"{int(delta_rescored[verdict])} |"
        )
    lines += [
        "",
        "## Actionable Claim Quality",
        "",
        "Quality is `unsupported + contradicted`; lower is better.",
        "",
        "Using selected final iteration's internal verifier total:",
        "",
        f"- Improved tasks: {improved}",
        f"- Unchanged tasks: {unchanged}",
        f"- Worsened tasks: {worsened}",
        f"- Total before quality: {int(summary_df['before_quality'].sum())}",
        f"- Total final quality: {int(summary_df['final_quality'].sum())}",
        f"- Delta quality: {int(summary_df['delta_quality'].sum())}",
        "",
        "Using final `verdict.json` rescoring:",
        "",
        f"- Improved tasks: {improved_rescored}",
        f"- Unchanged tasks: {unchanged_rescored}",
        f"- Worsened tasks: {worsened_rescored}",
        f"- Total final rescored quality: {int(summary_df['final_rescored_quality'].sum())}",
        f"- Delta rescored quality: {int(summary_df['delta_rescored_quality'].sum())}",
        "",
        "## Pathway Identification",
        "",
        "Pathway names/IDs are extracted from iter-0 and final selected narratives with regex heuristics; final verifier pathway claims are included in the CSV as a check.",
        "",
        f"- Tasks with changed extracted pathway identification: {changed}",
        f"- Tasks unchanged: {len(summary_df) - changed}",
        "",
        "Key files:",
        "",
        "- `feedback_verdict_counts_by_task_phase.csv`",
        "- `feedback_change_summary_by_task.csv`",
        "- `pathway_identification_by_task_phase.csv`",
        "- `verdict_totals_before_after.png/.pdf`",
        "- `verdict_delta_totals.png/.pdf`",
        "- `total_claims_before_after.png/.pdf`",
        "- `verdict_composition_percent_before_after.png/.pdf`",
        "- `quality_before_after_scatter.png/.pdf`",
        "- `pathway_identification_changed_counts.png/.pdf`",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n")

    summary = {
        "input_root": str(INPUT_ROOT.relative_to(REPO_ROOT)),
        "n_tasks": int(summary_df["task_id"].nunique()),
        "verdict_totals_before": totals.loc["before_feedback_iter0"].astype(int).to_dict(),
        "verdict_totals_final_selected_internal": totals.loc["after_feedback_final"].astype(int).to_dict(),
        "verdict_totals_final_verdict_json": totals.loc["after_feedback_final_rescored_verdict_json"].astype(int).to_dict(),
        "verdict_delta_final_selected_minus_before": delta.astype(int).to_dict(),
        "verdict_delta_final_verdict_json_minus_before": delta_rescored.astype(int).to_dict(),
        "quality_improved_tasks": improved,
        "quality_unchanged_tasks": unchanged,
        "quality_worsened_tasks": worsened,
        "quality_improved_tasks_rescored": improved_rescored,
        "quality_unchanged_tasks_rescored": unchanged_rescored,
        "quality_worsened_tasks_rescored": worsened_rescored,
        "before_quality_total": int(summary_df["before_quality"].sum()),
        "final_quality_total": int(summary_df["final_quality"].sum()),
        "final_rescored_quality_total": int(summary_df["final_rescored_quality"].sum()),
        "delta_quality_total": int(summary_df["delta_quality"].sum()),
        "delta_rescored_quality_total": int(summary_df["delta_rescored_quality"].sum()),
        "pathway_identification_changed_tasks": changed,
        "pathway_identification_unchanged_tasks": int(len(summary_df) - changed),
        "final_iter_idx_counts": Counter(summary_df["final_iter_idx"]).most_common(),
        "termination_reason_counts": Counter(summary_df["termination_reason"].fillna("None")).most_common(),
        "rollback_reason_counts": Counter(summary_df["rollback_reason"].fillna("None")).most_common(),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counts_df, summary_df, pathway_df = load_rows()
    counts_df.to_csv(OUT_DIR / "feedback_verdict_counts_by_task_phase.csv", index=False)
    summary_df.to_csv(OUT_DIR / "feedback_change_summary_by_task.csv", index=False)
    pathway_df.to_csv(OUT_DIR / "pathway_identification_by_task_phase.csv", index=False)

    plot_verdict_totals(counts_df)
    plot_quality(summary_df)
    plot_pathway_change(summary_df)
    write_summary(counts_df, summary_df)

    print(f"Wrote feedback-change analysis for {summary_df['task_id'].nunique()} tasks to {OUT_DIR}")


if __name__ == "__main__":
    main()
