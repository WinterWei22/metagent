"""W8 D2 — unit tests for the 9 ConcordMet LLM function tools.

Tests focus on the **dispatcher / handler layer** (the agent-facing
envelope), not the underlying wrapper engineering — wrapper-level tests
live in `tests/concord/test_*_wrapper.py`. The five PA tools have their
underlying `run_*` patched to a small canned dict so the handler logic
is exercised without needing sspa / Docker / mummichog venv installed.

Twelve cases per W8 spec § D2 Sub-task 5:

  Happy paths (9):
    1.  run_sspa_ora            — happy path via patched run_sspa
    2.  run_ramp_enrichment     — happy path via patched run_ramp_enrichment
    3.  run_metaboanalystr_psea — happy path via patched run_metaboanalystr_psea
    4.  run_mummichog           — happy path via patched run_mummichog
    5.  run_fella_rwr           — happy path via patched run_fella_rwr
    6.  lookup_chebi            — happy path via real ChEBI sqlite (D-glucose)
    7.  reconcile_inchikey      — happy path via real reconcile module
    8.  query_pathway_members   — happy path via real HUMAN1 sqlite
    9.  search_literature       — happy path via patched B1 wrapper

  Negative paths (3):
    10. run_sspa_ora invalid arguments (non-list compound_ids)
    11. run_sspa_ora wrapper unavailable (import patched to ImportError)
    12. dedup cache: identical (tool_name, args) twice → 2nd is cached
"""
from __future__ import annotations

import sys
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_dispatch_cache():
    """Reset the dispatcher's per-call dedup cache between tests so a
    cache hit in one test does not contaminate another."""
    from concord.agent.tool_dispatcher import reset_call_cache
    reset_call_cache()
    yield
    reset_call_cache()


def _fake_enrichment_dict(method: str, n_pathways: int = 2) -> dict[str, Any]:
    """Build a minimal dict matching the shape the 5 wrappers actually
    return (schema concordmet_v0.3.1 — `pathways` list of dicts with
    namespace-prefixed `pathway_id`)."""
    return {
        "method": method,
        "pathway_db": "kegg",
        "pathways": [
            {
                "pathway_id": f"KEGG:hsa{i:05d}",
                "pathway_name": f"Pathway {i}",
                "pathway_id_native": f"hsa{i:05d}",
                "pathway_db": "kegg",
                "score": 1e-3 * (i + 1),
                "score_type": "p_value",
                "rank": i,
                "metabolites_hit": [
                    {"primary_id": "CHEBI:17234", "inchikey": "WQZGKKKJIJFFOK-GASJEMHNSA-N", "display_name": "D-glucose"},
                ],
                "n_metabolites_in_pathway": 20,
                "n_metabolites_input": 5,
                "auxiliary_scores": {},
            }
            for i in range(n_pathways)
        ],
        "parameters": {"top_n": 10},
        "tool_version": f"{method}-test-1.0",
        "db_release": "test_2026",
        "n_input": 5,
        "n_input_resolved": 5,
        "wall_time_sec": 0.1,
        "schema_version": "concordmet_v0.3.1",
        "tautomer_canonicalized": False,
        "chebi_canonicalized": True,
        "notes": "test fake",
    }


# ---------------------------------------------------------------------------
# Happy paths (9)
# ---------------------------------------------------------------------------


def test_run_sspa_ora_happy_path(monkeypatch):
    """sspa handler returns {ok, result, _meta} envelope on success."""
    from concord.agent import tool_dispatcher
    from concord.wrappers import sspa_wrapper

    fake = _fake_enrichment_dict("ora_sspa")
    monkeypatch.setattr(sspa_wrapper, "run_sspa", lambda **kwargs: fake)

    r = tool_dispatcher.dispatch({
        "name": "run_sspa_ora",
        "arguments": {"compound_ids": ["CHEBI:17234", "CHEBI:15843"]},
    })
    assert r.payload.get("ok") is True, r.payload
    assert r.payload["result"]["pathways"][0]["pathway_id"] == "KEGG:hsa00000"
    assert r.payload["_tool_name"] == "run_sspa_ora"
    assert r.payload["_n_pathways"] == 2


def test_run_ramp_enrichment_happy_path(monkeypatch):
    from concord.agent import tool_dispatcher
    from concord.wrappers import ramp_wrapper

    fake = _fake_enrichment_dict("ora_ramp")
    monkeypatch.setattr(ramp_wrapper, "run_ramp_enrichment", lambda *a, **kw: fake)

    r = tool_dispatcher.dispatch({
        "name": "run_ramp_enrichment",
        "arguments": {"compound_ids": ["HMDB0000122"]},
    })
    assert r.payload.get("ok") is True, r.payload
    assert r.payload["_tool_name"] == "run_ramp_enrichment"
    assert r.payload["_n_pathways"] == 2


def test_run_metaboanalystr_psea_happy_path(monkeypatch):
    from concord.agent import tool_dispatcher
    from concord.wrappers import metaboanalystr_wrapper

    fake = _fake_enrichment_dict("psea_marx")
    monkeypatch.setattr(
        metaboanalystr_wrapper, "run_metaboanalystr_psea",
        lambda *a, **kw: fake,
    )

    r = tool_dispatcher.dispatch({
        "name": "run_metaboanalystr_psea",
        "arguments": {"compound_ids": ["C00031", "C00219"]},
    })
    assert r.payload.get("ok") is True, r.payload
    assert r.payload["_tool_name"] == "run_metaboanalystr_psea"


def test_run_mummichog_happy_path(monkeypatch):
    from concord.agent import tool_dispatcher
    from concord.wrappers import mummichog_wrapper

    fake = _fake_enrichment_dict("mummichog")
    # Patch both the venv-direct call AND the compound-set helper that
    # the handler may delegate to.
    monkeypatch.setattr(mummichog_wrapper, "run_mummichog", lambda *a, **kw: fake)
    monkeypatch.setattr(
        mummichog_wrapper, "run_mummichog_for_compound_set",
        lambda *a, **kw: fake,
    )

    r = tool_dispatcher.dispatch({
        "name": "run_mummichog",
        "arguments": {"compound_ids": ["CHEBI:15843"]},
    })
    assert r.payload.get("ok") is True, r.payload
    assert r.payload["_tool_name"] == "run_mummichog"


def test_run_fella_rwr_happy_path(monkeypatch):
    from concord.agent import tool_dispatcher
    from concord.wrappers import fella_wrapper

    fake = _fake_enrichment_dict("fella_rwr")
    monkeypatch.setattr(fella_wrapper, "run_fella_rwr", lambda *a, **kw: fake)

    r = tool_dispatcher.dispatch({
        "name": "run_fella_rwr",
        "arguments": {"compound_ids": ["C00031"]},
    })
    assert r.payload.get("ok") is True, r.payload
    assert r.payload["_tool_name"] == "run_fella_rwr"


def test_lookup_chebi_happy_path():
    """Real ChEBI sqlite query for D-glucose (CHEBI:17234)."""
    from concord.agent import tool_dispatcher

    r = tool_dispatcher.dispatch({
        "name": "lookup_chebi",
        "arguments": {"id": "CHEBI:17234"},
    })
    assert r.payload.get("ok") is True, r.payload
    assert r.payload["result"]["primary_id"] == "CHEBI:17234"
    # display_name is "glucose" / "D-glucose" — accept either
    assert "glucose" in (r.payload["result"]["display_name"] or "").lower()


def test_reconcile_inchikey_happy_path():
    """Two refs with identical InChIKey → 1 cluster, no conflict."""
    from concord.agent import tool_dispatcher

    refs = [
        {"display_name": "D-glucose-1", "inchikey": "WQZGKKKJIJFFOK-GASJEMHNSA-N", "primary_id": "CHEBI:17234"},
        {"display_name": "D-glucose-2", "inchikey": "WQZGKKKJIJFFOK-GASJEMHNSA-N", "primary_id": "KEGG:C00031"},
    ]
    r = tool_dispatcher.dispatch({
        "name": "reconcile_inchikey",
        "arguments": {"refs": refs},
    })
    assert r.payload.get("ok") is True, r.payload
    assert r.payload["result"]["n_clusters"] == 1
    assert r.payload["result"]["conflict_type"] == "none"


def test_query_pathway_members_happy_path():
    """Real HUMAN1 sqlite query — alanine_aspartate_glutamate has members."""
    from concord.agent import tool_dispatcher

    r = tool_dispatcher.dispatch({
        "name": "query_pathway_members",
        "arguments": {
            "pathway_id": "HUMAN1:alanine_aspartate_and_glutamate_metabolism",
        },
    })
    assert r.payload.get("ok") is True, r.payload
    members = r.payload["result"]["member_chebi_ids"]
    assert len(members) > 0, "HUMAN1 alanine_aspartate must have members"
    assert all(m.startswith("CHEBI:") for m in members)


def test_search_literature_happy_path(monkeypatch):
    """B1 search_literature delegate returns mocked PMID list."""
    from concord.agent import tool_dispatcher
    from tools.agent_tools import search_literature as b1_lit

    def _fake_search(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "results": [
                {
                    "pmid": "12345678",
                    "title": "Test paper on eicosanoid signalling",
                    "abstract": "snippet",
                    "year": 2024,
                    "journal": "J. Test",
                }
            ],
            "n_results": 1,
        }

    monkeypatch.setattr(b1_lit, "search_literature", _fake_search)

    r = tool_dispatcher.dispatch({
        "name": "search_literature",
        "arguments": {"query": "arachidonic acid metabolism eicosanoid", "max_results": 5},
    })
    assert r.payload.get("ok") is True, r.payload
    assert r.payload["result"]["n_results"] == 1
    assert r.payload["result"]["results"][0]["pmid"] == "12345678"


# ---------------------------------------------------------------------------
# Negative paths (3)
# ---------------------------------------------------------------------------


def test_run_sspa_ora_invalid_arguments_returns_error_envelope():
    """Passing non-list compound_ids returns an error envelope (no raise)."""
    from concord.agent import tool_dispatcher

    r = tool_dispatcher.dispatch({
        "name": "run_sspa_ora",
        "arguments": {"compound_ids": "not_a_list"},
    })
    assert "error" in r.payload, r.payload
    assert r.payload.get("ok") is not True
    # Error must be informative enough for the LLM to fix its call.
    assert "compound_ids" in r.payload.get("error", "").lower() or \
           "compound_ids" in r.payload.get("fallback_suggested", "").lower()


def test_run_sspa_ora_wrapper_unavailable(monkeypatch):
    """When sspa pkg is not installed, handler returns wrapper_unavailable
    envelope with fallback_suggested — never raises."""
    from concord.agent import tool_dispatcher

    # Force the sspa_wrapper module to be ImportError'd at handler-call
    # time. Removing from sys.modules + injecting a finder that raises
    # ImportError on subsequent re-import.
    monkeypatch.setitem(sys.modules, "concord.wrappers.sspa_wrapper", None)

    r = tool_dispatcher.dispatch({
        "name": "run_sspa_ora",
        "arguments": {"compound_ids": ["CHEBI:17234"]},
    })
    assert r.payload.get("error") == "wrapper_unavailable", r.payload
    assert "fallback_suggested" in r.payload
    # The LLM-readable fallback must mention an alternative tool.
    fb = r.payload["fallback_suggested"].lower()
    assert "ramp" in fb or "metaboanalystr" in fb or "psea" in fb


def test_run_sspa_ora_wrapper_runtime_module_not_found(monkeypatch):
    """D3 hotfix regression: when the wrapper module imports fine but
    its body lazy-imports a heavy dep at CALL time (sspa pkg pattern),
    the handler must still return wrapper_unavailable — not let the
    inner ModuleNotFoundError escape to the dispatcher."""
    from concord.agent import tool_dispatcher
    from concord.wrappers import sspa_wrapper

    def _boom(**_kwargs):
        raise ModuleNotFoundError("No module named 'sspa'")

    monkeypatch.setattr(sspa_wrapper, "run_sspa", _boom)

    r = tool_dispatcher.dispatch({
        "name": "run_sspa_ora",
        "arguments": {"compound_ids": ["CHEBI:17234"]},
    })
    assert r.payload.get("error") == "wrapper_unavailable", r.payload
    assert "fallback_suggested" in r.payload
    assert "sspa" in r.payload.get("reason", "").lower()


def test_dedup_cache_hit_on_identical_call(monkeypatch):
    """Same (tool, args) twice in one task → second call returns cached
    payload with _cached=True and a _note advising to vary the inputs."""
    from concord.agent import tool_dispatcher
    from concord.wrappers import sspa_wrapper

    fake = _fake_enrichment_dict("ora_sspa", n_pathways=1)
    monkeypatch.setattr(sspa_wrapper, "run_sspa", lambda **kw: fake)

    args = {"compound_ids": ["CHEBI:17234"], "top_n": 10}
    r1 = tool_dispatcher.dispatch({"name": "run_sspa_ora", "arguments": args})
    r2 = tool_dispatcher.dispatch({"name": "run_sspa_ora", "arguments": args})

    assert r1.payload.get("ok") is True
    assert r1.from_cache is False
    assert r2.from_cache is True
    assert r2.payload.get("_cached") is True
    assert "_note" in r2.payload
