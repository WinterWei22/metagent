from __future__ import annotations

import csv
import json
import random
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
BENCHMARK = ROOT / "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl"

TOTAL_W17_UV_CLAIMS = 973
W18_UV_RATE_PCT = 36.45
W18_CLAIM_DENOMINATOR = 1871

KEGG_ID_RE = re.compile(r"\b(?:KEGG:)?(?:C\d{5}|cpd:C\d{5}|map\d{5}|hsa\d{5}|R\d{5}|rn:R\d{5})\b", re.I)
KEGG_COMPOUND_RE = re.compile(r"\b(?:KEGG:|cpd:)?C\d{5}\b", re.I)
KEGG_PATHWAY_RE = re.compile(r"\b(?:KEGG:)?(?:map|hsa)\d{5}\b", re.I)
KEGG_REACTION_RE = re.compile(r"\b(?:KEGG:|rn:)?R\d{5}\b", re.I)
FORMULA_RE = re.compile(r"\b(?:molecular\s+formula|formula|composition)\b", re.I)
MEMBERSHIP_RE = re.compile(
    r"\b(member|belongs|belonging|part of|in pathway|within|mapped to|maps to|included in|participant|substrate|product|intermediate)\b",
    re.I,
)
PATHWAY_RELATION_RE = re.compile(r"\b(pathway|metabolism|biosynthesis|degradation|cycle)\b", re.I)
FUZZY_INTERPRETIVE_RE = re.compile(
    r"\b(driver|drives|contribute|contributes|responsible|key|central|node|module|cluster|domain|disrupted|explains|linking|bridge|converge|converged|axis|branch)\b",
    re.I,
)
OTHER_KB_RE = re.compile(r"\b(Reactome|SMPDB|WikiPathways|PubMed|literature|ChEBI|HMDB|PubChem)\b", re.I)


@dataclass(frozen=True)
class KeggDecision:
    label: str
    reason: str
    evidence: str


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    clean_task_ids = _read_clean_task_ids()
    benchmark_rows = _read_jsonl_by_task(BENCHMARK)
    full_task_rows = _read_full_task_rows(clean_task_ids)

    smoke = build_context_smoke(clean_task_ids, benchmark_rows, full_task_rows)
    _write_context_smoke(smoke)

    inventory_rows = _read_inventory()
    kegg_rows = []
    for row in inventory_rows:
        if row["label"] != "judge_uncoverable":
            continue
        decision = classify_kegg_fitness(row["claim_text"])
        out = dict(row)
        out["kegg_label"] = decision.label
        out["kegg_reason"] = decision.reason
        out["kegg_evidence"] = decision.evidence
        kegg_rows.append(out)

    _write_inventory(kegg_rows)
    summary = summarize_kegg_rows(kegg_rows)
    _write_summary(summary)
    _write_spot_check(kegg_rows)
    _write_carrier_audit(kegg_rows, smoke)


def _read_clean_task_ids() -> list[str]:
    ids: list[str] = []
    with W18_CLEAN_RESULTS.open() as handle:
        for line in handle:
            if line.strip():
                ids.append(json.loads(line)["task_id"])
    return ids


def _read_jsonl_by_task(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row["task_id"]] = row
    return rows


def _read_full_task_rows(clean_task_ids: list[str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for task_id in clean_task_ids:
        for base in W18_FULL_DIRS:
            path = base / f"{task_id}.json"
            if path.exists():
                rows[task_id] = json.loads(path.read_text())
    return rows


def _read_inventory() -> list[dict[str, str]]:
    with W18_INVENTORY.open(newline="") as handle:
        return list(csv.DictReader(handle))


def build_context_smoke(
    clean_task_ids: list[str],
    benchmark_rows: dict[str, dict[str, Any]],
    full_task_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    carrier_counts = Counter()
    narrative_counts = Counter()
    claim_counts = Counter()
    kegg_ids = Counter()
    task_examples: dict[str, list[str]] = defaultdict(list)
    compound_ids = Counter()
    pathway_ids = Counter()
    reaction_ids = Counter()

    for task_id in clean_task_ids:
        bench = benchmark_rows.get(task_id, {})
        _count_ids(json.dumps(bench, ensure_ascii=False), kegg_ids, compound_ids, pathway_ids, reaction_ids)

        full = full_task_rows.get(task_id, {})
        final = full.get("final_react_result") or {}
        carriers = final.get("enrichment_carriers") or {}
        for key in (
            "mummichog_enrichment_result",
            "metaboanalystr_enrichment_result",
            "sspa_enrichment_result",
            "fella_enrichment_result",
        ):
            if carriers.get(key):
                carrier_counts[key] += 1

        narrative = str(final.get("final_narrative_text") or "")
        _count_ids(narrative, kegg_ids, compound_ids, pathway_ids, reaction_ids)
        for name, pattern in {
            "biology_background": re.compile(r"\b(biology|biological|metabolism|biosynthesis|degradation|cycle|intermediate)\b", re.I),
            "compound_formula": FORMULA_RE,
            "pathway_compound": re.compile(r"\b(member|substrate|product|intermediate|driver metabolite|mapped to)\b", re.I),
            "kegg_mention": re.compile(r"\bKEGG\b|\bC\d{5}\b|\bhsa\d{5}\b|\bmap\d{5}\b", re.I),
        }.items():
            if pattern.search(narrative):
                narrative_counts[name] += 1
                if len(task_examples[name]) < 5:
                    task_examples[name].append(task_id)

        for claim in final.get("final_claims") or []:
            text = json.dumps(claim, ensure_ascii=False) if isinstance(claim, dict) else str(claim)
            _count_ids(text, kegg_ids, compound_ids, pathway_ids, reaction_ids)
            if KEGG_ID_RE.search(text):
                claim_counts["claims_with_kegg_id"] += 1
            if FORMULA_RE.search(text):
                claim_counts["claims_with_formula_language"] += 1
            if MEMBERSHIP_RE.search(text) and PATHWAY_RELATION_RE.search(text):
                claim_counts["claims_with_pathway_compound_language"] += 1

    return {
        "clean_task_count": len(clean_task_ids),
        "full_task_json_count": len(full_task_rows),
        "carrier_counts": dict(carrier_counts),
        "narrative_counts": dict(narrative_counts),
        "claim_counts": dict(claim_counts),
        "top_kegg_ids": kegg_ids.most_common(20),
        "top_compound_ids": compound_ids.most_common(20),
        "top_pathway_ids": pathway_ids.most_common(20),
        "top_reaction_ids": reaction_ids.most_common(20),
        "task_examples": dict(task_examples),
    }


def _count_ids(
    text: str,
    kegg_ids: Counter[str],
    compound_ids: Counter[str],
    pathway_ids: Counter[str],
    reaction_ids: Counter[str],
) -> None:
    for raw in KEGG_ID_RE.findall(text):
        value = raw.upper().replace("CPD:", "").replace("RN:", "")
        kegg_ids[value] += 1
        if value.startswith("C"):
            compound_ids[value] += 1
        elif value.startswith(("HSA", "MAP")):
            pathway_ids[value] += 1
        elif value.startswith("R"):
            reaction_ids[value] += 1


def classify_kegg_fitness(claim_text: str) -> KeggDecision:
    text = claim_text or ""
    evidence = "; ".join(sorted(set(KEGG_ID_RE.findall(text)))) or "(no KEGG id)"
    has_kegg_compound = bool(KEGG_COMPOUND_RE.search(text))
    has_kegg_pathway = bool(KEGG_PATHWAY_RE.search(text))
    has_kegg_reaction = bool(KEGG_REACTION_RE.search(text))
    has_formula = bool(FORMULA_RE.search(text))
    has_membership = bool(MEMBERSHIP_RE.search(text))
    has_pathway_relation = bool(PATHWAY_RELATION_RE.search(text))
    has_other_kb = bool(OTHER_KB_RE.search(text))
    has_interpretive = bool(FUZZY_INTERPRETIVE_RE.search(text))

    if has_other_kb and not (has_kegg_compound or has_kegg_pathway or has_kegg_reaction):
        return KeggDecision("kegg_uncoverable", "other KB namespace without KEGG REST surface", evidence)
    if has_kegg_reaction:
        return KeggDecision("kegg_strict", "KEGG reaction identifier can be checked by KEGG REST", evidence)
    if has_kegg_compound and has_formula:
        return KeggDecision("kegg_strict", "KEGG compound formula/content claim can be checked by KEGG REST", evidence)
    if has_kegg_compound and has_kegg_pathway and has_membership:
        return KeggDecision("kegg_strict", "KEGG compound-pathway relationship with explicit IDs", evidence)
    if has_kegg_compound and has_membership and has_pathway_relation and not has_interpretive:
        return KeggDecision("kegg_strict", "compound membership/intermediate claim with KEGG compound ID", evidence)
    if has_kegg_pathway and has_membership and not has_interpretive:
        return KeggDecision("kegg_strict", "pathway membership claim with KEGG pathway ID", evidence)
    if has_kegg_compound and has_pathway_relation and not has_interpretive:
        return KeggDecision("kegg_strict", "compound-pathway relation likely checkable via KEGG REST", evidence)
    if has_kegg_compound or has_kegg_pathway:
        return KeggDecision("kegg_uncoverable", "KEGG ID present but claim is interpretive or lacks checkable relation/formula", evidence)
    return KeggDecision("kegg_uncoverable", "no explicit KEGG REST-checkable identifier or relation", evidence)


def summarize_kegg_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    total = len(rows)
    label_counts = Counter(row["kegg_label"] for row in rows)
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    by_reason = Counter(row["kegg_reason"] for row in rows)
    for row in rows:
        by_type[row["claim_type"]][row["kegg_label"]] += 1
    strict = label_counts["kegg_strict"]
    ceiling_pp_vs_w17_uv = strict / TOTAL_W17_UV_CLAIMS * 100 if TOTAL_W17_UV_CLAIMS else 0.0
    ceiling_pp_vs_w18_denom = strict / W18_CLAIM_DENOMINATOR * 100 if W18_CLAIM_DENOMINATOR else 0.0
    target_drop_pp = ceiling_pp_vs_w18_denom * 0.6
    target_uv_rate = W18_UV_RATE_PCT - target_drop_pp
    return {
        "total": total,
        "label_counts": dict(label_counts),
        "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
        "by_reason": dict(by_reason.most_common()),
        "strict_ceiling_pp_vs_w17_uv": round(ceiling_pp_vs_w17_uv, 2),
        "strict_ceiling_pp_vs_w18_denominator": round(ceiling_pp_vs_w18_denom, 2),
        "target_drop_pp": round(target_drop_pp, 2),
        "target_uv_rate_pct": round(target_uv_rate, 2),
    }


def _write_context_smoke(smoke: dict[str, Any]) -> None:
    lines = [
        "# W19 D1.1 W18 KEGG Context Smoke",
        "",
        f"- Clean W18 tasks inspected: {smoke['clean_task_count']}",
        f"- Full task JSONs found: {smoke['full_task_json_count']}",
        "",
        "## Populated W17 carriers in final React result",
        "",
    ]
    for key, count in sorted(smoke["carrier_counts"].items()):
        lines.append(f"- `{key}`: {count} / {smoke['clean_task_count']}")
    lines += ["", "## Narrative / claim signals", ""]
    for key, count in sorted(smoke["narrative_counts"].items()):
        examples = ", ".join(smoke["task_examples"].get(key, [])[:5])
        lines.append(f"- `{key}`: {count} tasks; examples: {examples}")
    for key, count in sorted(smoke["claim_counts"].items()):
        lines.append(f"- `{key}`: {count} final claims")
    lines += ["", "## Top KEGG-like IDs", ""]
    for title, values in [
        ("All KEGG-like IDs", smoke["top_kegg_ids"]),
        ("Compound IDs", smoke["top_compound_ids"]),
        ("Pathway IDs", smoke["top_pathway_ids"]),
        ("Reaction IDs", smoke["top_reaction_ids"]),
    ]:
        lines += [f"### {title}", ""]
        if values:
            for value, count in values:
                lines.append(f"- `{value}`: {count}")
        else:
            lines.append("- none")
        lines.append("")
    (OUT_DIR / "w18_kegg_context_smoke.md").write_text("\n".join(lines))


def _write_inventory(rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else []
    with (OUT_DIR / "claim_kegg_fitness_inventory.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(summary: dict[str, Any]) -> None:
    lines = [
        "# W19 D1.2 KEGG Fitness Summary",
        "",
        f"- Total W18 `judge_uncoverable` claims classified: {summary['total']}",
        f"- `kegg_strict`: {summary['label_counts'].get('kegg_strict', 0)}",
        f"- `kegg_uncoverable`: {summary['label_counts'].get('kegg_uncoverable', 0)}",
        f"- Strict ceiling vs W17 UV count: {summary['strict_ceiling_pp_vs_w17_uv']:.2f} pp",
        f"- Strict ceiling vs W18 D5 denominator: {summary['strict_ceiling_pp_vs_w18_denominator']:.2f} pp",
        f"- Target drop at ceiling x 0.6: {summary['target_drop_pp']:.2f} pp",
        f"- Target UV rate from W18 36.45%: {summary['target_uv_rate_pct']:.2f}%",
        "",
        "## Claim Type x KEGG Label",
        "",
        "| claim_type | kegg_strict | kegg_uncoverable |",
        "|---|---:|---:|",
    ]
    for claim_type, counts in summary["by_type"].items():
        lines.append(
            f"| `{claim_type}` | {counts.get('kegg_strict', 0)} | {counts.get('kegg_uncoverable', 0)} |"
        )
    lines += ["", "## Top reasons", ""]
    for reason, count in summary["by_reason"].items():
        lines.append(f"- {count}: {reason}")
    (OUT_DIR / "claim_kegg_fitness_summary.md").write_text("\n".join(lines))
    (OUT_DIR / "claim_kegg_fitness_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))


def _write_spot_check(rows: list[dict[str, str]]) -> None:
    rng = random.Random(20260611)
    sample = rng.sample(rows, min(20, len(rows)))
    fieldnames = [
        "audit_id",
        "claim_id",
        "claim_type",
        "label",
        "kegg_label",
        "kegg_reason",
        "kegg_evidence",
        "claim_text",
        "human_label",
        "human_rationale",
    ]
    with (OUT_DIR / "claim_kegg_fitness_spot_check.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in sample:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _write_carrier_audit(rows: list[dict[str, str]], smoke: dict[str, Any]) -> None:
    source_counts = Counter()
    for row in rows:
        text = row["claim_text"]
        if "Reactome" in text:
            source_counts["Reactome"] += 1
        if "SMPDB" in text:
            source_counts["SMPDB"] += 1
        if "WikiPathways" in text:
            source_counts["WikiPathways"] += 1
        if "PubMed" in text or "literature" in text.lower():
            source_counts["PubMed/literature"] += 1
        if "KEGG" in text or KEGG_ID_RE.search(text):
            source_counts["KEGG"] += 1
        if "ChEBI" in text:
            source_counts["ChEBI"] += 1
        if "HMDB" in text:
            source_counts["HMDB"] += 1

    lines = [
        "# W19 D1.4 Carrier Audit Draft",
        "",
        "This D1 draft compares claim-side KB references against verifier-side carriers planned for W19.",
        "",
        "## Claim-side KB/source mentions in 624 W18 judge_uncoverable claims",
        "",
    ]
    for source, count in source_counts.most_common():
        lines.append(f"- `{source}`: {count}")
    lines += [
        "",
        "## Verifier-side accessible carriers before W19",
        "",
        "- W17 tool-output carriers: `mummichog_enrichment_result`, `metaboanalystr_enrichment_result`, `sspa_enrichment_result`, `fella_enrichment_result`.",
        "- W18 LLM-judge source excerpt over those carriers.",
        "- No external KB HTTP carrier is currently present.",
        "",
        "## W19 planned carrier",
        "",
        "- `KEGG REST`: external HTTP KB lookup for explicit KEGG compound, pathway, reaction, and formula surfaces.",
        "",
        "## MISSING_CARRIER policy",
        "",
        "- Reactome / PubMed / SMPDB / WikiPathways / ChEBI-only / HMDB-only claims remain UV fallback in W19.",
        "- KEGG REST miss or API error must remain UV and must not become CONTRADICTED.",
        "- CONTRADICTED requires explicit KEGG source compatibility and a direct mismatch.",
        "",
        "## W18 carrier smoke reference",
        "",
        f"- Clean tasks inspected: {smoke['clean_task_count']}",
        f"- Full task JSONs found: {smoke['full_task_json_count']}",
    ]
    (OUT_DIR / "carrier_audit.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
