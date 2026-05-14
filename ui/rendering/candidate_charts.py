"""Candidate-level chart rendering for Panel 2 (Pipeline output).

Two plots, both headless matplotlib (Agg backend set by spectrum_plot):

1. `plot_evidence_by_source` — horizontal bar, y=rank+name, x=evidence_score,
   bar colour by candidate provenance (library / generated / reference).
   Conveys "B dominates top ranks, C contributes the mid/tail" at a glance.

2. `plot_score_components` — vertical stacked bar, one column per rank,
   stacked by the evidence-score weight formula
   (0.4·B_score + 0.3·cosine + 0.2·mass_match + 0.1·pathway_presence).
   Shows which tool actually produced each candidate's evidence.

Neither plot mutates the report dict or touches the LLM.
"""
from __future__ import annotations

from typing import Any

import matplotlib
matplotlib.use("Agg")  # must match spectrum_plot
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Patch


# Scoring weights — mirror schemas.report's declared constants. Kept local
# so the UI layer doesn't import them (that would break in envs without
# the project's schemas package — UI should render what's on disk, not
# recompute it).
_W_CANDIDATE = 0.4
_W_PREDICTED_COSINE = 0.3
_W_MASS_MATCH = 0.2
_W_PATHWAY_PRESENCE = 0.1

_SOURCE_COLOUR = {
    "library":   "#2563eb",  # blue
    "generated": "#ea580c",  # orange
    "reference": "#6b7280",  # gray
}

_COMPONENT_COLOUR = {
    "cand":    "#2563eb",  # blue   (B/C candidate_score)
    "cosine":  "#7c3aed",  # purple (E predicted cosine)
    "mass":    "#059669",  # green  (SMILES-derived mass match)
    "pathway": "#d97706",  # amber  (D2 pathway presence)
}

_MAX_BARS = 10


def _best_name(cand_report: dict[str, Any]) -> str:
    info = cand_report.get("metabolite_info") or {}
    if info.get("found") and info.get("primary_name"):
        return info["primary_name"]
    pref = cand_report.get("prefilter_match") or {}
    if pref.get("name"):
        return pref["name"]
    return (cand_report.get("candidate") or {}).get("name") or "(unnamed)"


def _truncate(s: str, n: int = 28) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _empty_figure(msg: str, size=(7.0, 3.0)) -> Figure:
    fig, ax = plt.subplots(figsize=size, dpi=110)
    ax.text(0.5, 0.5, msg, ha="center", va="center",
            transform=ax.transAxes, color="#6b7280")
    ax.axis("off")
    return fig


def plot_evidence_by_source(candidates: list[dict[str, Any]] | None) -> Figure:
    """Horizontal bar chart: candidate evidence colour-coded by provenance."""
    if not candidates:
        return _empty_figure("(no candidates to plot)")

    rows = candidates[:_MAX_BARS]
    ranks = list(range(1, len(rows) + 1))
    scores = [float(c.get("evidence_score") or 0.0) for c in rows]
    sources = [(c.get("candidate") or {}).get("source", "?") for c in rows]
    labels = [f"#{r}  {_truncate(_best_name(c))}" for r, c in zip(ranks, rows)]
    colours = [_SOURCE_COLOUR.get(s, "#9ca3af") for s in sources]

    h = max(2.6, 0.38 * len(rows) + 1.2)
    fig, ax = plt.subplots(figsize=(7.2, h), dpi=110)
    y = np.arange(len(rows))
    ax.barh(y, scores, color=colours, edgecolor="white", height=0.72)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.invert_yaxis()  # rank 1 on top
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("evidence_score")
    ax.set_title(
        "Candidate evidence — B (library match) vs C (de novo)",
        loc="left", fontsize=10,
    )

    legend_handles = [
        Patch(facecolor=_SOURCE_COLOUR["library"],   label="B — library match"),
        Patch(facecolor=_SOURCE_COLOUR["generated"], label="C — de novo generated"),
    ]
    if "reference" in sources:
        legend_handles.append(
            Patch(facecolor=_SOURCE_COLOUR["reference"], label="reference")
        )
    ax.legend(handles=legend_handles, loc="lower right", fontsize=8,
              framealpha=0.92)
    ax.grid(axis="x", linestyle=":", alpha=0.45)
    fig.tight_layout()
    return fig


def plot_score_components(candidates: list[dict[str, Any]] | None) -> Figure:
    """Stacked bar per candidate showing evidence_score's 4 weighted parts."""
    if not candidates:
        return _empty_figure("(no candidates to plot)")

    rows = candidates[:_MAX_BARS]
    n = len(rows)
    x = np.arange(1, n + 1)

    cand_part    = np.array([_W_CANDIDATE *
                             float((c.get("candidate") or {}).get("score") or 0.0)
                             for c in rows])
    cos_part     = np.array([_W_PREDICTED_COSINE *
                             float(c.get("predicted_spectrum_cosine") or 0.0)
                             for c in rows])
    mass_part    = np.array([_W_MASS_MATCH *
                             float(c.get("mass_match_indicator") or 0.0)
                             for c in rows])
    pathway_part = np.array([_W_PATHWAY_PRESENCE *
                             float(c.get("pathway_presence_indicator") or 0.0)
                             for c in rows])

    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=110)
    width = 0.68
    bottom = np.zeros(n)

    stacks = [
        ("0.4 × B/C candidate_score", cand_part,    _COMPONENT_COLOUR["cand"]),
        ("0.3 × predicted cosine",    cos_part,     _COMPONENT_COLOUR["cosine"]),
        ("0.2 × mass match",          mass_part,    _COMPONENT_COLOUR["mass"]),
        ("0.1 × pathway presence",    pathway_part, _COMPONENT_COLOUR["pathway"]),
    ]
    for label, vals, colour in stacks:
        ax.bar(x, vals, width, bottom=bottom, label=label,
               color=colour, edgecolor="white", linewidth=0.6)
        bottom = bottom + vals

    # Mark the source under each rank tick (library/generated/…).
    sources = [(c.get("candidate") or {}).get("source", "?") for c in rows]
    tick_labels = [f"#{i}\n{s}" for i, s in zip(x, sources)]
    ax.set_xticks(x)
    ax.set_xticklabels(tick_labels, fontsize=8)
    ax.set_ylabel("evidence contribution")
    ax.set_ylim(0, 1.06)
    ax.set_title(
        "Evidence breakdown per candidate (by scoring-formula weights)",
        loc="left", fontsize=10,
    )
    ax.legend(fontsize=7.5, loc="upper right", framealpha=0.94, ncol=1)
    ax.grid(axis="y", linestyle=":", alpha=0.45)
    fig.tight_layout()
    return fig
