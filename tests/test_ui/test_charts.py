"""Smoke tests for ui.rendering.candidate_charts."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _sample_candidates() -> list[dict]:
    return [
        {
            "candidate": {"smiles": "CCO", "name": "Ethanol", "source": "library", "score": 0.82},
            "metabolite_info": {"found": True, "primary_name": "Ethanol"},
            "predicted_spectrum_cosine": 0.6,
            "mass_match_indicator": 1.0,
            "pathway_presence_indicator": 1.0,
            "evidence_score": 0.768,
        },
        {
            "candidate": {"smiles": "CC(=O)O", "name": "Acetate", "source": "library", "score": 0.7},
            "metabolite_info": {"found": True, "primary_name": "Acetate"},
            "predicted_spectrum_cosine": 0.5,
            "mass_match_indicator": 1.0,
            "pathway_presence_indicator": 0.0,
            "evidence_score": 0.63,
        },
        {
            "candidate": {"smiles": "CCCCO", "name": None, "source": "generated", "score": 0.55},
            "metabolite_info": {"found": False},
            "predicted_spectrum_cosine": 0.3,
            "mass_match_indicator": 1.0,
            "pathway_presence_indicator": 0.0,
            "evidence_score": 0.41,
        },
    ]


def test_plot_evidence_by_source_returns_figure() -> None:
    from matplotlib.figure import Figure
    from ui.rendering.candidate_charts import plot_evidence_by_source

    fig = plot_evidence_by_source(_sample_candidates())
    assert isinstance(fig, Figure)
    assert len(fig.axes) == 1


def test_plot_evidence_by_source_empty_input() -> None:
    from ui.rendering.candidate_charts import plot_evidence_by_source

    fig = plot_evidence_by_source([])
    assert fig is not None
    fig_none = plot_evidence_by_source(None)
    assert fig_none is not None


def test_plot_score_components_returns_figure() -> None:
    from matplotlib.figure import Figure
    from ui.rendering.candidate_charts import plot_score_components

    fig = plot_score_components(_sample_candidates())
    assert isinstance(fig, Figure)
    # One axis, four stacked bars per candidate → legend should have 4 entries.
    ax = fig.axes[0]
    legend = ax.get_legend()
    assert legend is not None
    assert len(legend.get_texts()) == 4


def test_plot_score_components_empty_input() -> None:
    from ui.rendering.candidate_charts import plot_score_components

    assert plot_score_components([]) is not None
    assert plot_score_components(None) is not None


def test_charts_handle_candidates_over_ten() -> None:
    """Charts clamp to top-10 so large reports don't bloat the figure."""
    from ui.rendering.candidate_charts import (
        plot_evidence_by_source, plot_score_components,
    )
    many = _sample_candidates() * 5  # 15 rows
    f1 = plot_evidence_by_source(many)
    f2 = plot_score_components(many)
    assert f1 is not None and f2 is not None
