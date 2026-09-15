"""RED test: _normalize_kegg_id in concord.agent.tool_handlers.

Verifies that KEGG:map00XXX pathway IDs emitted by RaMP are normalized
to KEGG:hsa00XXX so the LLM agent can correctly assess cross-tool
convergence (e.g. against Mummichog / SSPA results that already use
hsa-prefixed IDs).
"""
import pytest

from concord.agent.tool_handlers import _normalize_kegg_id


def test_map_prefix_replaced_with_hsa():
    assert _normalize_kegg_id("KEGG:map00250") == "KEGG:hsa00250"


def test_hsa_prefix_unchanged():
    assert _normalize_kegg_id("KEGG:hsa00250") == "KEGG:hsa00250"


def test_non_kegg_id_unchanged():
    assert _normalize_kegg_id("REACT:R-HSA-123") == "REACT:R-HSA-123"


def test_map_prefix_numeric_suffix_preserved():
    assert _normalize_kegg_id("KEGG:map00010") == "KEGG:hsa00010"
