"""End-to-end case study from spectrum (Sub-6A) — full 3-stage pipeline.

Output:
    summary/May_7/figures/fig_e2e_sub6a_case.{png,pdf}

Layout (Nature poster style, vertical 5-panel):
    a — Input: spectrum stack + one visualized MS/MS plot
    b — Stage 1: identification table (10 spectra, top-1 hit rate)
    c — Stage 2: identified compound list → LLM narrative
    d — Stage 3: verdict distribution + 6 sample claims
    e — Final: pathway match against ground truth
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

mpl.rcParams.update({
    "font.family": "Liberation Sans",
    "font.size": 7.5,
    "axes.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.labelsize": 7.5,
    "axes.titlesize": 8.5,
    "axes.titleweight": "bold",
    "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5,
    "pdf.fonttype": 42,
    "savefig.dpi": 600,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
})

ROOT = Path(__file__).resolve().parents[2]
OUT  = ROOT / "summary/May_7/figures"

C_GREEN = "#4C9F70"
C_RED   = "#D62728"
C_GREY  = "#808080"
C_DGREY = "#404040"
C_BLUE  = "#5B8FF9"
C_PURPLE = "#A459D1"
C_ORANGE = "#F59B49"


def render():
    case = json.loads((ROOT / "summary/May_7/end_to_end_case_sub6a.json").read_text())
    inp = case["input"]
    s1 = case["stage1_summary"]
    s1_ids = case["stage1_identifications"]
    s2 = case["stage2_narrative"]
    s3 = case["stage3_verdicts"]
    gt = inp["ground_truth_pathway"]

    fig = plt.figure(figsize=(190/25.4, 350/25.4))
    gs = fig.add_gridspec(8, 1,
        height_ratios=[0.4, 2.6, 3.0, 3.4, 1.0, 0.4, 1.5, 4.0],
        hspace=0.55, left=0.04, right=0.97, top=0.98, bottom=0.02)

    # ========================================================================
    # Panel 0: Title strip
    # ========================================================================
    ax = fig.add_subplot(gs[0])
    ax.axis("off")
    ax.text(0, 0.85,
        f"End-to-end case study (Sub-6A real-id): {case['task_id']}",
        fontsize=10, fontweight="bold", color="#111", transform=ax.transAxes)
    ax.text(0, 0.25,
        f"Input: 10 raw MS/MS spectra → Stage 1: identification → "
        f"Stage 2: narrative → Stage 3: verifier (40 claims) → Output",
        fontsize=7.5, color="#444", style="italic", transform=ax.transAxes)

    # ========================================================================
    # Panel A: Input — spectrum visualization + summary table
    # ========================================================================
    gs_a = gs[1].subgridspec(1, 2, width_ratios=[1.4, 1.0], wspace=0.25)
    ax_a1 = fig.add_subplot(gs_a[0])
    ax_a2 = fig.add_subplot(gs_a[1])

    # Left: One spectrum (sample, first one) as stem plot
    spec0 = inp["first_spectrum"]
    peaks = np.array(spec0["peaks"])  # (N, 2): m/z, intensity
    mzs = peaks[:, 0]
    intensities = peaks[:, 1]
    norm_int = intensities / intensities.max() * 100  # normalize to 0-100

    # Stem plot
    markerline, stemlines, baseline = ax_a1.stem(
        mzs, norm_int, linefmt=C_BLUE, markerfmt=" ", basefmt=" "
    )
    plt.setp(stemlines, linewidth=0.8, alpha=0.85)
    # Precursor m/z marker
    ax_a1.axvline(spec0["precursor_mz"], color=C_RED, linestyle="--",
                  linewidth=0.8, alpha=0.7,
                  label=f"Precursor m/z = {spec0['precursor_mz']:.4f}")
    # Annotate top-3 peaks
    sorted_idx = np.argsort(norm_int)[::-1][:3]
    for idx in sorted_idx:
        ax_a1.text(mzs[idx], norm_int[idx] + 3, f"{mzs[idx]:.2f}",
                   ha="center", va="bottom", fontsize=5.5, color="#333")
    ax_a1.set_xlabel("m/z")
    ax_a1.set_ylabel("Relative intensity (%)")
    ax_a1.set_xlim(40, max(mzs) * 1.05)
    ax_a1.set_ylim(0, 110)
    ax_a1.set_title(
        f"a   Spectrum 1 of 10 ({spec0['spectrum_id'][:35]}...)\n"
        f"     {spec0['ion_mode']} mode, {spec0['adduct']}, {spec0['n_peaks']} peaks",
        loc="left", fontsize=8)
    ax_a1.legend(loc="upper right", fontsize=6)

    # Right: spectrum stack table
    ax_a2.axis("off")
    ax_a2.text(0, 0.95, "All 10 spectra in this task:",
               fontsize=7.5, fontweight="bold", color="#222",
               transform=ax_a2.transAxes)
    cell_text = []
    for i, s in enumerate(inp["all_spectra_meta"][:10]):
        sid = s["spectrum_id"]
        if len(sid) > 32: sid = sid[:30] + ".."
        cell_text.append([
            f"{i+1}", sid, f"{s['precursor_mz']:.4f}", str(s["n_peaks"])
        ])
    tab = ax_a2.table(
        cellText=cell_text,
        colLabels=["#", "spectrum_id", "precursor m/z", "n peaks"],
        loc="upper left", cellLoc="left", colLoc="left",
        colWidths=[0.06, 0.58, 0.20, 0.16],
        bbox=[0, 0, 1, 0.85])
    tab.auto_set_font_size(False)
    tab.set_fontsize(5.8)
    for (r, c), cell in tab.get_celld().items():
        cell.set_linewidth(0.3)
        if r == 0:
            cell.set_facecolor("#E8E8E8")
            cell.set_text_props(weight="bold")

    # ========================================================================
    # Panel B: Stage 1 — Identification table
    # ========================================================================
    ax = fig.add_subplot(gs[2])
    ax.axis("off")
    ax.text(0, 1.0,
        f"b   Stage 1 — Library identification ({s1['id_strategy']}, "
        f"{s1['n_correct_top1']}/{s1['n_spectra']} = "
        f"{s1['identification_accuracy']*100:.0f}% top-1 in {s1['elapsed_id_seconds']:.1f}s)",
        fontsize=9, fontweight="bold", color="#111", transform=ax.transAxes)

    cell_text = []
    for i, ident in enumerate(s1_ids):
        name = ident.get("predicted_name") or "-"
        if len(name) > 38: name = name[:36] + ".."
        # Color hit
        is_hit = ident.get("correct_top1")
        mark = "OK" if is_hit else "X"
        score = ident.get("predicted_score") or 0.0
        cell_text.append([
            str(i+1),
            mark,
            ident.get("predicted_inchikey_first_block","-")[:14],
            ident.get("gt_inchikey_first_block","-")[:14],
            name,
            f"{score:.4f}",
        ])
    tab = ax.table(
        cellText=cell_text,
        colLabels=["#", "Hit", "predicted (InChIKey)", "ground truth (InChIKey)",
                   "predicted compound name", "score"],
        loc="upper left", cellLoc="left", colLoc="left",
        colWidths=[0.04, 0.05, 0.15, 0.15, 0.45, 0.10],
        bbox=[0, 0, 1, 0.92])
    tab.auto_set_font_size(False)
    tab.set_fontsize(6)
    for (r, c), cell in tab.get_celld().items():
        cell.set_linewidth(0.3)
        if r == 0:
            cell.set_facecolor("#E8E8E8")
            cell.set_text_props(weight="bold")
        elif c == 1:  # OK/X column
            value = cell_text[r-1][1]
            cell.set_facecolor("#E5F5E5" if value == "OK" else "#FBEAEA")
            cell.set_text_props(weight="bold", color=C_GREEN if value == "OK" else C_RED)

    # ========================================================================
    # Panel C: Stage 2 — Identified compounds + narrative excerpt
    # ========================================================================
    gs_c = gs[3].subgridspec(1, 2, width_ratios=[0.5, 1.4], wspace=0.20)
    ax_c1 = fig.add_subplot(gs_c[0])
    ax_c2 = fig.add_subplot(gs_c[1])

    # Left: deduplicated compound list
    ax_c1.axis("off")
    ax_c1.text(0, 1.0, "c1   Identified compounds (deduplicated)",
               fontsize=8.5, fontweight="bold", color="#111",
               transform=ax_c1.transAxes)
    seen_ikey = set()
    unique_compounds = []
    for m in case["stage2_identified_metabolites"]:
        ikey = m.get("inchikey_first_block","")
        if ikey and ikey not in seen_ikey:
            seen_ikey.add(ikey)
            unique_compounds.append(m)
    text_lines = []
    for i, m in enumerate(unique_compounds[:8]):
        name = m["name"]
        if len(name) > 35: name = name[:33] + ".."
        text_lines.append(f"  {i+1}. {name}")
    ax_c1.text(0, 0.86, "\n".join(text_lines),
               fontsize=6.8, color="#222", va="top", family="monospace",
               transform=ax_c1.transAxes,
               bbox=dict(boxstyle="round,pad=0.4", fc="#F4F8FB",
                         ec="#888", lw=0.4))

    # Right: LLM narrative excerpt
    ax_c2.axis("off")
    ax_c2.text(0, 1.0,
               f"c2   LLM narrative ({s2['llm_model']}, {s2['elapsed_seconds']:.1f}s, "
               f"{len(s2['text'])} chars)",
               fontsize=8.5, fontweight="bold", color="#111",
               transform=ax_c2.transAxes)
    text = s2["text"]
    if len(text) > 1100:
        text = text[:1100] + "\n\n... [truncated]"
    ax_c2.text(0, 0.92, text, fontsize=6, color="#222",
               va="top", transform=ax_c2.transAxes,
               bbox=dict(boxstyle="round,pad=0.4", fc="#FFFAEE",
                         ec="#888", lw=0.4))

    # ========================================================================
    # Panel D: Stage 3 — Verdict bar
    # ========================================================================
    ax = fig.add_subplot(gs[4])
    # spacing buffer (gs[5]) is intentionally empty
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1)
    totals = s3["totals"]
    n_total = sum(totals.values())
    order = [
        ("SUPPORTED",    "supported",       C_GREEN),
        ("UNSUPPORTED",  "unsupported",     C_GREY),
        ("CONTRADICTED", "contradicted",    C_RED),
        ("UNVERIFIABLE", "unverifiable_v0", C_DGREY),
    ]
    left = 0
    for label, key, color in order:
        n = totals.get(key, 0)
        if n == 0: continue
        pct = n / n_total * 100
        ax.barh(0.5, pct, left=left, height=0.55, color=color,
                edgecolor="white", linewidth=0.5)
        if pct >= 5:
            ax.text(left + pct/2, 0.5, f"{label}\n{n} ({pct:.0f}%)",
                    ha="center", va="center", color="white",
                    fontsize=6.5, fontweight="bold")
        left += pct
    ax.set_yticks([])
    ax.set_xlabel("Verdict share (%)")
    ax.set_title(f"d   Stage 3 — Verifier verdict over {n_total} extracted claims",
                 loc="left", fontsize=9)
    ax.spines["left"].set_visible(False)

    # ========================================================================
    # Panel E (top half): GT pathway + takeaway boxes — gs[6]
    # ========================================================================
    ax_e1 = fig.add_subplot(gs[6])
    ax_e1.axis("off")

    # Two side-by-side boxes
    ax_e1.text(0.0, 1.0, "Ground truth pathway",
            fontsize=7.5, fontweight="bold", color="#333",
            transform=ax_e1.transAxes, va="top")
    ax_e1.text(0.0, 0.85,
            f"{gt['pathway_name']}\n"
            f"({gt['pathway_source']}: {gt['external_id']})\n\n"
            f"Signal compounds:\n"
            f"   " + ", ".join(inp["ground_truth_signal_compounds"]),
            fontsize=6.7, color="#222",
            transform=ax_e1.transAxes, va="top",
            bbox=dict(boxstyle="round,pad=0.4", fc="#FFF8D8",
                      ec="#888", lw=0.5))

    ax_e1.text(0.50, 1.0, "Stage 1 → Stage 3 takeaway",
            fontsize=7.5, fontweight="bold", color="#333",
            transform=ax_e1.transAxes, va="top")
    ax_e1.text(0.50, 0.85,
            "• 10/10 spectra correctly identified (100% top-1)\n"
            "• Identified compounds match GT signals\n"
            "  (deoxycytidine, deoxyuridine, dihydrouracil, ...)\n"
            "• LLM said 'pyrimidine degradation' — CONTRADICTED\n"
            "  by Layer 6a (non-canonical name vs RaMP top-3)\n"
            "• Bottom-line: biology right, naming off",
            fontsize=6.5, color="#222",
            transform=ax_e1.transAxes, va="top",
            bbox=dict(boxstyle="round,pad=0.4", fc="#F0F4FA",
                      ec=C_BLUE, lw=0.6))

    # ========================================================================
    # Panel E (bottom): Sample claims list — gs[7]
    # ========================================================================
    ax = fig.add_subplot(gs[7])
    ax.axis("off")
    ax.text(0, 1.0, "e   Sample claims (8 of 40 extracted)",
            fontsize=9, fontweight="bold", color="#111", transform=ax.transAxes)

    claims = s3["claims"]
    sel = []
    for v_target in ["supported", "contradicted", "unsupported", "unverifiable_v0"]:
        matches = [c for c in claims if c["verdict"] == v_target][:2]
        sel.extend(matches)
    color_map = {"supported": C_GREEN, "unsupported": C_GREY,
                 "contradicted": C_RED, "unverifiable_v0": C_DGREY}

    y_start = 0.92
    line_h  = 0.115
    for i, c in enumerate(sel):
        y = y_start - i * line_h
        col = color_map[c["verdict"]]
        ax.text(0, y, f"#{c['n']}", fontsize=6.5, color="#777",
                transform=ax.transAxes, va="top", fontweight="bold")
        chip = FancyBboxPatch((0.035, y - 0.028), 0.10, 0.030,
            boxstyle="round,pad=0.005,rounding_size=0.008",
            transform=ax.transAxes, linewidth=0.4,
            edgecolor="black", facecolor=col, clip_on=False)
        ax.add_patch(chip)
        ax.text(0.085, y - 0.012, c["verdict"].replace("_v0","").upper(),
                fontsize=5.5, color="white", fontweight="bold",
                transform=ax.transAxes, ha="center", va="center")
        text = c["text"][:140]
        if len(c["text"]) > 140: text += "..."
        ax.text(0.155, y, text, fontsize=6.7, color="#222",
                transform=ax.transAxes, va="top")
        if c.get("evidence"):
            evid = c["evidence"][:170]
            if len(c["evidence"]) > 170: evid += "..."
            ax.text(0.155, y - 0.040, f"Evidence: {evid}",
                    fontsize=5.5, color="#666", style="italic",
                    transform=ax.transAxes, va="top")

    plt.savefig(OUT / "fig_e2e_sub6a_case.png")
    plt.savefig(OUT / "fig_e2e_sub6a_case.pdf")
    plt.close()
    print(f"saved {OUT / 'fig_e2e_sub6a_case.png'}")


if __name__ == "__main__":
    render()
