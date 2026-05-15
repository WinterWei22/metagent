"""Fig 3 v2 refined — Panel A unchanged, Panel B upgraded with Uncharger
reconciliation lift (W4 D5).

Panel A: PA method × method Jaccard heatmap (N=22 unique tasks from Session 4,
         identical to v1 preliminary).

Panel B: Cross-source InChIKey disagreement two-layer + reconciliation lift.
         Per source-pair (chebi-hmdb / chebi-lipidmaps / hmdb-lipidmaps):
            4 bars: block14 raw / block14 reconciled / full raw / full reconciled
         Disagreement % = 100 - match %.
         Annotation: 'reconciliation halves full-layer disagreement' style.

Reads:
    data/investigation/fig3_toy/jaccard_data_n30.csv (Session 4 — Panel A)
    data/concord/fig3/uncharger_summary.json        (W4 Background F — Panel B)

Outputs:
    data/concord/fig3/fig3_v2_refined.png  (300 DPI)
    data/concord/fig3/fig3_v2_refined.pdf  (vector)
    data/concord/fig3/fig3_v2_data.csv     (aggregated plot data)

Preserves fig3_preliminary.* — paper supplementary uses both.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.gridspec import GridSpec

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

JACCARD_CSV = WORKTREE / "data" / "investigation" / "fig3_toy" / "jaccard_data_n30.csv"
UNCHARGER_JSON = WORKTREE / "data" / "concord" / "fig3" / "uncharger_summary.json"
OUTPUT_DIR = WORKTREE / "data" / "concord" / "fig3"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.linewidth": 0.8,
    "legend.fontsize": 7,
})

METHODS = ("ramp", "sspa", "mummichog")
METHOD_LABEL = {"ramp": "RaMP\nORA", "sspa": "sspa\nORA", "mummichog": "mummichog"}


def aggregate_jaccard_matrix(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    M = np.full((3, 3), np.nan)
    S = np.full((3, 3), np.nan)
    for i, m1 in enumerate(METHODS):
        for j, m2 in enumerate(METHODS):
            sub = df[(df["method_a"] == m1) & (df["method_b"] == m2)]
            if not sub.empty:
                M[i, j] = float(sub["jaccard"].mean())
                S[i, j] = float(sub["jaccard"].std())
    return M, S


def plot_panel_a(ax, M, S, n_tasks):
    im = ax.imshow(M, cmap="Greys", vmin=0, vmax=1, aspect="equal")
    ax.set_xticks(range(3)); ax.set_xticklabels([METHOD_LABEL[m] for m in METHODS])
    ax.set_yticks(range(3)); ax.set_yticklabels([METHOD_LABEL[m] for m in METHODS])
    for i in range(3):
        for j in range(3):
            txt = "—" if np.isnan(M[i, j]) else f"{M[i, j]:.3f}"
            if not np.isnan(M[i, j]) and not np.isnan(S[i, j]) and S[i, j] > 0:
                txt += f"\n±{S[i, j]:.2f}"
            color = "white" if (np.isnan(M[i, j]) or M[i, j] > 0.5) else "black"
            ax.text(j, i, txt, ha="center", va="center", color=color,
                    fontsize=8, linespacing=1.0)
    ax.set_title(
        f"A. Top-10 pathway Jaccard\nacross PA methods (N={n_tasks} tasks)",
        loc="left",
    )
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Mean Jaccard", fontsize=8)
    cbar.ax.tick_params(labelsize=7)


def plot_panel_b(ax, uncharger: dict):
    pairs_raw = uncharger["by_source_pair"]
    pair_keys = list(pairs_raw.keys())  # e.g. "chebi__hmdb"
    n_pairs = len(pair_keys)
    x = np.arange(n_pairs)
    width = 0.18

    raw_b14_dis = []     # disagreement = 100 - match
    rec_b14_dis = []
    raw_full_dis = []
    rec_full_dis = []
    n_per_pair = []
    labels = []
    for k in pair_keys:
        p = pairs_raw[k]
        raw_b14_dis.append(100 - p["raw_block14_match_pct"])
        rec_b14_dis.append(100 - p["reconciled_block14_match_pct"])
        raw_full_dis.append(100 - p["raw_full_match_pct"])
        rec_full_dis.append(100 - p["reconciled_full_match_pct"])
        n_per_pair.append(p["n_pairs"])
        a, b = k.split("__")
        labels.append(f"{a}\nvs {b}")

    bars_raw_b = ax.bar(x - 1.5 * width, raw_b14_dis, width,
                       label="block14 raw", color="0.85", edgecolor="black", linewidth=0.5)
    bars_rec_b = ax.bar(x - 0.5 * width, rec_b14_dis, width,
                       label="block14 reconciled", color="0.6", edgecolor="black", linewidth=0.5)
    bars_raw_f = ax.bar(x + 0.5 * width, raw_full_dis, width,
                       label="full raw", color="0.35", edgecolor="black", linewidth=0.5)
    bars_rec_f = ax.bar(x + 1.5 * width, rec_full_dis, width,
                       label="full reconciled", color="0.1", edgecolor="black", linewidth=0.5)

    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("% compound-pairs with disagreement")
    ax.set_ylim(0, max(60, max(raw_full_dis) * 1.15) if raw_full_dis else 60)
    ax.set_title(
        "B. Cross-source InChIKey disagreement\n"
        "raw vs RDKit Uncharger reconciliation",
        loc="left",
    )
    ax.legend(loc="upper right", frameon=False, ncol=2)
    for rect, n in zip(bars_raw_b, n_per_pair):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 1.0,
                f"n={n}", ha="center", va="bottom", fontsize=6.5)

    # Aggregate annotation
    agg = uncharger["aggregate"]
    raw_full = 100 - agg["raw_full_match_pct"]
    rec_full = 100 - agg["reconciled_full_match_pct"]
    ax.text(0.02, 0.95,
            f"aggregate full-layer disagreement:\n"
            f"  raw → reconciled  =  {raw_full:.0f}% → {rec_full:.0f}%",
            transform=ax.transAxes, fontsize=7, va="top",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="0.6", lw=0.5))


def main() -> int:
    if not JACCARD_CSV.exists():
        raise SystemExit(f"❌ Missing {JACCARD_CSV}")
    if not UNCHARGER_JSON.exists():
        raise SystemExit(f"❌ Missing {UNCHARGER_JSON} — run "
                         f"_reconcile_cross_source.py first")

    df_jac = pd.read_csv(JACCARD_CSV)
    n_tasks = df_jac["task_id"].nunique()
    M, S = aggregate_jaccard_matrix(df_jac)
    uncharger = json.loads(UNCHARGER_JSON.read_text())

    # Save plot data
    plot_data = []
    for i, m1 in enumerate(METHODS):
        for j, m2 in enumerate(METHODS):
            plot_data.append({
                "panel": "A",
                "method_a": m1, "method_b": m2,
                "mean_jaccard": float(M[i, j]) if not np.isnan(M[i, j]) else None,
                "std_jaccard": float(S[i, j]) if not np.isnan(S[i, j]) else None,
            })
    for pair_key, p in uncharger["by_source_pair"].items():
        plot_data.append({
            "panel": "B", "source_pair": pair_key, "n_pairs": p["n_pairs"],
            "raw_block14_disagreement_pct": 100 - p["raw_block14_match_pct"],
            "raw_full_disagreement_pct": 100 - p["raw_full_match_pct"],
            "reconciled_block14_disagreement_pct": 100 - p["reconciled_block14_match_pct"],
            "reconciled_full_disagreement_pct": 100 - p["reconciled_full_match_pct"],
        })
    pd.DataFrame(plot_data).to_csv(OUTPUT_DIR / "fig3_v2_data.csv", index=False)
    print(f"  fig3_v2_data.csv  ({len(plot_data)} rows)")

    fig = plt.figure(figsize=(10, 4.2))
    gs = GridSpec(1, 2, figure=fig, wspace=0.35, width_ratios=[1, 1.3])
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    plot_panel_a(ax_a, M, S, n_tasks)
    plot_panel_b(ax_b, uncharger)

    agg = uncharger["aggregate"]
    fig.suptitle(
        "Fig. 3 (v2, refined). PA-method disagreement (Panel A) motivates ConcordMet "
        f"reconciliation; cross-source InChIKey disagreement (Panel B) is reduced "
        f"{100 - agg['raw_full_match_pct']:.0f}% → {100 - agg['reconciled_full_match_pct']:.0f}% "
        "(full-layer aggregate) by RDKit Uncharger + tautomer canonicalization.",
        fontsize=8, y=1.04,
    )
    plt.tight_layout()
    png = OUTPUT_DIR / "fig3_v2_refined.png"
    pdf = OUTPUT_DIR / "fig3_v2_refined.pdf"
    fig.savefig(png, dpi=300, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)
    print(f"  {png}  (300 DPI)")
    print(f"  {pdf}  (vector)")

    print()
    cross_means = [M[i, j] for i in range(3) for j in range(3)
                    if i != j and not np.isnan(M[i, j])]
    mean_cross = float(np.mean(cross_means)) if cross_means else float("nan")
    print(f"  Panel A mean off-diagonal Jaccard: {mean_cross:.4f}")
    print(f"  Panel B reconciliation lift:")
    print(f"    aggregate full-layer disagreement: "
          f"{100-agg['raw_full_match_pct']:.1f}% → {100-agg['reconciled_full_match_pct']:.1f}%")
    print("→ Fig 3 v2 refined DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
