"""Nature-style figures for Sub-6 v2 + audit findings.

Outputs:
    data/paper_figures/fig1_cross_llm_distribution.{png,pdf}
    data/paper_figures/fig2_cascade_decomposition.{png,pdf}
    data/paper_figures/fig3_se_supported_3way.{png,pdf}
    data/paper_figures/fig4_per_layer_breakdown.{png,pdf}
    data/paper_figures/fig5_data_scale_v1_vs_v2.{png,pdf}

Style follows Nature template: Liberation Sans (Arial proxy), no top/right
spines, minimal grid, Nature-friendly palette (greys + 2 accents), single
column 89 mm or double column 183 mm widths.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Nature-style global parameters
# ---------------------------------------------------------------------------
mpl.rcParams.update({
    "font.family": "Liberation Sans",
    "font.size": 7,
    "axes.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.labelsize": 7,
    "axes.titlesize": 8,
    "axes.titleweight": "bold",
    "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "xtick.major.size": 2.5,
    "ytick.major.size": 2.5,
    "legend.fontsize": 6.5,
    "legend.frameon": False,
    "figure.dpi": 300,
    "savefig.dpi": 600,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

# Nature-friendly palette
COLOR_SUPPORTED   = "#4C9F70"   # green
COLOR_UNSUPPORTED = "#C0C0C0"   # grey
COLOR_CONTRADICTED = "#D62728"  # red
COLOR_UNVERIFIABLE = "#404040"  # dark grey

LLM_COLORS = {
    "MiniMax-M2.7": "#5B8FF9",
    "GPT-5.5":      "#F6BD16",
    "Opus-4-7":     "#A459D1",
}

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
OUT  = ROOT / "data/paper_figures"
OUT.mkdir(parents=True, exist_ok=True)

def load_summary(path: str) -> dict:
    return json.loads((ROOT / path).read_text())

S = {
    "sub6b_opus":    load_summary("results/v2/sub6b_opus/sub6b_v2_opus_verdicts_summary.json"),
    "sub6b_gpt55":   load_summary("results/v2/sub6b_gpt55/sub6b_v2_gpt55_verdicts_summary.json"),
    "sub6a_perfect": load_summary("results/v2/sub6a_perfect/sub6a_v2_perfect_verdicts_summary.json"),
    "sub6a_real":    load_summary("results/v2/sub6a_real/sub6a_v2_real_verdicts_summary.json"),
}

VERDICT_ORDER = ["supported", "unsupported", "contradicted", "unverifiable_v0"]
VERDICT_LABELS = ["Supported", "Unsupported", "Contradicted", "Unverifiable"]
VERDICT_COLORS = [COLOR_SUPPORTED, COLOR_UNSUPPORTED, COLOR_CONTRADICTED, COLOR_UNVERIFIABLE]


def stacked_bars(ax, labels: list[str], rates_list: list[list[float]],
                 totals: list[int]):
    """Plot stacked horizontal bars with verdict % stacks."""
    y = np.arange(len(labels))
    rates = np.array(rates_list) * 100  # to percent
    left = np.zeros(len(labels))
    for i, (color, vlabel) in enumerate(zip(VERDICT_COLORS, VERDICT_LABELS)):
        ax.barh(y, rates[:, i], left=left, color=color, edgecolor="white",
                linewidth=0.4, label=vlabel, height=0.65)
        # in-bar percent annotation if segment is wide enough
        for j, r in enumerate(rates[:, i]):
            if r >= 5:
                ax.text(left[j] + r / 2, j, f"{r:.0f}%",
                        ha="center", va="center", color="white",
                        fontsize=5.5, fontweight="bold")
        left += rates[:, i]
    # totals on right
    for j, n in enumerate(totals):
        ax.text(102, j, f"n = {n:,}", ha="left", va="center", fontsize=6.0, color="#666")
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Verdict share (%)")
    ax.set_xticks([0, 25, 50, 75, 100])

# ---------------------------------------------------------------------------
# Figure 1 — Cross-LLM verdict distribution on Sub-6B
# ---------------------------------------------------------------------------
def fig1_cross_llm():
    fig, ax = plt.subplots(figsize=(89/25.4, 38/25.4))  # single column
    labels = ["GPT-5.5", "Claude Opus-4-7"]
    rates = [
        [S["sub6b_gpt55"]["verdict_rates"][k] for k in VERDICT_ORDER],
        [S["sub6b_opus"]["verdict_rates"][k]  for k in VERDICT_ORDER],
    ]
    totals = [S["sub6b_gpt55"]["total_claims"], S["sub6b_opus"]["total_claims"]]
    stacked_bars(ax, labels, rates, totals)
    ax.set_title("a  Verdict distribution by narrative LLM (Sub-6B, n = 63 tasks)", loc="left", pad=6)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.45), ncol=4, handlelength=1.2)
    plt.savefig(OUT / "fig1_cross_llm_distribution.png")
    plt.savefig(OUT / "fig1_cross_llm_distribution.pdf")
    plt.close()
    print("saved fig1_cross_llm_distribution")

# ---------------------------------------------------------------------------
# Figure 2 — Cascade decomposition (Opus, three tracks)
# ---------------------------------------------------------------------------
def fig2_cascade():
    fig, ax = plt.subplots(figsize=(89/25.4, 45/25.4))
    labels = [
        "Sub-6B\n(compound list)",
        "Sub-6A perfect-id\n(spectrum, oracle id)",
        "Sub-6A real-id\n(spectrum, library_search)",
    ]
    rates = [
        [S["sub6b_opus"]["verdict_rates"][k] for k in VERDICT_ORDER],
        [S["sub6a_perfect"]["verdict_rates"][k] for k in VERDICT_ORDER],
        [S["sub6a_real"]["verdict_rates"][k] for k in VERDICT_ORDER],
    ]
    totals = [S["sub6b_opus"]["total_claims"], S["sub6a_perfect"]["total_claims"], S["sub6a_real"]["total_claims"]]
    stacked_bars(ax, labels, rates, totals)
    ax.set_title("b  Cascade decomposition: compound list → spectrum end-to-end (Opus-4-7)",
                 loc="left", pad=6)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=4, handlelength=1.2)
    plt.savefig(OUT / "fig2_cascade_decomposition.png")
    plt.savefig(OUT / "fig2_cascade_decomposition.pdf")
    plt.close()
    print("saved fig2_cascade_decomposition")

# ---------------------------------------------------------------------------
# Figure 3 — Set-enrichment supported rate, 3-way audit (smoking gun)
# ---------------------------------------------------------------------------
def fig3_se_3way():
    """Audit + sanity 3-way control: same task set, swap LLM."""
    fig, ax = plt.subplots(figsize=(120/25.4, 65/25.4))  # widened
    # Data straight from audit reports
    bars = [
        ("v1\nMiniMax-M2.7\n(14 tasks)", "MiniMax-M2.7", 3, 28),
        ("v1-Opus\nClaude Opus-4-7\n(14 tasks)",  "Opus-4-7", 0, 25),
        ("v2\nClaude Opus-4-7\n(38 tasks)", "Opus-4-7", 1, 114),
    ]
    x = np.arange(len(bars))
    pcts = [(s/t)*100 for _,_,s,t in bars]
    counts = [f"{s}/{t}" for _,_,s,t in bars]
    colors = [LLM_COLORS[llm] for _,llm,_,_ in bars]

    ax.bar(x, pcts, color=colors, edgecolor="black", linewidth=0.5, width=0.55)
    ymax = max(pcts) * 1.5
    for xi, p, c in zip(x, pcts, counts):
        ax.text(xi, p + ymax*0.02, c, ha="center", va="bottom",
                fontsize=7, fontweight="bold", color="#222")

    ax.set_xticks(x)
    ax.set_xticklabels([b[0] for b in bars], fontsize=6.5)
    ax.set_ylabel("Set-enrichment Supported (%)")
    ax.set_ylim(0, ymax)
    ax.set_title("c  LLM-style sensitivity: same verifier, swap narrative LLM",
                 loc="left", pad=8)

    # Smoking-gun annotation positioned in upper-right, away from bars
    ax.text(0.98, 0.78,
            "Same 14 tasks · Same verifier code\n"
            "Only narrative LLM differs:\n"
            "MiniMax → Opus-4-7\n"
            "Supported: 3 → 0",
            ha="right", va="top", transform=ax.transAxes, fontsize=6.5,
            bbox=dict(boxstyle="round,pad=0.4", fc="#fff8d8",
                      ec="#888", lw=0.5))

    # Curved arrow from v1 to v1-Opus showing the swap effect
    ax.annotate("", xy=(0.95, 0.5), xytext=(0.05, 9.0),
                arrowprops=dict(arrowstyle="->", color="#666", lw=1.0,
                                connectionstyle="arc3,rad=-0.3"))

    plt.tight_layout()
    plt.savefig(OUT / "fig3_se_supported_3way.png")
    plt.savefig(OUT / "fig3_se_supported_3way.pdf")
    plt.close()
    print("saved fig3_se_supported_3way")

# ---------------------------------------------------------------------------
# Figure 4 — Per-layer verdict breakdown (4 layers × 2 LLMs, Sub-6B)
# ---------------------------------------------------------------------------
def fig4_per_layer():
    layers = [
        ("set_enrichment",       "Layer 6a · Set enrichment"),
        ("driver_metabolite",    "Layer 6b · Driver metabolite"),
        ("biological_claim",     "Layer 6c · Biological claim"),
        ("pathway_relationship", "Layer 6d · Pathway relationship"),
    ]
    fig, axes = plt.subplots(1, 4, figsize=(183/25.4, 60/25.4), sharey=True)

    for ax, (lkey, ltitle) in zip(axes, layers):
        opus_v = S["sub6b_opus"]["verdicts_by_type"].get(lkey, {})
        gpt_v  = S["sub6b_gpt55"]["verdicts_by_type"].get(lkey, {})
        opus_total = sum(opus_v.values()) or 1
        gpt_total  = sum(gpt_v.values()) or 1

        x = np.arange(len(VERDICT_ORDER))
        w = 0.4
        opus_pct = [opus_v.get(k, 0)/opus_total*100 for k in VERDICT_ORDER]
        gpt_pct  = [gpt_v.get(k, 0)/gpt_total*100  for k in VERDICT_ORDER]

        ax.bar(x - w/2, gpt_pct,  width=w, color=LLM_COLORS["GPT-5.5"],
               edgecolor="black", linewidth=0.4, label="GPT-5.5")
        ax.bar(x + w/2, opus_pct, width=w, color=LLM_COLORS["Opus-4-7"],
               edgecolor="black", linewidth=0.4, label="Opus-4-7")

        ax.set_xticks(x)
        ax.set_xticklabels(VERDICT_LABELS, rotation=30, ha="right")
        ax.set_title(ltitle, loc="left", fontsize=7, pad=4)
        # Move n labels to lower-left to avoid title collision
        ax.text(0.02, 0.96,
                f"n(GPT)={gpt_total}  n(Opus)={opus_total}",
                ha="left", va="top", transform=ax.transAxes, fontsize=5.5,
                color="#666")
        ax.set_ylim(0, 100)

    axes[0].set_ylabel("Verdict share (%)")
    # Single legend below figure
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2,
               bbox_to_anchor=(0.5, -0.02), fontsize=7, handlelength=1.2)
    fig.suptitle("d  Per-layer verdict breakdown across narrative LLMs (Sub-6B)",
                 x=0.005, y=1.01, ha="left", fontweight="bold", fontsize=8)
    plt.tight_layout()
    plt.subplots_adjust(top=0.85, bottom=0.20)
    plt.savefig(OUT / "fig4_per_layer_breakdown.png")
    plt.savefig(OUT / "fig4_per_layer_breakdown.pdf")
    plt.close()
    print("saved fig4_per_layer_breakdown")

# ---------------------------------------------------------------------------
# Figure 5 — Data scale v1 → v2
# ---------------------------------------------------------------------------
def fig5_scale():
    fig, ax = plt.subplots(figsize=(120/25.4, 60/25.4))  # widened
    metrics = [
        ("Sub-6B tasks", 20, 63),
        ("Sub-6A tasks", 14, 38),
        ("Pathways covered", 7, 13),
        ("HMDB compounds", 150, 250),
        ("Sub-6A spectra", 128, 459),
        ("Total verdicts", 1800, 10042),
    ]
    y = np.arange(len(metrics))
    v1 = [m[1] for m in metrics]
    v2 = [m[2] for m in metrics]
    h = 0.35
    ax.barh(y - h/2, v1, h, color="#C0C0C0", edgecolor="black", linewidth=0.4, label="v1")
    ax.barh(y + h/2, v2, h, color="#404040", edgecolor="black", linewidth=0.4, label="v2")
    for i, (n, a, b) in enumerate(metrics):
        delta = (b - a) / a * 100 if a > 0 else 0
        # Show absolute v2 value AND delta, with extra padding
        ax.text(b * 1.15, i + h/2, f"  {b:,}  (+{delta:.0f}%)",
                va="center", fontsize=6.0,
                color="#4C9F70", fontweight="bold")
    ax.set_yticks(y)
    ax.set_yticklabels([m[0] for m in metrics])
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("Count (log scale)")
    ax.set_title("e  Benchmark scale: v1 → v2 expansion", loc="left", pad=6)
    ax.legend(loc="lower right", bbox_to_anchor=(0.98, 0.05))
    ax.set_xlim(5, 100000)  # widened to fit annotations
    plt.tight_layout()
    plt.savefig(OUT / "fig5_data_scale_v1_vs_v2.png")
    plt.savefig(OUT / "fig5_data_scale_v1_vs_v2.pdf")
    plt.close()
    print("saved fig5_data_scale_v1_vs_v2")


if __name__ == "__main__":
    fig1_cross_llm()
    fig2_cascade()
    fig3_se_3way()
    fig4_per_layer()
    fig5_scale()
    print(f"\nAll figures written to {OUT}/")
