"""Unit tests for evaluation.sub6.pathway_extract."""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.pathway_extract import (
    extract_compound_mentions,
    extract_driver_mentions,
    extract_pathway_mentions,
)


# ---------------- pathway extraction ----------------------------------------


def test_extracts_pathway_metabolism():
    out = extract_pathway_mentions(
        "The differential profile points to Tyrosine metabolism most strongly."
    )
    assert [m.text for m in out] == ["Tyrosine metabolism"]


def test_dedupes_repeated_pathway_mention():
    out = extract_pathway_mentions(
        "Tyrosine metabolism is implicated. Tyrosine metabolism contributes most signal."
    )
    assert len(out) == 1


def test_preserves_first_occurrence_order():
    text = (
        "First, Tyrosine metabolism. "
        "Second, Phenylalanine biosynthesis. "
        "Third, the urea cycle."
    )
    out = [m.text for m in extract_pathway_mentions(text)]
    assert out[0] == "Tyrosine metabolism"
    assert out[1] == "Phenylalanine biosynthesis"
    # 'urea cycle' has lowercase head — pattern allows it
    assert any("urea cycle" in m.lower() for m in out)


def test_handles_catabolism_synonyms():
    out = extract_pathway_mentions("Tyrosine catabolism is upregulated.")
    assert out and out[0].text == "Tyrosine catabolism"


# ---------------- driver extraction ----------------------------------------


def test_marks_compound_only_when_driver_marker_in_same_sentence():
    text = (
        "Tyrosine and homogentisate are central to the response. "
        "Acetoacetate is also elevated. "
        "Fumarate drives the catabolic flux."
    )
    out = extract_driver_mentions(text, ["Tyrosine", "Homogentisate", "Acetoacetate", "Fumarate"])
    # 'central to' marks tyrosine + homogentisate; 'drives' marks fumarate.
    # Acetoacetate is mentioned but not in a driver-marker sentence.
    assert "Tyrosine" in out and "Homogentisate" in out
    assert "Fumarate" in out
    assert "Acetoacetate" not in out


def test_driver_with_no_markers_returns_empty():
    text = "Tyrosine and fumarate are present in the differential set."
    out = extract_driver_mentions(text, ["Tyrosine", "Fumarate"])
    assert out == []


def test_driver_extraction_case_insensitive():
    text = "tyrosine drives the pathway."
    out = extract_driver_mentions(text, ["L-Tyrosine"])
    # Different canonical name; no match expected.
    assert out == []
    out2 = extract_driver_mentions(text, ["Tyrosine"])
    assert out2 == ["Tyrosine"]


def test_driver_returns_no_duplicates():
    text = "Tyrosine drives the pathway. Tyrosine drives further fluxes."
    out = extract_driver_mentions(text, ["Tyrosine"])
    assert out == ["Tyrosine"]


def test_compound_mentions_includes_non_driver():
    text = "Tyrosine and acetoacetate are listed."
    out = extract_compound_mentions(text, ["Tyrosine", "Acetoacetate"])
    assert set(out) == {"Tyrosine", "Acetoacetate"}
