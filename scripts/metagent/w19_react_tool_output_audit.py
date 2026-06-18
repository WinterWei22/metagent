from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data/metagent/w19_dual_audit"
W18_INVENTORY = ROOT / "data/metagent/w18_dual_audit/claim_judge_fitness_inventory_v4.csv"
W18_CLEAN_RESULTS = ROOT / "data/metagent/w18_path_x_post_llm_judge_full63_d5_clean/path_x_full63_results.jsonl"
W18_FULL_DIRS = [
    ROOT / "data/metagent/w18_path_x_post_llm_judge_full63_d5/path_x_full",
    ROOT / "data/metagent/w18_path_x_post_llm_judge_full63_d5_rerun30/path_x_full",
]
W18_CLAIM_DENOMINATOR = 1871
W18_UV_RATE_PCT = 36.45


METHOD_PATTERNS = {
    "mummichog": re.compile(r"\b(MUMM:|Mummichog|mummichog)\b"),
    "ramp": re.compile(r"\b(RaMP|multi-DB|RAMP)\b"),
    "metaboanalystr": re.compile(r"\b(MetaboAnalystR|MetaboAnalyst|PSEA|MSEA)\b"),
    "sspa": re.compile(r"\b(SSPA|ssPA)\b"),
    "fella": re.compile(r"\b(FELLA|diffusion|random walk|RWR)\b"),
}
DIRECT_VALUE_RE = re.compile(
    r"\b("
    r"rank|ranked|p[- ]?value|p\s*=|FDR|q[- ]?value|NES|score|fold enrichment|"
    r"top\s*[- ]?\s*\d+|top[- ]?ranked|top ranked|top hit|"
    r"listed|appears|appeared|reported|returned|hit list|hit|hits|"
    r"overlap|overlaps|matched|mapped|identifies|identified|targets|"
    r"member|members|input metabolite|input metabolites|metabolites_hit|"
    r"enriched|covered"
    r")\b",
    re.I,
)
INTERPRETIVE_RE = re.compile(
    r"\b(converge|converged|module|cluster|domain|driver|drives|responsible|explains|key|central|node|branch|axis|disrupted|linking|bridge)\b",
    re.I,
)


@dataclass(frozen=True)
class ToolDecision:
    label: str
    method: str
    reason: str
    carrier_present: bool


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    clean_task_ids = _read_clean_task_ids()
    full_rows = _read_full_rows(clean_task_ids)
    full_ids = sorted(full_rows)
    rows = [row for row in _read_inventory() if row["label"] == "judge_uncoverable"]

    out_rows = []
    for row in rows:
        task_id = _resolve_task_id(row["task_id_tail"], full_ids)
        carriers = _carriers_for_task(task_id, full_rows)
        decision = classify_tool_output(row, carriers)
        enriched = dict(row)
        enriched["resolved_task_id"] = task_id or ""
        enriched["react_tool_label"] = decision.label
        enriched["react_tool_method"] = decision.method
        enriched["react_tool_reason"] = decision.reason
        enriched["react_tool_carrier_present"] = str(decision.carrier_present)
        out_rows.append(enriched)

    summary = summarize(out_rows)
    write_inventory(out_rows)
    write_summary(summary)
    write_spot_check(out_rows)


def _read_clean_task_ids() -> list[str]:
    with W18_CLEAN_RESULTS.open() as handle:
        return [json.loads(line)["task_id"] for line in handle if line.strip()]


def _read_inventory() -> list[dict[str, str]]:
    with W18_INVENTORY.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _read_full_rows(clean_task_ids: list[str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for task_id in clean_task_ids:
        for base in W18_FULL_DIRS:
            path = base / f"{task_id}.json"
            if path.exists():
                rows[task_id] = json.loads(path.read_text())
    return rows


def _resolve_task_id(tail: str, full_ids: list[str]) -> str | None:
    matches = [task_id for task_id in full_ids if task_id.endswith(tail)]
    return matches[0] if len(matches) == 1 else None


def _carriers_for_task(task_id: str | None, full_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not task_id:
        return {}
    final = (full_rows.get(task_id) or {}).get("final_react_result") or {}
    return final.get("enrichment_carriers") or {}


def classify_tool_output(row: dict[str, str], carriers: dict[str, Any]) -> ToolDecision:
    text = row["claim_text"]
    methods = _detect_methods(row, text)
    direct_value = bool(DIRECT_VALUE_RE.search(text))
    interpretive = bool(INTERPRETIVE_RE.search(text))

    if not methods:
        return ToolDecision("tool_uncoverable", "NONE", "no explicit ReAct tool/source mention", False)
    if len(methods) > 1:
        return ToolDecision(
            "tool_uncoverable",
            ";".join(methods),
            "multi-tool convergence/comparison claim; needs cross-tool reasoning, not single-carrier check",
            all(_carrier_present(method, carriers) for method in methods),
        )

    method = methods[0]
    carrier_present = _carrier_present(method, carriers)
    if not carrier_present:
        return ToolDecision("tool_uncoverable", method, "referenced tool carrier is not populated", False)
    if interpretive and not direct_value:
        return ToolDecision("tool_uncoverable", method, "interpretive claim without direct rank/FDR/NES/list evidence", True)
    if direct_value:
        return ToolDecision("tool_strict", method, "direct tool-output rank/FDR/NES/list claim with matching carrier", True)
    return ToolDecision("tool_uncoverable", method, "tool mentioned but no direct checkable value/list relation", True)


def _detect_methods(row: dict[str, str], text: str) -> list[str]:
    methods: set[str] = set()
    cited = row.get("paradigms_cited", "")
    method = row.get("method", "")
    if "MUMMICHOG" in cited or "MUMMICHOG" in method:
        methods.add("mummichog")
    if "RAMP" in cited or "RAMP" in method:
        methods.add("ramp")
    if "METABOANALYSTR" in cited or method in {"PSEA", "MSEA"}:
        methods.add("metaboanalystr")
    if "SSPA" in cited:
        methods.add("sspa")
    if "FELLA" in cited or method == "DIFFUSION":
        methods.add("fella")
    for name, pattern in METHOD_PATTERNS.items():
        if pattern.search(text):
            methods.add(name)
    return sorted(methods)


def _carrier_present(method: str, carriers: dict[str, Any]) -> bool:
    if method == "mummichog":
        return bool(carriers.get("mummichog_enrichment_result"))
    if method == "ramp":
        return True
    if method == "metaboanalystr":
        return bool(carriers.get("metaboanalystr_enrichment_result"))
    if method == "sspa":
        return bool(carriers.get("sspa_enrichment_result"))
    if method == "fella":
        return bool(carriers.get("fella_enrichment_result"))
    return False


def summarize(rows: list[dict[str, str]]) -> dict[str, Any]:
    labels = Counter(row["react_tool_label"] for row in rows)
    methods = Counter(row["react_tool_method"] for row in rows)
    reasons = Counter(row["react_tool_reason"] for row in rows)
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    by_method_label: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_type[row["claim_type"]][row["react_tool_label"]] += 1
        by_method_label[row["react_tool_method"]][row["react_tool_label"]] += 1
    strict = labels["tool_strict"]
    ceiling_pp = strict / W18_CLAIM_DENOMINATOR * 100
    target_pp = ceiling_pp * 0.6
    return {
        "total": len(rows),
        "labels": dict(labels),
        "methods": dict(methods),
        "reasons": dict(reasons.most_common()),
        "by_type": {key: dict(value) for key, value in sorted(by_type.items())},
        "by_method_label": {key: dict(value) for key, value in sorted(by_method_label.items())},
        "strict_ceiling_pp_vs_w18_denominator": round(ceiling_pp, 2),
        "target_drop_pp": round(target_pp, 2),
        "target_uv_rate_pct": round(W18_UV_RATE_PCT - target_pp, 2),
    }


def write_inventory(rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else []
    with (OUT_DIR / "claim_react_tool_output_fitness_inventory.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(summary: dict[str, Any]) -> None:
    lines = [
        "# W19 ReAct Tool-Output Fitness Summary",
        "",
        f"- Total W18 `judge_uncoverable` claims classified: {summary['total']}",
        f"- `tool_strict`: {summary['labels'].get('tool_strict', 0)}",
        f"- `tool_uncoverable`: {summary['labels'].get('tool_uncoverable', 0)}",
        f"- Strict ceiling vs W18 D5 denominator: {summary['strict_ceiling_pp_vs_w18_denominator']:.2f} pp",
        f"- Target drop at ceiling x 0.6: {summary['target_drop_pp']:.2f} pp",
        f"- Target UV rate from W18 36.45%: {summary['target_uv_rate_pct']:.2f}%",
        "",
        "## Method x label",
        "",
        "| method | tool_strict | tool_uncoverable |",
        "|---|---:|---:|",
    ]
    for method, counts in summary["by_method_label"].items():
        lines.append(f"| `{method}` | {counts.get('tool_strict', 0)} | {counts.get('tool_uncoverable', 0)} |")
    lines += ["", "## Claim type x label", "", "| claim_type | tool_strict | tool_uncoverable |", "|---|---:|---:|"]
    for claim_type, counts in summary["by_type"].items():
        lines.append(f"| `{claim_type}` | {counts.get('tool_strict', 0)} | {counts.get('tool_uncoverable', 0)} |")
    lines += ["", "## Top reasons", ""]
    for reason, count in summary["reasons"].items():
        lines.append(f"- {count}: {reason}")
    (OUT_DIR / "claim_react_tool_output_fitness_summary.md").write_text("\n".join(lines))
    (OUT_DIR / "claim_react_tool_output_fitness_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_spot_check(rows: list[dict[str, str]]) -> None:
    selected = [row for row in rows if row["react_tool_label"] == "tool_strict"][:10]
    selected += [row for row in rows if row["react_tool_method"] != "NONE" and row["react_tool_label"] != "tool_strict"][:10]
    fieldnames = [
        "audit_id",
        "claim_id",
        "claim_type",
        "react_tool_label",
        "react_tool_method",
        "react_tool_reason",
        "react_tool_carrier_present",
        "claim_text",
        "human_label",
        "human_rationale",
    ]
    with (OUT_DIR / "claim_react_tool_output_fitness_spot_check.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in selected[:20]:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


if __name__ == "__main__":
    main()
