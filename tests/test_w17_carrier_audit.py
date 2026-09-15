"""W17 D1 RED - carrier audit helper contracts."""
from __future__ import annotations


def test_rule_based_paradigm_detection_covers_method_variants():
    from scripts.metagent.w17_carrier_audit import rule_based_extract_paradigms

    row = rule_based_extract_paradigms(
        "MetaboAnalystR KEGG PSEA and m/z-direct Mummichog agree with RaMP ORA."
    )

    assert row["paradigms"] == ["RAMP", "METABOANALYSTR_PSEA", "MUMMICHOG"]
    assert row["method"] == "PSEA"


def test_rule_based_paradigm_detection_treats_namespaces_as_none():
    from scripts.metagent.w17_carrier_audit import PARADIGMS, rule_based_extract_paradigms

    assert "KEGG" not in PARADIGMS
    assert "REACTOME" not in PARADIGMS

    kegg_row = rule_based_extract_paradigms("tryptophan is in KEGG:hsa00380 pathway")
    reactome_row = rule_based_extract_paradigms("REACTOME:R-HSA-71384 is involved")

    assert kegg_row["paradigms"] == ["NONE"]
    assert reactome_row["paradigms"] == ["NONE"]


def test_rule_based_paradigm_detection_applies_v3_edge_rules():
    from scripts.metagent.w17_carrier_audit import rule_based_extract_paradigms

    generic_metabo = rule_based_extract_paradigms("MetaboAnalystR analysis shows p = 0.01 for pathway X")
    mumm_namespace = rule_based_extract_paradigms("MUMM:tyrosine_metabolism has p = 0.000420")
    mumm_mz_direct = rule_based_extract_paradigms("Mummichog m/z-direct analysis reports p = 0.000420")
    ramp_database = rule_based_extract_paradigms("Dihydrolipoate appears in RaMP")
    ramp_enrichment = rule_based_extract_paradigms("RaMP fold-enrichment is 1162 for the top hit")

    assert generic_metabo["paradigms"] == ["METABOANALYSTR_PSEA"]
    assert generic_metabo["confidence"] == 0.6
    assert mumm_namespace["paradigms"] == ["MUMMICHOG"]
    assert mumm_mz_direct["paradigms"] == ["MUMMICHOG"]
    assert mumm_mz_direct["method"] == "NONE"
    assert ramp_database["paradigms"] == ["NONE"]
    assert ramp_enrichment["paradigms"] == ["RAMP"]


def test_spot_check_v2_preserves_v1_manual_sample():
    from scripts.metagent.w17_carrier_audit import build_spot_check_from_v1_sample

    classified = [
        {
            "claim_id": "c1",
            "audit_id": "new_audit_id_should_not_matter",
            "source": "w15_attribution",
            "claim_text_excerpt": "tryptophan is in KEGG:hsa00380 pathway",
            "paradigms_cited": "NONE",
            "method": "NONE",
            "confidence": "0.90",
            "rationale": "v2",
        }
    ]
    v1_rows = [
        {
            "claim_id": "c1",
            "audit_id": "b001_p002",
            "source": "w15_attribution",
            "claim_text_excerpt": "tryptophan is in KEGG:hsa00380 pathway",
            "manual_paradigms": "NONE",
            "manual_method": "NONE",
        }
    ]

    rows, spot = build_spot_check_from_v1_sample(classified, v1_rows)

    assert rows[0]["audit_id"] == "b001_p002"
    assert rows[0]["paradigms_cited"] == "NONE"
    assert rows[0]["manual_paradigms"] == "NONE"
    assert rows[0]["strict_match"] == "yes"
    assert spot == {"n": 1, "matches": 1, "agreement_pct": 100.0}


def test_spot_check_uses_original_audit_id_when_claim_ids_repeat():
    from scripts.metagent.w17_carrier_audit import build_spot_check_from_v1_sample

    classified = [
        {
            "claim_id": "v1:c000",
            "audit_id": "b010_p014",
            "source": "w15_attribution",
            "claim_text_excerpt": "Three complementary pathway-enrichment paradigms converge on KEGG:hsa00052",
            "paradigms_cited": "NONE",
            "method": "NONE",
        },
        {
            "claim_id": "v1:c000",
            "audit_id": "b000_p001",
            "source": "w15_attribution",
            "claim_text_excerpt": "wrong duplicate",
            "paradigms_cited": "RAMP",
            "method": "NONE",
        },
    ]
    v1_rows = [
        {
            "claim_id": "v1:c000",
            "audit_id": "b010_p014",
            "source": "w15_attribution",
            "claim_text_excerpt": "Three complementary pathway-enrichment paradigms converge on KEGG:hsa00052",
        }
    ]

    rows, spot = build_spot_check_from_v1_sample(classified, v1_rows)

    assert rows[0]["audit_id"] == "b010_p014"
    assert rows[0]["claim_text_excerpt"].startswith("Three complementary")
    assert rows[0]["paradigms_cited"] == "NONE"
    assert spot["agreement_pct"] == 100.0


def test_carrier_crosstab_marks_schema_missing_when_wrapper_structured():
    from scripts.metagent.w17_carrier_audit import build_carrier_crosstab

    claim_counts = {"MUMMICHOG": 7, "RAMP": 11, "NONE": 3}
    carriers = [
        {
            "paradigm": "MUMMICHOG",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "no",
            "schema_field_populated_in_w16_traces": "no",
            "recommended_field": "mummichog_enrichment_result",
        },
        {
            "paradigm": "RAMP",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "yes",
            "schema_field_populated_in_w16_traces": "yes",
            "recommended_field": "ramp_enrichment_result",
        },
    ]

    rows = build_carrier_crosstab(claim_counts, carriers)

    by_name = {row["paradigm"]: row for row in rows}
    assert by_name["MUMMICHOG"]["missing_carrier"] == "yes"
    assert by_name["MUMMICHOG"]["reason"] == "schema field missing"
    assert by_name["RAMP"]["missing_carrier"] == "no"
    assert "NONE" not in by_name


def test_schema_field_proposal_uses_nested_variant_carriers():
    from scripts.metagent.w17_carrier_audit import propose_schema_fields

    crosstab = [
        {
            "paradigm": "METABOANALYSTR_PSEA",
            "claim_count": 5,
            "missing_carrier": "yes",
            "recommended_field": "metaboanalystr_enrichment_result",
        },
        {
            "paradigm": "METABOANALYSTR_MSEA",
            "claim_count": 2,
            "missing_carrier": "yes",
            "recommended_field": "metaboanalystr_enrichment_result",
        },
        {
            "paradigm": "FELLA_RWR",
            "claim_count": 3,
            "missing_carrier": "yes",
            "recommended_field": "fella_enrichment_result",
        },
    ]

    rows = propose_schema_fields(crosstab)

    fields = {row["new_field_name"]: row for row in rows}
    assert fields["metaboanalystr_enrichment_result"]["nesting_decision"] == "nested variants"
    assert fields["metaboanalystr_enrichment_result"]["claim_count"] == 7
    assert fields["fella_enrichment_result"]["nesting_decision"] == "nested variants"


def test_final_schema_fields_include_wrapper_inventory_carriers_even_without_claims():
    from scripts.metagent.w17_carrier_audit import final_schema_fields

    fields = final_schema_fields(
        [
            {
                "new_field_name": "mummichog_enrichment_result",
                "type": "dict[str, Any] | None = None",
                "source_wrapper": "MUMMICHOG",
                "nesting_decision": "single carrier",
                "priority": "P1",
                "claim_count": 156,
            }
        ]
    )

    by_name = {row["new_field_name"]: row for row in fields}
    assert list(by_name) == [
        "mummichog_enrichment_result",
        "metaboanalystr_enrichment_result",
        "sspa_enrichment_result",
        "fella_enrichment_result",
    ]
    assert by_name["sspa_enrichment_result"]["claim_count"] == 0
    assert by_name["fella_enrichment_result"]["nesting_decision"] == "nested variants"
