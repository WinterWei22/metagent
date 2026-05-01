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


# ---------------- §9.5 fix 1: markdown header artefact -------------------


def test_pathway_regex_does_not_span_newlines():
    """Real LLM narrative starts with markdown header then prose; the
    regex used to capture 'Affected Metabolic Pathways\\n\\nThe dominant
    pathway' as one mention because \\s+ matched newlines."""
    text = (
        "## Pathway Analysis\n\n"
        "### 1. Most Affected Metabolic Pathways\n\n"
        "The dominant pathway affected is glycerolipid metabolism.\n"
    )
    out = [m.text for m in extract_pathway_mentions(text)]
    # Must NOT capture the cross-line phrase.
    assert not any("\n" in t for t in out)
    # And the only valid mention here is 'glycerolipid metabolism'.
    assert "glycerolipid metabolism" in out


def test_markdown_header_stripped_before_extraction():
    """`### 1. Tyrosine metabolism` — the leading `###` must not become
    part of the head."""
    text = "### 1. Tyrosine metabolism is dominant."
    out = [m.text for m in extract_pathway_mentions(text)]
    assert "Tyrosine metabolism" in out


# ---------------- §9.5 fix 2: empty-content-token mentions ---------------


def test_drops_known_name_with_no_content_tokens():
    """`Metabolism` alone is a token in some RaMP top_pathways lists; it
    must be dropped — predicting just 'Metabolism' is meaningless."""
    text = "Methionine Metabolism is the dominant signal."
    out = [m.text for m in extract_pathway_mentions(text, ["Metabolism", "Methionine Metabolism"])]
    assert "Methionine Metabolism" in out
    assert "Metabolism" not in out


def test_drops_generic_adjective_pathway():
    """`biosynthetic pathway` / `prominent pathway` carry no content."""
    text = (
        "The biosynthetic pathway is implicated. "
        "A prominent pathway emerges. "
        "Tyrosine metabolism dominates."
    )
    out = [m.text for m in extract_pathway_mentions(text)]
    # Tyrosine metabolism must survive; the two generic phrases must not.
    assert any("tyrosine" in t.lower() for t in out)
    assert not any("biosynthetic pathway" == t.lower() for t in out)
    assert not any("prominent pathway" == t.lower() for t in out)


def test_drops_multi_token_head_ending_in_generic_word():
    """`Most Affected Metabolic pathway` — last head token 'Metabolic' is
    a generic adjective; drop the whole mention."""
    text = "Most Affected Metabolic pathway dominates."
    out = [m.text for m in extract_pathway_mentions(text)]
    assert not any("affected" in t.lower() for t in out)


# ---------------- §9.5 fix 3: driver-section markdown rule ---------------


def test_driver_section_picks_up_bullet_drivers_without_marker_phrase():
    """LLMs commonly use a `### Key Drivers` section followed by bullets
    that don't always contain a multi-word marker like 'key driver'."""
    text = (
        "## Pathway Analysis\n\n"
        "### 1. Affected Pathways\n\n"
        "Pyrimidine metabolism dominates.\n\n"
        "### 2. Key Drivers\n\n"
        "- **Ureidosuccinic acid** is the pathway entry point.\n"
        "- **dCMP** and **UTP** are critical branch points.\n\n"
        "### 3. Significance\n\n"
        "Acetoacetate is mentioned but outside the driver section.\n"
    )
    candidates = ["Ureidosuccinic acid", "dCMP", "UTP", "Acetoacetate"]
    out = extract_driver_mentions(text, candidates)
    assert "Ureidosuccinic acid" in out
    assert "dCMP" in out
    assert "UTP" in out
    # Acetoacetate is in another section, no driver marker → must NOT be a driver.
    assert "Acetoacetate" not in out


def test_driver_section_terminates_at_next_header():
    """A driver section must not bleed into the next section."""
    text = (
        "### Key Drivers\n\n"
        "- **A** drives the response.\n\n"
        "### Other Notes\n\n"
        "- B is just listed here.\n"
    )
    out = extract_driver_mentions(text, ["A", "B"])
    assert "A" in out
    assert "B" not in out


def test_driver_section_combined_with_sentence_marker():
    """Section rule + sentence rule are unioned; both yield drivers."""
    text = (
        "### Drivers\n\n"
        "- **Ureidosuccinic acid** is the entry point.\n\n"
        "### Discussion\n\n"
        "Tyrosine drives the catabolic flux.\n"
    )
    out = extract_driver_mentions(text, ["Ureidosuccinic acid", "Tyrosine"])
    assert set(out) == {"Ureidosuccinic acid", "Tyrosine"}
