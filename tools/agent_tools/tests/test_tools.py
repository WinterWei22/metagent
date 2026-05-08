"""Unit tests for tools/agent_tools (Phase A1, D1).

Layered:
  - schemas: validation, truncation budget
  - tool_definitions: JSON-schema sanity for OpenAI tool calling
  - wrappers: each wrapper is exercised against a mocked underlying tool,
    so unit tests do NOT need RaMP / HMDB / KEGG DBs
  - dispatcher: routing, validation-error capture, dedup cache, OpenAI-shape
    tool_call extraction
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Match other tracks' bootstrap so `pytest path/to/file` works without a
# repo-wide conftest.py.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from tools.agent_tools import dispatcher
from tools.agent_tools.schemas import (
    SCHEMA_REGISTRY,
    TOOL_RESULT_BUDGET_BYTES,
    LiteratureInput,
    PathwayMembershipInput,
    RampEnrichmentInput,
    truncate_to_budget,
)
from tools.agent_tools.tool_definitions import (
    TOOL_DEFINITIONS_OPENAI,
    TOOL_NAMES,
    get_tool_definition,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_ramp_input_accepts_minimal(self):
        m = RampEnrichmentInput(compound_kegg_ids=["C00031"])
        assert m.compound_kegg_ids == ["C00031"]
        assert m.top_k == 5

    def test_ramp_input_rejects_empty_list(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RampEnrichmentInput(compound_kegg_ids=[])

    def test_ramp_input_rejects_top_k_out_of_range(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RampEnrichmentInput(compound_kegg_ids=["C00031"], top_k=999)

    def test_pathway_membership_rejects_short_id(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PathwayMembershipInput(metabolite_id="X")

    def test_literature_rejects_short_query(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LiteratureInput(query="x")

    def test_literature_accepts_year_from(self):
        m = LiteratureInput(query="methionine cycle", year_from=2015)
        assert m.year_from == 2015


class TestTruncate:
    def test_pass_through_under_budget(self):
        out = truncate_to_budget({"a": "x" * 100, "items": [1, 2, 3]})
        assert out == {"a": "x" * 100, "items": [1, 2, 3]}

    def test_drops_tail_items_when_over(self):
        big_items = [{"x": "y" * 200} for _ in range(50)]
        out = truncate_to_budget(
            {"items": big_items},
            truncatable_key="items",
            more_hint="see more",
            budget=2048,
        )
        assert len(out["items"]) < 50
        assert "_truncated" in out
        assert out["_more"] == "see more"
        # Confirm the result actually fits.
        blob = json.dumps(out, ensure_ascii=False)
        assert len(blob.encode("utf-8")) <= 2048

    def test_falls_back_to_error_envelope_when_unrescuable(self):
        # No truncatable list — root payload itself too big.
        out = truncate_to_budget({"blob": "X" * 10_000}, budget=1024)
        assert out["error"] == "result_too_large"
        assert out["_original_size_bytes"] > 1024


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    def test_one_definition_per_tool(self):
        assert len(TOOL_DEFINITIONS_OPENAI) == len(TOOL_NAMES) == 5
        assert {d["function"]["name"] for d in TOOL_DEFINITIONS_OPENAI} == set(TOOL_NAMES)

    def test_definitions_have_openai_shape(self):
        for d in TOOL_DEFINITIONS_OPENAI:
            assert d["type"] == "function"
            fn = d["function"]
            assert isinstance(fn["name"], str) and fn["name"]
            assert isinstance(fn["description"], str) and len(fn["description"]) > 30
            params = fn["parameters"]
            assert isinstance(params, dict)
            assert params.get("type") == "object"
            # Pydantic always emits 'properties' for BaseModel schemas.
            assert "properties" in params and isinstance(params["properties"], dict)

    def test_get_tool_definition_lookup(self):
        d = get_tool_definition("query_ramp_enrichment")
        assert d["function"]["name"] == "query_ramp_enrichment"
        assert "compound_kegg_ids" in d["function"]["parameters"]["properties"]

    def test_get_tool_definition_unknown_raises(self):
        with pytest.raises(KeyError):
            get_tool_definition("does_not_exist")

    def test_definitions_round_trip_via_json(self):
        # Whatever we hand the LLM, it has to serialise. This catches any
        # non-JSON-able default (e.g. tuples) sneaking into a schema.
        for d in TOOL_DEFINITIONS_OPENAI:
            json.dumps(d)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestDispatcherRouting:
    def setup_method(self) -> None:
        dispatcher.reset_call_cache()

    def test_dispatches_simplified_shape(self):
        with patch.dict(
            dispatcher.WRAPPERS,
            {"query_ramp_enrichment": lambda payload: {"echo": payload}},
        ):
            env = dispatcher.dispatch(
                {
                    "name": "query_ramp_enrichment",
                    "arguments": {"compound_kegg_ids": ["C00031"], "top_k": 3},
                }
            )
        assert env["name"] == "query_ramp_enrichment"
        assert env["cached"] is False
        # validated payload is what reached the wrapper
        assert env["result"]["echo"]["compound_kegg_ids"] == ["C00031"]
        assert env["result"]["echo"]["top_k"] == 3

    def test_dispatches_openai_shape_with_string_arguments(self):
        with patch.dict(
            dispatcher.WRAPPERS,
            {"lookup_compound_info": lambda payload: {"ok": payload["identifier"]}},
        ):
            env = dispatcher.dispatch(
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "lookup_compound_info",
                        "arguments": json.dumps({"identifier": "HMDB0000122"}),
                    },
                }
            )
        assert env["tool_call_id"] == "call_123"
        assert env["result"] == {"ok": "HMDB0000122"}

    def test_unknown_tool_returns_error(self):
        env = dispatcher.dispatch({"name": "totally_made_up", "arguments": {}})
        assert env["result"]["error"].startswith("unknown_tool")
        assert env["cached"] is False

    def test_malformed_tool_call_returns_error(self):
        env = dispatcher.dispatch({"function": {"name": "x", "arguments": "{not json"}})
        assert "malformed_tool_call" in env["result"]["error"]

    def test_validation_error_returns_structured_details(self):
        env = dispatcher.dispatch(
            {"name": "query_ramp_enrichment", "arguments": {"compound_kegg_ids": []}}
        )
        assert env["result"]["error"] == "validation_error"
        assert isinstance(env["result"]["details"], list)
        assert any("compound_kegg_ids" in d["loc"] for d in env["result"]["details"])


class TestDispatcherCaching:
    def setup_method(self) -> None:
        dispatcher.reset_call_cache()

    def test_repeat_call_serves_from_cache(self):
        n_calls = {"count": 0}

        def stub(payload):
            n_calls["count"] += 1
            return {"matched": payload["compound_kegg_ids"]}

        with patch.dict(dispatcher.WRAPPERS, {"query_ramp_enrichment": stub}):
            args = {"compound_kegg_ids": ["C00031", "C00022"]}
            env1 = dispatcher.dispatch({"name": "query_ramp_enrichment", "arguments": args})
            env2 = dispatcher.dispatch({"name": "query_ramp_enrichment", "arguments": args})

        assert n_calls["count"] == 1
        assert env1["cached"] is False
        assert env2["cached"] is True
        assert env2["result"].get("_cached") is True
        assert "already called" in env2["result"]["_note"]

    def test_different_args_not_cached(self):
        n_calls = {"count": 0}

        def stub(payload):
            n_calls["count"] += 1
            return {"top_k": payload["top_k"]}

        with patch.dict(dispatcher.WRAPPERS, {"query_ramp_enrichment": stub}):
            dispatcher.dispatch(
                {"name": "query_ramp_enrichment",
                 "arguments": {"compound_kegg_ids": ["C00031"], "top_k": 3}}
            )
            dispatcher.dispatch(
                {"name": "query_ramp_enrichment",
                 "arguments": {"compound_kegg_ids": ["C00031"], "top_k": 5}}
            )
        assert n_calls["count"] == 2

    def test_reset_cache_clears(self):
        n_calls = {"count": 0}

        def stub(payload):
            n_calls["count"] += 1
            return {}

        with patch.dict(dispatcher.WRAPPERS, {"lookup_compound_info": stub}):
            args = {"identifier": "HMDB0000122"}
            dispatcher.dispatch({"name": "lookup_compound_info", "arguments": args})
            dispatcher.reset_call_cache()
            dispatcher.dispatch({"name": "lookup_compound_info", "arguments": args})
        assert n_calls["count"] == 2


# ---------------------------------------------------------------------------
# Wrapper projection (one happy path + one failure path per tool, mocking the
# underlying tool function so RaMP/HMDB/KEGG DBs are NOT required).
# ---------------------------------------------------------------------------


class TestWrapperProjections:
    """Each wrapper transforms a heavy internal response into a slim dict.
    These tests assert the shape — they do not exercise real DBs.
    """

    def test_ramp_wrapper_projects_top_pathways(self):
        from tools.agent_tools import query_ramp_enrichment as mod
        from tools.benchmark.sub6.ramp_enrichment import (
            EnrichmentReport,
            EnrichmentResult,
        )

        fake_report = EnrichmentReport(
            input_compounds=["C00031"],
            resolved_compounds=["RAMP_C_1"],
            unresolved_compounds=[],
            background_size=10000,
            n_input_resolved=1,
            top_pathways=[
                EnrichmentResult(
                    pathway_id="RAMP_P_1",
                    pathway_name="Glycolysis",
                    pathway_source="kegg",
                    pathway_external_id="hsa00010",
                    total_pathway_compounds=80,
                    matched_compounds=["C00031"],
                    p_value=1e-5,
                    fdr=1e-3,
                    fold_enrichment=12.5,
                ),
            ],
            ramp_snapshot_date="2024-09-01",
            excluded_pathway_types=["pfocr"],
            fdr_threshold=0.05,
        )

        with patch.object(mod, "compute_enrichment", return_value=fake_report):
            out = mod.query_ramp_enrichment({"compound_kegg_ids": ["C00031"]})

        assert out["n_resolved"] == 1
        assert out["background_size"] == 10000
        assert len(out["top_pathways"]) == 1
        path = out["top_pathways"][0]
        assert path["name"] == "Glycolysis"
        assert path["source"] == "kegg"
        assert path["external_id"] == "hsa00010"
        assert path["matched_compounds"] == ["C00031"]
        # No technical-internal field leaks.
        assert "pathway_id" not in path
        assert "p_value" not in path

    def test_ramp_wrapper_strips_cpd_prefix(self):
        from tools.agent_tools import query_ramp_enrichment as mod
        seen: dict[str, list[str]] = {}

        def capture(compound_ids, **kwargs):
            seen["ids"] = list(compound_ids)
            raise ImportError("stop here")  # arbitrary; we just need the args

        with patch.object(mod, "compute_enrichment", side_effect=capture):
            out = mod.query_ramp_enrichment(
                {"compound_kegg_ids": ["cpd:C00031", "C00022", "CPD:c00073"]}
            )
        # Underlying tool sees bare KEGG IDs.
        assert seen["ids"] == ["C00031", "C00022", "c00073"]
        # ImportError is wrapped as unexpected_error, not raised.
        assert "unexpected_error" in out["error"]

    def test_ramp_wrapper_handles_enrichment_error(self):
        from tools.agent_tools import query_ramp_enrichment as mod
        from tools.benchmark.sub6.ramp_enrichment import EnrichmentError

        with patch.object(mod, "compute_enrichment", side_effect=EnrichmentError("DB missing")):
            out = mod.query_ramp_enrichment({"compound_kegg_ids": ["C00031"]})
        assert "enrichment_error" in out["error"]
        assert "fallback_suggested" in out

    def test_pathway_membership_projects_pathways(self):
        from schemas.common import PathwayEntry
        from schemas.pathway import PathwayContextResponse
        from tools.agent_tools import query_pathway_membership as mod

        fake = PathwayContextResponse(
            pathways=[
                PathwayEntry(
                    id="hsa00270",
                    name="Cysteine and methionine metabolism",
                    source="kegg",
                    hit_count=2,
                    url="https://www.kegg.jp/path:hsa00270",
                ),
            ],
            upstream_neighbours=["hmdb:HMDB0000696"],
            downstream_neighbours=[],
            cooccurrence_score=0.5,
            plausibility_summary="Methionine sits in 1 pathway shared by 50% of the co-observed inputs.",
            explain="Found 1 pathway, 1 upstream, 0 downstream; cooccurrence_score=0.50.",
        )
        with patch.object(mod, "pathway_context", return_value=fake):
            out = mod.query_pathway_membership({"metabolite_id": "HMDB0000696"})

        assert out["n_pathways"] == 1
        assert out["pathways"][0]["name"] == "Cysteine and methionine metabolism"
        assert out["cooccurrence_score"] == 0.5
        assert out["plausibility_summary"].startswith("Methionine sits")

    def test_pathway_membership_handles_not_in_network(self):
        from tools.agent_tools import query_pathway_membership as mod
        from tools.pathway_context.errors import MetaboliteNotInNetworkError

        with patch.object(
            mod, "pathway_context",
            side_effect=MetaboliteNotInNetworkError("no rows"),
        ):
            out = mod.query_pathway_membership({"metabolite_id": "HMDB9999999"})
        assert out["error"] == "metabolite_not_in_network"
        assert "fallback_suggested" in out

    def test_kegg_path_handles_missing_db(self, monkeypatch):
        from tools.agent_tools import query_kegg_path as mod
        # Force the resolver to return None.
        monkeypatch.setattr(mod, "_resolve_kegg_db", lambda: None)
        out = mod.query_kegg_path({"compound_a": "C00073", "compound_b": "C00065"})
        assert out["error"] == "kegg_graph_unavailable"

    def test_kegg_path_projects_reachability(self, tmp_path, monkeypatch):
        from tools.agent_tools import query_kegg_path as mod
        from tools.kegg.reachability import ReachabilityResult

        fake_db = tmp_path / "fake.sqlite"
        fake_db.touch()  # exists, but we mock the tool that opens it
        monkeypatch.setattr(mod, "_resolve_kegg_db", lambda: fake_db)

        fake_result = ReachabilityResult(
            source_compounds=["cpd:C00073"],
            target_compounds=["cpd:C00065"],
            is_reachable=True,
            shortest_path=["cpd:C00073", "cpd:C00109", "cpd:C00065"],
            path_length=2,
            direction="forward",
            max_path_length=6,
            notes=["resolved via 'kegg' source"],
        )
        with patch.object(mod, "is_compound_a_upstream_of_compound_b", return_value=fake_result):
            out = mod.query_kegg_path({"compound_a": "C00073", "compound_b": "C00065"})

        assert out["is_reachable"] is True
        assert out["direction"] == "forward"
        assert out["path_length"] == 2
        assert out["resolved_a"] == "cpd:C00073"

    def test_lookup_compound_info_projects_found(self):
        from schemas.molecule import MetaboliteInfoResponse
        from tools.agent_tools import lookup_compound_info as mod

        fake = MetaboliteInfoResponse(
            found=True,
            primary_name="Methionine",
            synonyms=["L-Methionine", "Met"],
            molecular_formula="C5H11NO2S",
            exact_mass=149.0510,
            smiles="CSCCC(N)C(=O)O",
            inchikey="FFEARJCKVFRZRR-BYPYZUCNSA-N",
            chemical_class="Amino acid",
            tissue_locations=["Liver", "Kidney"],
            disease_associations=["Homocystinuria"],
            cross_refs={"hmdb": "HMDB0000696", "kegg": "C00073"},
            source="hmdb",
            explain="Resolved 'Methionine' via hmdb metadata source.",
        )
        with patch.object(mod, "fetch_metabolite_info", return_value=fake):
            out = mod.lookup_compound_info({"identifier": "HMDB0000696"})

        assert out["found"] is True
        assert out["primary_name"] == "Methionine"
        assert out["cross_refs"]["kegg"] == "C00073"
        assert out["source"] == "hmdb"
        # Confirm 'explain' (raw HMDB nuance) does NOT leak into the slim payload.
        assert "explain" not in out

    def test_lookup_compound_info_projects_not_found(self):
        from schemas.molecule import MetaboliteInfoResponse
        from tools.agent_tools import lookup_compound_info as mod

        fake = MetaboliteInfoResponse(
            found=False,
            primary_name=None,
            synonyms=[],
            molecular_formula=None,
            exact_mass=None,
            smiles=None,
            inchikey=None,
            chemical_class=None,
            tissue_locations=[],
            disease_associations=[],
            cross_refs={},
            source=None,
            explain="No record found for identifier 'Q123' (treated as name).",
        )
        with patch.object(mod, "fetch_metabolite_info", return_value=fake):
            out = mod.lookup_compound_info({"identifier": "Q123"})
        assert out["found"] is False
        assert "fallback_suggested" in out

    def test_search_literature_projects_records(self):
        from schemas.common import LiteratureRecord
        from schemas.pathway import LiteratureSearchResponse
        from tools.agent_tools import search_literature as mod

        fake = LiteratureSearchResponse(
            records=[
                LiteratureRecord(
                    pmid="12345678",
                    title="Methionine cycle in HCC",
                    abstract="X" * 1000,
                    authors=["A B", "C D"],
                    year=2022,
                    journal="J Test",
                    doi="10.1/test",
                    url="https://europepmc.org/article/MED/12345678",
                ),
            ],
            query_used="methionine HCC",
            explain="Retrieved 1 record(s) from europepmc...",
        )
        with patch.object(mod, "literature_search", return_value=fake):
            out = mod.search_literature({"query": "methionine HCC", "max_results": 5})

        assert out["n_records"] == 1
        rec = out["records"][0]
        assert rec["pmid"] == "12345678"
        # Abstract excerpt is capped.
        assert len(rec["abstract_excerpt"]) <= 320
        assert rec["abstract_excerpt"].endswith("...")
        # No 'authors' field in slim projection (saves bytes; LLM rarely uses it)
        assert "authors" not in rec

    def test_search_literature_handles_rate_limit(self):
        from tools.agent_tools import search_literature as mod
        from tools.literature.errors import RateLimitError

        with patch.object(mod, "literature_search", side_effect=RateLimitError("429")):
            out = mod.search_literature({"query": "methionine HCC"})
        assert "rate_limited" in out["error"]


# ---------------------------------------------------------------------------
# End-to-end dispatcher × wrapper integration (mock at boundary)
# ---------------------------------------------------------------------------


class TestDispatcherIntegration:
    def setup_method(self) -> None:
        dispatcher.reset_call_cache()

    def test_validation_error_caught_via_dispatcher_for_real_wrapper(self):
        # No need to mock — RampEnrichmentInput rejects empty list before
        # any DB is touched.
        env = dispatcher.dispatch(
            {
                "name": "query_ramp_enrichment",
                "arguments": {"compound_kegg_ids": []},
            }
        )
        assert env["result"]["error"] == "validation_error"
        assert env["cached"] is False

    def test_kegg_path_unknown_db_short_circuits_via_dispatcher(self, monkeypatch):
        from tools.agent_tools import query_kegg_path as mod

        monkeypatch.setattr(mod, "_resolve_kegg_db", lambda: None)
        env = dispatcher.dispatch(
            {
                "name": "query_kegg_path",
                "arguments": {"compound_a": "C00073", "compound_b": "C00065"},
            }
        )
        assert env["result"]["error"] == "kegg_graph_unavailable"

    def test_full_openai_call_shape_round_trip(self):
        # Simulate exactly what the OpenAI/viviai response would look like:
        # message.tool_calls[0] is a dict with id/type/function.{name,arguments-as-string}
        from tools.agent_tools import lookup_compound_info as mod

        from schemas.molecule import MetaboliteInfoResponse
        fake = MetaboliteInfoResponse(
            found=True,
            primary_name="Glucose",
            synonyms=[],
            molecular_formula="C6H12O6",
            exact_mass=180.063,
            smiles="OC[C@@H]1O[C@H](O)[C@H](O)[C@@H](O)[C@@H]1O",
            inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N",
            chemical_class=None,
            tissue_locations=[],
            disease_associations=[],
            cross_refs={"hmdb": "HMDB0000122"},
            source="hmdb",
            explain="ok",
        )

        oai_call = {
            "id": "call_glucose",
            "type": "function",
            "function": {
                "name": "lookup_compound_info",
                "arguments": json.dumps({"identifier": "HMDB0000122", "id_type": "hmdb"}),
            },
        }

        with patch.object(mod, "fetch_metabolite_info", return_value=fake):
            env = dispatcher.dispatch(oai_call)

        assert env["tool_call_id"] == "call_glucose"
        assert env["name"] == "lookup_compound_info"
        assert env["result"]["primary_name"] == "Glucose"
        assert env["cached"] is False

        # Repeat call returns cache.
        with patch.object(mod, "fetch_metabolite_info", return_value=fake) as m2:
            env2 = dispatcher.dispatch(oai_call)
        assert env2["cached"] is True
        # The wrapper should not have been called the second time.
        m2.assert_not_called()
