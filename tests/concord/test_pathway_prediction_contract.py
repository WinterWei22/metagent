from __future__ import annotations

import dataclasses
import json
from typing import Any

from concord.agent.pathway_prediction import (
    compute_pathway_prediction_metrics,
    parse_pathway_prediction_contract,
    pathway_semantic_match,
)
from concord.agent.react_runner import ConcordReactResult, _validate_grammar_v2
from concord.agent.system_prompts import _load_template, get_system_prompt


def _claim(pathway_name: str, term_id: str = "WP:WP167") -> dict[str, Any]:
    return {
        "claim_type": "PATHWAY_ENRICHMENT",
        "grammar": "pathway_enrichment",
        "claim_text": f"{pathway_name} is enriched.",
        "term_id": term_id,
        "term_name": pathway_name,
        "term_type": "pathway",
        "method": "run_ramp_enrichment",
        "rank": 1,
    }


def _prediction(
    *,
    primary_name: str = "Eicosanoid synthesis",
    primary_id: str = "WP:WP167",
    supporting_claim_indices: list[int] | None = None,
    alternatives: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "primary": {
            "pathway_id": primary_id,
            "pathway_name": primary_name,
            "pathway_source": "WikiPathways",
            "confidence": 0.86,
            "evidence_methods": ["run_ramp_enrichment"],
            "supporting_claim_indices": [0] if supporting_claim_indices is None else supporting_claim_indices,
            "rationale": "Evidence supports this pathway.",
        },
        "alternatives": [] if alternatives is None else alternatives,
        "abstain": False,
        "abstain_reason": None,
    }


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "narrative_text": "Eicosanoid synthesis dominates the pathway signal.",
        "claims": [_claim("Eicosanoid synthesis")],
        "pathway_prediction": _prediction(),
    }
    payload.update(overrides)
    return payload


def test_parser_contract_accepts_valid_pathway_prediction() -> None:
    parsed = parse_pathway_prediction_contract(_payload())
    assert parsed.ok
    assert parsed.value is not None
    assert parsed.value.primary is not None
    assert parsed.value.primary.pathway_name == "Eicosanoid synthesis"
    assert parsed.value.abstain is False


def test_parser_rejects_missing_pathway_prediction_but_marks_degraded() -> None:
    payload = _payload()
    payload.pop("pathway_prediction")
    parsed = parse_pathway_prediction_contract(payload)
    assert not parsed.ok
    assert parsed.degraded
    assert "missing" in parsed.error


def test_parser_sanitizes_out_of_range_supporting_claim_indices() -> None:
    parsed = parse_pathway_prediction_contract(
        _payload(pathway_prediction=_prediction(supporting_claim_indices=[99]))
    )
    assert parsed.ok
    assert parsed.value is not None
    assert parsed.value.primary is not None
    assert parsed.value.primary.supporting_claim_indices == []


def test_parser_accepts_second_pass_wrapped_pathway_prediction_object() -> None:
    parsed = parse_pathway_prediction_contract(
        _payload(pathway_prediction={"pathway_prediction": _prediction()})
    )
    assert parsed.ok
    assert parsed.value is not None
    assert parsed.value.primary is not None
    assert parsed.value.primary.pathway_name == "Eicosanoid synthesis"


def test_parser_accepts_second_pass_string_confidence_as_ordering_hint() -> None:
    prediction = _prediction()
    prediction["primary"]["confidence"] = "high"
    parsed = parse_pathway_prediction_contract(_payload(pathway_prediction=prediction))
    assert parsed.ok
    assert parsed.value is not None
    assert parsed.value.primary is not None
    assert parsed.value.primary.confidence is None


def test_parser_sanitizes_bad_alternative_without_rejecting_usable_primary() -> None:
    parsed = parse_pathway_prediction_contract(
        _payload(
            claims=[_claim("Eicosanoid synthesis")],
            pathway_prediction=_prediction(
                alternatives=[
                    {
                        "pathway_id": "KEGG:hsa00140",
                        "pathway_name": "Steroid hormone biosynthesis",
                        "confidence": 0.5,
                        "supporting_claim_indices": [11],
                    }
                ]
            ),
        )
    )
    assert parsed.ok
    assert parsed.value is not None
    assert parsed.value.primary is not None
    assert parsed.value.alternatives[0].supporting_claim_indices == []


def test_parser_accepts_second_pass_flat_primary_string_shape() -> None:
    parsed = parse_pathway_prediction_contract(
        _payload(
            claims=[_claim("Methionine Metabolism", "SMPDB:SMP00033")],
            pathway_prediction={
                "primary": "Methionine Metabolism",
                "primary_pathway_id": "KEGG:hsa00270",
                "confidence": "high",
                "supporting_claim_indices": [0],
                "alternatives": [
                    {
                        "pathway_id": "KEGG:hsa00260",
                        "pathway_name": "Glycine, serine and threonine metabolism",
                        "confidence": "medium",
                        "supporting_claim_indices": [],
                    }
                ],
                "abstain": False,
                "abstain_reason": None,
            },
        )
    )
    assert parsed.ok
    assert parsed.value is not None
    assert parsed.value.primary is not None
    assert parsed.value.primary.pathway_name == "Methionine Metabolism"
    assert parsed.value.primary.pathway_id == "KEGG:hsa00270"


def test_parser_accepts_string_alternatives_from_second_pass() -> None:
    parsed = parse_pathway_prediction_contract(
        _payload(
            pathway_prediction={
                "primary": "Central carbon metabolism / TCA cycle",
                "supporting_claim_indices": [0],
                "confidence": "high",
                "alternatives": [
                    "Glutamate metabolism",
                    "Phosphate metabolism",
                ],
                "abstain": False,
                "abstain_reason": None,
            }
        )
    )
    assert parsed.ok
    assert parsed.value is not None
    assert [alt.pathway_name for alt in parsed.value.alternatives] == [
        "Glutamate metabolism",
        "Phosphate metabolism",
    ]


def test_parser_accepts_abstain_only_with_null_primary_and_empty_alternatives() -> None:
    valid_abstain = _payload(
        pathway_prediction={
            "primary": None,
            "alternatives": [],
            "abstain": True,
            "abstain_reason": "No defensible pathway prediction.",
        },
        claims=[],
    )
    assert parse_pathway_prediction_contract(valid_abstain).ok

    invalid_abstain = _payload(
        pathway_prediction={
            "primary": {
                "pathway_id": "WP:WP167",
                "pathway_name": "Eicosanoid synthesis",
                "pathway_source": "WikiPathways",
                "confidence": 0.3,
                "evidence_methods": [],
                "supporting_claim_indices": [],
                "rationale": "Still filled.",
            },
            "alternatives": [],
            "abstain": True,
            "abstain_reason": "No defensible pathway prediction.",
        }
    )
    assert not parse_pathway_prediction_contract(invalid_abstain).ok


def test_analysis_primary_name_exact_uses_pathway_prediction_not_first_claim() -> None:
    payload = _payload(
        pathway_prediction=_prediction(
            primary_name="Arachidonic acid metabolism",
            primary_id="KEGG:hsa00590",
            supporting_claim_indices=[1],
        ),
        claims=[
            _claim("Wrong first claim", "WP:wrong"),
            _claim("Arachidonic acid metabolism", "KEGG:hsa00590"),
        ],
    )
    metrics = compute_pathway_prediction_metrics(
        payload,
        ground_truth_pathway_id="KEGG:hsa00590",
        ground_truth_pathway_name="Arachidonic acid metabolism",
        supported_claim_indices={1},
    )
    assert metrics["primary_name_exact"] is True
    assert metrics["primary_id_exact"] is True
    assert metrics["verifier_supported_primary"] is True


def test_analysis_keeps_claim_metrics_separate_from_pathway_metrics() -> None:
    payload = _payload()
    metrics = compute_pathway_prediction_metrics(
        payload,
        ground_truth_pathway_id="WP:WP167",
        ground_truth_pathway_name="Eicosanoid synthesis",
        claim_metrics={"supported": 7, "uv": 3},
    )
    assert metrics["primary_name_exact"] is True
    assert metrics["claim_metrics"] == {"supported": 7, "uv": 3}
    assert "supported" not in {k for k in metrics if k != "claim_metrics"}


def test_real_saved_task_dump_with_pathway_prediction_round_trips_runner_serialization() -> None:
    payload = _payload()
    ok, why = _validate_grammar_v2(payload)
    assert ok, why

    result = ConcordReactResult(
        task_id="roundtrip_task",
        final_narrative_json=json.dumps(payload),
        final_narrative_text=payload["narrative_text"],
        final_claims=payload["claims"],
        pathway_prediction=payload["pathway_prediction"],
    )
    encoded = json.loads(json.dumps(dataclasses.asdict(result)))
    assert encoded["pathway_prediction"]["primary"]["pathway_name"] == "Eicosanoid synthesis"
    assert parse_pathway_prediction_contract(
        {
            "pathway_prediction": encoded["pathway_prediction"],
            "narrative_text": encoded["final_narrative_text"],
            "claims": encoded["final_claims"],
        }
    ).ok


def test_semantic_match_uses_documented_single_rubric() -> None:
    assert pathway_semantic_match("Arachidonic acid metabolism", "Eicosanoid synthesis")
    assert pathway_semantic_match("Vitamin B2 metabolism", "Riboflavin Metabolism")
    assert pathway_semantic_match("Fatty acid biosynthesis", "De novo fatty acid biosynthesis")
    assert not pathway_semantic_match("Urea cycle", "Urea cycle/amino group metabolism")


def test_system_prompt_keeps_pathway_prediction_out_of_main_react_prompt(monkeypatch) -> None:
    monkeypatch.delenv("METAGENT_DISABLE_PATHWAY_PREDICTION_CONTRACT", raising=False)
    _load_template.cache_clear()
    prompt = get_system_prompt()
    assert '"pathway_prediction"' not in prompt
    assert "pathway_prediction.primary" not in prompt
    assert '"narrative_text"' in prompt
    assert '"claims"' in prompt


def test_system_prompt_disable_flag_is_noop_after_second_pass_split(monkeypatch) -> None:
    monkeypatch.setenv("METAGENT_DISABLE_PATHWAY_PREDICTION_CONTRACT", "1")
    _load_template.cache_clear()
    prompt = get_system_prompt()
    assert '"pathway_prediction"' not in prompt
    assert '"narrative_text"' in prompt
    monkeypatch.delenv("METAGENT_DISABLE_PATHWAY_PREDICTION_CONTRACT", raising=False)
    _load_template.cache_clear()
