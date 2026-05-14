#!/usr/bin/env python3
"""Render a one-page MetAgent case-study figure."""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


REPO_ROOT = Path(__file__).resolve().parents[4]
TASK_ID = "compound_only_enrich_mammalian_RAMP_P_000000016_seed1"
TASKS_PATH = REPO_ROOT / "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl"
RESULT_PATH = REPO_ROOT / "data/eval/sub6/v4_a3_d3_with_lit/feedback" / TASK_ID / "result.json"
VERDICT_PATH = REPO_ROOT / "data/eval/sub6/v4_a3_d3_with_lit/feedback" / TASK_ID / "verdict.json"
OUT_DIR = REPO_ROOT / "paper_docs/stage2/minimax/claims/case_study"


PALETTE = {
    "ink": "#16202A",
    "muted": "#5B6777",
    "line": "#D8E1EA",
    "panel": "#F7FAFC",
    "input": "#EAF2FB",
    "signal": "#DDF3E8",
    "noise": "#F3F5F8",
    "accent": "#0F766E",
    "blue": "#2563EB",
    "orange": "#D97706",
    "red": "#B91C1C",
    "gray": "#64748B",
    "supported_bg": "#E8F6EF",
    "unsupported_bg": "#FFF7ED",
    "contradicted_bg": "#FEF2F2",
    "unverifiable_bg": "#F1F5F9",
}

VERDICT_STYLE = {
    "supported": ("supported", PALETTE["accent"], PALETTE["supported_bg"], "#9BD3B8"),
    "unsupported": ("unsupported", PALETTE["orange"], PALETTE["unsupported_bg"], "#FDBA74"),
    "contradicted": ("contradicted", PALETTE["red"], PALETTE["contradicted_bg"], "#FCA5A5"),
    "unverifiable_v0": ("unverifiable_v0", PALETTE["gray"], PALETTE["unverifiable_bg"], "#CBD5E1"),
}

VERDICT_PRIORITY = {
    "contradicted": 4,
    "unsupported": 3,
    "supported": 2,
    "unverifiable_v0": 1,
}


def load_task() -> dict:
    with TASKS_PATH.open() as f:
        for line in f:
            task = json.loads(line)
            if task["task_id"] == TASK_ID:
                return task
    raise SystemExit(f"task not found: {TASK_ID}")


def clean_markup(text: str) -> str:
    text = text.replace("**", "")
    text = text.replace("##", "")
    text = text.replace("###", "")
    text = text.replace("≈", "~")
    text = text.replace("—", "-")
    text = text.replace("→", "->")
    text = text.replace("β", "beta")
    text = text.replace("₄", "4")
    text = text.replace("⁺", "+")
    text = text.replace("覆盖面", " coverage")
    text = text.replace("`query_pathway_membership`", "pathway membership evidence")
    return text


def normalize(text: str) -> str:
    text = clean_markup(text).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if len(t) > 2}


def claim_match_texts(claim: dict) -> list[str]:
    texts = [claim.get("claim_text") or ""]
    evidence = claim.get("evidence") or ""
    if claim.get("verdict") == "contradicted" and "Cited claim texts:" in evidence:
        texts.extend(re.findall(r'"([^"]+)"', evidence))
    return [text for text in texts if normalize(text)]


def split_report(text: str) -> list[str]:
    text = clean_markup(text)
    text = re.sub(r"\n+", "\n", text).strip()
    units: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if paragraph.endswith(":") or len(paragraph) < 32:
            units.append(paragraph)
            continue
        parts = re.split(r"(?<=[.!?])\s+", paragraph)
        units.extend(part.strip() for part in parts if part.strip())
        units.append("")
    return units[:-1] if units and units[-1] == "" else units


def sentence_verdict(sentence: str, claims: list[dict]) -> str | None:
    if not sentence.strip():
        return None
    sentence_norm = normalize(sentence)
    sentence_tokens = tokens(sentence)
    best_verdict = None
    best_score = 0.0
    best_priority = 0
    for claim in claims:
        for claim_text in claim_match_texts(claim):
            claim_norm = normalize(claim_text)
            if not claim_norm:
                continue
            if claim_norm in sentence_norm or sentence_norm in claim_norm:
                score = 1.0
            else:
                claim_tokens = tokens(claim_text)
                if not claim_tokens:
                    continue
                overlap = len(sentence_tokens & claim_tokens) / len(claim_tokens)
                score = overlap
            verdict = claim.get("verdict")
            priority = VERDICT_PRIORITY.get(verdict or "", 0)
            if score >= 0.42 and (
                priority > best_priority
                or (priority == best_priority and score > best_score)
            ):
                best_verdict = verdict
                best_score = score
                best_priority = priority
    return best_verdict


def rounded_box(ax, xy, wh, fc, ec="#CBD5E1", lw=1.0, radius=0.03, zorder=1):
    x, y = xy
    w, h = wh
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def add_wrapped(
    ax,
    x,
    y,
    text,
    width=44,
    size=9,
    color=None,
    weight=None,
    va="top",
    ha="left",
    lineheight=1.18,
):
    color = color or PALETTE["ink"]
    wrapped = "\n".join(textwrap.wrap(text, width=width, break_long_words=False))
    ax.text(
        x,
        y,
        wrapped,
        fontsize=size,
        color=color,
        weight=weight,
        va=va,
        ha=ha,
        linespacing=lineheight,
        family="DejaVu Sans",
    )


def arrow(ax, start, end, color="#64748B", lw=1.5, rad=0.0):
    arr = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=lw,
        color=color,
        connectionstyle=f"arc3,rad={rad}",
    )
    ax.add_patch(arr)


def draw_chip(ax, x, y, text, fc, ec, color, w=0.11):
    rounded_box(ax, (x, y), (w, 0.032), fc, ec=ec, radius=0.012)
    ax.text(x + w / 2, y + 0.016, text, fontsize=7.5, color=color, ha="center", va="center", weight="bold")


def draw_report(ax, result: dict, verdict: dict) -> int:
    claims = verdict.get("claims") or []
    report = result.get("final_narrative") or ""
    units = split_report(report)

    x0, y0, w, h = 0.41, 0.075, 0.555, 0.82
    rounded_box(ax, (x0, y0), (w, h), PALETTE["panel"], ec="#CBD5E1", radius=0.018)
    ax.text(x0 + 0.02, y0 + h - 0.035, "Final MetAgent report", fontsize=14, weight="bold", color=PALETTE["ink"])
    ax.text(x0 + 0.02, y0 + h - 0.064, "Verifier-colored complete narrative", fontsize=9.2, color=PALETTE["muted"])

    legend_x = x0 + 0.02
    for verdict_name in ["supported", "unsupported", "contradicted", "unverifiable_v0"]:
        label, color, bg, edge = VERDICT_STYLE[verdict_name]
        chip_w = 0.086 if verdict_name != "unverifiable_v0" else 0.118
        draw_chip(ax, legend_x, y0 + h - 0.112, label, bg, edge, color, w=chip_w)
        legend_x += chip_w + 0.012

    line_y = y0 + h - 0.155
    line_h = 0.0129
    max_y = y0 + 0.026
    rendered_lines = 0
    wrap_width = 124

    for unit in units:
        if unit == "":
            line_y -= line_h * 0.52
            continue
        verdict_name = sentence_verdict(unit, claims)
        color = VERDICT_STYLE.get(verdict_name, ("", PALETTE["ink"], "", ""))[1] if verdict_name else PALETTE["ink"]
        weight = "bold" if unit in {"Revised Narrative", "Limitations:"} else None
        wrapped = textwrap.wrap(unit, width=wrap_width, break_long_words=False) or [unit]
        for line in wrapped:
            if line_y < max_y:
                return rendered_lines
            ax.text(
                x0 + 0.02,
                line_y,
                line,
                fontsize=5.85,
                color=color,
                weight=weight,
                va="top",
                family="DejaVu Sans",
            )
            rendered_lines += 1
            line_y -= line_h
        line_y -= line_h * 0.23
    return rendered_lines


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    task = load_task()
    result = json.loads(RESULT_PATH.read_text())
    verdict = json.loads(VERDICT_PATH.read_text())

    metabolites = task.get("differential_metabolites") or []
    top_pathway = (task.get("ramp_enrichment_result") or {}).get("top_pathways", [])[0]
    matched_ids = set(top_pathway.get("matched_compounds") or [])
    matched = [m for m in metabolites if m.get("kegg_id") in matched_ids]
    other = [m for m in metabolites if m.get("kegg_id") not in matched_ids]
    vt = verdict.get("verdicts_total") or {}

    fig = plt.figure(figsize=(14.2, 9.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.04, 0.955, "MetAgent case study", fontsize=20, weight="bold", color=PALETTE["ink"], va="top")
    ax.text(
        0.04,
        0.914,
        "Input metabolite set -> pathway evidence -> final metabolic interpretation",
        fontsize=11,
        color=PALETTE["muted"],
        va="top",
    )
    ax.text(0.96, 0.948, TASK_ID, fontsize=8.2, color=PALETTE["muted"], ha="right", va="top")

    rounded_box(ax, (0.035, 0.075), (0.33, 0.82), PALETTE["panel"], ec="#CBD5E1", radius=0.018)
    ax.text(0.055, 0.86, "Input", fontsize=14, weight="bold", color=PALETTE["ink"])
    ax.text(0.055, 0.83, f"Differential metabolites (n={len(metabolites)})", fontsize=10, color=PALETTE["muted"])

    y = 0.79
    for m in matched:
        name = m["name"]
        kid = m.get("kegg_id") or ""
        formula = m.get("molecular_formula") or ""
        rounded_box(ax, (0.055, y - 0.032), (0.275, 0.038), PALETTE["signal"], ec="#A7D8C0", radius=0.014)
        ax.text(0.068, y - 0.011, name, fontsize=9.0, weight="bold", color=PALETTE["ink"], va="center")
        ax.text(0.322, y - 0.011, kid, fontsize=7.8, color=PALETTE["muted"], va="center", ha="right")
        ax.text(0.068, y - 0.027, formula, fontsize=7.2, color=PALETTE["muted"], va="center")
        y -= 0.047

    if other:
        ax.text(0.055, y - 0.004, "Other differential metabolites", fontsize=9, color=PALETTE["muted"], weight="bold")
        other_text = ", ".join(f"{m['name']} ({m.get('kegg_id') or 'NA'})" for m in other)
        add_wrapped(ax, 0.055, y - 0.032, other_text, width=48, size=8.0, color=PALETTE["ink"], lineheight=1.08)

    rounded_box(ax, (0.055, 0.265), (0.275, 0.12), "#E6F2FA", ec="#9ECAE1", radius=0.014)
    ax.text(0.072, 0.352, "Top pathway", fontsize=9.6, weight="bold", color=PALETTE["blue"])
    ax.text(0.072, 0.325, top_pathway["pathway_name"], fontsize=13.0, weight="bold", color=PALETTE["ink"])
    ax.text(
        0.072,
        0.300,
        f"{top_pathway['pathway_source'].upper()} {top_pathway['pathway_external_id']} | FDR={top_pathway['fdr']:.2e}",
        fontsize=8.2,
        color=PALETTE["muted"],
    )
    ax.text(
        0.072,
        0.280,
        f"fold-enrichment={top_pathway['fold_enrichment']:.1f} | matched {len(matched)}/{len(metabolites)}",
        fontsize=8.2,
        color=PALETTE["muted"],
    )

    rounded_box(ax, (0.055, 0.125), (0.275, 0.085), "#EEF7F4", ec="#B9DED2", radius=0.014)
    ax.text(0.072, 0.185, "Final verifier totals", fontsize=9.2, weight="bold", color=PALETTE["accent"])
    ax.text(
        0.072,
        0.159,
        f"supported {vt.get('supported', 0)} | unsupported {vt.get('unsupported', 0)} | contradicted {vt.get('contradicted', 0)}",
        fontsize=8.0,
        color=PALETTE["ink"],
    )
    ax.text(0.072, 0.139, f"unverifiable_v0 {vt.get('unverifiable_v0', 0)}", fontsize=8.0, color=PALETTE["ink"])

    rendered_lines = draw_report(ax, result, verdict)
    arrow(ax, (0.368, 0.49), (0.405, 0.49), color="#94A3B8", lw=2.0)

    out_stem = "metagent_case_glycine_serine_threonine_colored_report"
    fig.savefig(OUT_DIR / f"{out_stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{out_stem}.pdf", bbox_inches="tight")
    plt.close(fig)

    summary = {
        "task_id": TASK_ID,
        "ground_truth_pathway": task.get("ground_truth_pathway"),
        "top_pathway": top_pathway,
        "matched_metabolites": [m["name"] for m in matched],
        "other_metabolites": [m["name"] for m in other],
        "final_iter_idx": result.get("final_iter_idx"),
        "verdicts_total": vt,
        "rendered_report_lines": rendered_lines,
        "output_stem": out_stem,
    }
    (OUT_DIR / f"{out_stem}_summary.json").write_text(json.dumps(summary, indent=2))
    (OUT_DIR / "README.md").write_text(
        "# MetAgent Case Study Figure\n\n"
        f"Task: `{TASK_ID}`\n\n"
        "This updated case uses the Glycine, serine and threonine metabolism task. The final verifier output "
        "contains supported, unsupported, contradicted, and unverifiable claims, so all "
        "verdict colors are visible in the continuous report panel.\n\n"
        "Files:\n"
        f"- `{out_stem}.png`\n"
        f"- `{out_stem}.pdf`\n"
        f"- `{out_stem}_summary.json`\n"
    )
    print(f"Wrote case-study figure to {OUT_DIR / (out_stem + '.png')}")


if __name__ == "__main__":
    main()
