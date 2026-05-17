"""W7 D4 — Fig 3 v4 with V3 best-variant Panel C.

Replaces W6's RED V0 strict-intersection lift in Panel C with the
**V3 rank-weighted soft-union** verdict. V3 was selected on W7 D2:
  PRIMARY: GREEN  Δ +25.5 pp  p = 0.0009  (13 / 0)
  SENS_A:  YELLOW Δ +21.1 pp  p = 0.125   (4 / 0)
  SENS_B:  YELLOW Δ +16.7 pp  p = 0.500   (2 / 0)
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

WORKTREE = Path(__file__).resolve().parents[3]
W7_DIR = WORKTREE / "data/concord/gate2_w7"
W6_DIR = WORKTREE / "data/concord/gate2_w6"
OUT = WORKTREE / "data/concord/fig3_v4"
OUT.mkdir(parents=True, exist_ok=True)

METHODS = ["sspa_ora", "ramp", "PSEA", "mummichog", "FELLA"]
PARADIGM = {"sspa_ora": "ORA", "ramp": "ORA", "PSEA": "ORA",
            "mummichog": "m/z", "FELLA": "Net"}
VERDICT_COLOR = {"GREEN": "#2ca02c", "YELLOW": "#bcbd22", "RED": "#d62728"}


def _load_verdicts() -> list[dict]:
    rows = []
    with (W7_DIR / "verdicts_3variant.csv").open() as f:
        for r in csv.DictReader(f):
            for k in ("cond_a_prec", "cond_b_prec", "delta_pp", "sign_p"):
                r[k] = float(r[k])
            r["n_tasks"] = int(r["n_tasks"])
            rows.append(r)
    return rows


def _load_w6_jaccard() -> dict:
    """Reuse W6 paradigm-bucket Jaccard for Panel A (already computed)."""
    return json.loads((W6_DIR / "gate2_verdict.json").read_text())


def panel_a_paradigm_jaccard(ax, w6_data: dict):
    pair_mean = w6_data["primary"]["jaccard_5x5"]["pair_mean"]
    n = len(METHODS)
    mat = np.zeros((n, n)); np.fill_diagonal(mat, 1.0)
    for i, a in enumerate(METHODS):
        for j, b in enumerate(METHODS):
            if i == j: continue
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
    ax.set_title(f"A · 5×5 pathway-name Jaccard\n(PRIMARY, N={w6_data['primary']['n_tasks']})",
                  fontsize=10)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)


def panel_b_charge_reconciliation(ax):
    categories = ["Raw\n(no canonical.)", "Charge\nreconciled",
                  "+ Tautomer\nsafeguarded"]
    disagreement = [59.1, 12.3, 5.5]
    bars = ax.bar(categories, disagreement,
                   color=["#d62728", "#ff7f0e", "#2ca02c"])
    ax.set_ylabel("Cross-source compound\ndisagreement % (N=110)", fontsize=9)
    ax.set_ylim(0, 70)
    for b, v in zip(bars, disagreement):
        ax.text(b.get_x() + b.get_width()/2, v + 1.5, f"{v:.1f}%",
                ha="center", fontsize=9, fontweight="bold")
    ax.set_title("B · Charge / tautomer reconciliation\n(W4 carry-fwd, 91 % reduction)",
                  fontsize=10)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)


def panel_c_v3_lift(ax, verdicts: list[dict]):
    """V3 best-variant lift per cohort, color-coded by verdict."""
    v3_rows = [r for r in verdicts if r["variant"] == "V3_soft_union"]
    cohorts = [r["cohort"] for r in v3_rows]
    a = [r["cond_a_prec"] * 100 for r in v3_rows]
    b = [r["cond_b_prec"] * 100 for r in v3_rows]
    verds = [r["verdict"] for r in v3_rows]
    deltas = [r["delta_pp"] for r in v3_rows]
    signs = [r["sign_p"] for r in v3_rows]

    xs = np.arange(len(cohorts))
    width = 0.35
    ax.bar(xs - width/2, a, width, color="#888888",
            label="A · RaMP baseline")
    bars_b = ax.bar(xs + width/2, b, width,
                     color=[VERDICT_COLOR[v] for v in verds],
                     label="B · V3 soft union")
    for i, (ai, bi, d, p, v) in enumerate(zip(a, b, deltas, signs, verds)):
        ax.text(i, max(ai, bi) + 4, f"Δ=+{d:.1f}pp\np={p:.3f}\n{v}",
                ha="center", fontsize=8)
    cohort_labels = [f"{c.upper()}\nN={r['n_tasks']}" for c, r in zip(cohorts, v3_rows)]
    ax.set_xticks(xs); ax.set_xticklabels(cohort_labels, fontsize=8)
    ax.set_ylabel("Precision@10 vs Cooke GT\n(name-fuzzy ≥ 0.5)", fontsize=9)
    ax.set_title("C · Gate-2 lift, V3 rank-weighted soft union\nbest variant of W7 3-variant comparison",
                  fontsize=10)
    ax.set_ylim(0, max(max(a) if a else 0, max(b) if b else 0) * 1.4 + 12)
    ax.legend(loc="upper right", fontsize=8)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)


def build_caption(verdicts, w6) -> str:
    v3 = [r for r in verdicts if r["variant"] == "V3_soft_union"]
    pri = next(r for r in v3 if r["cohort"] == "primary")
    sa = next(r for r in v3 if r["cohort"] == "sens_a")
    sb = next(r for r in v3 if r["cohort"] == "sens_b")
    bucket = w6["primary"]["jaccard_5x5"]["paradigm_bucket_mean"]
    return f"""# Fig 3 v4 Caption (≤150 words)

**Figure 3.** Cross-paradigm reconciliation. (A) Pathway-name Jaccard between
five tools on Cooke SAMBA PRIMARY (Human1, |z|>1, N={pri['n_tasks']}):
ORA×ORA={bucket['ora_ora']:.3f}, ORA×m/z={bucket['ora_mz']:.3f},
ORA×Network={bucket['ora_net']:.3f}, m/z×Network={bucket['mz_net']:.3f} —
cross-paradigm overlap dominated by namespace fragmentation, not biological
disagreement. (B) Charge/tautomer reconciliation reduces cross-source
compound disagreement 59.1%→5.5% (91% reduction; safeguarded RDKit
Uncharger + tautomer canonicalization). (C) Gate-2 precision@10 vs Cooke
in-silico ground truth (name-fuzzy ≥0.5): RaMP baseline (grey) vs **V3
rank-weighted soft-union consensus** (verdict-colored). PRIMARY GREEN:
Δ+{pri['delta_pp']:.1f}pp, p={pri['sign_p']:.3f}, 13/0 positive deltas. SENS_A
YELLOW: Δ+{sa['delta_pp']:.1f}pp. SENS_B YELLOW: Δ+{sb['delta_pp']:.1f}pp.
Soft-union beats strict intersection (V0=−19.6pp) by avoiding paradigm-driven
name-mismatch veto.

*In silico ground truth — Cooke 2025 SAMBA simulations, not experimental.*
"""


def main() -> int:
    verdicts = _load_verdicts()
    w6 = _load_w6_jaccard()

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    panel_a_paradigm_jaccard(axes[0], w6)
    panel_b_charge_reconciliation(axes[1])
    panel_c_v3_lift(axes[2], verdicts)
    plt.tight_layout()

    png = OUT / "fig3_v4.png"
    pdf = OUT / "fig3_v4.pdf"
    fig.savefig(png, dpi=300); fig.savefig(pdf)
    print(f"wrote {png}")
    print(f"wrote {pdf}")

    # CSV of underlying numbers (full 12 row + winner highlighted)
    csv_path = OUT / "fig3_v4_data.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(verdicts[0].keys()))
        w.writeheader()
        for r in verdicts:
            w.writerow(r)
    print(f"wrote {csv_path}")

    (OUT / "fig3_v4_caption.md").write_text(build_caption(verdicts, w6))
    print(f"wrote {OUT / 'fig3_v4_caption.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
