"""Smoke tests for ui.rendering.spectrum_plot and ui.rendering.molecule_img."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def test_plot_spectrum_returns_figure_with_axes() -> None:
    from matplotlib.figure import Figure

    from ui.rendering.spectrum_plot import plot_spectrum

    fig = plot_spectrum(
        {
            "mz": [60.0, 91.0, 120.0, 163.1],
            "intensity": [0.2, 0.5, 0.9, 1.0],
            "precursor_mz": 181.0707,
            "adduct": "[M+H]+",
            "ionization_mode": "positive",
        },
        neutral_mass=180.0634,
        quality_flag="sparse",
    )
    assert isinstance(fig, Figure)
    assert len(fig.axes) == 1
    assert fig.axes[0].get_xlabel() == "m/z"


def test_plot_spectrum_empty_peaks_does_not_crash() -> None:
    from ui.rendering.spectrum_plot import plot_spectrum

    fig = plot_spectrum({"mz": [], "intensity": [], "precursor_mz": 100.0})
    assert fig is not None


def test_molecule_img_renders_valid_smiles() -> None:
    from ui.rendering.molecule_img import smiles_to_image

    img = smiles_to_image("CCO", size=(150, 150))
    assert img.size == (150, 150)
    assert img.mode == "RGB"


def test_molecule_img_fallback_on_invalid_smiles() -> None:
    from ui.rendering.molecule_img import smiles_to_image

    img = smiles_to_image("not a smiles at all", size=(150, 150))
    assert img.size == (150, 150)


def test_molecule_img_handles_empty_string() -> None:
    from ui.rendering.molecule_img import smiles_to_image

    img = smiles_to_image("", size=(150, 150))
    assert img.size == (150, 150)


def test_molecule_img_handles_none() -> None:
    from ui.rendering.molecule_img import smiles_to_image

    img = smiles_to_image(None, size=(150, 150))
    assert img.size == (150, 150)
