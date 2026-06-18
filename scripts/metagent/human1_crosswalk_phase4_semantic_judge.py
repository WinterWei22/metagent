#!/usr/bin/env python3
"""Human1 crosswalk Phase 4 semantic pathway judging from saved dumps.

This is an offline evaluator. It does not rerun ReAct and does not change the
Stage2 output contract. It compares each saved task's top-k pathway predictions
against the Human1 ground-truth pathway name using an LLM semantic judge.
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.llm_client import chat, set_log_path


BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
DUMP_DIR = ROOT / "data/metagent/human1_crosswalk_full117/path_x_full"
OUT_DIR = ROOT / "reports/reports_v2"
DETAIL_CSV = OUT_DIR / "2026-06-17_human1_phase4_semantic_pathway_judge.csv"
SUMMARY_JSON = OUT_DIR / "2026-06-17_human1_phase4_semantic_pathway_judge_metrics.json"
REPORT_MD = OUT_DIR / "2026-06-17_human1_phase4_semantic_pathway_judge.md"
VALIDATION_MD = OUT_DIR / "2026-06-17_human1_phase4_semantic_manual_validation.md"
LLM_LOG = ROOT / "logs/concord/human1_crosswalk_phase4_semantic_judge.jsonl"
MASTER_LOG = ROOT / "conversation/master/2026-06-17_190000_human1-phase4-semantic-judge.md"
MINIMAX_KEY_FILE = ROOT.parent / "metagent_day1_v5/api_key_minimax.txt"

MODEL = "MiniMax-M2.7-highspeed"
TOP_K = 5
PROMPT_COST_PER_M = 0.30
COMPLETION_COST_PER_M = 1.20


@dataclass(frozen=True)
class Prediction:
    rank: int
    pathway_id: str
    pathway_name: str
    evidence_method: str
    claim_text: str


def norm_name(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"\b(?:kegg|map|hsa|rno|mmu|wp|reactome|smpdb|mumm):?\d*\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def load_benchmark() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with BENCHMARK.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            gt = row.get("ground_truth") or {}
            pathway = gt.get("perturbed_pathway") or {}
            if pathway.get("ontology") == "Human1":
                out[str(row["task_id"])] = row
    return out


def prediction_name(pred: Prediction) -> str:
    return pred.pathway_name or pred.pathway_id


def extract_predictions(task_dump: dict[str, Any], top_k: int = TOP_K) -> list[Prediction]:
    final = task_dump.get("final_react_result") or {}
    claims = final.get("final_claims") or []
    out: list[Prediction] = []
    seen: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        if str(claim.get("claim_type") or "") != "PATHWAY_ENRICHMENT":
            continue
        name = str(claim.get("pathway_name") or "").strip()
        pathway_id = str(claim.get("pathway_id") or "").strip()
        value = name or pathway_id
        key = norm_name(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            Prediction(
                rank=len(out) + 1,
                pathway_id=pathway_id,
                pathway_name=name,
                evidence_method=str(claim.get("evidence_method") or ""),
                claim_text=str(claim.get("claim_text") or ""),
            )
        )
        if len(out) >= top_k:
            break
    return out


def deterministic_metrics(gt_name: str, preds: list[Prediction]) -> dict[str, Any]:
    gt_norm = norm_name(gt_name)
    names = [prediction_name(p) for p in preds]
    exact_ranks = [i + 1 for i, name in enumerate(names) if gt_norm and norm_name(name) == gt_norm]
    loose_ranks = [
        i + 1
        for i, name in enumerate(names)
        if gt_norm
        and norm_name(name)
        and (gt_norm in norm_name(name) or norm_name(name) in gt_norm)
    ]
    return {
        "id_exact_hit": any(str(p.pathway_id or "").strip() == gt_name for p in preds),
        "name_exact_hit": bool(exact_ranks),
        "name_exact_rank": exact_ranks[0] if exact_ranks else "",
        "name_match_loose_hit": bool(loose_ranks),
        "name_match_loose_rank": loose_ranks[0] if loose_ranks else "",
    }


def judge_semantic(task_id: str, gt_name: str, preds: list[Prediction]) -> dict[str, Any]:
    pred_lines = "\n".join(
        f"{p.rank}. name={prediction_name(p)!r}; id={p.pathway_id!r}; evidence_method={p.evidence_method!r}"
        for p in preds
    ) or "(no pathway predictions)"
    prompt = f"""You are judging pathway-name equivalence for a metabolomics benchmark.

Ground truth Human1 pathway:
{gt_name}

Model top-{TOP_K} pathway predictions, in rank order:
{pred_lines}

Decide whether ANY predicted pathway is semantically equivalent to the ground truth pathway.

Count as equivalent when the prediction names the same biochemical pathway, a well-known pathway-family synonym, or a pathway that directly denotes the same biochemical cascade. For example, "Eicosanoid synthesis" can match "Arachidonic acid metabolism" when the prediction clearly refers to arachidonic acid/eicosanoid biology.

Do NOT count broad neighboring metabolism, generic superclass overlap, or sharing one metabolite family as equivalent.

Return only JSON:
{{
  "semantic_hit": true,
  "best_rank": 1,
  "best_prediction_name": "...",
  "confidence": 0.0,
  "rationale": "short reason"
}}

Use semantic_hit=false, best_rank=null, best_prediction_name=null when there is no equivalent prediction.
"""
    raw = chat(
        [
            {"role": "system", "content": "You are a precise pathway semantic equivalence judge. Output only JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=2500,
        model=MODEL,
        provider="minimax",
        trace_id=f"human1.phase4.semantic.{task_id}",
        caller="scripts.metagent.human1_crosswalk_phase4_semantic_judge",
        response_format={"type": "json_object"},
    )
    data = coerce_json(raw)
    if not isinstance(data, dict):
        return {
            "semantic_hit": False,
            "best_rank": None,
            "best_prediction_name": None,
            "confidence": 0.0,
            "rationale": "parse failure",
            "raw_response": raw,
        }
    return {
        "semantic_hit": bool(data.get("semantic_hit")),
        "best_rank": data.get("best_rank"),
        "best_prediction_name": data.get("best_prediction_name"),
        "confidence": clamp_float(data.get("confidence")),
        "rationale": str(data.get("rationale") or ""),
        "raw_response": raw,
    }


def validate_hit(row: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""Validate this claimed semantic pathway match.

Ground truth pathway: {row['gt_name']}
Predicted pathway: {row['semantic_best_prediction_name']}
Prediction rank: {row['semantic_best_rank']}
Original judge rationale: {row['semantic_rationale']}

Question: is this a true semantic hit for the benchmark's intended pathway prediction?

Be stricter than the first-pass judge. Accept synonyms or directly equivalent biochemical cascades. Reject broad neighboring pathways, generic superclasses, or pathways sharing only a few metabolites.

Return only JSON:
{{
  "manual_tp": true,
  "confidence": 0.0,
  "rationale": "short reason"
}}
"""
    raw = chat(
        [
            {"role": "system", "content": "You are a strict manual validator for pathway semantic matches. Output only JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=2500,
        model=MODEL,
        provider="minimax",
        trace_id=f"human1.phase4.validate.{row['task_id']}",
        caller="scripts.metagent.human1_crosswalk_phase4_semantic_judge.validation",
        response_format={"type": "json_object"},
    )
    data = coerce_json(raw)
    if not isinstance(data, dict):
        return {"manual_tp": False, "confidence": 0.0, "rationale": "parse failure", "raw_response": raw}
    return {
        "manual_tp": bool(data.get("manual_tp")),
        "confidence": clamp_float(data.get("confidence")),
        "rationale": str(data.get("rationale") or ""),
        "raw_response": raw,
    }


def coerce_json(raw: str) -> Any:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def clamp_float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def configure_minimax() -> None:
    os.environ["METAGENT_LLM_PROVIDER"] = "minimax"
    os.environ["METAGENT_MINIMAX_MODEL"] = MODEL
    if not os.environ.get("MINIMAX_API_KEY") and MINIMAX_KEY_FILE.exists():
        os.environ["MINIMAX_API_KEY"] = MINIMAX_KEY_FILE.read_text(encoding="utf-8").strip()
    set_log_path(LLM_LOG)


def llm_cost() -> dict[str, Any]:
    if not LLM_LOG.exists():
        return {
            "llm_rows": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "actual_cost_usd": 0.0,
            "llm_errors": 0,
            "models": [],
        }
    rows: list[dict[str, Any]] = []
    for line in LLM_LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    prompt = sum(int(row.get("prompt_tokens") or 0) for row in rows)
    completion = sum(int(row.get("completion_tokens") or 0) for row in rows)
    cached = sum(int(row.get("cached_tokens") or 0) for row in rows)
    total = sum(int(row.get("total_tokens") or 0) for row in rows)
    return {
        "llm_rows": len(rows),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cached_tokens": cached,
        "total_tokens": total,
        "actual_cost_usd": round(prompt * PROMPT_COST_PER_M / 1_000_000 + completion * COMPLETION_COST_PER_M / 1_000_000, 6),
        "llm_errors": sum(1 for row in rows if row.get("error")),
        "models": sorted({str(row.get("model")) for row in rows if row.get("model")}),
    }


def ratio(num: int, den: int) -> float:
    return round(num / den, 6) if den else 0.0


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_rows() -> list[dict[str, Any]]:
    benchmark = load_benchmark()
    rows: list[dict[str, Any]] = []
    for dump_path in sorted(DUMP_DIR.glob("*.json")):
        task_id = dump_path.stem
        task = benchmark.get(task_id)
        if not task:
            continue
        obj = json.loads(dump_path.read_text(encoding="utf-8"))
        gt = task["ground_truth"]["perturbed_pathway"]
        gt_name = str(gt["name"])
        gt_id = str(gt["id"])
        preds = extract_predictions(obj)
        deterministic = deterministic_metrics(gt_name, preds)
        judged = judge_semantic(task_id, gt_name, preds)
        rows.append(
            {
                "task_id": task_id,
                "gt_id": gt_id,
                "gt_name": gt_name,
                "n_predictions": len(preds),
                "top1_prediction_name": prediction_name(preds[0]) if preds else "",
                "top1_prediction_id": preds[0].pathway_id if preds else "",
                "topk_prediction_names": " | ".join(prediction_name(p) for p in preds),
                "topk_prediction_ids": " | ".join(p.pathway_id for p in preds),
                "id_exact_hit": deterministic["id_exact_hit"],
                "name_exact_hit": deterministic["name_exact_hit"],
                "name_exact_rank": deterministic["name_exact_rank"],
                "name_match_loose_hit": deterministic["name_match_loose_hit"],
                "name_match_loose_rank": deterministic["name_match_loose_rank"],
                "semantic_hit": judged["semantic_hit"],
                "semantic_best_rank": judged["best_rank"] if judged["best_rank"] is not None else "",
                "semantic_best_prediction_name": judged["best_prediction_name"] or "",
                "semantic_confidence": judged["confidence"],
                "semantic_rationale": judged["rationale"],
            }
        )
    return rows


def validate_semantic_hits(rows: list[dict[str, Any]], n: int = 15) -> list[dict[str, Any]]:
    hits = [row for row in rows if row["semantic_hit"]]
    hits.sort(key=lambda r: (str(r["task_id"])))
    rng = random.Random(20260617)
    sample = hits[:] if len(hits) <= n else rng.sample(hits, n)
    sample.sort(key=lambda r: str(r["task_id"]))
    out: list[dict[str, Any]] = []
    for row in sample:
        validation = validate_hit(row)
        merged = {
            "task_id": row["task_id"],
            "gt_name": row["gt_name"],
            "semantic_best_prediction_name": row["semantic_best_prediction_name"],
            "semantic_best_rank": row["semantic_best_rank"],
            "first_pass_confidence": row["semantic_confidence"],
            "first_pass_rationale": row["semantic_rationale"],
            "manual_tp": validation["manual_tp"],
            "manual_confidence": validation["confidence"],
            "manual_rationale": validation["rationale"],
        }
        out.append(merged)
    return out


def summarize(rows: list[dict[str, Any]], validation: list[dict[str, Any]]) -> dict[str, Any]:
    den = len(rows)
    id_exact = sum(1 for row in rows if row["id_exact_hit"])
    name_exact = sum(1 for row in rows if row["name_exact_hit"])
    loose = sum(1 for row in rows if row["name_match_loose_hit"])
    semantic = sum(1 for row in rows if row["semantic_hit"])
    rescued_vs_name_exact = sum(
        1 for row in rows if row["semantic_hit"] and not row["name_exact_hit"]
    )
    rescued_vs_loose = sum(
        1 for row in rows if row["semantic_hit"] and not row["name_match_loose_hit"]
    )
    validation_den = len(validation)
    validation_tp = sum(1 for row in validation if row["manual_tp"])
    return {
        "input": {
            "saved_dumps": den,
            "benchmark_human1_tasks": len(load_benchmark()),
            "top_k": TOP_K,
            "dump_dir": str(DUMP_DIR.relative_to(ROOT)),
            "llm_log": str(LLM_LOG.relative_to(ROOT)),
        },
        "metrics": {
            "id_exact_hits": id_exact,
            "id_exact_rate": ratio(id_exact, den),
            "name_exact_hits": name_exact,
            "name_exact_rate": ratio(name_exact, den),
            "name_match_loose_hits": loose,
            "name_match_loose_rate": ratio(loose, den),
            "semantic_hits": semantic,
            "semantic_rate": ratio(semantic, den),
            "semantic_rescued_vs_name_exact": rescued_vs_name_exact,
            "semantic_rescued_vs_name_exact_rate": ratio(rescued_vs_name_exact, den),
            "semantic_rescued_vs_loose": rescued_vs_loose,
            "semantic_rescued_vs_loose_rate": ratio(rescued_vs_loose, den),
        },
        "validation": {
            "sampled_semantic_hits": validation_den,
            "manual_tp": validation_tp,
            "manual_tp_rate": ratio(validation_tp, validation_den),
            "pass_80pct_gate": ratio(validation_tp, validation_den) >= 0.80 if validation_den else False,
        },
        "cost": llm_cost(),
    }


def write_reports(summary: dict[str, Any], rows: list[dict[str, Any]], validation: list[dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(DETAIL_CSV, rows)

    validation_lines = [
        "# Human1 Phase 4 Semantic Hit Validation",
        "",
        f"- Sampled semantic hits: `{summary['validation']['sampled_semantic_hits']}`",
        f"- Manual TP: `{summary['validation']['manual_tp']}`",
        f"- Manual TP rate: `{percent(summary['validation']['manual_tp_rate'])}`",
        f"- Gate >=80%: `{'PASS' if summary['validation']['pass_80pct_gate'] else 'FAIL'}`",
        "",
        "| task_id | GT | predicted | rank | TP | rationale |",
        "|---|---|---|---:|---|---|",
    ]
    for row in validation:
        validation_lines.append(
            f"| {row['task_id']} | {row['gt_name']} | {row['semantic_best_prediction_name']} | "
            f"{row['semantic_best_rank']} | {row['manual_tp']} | {row['manual_rationale']} |"
        )
    VALIDATION_MD.write_text("\n".join(validation_lines) + "\n", encoding="utf-8")

    m = summary["metrics"]
    cost = summary["cost"]
    lines = [
        "# Human1 Crosswalk Phase 4 Semantic Pathway Judge",
        "",
        "Scope: offline evaluation over existing `human1_crosswalk_full117/path_x_full` dumps. No ReAct rerun and no output-contract change.",
        "",
        "## Headline",
        "",
        f"- Evaluated saved dumps: `{summary['input']['saved_dumps']}`.",
        f"- ID-exact hits: `{m['id_exact_hits']}` / `{summary['input']['saved_dumps']}` = `{percent(m['id_exact_rate'])}`.",
        f"- Exact pathway-name hits: `{m['name_exact_hits']}` / `{summary['input']['saved_dumps']}` = `{percent(m['name_exact_rate'])}`.",
        f"- Name-match hits, looser string containment: `{m['name_match_loose_hits']}` / `{summary['input']['saved_dumps']}` = `{percent(m['name_match_loose_rate'])}`. This is marked looser and should not be treated as exact accuracy.",
        f"- W18-style semantic judge hits: `{m['semantic_hits']}` / `{summary['input']['saved_dumps']}` = `{percent(m['semantic_rate'])}`.",
        f"- Semantic rescued vs exact-name: `{m['semantic_rescued_vs_name_exact']}` = `{percent(m['semantic_rescued_vs_name_exact_rate'])}` of all evaluated tasks.",
        f"- Semantic rescued vs loose name-match: `{m['semantic_rescued_vs_loose']}` = `{percent(m['semantic_rescued_vs_loose_rate'])}` of all evaluated tasks.",
        "",
        "## Validation",
        "",
        f"- Sampled semantic hits: `{summary['validation']['sampled_semantic_hits']}`.",
        f"- Manual TP: `{summary['validation']['manual_tp']}`.",
        f"- Manual TP rate: `{percent(summary['validation']['manual_tp_rate'])}`.",
        f"- >=80% gate: `{'PASS' if summary['validation']['pass_80pct_gate'] else 'FAIL'}`.",
        "",
        "## Cost",
        "",
        f"- LLM calls: `{cost['llm_rows']}`.",
        f"- Prompt tokens: `{cost['prompt_tokens']}`.",
        f"- Completion tokens: `{cost['completion_tokens']}`.",
        f"- Actual MiniMax cost estimate from JSONL token counts: `${cost['actual_cost_usd']:.6f}`.",
        f"- Log: `{summary['input']['llm_log']}`.",
        "",
        "## Artifacts",
        "",
        f"- Detail CSV: `{DETAIL_CSV.relative_to(ROOT)}`",
        f"- Metrics JSON: `{SUMMARY_JSON.relative_to(ROOT)}`",
        f"- Validation notes: `{VALIDATION_MD.relative_to(ROOT)}`",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    master = [
        "# Human1 Phase 4 Semantic Judge",
        "",
        "## What was requested",
        "",
        "Run true Phase 4 semantic pathway judging on the existing 115 Human1 crosswalk dumps, without rerunning ReAct or changing the output contract.",
        "",
        "## What was done",
        "",
        f"- Added and ran offline script: `scripts/metagent/human1_crosswalk_phase4_semantic_judge.py`.",
        f"- Compared top-{TOP_K} pathway predictions from saved `PATHWAY_ENRICHMENT` claims against Human1 GT pathway names.",
        "- Reported ID-exact, exact name, looser name-match, and LLM semantic rates separately.",
        "- Sampled semantic hits for a second strict validation pass.",
        "",
        "## Current status",
        "",
        f"- Saved dumps evaluated: `{summary['input']['saved_dumps']}`.",
        f"- ID-exact: `{m['id_exact_hits']}` / `{summary['input']['saved_dumps']}` = `{percent(m['id_exact_rate'])}`.",
        f"- Exact name: `{m['name_exact_hits']}` / `{summary['input']['saved_dumps']}` = `{percent(m['name_exact_rate'])}`.",
        f"- Name-match, looser: `{m['name_match_loose_hits']}` / `{summary['input']['saved_dumps']}` = `{percent(m['name_match_loose_rate'])}`.",
        f"- Semantic: `{m['semantic_hits']}` / `{summary['input']['saved_dumps']}` = `{percent(m['semantic_rate'])}`.",
        f"- Semantic rescued vs exact-name: `{m['semantic_rescued_vs_name_exact']}` tasks.",
        f"- Validation TP rate: `{summary['validation']['manual_tp']}` / `{summary['validation']['sampled_semantic_hits']}` = `{percent(summary['validation']['manual_tp_rate'])}`.",
        f"- Cost from JSONL token counts: `${cost['actual_cost_usd']:.6f}`.",
        "",
        "## Next step",
        "",
        "Review whether this semantic metric should become the Human1-facing pathway metric while keeping ID-exact and exact-name as stricter companion numbers.",
        "",
        "## Artifacts",
        "",
        f"- Report: `{REPORT_MD.relative_to(ROOT)}`",
        f"- CSV: `{DETAIL_CSV.relative_to(ROOT)}`",
        f"- JSON: `{SUMMARY_JSON.relative_to(ROOT)}`",
        f"- Validation: `{VALIDATION_MD.relative_to(ROOT)}`",
        f"- LLM log: `{LLM_LOG.relative_to(ROOT)}`",
    ]
    MASTER_LOG.parent.mkdir(parents=True, exist_ok=True)
    MASTER_LOG.write_text("\n".join(master) + "\n", encoding="utf-8")


def main() -> None:
    configure_minimax()
    if LLM_LOG.exists():
        LLM_LOG.unlink()
    rows = build_rows()
    validation = validate_semantic_hits(rows)
    summary = summarize(rows, validation)
    write_reports(summary, rows, validation)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
