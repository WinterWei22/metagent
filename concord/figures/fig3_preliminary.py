"""Fig 3 preliminary 2-panel composite (W3 D5).

Reads Session 4 data (single source of truth in `data/investigation/fig3_toy/`):
    jaccard_data_n30.csv          → Panel A
    id_disagreement_cross_source.csv → Panel B

Produces (in `data/concord/fig3/`):
    fig3_preliminary.png  (300 DPI)
    fig3_preliminary.pdf  (vector)
    fig3_data.csv         (aggregated plot data, independently re-reviewable)

Panel A — Cross-method PA Jaccard matrix(3×3,seeds 42/41/40 merged):
    rows/cols = {ramp, sspa, mummichog}
    cell value = mean off-diagonal Jaccard over N=22 unique tasks
    cmap = greys (paper-printable B/W safe)

Panel B — Cross-source InChIKey disagreement two-layer bar:
    x-axis: 3 source pairs (chebi-hmdb / chebi-lipidmaps / hmdb-lipidmaps)
    y-axis: % disagreement
    Two bars per pair (side-by-side): block14 (connectivity) vs full InChIKey

The caption explicitly says "preliminary" — refined Fig 3 v2 in W4 末.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Headless matplotlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

logger = logging.getLogger(__name__)

JACCARD_CSV = WORKTREE / "data" / "investigation" / "fig3_toy" / "jaccard_data_n30.csv"
DISAGREE_CSV = WORKTREE / "data" / "investigation" / "fig3_toy" / "id_disagreement_cross_source.csv"

OUTPUT_DIR = WORKTREE / "data" / "concord" / "fig3"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Paper-style settings
plt.rcParams.update({
    "font.family": "DejaVu Sans",       # broad cross-platform availability
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.linewidth": 0.8,
    "legend.fontsize": 8,
})

METHODS = ("ramp", "sspa", "mummichog")
METHOD_LABEL = {"ramp": "RaMP\nORA", "sspa": "sspa\nORA", "mummichog": "mummichog"}


# ---------------------------------------------------------------------------
# Panel A — Cross-method Jaccard matrix
# ---------------------------------------------------------------------------


def aggregate_jaccard_matrix(df_jac: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Returns (mean_matrix, std_matrix) shape (3, 3) over N tasks."""
    M = np.full((3, 3), np.nan)
    S = np.full((3, 3), np.nan)
    for i, m1 in enumerate(METHODS):
        for j, m2 in enumerate(METHODS):
            sub = df_jac[(df_jac["method_a"] == m1) & (df_jac["method_b"] == m2)]
            if not sub.empty:
                M[i, j] = float(sub["jaccard"].mean())
                S[i, j] = float(sub["jaccard"].std())
    return M, S


def plot_panel_a(ax, M, S, n_tasks: int) -> None:
    """3×3 Jaccard heatmap, greyscale paper-printable."""
    im = ax.imshow(M, cmap="Greys", vmin=0, vmax=1, aspect="equal")
    ax.set_xticks(range(3))
    ax.set_yticks(range(3))
    ax.set_xticklabels([METHOD_LABEL[m] for m in METHODS])
    ax.set_yticklabels([METHOD_LABEL[m] for m in METHODS])
    for i in range(3):
        for j in range(3):
            if np.isnan(M[i, j]):
                txt = "—"
            else:
                txt = f"{M[i, j]:.3f}"
                if not np.isnan(S[i, j]) and S[i, j] > 0:
                    txt += f"\n±{S[i, j]:.2f}"
            color = "white" if (not np.isnan(M[i, j]) and M[i, j] > 0.5) else "black"
            ax.text(j, i, txt, ha="center", va="center", color=color,
                    fontsize=8, linespacing=1.0)
    ax.set_title(
        f"A. Top-10 pathway Jaccard\nacross PA methods (N={n_tasks} tasks)",
        loc="left",
    )
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Mean Jaccard", fontsize=8)
    cbar.ax.tick_params(labelsize=7)


# ---------------------------------------------------------------------------
# Panel B — Two-layer cross-source ID disagreement
# ---------------------------------------------------------------------------


def aggregate_id_disagreement(df_id: pd.DataFrame) -> pd.DataFrame:
    """Returns long-form DataFrame for plot:
        rows = (source_pair, layer) combinations
        columns: source_pair, layer, n_disagree, n_total, pct
    """
    sources = sorted(df_id["chem_data_source"].unique())
    n_sources_present = [(s1, s2) for i, s1 in enumerate(sources) for s2 in sources[i+1:]]

    rows = []
    for s1, s2 in n_sources_present:
        # For each hmdb_id (compound) with both s1 and s2 present, check
        # block14 vs full InChIKey agreement
        n_pair_block14 = 0; n_pair_full = 0
        n_disagree_block14 = 0; n_disagree_full = 0
        for hmdb_id, sub in df_id.groupby("hmdb_id"):
            sub_s1 = sub[sub["chem_data_source"] == s1]
            sub_s2 = sub[sub["chem_data_source"] == s2]
            if sub_s1.empty or sub_s2.empty:
                continue
            full_s1 = set(sub_s1["inchi_key"].dropna().tolist())
            full_s2 = set(sub_s2["inchi_key"].dropna().tolist())
            blk_s1 = set(sub_s1["inchi_key_prefix"].dropna().tolist())
            blk_s2 = set(sub_s2["inchi_key_prefix"].dropna().tolist())
            if not full_s1 or not full_s2:
                continue
            n_pair_full += 1
            if not (full_s1 & full_s2):
                n_disagree_full += 1
            if blk_s1 and blk_s2:
                n_pair_block14 += 1
                if not (blk_s1 & blk_s2):
                    n_disagree_block14 += 1
        if n_pair_full:
            rows.append({
                "source_pair": f"{s1}\nvs {s2}",
                "layer": "block14",
                "n_disagree": n_disagree_block14,
                "n_total": n_pair_block14,
                "pct": 100 * n_disagree_block14 / n_pair_block14 if n_pair_block14 else 0,
            })
            rows.append({
                "source_pair": f"{s1}\nvs {s2}",
                "layer": "full",
                "n_disagree": n_disagree_full,
                "n_total": n_pair_full,
                "pct": 100 * n_disagree_full / n_pair_full,
            })
    return pd.DataFrame(rows)


def plot_panel_b(ax, df_agg: pd.DataFrame) -> None:
    """Side-by-side bar:block14 vs full per source pair."""
    pairs = df_agg["source_pair"].unique().tolist()
    x = np.arange(len(pairs))
    width = 0.35

    block14_vals = []
    full_vals = []
    block14_ns = []
    full_ns = []
    for sp in pairs:
        sub = df_agg[df_agg["source_pair"] == sp]
        b14 = sub[sub["layer"] == "block14"]
        full = sub[sub["layer"] == "full"]
        block14_vals.append(float(b14["pct"].iloc[0]) if not b14.empty else 0)
        full_vals.append(float(full["pct"].iloc[0]) if not full.empty else 0)
        block14_ns.append(int(b14["n_total"].iloc[0]) if not b14.empty else 0)
        full_ns.append(int(full["n_total"].iloc[0]) if not full.empty else 0)

    bar1 = ax.bar(x - width / 2, block14_vals, width, label="block14 (connectivity)",
                   color="0.7", edgecolor="black", linewidth=0.5)
    bar2 = ax.bar(x + width / 2, full_vals, width, label="full InChIKey\n(+ charge + stereo)",
                   color="0.35", edgecolor="black", linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(pairs)
    ax.set_ylabel("% compounds with disagreement")
    ax.set_ylim(0, max(max(full_vals) * 1.2, 10))
    ax.set_title(
        "B. Cross-source InChIKey disagreement\n(RaMP chem_props, 3 sources)",
        loc="left",
    )
    ax.legend(loc="upper left", frameon=False, fontsize=7)
    # Annotate counts above each bar
    for rect, n in zip(bar1, block14_ns):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 0.5,
                f"n={n}", ha="center", va="bottom", fontsize=6)
    for rect, n in zip(bar2, full_ns):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 0.5,
                f"n={n}", ha="center", va="bottom", fontsize=6)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if not JACCARD_CSV.exists():
        raise SystemExit(f"❌ Missing Session 4 data: {JACCARD_CSV}")
    if not DISAGREE_CSV.exists():
        raise SystemExit(f"❌ Missing Session 4 data: {DISAGREE_CSV}")

    df_jac = pd.read_csv(JACCARD_CSV)
    n_tasks = df_jac["task_id"].nunique()
    M, S = aggregate_jaccard_matrix(df_jac)

    df_id = pd.read_csv(DISAGREE_CSV)
    df_agg = aggregate_id_disagreement(df_id)

    # Save plot data (independently reviewable)
    plot_data = []
    for i, m1 in enumerate(METHODS):
        for j, m2 in enumerate(METHODS):
            plot_data.append({
                "panel": "A",
                "method_a": m1,
                "method_b": m2,
                "mean_jaccard": float(M[i, j]),
                "std_jaccard": float(S[i, j]) if not np.isnan(S[i, j]) else 0.0,
            })
    for _, row in df_agg.iterrows():
        plot_data.append({
            "panel": "B",
            "source_pair": row["source_pair"].replace("\n", "_"),
            "layer": row["layer"],
            "n_disagree": int(row["n_disagree"]),
            "n_total": int(row["n_total"]),
            "pct": float(row["pct"]),
        })
    pd.DataFrame(plot_data).to_csv(OUTPUT_DIR / "fig3_data.csv", index=False)
    print(f"  fig3_data.csv  ({len(plot_data)} rows)")

    # Build composite figure (2 panels horizontal)
    fig = plt.figure(figsize=(8.5, 4))
    gs = GridSpec(1, 2, figure=fig, wspace=0.3)
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    plot_panel_a(ax_a, M, S, n_tasks)
    plot_panel_b(ax_b, df_agg)

    fig.suptitle(
        "Fig. 3 (preliminary). PA-method disagreement and cross-source ID "
        "disagreement\nmotivate ConcordMet reconciliation. "
        "Refined Fig. 3 v2 with full RDKit Uncharger normalization in W4.",
        fontsize=8, y=1.02,
    )
    plt.tight_layout()

    png = OUTPUT_DIR / "fig3_preliminary.png"
    pdf = OUTPUT_DIR / "fig3_preliminary.pdf"
    fig.savefig(png, dpi=300, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)
    print(f"  {png}  (300 DPI)")
    print(f"  {pdf}  (vector)")

    # Print summary numbers
    cross = [M[i, j] for i in range(3) for j in range(3) if i != j and not np.isnan(M[i, j])]
    mean_cross = float(np.mean(cross)) if cross else float("nan")
    print(f"\n  Panel A mean off-diagonal Jaccard: {mean_cross:.4f}")
    print(f"  Panel B # source pairs with data: {df_agg['source_pair'].nunique()}")
    print(f"  → Fig 3 preliminary DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
