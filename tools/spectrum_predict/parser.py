"""Parse CFM-ID 4.0's text output into structured peak lists.

CFM-ID's ``cfm-predict`` binary writes a single text block containing three
energy ramps, delimited by the literal headers ``energy0`` / ``energy1`` /
``energy2`` — low / medium / high — which correspond by convention to the
10 / 20 / 40 eV pre-trained models. Example::

    energy0
    50.0386 2.92 1 2
    91.0548 18.96 3
    ...
    energy1
    50.0386 1.50
    ...
    energy2
    50.0386 0.90
    ...

Each peak line is ``<mz> <intensity>`` optionally followed by fragment
identifiers (space-separated integers) that CFM-ID assigns to every peak. The
tool's downstream consumers only need ``(mz, intensity)`` pairs; the fragment
IDs are dropped here. A trailing block after the three energies sometimes
lists full fragment SMILES — we stop at the first line that does not begin
with an ``energy``-header and does not parse as two floats.

This module deliberately does not depend on anything else in the codebase so
the tests can exercise the parser with raw text fixtures.
"""
from __future__ import annotations

import re

# Header pattern CFM-ID 4.0 emits. Numbered 0..2 regardless of the requested
# collision energy, because the binary always runs the three fixed models.
_ENERGY_HEADER = re.compile(r"^\s*energy\s*([0-2])\s*$", re.IGNORECASE)


def parse_cfm_output(text: str) -> dict[int, list[tuple[float, float]]]:
    """Parse raw ``cfm-predict`` stdout.

    Returns a dict keyed by CFM-ID energy index (0, 1, 2) with a list of
    ``(mz, intensity)`` tuples per block. The caller is responsible for
    mapping energy indices onto eV labels and for normalising intensities;
    this function returns the raw numbers as emitted by CFM-ID.

    An unparseable line inside an energy block stops parsing of that block
    only. A completely empty block yields an empty list for that index —
    not an error, because CFM-ID can legitimately predict zero peaks at a
    given energy for very small molecules.
    """
    blocks: dict[int, list[tuple[float, float]]] = {}
    current: int | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header = _ENERGY_HEADER.match(line)
        if header is not None:
            current = int(header.group(1))
            blocks.setdefault(current, [])
            continue

        if current is None:
            # Leading preamble lines before the first `energy0` — ignore.
            continue

        parts = line.split()
        if len(parts) < 2:
            # Inside a block but the line has no peak data — treat as the
            # start of the fragment-annotation trailer and stop consuming
            # peaks for every remaining block.
            current = None
            continue

        try:
            mz = float(parts[0])
            intensity = float(parts[1])
        except ValueError:
            # Non-numeric leader → annotation trailer started.
            current = None
            continue

        blocks[current].append((mz, intensity))

    return blocks


def sort_and_dedup(peaks: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sort peaks by m/z ascending and collapse exact-duplicate m/z values.

    CFM-ID occasionally reports the same m/z twice within one energy block
    when two fragments share an exact mass — keep the larger intensity.
    ``Spectrum`` validation downstream assumes sorted m/z and requires
    one intensity per m/z, so enforce both here before constructing the
    Pydantic object.
    """
    if not peaks:
        return []
    best: dict[float, float] = {}
    for mz, intensity in peaks:
        prev = best.get(mz)
        if prev is None or intensity > prev:
            best[mz] = intensity
    return sorted(best.items(), key=lambda p: p[0])


def normalise(peaks: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Rescale so the base peak has intensity 1.0; drop non-positive peaks.

    CFM-ID emits intensities on an arbitrary positive scale. The schema
    requires ``intensity ∈ [0, 1]`` with the base peak at exactly 1.0, so
    every ``Spectrum`` we build has to be renormalised at construction.
    """
    kept = [(mz, i) for mz, i in peaks if i > 0]
    if not kept:
        return []
    base = max(i for _, i in kept)
    return [(mz, i / base) for mz, i in kept]
