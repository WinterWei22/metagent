"""Mirror-plot overlay of experimental spectrum vs CFM-ID predicted spectrum.

Classic MS/MS comparison style:
  • Experimental spectrum drawn on +y axis in black
  • Predicted spectrum reflected onto -y axis in red
  • Shared m/z axis; precursor peak highlighted on the experimental side
  • Title bar carries cosine score, model version, candidate name

Headless (Agg) matplotlib.
"""
from __future__ import annotations

from typing import Any

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure


_EXP_COLOUR = "#111827"   # near-black
_PRED_COLOUR = "#dc2626"  # red-600


def plot_overlay(
    experimental: dict[str, Any],
    predicted: dict[str, Any] | None,
    *,
    cosine: float | None = None,
    candidate_name: str | None = None,
    model_version: str | None = None,
) -> Figure:
    """Return a matplotlib Figure with experimental (top) vs predicted
    (bottom, mirrored) stem plots.

    `predicted` may be None — in that case only the experimental side
    renders and the title says so explicitly.
    """
    exp_mz = list(experimental.get("mz") or [])
    exp_int = list(experimental.get("intensity") or [])
    exp_precursor = float(experimental.get("precursor_mz") or 0.0)

    if predicted is None:
        pred_mz: list[float] = []
        pred_int: list[float] = []
    else:
        pred_mz = list(predicted.get("mz") or [])
        raw = list(predicted.get("intensity") or [])
        # Normalise predicted to [0, 1] so the mirror plot has symmetric scale.
        m = max(raw) if raw else 0.0
        pred_int = [float(v) / m for v in raw] if m > 0 else [0.0 for _ in raw]

    fig, ax = plt.subplots(figsize=(7.4, 4.0), dpi=110)
    ax.set_facecolor("white")
    ax.axhline(0, color="#9ca3af", linewidth=0.5)

    # Experimental on +y
    if exp_mz and exp_int:
        ml, sl, _ = ax.stem(
            exp_mz, exp_int, basefmt=" ",
            linefmt="-", markerfmt=" ",
        )
        sl.set_color(_EXP_COLOUR)
        sl.set_linewidth(1.2)
        ml.set_color(_EXP_COLOUR)
        # Precursor highlight
        for i, m in enumerate(exp_mz):
            if abs(m - exp_precursor) < 1e-3:
                ax.plot([m], [exp_int[i]], "o", color="#f97316", markersize=6)
                ax.annotate(
                    f"precursor\n{m:.4f}",
                    xy=(m, exp_int[i]),
                    xytext=(6, 6), textcoords="offset points",
                    fontsize=7, color="#c2410c",
                )
                break

    # Predicted on -y (mirrored)
    if pred_mz and pred_int:
        mirrored = [-v for v in pred_int]
        ml, sl, _ = ax.stem(
            pred_mz, mirrored, basefmt=" ",
            linefmt="-", markerfmt=" ",
        )
        sl.set_color(_PRED_COLOUR)
        sl.set_linewidth(1.2)
        ml.set_color(_PRED_COLOUR)

    # Y-axis labelling: symmetric
    ax.set_ylim(-1.08, 1.08)
    ax.set_yticks([-1.0, -0.5, 0.0, 0.5, 1.0])
    ax.set_yticklabels(["1.0", "0.5", "0", "0.5", "1.0"], fontsize=8)
    ax.set_xlabel("m/z")
    ax.text(
        0.01, 0.97, "experimental",
        transform=ax.transAxes, fontsize=8, color=_EXP_COLOUR,
        va="top",
    )
    ax.text(
        0.01, 0.03, "CFM-ID predicted (mirrored)",
        transform=ax.transAxes, fontsize=8, color=_PRED_COLOUR,
        va="bottom",
    )

    parts: list[str] = []
    if candidate_name:
        parts.append(str(candidate_name))
    if cosine is not None:
        parts.append(f"cosine = {float(cosine):.3f}")
    else:
        parts.append("cosine = —")
    if model_version:
        parts.append(str(model_version))
    ax.set_title("   ·   ".join(parts), loc="left", fontsize=10)
    ax.grid(axis="x", linestyle=":", alpha=0.35)
    fig.tight_layout()
    return fig


def caption_for_overlay(
    *,
    candidate_name: str | None,
    cosine: float | None,
    n_exp_peaks: int,
    n_pred_peaks: int,
    predicted_available: bool,
    model_version: str | None = None,
) -> str:
    """Short markdown blurb under the overlay plot explaining what reviewer
    is looking at + how cosine was computed."""
    if not predicted_available:
        return (
            "<small style='color:#6b7280'>"
            "_Predicted spectrum not available for this cached run._ "
            "The three original Track O1 fixtures do not carry a side-car "
            "of per-candidate predicted spectra — those were produced "
            "before the UI persisted CFM-ID output. Re-run Live or pick "
            "the <code>glucose_pos_fusion</code> cached run to see overlays."
            "</small>"
        )
    cos_str = f"{cosine:.3f}" if cosine is not None else "—"
    who = candidate_name or "(unnamed candidate)"
    mv = f" ({model_version})" if model_version else ""
    return (
        f"<small style='color:#6b7280'>"
        f"Comparing the <b>experimental</b> spectrum (top, black) against "
        f"CFM-ID's <b>predicted</b> spectrum for <b>{who}</b>{mv}, shown "
        f"mirrored below in red. "
        f"<b>Modified-cosine similarity</b> between the two (match m/z "
        f"within tolerance, weighted by intensity; precursor-shifted "
        f"peaks also contribute) = <b>{cos_str}</b>. "
        f"Peaks: experimental {n_exp_peaks}, predicted {n_pred_peaks}. "
        f"A higher cosine means the predicted fragmentation pattern "
        f"agrees more closely with what the mass-spec actually produced — "
        f"evidence that the candidate structure fragments the way the "
        f"instrument saw."
        f"</small>"
    )
