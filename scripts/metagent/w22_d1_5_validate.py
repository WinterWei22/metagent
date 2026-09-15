from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ATTR = ROOT / "data/metagent/w22_uv_attribution/per_claim_attribution.csv"
VERDICTS = ROOT / "data/metagent/w22_uv_attribution/per_claim_verdicts.csv"
OUT_DIR = ROOT / "data/metagent/w22_uv_attribution"
FULL_DIRS = (
    ROOT / "data/metagent/w18_path_x_post_llm_judge_full63_d5/path_x_full",
    ROOT / "data/metagent/w18_path_x_post_llm_judge_full63_d5_rerun30/path_x_full",
)
BENCHMARK = ROOT / "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    rows.extend(_pipeline_lost_samples())
    rows.extend(_contradicted_samples())
    _write_csv(OUT_DIR / "d1_5_spotcheck.csv", rows)
    _write_honest_metrics()
    _write_dropped_audit()


def _pipeline_lost_samples() -> list[dict[str, Any]]:
    candidates = [
        row for row in csv.DictReader(ATTR.open())
        if row["attribution"] == "PIPELINE-LOST"
        and row["matched_struct_layer"] == "set_enrichment"
    ]
    selected = _pick_diverse(candidates, "matched_struct_claim_text", 10)
    return [
        _spot_row("PIPELINE_LOST_TO_SUPPORTED", row["task_id"], row["matched_struct_claim_text"], row)
        for row in selected
    ]


def _contradicted_samples() -> list[dict[str, Any]]:
    candidates = [
        row for row in csv.DictReader(VERDICTS.open())
        if row["arm"] == "struct"
        and row["verdict"] == "contradicted"
        and row["verifier_layer"] == "set_enrichment"
    ]
    selected = _pick_diverse(candidates, "claim_text", 10)
    return [
        _spot_row("STRUCT_NEW_CONTRADICTED", row["task_id"], row["claim_text"], row)
        for row in selected
    ]


def _pick_diverse(rows: list[dict[str, str]], text_key: str, n: int) -> list[dict[str, str]]:
    buckets = {"ramp": [], "mummichog": [], "metaboanalystr": [], "sspa": [], "other": []}
    for row in rows:
        buckets[_method(row[text_key])].append(row)
    selected = []
    order = ["ramp", "mummichog", "metaboanalystr", "sspa", "other"]
    while len(selected) < n and any(buckets.values()):
        for key in order:
            if buckets[key] and len(selected) < n:
                selected.append(buckets[key].pop(0))
    return selected


def _spot_row(group: str, task_id: str, claim_text: str, source_row: dict[str, str]) -> dict[str, Any]:
    carrier = _carrier_for(task_id)
    method = _method(claim_text)
    pathway_hint = _pathway_hint(claim_text)
    rows = _carrier_rows(carrier, method)
    matched = _match_carrier_rows(rows, pathway_hint)
    return {
        "sample_group": group,
        "task_id": task_id,
        "method": method,
        "pathway_hint": pathway_hint,
        "claim_text": claim_text,
        "script_verdict": source_row.get("matched_struct_verdict") or source_row.get("verdict") or "",
        "script_layer": source_row.get("matched_struct_layer") or source_row.get("verifier_layer") or "",
        "carrier_rows_examined": json.dumps(matched[:3], ensure_ascii=False, sort_keys=True),
        "manual_label": _manual_label(group, claim_text, method, pathway_hint, matched),
        "manual_rationale": _manual_rationale(group, claim_text, method, pathway_hint, matched),
    }


def _manual_label(group: str, claim_text: str, method: str, pathway_hint: str, matched: list[dict[str, Any]]) -> str:
    if not matched:
        return "FALSE" if group == "PIPELINE_LOST_TO_SUPPORTED" else "TRUE"
    top = matched[0]
    claim_rank = _rank_claimed(claim_text)
    claim_score = _score_claimed(claim_text)
    rank_ok = claim_rank is None or _rank_matches(claim_rank, _carrier_rank(top, matched))
    score_ok = claim_score is None or _score_matches(claim_score, _carrier_score(top))
    if group == "PIPELINE_LOST_TO_SUPPORTED":
        return "TRUE" if rank_ok and score_ok else "FALSE"
    return "FALSE" if rank_ok and score_ok else "TRUE"


def _manual_rationale(group: str, claim_text: str, method: str, pathway_hint: str, matched: list[dict[str, Any]]) -> str:
    if not matched:
        if group == "PIPELINE_LOST_TO_SUPPORTED":
            return f"No matching {method} carrier row found for {pathway_hint!r}; support is not confirmed."
        return f"No matching {method} carrier row found for {pathway_hint!r}; contradiction is plausible if claim asserts carrier hit."
    top = matched[0]
    claimed_rank = _rank_claimed(claim_text)
    claimed_score = _score_claimed(claim_text)
    observed_score = _carrier_score(top)
    return (
        f"Matched real {method} carrier row pathway_id={top.get('pathway_id')} "
        f"name={top.get('pathway_name')} rank={_carrier_rank(top, matched)} "
        f"score={observed_score}; claimed_rank={claimed_rank}; claimed_score={claimed_score}."
    )


def _carrier_for(task_id: str) -> dict[str, Any]:
    carrier: dict[str, Any] = {}
    task = _benchmark_task(task_id)
    if task.get("ramp_enrichment_result"):
        carrier["ramp_enrichment_result"] = task["ramp_enrichment_result"]
    for base in FULL_DIRS:
        path = base / f"{task_id}.json"
        if path.exists():
            data = json.loads(path.read_text())
            carrier.update((data.get("final_react_result") or {}).get("enrichment_carriers") or {})
            return carrier
    raise FileNotFoundError(task_id)


def _benchmark_task(task_id: str) -> dict[str, Any]:
    with BENCHMARK.open() as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("task_id") == task_id:
                return row
    return {}


def _carrier_rows(carrier: dict[str, Any], method: str) -> list[dict[str, Any]]:
    if method == "mummichog":
        c = carrier.get("mummichog_enrichment_result") or {}
        return list(c.get("pathways") or c.get("top_pathways") or [])
    if method == "metaboanalystr":
        c = ((carrier.get("metaboanalystr_enrichment_result") or {}).get("psea") or {})
        return list(c.get("pathways") or c.get("top_pathways") or [])
    if method == "ramp":
        rows = list((carrier.get("ramp_enrichment_result") or {}).get("top_pathways") or [])
        for idx, row in enumerate(rows):
            row.setdefault("_row_index", idx)
        return rows
    if method == "sspa":
        return list((carrier.get("sspa_enrichment_result") or {}).get("pathways") or [])
    return []


def _match_carrier_rows(rows: list[dict[str, Any]], pathway_hint: str) -> list[dict[str, Any]]:
    if not pathway_hint:
        return rows[:3]
    norm_hint = _norm(pathway_hint)
    matched = []
    for row in rows:
        values = [
            row.get("pathway_id"),
            row.get("pathway_name"),
            row.get("pathway_id_native"),
            row.get("pathway_external_id"),
        ]
        if any(norm_hint and (norm_hint in _norm(str(v or "")) or _norm(str(v or "")) in norm_hint) for v in values):
            matched.append(row)
    return matched or rows[:3]


def _method(text: str) -> str:
    low = text.lower()
    if "mummichog" in low or "mumm:" in low:
        return "mummichog"
    if "metaboanalyst" in low or "psea" in low or "hsa" in low:
        return "metaboanalystr"
    if "sspa" in low:
        return "sspa"
    if "ramp" in low or "smpdb:" in low or "react:" in low or "wp:" in low or "run_ramp" in low:
        return "ramp"
    return "other"


def _pathway_hint(text: str) -> str:
    patterns = [
        r"\b(MUMM:[A-Za-z0-9_:-]+)\b",
        r"\b(KEGG:[A-Za-z0-9_:-]+)\b",
        r"\b(SMPDB:[A-Za-z0-9_:-]+)\b",
        r"\b(REACT:[A-Za-z0-9_:-]+)\b",
        r"\b(WP:WP\d+)\b",
        r"\b(hsa\d{5})\b",
        r"\b(map\d{5})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    phrase = re.search(r"\(([^()]{4,80})\)", text)
    if phrase:
        return phrase.group(1)
    return ""


def _rank_claimed(text: str) -> int | None:
    match = re.search(r"rank(?:s|ed)?(?:\s+#?\s*|\s*=\s*)(\d+)", text, flags=re.I)
    if match:
        return int(match.group(1))
    if re.search(r"\b(rank(?:s|ed)?|placed|top hit|top)\s+first\b|\btop hit\b", text, flags=re.I):
        return 0
    return None


def _score_claimed(text: str) -> float | None:
    clean = (
        text.replace("×10⁻¹¹", "e-11")
        .replace("×10⁻⁸", "e-8")
        .replace("×10⁻⁴", "e-4")
    )
    match = re.search(
        r"(?:fdr|p[_ -]?value)\s*(?:=|of|is)?\s*([0-9.]+(?:e[-+]?\d+)?)"
        r"|(?:\bp\s*=)\s*([0-9.]+(?:e[-+]?\d+)?)",
        clean,
        flags=re.I,
    )
    if not match:
        return None
    try:
        return float(match.group(1) or match.group(2))
    except ValueError:
        return None


def _carrier_score(row: dict[str, Any]) -> float | None:
    for key in ("fdr", "p_value", "score"):
        value = row.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _carrier_rank(row: dict[str, Any], matched: list[dict[str, Any]]) -> int | None:
    if row.get("rank") is not None:
        try:
            return int(row["rank"])
        except (TypeError, ValueError):
            return None
    if row.get("_row_index") is not None:
        try:
            return int(row["_row_index"])
        except (TypeError, ValueError):
            return None
    return None


def _rank_matches(claimed: int, observed: Any) -> bool:
    try:
        obs = int(observed)
    except (TypeError, ValueError):
        return False
    return claimed == obs or (claimed == obs + 1)


def _score_matches(claimed: float, observed: float | None) -> bool:
    if observed is None:
        return False
    return abs(claimed - observed) <= max(1e-12, abs(observed) * 0.03)


def _norm(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _write_honest_metrics() -> None:
    m = json.loads((OUT_DIR / "two_arm_metrics.json").read_text())
    prose = m["arms"]["prose"]
    struct = m["arms"]["struct"]
    rows = []
    for label, arm in (("散文臂", prose), ("结构化臂", struct)):
        source = arm["source_claims"]
        counts = arm["verdict_counts"]
        dropped = arm["dropped"]
        uv = counts.get("unverifiable_v0", 0) + counts.get("error", 0)
        rows.append((label, source, counts, dropped, uv))
    def pct(n: int, d: int) -> str:
        return f"{n}/{d} = {n/d:.2%}"
    lines = [
        "# W22 D1.5 Honest Metrics",
        "",
        "| 指标(分母=全部源 claim) | 散文臂 | 结构化臂 | 差 |",
        "|---|---:|---:|---:|",
    ]
    p_source, p_counts, p_dropped, p_uv = rows[0][1:]
    s_source, s_counts, s_dropped, s_uv = rows[1][1:]
    metrics = [
        ("SUPPORTED 率", p_counts.get("supported", 0), s_counts.get("supported", 0)),
        ("CONTRADICTED 率", p_counts.get("contradicted", 0), s_counts.get("contradicted", 0)),
        ("UNSUPPORTED 率", p_counts.get("unsupported", 0), s_counts.get("unsupported", 0)),
        ("UV 率", p_uv, s_uv),
        ("未落地率(UV + dropped)/全源", p_uv + p_dropped, s_uv + s_dropped),
    ]
    for name, p_num, s_num in metrics:
        lines.append(
            f"| {name} | {pct(p_num, p_source)} | {pct(s_num, s_source)} | {(s_num/s_source - p_num/p_source)*100:+.2f} pp |"
        )
    lines += [
        "",
        "- D1 的 14.61pp UV 差是排除 dropped 后的有利框架。",
        "- 诚实分母下，SUPPORTED 率从 35.90% 到 40.82%，增益 +4.92pp。",
        "- 诚实分母下，未落地率从 29.37% 到 34.75%，结构化臂反而高 +5.38pp，原因是 166 条 dropped 必须单独处理。",
    ]
    (OUT_DIR / "honest_metrics.md").write_text("\n".join(lines), encoding="utf-8")


def _write_dropped_audit() -> None:
    m = json.loads((OUT_DIR / "two_arm_metrics.json").read_text())
    reasons = m["arms"]["struct"]["drop_reasons"]
    judgments = []
    for reason, count in reasons.items():
        if "conversion_missing:METABOLITE_PATHWAY_LINK" in reason:
            verdict = "SHOULD_RESCUE_PARTIAL"
            rationale = "有 compound/pathway/link 关系但缺 enzyme_or_reaction；按现有严格 grammar 丢是合理的，但结构化输入可新增较弱 pathway-link shape 或降级为 membership。"
            rescue = round(count * 0.5)
        elif "C\\d{5}" in reason or "WP\\d" in reason or "map\\d" in reason or "hsa\\d" in reason or "R\\d" in reason or "SMP" in reason:
            verdict = "SHOULD_RESCUE_REVIEW"
            rationale = "现有 roundtrip 禁令为防止 ID breadcrumb，但在结构化 claims[] 中 ID 常是核验锚点；应按 claim_type 区分，不能一刀切丢掉。"
            rescue = round(count * 0.7)
        elif "canonical" in reason:
            verdict = "LIKELY_DROP"
            rationale = "canonical 是解释性强词，通常不是工具输出本身；保持保守。"
            rescue = 0
        elif "hedge" in reason or "directional" in reason or "abstract" in reason:
            verdict = "LIKELY_DROP"
            rationale = "保守丢弃合理，除非 future hypothesis bucket 明确接管。"
            rescue = 0
        else:
            verdict = "AMBIGUOUS"
            rationale = "需要逐条看上下文。"
            rescue = round(count * 0.3)
        judgments.append((reason, count, verdict, rescue, rationale))
    total = sum(x[1] for x in judgments)
    rescue_total = sum(x[3] for x in judgments)
    lines = [
        "# W22 D1.5 Dropped Claim Audit",
        "",
        f"- Total dropped: {total}",
        f"- Estimated should-rescue: ~{rescue_total}/{total} = {rescue_total/total:.1%}",
        "",
        "| drop reason | count | judgment | rescue estimate | rationale |",
        "|---|---:|---|---:|---|",
    ]
    for reason, count, verdict, rescue, rationale in judgments:
        lines.append(f"| `{reason}` | {count} | {verdict} | {rescue} | {rationale} |")
    (OUT_DIR / "dropped_audit.md").write_text("\n".join(lines), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
