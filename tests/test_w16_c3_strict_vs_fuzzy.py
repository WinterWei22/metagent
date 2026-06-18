"""W16 D1 RED - C3 signal_evidence strict-vs-fuzzy reclassification.

Pins the pure-audit helper contract before implementing
``scripts.metagent.w16_c3_strict_vs_fuzzy``:

1. Load only W15 v2 rows with ``w11_bucket == C3``.
2. Use positional IDs in LLM batches so duplicate claim IDs do not collide.
3. Parse strict JSON list responses and merge labels back to original rows.
4. Compute UV-drop ceiling and target from strict count / 901 W14 UV claims.
"""
from __future__ import annotations

from pathlib import Path


_ATTRIBUTION_V2 = (
    Path(__file__).resolve().parents[1]
    / "data" / "metagent" / "w15_uv_attribution" / "attribution_v2.csv"
)


def test_load_c3_claims_filters_w15_v2_csv():
    from scripts.metagent.w16_c3_strict_vs_fuzzy import load_c3_claims

    rows = load_c3_claims(_ATTRIBUTION_V2)

    assert len(rows) == 150
    assert {row["w11_bucket"] for row in rows} == {"C3"}
    assert rows[0]["claim_text"]
    assert rows[0]["claim_type"]
    assert rows[0]["verifier_layer"]


def test_build_positional_batch_prevents_duplicate_claim_id_collision():
    from scripts.metagent.w16_c3_strict_vs_fuzzy import build_positional_batch

    batch = [
        {
            "claim_id": "v1:c008",
            "claim_text": "Mummichog reports p = 0.000420.",
            "claim_type": "GROUNDED",
            "verifier_layer": "factual_sub6",
            "attribution": "verifier_gap",
        },
        {
            "claim_id": "v1:c008",
            "claim_text": "ORA rank is 3 for tyrosine metabolism.",
            "claim_type": "GROUNDED",
            "verifier_layer": "factual_sub6",
            "attribution": "verifier_gap",
        },
    ]

    positional, pos_map = build_positional_batch(batch, batch_index=7)

    assert [row["claim_id"] for row in positional] == ["b007_p000", "b007_p001"]
    assert pos_map["b007_p000"]["claim_text"].startswith("Mummichog")
    assert pos_map["b007_p001"]["claim_text"].startswith("ORA")


def test_parse_and_merge_response_preserves_original_rows():
    from scripts.metagent.w16_c3_strict_vs_fuzzy import (
        build_positional_batch,
        merge_batch_labels,
        parse_llm_json_list,
    )

    batch = [
        {"claim_id": "v1:c001", "claim_text": "p = 0.01", "w11_bucket": "C3"},
        {"claim_id": "v1:c001", "claim_text": "significantly enriched", "w11_bucket": "C3"},
        {"claim_id": "v1:c002", "claim_text": "ranked first", "w11_bucket": "C3"},
    ]
    _, pos_map = build_positional_batch(batch, batch_index=0)
    parsed = parse_llm_json_list(
        "```json\n"
        "["
        "{\"claim_id\": \"b000_p000\", \"bucket\": \"strict_signal_lookup\"},"
        "{\"claim_id\": \"b000_p001\", \"bucket\": \"fuzzy_signal_inference\"},"
        "{\"claim_id\": \"b000_p002\", \"bucket\": \"unsupported_bucket\"}"
        "]\n```"
    )

    merged = merge_batch_labels(pos_map, parsed)

    assert [row["claim_id"] for row in merged] == ["v1:c001", "v1:c001", "v1:c002"]
    assert [row["bucket"] for row in merged] == [
        "strict_signal_lookup",
        "fuzzy_signal_inference",
        "UNCLASSIFIED",
    ]


def test_summarize_classifications_computes_uv_ceiling_and_target():
    from scripts.metagent.w16_c3_strict_vs_fuzzy import summarize_classifications

    rows = (
        [{"bucket": "strict_signal_lookup"} for _ in range(30)]
        + [{"bucket": "fuzzy_signal_inference"} for _ in range(20)]
        + [{"bucket": "UNCLASSIFIED"}]
    )

    summary = summarize_classifications(rows, total_uv_claims=901)

    assert summary["n_c3_total"] == 51
    assert summary["n_strict_signal_lookup"] == 30
    assert summary["n_fuzzy_signal_inference"] == 20
    assert summary["n_unclassified"] == 1
    assert summary["w14_uv_total"] == 901
    assert summary["strict_signal_ceiling_pp"] == 3.33
    assert summary["target_pp_at_0p6_ceiling"] == 2.00
