from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.metagent.w18_dual_audit import (
    BATCH_SIZE,
    CarrierStats,
    build_judge_pool,
    build_v4_spot_check_pool,
    classify_batches,
    compute_target,
    count_carriers,
    load_benchmark_carriers,
    load_cached_judgments,
    system_prompt,
)


def test_count_carriers_reads_nested_react_result_carriers(tmp_path: Path):
    trace = tmp_path / "task.json"
    trace.write_text(
        json.dumps(
            {
                "task_id": "t1",
                "final_react_result": {
                    "enrichment_carriers": {
                        "mummichog_enrichment_result": {"pathways": [{"pathway_id": "MUMM:x"}]},
                        "metaboanalystr_enrichment_result": {"psea": {"pathways": []}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    stats = count_carriers(tmp_path)

    assert stats.n_tasks == 1
    assert stats.non_empty["mummichog_enrichment_result"] == 1
    assert stats.non_empty["metaboanalystr_enrichment_result.psea"] == 1
    assert stats.non_empty["sspa_enrichment_result"] == 0


def test_count_carriers_merges_benchmark_ramp_carrier(tmp_path: Path):
    trace = tmp_path / "task.json"
    trace.write_text(
        json.dumps({"task_id": "t1", "final_react_result": {"enrichment_carriers": {}}}),
        encoding="utf-8",
    )

    stats = count_carriers(tmp_path, benchmark_carriers={"t1": {"ramp_enrichment_result": {"top_pathways": []}}})

    assert stats.non_empty["ramp_enrichment_result"] == 1


def test_load_benchmark_carriers_indexes_ramp_by_task_id(tmp_path: Path):
    benchmark = tmp_path / "tasks.jsonl"
    benchmark.write_text(
        json.dumps({"task_id": "t1", "ramp_enrichment_result": {"top_pathways": []}}) + "\n",
        encoding="utf-8",
    )

    carriers = load_benchmark_carriers(benchmark)

    assert carriers["t1"]["ramp_enrichment_result"] == {"top_pathways": []}


def test_carrier_stats_detects_non_ramp_population():
    stats = CarrierStats()
    stats.record({"mummichog_enrichment_result": {"pathways": []}})
    stats.record({})

    assert stats.any_non_ramp_populated() is True
    assert stats.rate("mummichog_enrichment_result") == 50.0


def test_build_judge_pool_joins_w15_and_w17_by_claim_id(tmp_path: Path):
    w15 = tmp_path / "attribution.csv"
    w17 = tmp_path / "inventory.csv"
    with w15.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["claim_id", "claim_type", "attribution", "w11_bucket", "claim_text"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "claim_id": "c1",
                "claim_type": "BIOLOGICAL",
                "attribution": "verifier_gap",
                "w11_bucket": "C1",
                "claim_text": "Mummichog reports pathway X.",
            }
        )
        writer.writerow(
            {
                "claim_id": "c2",
                "claim_type": "FACTUAL",
                "attribution": "producer_fault",
                "w11_bucket": "C9",
                "claim_text": "bad claim",
            }
        )
    with w17.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["claim_id", "paradigms_cited", "method"])
        writer.writeheader()
        writer.writerow({"claim_id": "c1", "paradigms_cited": "MUMMICHOG", "method": "NONE"})

    pool = build_judge_pool(w15, w17)

    assert [row["claim_id"] for row in pool] == ["c1", "c2"]
    assert pool[0]["paradigms_cited"] == "MUMMICHOG"
    assert pool[1]["paradigms_cited"] == "NONE"


def test_build_judge_pool_joins_w15_and_w17_by_claim_and_task(tmp_path: Path):
    w15 = tmp_path / "attribution.csv"
    w17 = tmp_path / "inventory.csv"
    with w15.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["claim_id", "task_id_tail", "claim_type", "attribution", "w11_bucket", "claim_text"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "claim_id": "c1",
                "task_id_tail": "task_a",
                "claim_type": "GROUNDED",
                "attribution": "verifier_gap",
                "w11_bucket": "C1",
                "claim_text": "task a claim",
            }
        )
        writer.writerow(
            {
                "claim_id": "c1",
                "task_id_tail": "task_b",
                "claim_type": "GROUNDED",
                "attribution": "verifier_gap",
                "w11_bucket": "C1",
                "claim_text": "task b claim",
            }
        )
    with w17.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["claim_id", "task_id_tail", "paradigms_cited", "method", "rationale"])
        writer.writeheader()
        writer.writerow(
            {
                "claim_id": "c1",
                "task_id_tail": "task_a",
                "paradigms_cited": "MUMMICHOG",
                "method": "NONE",
                "rationale": "task a rationale",
            }
        )
        writer.writerow(
            {
                "claim_id": "c1",
                "task_id_tail": "task_b",
                "paradigms_cited": "RAMP",
                "method": "ORA",
                "rationale": "task b rationale",
            }
        )

    pool = build_judge_pool(w15, w17)

    assert pool[0]["paradigms_cited"] == "MUMMICHOG"
    assert pool[0]["carrier_audit_rationale"] == "task a rationale"
    assert pool[1]["paradigms_cited"] == "RAMP"
    assert pool[1]["carrier_audit_rationale"] == "task b rationale"


def test_compute_target_uses_ceiling_times_point_six():
    target = compute_target(strict_count=100, total_uv=901, baseline_uv_rate_pct=44.92)

    assert target["strict_ceiling_pp"] == 4.99
    assert target["target_drop_pp"] == 2.99
    assert target["target_uv_rate_pct"] == 41.93


def test_classify_batches_does_not_collapse_duplicate_claim_ids():
    pool = [
        {"audit_id": "a1", "claim_id": "c1", "claim_text": "first"},
        {"audit_id": "a2", "claim_id": "c1", "claim_text": "second"},
    ]

    rows = classify_batches(
        pool,
        lambda batch, batch_idx: [
            {"audit_id": row["audit_id"], "claim_id": row["claim_id"], "label": "judge_strict"}
            for row in batch
        ],
    )

    assert [row["audit_id"] for row in rows] == ["a1", "a2"]
    assert [row["claim_text"] for row in rows] == ["first", "second"]


def test_load_cached_judgments_reads_successful_batches(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    log.write_text(
        json.dumps(
            {
                "caller": "w18.dual_audit.judge_fitness",
                "trace_id": "w18_dual_audit.batch003",
                "response_cleaned": json.dumps(
                    {"items": [{"audit_id": "a1", "claim_id": "c1", "label": "judge_strict"}]}
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cached = load_cached_judgments(log)

    assert cached[3][0]["audit_id"] == "a1"


def test_classify_batches_maps_legacy_cached_items_by_position():
    pool = [
        {"audit_id": "a1", "claim_id": "c1", "claim_text": "first"},
        {"audit_id": "a2", "claim_id": "c2", "claim_text": "second"},
    ]
    cached = {0: [{"claim_id": "c1", "label": "judge_strict"}, {"claim_id": "c2", "label": "judge_uncoverable"}]}

    rows = classify_batches(pool, lambda batch, batch_idx: [], cached_batches=cached)

    assert rows[0]["label"] == "judge_strict"
    assert rows[1]["label"] == "judge_uncoverable"


def test_classify_batches_maps_empty_audit_id_items_by_position():
    pool = [
        {"audit_id": "a1", "claim_id": "c1", "claim_text": "first"},
        {"audit_id": "a2", "claim_id": "c2", "claim_text": "second"},
    ]

    rows = classify_batches(
        pool,
        lambda batch, batch_idx: [
            {"audit_id": "", "claim_id": row["claim_id"], "label": "judge_strict"}
            for row in batch
        ],
    )

    assert [row["audit_id"] for row in rows] == ["a1", "a2"]


def test_classify_batches_retries_incomplete_cached_batch():
    pool = [
        {"audit_id": "a1", "claim_id": "c1", "claim_text": "first"},
        {"audit_id": "a2", "claim_id": "c2", "claim_text": "second"},
    ]
    cached = {0: [{"audit_id": "a1", "claim_id": "c1", "label": "judge_strict"}]}

    rows = classify_batches(
        pool,
        lambda batch, batch_idx: [
            {"audit_id": row["audit_id"], "claim_id": row["claim_id"], "label": "judge_uncoverable"}
            for row in batch
        ],
        cached_batches=cached,
    )

    assert [row["label"] for row in rows] == ["judge_uncoverable", "judge_uncoverable"]


def test_classify_batches_rejects_incomplete_fresh_batch():
    pool = [
        {"audit_id": "a1", "claim_id": "c1", "claim_text": "first"},
        {"audit_id": "a2", "claim_id": "c2", "claim_text": "second"},
    ]

    try:
        classify_batches(pool, lambda batch, batch_idx: [{"audit_id": "a1", "claim_id": "c1", "label": "judge_strict"}])
    except ValueError as error:
        assert "incomplete batch" in str(error)
    else:
        raise AssertionError("expected incomplete batch failure")


def test_batch_size_keeps_json_responses_below_minimax_cap():
    assert BATCH_SIZE <= 10


def test_v4_system_prompt_contains_edge_case_rules():
    prompt = system_prompt(rubric_version="v4")

    assert "Do not use markdown" in prompt
    assert "Do not explain" in prompt
    assert "EDGE CASE RESOLUTIONS — V4" in prompt
    assert "External KB scope leak" in prompt
    assert "Identifier-as-content miscoding" in prompt
    assert "Interpretive contribution language" in prompt
    assert "Undefined placement / status terms" in prompt
    assert "Mummichog rank/score claim" in prompt


def test_build_v4_spot_check_pool_preserves_reviewed_sample_order(tmp_path: Path):
    reviewed = tmp_path / "reviewed.csv"
    with reviewed.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["audit_id", "review_label"])
        writer.writeheader()
        writer.writerow({"audit_id": "a2", "review_label": "judge_uncoverable"})
        writer.writerow({"audit_id": "a1", "review_label": "judge_strict"})
    pool = [
        {"audit_id": "a1", "claim_id": "c1", "claim_text": "first"},
        {"audit_id": "a2", "claim_id": "c2", "claim_text": "second"},
    ]

    sample = build_v4_spot_check_pool(pool, reviewed)

    assert [row["audit_id"] for row in sample] == ["a2", "a1"]
    assert [row["manual_label"] for row in sample] == ["judge_uncoverable", "judge_strict"]
