"""W8 D4 sub-task 1 — `concord.agent.verifier_adapter` strict-TDD tests.

Three conversion functions at the ConcordMet ↔ B1-verifier boundary:

  (A) concord_result_to_b1_narrative(result, task) -> str
        ConcordReactResult → the prose narrative_text string that B1's
        verify_sub6() consumes as `llm_output`. The grammar-v2 structured
        `claims` array is ConcordMet-internal bookkeeping; B1 extracts
        atomic claims from the prose itself, so the adapter passes the
        prose only.

  (B) sub6b_task_to_subsix_source_report(task) -> SubsixSourceReport
        sub6b-v3 task dict → pydantic SubsixSourceReport. v3 task JSONL
        rows already carry every field the schema requires; the adapter
        is a thin pydantic constructor + optional compound_lookup fill.

  (C) task_outcome_str_to_enum(outcome_str) -> ConcordTaskOutcome
        Bridges the ConcordReactResult.task_outcome string field (NORMAL
        / EMPTY_HONEST_REFUSAL / EMPTY_SYSTEM_FAILURE / EMPTY_UNKNOWN) to
        a typed enum. The B1 D4 spec defines a TaskOutcome enum in
        verifier/schemas.py — that enum is NOT present in the
        feature/investigation-concord branch (B1 D4 lives on the
        feature/agent-phase-b1 branch and has not merged). We therefore
        own a `ConcordTaskOutcome` enum locally with the same 4 string
        values for parity.

Tests run before the implementation exists — strict RED → GREEN per
the D3 TDD-slip commitment.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

# Importing the not-yet-existent adapter module is itself a RED step on
# first run; once GREEN, these imports work.
from concord.agent.react_runner import (
    ConcordIterationRecord,
    ConcordReactResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_v3_task() -> dict[str, Any]:
    """Minimal sub6b-v3 task with every SubsixSourceReport-required key."""
    return {
        "task_id": "compound_only_enrich_mammalian_lm_pathway_WP167_seed3",
        "task_type": "compound_only_enrichment",
        "domain": "mammalian",
        "differential_metabolites": [
            {"name": "arachidonic acid", "kegg_id": "C00219",
             "inchikey": "YZXBAPSDXZZRGB-DOFZRALJSA-N",
             "inchikey_first_block": "YZXBAPSDXZZRGB"},
        ],
        "differential_spectra": None,
        "ground_truth_pathway": {
            "pathway_id": "lm_pathway:WP167",
            "pathway_name": "Eicosanoid synthesis",
            "pathway_source": "lipidmaps",
            "external_id": "WP167",
            "primary_pathway_pre_aggregation": "lm_pathway:WP167",
        },
        "ground_truth_signal_compounds": ["C00219", "C00909"],
        "ground_truth_noise_compounds": ["C00116"],
        "ramp_enrichment_result": {
            "input_compounds": ["C00219"],
            "resolved_compounds": ["C00219"],
            "unresolved_compounds": [],
            "background_size": 1000,
            "n_input_resolved": 1,
            "top_pathways": [
                {"pathway_id": "RAMP_P_000050021", "fdr": 0.01,
                 "pathway_name": "Biological oxidations"},
            ],
        },
    }


@pytest.fixture
def fake_concord_result() -> ConcordReactResult:
    """Minimal ConcordReactResult mimicking a D3 smoke 2 outcome shape."""
    return ConcordReactResult(
        task_id="compound_only_enrich_mammalian_lm_pathway_WP167_seed3",
        iterations=[
            ConcordIterationRecord(
                iter_idx=0,
                narrative_json=json.dumps({
                    "narrative_text": (
                        "Multi-paradigm pathway analysis identifies arachidonic "
                        "acid metabolism (MUMM:00002) as the dominant signal. "
                        "Key drivers include arachidonate and leukotriene A4."
                    ),
                    "claims": [
                        {"claim_type": "PATHWAY_ENRICHMENT",
                         "pathway_id": "MUMM:00002",
                         "pathway_name": "Arachidonic acid metabolism"},
                    ],
                }),
                n_turns=8,
                n_tool_calls=26,
                force_finalised=True,
            ),
        ],
        final_iter_idx=0,
        final_narrative_text=(
            "Multi-paradigm pathway analysis identifies arachidonic "
            "acid metabolism (MUMM:00002) as the dominant signal. "
            "Key drivers include arachidonate and leukotriene A4."
        ),
        final_claims=[
            {"claim_type": "PATHWAY_ENRICHMENT",
             "pathway_id": "MUMM:00002",
             "pathway_name": "Arachidonic acid metabolism"},
        ],
        final_narrative_json="<see iterations[0].narrative_json>",
        task_outcome="normal",
        elapsed_seconds=194.2,
        llm_model="MiniMax-M2.7",
        metabolite_count=9,
        n_distinct_tools_called=7,
        tools_called=["lookup_chebi", "query_pathway_members",
                      "run_fella_rwr", "run_metaboanalystr_psea",
                      "run_mummichog", "run_ramp_enrichment", "run_sspa_ora"],
    )


# ---------------------------------------------------------------------------
# (A) concord_result_to_b1_narrative
# ---------------------------------------------------------------------------


def test_concord_result_to_b1_narrative_returns_prose_string(fake_concord_result, fake_v3_task):
    """Returns the LLM's narrative_text (prose); NOT the structured JSON,
    because B1.verify_sub6() expects natural-language atomic-claim source."""
    from concord.agent.verifier_adapter import concord_result_to_b1_narrative

    out = concord_result_to_b1_narrative(fake_concord_result, fake_v3_task)
    assert isinstance(out, str)
    # Body must contain the prose — not the structured `claims` field name.
    assert "arachidonic acid metabolism" in out.lower()
    # ConcordMet structured-claim metadata must NOT bleed into the string
    # we hand to B1's extractor (that would confuse B1's atomic-claim parsing).
    assert "PATHWAY_ENRICHMENT" not in out
    assert "claim_type" not in out


def test_concord_result_to_b1_narrative_empty_outcome_returns_empty_string(fake_v3_task):
    """When task_outcome is empty_*, narrative_text is empty by D3 contract;
    adapter must propagate that as an empty string, not raise."""
    from concord.agent.verifier_adapter import concord_result_to_b1_narrative

    empty = ConcordReactResult(
        task_id="x",
        final_narrative_text="",
        task_outcome="empty_system_failure",
        error="task_timeout",
    )
    out = concord_result_to_b1_narrative(empty, fake_v3_task)
    assert out == ""


# ---------------------------------------------------------------------------
# (B) sub6b_task_to_subsix_source_report
# ---------------------------------------------------------------------------


def test_sub6b_task_to_subsix_source_report_minimum_required_fields(fake_v3_task):
    """All SubsixSourceReport required fields are copied verbatim from the v3 task row."""
    from concord.agent.verifier_adapter import sub6b_task_to_subsix_source_report

    rpt = sub6b_task_to_subsix_source_report(fake_v3_task)
    # Field-by-field parity with the JSONL row
    assert rpt.task_id == fake_v3_task["task_id"]
    assert rpt.task_type == fake_v3_task["task_type"]
    assert rpt.domain == fake_v3_task["domain"]
    assert rpt.ground_truth_pathway == fake_v3_task["ground_truth_pathway"]
    assert rpt.ground_truth_signal_compounds == fake_v3_task["ground_truth_signal_compounds"]
    assert rpt.ground_truth_noise_compounds == fake_v3_task["ground_truth_noise_compounds"]
    assert rpt.ramp_enrichment_result == fake_v3_task["ramp_enrichment_result"]
    assert rpt.differential_metabolites == fake_v3_task["differential_metabolites"]
    # Optional / unspecified
    assert rpt.differential_spectra is None
    assert rpt.compound_lookup is None


def test_sub6b_task_to_subsix_source_report_handles_lipid_namespace_pathway(fake_v3_task):
    """The lipid smoking-gun task uses `lm_pathway:WP167` pathway_id (LIPIDMAPS
    namespace, W8-specific). Adapter passes it through unchanged — the v3
    extension does NOT need to be remapped to a B1 namespace."""
    from concord.agent.verifier_adapter import sub6b_task_to_subsix_source_report

    rpt = sub6b_task_to_subsix_source_report(fake_v3_task)
    assert rpt.ground_truth_pathway["pathway_id"] == "lm_pathway:WP167"
    assert rpt.ground_truth_pathway["pathway_source"] == "lipidmaps"


def test_sub6b_task_to_subsix_source_report_missing_required_field_raises(fake_v3_task):
    """A v3 task missing `ground_truth_pathway` is a benchmark corruption —
    adapter must let pydantic surface the ValidationError (not silently fill)."""
    from concord.agent.verifier_adapter import sub6b_task_to_subsix_source_report
    from pydantic import ValidationError

    bad = dict(fake_v3_task)
    del bad["ground_truth_pathway"]
    with pytest.raises(ValidationError):
        sub6b_task_to_subsix_source_report(bad)


# ---------------------------------------------------------------------------
# (C) task_outcome_str_to_enum
# ---------------------------------------------------------------------------


def test_task_outcome_str_to_enum_round_trips_four_values():
    """All four ConcordReactResult.task_outcome strings map to a distinct enum value."""
    from concord.agent.verifier_adapter import (
        ConcordTaskOutcome,
        task_outcome_str_to_enum,
    )

    for s in ["normal", "empty_honest_refusal",
              "empty_system_failure", "empty_unknown"]:
        e = task_outcome_str_to_enum(s)
        assert isinstance(e, ConcordTaskOutcome)
        assert e.value == s


def test_task_outcome_str_to_enum_case_insensitive_and_uppercase():
    """`NORMAL`, `Normal`, `normal` all map to the same enum — the runner
    emits lowercase but external callers may have stored uppercase B1-style."""
    from concord.agent.verifier_adapter import (
        ConcordTaskOutcome,
        task_outcome_str_to_enum,
    )

    assert task_outcome_str_to_enum("NORMAL") is ConcordTaskOutcome.NORMAL
    assert task_outcome_str_to_enum("Normal") is ConcordTaskOutcome.NORMAL
    assert task_outcome_str_to_enum("normal") is ConcordTaskOutcome.NORMAL


def test_task_outcome_str_to_enum_unknown_string_raises():
    """An unrecognised string is a programmer error, not a runtime fallback —
    raise so the caller fixes the source rather than swallows the issue."""
    from concord.agent.verifier_adapter import task_outcome_str_to_enum

    with pytest.raises(ValueError):
        task_outcome_str_to_enum("partial_failure")
    with pytest.raises(ValueError):
        task_outcome_str_to_enum("")
