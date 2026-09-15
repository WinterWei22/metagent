"""W6 D5 — Fig 3 v3 composite (Panel A paradigm Jaccard 5x5,
Panel B charge-reconciliation lift (W4 v2 carry-forward),
Panel C Gate-2 precision lift, color-coded by verdict).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

WORKTREE = Path(__file__).resolve().parents[3]
GATE2 = WORKTREE / "data/concord/gate2_w6"
OUT = WORKTREE / "data/concord/fig3_v3"
OUT.mkdir(parents=True, exist_ok=True)

METHODS = ["sspa_ora", "ramp", "PSEA", "mummichog", "FELLA"]
PARADIGM = {"sspa_ora": "ORA", "ramp": "ORA", "PSEA": "ORA",
            "mummichog": "m/z", "FELLA": "Net"}
VERDICT_COLOR = {"GREEN": "#2ca02c", "YELLOW": "#bcbd22", "RED": "#d62728"}


def panel_a_paradigm_jaccard(ax, summary: dict):
    """5x5 pair-wise pathway-name Jaccard heatmap (PRIMARY cohort)."""
    pair_mean = summary["primary"]["jaccard_5x5"]["pair_mean"]
    n = len(METHODS)
    mat = np.zeros((n, n))
    np.fill_diagonal(mat, 1.0)
    for i, a in enumerate(METHODS):
        for j, b in enumerate(METHODS):
            if i == j:
                continue
            key = f"{a}_vs_{b}" if f"{a}_vs_{b}" in pair_mean else f"{b}_vs_{a}"
            mat[i, j] = pair_mean.get(key, 0.0)

    im = ax.imshow(mat, vmin=0, vmax=1, cmap="viridis")
    labels = [f"{m}\n({PARADIGM[m]})" for m in METHODS]
    ax.set_xticks(range(n)); ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(labels, fontsize=8)
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{mat[i,j]:.2f}", ha="center", va="center",
                    color="white" if mat[i,j] < 0.55 else "black", fontsize=8)
    ax.set_title(f"A · 5×5 pathway-name Jaccard\n(PRIMARY cohort, N={summary['primary']['n_tasks']})",
                  fontsize=10)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)


def panel_b_charge_reconciliation(ax):
    """W4 v2 charge-reconciliation bar (carry-forward)."""
    categories = ["Raw\n(no canonicalization)", "Charge\nreconciled",
                  "+ Tautomer\nsafeguarded"]
    disagreement = [59.1, 12.3, 5.5]  # W4 v2 data; PER-SOURCE canon caveat
    bars = ax.bar(categories, disagreement,
                   color=["#d62728", "#ff7f0e", "#2ca02c"])
    ax.set_ylabel("Compound-level disagreement %\n(N=110 cross-source pairs)",
                   fontsize=9)
    ax.set_ylim(0, 70)
    for b, v in zip(bars, disagreement):
        ax.text(b.get_x() + b.get_width()/2, v + 1.5, f"{v:.1f}%",
                ha="center", fontsize=9, fontweight="bold")
    ax.set_title("B · Charge / tautomer reconciliation\n(W4 carry-forward,"
                  " 91 % residual reduction)", fontsize=10)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)


def panel_c_gate2_lift(ax, summary: dict):
    """Per-cohort precision/recall lift bar."""
    cohorts = ["primary", "sens_a", "sens_b"]
    n = len(cohorts)
    width = 0.35
    xs = np.arange(n)
    a_prec = [summary[c]["metric_2"]["cond_a"]["mean_precision"] * 100
              for c in cohorts]
    b_prec = [summary[c]["metric_2"]["cond_b"]["mean_precision"] * 100
              for c in cohorts]
    verdicts = [summary[c]["verdict"] for c in cohorts]

    colors_a = ["#888888"] * n
    colors_b = [VERDICT_COLOR[v] for v in verdicts]

    ax.bar(xs - width/2, a_prec, width, color=colors_a,
            label="A · RaMP only")
    ax.bar(xs + width/2, b_prec, width, color=colors_b,
            label="B · Cross-paradigm consensus")

    for i, (a, b, v) in enumerate(zip(a_prec, b_prec, verdicts)):
        ax.text(i, max(a, b) + 2.5, f"Δ={b-a:+.1f}pp\n{v}",
                ha="center", fontsize=8)
    ax.set_xticks(xs)
    cohort_labels = [f"{c.upper()}\nN={summary[c]['n_tasks']}" for c in cohorts]
    ax.set_xticklabels(cohort_labels, fontsize=8)
    ax.set_ylabel("Precision@10 vs Cooke ground truth (%)\n(name-fuzzy ≥ 0.5)",
                   fontsize=9)
    ax.set_title("C · Gate-2 precision lift\n(A=baseline · B=consensus)",
                  fontsize=10)
    ax.set_ylim(0, max(max(a_prec) if a_prec else 0,
                         max(b_prec) if b_prec else 0) * 1.3 + 10)
    ax.legend(loc="upper right", fontsize=8)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)


def main() -> int:
    summary = json.loads((GATE2 / "gate2_verdict.json").read_text())
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    panel_a_paradigm_jaccard(axes[0], summary)
    panel_b_charge_reconciliation(axes[1])
    panel_c_gate2_lift(axes[2], summary)
    plt.tight_layout()

    png = OUT / "fig3_v3.png"
    pdf = OUT / "fig3_v3.pdf"
    fig.savefig(png, dpi=300)
    fig.savefig(pdf)
    print(f"wrote {png}")
    print(f"wrote {pdf}")

    # CSV of underlying numbers
    csv_path = OUT / "fig3_v3_data.csv"
    with csv_path.open("w") as f:
        f.write("cohort,n_tasks,verdict,m1_cond_a,m1_cond_b,m1_delta_pp,"
                  "m2_cond_a_prec,m2_cond_b_prec,m2_delta_prec_pp,m2_sign_p\n")
        for c in ("primary", "sens_a", "sens_b"):
            s = summary[c]
            m1 = s["metric_1"]; m2 = s["metric_2"]
            f.write(f"{c},{s['n_tasks']},{s['verdict']},"
                     f"{m1['cond_a_supported_pct']:.4f},{m1['cond_b_supported_pct']:.4f},{m1['delta_pp']:.2f},"
                     f"{m2['cond_a']['mean_precision']:.4f},{m2['cond_b']['mean_precision']:.4f},"
                     f"{m2['delta_precision_mean']*100:.2f},{m2['sign_test_p']:.4f}\n")
    print(f"wrote {csv_path}")

    # Caption (≤ 150 words)
    overall = "GREEN" if all(summary[c]["verdict"] == "GREEN" for c in ("primary","sens_a","sens_b")) \
              else "RED" if all(summary[c]["verdict"] == "RED" for c in ("primary","sens_a","sens_b")) \
              else "YELLOW"
    caption = build_caption(summary, overall)
    (OUT / "fig3_v3_caption.md").write_text(caption)
    print(f"wrote {OUT / 'fig3_v3_caption.md'}")
    print(f"\n=== OVERALL Gate-2 verdict: {overall} ===")
    return 0


def build_caption(summary: dict, overall: str) -> str:
    primary = summary["primary"]
    n_p = primary["n_tasks"]
    bucket = primary["jaccard_5x5"]["paradigm_bucket_mean"]
    m1 = primary["metric_1"]; m2 = primary["metric_2"]

    if overall == "GREEN":
        narrative = (
            "Cross-paradigm consensus consistently lifts ground-truth-anchored "
            "precision/recall above the single-tool baseline across cohorts, "
            "supporting the reconciliation framework."
        )
    elif overall == "RED":
        narrative = (
            "Cross-paradigm consensus does not yield ground-truth-anchored "
            "lift; the reconciliation contribution is qualitative (within-"
            "paradigm consistency, panel A) rather than precision-driven."
        )
    else:
        narrative = (
            "Reconciliation lift is heterogeneous across cohorts — paper "
            "narrative leans on within-paradigm consistency (panel A) and "
            "compound-level reconciliation depth (panel B) rather than a "
            "single Gate-2 precision number."
        )

    return f"""# Fig 3 v3 Caption (≤150 words)

**Figure 3.** ConcordMet reconciliation across paradigm boundaries. (A) Mean
pairwise pathway-name Jaccard between five enrichment tools on the PRIMARY
Cooke SAMBA cohort (Human1 GEM, |z|>1, N={n_p}): ORA × ORA mean = {bucket['ora_ora']:.3f},
ORA × m/z = {bucket['ora_mz']:.3f}, ORA × Network = {bucket['ora_net']:.3f},
m/z × Network = {bucket['mz_net']:.3f}. (B) Charge/tautomer reconciliation
reduces cross-source compound-level disagreement from 59.1 % (raw) to 5.5 %
(safeguarded tautomer canonicalization); upper-bound estimate, per-source
canonicalization in supplementary. (C) Gate-2 precision@10 against Cooke
in-silico ground truth (name-fuzzy ≥0.5): RaMP baseline vs cross-paradigm
consensus top-10, per cohort, bars color-coded by cohort verdict. PRIMARY
delta Metric-2 precision = {m2['delta_precision_mean']*100:+.1f} pp; Metric-1
support delta = {m1['delta_pp']:+.1f} pp. Overall: **{overall}** ({summary['primary']['verdict']} /
{summary['sens_a']['verdict']} / {summary['sens_b']['verdict']}). {narrative}

*In silico ground truth — Cooke et al. 2025 SAMBA simulations, not experimental.*
"""


if __name__ == "__main__":
    sys.exit(main())
