"""Nature-style system architecture flowchart for MetAgent — v2 cleaner layout."""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

mpl.rcParams.update({
    "font.family": "Liberation Sans",
    "font.size": 7,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "figure.dpi": 300,
    "savefig.dpi": 600,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
})

COLOR_INPUT  = "#E8E8E8"
COLOR_STAGE1 = "#D4E4F7"
COLOR_STAGE2 = "#FFE9C7"
COLOR_STAGE3 = "#E5D9F2"
COLOR_OUTPUT = "#D8F0DC"
COLOR_ACCENT = "#404040"

LLM_COLORS = {
    "Opus-4-7":     "#A459D1",
    "GPT-5.5":      "#F6BD16",
    "MiniMax-M2.7": "#5B8FF9",
}

ROOT = Path(__file__).resolve().parents[2]
OUT  = ROOT / "data/paper_figures"
OUT.mkdir(parents=True, exist_ok=True)


def rbox(ax, x, y, w, h, text, fc="white", ec=COLOR_ACCENT,
         fontsize=6.5, weight="normal", lw=0.6):
    box = FancyBboxPatch((x, y), w, h,
        boxstyle="round,pad=0.01,rounding_size=0.06",
        linewidth=lw, edgecolor=ec, facecolor=fc, zorder=2)
    ax.add_patch(box)
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            fontsize=fontsize, fontweight=weight, color=COLOR_ACCENT,
            linespacing=1.15, zorder=3)


def stage_band(ax, x, y, w, h, label, color):
    band = patches.Rectangle((x, y), w, h, linewidth=0,
                             facecolor=color, alpha=0.45, zorder=0)
    ax.add_patch(band)
    ax.text(x + 0.12, y + h - 0.18, label, ha="left", va="top",
            fontsize=8, fontweight="bold", color="#222", zorder=1)


def arrow(ax, x1, y1, x2, y2, lw=0.8, rad=0, color=COLOR_ACCENT):
    a = FancyArrowPatch((x1, y1), (x2, y2),
        arrowstyle="-|>", mutation_scale=8,
        linewidth=lw, color=color,
        connectionstyle=f"arc3,rad={rad}", zorder=4)
    ax.add_patch(a)


def render():
    # Taller canvas, vertical breathing room
    fig, ax = plt.subplots(figsize=(190/25.4, 200/25.4))
    ax.set_xlim(0, 19)
    ax.set_ylim(0, 20)
    ax.axis("off")

    # ============== Title (above all bands) ==============
    ax.text(0.0, 19.6,
            "MetAgent: a 3-stage LLM + multi-agent framework for "
            "metabolomics with claim-level verification",
            fontsize=10, fontweight="bold", color="#111")

    # ============== Stage bands ==============
    stage_band(ax, 0.2, 14.4, 18.6, 4.7,
               "a   Stage 1: Spectrum -> Compound identification (Sub-6A only)",
               COLOR_STAGE1)
    stage_band(ax, 0.2, 9.6, 18.6, 4.4,
               "b   Stage 2: Narrative generation (cross-LLM)",
               COLOR_STAGE2)
    stage_band(ax, 0.2, 0.4, 18.6, 8.8,
               "c   Stage 3: Verifier cascade (4 stages, 10 layers)",
               COLOR_STAGE3)

    # ============== Inputs (left side) ==============
    rbox(ax, 0.5, 16.7, 2.0, 1.0,
         "Spectrum\n(m/z, peaks)\nSub-6A: 38",
         fc=COLOR_INPUT, weight="bold", fontsize=6.5)
    rbox(ax, 0.5, 14.85, 2.0, 1.0,
         "Compound list\n(KEGG IDs)\nSub-6B: 63",
         fc=COLOR_INPUT, weight="bold", fontsize=6.5)

    # ============== Stage 1 pipeline ==============
    pipeline = [
        (3.0,  16.7, 2.05, 1.0, "Candidate\nprefilter",   "GNPS + PubChem-Lite\n5 ppm window"),
        (5.4,  16.7, 2.05, 1.0, "Library\nsearch",        "Modified Cosine\n+ MS-CLIP"),
        (7.8,  16.7, 2.05, 1.0, "Molecule\ngenerate",     "SIRIUS fingerprint\n-> MS-BART"),
        (10.2, 16.7, 2.05, 1.0, "Merge\n+ dedupe",        "Canonical SMILES"),
        (12.6, 16.7, 2.05, 1.0, "Per-candidate\nenrichment", "HMDB / RaMP /\nCFM-ID predict"),
        (15.0, 16.7, 2.05, 1.0, "Evidence\nscore + sort", "Linear combo, T=0"),
    ]
    for x, y, w, h, top, bot in pipeline:
        rbox(ax, x, y, w, h, top, fc="white", weight="bold", fontsize=6.5)
        ax.text(x + w/2, y - 0.18, bot, ha="center", va="top",
                fontsize=5.4, color="#666", style="italic", linespacing=1.15)

    # Arrows: input -> first box, then chained
    arrow(ax, 2.5, 17.2, 3.0, 17.2)
    for i in range(len(pipeline) - 1):
        x1 = pipeline[i][0] + pipeline[i][2]
        x2 = pipeline[i+1][0]
        y  = pipeline[i][1] + pipeline[i][3] / 2
        arrow(ax, x1, y, x2, y)

    # IdentificationReport box at right end of Stage 1
    rbox(ax, 15.4, 14.85, 3.0, 0.85,
         "IdentificationReport (JSON)",
         fc=COLOR_INPUT, weight="bold", fontsize=6.5)
    arrow(ax, 16.0, 16.7, 16.0, 15.7)

    # ============== Stage 2: Narrative ==============
    # Compound list shortcut to formatter (now starts from input row, curves down)
    arrow(ax, 1.5, 14.85, 1.5, 13.4, rad=0)
    ax.text(1.65, 14.05, "Sub-6B path\n(skips Stage 1)",
            ha="left", va="center", fontsize=5.5, color="#555", style="italic")

    # Formatter box (centered)
    rbox(ax, 7.0, 13.0, 4.0, 0.85,
         "format_report_for_llm()",
         fc="white", weight="bold", fontsize=7)

    # Arrows from IdReport and Compound list to formatter
    arrow(ax, 16.0, 14.85, 11.0, 13.4, rad=-0.1)
    arrow(ax, 1.5, 13.4, 7.0, 13.4, rad=0)

    # 3 LLM choices side-by-side (status moved INSIDE the box)
    llms = [
        (3.5,  11.0, 3.0, 1.0, "Claude Opus-4-7\n(run, n=63)", "Opus-4-7"),
        (7.5,  11.0, 3.0, 1.0, "GPT-5.5\n(run, n=63)",         "GPT-5.5"),
        (11.5, 11.0, 3.0, 1.0, "MiniMax-M2.7\n(pending)",       "MiniMax-M2.7"),
    ]
    for x, y, w, h, name, key in llms:
        rbox(ax, x, y, w, h, name, fc=LLM_COLORS[key],
             weight="bold", fontsize=7.5, ec="black")

    # Branching arrows from formatter to LLMs
    for x, y, w, h, _, _ in llms:
        arrow(ax, 9.0, 13.0, x + w/2, y + h, rad=0, lw=0.6)

    # Converged narrative output
    rbox(ax, 6.0, 9.85, 6.0, 0.7,
         "Natural-language enrichment narrative",
         fc="white", weight="bold", fontsize=7)
    for x, y, w, h, _, _ in llms:
        arrow(ax, x + w/2, y, 9.0, 10.55, rad=0, lw=0.5)

    # Down to Stage 3
    arrow(ax, 9.0, 9.85, 9.0, 8.9, lw=1.2)

    # ============== Stage 3: Verifier cascade ==============
    cascade = [
        (1.3,  7.7, 3.5, 0.8, "1. Extract claims",    "LLM #1 (Opus-4-7)"),
        (5.3,  7.7, 3.5, 0.8, "2. Classify type",     "Rules 80% + LLM #2"),
        (9.3,  7.7, 3.5, 0.8, "3. Per-claim verify",  "Routes to layers below"),
        (13.3, 7.7, 4.5, 0.8, "4. Rewrite + re-verify", "If contradictions found"),
    ]
    for x, y, w, h, top, bot in cascade:
        rbox(ax, x, y, w, h, top, fc="white", weight="bold", fontsize=7)
        ax.text(x + w/2, y - 0.18, bot, ha="center", va="top",
                fontsize=5.5, color="#666", style="italic")
    for i in range(len(cascade) - 1):
        x1 = cascade[i][0] + cascade[i][2]
        x2 = cascade[i+1][0]
        y  = cascade[i][1] + cascade[i][3]/2
        arrow(ax, x1, y, x2, y)

    # Arrow from cascade step 3 down to layer panel
    arrow(ax, 11.05, 7.7, 11.05, 6.95, lw=0.8)

    # Section header for layers
    ax.text(0.5, 6.95, "10 verifier layers (each routes one claim type)",
            fontsize=7, fontweight="bold", color="#333", style="italic")

    # Two columns of 5 layers each
    col1 = [
        ("Layer A",  "Grounded",            "IdReport fields"),
        ("Layer B",  "Factual",             "HMDB / KEGG"),
        ("Layer C",  "Biological",          "RaMP pathways"),
        ("Layer D",  "Consistency",         "LLM cross-claim"),
        ("Layer E",  "Literature",          "Europe PMC"),
    ]
    col2 = [
        ("Layer F",  "Peak mechanistic",    "SIRIUS + CFM-ID"),
        ("Layer 6a", "Set enrichment",      "RaMP top-3 lookup"),
        ("Layer 6b", "Driver metabolite",   "Ground truth signals"),
        ("Layer 6c", "Biological (Sub-6)",  "RaMP, no IdReport"),
        ("Layer 6d", "Pathway relationship","KEGG graph BFS<=6"),
    ]

    layer_w = 4.5
    layer_h = 0.5
    y_top   = 6.4
    y_step  = 0.65

    for i, (lk, ln, src) in enumerate(col1):
        x = 0.5
        y = y_top - i * y_step
        rbox(ax, x, y, layer_w, layer_h, f"{lk}  ·  {ln}",
             fc="white", fontsize=6.2, weight="bold", lw=0.5)
        ax.text(x + layer_w + 0.1, y + layer_h/2,
                f"<- {src}", ha="left", va="center",
                fontsize=5.5, color="#666", style="italic")
    for i, (lk, ln, src) in enumerate(col2):
        x = 9.8
        y = y_top - i * y_step
        rbox(ax, x, y, layer_w, layer_h, f"{lk}  ·  {ln}",
             fc="white", fontsize=6.2, weight="bold", lw=0.5)
        ax.text(x + layer_w + 0.1, y + layer_h/2,
                f"<- {src}", ha="left", va="center",
                fontsize=5.5, color="#666", style="italic")

    # ============== Output box (bottom center) ==============
    rbox(ax, 6.0, 0.7, 7.0, 1.6,
         "Output: VerifiedIdentification\n\n"
         "verdict in {SUPPORTED, UNSUPPORTED, CONTRADICTED, UNVERIFIABLE_v0}\n"
         "+ evidence, source, layer used",
         fc=COLOR_OUTPUT, weight="bold", fontsize=7)

    # Arrow from cascade step 4 to output
    arrow(ax, 15.5, 7.7, 13.0, 2.3, rad=-0.25, lw=1.0)

    plt.savefig(OUT / "fig6_architecture.png")
    plt.savefig(OUT / "fig6_architecture.pdf")
    plt.close()
    print(f"saved {OUT / 'fig6_architecture.png'}")


if __name__ == "__main__":
    render()
