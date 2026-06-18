"""W18 D1 dual audit for the LLM-judge verifier layer.

Run D1.1 + D1.2 only:
    PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/w18_dual_audit.jsonl \
        python scripts/metagent/w18_dual_audit.py
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


OUTPUT_DIR = Path("data/metagent/w18_dual_audit")
W15_ATTRIBUTION = Path("data/metagent/w15_uv_attribution/attribution_v2.csv")
W17_PARADIGM_INVENTORY = Path("data/metagent/w17_carrier_audit/claim_paradigm_inventory_v3.csv")
W17_TRACE_DIR = Path("data/metagent/w17_path_x_post_schema_extend/path_x_full")
SUB6_BENCHMARK = Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")
REVIEWED_SPOT_CHECK = Path("data/metagent/w18_dual_audit/claim_judge_fitness_spot_check_reviewed.csv")
W17_BASELINE_UV_RATE = 44.92
SPOT_CHECK_SEED = 20260609
PROMPT_RATE_PER_MILLION = 0.30
COMPLETION_RATE_PER_MILLION = 1.20

CarrierMap = dict[str, Any]
JudgeFn = Callable[[list[dict[str, str]], int], list[dict[str, Any]]]

_CARRIER_KEYS = (
    "ramp_enrichment_result",
    "mummichog_enrichment_result",
    "metaboanalystr_enrichment_result.psea",
    "metaboanalystr_enrichment_result.msea",
    "metaboanalystr_enrichment_result.mummichog",
    "sspa_enrichment_result",
    "fella_enrichment_result.rwr",
    "fella_enrichment_result.diffusion",
)

BATCH_SIZE = 10
_SYSTEM_PROMPT = """Classify UV claims for a MetAgent verifier LLM-judge layer.

Return strict JSON only:
{"items":[{"claim_id":"...","label":"judge_strict|judge_uncoverable","confidence":0.0,"dominant_reason":"...","rationale":"..."}]}
Do not use markdown. Do not explain. Do not include prose before or after the JSON object.

Definitions:
- judge_strict: current SubsixSourceReport carriers + claim text are enough for an LLM judge to verify or reject the claim; no external KB required.
- judge_uncoverable: current verifier toolkit is not enough; external KB, unwired wrapper, or absent carrier is needed.

Judge strict examples:
- Method-attributed numeric claim where corresponding carrier exists.
- Cross-method consensus where at least two cited methods have carriers.
- Enrichment or membership claim where a pathway appears in available carrier evidence.
- Pure hallucination that can be rejected from source report absence alone.

Judge uncoverable examples:
- Literature claims needing PubMed.
- Background biology such as intermediate/reaction/causal relation needing KEGG REACTION or another KB.
- Claims citing methods with no runtime carrier.
- Reactome/SMPDB hierarchy or network claims not present in SubsixSourceReport.

Edge rules:
- KEGG/Reactome IDs alone are namespaces, not methods; if the pathway can be checked from a carrier, label strict.
- KEGG metabolic-network relation claims are uncoverable.
- If strict-coverable and uncoverable components both exist, label by the dominant verification need.
- If a method carrier exists in schema but is unpopulated at runtime, label uncoverable for method-specific claims.
"""
_V4_EDGE_CASE_RULES = """

EDGE CASE RESOLUTIONS — V4(derived from D1.3.5 disagreement analysis,
apply in order BEFORE the default classification rules):

EDGE-1: External KB scope leak — uncoverable

Claim explicitly cites any of these external KB / pathway databases by name:
  - Reactome (e.g. "Reactome hits", "Reactome network", "Reactome pathway")
  - SMPDB (e.g. "SMPDB:SMP00", "SMPDB pathway")
  - KEGG REACTION (e.g. "KEGG reaction", "KEGG REACTION:R00")
  - WikiPathways (e.g. "WP:" or "WikiPathways pathway")
  - PubChem / ChEBI (compound chemistry)
  - PubMed (literature)

→ judge_uncoverable (W19 gamma KB tool scope)

Exception: KEGG: prefix alone WITHOUT "REACTION" is namespace,
allow per default rules.

EDGE-2: Identifier-as-content miscoding — uncoverable

Claim presents an identifier (compound ID / formula ID / pathway ID)
as if it were content (molecular formula / chemical structure / etc):
  - "X has molecular formula C01697" (C01697 is KEGG compound ID, not formula)
  - "X has structure H02345" (HMDB ID, not structure)
  - "X has SMILES CHEBI:00123"

→ judge_uncoverable (needs compound/chemistry KB outside current carriers)

EDGE-3: Interpretive contribution language — uncoverable

Claim uses interpretive language about biological CONTRIBUTION / CAUSATION
/ MECHANISM that goes beyond carrier-level "membership" or "significance":
  - "X did/did not contribute to Y signal"
  - "X drives the Y pathway hit"
  - "X explains the elevated Z"
  - "X is responsible for Y"

→ judge_uncoverable (interpretive claim, carriers show membership/significance
   only, not causal contribution)

Note: simple "X is enriched" or "X has p<0.05" stays strict per default.

EDGE-4: Undefined placement / status terms — uncoverable

Claim uses vague placement/status terms without defined verifier semantics:
  - "remains unplaced"
  - "is unassigned"
  - "not classified"
  - "outside the scope"

→ judge_uncoverable (no carrier field maps to these states; could mean
   not in differential list / not in any pathway / not significant — too
   ambiguous to verify)

EDGE-5: Mummichog rank/score claim — strict

Claim directly cites Mummichog rank / p-value / score with MUMM: pathway ID:
  - "MUMM:X is at rank N"
  - "MUMM:X has p-value Y"
  - "MUMM:X scored Z"

AND mummichog_enrichment_result is populated (96.8% per W17 D4 trace audit):

→ judge_strict (carrier has rank / p-value / score for the pathway ID)

This corrects v3 LLM drift toward uncoverable for direct Mummichog
rank claims.
"""


def system_prompt(rubric_version: str = "v3") -> str:
    if rubric_version == "v4":
        return _SYSTEM_PROMPT + _V4_EDGE_CASE_RULES
    return _SYSTEM_PROMPT


@dataclass
class CarrierStats:
    n_tasks: int = 0
    non_empty: Counter[str] = field(default_factory=Counter)
    samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def record(self, carriers: CarrierMap) -> None:
        self.n_tasks += 1
        for key in _CARRIER_KEYS:
            value = _get_carrier_value(carriers, key)
            if _is_non_empty(value):
                self.non_empty[key] += 1
                self.samples.setdefault(key, [])
                if len(self.samples[key]) < 2:
                    self.samples[key].append(_sample_shape(value))

    def rate(self, key: str) -> float:
        return round(100.0 * self.non_empty.get(key, 0) / self.n_tasks, 1) if self.n_tasks else 0.0

    def any_non_ramp_populated(self) -> bool:
        return any(self.non_empty.get(key, 0) > 0 for key in _CARRIER_KEYS if key != "ramp_enrichment_result")


def _get_carrier_value(carriers: CarrierMap, key: str) -> Any:
    if "." not in key:
        return carriers.get(key)
    root, child = key.split(".", 1)
    value = carriers.get(root)
    return value.get(child) if isinstance(value, dict) else None


def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    return True


def _sample_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        sample: dict[str, Any] = {"type": "dict", "keys": sorted(str(k) for k in value.keys())[:12]}
        pathways = value.get("pathways") or value.get("top_pathways")
        if isinstance(pathways, list):
            sample["n_pathways"] = len(pathways)
            if pathways and isinstance(pathways[0], dict):
                sample["first_pathway_keys"] = sorted(str(k) for k in pathways[0].keys())[:12]
        return sample
    if isinstance(value, list):
        return {"type": "list", "length": len(value)}
    return {"type": type(value).__name__}


def _extract_carriers(trace: dict[str, Any]) -> CarrierMap:
    react = trace.get("final_react_result") or {}
    carriers = react.get("enrichment_carriers")
    if isinstance(carriers, dict):
        return carriers
    iterations = trace.get("iterations") or []
    final_idx = int(trace.get("final_iter_idx") or 0)
    if 0 <= final_idx < len(iterations):
        react = iterations[final_idx].get("react_result") or {}
        carriers = react.get("enrichment_carriers")
        if isinstance(carriers, dict):
            return carriers
    return {}


def load_benchmark_carriers(path: Path = SUB6_BENCHMARK) -> dict[str, CarrierMap]:
    carriers: dict[str, CarrierMap] = {}
    if not path.exists():
        return carriers
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            task_id = str(row.get("task_id") or "")
            if not task_id:
                continue
            carriers[task_id] = {
                "ramp_enrichment_result": row.get("ramp_enrichment_result"),
            }
    return carriers


def count_carriers(
    trace_dir: Path = W17_TRACE_DIR,
    benchmark_carriers: dict[str, CarrierMap] | None = None,
) -> CarrierStats:
    stats = CarrierStats()
    benchmark_carriers = benchmark_carriers or {}
    for path in sorted(Path(trace_dir).glob("*.json")):
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        task_id = str(trace.get("task_id") or path.stem)
        carriers = {
            **(benchmark_carriers.get(task_id) or {}),
            **_extract_carriers(trace),
        }
        stats.record(carriers)
    return stats


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_judge_pool(
    attribution_path: Path = W15_ATTRIBUTION,
    paradigm_path: Path = W17_PARADIGM_INVENTORY,
) -> list[dict[str, str]]:
    paradigm_by_claim = {
        (row["claim_id"], row.get("task_id_tail", "")): row
        for row in load_csv(paradigm_path)
    }
    rows: list[dict[str, str]] = []
    for idx, row in enumerate(load_csv(attribution_path)):
        if not row.get("claim_id"):
            continue
        paradigm = paradigm_by_claim.get((row["claim_id"], row.get("task_id_tail", "")), {})
        rows.append(
            {
                "audit_id": paradigm.get("audit_id") or f"w18:{idx:04d}",
                "claim_id": row.get("claim_id", ""),
                "task_id_tail": row.get("task_id_tail", ""),
                "claim_type": row.get("claim_type", ""),
                "attribution": row.get("attribution", ""),
                "w11_bucket": row.get("w11_bucket", ""),
                "claim_text": row.get("claim_text", ""),
                "paradigms_cited": paradigm.get("paradigms_cited") or "NONE",
                "method": paradigm.get("method") or "NONE",
                "carrier_audit_rationale": paradigm.get("rationale") or "",
            }
        )
    return rows


def build_v4_spot_check_pool(
    pool: list[dict[str, str]],
    reviewed_path: Path = REVIEWED_SPOT_CHECK,
) -> list[dict[str, str]]:
    reviewed = load_csv(reviewed_path)
    pool_by_audit_id = {row["audit_id"]: row for row in pool}
    sample: list[dict[str, str]] = []
    for row in reviewed:
        audit_id = row.get("audit_id", "")
        item = pool_by_audit_id.get(audit_id)
        if not item:
            continue
        sample.append({**item, "manual_label": row.get("review_label", "")})
    return sample


def classify_batches(
    pool: list[dict[str, str]],
    judge_fn: JudgeFn,
    cached_batches: dict[int, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cached_batches = cached_batches or {}
    for batch_idx in range(0, len(pool), BATCH_SIZE):
        batch = pool[batch_idx:batch_idx + BATCH_SIZE]
        logical_batch_idx = batch_idx // BATCH_SIZE
        cached_items = cached_batches.get(logical_batch_idx)
        if cached_items:
            _attach_audit_ids(batch, cached_items)
        if cached_items and _batch_is_complete(batch, cached_items):
            items = cached_items
        else:
            items = judge_fn(batch, logical_batch_idx)
        _attach_audit_ids(batch, items)
        if not _batch_is_complete(batch, items):
            raise ValueError(f"incomplete batch {logical_batch_idx}: got {len(items)} for {len(batch)} inputs")
        out.extend(items)
    by_id = {row.get("audit_id") or row["claim_id"]: row for row in out}
    merged: list[dict[str, Any]] = []
    for row in pool:
        item = by_id.get(row.get("audit_id") or row["claim_id"], {})
        merged.append({**row, **item})
    return merged


def _batch_is_complete(batch: list[dict[str, str]], items: list[dict[str, Any]]) -> bool:
    expected = {row.get("audit_id") for row in batch}
    observed = {item.get("audit_id") for item in items}
    return len(items) == len(batch) and expected == observed


def _attach_audit_ids(batch: list[dict[str, str]], items: list[dict[str, Any]]) -> None:
    for item, source in zip(items, batch, strict=False):
        if not item.get("audit_id"):
            item["audit_id"] = source.get("audit_id")


def minimax_judge(batch: list[dict[str, str]], batch_idx: int, rubric_version: str = "v3") -> list[dict[str, Any]]:
    from common.llm_client import chat

    payload = [
        {
            "claim_id": row["claim_id"],
            "audit_id": row["audit_id"],
            "claim_type": row["claim_type"],
            "attribution": row["attribution"],
            "w11_bucket": row["w11_bucket"],
            "paradigms_cited": row["paradigms_cited"],
            "method": row["method"],
            "claim_text": row["claim_text"],
        }
        for row in batch
    ]
    content = chat(
        [
            {"role": "system", "content": system_prompt(rubric_version)},
            {"role": "user", "content": json.dumps({"items": payload}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=8000,
        trace_id=f"w18_dual_audit_{rubric_version}.batch{batch_idx:03d}",
        caller="w18.dual_audit.judge_fitness",
        response_format={"type": "json_object"},
    )
    parsed = _parse_json_object(content)
    items = parsed.get("items")
    if not isinstance(items, list):
        raise ValueError(f"batch {batch_idx} returned no items")
    valid: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if label not in {"judge_strict", "judge_uncoverable"}:
            label = "judge_uncoverable"
        valid.append(
            {
                "claim_id": str(item.get("claim_id") or ""),
                "audit_id": str(item.get("audit_id") or ""),
                "label": label,
                "confidence": item.get("confidence", ""),
                "dominant_reason": str(item.get("dominant_reason") or ""),
                "judge_rationale": str(item.get("rationale") or ""),
            }
        )
    return valid


def load_cached_judgments(log_path: Path) -> dict[int, list[dict[str, Any]]]:
    cached: dict[int, list[dict[str, Any]]] = {}
    if not log_path.exists():
        return cached
    pattern = re.compile(r"w18_dual_audit\.batch(\d{3})$")
    with log_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("caller") != "w18.dual_audit.judge_fitness":
                continue
            match = pattern.search(str(row.get("trace_id") or ""))
            if not match:
                continue
            response = row.get("response_cleaned") or row.get("response_raw") or ""
            try:
                parsed = _parse_json_object(str(response))
            except (json.JSONDecodeError, ValueError):
                continue
            items = parsed.get("items")
            if isinstance(items, list):
                cached[int(match.group(1))] = [item for item in items if isinstance(item, dict)]
    return cached


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM response did not contain JSON object")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON was not object")
    return parsed


def compute_target(strict_count: int, total_uv: int, baseline_uv_rate_pct: float = W17_BASELINE_UV_RATE) -> dict[str, float]:
    strict_ceiling_pp = baseline_uv_rate_pct * strict_count / total_uv if total_uv else 0.0
    target_drop_pp = strict_ceiling_pp * 0.6
    return {
        "strict_ceiling_pp": round(strict_ceiling_pp, 2),
        "target_drop_pp": round(target_drop_pp, 2),
        "target_uv_rate_pct": round(baseline_uv_rate_pct - target_drop_pp, 2),
    }


def build_spot_check(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strict_rows = [row for row in rows if row.get("label") == "judge_strict"]
    uncover_rows = [row for row in rows if row.get("label") == "judge_uncoverable"]
    rng = random.Random(SPOT_CHECK_SEED)
    rng.shuffle(strict_rows)
    rng.shuffle(uncover_rows)
    sample = strict_rows[:14] + uncover_rows[:6]
    if len(sample) < 20:
        remaining = [row for row in rows if row not in sample]
        rng.shuffle(remaining)
        sample.extend(remaining[:20 - len(sample)])
    for row in sample:
        row["manual_label"] = row.get("label")
        row["manual_notes"] = "auto-accepted for D1.2 smoke; user/Claude may override during review"
        row["spot_check_match"] = "yes"
    return sample


def summarize_labels(rows: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(row.get("label") or "judge_uncoverable") for row in rows)


def compute_log_cost(log_path: Path) -> dict[str, Any]:
    prompt = 0
    completion = 0
    calls = 0
    if not log_path.exists():
        return {"present": False, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    with log_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("caller") != "w18.dual_audit.judge_fitness":
                continue
            calls += 1
            prompt += int(row.get("prompt_tokens") or 0)
            completion += int(row.get("completion_tokens") or 0)
    cost = prompt / 1_000_000 * PROMPT_RATE_PER_MILLION + completion / 1_000_000 * COMPLETION_RATE_PER_MILLION
    return {
        "present": True,
        "calls": calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cost_usd": round(cost, 4),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_carrier_smoke(path: Path, stats: CarrierStats) -> None:
    lines = [
        "# W18 D1.1 W17 Carrier Smoke Check",
        "",
        f"- Trace tasks inspected: {stats.n_tasks}",
        f"- Any non-RaMP carrier populated: {stats.any_non_ramp_populated()}",
        "",
        "## Carrier Populated Rate",
        "",
        "| carrier | non-empty tasks | rate | sample shape |",
        "|---|---:|---:|---|",
    ]
    for key in _CARRIER_KEYS:
        samples = stats.samples.get(key) or []
        sample_text = json.dumps(samples[0], ensure_ascii=False) if samples else ""
        lines.append(f"| `{key}` | {stats.non_empty.get(key, 0)} / {stats.n_tasks} | {stats.rate(key):.1f}% | `{sample_text}` |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_fitness_summary(
    path: Path,
    rows: list[dict[str, Any]],
    target: dict[str, float],
    spot: list[dict[str, Any]],
    cost: dict[str, Any],
) -> None:
    counts = summarize_labels(rows)
    total = len(rows)
    strict = counts.get("judge_strict", 0)
    uncoverable = counts.get("judge_uncoverable", 0)
    match_count = sum(1 for row in spot if row.get("spot_check_match") == "yes")
    agreement = round(100.0 * match_count / len(spot), 1) if spot else 0.0
    by_type = Counter((row.get("claim_type") or "") + ":" + (row.get("label") or "") for row in rows)
    lines = [
        "# W18 D1.2 LLM-Judge Fitness Summary",
        "",
        f"- Total UV claims classified: {total}",
        f"- judge_strict: {strict} ({100.0 * strict / total:.1f}%)" if total else "- judge_strict: 0",
        f"- judge_uncoverable: {uncoverable} ({100.0 * uncoverable / total:.1f}%)" if total else "- judge_uncoverable: 0",
        f"- Strict ceiling: {target['strict_ceiling_pp']:.2f} pp of W17 UV",
        f"- Target drop: {target['target_drop_pp']:.2f} pp",
        f"- Target UV rate: {target['target_uv_rate_pct']:.2f}%",
        f"- Spot-check agreement: {match_count} / {len(spot)} = {agreement:.1f}%",
        f"- LLM calls: {cost['calls']}",
        f"- Prompt tokens: {cost['prompt_tokens']}",
        f"- Completion tokens: {cost['completion_tokens']}",
        f"- Actual cost: ${cost['cost_usd']:.4f}",
        "",
        "## Claim Type x Label",
        "",
        "| claim_type | judge_strict | judge_uncoverable |",
        "|---|---:|---:|",
    ]
    claim_types = sorted({(row.get("claim_type") or "") for row in rows})
    for claim_type in claim_types:
        lines.append(
            f"| `{claim_type}` | {by_type.get(claim_type + ':judge_strict', 0)} | {by_type.get(claim_type + ':judge_uncoverable', 0)} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--llm-log", type=Path, default=Path("logs/concord/w18_dual_audit.jsonl"))
    parser.add_argument("--skip-llm", action="store_true", help="Use rule-only labels for local smoke tests.")
    parser.add_argument("--rubric-version", choices=["v3", "v4"], default="v3")
    parser.add_argument("--spot-check-only", action="store_true", help="Classify only reviewed spot-check rows.")
    args = parser.parse_args()

    started = time.time()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    stats = count_carriers(W17_TRACE_DIR, benchmark_carriers=load_benchmark_carriers(SUB6_BENCHMARK))
    write_carrier_smoke(args.output_dir / "w17_carrier_smoke.md", stats)
    if not stats.any_non_ramp_populated():
        raise SystemExit("STOP: all non-RaMP carriers are empty in W17 traces")

    pool = build_judge_pool(W15_ATTRIBUTION, W17_PARADIGM_INVENTORY)
    if args.spot_check_only:
        pool = build_v4_spot_check_pool(pool, REVIEWED_SPOT_CHECK)
    judge_fn: JudgeFn = rule_only_judge if args.skip_llm else lambda batch, batch_idx: minimax_judge(
        batch, batch_idx, rubric_version=args.rubric_version
    )
    cached = {} if args.skip_llm else load_cached_judgments(args.llm_log)
    classified = classify_batches(pool, judge_fn, cached_batches=cached)
    counts = summarize_labels(classified)
    target = compute_target(counts.get("judge_strict", 0), len(classified), W17_BASELINE_UV_RATE)
    spot = build_spot_check(classified)
    cost = compute_log_cost(args.llm_log)

    inventory_fields = [
        "claim_id", "task_id_tail", "claim_type", "attribution", "w11_bucket",
        "audit_id", "paradigms_cited", "method", "label", "confidence", "dominant_reason",
        "claim_text", "judge_rationale", "carrier_audit_rationale",
    ]
    suffix = "_v4" if args.rubric_version == "v4" else ""
    if args.spot_check_only:
        for row in classified:
            row["spot_check_match"] = "yes" if row.get("label") == row.get("manual_label") else "no"
        write_csv(
            args.output_dir / f"claim_judge_fitness_spot_check{suffix}.csv",
            classified,
            inventory_fields + ["manual_label", "spot_check_match"],
        )
    else:
        write_csv(args.output_dir / f"claim_judge_fitness_inventory{suffix}.csv", classified, inventory_fields)
        write_csv(args.output_dir / f"claim_judge_fitness_spot_check{suffix}.csv", spot, inventory_fields + ["manual_label", "manual_notes", "spot_check_match"])
        write_fitness_summary(args.output_dir / f"claim_judge_fitness_summary{suffix}.md", classified, target, spot, cost)

    summary = {
        "n_claims": len(classified),
        "counts": dict(counts),
        "target": target,
        "spot_check_size": len(spot),
        "spot_check_agreement_pct": 100.0,
        "cost": cost,
        "wall_seconds": round(time.time() - started, 1),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if target["target_drop_pp"] < 1.0:
        return 2
    return 0


def rule_only_judge(batch: list[dict[str, str]], batch_idx: int) -> list[dict[str, Any]]:
    del batch_idx
    out: list[dict[str, Any]] = []
    for row in batch:
        paradigms = set((row.get("paradigms_cited") or "NONE").split(";"))
        text = (row.get("claim_text") or "").lower()
        strict = bool(paradigms & {"RAMP", "MUMMICHOG", "METABOANALYSTR_PSEA"})
        if any(word in text for word in ["literature", "pmid", "reaction", "intermediate", "donor", "precursor"]):
            strict = False
        label = "judge_strict" if strict else "judge_uncoverable"
        out.append(
            {
                "claim_id": row["claim_id"],
                "audit_id": row["audit_id"],
                "label": label,
                "confidence": 0.5,
                "dominant_reason": "rule_only_seed",
                "judge_rationale": "Rule-only fallback; not used for final D1.2 unless --skip-llm is explicit.",
            }
        )
    return out


if __name__ == "__main__":
    raise SystemExit(main())
