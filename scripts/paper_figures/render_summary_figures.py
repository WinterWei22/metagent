"""Generate summary report-specific figures for May_7 stage report.

Outputs to summary/May_7/figures/:
    fig_id_per_task_distribution.png        - Sub-6A top-1 accuracy distribution
    fig_id_per_task_histogram.png           - per-task accuracy histogram
    fig_e2e_case_pipeline.png               - end-to-end case study visual
    fig_metric_explainer.png                - 4 verdict types + interpretation
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

mpl.rcParams.update({
    "font.family": "Liberation Sans",
    "font.size": 8,
    "axes.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.labelsize": 8,
    "axes.titlesize": 9,
    "axes.titleweight": "bold",
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "pdf.fonttype": 42,
    "savefig.dpi": 600,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
})

ROOT = Path(__file__).resolve().parents[2]
OUT  = ROOT / "summary/May_7/figures"
OUT.mkdir(parents=True, exist_ok=True)

C_GREEN = "#4C9F70"
C_RED   = "#D62728"
C_GREY  = "#808080"
C_DGREY = "#404040"
C_BLUE  = "#5B8FF9"
C_ORANGE = "#F59B49"


# =====================================================================
# Figure: Sub-6A identification per-task accuracy distribution
# =====================================================================
def fig_id_per_task():
    data = []
    with open(ROOT / "data/eval/sub6/v2/sub6a_real/sub6a_narratives.jsonl") as f:
        for line in f:
            data.append(json.loads(line))
    accs = sorted([d["identification_accuracy"]*100 for d in data])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(180/25.4, 65/25.4))

    # Left: histogram
    ax1.hist(accs, bins=10, color=C_BLUE, edgecolor="black", linewidth=0.5)
    ax1.axvline(np.mean(accs), color=C_RED, linestyle="--", linewidth=1.0,
                label=f"mean = {np.mean(accs):.1f}%")
    ax1.axvline(np.median(accs), color=C_DGREY, linestyle=":", linewidth=1.0,
                label=f"median = {np.median(accs):.1f}%")
    ax1.set_xlabel("Per-task top-1 identification accuracy (%)")
    ax1.set_ylabel("Number of tasks")
    ax1.set_title("a   Per-task identification accuracy distribution\n      (Sub-6A real-id v2, n=38 tasks, 459 spectra)",
                  loc="left")
    ax1.legend()

    # Right: cumulative
    n = len(accs)
    cum_pct = np.arange(1, n+1) / n * 100
    ax2.plot(accs, cum_pct, color=C_DGREY, linewidth=1.5)
    ax2.fill_between(accs, 0, cum_pct, alpha=0.15, color=C_BLUE)
    ax2.scatter(accs, cum_pct, color=C_BLUE, s=10, zorder=3)
    # Mark key thresholds
    for thresh, label in [(50, "≥50%"), (75, "≥75%"), (100, "100%")]:
        n_above = sum(1 for a in accs if a >= thresh)
        ax2.axvline(thresh, color=C_RED, linestyle=":", linewidth=0.7, alpha=0.5)
        ax2.text(thresh, 95, f" {label}: {n_above}/{n}", fontsize=6.5, color=C_RED,
                 ha="left")
    ax2.set_xlabel("Per-task top-1 accuracy threshold (%)")
    ax2.set_ylabel("Cumulative tasks (%)")
    ax2.set_title("b   Cumulative task distribution\n      (84% of tasks ≥50% accuracy; no tasks at 0%)",
                  loc="left")
    ax2.set_xlim(0, 105)
    ax2.set_ylim(0, 105)

    plt.tight_layout()
    plt.savefig(OUT / "fig_id_per_task_distribution.png")
    plt.savefig(OUT / "fig_id_per_task_distribution.pdf")
    plt.close()
    print("saved fig_id_per_task_distribution")


# =====================================================================
# Figure: Verdict explainer (what each verdict means)
# =====================================================================
def fig_metric_explainer():
    fig, ax = plt.subplots(figsize=(180/25.4, 75/25.4))
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 9)
    ax.axis("off")

    ax.text(0, 8.6, "What each verdict means",
            fontsize=10, fontweight="bold", color="#222")

    rows = [
        ("SUPPORTED",      C_GREEN,  "LLM claim matches evidence in RaMP / KEGG / HMDB / SIRIUS",
         "Higher = LLM in agreement with verifier evidence sources"),
        ("UNSUPPORTED",    C_GREY,   "Evidence DB has no record matching the claim — could be missing or wrong",
         "Conservative: doesn't say wrong, just no positive evidence"),
        ("CONTRADICTED",   C_RED,    "Evidence DB returns OPPOSING information (e.g. compound is in different pathway)",
         "Higher = more LLM hallucinations caught by verifier"),
        ("UNVERIFIABLE_v0",C_DGREY,  "Claim is out of v0 verifier scope (free-text biology, mechanism, etc.)",
         "Higher = LLM writes more functional / mechanistic narrative; verifier limitation"),
    ]

    y_top = 7.5
    h = 1.6
    for i, (name, color, what, interpret) in enumerate(rows):
        y = y_top - i * (h + 0.2)
        # Color block
        box = FancyBboxPatch((0.2, y - h + 0.1), 2.5, h - 0.2,
            boxstyle="round,pad=0.01,rounding_size=0.05",
            linewidth=0.6, edgecolor="black", facecolor=color)
        ax.add_patch(box)
        ax.text(1.45, y - h/2 + 0.05, name, ha="center", va="center",
                fontsize=8, fontweight="bold", color="white")
        # What it means
        ax.text(3.0, y - 0.25, "Definition:", fontsize=7.5, fontweight="bold",
                color="#333")
        ax.text(3.0, y - 0.65, what, fontsize=7.5, color="#222", wrap=True)
        # Interpretation
        ax.text(3.0, y - 1.05, "Interpretation:", fontsize=7.5, fontweight="bold",
                color="#333", style="italic")
        ax.text(3.0, y - 1.45, interpret, fontsize=7.5, color="#444",
                style="italic", wrap=True)

    plt.savefig(OUT / "fig_metric_explainer.png")
    plt.savefig(OUT / "fig_metric_explainer.pdf")
    plt.close()
    print("saved fig_metric_explainer")


# =====================================================================
# Figure: End-to-end case study
# =====================================================================
def _wrap(text, width):
    """Simple word-wrap that preserves manual newlines."""
    out = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        words = para.split()
        line = ""
        for w in words:
            if len(line) + len(w) + 1 <= width:
                line = (line + " " + w).strip()
            else:
                out.append(line)
                line = w
        if line:
            out.append(line)
    return "\n".join(out)


def fig_e2e_case():
    """End-to-end case study figure — Nature poster style with proper spacing."""
    case = json.loads((ROOT / "summary/May_7/end_to_end_case.json").read_text())
    mets = case["input"]["differential_metabolites"]
    gt_signals = set(case["input"]["ground_truth_signal_compounds"] or [])
    gt = case["input"]["ground_truth_pathway"]
    n_total_claims = sum(case["verdicts"]["totals"].values())

    # Tall canvas with generous spacing
    fig = plt.figure(figsize=(190/25.4, 260/25.4))
    gs = fig.add_gridspec(
        5, 1,
        height_ratios=[0.5, 2.4, 4.0, 1.0, 5.0],
        hspace=0.40,
        left=0.04, right=0.97, top=0.97, bottom=0.02,
    )

    # ============ Panel 0: Title strip ============
    ax = fig.add_subplot(gs[0])
    ax.axis("off")
    ax.text(0, 0.85,
            f"End-to-end case study: {case['task_id']}",
            fontsize=10, fontweight="bold", color="#111",
            transform=ax.transAxes)
    ax.text(0, 0.30,
            f"Ground truth pathway: {gt['pathway_name']}  "
            f"({gt['pathway_source']} · {gt['external_id']})  "
            f"|  {len(mets)} input metabolites  ({len(gt_signals)} signal + {len(mets)-len(gt_signals)} noise)  "
            f"|  {n_total_claims} extracted claims",
            fontsize=8, color="#444", transform=ax.transAxes)

    # ============ Panel A: Input table ============
    ax = fig.add_subplot(gs[1])
    ax.axis("off")
    ax.text(0, 1.0,
            "a   Input differential metabolites",
            fontsize=10, fontweight="bold", color="#111",
            transform=ax.transAxes)

    cell_text = []
    cell_colors = []
    for m in mets:
        kegg = m.get("kegg_id") or "-"
        is_signal = kegg in gt_signals
        marker = "[GT signal]" if is_signal else " "
        cell_text.append([
            marker,
            m["name"],
            kegg,
            m.get("compound_class", "-"),
        ])
        # row color
        bg = "#E8F5E9" if is_signal else "white"
        cell_colors.append([bg]*4)

    table = ax.table(
        cellText=cell_text,
        colLabels=["Status", "Compound name", "KEGG ID", "Bucket"],
        cellColours=cell_colors,
        loc="center", cellLoc="left", colLoc="left",
        colWidths=[0.13, 0.40, 0.15, 0.32],
        bbox=[0, 0.05, 1, 0.85],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    for (r, c), cell in table.get_celld().items():
        cell.set_linewidth(0.5)
        cell.set_height(0.10)
        if r == 0:
            cell.set_facecolor("#404040")
            cell.set_text_props(weight="bold", color="white")

    # ============ Panel B: LLM narrative ============
    ax = fig.add_subplot(gs[2])
    ax.axis("off")
    ax.text(0, 1.0,
            f"b   LLM narrative  ·  {case['narrative']['llm_model']}  ·  {case['narrative']['elapsed_seconds']:.1f}s  ·  {len(case['narrative']['text']):,} chars",
            fontsize=10, fontweight="bold", color="#111",
            transform=ax.transAxes)

    # Wrap narrative to fit width comfortably (shorter excerpt to avoid overflow)
    text = case["narrative"]["text"]
    if len(text) > 800:
        text = text[:800] + "\n\n... [truncated; full text in end_to_end_case.json]"
    wrapped = _wrap(text, width=125)

    ax.text(0.005, 0.93, wrapped,
            fontsize=7, color="#222",
            transform=ax.transAxes, va="top",
            family="Liberation Sans",
            linespacing=1.4,
            bbox=dict(boxstyle="round,pad=0.6",
                      fc="#FFFAEE", ec="#999", lw=0.5))

    # ============ Panel C: Verdict bar ============
    ax = fig.add_subplot(gs[3])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1)
    totals = case["verdicts"]["totals"]
    order = [("SUPPORTED",    "supported",      C_GREEN),
             ("UNSUPPORTED",  "unsupported",    C_GREY),
             ("CONTRADICTED", "contradicted",   C_RED),
             ("UNVERIFIABLE", "unverifiable_v0",C_DGREY)]
    left = 0
    for label, key, color in order:
        n = totals.get(key, 0)
        if n == 0: continue
        pct = n / n_total_claims * 100
        ax.barh(0.5, pct, left=left, height=0.5,
                color=color, edgecolor="white", linewidth=0.5)
        if pct >= 5:
            ax.text(left + pct/2, 0.5,
                    f"{label}\n{n} ({pct:.0f}%)",
                    ha="center", va="center", color="white",
                    fontsize=8, fontweight="bold")
        left += pct
    ax.set_yticks([])
    ax.set_xlabel("Verdict share (%)", fontsize=8)
    ax.set_title(f"c   Verifier verdict distribution",
                 loc="left", fontsize=10, pad=8)
    ax.spines["left"].set_visible(False)

    # ============ Panel D: Sample claims ============
    ax = fig.add_subplot(gs[4])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0, 1.0,
            "d   Sample claims and verdicts  (6 of 49 extracted; 2 per category)",
            fontsize=10, fontweight="bold", color="#111",
            transform=ax.transAxes)

    claims = case["verdicts"]["claims"]
    sel = []
    for v_target in ["supported", "unsupported", "unverifiable_v0"]:
        matches = [c for c in claims if c["verdict"] == v_target][:2]
        sel.extend(matches)
    color_map = {"supported": C_GREEN, "unsupported": C_GREY,
                 "contradicted": C_RED, "unverifiable_v0": C_DGREY}
    label_map = {"supported": "SUPPORTED", "unsupported": "UNSUPPORTED",
                 "contradicted": "CONTRADICTED", "unverifiable_v0": "UNVERIFIABLE"}

    # Each card occupies ~0.155 in y (6 cards from 0.93 down to ~0.02)
    card_h = 0.13
    y_top = 0.93
    y_gap = 0.02

    for i, c in enumerate(sel):
        y_card_top = y_top - i * (card_h + y_gap)
        col = color_map[c["verdict"]]
        col_label = label_map[c["verdict"]]

        # Background card
        bg = patches.Rectangle(
            (0.0, y_card_top - card_h), 1.0, card_h,
            transform=ax.transAxes,
            facecolor="#FAFAFA", edgecolor="#DDD", linewidth=0.5,
        )
        ax.add_patch(bg)

        # Verdict chip on left
        chip_w = 0.12
        chip = FancyBboxPatch(
            (0.01, y_card_top - card_h + 0.025),
            chip_w, card_h - 0.05,
            boxstyle="round,pad=0.005,rounding_size=0.012",
            transform=ax.transAxes,
            linewidth=0.5, edgecolor="black", facecolor=col,
        )
        ax.add_patch(chip)
        ax.text(0.01 + chip_w/2, y_card_top - card_h/2,
                col_label,
                ha="center", va="center",
                fontsize=7, color="white", fontweight="bold",
                transform=ax.transAxes)

        # Claim number under chip
        ax.text(0.01 + chip_w/2, y_card_top - card_h + 0.012,
                f"claim #{c['n']}",
                ha="center", va="bottom",
                fontsize=6, color="#444",
                transform=ax.transAxes)

        # Claim text (right of chip)
        text_x = chip_w + 0.025
        claim_wrapped = _wrap(c["text"], width=95)
        ax.text(text_x, y_card_top - 0.010,
                claim_wrapped,
                fontsize=8, color="#111", fontweight="bold",
                transform=ax.transAxes, va="top")

        # Evidence (small italic below)
        if c.get("evidence"):
            evid = c["evidence"][:200]
            if len(c["evidence"]) > 200: evid += "..."
            evid_wrapped = _wrap(f"Evidence: {evid}", width=110)
            ax.text(text_x, y_card_top - 0.060,
                    evid_wrapped,
                    fontsize=6.5, color="#666", style="italic",
                    transform=ax.transAxes, va="top")

    plt.savefig(OUT / "fig_e2e_case.png")
    plt.savefig(OUT / "fig_e2e_case.pdf")
    plt.close()
    print("saved fig_e2e_case")


# =====================================================================
# Figure: End-to-end case study FROM SPEC (PPT-friendly horizontal)
# =====================================================================
def fig_e2e_case_from_spec():
    """5-stage horizontal pipeline: spec → ID → narrative → verdict → pathway.

    Designed to fit on a single 16:9 PPT slide. Reuses end_to_end_case_sub6a.json.
    """
    case = json.loads((ROOT / "summary/May_7/end_to_end_case_sub6a.json").read_text())
    inp = case["input"]
    s1  = case["stage1_summary"]
    s1_ids = case["stage1_identifications"]
    s2  = case["stage2_narrative"]
    s2_mets = case["stage2_identified_metabolites"]
    s3  = case["stage3_verdicts"]
    gt  = inp["ground_truth_pathway"]

    fig = plt.figure(figsize=(280/25.4, 150/25.4))
    gs = fig.add_gridspec(
        2, 5,
        height_ratios=[0.18, 1.0],
        width_ratios=[1.15, 0.85, 1.45, 1.05, 1.05],
        hspace=0.10, wspace=0.22,
        left=0.025, right=0.985, top=0.96, bottom=0.04,
    )

    # ---- Title strip spanning all columns ----
    ax_title = fig.add_subplot(gs[0, :])
    ax_title.axis("off")
    ax_title.text(0, 0.65,
        "End-to-end case study from raw spectra to pathway identification",
        fontsize=11, fontweight="bold", color="#111", transform=ax_title.transAxes)
    ax_title.text(0, 0.05,
        f"Task {case['task_id']}   ·   GT pathway: {gt['pathway_name']} "
        f"({gt['pathway_source']} · {gt['external_id']})",
        fontsize=7.5, color="#555", style="italic", transform=ax_title.transAxes)

    # Helper: arrow between two panel centers (drawn in figure coords)
    def _arrow_between(x_fig):
        ax_arr = fig.add_axes([x_fig - 0.012, 0.46, 0.024, 0.05])
        ax_arr.axis("off")
        ax_arr.annotate("", xy=(1.0, 0.5), xytext=(0.0, 0.5),
                        xycoords="axes fraction",
                        arrowprops=dict(arrowstyle="->", color="#888",
                                        lw=1.2, shrinkA=0, shrinkB=0))

    # ---- Panel a: Spectrum ----
    ax_a = fig.add_subplot(gs[1, 0])
    spec0 = inp["first_spectrum"]
    peaks = np.array(spec0["peaks"])
    mzs, ints = peaks[:, 0], peaks[:, 1]
    norm_int = ints / ints.max() * 100
    markerline, stemlines, baseline = ax_a.stem(
        mzs, norm_int, linefmt=C_BLUE, markerfmt=" ", basefmt=" ")
    plt.setp(stemlines, linewidth=0.8, alpha=0.85)
    ax_a.axvline(spec0["precursor_mz"], color=C_RED, linestyle="--",
                 linewidth=0.8, alpha=0.7,
                 label=f"precursor {spec0['precursor_mz']:.2f}")
    top3 = np.argsort(norm_int)[::-1][:3]
    for idx in top3:
        ax_a.text(mzs[idx], norm_int[idx] + 3, f"{mzs[idx]:.2f}",
                  ha="center", va="bottom", fontsize=5.5, color="#333")
    ax_a.set_xlabel("m/z")
    ax_a.set_ylabel("Relative intensity (%)")
    ax_a.set_xlim(40, max(mzs) * 1.05)
    ax_a.set_ylim(0, 115)
    ax_a.set_title(
        f"a   Input: 1 of {inp['n_spectra']} MS/MS spectra\n"
        f"     {spec0['ion_mode']} mode · {spec0['adduct']} · {spec0['n_peaks']} peaks",
        loc="left", fontsize=8.5)
    ax_a.legend(loc="upper right", fontsize=6, frameon=False)

    # ---- Panel b: Stage 1 identification ----
    ax_b = fig.add_subplot(gs[1, 1])
    ax_b.axis("off")
    ax_b.set_xlim(0, 1); ax_b.set_ylim(0, 1)
    ax_b.text(0, 1.0,
        f"b   Stage 1 — Library ID\n     ({s1['id_strategy']}, {s1['elapsed_id_seconds']:.1f}s)",
        fontsize=8.5, fontweight="bold", color="#111", transform=ax_b.transAxes)

    # Big accuracy callout
    pct = s1["identification_accuracy"] * 100
    ax_b.text(0.50, 0.78, f"{pct:.0f}%", ha="center", va="center",
              fontsize=24, fontweight="bold", color=C_GREEN,
              transform=ax_b.transAxes)
    ax_b.text(0.50, 0.66,
              f"top-1 hit rate\n({s1['n_correct_top1']}/{s1['n_spectra']} spectra)",
              ha="center", va="center", fontsize=7, color="#444",
              transform=ax_b.transAxes)

    # OK/X marker grid (10 markers in 2 rows of 5) — use scatter for round dots
    xs, ys, colors = [], [], []
    for i, ident in enumerate(s1_ids):
        row, col = divmod(i, 5)
        xs.append(0.13 + col * 0.185)
        ys.append(0.43 - row * 0.14)
        colors.append(C_GREEN if ident.get("correct_top1") else C_RED)
    ax_b.scatter(xs, ys, s=180, c=colors,
                 edgecolors="black", linewidths=0.5,
                 transform=ax_b.transAxes, clip_on=False, zorder=3)
    for x, y, c in zip(xs, ys, colors):
        ax_b.text(x, y, "OK" if c == C_GREEN else "X",
                  ha="center", va="center",
                  fontsize=5.5, color="white", fontweight="bold",
                  transform=ax_b.transAxes, zorder=4)
    ax_b.text(0.50, 0.13, "10 spectra · all correct",
              ha="center", va="center", fontsize=6.5, color="#666",
              style="italic", transform=ax_b.transAxes)

    # ---- Panel c: Stage 2 identified compounds + narrative excerpt ----
    ax_c = fig.add_subplot(gs[1, 2])
    ax_c.axis("off")
    ax_c.set_xlim(0, 1); ax_c.set_ylim(0, 1)
    ax_c.text(0, 1.0,
        f"c   Stage 2 — LLM narrative\n     ({s2['llm_model']}, {s2['elapsed_seconds']:.1f}s, {len(s2['text']):,} chars)",
        fontsize=8.5, fontweight="bold", color="#111", transform=ax_c.transAxes)

    # Compounds box (top half)
    comp_lines = [f"{i+1}. {m['name']}"
                  for i, m in enumerate(s2_mets)]
    comp_text = "Identified compounds (deduplicated, n=" + str(len(s2_mets)) + "):\n" + \
                "\n".join(comp_lines)
    ax_c.text(0.02, 0.85, comp_text,
              fontsize=6.8, color="#222", va="top", family="monospace",
              transform=ax_c.transAxes, linespacing=1.5,
              bbox=dict(boxstyle="round,pad=0.45", fc="#F4F8FB",
                        ec="#888", lw=0.4))

    # Narrative excerpt (bottom half) — truncate hard to one or two sentences
    nar = s2["text"]
    body = "\n".join([l for l in nar.splitlines()
                      if l.strip() and not l.lstrip().startswith("#")])
    # Take first ~220 chars, end at sentence boundary if possible
    excerpt = body[:220]
    last_dot = max(excerpt.rfind(". "), excerpt.rfind("."))
    if last_dot > 80:
        excerpt = excerpt[:last_dot + 1]
    excerpt_wrapped = _wrap("Excerpt: " + excerpt, width=52)
    ax_c.text(0.02, 0.38, excerpt_wrapped,
              fontsize=6.5, color="#222", va="top",
              transform=ax_c.transAxes, linespacing=1.45,
              bbox=dict(boxstyle="round,pad=0.45", fc="#FFFAEE",
                        ec="#888", lw=0.4))

    # ---- Panel d: Stage 3 verdict bar ----
    ax_d = fig.add_subplot(gs[1, 3])
    ax_d.set_xlim(0, 100); ax_d.set_ylim(0, 1)
    totals = s3["totals"]
    n_total = sum(totals.values())
    order = [
        ("SUPPORTED",    "supported",       C_GREEN),
        ("UNSUPPORTED",  "unsupported",     C_GREY),
        ("CONTRADICTED", "contradicted",    C_RED),
        ("UNVERIFIABLE", "unverifiable_v0", C_DGREY),
    ]
    # Vertical stacked bar (single column) for compact display
    ax_d.clear()
    ax_d.set_ylim(0, 100); ax_d.set_xlim(-0.6, 2.6)
    bar_x = 0.0
    bar_w = 0.95
    bottom = 0
    for label, key, color in order:
        n = totals.get(key, 0)
        if n == 0: continue
        pct_v = n / n_total * 100
        ax_d.bar(bar_x, pct_v, bottom=bottom, width=bar_w,
                 color=color, edgecolor="white", linewidth=0.6)
        # All labels go to the right of the bar with a connector
        y_center = bottom + pct_v / 2
        ax_d.annotate(
            f"{label}\n{n} ({pct_v:.0f}%)",
            xy=(bar_x + bar_w/2, y_center),
            xytext=(bar_x + bar_w/2 + 0.55, y_center),
            ha="left", va="center",
            fontsize=6.5, color=color, fontweight="bold",
            arrowprops=dict(arrowstyle="-", color=color, lw=0.6,
                            shrinkA=0, shrinkB=0),
        )
        bottom += pct_v
    ax_d.set_xticks([])
    ax_d.set_ylabel("Verdict share (%)", fontsize=7.5)
    ax_d.set_title(
        f"d   Stage 3 — Verifier\n     ({n_total} extracted claims)",
        loc="left", fontsize=8.5)
    ax_d.spines["bottom"].set_visible(False)

    # ---- Panel e: Final pathway match ----
    ax_e = fig.add_subplot(gs[1, 4])
    ax_e.axis("off")
    ax_e.set_xlim(0, 1); ax_e.set_ylim(0, 1)
    ax_e.text(0, 1.0,
        "e   Final — Pathway identification",
        fontsize=8.5, fontweight="bold", color="#111", transform=ax_e.transAxes)

    # GT pathway card (yellow)
    gt_card = FancyBboxPatch(
        (0.02, 0.66), 0.96, 0.24,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        transform=ax_e.transAxes,
        linewidth=0.6, edgecolor="#B89A2E", facecolor="#FFF8D8")
    ax_e.add_patch(gt_card)
    ax_e.text(0.50, 0.86, "Ground truth pathway",
              ha="center", va="top", fontsize=7,
              fontweight="bold", color="#7A6614",
              transform=ax_e.transAxes)
    ax_e.text(0.50, 0.79, gt["pathway_name"],
              ha="center", va="top", fontsize=8.5,
              fontweight="bold", color="#222",
              transform=ax_e.transAxes)
    ax_e.text(0.50, 0.71,
              f"{gt['pathway_source']}: {gt['external_id']}",
              ha="center", va="top", fontsize=6.8, color="#555",
              style="italic", transform=ax_e.transAxes)

    # Match takeaway box
    take_card = FancyBboxPatch(
        (0.02, 0.04), 0.96, 0.55,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        transform=ax_e.transAxes,
        linewidth=0.6, edgecolor=C_BLUE, facecolor="#F0F4FA")
    ax_e.add_patch(take_card)
    ax_e.text(0.50, 0.55, "Stage 1 → Stage 3 takeaway",
              ha="center", va="top", fontsize=7,
              fontweight="bold", color="#2A4F8F",
              transform=ax_e.transAxes)
    bullets = [
        ("+", C_GREEN, "10/10 spectra correctly identified"),
        ("+", C_GREEN, "Compounds match GT signals\n  (deoxycytidine, deoxyuridine, ...)"),
        ("-", C_RED,   "LLM said 'pyrimidine degradation' -\n  CONTRADICTED on canonical naming"),
        (">", C_DGREY, "Biology: right    Naming: off"),
    ]
    y0 = 0.46
    for i, (mark, color, txt) in enumerate(bullets):
        y = y0 - i * 0.105
        ax_e.text(0.05, y, mark, fontsize=8, fontweight="bold",
                  color=color, va="top", transform=ax_e.transAxes)
        ax_e.text(0.13, y, txt, fontsize=6.7, color="#222",
                  va="top", transform=ax_e.transAxes, linespacing=1.3)

    # ---- Arrows between panels — drawn directly in figure coordinates ----
    fig.canvas.draw()  # ensure tight_layout-ish positions are computed
    panel_axes = [ax_a, ax_b, ax_c, ax_d, ax_e]
    bboxes = [a.get_position() for a in panel_axes]
    for i in range(len(bboxes) - 1):
        x_left  = bboxes[i].x1
        x_right = bboxes[i+1].x0
        y_mid = (bboxes[i].y0 + bboxes[i].y1) / 2
        # Draw a single arrow patch in figure coordinates
        arrow = FancyArrowPatch(
            (x_left + 0.002, y_mid),
            (x_right - 0.002, y_mid),
            transform=fig.transFigure,
            arrowstyle="-|>",
            mutation_scale=14,
            color="#666",
            linewidth=1.4,
            shrinkA=0, shrinkB=0,
        )
        fig.patches.append(arrow)

    plt.savefig(OUT / "fig_e2e_case_from_spec.png")
    plt.savefig(OUT / "fig_e2e_case_from_spec.pdf")
    plt.close()
    print("saved fig_e2e_case_from_spec")


if __name__ == "__main__":
    fig_id_per_task()
    fig_metric_explainer()
    fig_e2e_case()
    fig_e2e_case_from_spec()
