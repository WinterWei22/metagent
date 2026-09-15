"""Unit tests for evaluation.sub6.prompts."""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6 import prompts


def test_render_line_with_full_metadata():
    line = prompts.render_metabolite_line(
        {"name": "L-Tyrosine", "kegg_id": "C00082", "inchikey_first_block": "OUYCCCASQSFEME"}
    )
    assert line == "  - L-Tyrosine (KEGG: C00082, InChIKey: OUYCCCASQSFEME)"


def test_render_line_partial_metadata():
    line = prompts.render_metabolite_line({"name": "Glucose"})
    assert line == "  - Glucose"


def test_render_line_uses_inchikey_fallback():
    line = prompts.render_metabolite_line({"name": "X", "inchikey": "ABCDEFGHIJ-XYZ"})
    assert "InChIKey: ABCDEFGHIJ-XYZ" in line


def test_render_block_preserves_order_and_count():
    items = [
        {"name": "A", "kegg_id": "C0001"},
        {"name": "B", "kegg_id": "C0002"},
        {"name": "C", "kegg_id": "C0003"},
    ]
    block = prompts.render_metabolite_block(items)
    assert block.count("\n") == 2
    lines = block.splitlines()
    assert "A" in lines[0] and "B" in lines[1] and "C" in lines[2]


def test_user_prompt_specifies_grammar_v2_output():
    out = prompts.render_user_prompt([{"name": "Tyrosine", "kegg_id": "C00082"}])
    assert "narrative_text" in out
    assert "claims" in out
    assert "pathway_membership" in out
    assert "driver_metabolite" in out


def test_user_prompt_does_not_leak_ground_truth():
    """Belt-and-braces: even if a caller hands us a task dict by mistake,
    rendering only consumes ``differential_metabolites``-style entries.
    """
    items = [{"name": "Tyrosine", "kegg_id": "C00082"}]
    out = prompts.render_user_prompt(items)
    forbidden = [
        "ground_truth",
        "ramp_enrichment",
        "top_pathways",
        "fdr",
        "p_value",
        "fold_enrichment",
        "signal_count",
        "noise_count",
    ]
    low = out.lower()
    for w in forbidden:
        assert w not in low, f"forbidden token leaked into prompt: {w}"


def test_build_messages_shape():
    msgs = prompts.build_messages([{"name": "Tyrosine"}])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "Tyrosine" in msgs[1]["content"]
