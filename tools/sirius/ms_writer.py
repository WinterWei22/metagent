"""Write project ``Spectrum`` objects in SIRIUS ``.ms`` format."""
from __future__ import annotations

from pathlib import Path

from schemas.common import Spectrum


def spectrum_to_ms_text(spectrum: Spectrum, *, compound_id: str = "query") -> str:
    """Render a ``Spectrum`` as SIRIUS plain-text ``.ms`` input."""
    lines = [
        f">compound {compound_id}",
        f">parentmass {spectrum.precursor_mz:.6f}",
        f">ionization {spectrum.adduct}",
    ]
    if spectrum.collision_energy is not None:
        lines.append(f">collision {spectrum.collision_energy:g}")

    for mz, intensity in zip(spectrum.mz, spectrum.intensity, strict=True):
        lines.append(f"{mz:.6f} {float(intensity) * 100.0:.6f}")
    return "\n".join(lines) + "\n"


def write_ms_file(
    spectrum: Spectrum,
    path: str | Path,
    *,
    compound_id: str = "query",
) -> Path:
    """Write ``spectrum`` to ``path`` and return the created path."""
    out = Path(path)
    out.write_text(
        spectrum_to_ms_text(spectrum, compound_id=compound_id),
        encoding="utf-8",
    )
    return out


def read_ms_peaks(path: str | Path) -> list[tuple[float, float]]:
    """Read peak rows from a simple SIRIUS ``.ms`` file.

    This intentionally parses only the peak table used by our writer; metadata
    lines beginning with ``>`` are ignored.
    """
    peaks: list[tuple[float, float]] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(">"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        peaks.append((float(parts[0]), float(parts[1])))
    return peaks
