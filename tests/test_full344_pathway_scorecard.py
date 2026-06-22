from __future__ import annotations

import json
from pathlib import Path

from scripts.metagent import full344_pathway_scorecard as scorecard


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _prediction(name: str, pid: str = "WP:WP167") -> dict:
    return {
        "primary": {
            "pathway_id": pid,
            "pathway_name": name,
            "supporting_claim_indices": [0],
        },
        "alternatives": [],
        "abstain": False,
        "abstain_reason": None,
    }


def test_rows_mark_ratelimit_dumps_as_contaminated(tmp_path: Path) -> None:
    benchmark = {
        "ok_task": {
            "task_id": "ok_task",
            "ground_truth": {
                "perturbed_pathway": {
                    "id": "WP:WP167",
                    "name": "Arachidonic acid metabolism",
                    "ontology": "RaMP:wiki",
                }
            },
        },
        "bad_task": {
            "task_id": "bad_task",
            "ground_truth": {
                "perturbed_pathway": {
                    "id": "WP:WP1",
                    "name": "Some pathway",
                    "ontology": "RaMP:wiki",
                }
            },
        },
    }
    status_dir = tmp_path / "status"
    dump_dir = tmp_path / "path_x_full"
    _write_json(status_dir / "ok_task.json", {"task_id": "ok_task", "stratum": "hmdb_ramp", "ok": True})
    _write_json(status_dir / "bad_task.json", {"task_id": "bad_task", "stratum": "hmdb_ramp", "ok": True})
    _write_json(
        dump_dir / "ok_task.json",
        {
            "final_react_result": {
                "final_claims": [{"claim_text": "x"}],
                "pathway_prediction": _prediction("Eicosanoid synthesis"),
            }
        },
    )
    _write_json(
        dump_dir / "bad_task.json",
        {
            "error": "chat_error: RateLimitError: Token Plan exhausted",
            "final_react_result": {"final_claims": [], "pathway_prediction": None},
        },
    )

    rows = scorecard.rows_for_full344(status_dir=status_dir, dump_dir=dump_dir, benchmark=benchmark)

    by_id = {row["task_id"]: row for row in rows}
    assert by_id["ok_task"]["contaminated"] is False
    assert by_id["ok_task"]["primary_semantic_match"] is True
    assert by_id["bad_task"]["contaminated"] is True
    assert by_id["bad_task"]["contamination_reason"] == "ratelimit"


def test_summary_reports_all_and_clean_denominators(tmp_path: Path) -> None:
    rows = [
        {
            "task_id": "a",
            "stratum": "human1",
            "contaminated": False,
            "contamination_reason": "",
            "pathway_prediction_ok": True,
            "primary_id_exact": False,
            "primary_name_exact": False,
            "primary_semantic_match": True,
            "topk_id_exact": False,
            "topk_name_exact": False,
            "topk_semantic_match": True,
            "abstain": False,
        },
        {
            "task_id": "b",
            "stratum": "human1",
            "contaminated": True,
            "contamination_reason": "ratelimit",
            "pathway_prediction_ok": False,
            "primary_id_exact": False,
            "primary_name_exact": False,
            "primary_semantic_match": False,
            "topk_id_exact": False,
            "topk_name_exact": False,
            "topk_semantic_match": False,
            "abstain": False,
        },
    ]

    summary = scorecard.summarize(rows)

    assert summary["all"]["by_stratum"]["human1"]["tasks"] == 2
    assert summary["all"]["by_stratum"]["human1"]["primary_semantic_match_rate"] == 0.5
    assert summary["clean"]["by_stratum"]["human1"]["tasks"] == 1
    assert summary["clean"]["by_stratum"]["human1"]["primary_semantic_match_rate"] == 1.0
    assert summary["contamination"]["by_stratum"]["human1"]["ratelimit"] == 1


def test_validation_candidates_keep_semantic_and_abstain_separate() -> None:
    rows = [
        {"task_id": "s1", "stratum": "human1", "contaminated": False, "primary_semantic_match": True, "topk_semantic_match": True, "abstain": False},
        {"task_id": "a1", "stratum": "human1", "contaminated": False, "primary_semantic_match": False, "topk_semantic_match": False, "abstain": True},
        {"task_id": "dirty", "stratum": "human1", "contaminated": True, "primary_semantic_match": True, "topk_semantic_match": True, "abstain": False},
    ]

    candidates = scorecard.validation_candidates(rows, per_type=2)

    assert [(row["task_id"], row["validation_type"]) for row in candidates] == [
        ("s1", "semantic_match"),
        ("a1", "abstain"),
    ]


def test_default_llm_log_path_follows_out_dir_name() -> None:
    out_dir = scorecard.ROOT / "data/metagent/full344_fullpipeline_eval_gpt55_20260620"

    assert scorecard.default_llm_log_path(out_dir) == (
        scorecard.ROOT / "logs/concord/full344_fullpipeline_eval_gpt55_20260620.jsonl"
    )
