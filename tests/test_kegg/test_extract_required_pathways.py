"""Unit tests for scripts.kegg.extract_required_pathways."""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from scripts.kegg.extract_required_pathways import (
    _extract_compound_pair,
    _normalise_kegg_id,
)


# ---- _normalise_kegg_id ----------------------------------------------------


@pytest.mark.parametrize("inp,expected", [
    ("map00270", "hsa00270"),
    ("hsa00270", "hsa00270"),
    ("ko00270", "hsa00270"),
    ("00270", "hsa00270"),
    ("path:hsa00270", "hsa00270"),
    ("path:map00270", "hsa00270"),
    ("HSA00270", "hsa00270"),  # case-insensitive
    ("WP430", None),       # WikiPathways ID is not KEGG
    ("SMP00169", None),    # SMPDB ID is not KEGG
    (None, None),
    ("", None),
    ("garbage", None),
])
def test_normalise_kegg_id(inp, expected):
    assert _normalise_kegg_id(inp) == expected


# ---- _extract_compound_pair ----------------------------------------------


@pytest.mark.parametrize("text,expected_a,expected_b", [
    # Real claims from the v2 verdicts JSONL.
    ("Methionine is upstream of homocysteine generation",
     "Methionine", "homocysteine generation"),
    ("UMP is upstream of UDP in the phosphorylation cascade",
     "UMP", "UDP"),
    ("Cysteine is upstream of glutathione",
     "Cysteine", "glutathione"),
    ("Pyruvate is upstream of TCA",
     "Pyruvate", "TCA"),
    ("Histidine is upstream of cis-urocanic acid",
     "Histidine", "cis-urocanic acid"),
    ("Ureidosuccinic acid is upstream of UMP",
     "Ureidosuccinic acid", "UMP"),
    ("L-Methionine feeds into S-adenosylmethionine (SAM)",
     "L-Methionine", "S-adenosylmethionine (SAM)"),
    ("DOPAL formation is downstream of monoamine oxidase activity",
     "DOPAL formation", "monoamine oxidase activity"),
    ("UTP feeds into glycogen metabolism via UDP-glucose",
     "UTP", "glycogen metabolism"),
    ("Methylation reactions are downstream of SAM",
     "Methylation reactions", "SAM"),
])
def test_extract_compound_pair_real_claims(text, expected_a, expected_b):
    a, b = _extract_compound_pair(text)
    assert a == expected_a, f"subject extraction failed: got {a!r}"
    assert b == expected_b, f"object extraction failed: got {b!r}"


def test_extract_compound_pair_no_relationship_keyword():
    a, b = _extract_compound_pair(
        "Methionine plays a role in transsulfuration"
    )
    assert (a, b) == (None, None)


def test_extract_compound_pair_collapses_whitespace():
    """Multi-line / extra whitespace shouldn't break the extractor —
    LLM narrative fragments occasionally contain artefacts."""
    a, b = _extract_compound_pair(
        "Methionine\n   is upstream of\thomocysteine\n"
    )
    assert a == "Methionine" and b == "homocysteine"
