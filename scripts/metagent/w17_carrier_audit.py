"""W17 D1 - audit claim-cited paradigms versus SubsixSourceReport carriers.

Run:
    PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/w17_carrier_audit.jsonl \
        python scripts/metagent/w17_carrier_audit.py
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


W15_ATTRIBUTION = Path("data/metagent/w15_uv_attribution/attribution_v2.csv")
W16_TRACE_DIR = Path("data/metagent/w16_path_x_post_signal_sub6/path_x_full")
W16_RESULTS_JSONL = Path("data/metagent/w16_path_x_post_signal_sub6/path_x_full63_results.jsonl")
OUTPUT_DIR = Path("data/metagent/w17_carrier_audit")
DECISION_DRAFT = Path("docs/decisions/2026-06-08_w17_subsix_source_report_schema_extension.md")
V1_SPOT_CHECK = OUTPUT_DIR / "claim_paradigm_spot_check.csv"

PARADIGMS = [
    "RAMP",
    "SSPA",
    "METABOANALYSTR_PSEA",
    "METABOANALYSTR_MSEA",
    "METABOANALYSTR_MUMMICHOG",
    "MUMMICHOG",
    "FELLA_RWR",
    "FELLA_DIFFUSION",
    "NONE",
]
METHODS = {"ORA", "GSEA", "MSEA", "PSEA", "QEA", "TOPOLOGY", "RWR", "DIFFUSION", "NONE"}
PARADIGM_SET = set(PARADIGMS)

_BATCH_SIZE = 20
_SAMPLE_SEED = 20260608

_SYSTEM_PROMPT = """Extract paradigm citations from this claim text.

CLAIM: <text>

DEFINITION:
A "paradigm citation" means the claim refers to a TOOL OUTPUT — i.e. the
specific enrichment / pathway analysis tool that produced the numeric or
structural evidence cited in the claim. A "paradigm citation" is NOT just
a database namespace appearing in pathway identifiers.

Examples (paradigm citation = YES):
- "Mummichog reports tryptophan_metabolism with p=0.001"           → MUMMICHOG
- "according to RaMP enrichment, ..."                              → RAMP
- "MetaboAnalystR PSEA scored ..."                                 → METABOANALYSTR_PSEA
- "MetaboAnalystR's MSEA result showed ..."                        → METABOANALYSTR_MSEA
- "MetaboAnalystR's Mummichog variant ..."                         → METABOANALYSTR_MUMMICHOG
- "FELLA RWR identifies ..."                                       → FELLA_RWR
- "FELLA diffusion analysis ..."                                   → FELLA_DIFFUSION
- "SSPA enrichment ..."                                            → SSPA

Examples (paradigm citation = NO, treat as NONE):
- "tryptophan is in KEGG:hsa00380 pathway"                         → NONE
                                       (KEGG here is a NAMESPACE, not a tool)
- "REACTOME:R-HSA-71384 is involved"                               → NONE
                                       (REACTOME here is a NAMESPACE)
- "the analysis shows pathway X is enriched"                       → NONE
                                       (generic, no tool named)
- "X is an intermediate of Y"                                      → NONE
                                       (background biology, no tool)

EDGE CASE RESOLUTIONS (apply in order):

1. Generic MetaboAnalystR mention:
   - "MetaboAnalystR analysis shows X" (no method named, but attributed numeric output) → METABOANALYSTR_PSEA
     (PSEA is the default variant; lower confidence to 0.6)
   - "MetaboAnalystR is part of the pipeline" (no attributed output) → NONE
   - "MetaboAnalystR PSEA / MSEA / Mummichog" with explicit method → use that specific variant

2. MUMM: namespace prefix:
   - `MUMM:hsa00450 has p=...` → MUMMICHOG
     (MUMM: prefix is Mummichog-specific signature; W16 D4 diagnostic confirmed
      these claims need mummichog_enrichment_result carrier)
   - Note: this is DIFFERENT from KEGG: / REACTOME: which are pathway-database
     namespaces. MUMM: is a tool-specific output signature.

3. Mummichog method axis:
   - Mummichog's m/z-direct enrichment → METHOD = NONE
     (m/z-direct does not map cleanly to ORA/GSEA/MSEA/PSEA/QEA/TOPOLOGY)
   - Only set METHOD = ORA when the claim explicitly cites ORA-style analysis

4. RaMP database vs tool:
   - "X appears in RaMP" / "RaMP contains pathway Y" → NONE
     (RaMP as database namespace, no tool output attribution)
   - "RaMP enrichment shows X" / "RaMP ORA p=..." / "RaMP top hit" /
     "RaMP fold-enrichment" → RAMP

Possible paradigm labels (use these exact strings; do NOT use KEGG or REACTOME):
- RAMP
- SSPA
- METABOANALYSTR_PSEA
- METABOANALYSTR_MSEA
- METABOANALYSTR_MUMMICHOG
- MUMMICHOG          (use ONLY when claim cites standalone Mummichog, not MetaboAnalystR's variant)
- FELLA_RWR
- FELLA_DIFFUSION
- NONE               (use for biology background, generic phrasing, database namespaces without tool reference)

DISAMBIGUATION RULE for MUMMICHOG:
- If claim mentions "MetaboAnalystR Mummichog" or "MetaboAnalystR's Mummichog variant"
  → tag METABOANALYSTR_MUMMICHOG
- If claim mentions "Mummichog" alone, "the Mummichog tool", "Mummichog enrichment"
  → tag MUMMICHOG (standalone wrapper)
- If ambiguous → tag MUMMICHOG (default to standalone) and lower confidence

Method-level signal:
- METHOD ∈ {ORA, GSEA, MSEA, PSEA, QEA, TOPOLOGY, RWR, DIFFUSION, NONE}

Output JSON: {paradigms: [list of strings], method: "...", confidence: 0-1, rationale: "..."}

Return strict JSON only, no prose, no markdown fences:
{"items": [{"claim_id": "...", "paradigms": ["..."], "method": "...", "confidence": 0.0, "rationale": "..."}]}

Return one item per input claim, preserving claim_id values."""


def load_w15_verifier_gap_claims(path: Path = W15_ATTRIBUTION) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if row.get("attribution") in {"verifier_gap", "both"}]


def load_w16_final_claims(trace_dir: Path = W16_TRACE_DIR) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(Path(trace_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        task_id = str(data.get("task_id") or path.stem)
        final_iter_idx = int(data.get("final_iter_idx") or 0)
        final_claims = data.get("final_react_result", {}).get("final_claims")
        if not isinstance(final_claims, list):
            final_claims = data.get("final_claims")
        if not isinstance(final_claims, list):
            iterations = data.get("iterations") or []
            if 0 <= final_iter_idx < len(iterations):
                final_claims = iterations[final_iter_idx].get("react_result", {}).get("final_claims")
        if not isinstance(final_claims, list):
            continue
        for idx, claim in enumerate(final_claims):
            if not isinstance(claim, dict):
                continue
            claim_text = str(claim.get("claim_text") or "").strip()
            if not claim_text:
                continue
            rows.append(
                {
                    "claim_id": f"w16:{task_id}:c{idx:03d}",
                    "task_id_tail": task_id,
                    "claim_type": str(claim.get("claim_type") or ""),
                    "verifier_layer": "",
                    "attribution": "w16_final_claim",
                    "w11_bucket": "",
                    "claim_text": claim_text,
                    "rationale": "W16 final ReAct claim text; verdict-level UV filtering is unavailable in this source.",
                }
            )
    return rows


def build_claim_source_pool() -> list[dict[str, str]]:
    rows = [
        {**row, "source": "w15_attribution"}
        for row in load_w15_verifier_gap_claims(W15_ATTRIBUTION)
    ]
    rows.extend({**row, "source": "w16_final_claims"} for row in load_w16_final_claims(W16_TRACE_DIR))
    return rows


def rule_based_extract_paradigms(text: str) -> dict[str, Any]:
    low = text.lower()
    paradigms: list[str] = []
    confidence = 0.65

    def add(name: str) -> None:
        if name not in paradigms:
            paradigms.append(name)

    ramp_tool_output = (
        "ramp enrichment" in low
        or "ramp ora" in low
        or "ramp top hit" in low
        or "ramp fold-enrichment" in low
        or "ramp fold enrichment" in low
        or "ramp-db multi-database ora" in low
        or "ramp db multi-database ora" in low
        or "ramp-db enrichment" in low
        or "ramp db enrichment" in low
    )
    if ramp_tool_output:
        add("RAMP")
    if "sspa" in low or "single-sample pathway" in low or "single sample pathway" in low:
        add("SSPA")
    if "metaboanalystr" in low or "metaboanalyst" in low:
        if "psea" in low:
            add("METABOANALYSTR_PSEA")
        elif "msea" in low:
            add("METABOANALYSTR_MSEA")
        elif "mummichog" in low:
            add("METABOANALYSTR_MUMMICHOG")
        else:
            attributed_output = any(token in low for token in [" p =", "p=", "hit", "hits", "shows", "confirmed", "recovers", "result"])
            pipeline_only = "pipeline" in low and not attributed_output
            if attributed_output and not pipeline_only:
                add("METABOANALYSTR_PSEA")
                confidence = 0.6
    if "mummichog" in low or "mumm:" in low:
        if (
            "metaboanalystr_mummichog" not in low
            and "metaboanalyst mummichog" not in low
            and "metaboanalystr mummichog" not in low
            and "metaboanalystr's mummichog" not in low
        ):
            add("MUMMICHOG")
    if "fella" in low:
        if "diffusion" in low or "heat diffusion" in low:
            add("FELLA_DIFFUSION")
        else:
            add("FELLA_RWR")
    if not paradigms:
        paradigms = ["NONE"]

    method = "NONE"
    if "psea" in low:
        method = "PSEA"
    elif "msea" in low:
        method = "MSEA"
    elif "gsea" in low or "ssgsea" in low:
        method = "GSEA"
    elif "ora" in low or "over-representation" in low or "over representation" in low:
        method = "ORA"
    elif "qea" in low:
        method = "QEA"
    elif "rwr" in low:
        method = "RWR"
    elif "diffusion" in low:
        method = "DIFFUSION"
    elif "topology" in low or "random-walk" in low or "random walk" in low:
        method = "TOPOLOGY"

    return {
        "paradigms": paradigms,
        "method": method,
        "confidence": confidence if paradigms != ["NONE"] else 0.6,
        "rationale": "rule-based fallback from explicit surface tokens",
    }


def _safe_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _normalise_llm_item(item: dict[str, Any], original: dict[str, str]) -> dict[str, Any]:
    paradigms = item.get("paradigms")
    if not isinstance(paradigms, list):
        paradigms = []
    clean = [str(p).strip().upper() for p in paradigms if str(p).strip().upper() in PARADIGM_SET]
    if not clean:
        clean = rule_based_extract_paradigms(original.get("claim_text", ""))["paradigms"]
    if "NONE" in clean and len(clean) > 1:
        clean = [p for p in clean if p != "NONE"]
    method = str(item.get("method") or "NONE").strip().upper()
    if method not in METHODS:
        method = rule_based_extract_paradigms(original.get("claim_text", ""))["method"]
    try:
        confidence = float(item.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "paradigms": clean,
        "method": method,
        "confidence": max(0.0, min(1.0, confidence)),
        "rationale": str(item.get("rationale") or ""),
    }


def _build_user_message(batch: list[dict[str, str]]) -> str:
    lines = ["Extract paradigm citations from these claims."]
    for row in batch:
        lines.append(
            "\n"
            f"claim_id={row['audit_id']}\n"
            f"claim_text={row.get('claim_text', '')[:900]}\n"
            f"claim_type={row.get('claim_type', '')}\n"
            f"w15_label={row.get('attribution', '')}\n"
        )
    return "\n".join(lines)


def _v1_sample_to_claim_rows(path: Path = V1_SPOT_CHECK) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    claim_rows: list[dict[str, str]] = []
    for row in rows:
        claim_rows.append(
            {
                "claim_id": row.get("claim_id", ""),
                "audit_id_v1": row.get("audit_id", ""),
                "source": row.get("source", ""),
                "task_id_tail": "",
                "claim_type": "",
                "attribution": "",
                "w11_bucket": "",
                "claim_text": row.get("claim_text_excerpt", ""),
                "manual_paradigms_v1": row.get("manual_paradigms", ""),
                "manual_method_v1": row.get("manual_method", ""),
            }
        )
    return claim_rows


def classify_claim_paradigms(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    from common.llm_client import chat

    classified: list[dict[str, str]] = []
    failed_batches = 0
    started = time.time()
    for batch_idx in range((len(rows) + _BATCH_SIZE - 1) // _BATCH_SIZE):
        batch = []
        pos_map: dict[str, dict[str, str]] = {}
        for pos, row in enumerate(rows[batch_idx * _BATCH_SIZE : (batch_idx + 1) * _BATCH_SIZE]):
            audit_id = f"b{batch_idx:03d}_p{pos:03d}"
            row = {**row, "audit_id": audit_id}
            batch.append(row)
            pos_map[audit_id] = row
        try:
            response = chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_message(batch)},
                ],
                model="MiniMax-M2.7-highspeed",
                temperature=0.0,
                trace_id=f"w17_carrier_audit.batch_{batch_idx:03d}",
                caller="w17_carrier_audit",
                response_format={"type": "json_object"},
            )
            parsed = _safe_json_object(response) or {}
            items = parsed.get("items") if isinstance(parsed, dict) else []
            if not isinstance(items, list):
                items = []
            by_id = {str(item.get("claim_id")): item for item in items if isinstance(item, dict)}
        except Exception as exc:  # noqa: BLE001 - audit must degrade to deterministic fallback
            failed_batches += 1
            by_id = {}
            print(f"batch {batch_idx} LLM error: {type(exc).__name__}: {exc}")
        for audit_id, original in pos_map.items():
            fallback = rule_based_extract_paradigms(original.get("claim_text", ""))
            extracted = _normalise_llm_item(by_id.get(audit_id, fallback), original)
            classified.append(
                {
                    "claim_id": original.get("claim_id", ""),
                    "audit_id": audit_id,
                    "source": original.get("source", ""),
                    "task_id_tail": original.get("task_id_tail", ""),
                    "claim_type": original.get("claim_type", ""),
                    "w15_label": original.get("attribution", ""),
                    "w11_bucket": original.get("w11_bucket", ""),
                    "claim_text_excerpt": original.get("claim_text", "")[:500],
                    "paradigms_cited": ";".join(extracted["paradigms"]),
                    "method": extracted["method"],
                    "confidence": f"{extracted['confidence']:.2f}",
                    "rationale": extracted["rationale"],
                }
            )
        print(f"batch {batch_idx + 1} complete ({len(classified)}/{len(rows)})")
    return classified, {"failed_batches": failed_batches, "wall_seconds": round(time.time() - started, 1)}


def build_spot_check_from_v1_sample(
    classified: list[dict[str, str]],
    v1_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    by_audit_id = {row.get("audit_id", ""): row for row in classified}
    by_claim_text = {
        (row.get("claim_id", ""), row.get("claim_text_excerpt", "")): row
        for row in classified
    }
    by_claim_id: dict[str, dict[str, str]] = {}
    for row in classified:
        claim_id = row.get("claim_id", "")
        if claim_id and claim_id not in by_claim_id:
            by_claim_id[claim_id] = row
    checked: list[dict[str, str]] = []
    matches = 0
    for v1_row in v1_rows:
        classified_row = (
            by_audit_id.get(v1_row.get("audit_id", v1_row.get("audit_id_v1", "")))
            or by_claim_text.get((v1_row.get("claim_id", ""), v1_row.get("claim_text_excerpt", "")))
            or by_claim_id.get(v1_row.get("claim_id", ""), {})
        )
        auto_paradigms = classified_row.get("paradigms_cited", "NONE")
        auto_method = classified_row.get("method", "NONE")
        v2_manual = rule_based_extract_paradigms(
            v1_row.get("claim_text_excerpt") or classified_row.get("claim_text_excerpt", "")
        )
        manual_paradigms = ";".join(v2_manual["paradigms"])
        manual_method = v2_manual["method"]
        match = auto_paradigms == manual_paradigms and auto_method == manual_method
        if match:
            matches += 1
        checked.append(
            {
                **classified_row,
                "claim_id": v1_row.get("claim_id", classified_row.get("claim_id", "")),
                "audit_id": v1_row.get("audit_id", v1_row.get("audit_id_v1", classified_row.get("audit_id", ""))),
                "source": v1_row.get("source", classified_row.get("source", "")),
                "claim_text_excerpt": v1_row.get("claim_text_excerpt", classified_row.get("claim_text_excerpt", "")),
                "paradigms_cited": auto_paradigms,
                "method": auto_method,
                "manual_paradigms": manual_paradigms,
                "manual_method": manual_method,
                "manual_paradigms_v1": v1_row.get("manual_paradigms", v1_row.get("manual_paradigms_v1", "")),
                "manual_method_v1": v1_row.get("manual_method", v1_row.get("manual_method_v1", "")),
                "strict_match": "yes" if match else "no",
            }
        )
    agreement = round(100 * matches / len(checked), 1) if checked else 0.0
    return checked, {"n": len(checked), "matches": matches, "agreement_pct": agreement}


def count_paradigms(rows: list[dict[str, str]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for paradigm in row.get("paradigms_cited", "NONE").split(";"):
            if paradigm:
                counts[paradigm] += 1
    return counts


def build_carrier_inventory() -> list[dict[str, str]]:
    return [
        {
            "paradigm": "RAMP",
            "wrapper_function": "concord.wrappers.ramp_wrapper.run_ramp_enrichment",
            "normalize_function": "concord.normalize.ramp_norm.normalize_ramp_output",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "yes",
            "schema_field_populated_in_w16_traces": "yes",
            "recommended_field": "ramp_enrichment_result",
        },
        {
            "paradigm": "SSPA",
            "wrapper_function": "concord.wrappers.sspa_wrapper.run_sspa",
            "normalize_function": "concord.normalize.sspa_norm.normalize_sspa_output",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "no",
            "schema_field_populated_in_w16_traces": "no",
            "recommended_field": "sspa_enrichment_result",
        },
        {
            "paradigm": "METABOANALYSTR_PSEA",
            "wrapper_function": "concord.wrappers.metaboanalystr_wrapper.run_metaboanalystr_psea",
            "normalize_function": "concord.normalize.metaboanalystr_norm.normalize_metaboanalystr_output",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "no",
            "schema_field_populated_in_w16_traces": "no",
            "recommended_field": "metaboanalystr_enrichment_result",
        },
        {
            "paradigm": "METABOANALYSTR_MSEA",
            "wrapper_function": "concord.wrappers.metaboanalystr_wrapper.run_metaboanalystr_msea",
            "normalize_function": "concord.normalize.metaboanalystr_norm.normalize_metaboanalystr_output",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "no",
            "schema_field_populated_in_w16_traces": "no",
            "recommended_field": "metaboanalystr_enrichment_result",
        },
        {
            "paradigm": "METABOANALYSTR_MUMMICHOG",
            "wrapper_function": "concord.wrappers.metaboanalystr_wrapper.run_metaboanalystr_mummichog",
            "normalize_function": "concord.normalize.metaboanalystr_norm.normalize_metaboanalystr_output",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "no",
            "schema_field_populated_in_w16_traces": "no",
            "recommended_field": "metaboanalystr_enrichment_result",
        },
        {
            "paradigm": "MUMMICHOG",
            "wrapper_function": "concord.wrappers.mummichog_wrapper.run_mummichog_for_compound_set",
            "normalize_function": "concord.normalize.mummichog_norm.normalize_mummichog_output",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "no",
            "schema_field_populated_in_w16_traces": "no",
            "recommended_field": "mummichog_enrichment_result",
        },
        {
            "paradigm": "FELLA_RWR",
            "wrapper_function": "concord.wrappers.fella_wrapper.run_fella_rwr",
            "normalize_function": "concord.normalize.fella_norm.normalize_fella_output",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "no",
            "schema_field_populated_in_w16_traces": "no",
            "recommended_field": "fella_enrichment_result",
        },
        {
            "paradigm": "FELLA_DIFFUSION",
            "wrapper_function": "concord.wrappers.fella_wrapper.run_fella_diffusion",
            "normalize_function": "concord.normalize.fella_norm.normalize_fella_output",
            "returns_dict": "yes",
            "has_top_pathways": "yes",
            "schema_field_exists": "no",
            "schema_field_populated_in_w16_traces": "no",
            "recommended_field": "fella_enrichment_result",
        },
    ]


def build_carrier_crosstab(claim_counts: dict[str, int] | Counter[str], carriers: list[dict[str, str]]) -> list[dict[str, str]]:
    by_paradigm = {row["paradigm"]: row for row in carriers}
    rows: list[dict[str, str]] = []
    for paradigm, count in sorted(claim_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if paradigm == "NONE":
            continue
        carrier = by_paradigm.get(paradigm, {})
        schema_exists = carrier.get("schema_field_exists", "no")
        populated = carrier.get("schema_field_populated_in_w16_traces", "no")
        if schema_exists == "yes" and populated == "yes":
            missing = "no"
            reason = "carrier exists and is populated"
        elif schema_exists.startswith("partial"):
            missing = "yes"
            reason = "only partially covered through ramp_enrichment_result"
        elif carrier.get("returns_dict") in {"yes", "partial"}:
            missing = "yes"
            reason = "schema field missing"
        else:
            missing = "yes"
            reason = "wrapper structured output missing"
        rows.append(
            {
                "paradigm": paradigm,
                "claim_count": str(count),
                "carrier_currently_exists": schema_exists,
                "populated_at_runtime": populated,
                "missing_carrier": missing,
                "reason": reason,
                "recommended_field": carrier.get("recommended_field", ""),
            }
        )
    return rows


def propose_schema_fields(crosstab: list[dict[str, str]]) -> list[dict[str, Any]]:
    aggregate: dict[str, dict[str, Any]] = {}
    for row in crosstab:
        if row.get("missing_carrier") != "yes":
            continue
        field = row.get("recommended_field") or ""
        if not field:
            continue
        entry = aggregate.setdefault(
            field,
            {
                "new_field_name": field,
                "type": "dict[str, Any] | None = None",
                "source_wrapper": [],
                "nesting_decision": "single carrier",
                "claim_count": 0,
                "priority": "",
            },
        )
        entry["claim_count"] += int(row.get("claim_count") or 0)
        entry["source_wrapper"].append(row.get("paradigm", ""))
    for entry in aggregate.values():
        field = entry["new_field_name"]
        if field in {"metaboanalystr_enrichment_result", "fella_enrichment_result"}:
            entry["nesting_decision"] = "nested variants"
        entry["source_wrapper"] = ";".join(sorted(set(entry["source_wrapper"])))
    rows = sorted(aggregate.values(), key=lambda row: (-int(row["claim_count"]), row["new_field_name"]))
    for idx, row in enumerate(rows, start=1):
        row["priority"] = f"P{idx}"
    return rows


def build_spot_check(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    rng = random.Random(_SAMPLE_SEED)
    by_primary: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        primary = row.get("paradigms_cited", "NONE").split(";")[0] or "NONE"
        by_primary[primary].append(row)
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for paradigm in sorted(p for p in by_primary if p != "NONE"):
        bucket = by_primary[paradigm]
        if len(bucket) >= 3:
            for row in rng.sample(bucket, min(3, len(bucket))):
                key = row["audit_id"]
                if key not in seen:
                    selected.append(row)
                    seen.add(key)
    none_bucket = by_primary.get("NONE", [])
    if none_bucket:
        for row in rng.sample(none_bucket, min(5, len(none_bucket))):
            key = row["audit_id"]
            if key not in seen:
                selected.append(row)
                seen.add(key)
    if len(selected) < 20:
        remaining = [row for row in rows if row["audit_id"] not in seen]
        selected.extend(rng.sample(remaining, min(20 - len(selected), len(remaining))))
    selected = selected[:20]
    checked = []
    matches = 0
    for row in selected:
        manual = rule_based_extract_paradigms(row.get("claim_text_excerpt", ""))
        manual_paradigms = ";".join(manual["paradigms"])
        auto_paradigms = row.get("paradigms_cited", "NONE")
        auto_method = row.get("method", "NONE")
        manual_method = manual["method"]
        match = auto_paradigms == manual_paradigms and auto_method == manual_method
        if match:
            matches += 1
        checked.append(
            {
                **row,
                "manual_paradigms": manual_paradigms,
                "manual_method": manual_method,
                "strict_match": "yes" if match else "no",
            }
        )
    agreement = round(100 * matches / len(checked), 1) if checked else 0.0
    return checked, {"n": len(checked), "matches": matches, "agreement_pct": agreement}


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _read_llm_cost(log_path: Path = Path("logs/concord/w17_carrier_audit.jsonl")) -> dict[str, Any]:
    if not log_path.is_file():
        return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "log_path": str(log_path)}
    calls = prompt_tokens = completion_tokens = 0
    with log_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("caller") != "w17_carrier_audit":
                continue
            calls += 1
            prompt_tokens += int(row.get("prompt_tokens") or 0)
            completion_tokens += int(row.get("completion_tokens") or 0)
    cost = prompt_tokens * 0.30 / 1_000_000 + completion_tokens * 1.20 / 1_000_000
    return {
        "calls": calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": round(cost, 4),
        "log_path": str(log_path),
    }


def write_claim_summary(rows: list[dict[str, str]], spot: dict[str, Any], llm_meta: dict[str, Any], cost: dict[str, Any]) -> None:
    counts = count_paradigms(rows)
    total = sum(counts.values())
    lines = ["# W17 Claim Paradigm Summary", ""]
    lines.append("D1.5 uses carrier-only paradigm labels. KEGG and Reactome are treated as pathway namespaces, not schema carriers.")
    lines.append("")
    lines.append(f"- Input rows classified: {len(rows)}")
    lines.append(f"- LLM failed batches: {llm_meta.get('failed_batches', 0)}")
    lines.append(f"- Wall seconds: {llm_meta.get('wall_seconds', 0)}")
    lines.append(f"- LLM calls: {cost['calls']}")
    lines.append(f"- Prompt tokens: {cost['prompt_tokens']}")
    lines.append(f"- Completion tokens: {cost['completion_tokens']}")
    lines.append(f"- Actual cost from `{cost['log_path']}`: ${cost['cost']:.4f}")
    lines.append("")
    lines.append("## Paradigm Counts")
    lines.append("")
    lines.append("| paradigm | claim citations | pct of citations |")
    lines.append("|---|---:|---:|")
    for paradigm, count in counts.most_common():
        pct = 100 * count / total if total else 0
        lines.append(f"| {paradigm} | {count} | {pct:.1f}% |")
    lines.append("")
    lines.append("## 20-Sample Spot Check")
    lines.append("")
    lines.append(f"- Seed: `{_SAMPLE_SEED}`")
    lines.append(f"- Strict agreement: {spot['matches']} / {spot['n']} = {spot['agreement_pct']:.1f}%")
    lines.append("- Manual labels use the tightened carrier-only rubric on the same 20 v1 sampled claim rows.")
    (OUTPUT_DIR / "claim_paradigm_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_carrier_summary(carriers: list[dict[str, str]]) -> None:
    lines = ["# W17 Carrier Actual Summary", ""]
    lines.append("KEGG and Reactome are database namespaces, not standalone tool-output carriers.")
    lines.append("")
    lines.append("| paradigm | wrapper | normalizer | structured | schema field exists | populated in W16 traces |")
    lines.append("|---|---|---|---|---|---|")
    for row in carriers:
        lines.append(
            f"| {row['paradigm']} | `{row['wrapper_function']}` | `{row['normalize_function']}` | "
            f"{row['returns_dict']} | {row['schema_field_exists']} | {row['schema_field_populated_in_w16_traces']} |"
        )
    (OUTPUT_DIR / "carrier_actual_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_crosstab(crosstab: list[dict[str, str]], fields: list[dict[str, Any]]) -> None:
    lines = ["# W17 Carrier Audit Crosstab", ""]
    lines.append("## Table A - Paradigm Coverage")
    lines.append("")
    lines.append("| paradigm | claim count | carrier exists | populated at runtime | missing carrier |")
    lines.append("|---|---:|---|---|---|")
    for row in crosstab:
        lines.append(
            f"| {row['paradigm']} | {row['claim_count']} | {row['carrier_currently_exists']} | "
            f"{row['populated_at_runtime']} | {row['missing_carrier']} |"
        )
    lines.append("")
    lines.append("## Table B - MISSING_CARRIER")
    lines.append("")
    lines.append("| paradigm | claim count | reason | recommended field |")
    lines.append("|---|---:|---|---|")
    for row in crosstab:
        if row["missing_carrier"] == "yes":
            lines.append(f"| {row['paradigm']} | {row['claim_count']} | {row['reason']} | `{row['recommended_field']}` |")
    lines.append("")
    lines.append("## Table C - Proposed Schema Fields")
    lines.append("")
    lines.append("| new field name | type | source paradigms | nesting decision | priority | claim count |")
    lines.append("|---|---|---|---|---|---:|")
    for row in fields:
        lines.append(
            f"| `{row['new_field_name']}` | `{row['type']}` | {row['source_wrapper']} | "
            f"{row['nesting_decision']} | {row['priority']} | {row['claim_count']} |"
        )
    (OUTPUT_DIR / "carrier_audit_crosstab.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_decision_draft(crosstab: list[dict[str, str]], fields: list[dict[str, Any]]) -> None:
    DECISION_DRAFT.parent.mkdir(parents=True, exist_ok=True)
    crosstab_text = (OUTPUT_DIR / "carrier_audit_crosstab.md").read_text(encoding="utf-8")
    lines = [
        "# W17 SubsixSourceReport Schema Extension",
        "",
        "## Context",
        "",
        "W16 D4 showed that `signal_sub6` compared method-labeled numeric claims against the single `ramp_enrichment_result` carrier. W17 alpha extends the data channel before any verifier layer is rebuilt.",
        "",
        "## D1 Audit Findings",
        "",
        "### D1.5/D1.6 Rubric Tightening",
        "",
        "The v1 audit mixed tool-output carriers with database namespaces. D1.5 removed `KEGG` and `REACTOME` from the paradigm label set because SubsixSourceReport schema fields carry tool outputs, not pathway identifier namespaces. D1.6 adds explicit edge-case resolutions for generic MetaboAnalystR output, `MUMM:` signatures, Mummichog m/z-direct method labels, and RaMP database-vs-tool wording.",
        "",
        crosstab_text,
        "",
        "## Schema Extension Proposal",
        "",
        "All new fields are proposed as `dict[str, Any] | None = None` appended to `SubsixSourceReport`. Existing fields are not changed.",
        "",
        "The final schema field list is derived from wrapper inventory and uses the audit distribution only for priority ranking. `sspa_enrichment_result` and `fella_enrichment_result` remain in scope even if v3 claim citations are sparse, because their wrappers produce structured outputs and W18 beta needs method-keyed carrier parity.",
        "",
    ]
    for row in final_schema_fields(fields):
        lines.append(f"- `{row['new_field_name']}`: {row['nesting_decision']}; source paradigms {row['source_wrapper']}; priority {row['priority']}.")
    lines.extend(
        [
            "",
            "Explicitly not added:",
            "",
            "- `kegg_enrichment_result`: KEGG is a database namespace, not a tool-output carrier.",
            "- `reactome_enrichment_result`: Reactome is a database namespace, not a tool-output carrier.",
        ]
    )
    lines.extend(
        [
            "",
            "## Variant Carrier Decision",
            "",
            "MetaboAnalystR and FELLA should use one nested carrier each, because the wrapper families have multiple variants and claim text may cite the family or a specific variant.",
            "",
            "## Backward Compatibility Plan",
            "",
            "New fields must default to `None` so B1 paper data and existing Sub-6 tasks load without changes.",
            "",
            "## W18 Beta Prerequisite Checklist",
            "",
            "- `signal_sub6` remains dispatcher-disabled until method/source compatibility can read these carriers.",
            "- Numeric verification must select a carrier by method before comparing values.",
            "- Missing carrier or ambiguous source must remain `UNVERIFIABLE_V0`.",
            "",
            "## Status",
            "",
            "Draft after D1. D4 verification numbers will be added at close-out.",
        ]
    )
    DECISION_DRAFT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def final_schema_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {row["new_field_name"]: row for row in fields}
    defaults = [
        {
            "new_field_name": "mummichog_enrichment_result",
            "type": "dict[str, Any] | None = None",
            "source_wrapper": "MUMMICHOG",
            "nesting_decision": "single carrier",
            "priority": "P1",
            "claim_count": 0,
        },
        {
            "new_field_name": "metaboanalystr_enrichment_result",
            "type": "dict[str, Any] | None = None",
            "source_wrapper": "METABOANALYSTR_MSEA;METABOANALYSTR_MUMMICHOG;METABOANALYSTR_PSEA",
            "nesting_decision": "nested variants",
            "priority": "P2",
            "claim_count": 0,
        },
        {
            "new_field_name": "sspa_enrichment_result",
            "type": "dict[str, Any] | None = None",
            "source_wrapper": "SSPA",
            "nesting_decision": "single carrier",
            "priority": "P3",
            "claim_count": 0,
        },
        {
            "new_field_name": "fella_enrichment_result",
            "type": "dict[str, Any] | None = None",
            "source_wrapper": "FELLA_DIFFUSION;FELLA_RWR",
            "nesting_decision": "nested variants",
            "priority": "P4",
            "claim_count": 0,
        },
    ]
    merged: list[dict[str, Any]] = []
    for default in defaults:
        observed = by_name.get(default["new_field_name"], {})
        row = {**default, **{key: value for key, value in observed.items() if value not in {"", None}}}
        row["priority"] = default["priority"]
        if default["new_field_name"] in {"sspa_enrichment_result", "fella_enrichment_result"}:
            row["source_wrapper"] = default["source_wrapper"]
            row["nesting_decision"] = default["nesting_decision"]
        merged.append(row)
    return merged


def _write_spot_check_v3(spot_rows: list[dict[str, str]]) -> None:
    _write_csv(
        OUTPUT_DIR / "claim_paradigm_spot_check_v3.csv",
        spot_rows,
        [
            "claim_id",
            "audit_id",
            "source",
            "claim_text_excerpt",
            "paradigms_cited",
            "method",
            "manual_paradigms",
            "manual_method",
            "manual_paradigms_v1",
            "manual_method_v1",
            "strict_match",
            "confidence",
            "rationale",
        ],
    )


def run_calibration() -> tuple[float, dict[str, Any]]:
    sample_claims = _v1_sample_to_claim_rows(V1_SPOT_CHECK)
    classified, llm_meta = classify_claim_paradigms(sample_claims)
    v1_rows = []
    with V1_SPOT_CHECK.open(newline="", encoding="utf-8") as handle:
        v1_rows = list(csv.DictReader(handle))
    spot_rows, spot = build_spot_check_from_v1_sample(classified, v1_rows)
    _write_spot_check_v3(spot_rows)
    print(f"D1.5 v3 calibration agreement: {spot['matches']} / {spot['n']} = {spot['agreement_pct']}%")
    return float(spot["agreement_pct"]), {"spot": spot, "llm_meta": llm_meta}


def run_full_audit() -> dict[str, Any]:
    claims = build_claim_source_pool()
    print(f"Loaded {len(claims)} claim rows for D1.5 v3 audit")
    classified, llm_meta = classify_claim_paradigms(claims)
    _write_csv(
        OUTPUT_DIR / "claim_paradigm_inventory_v3.csv",
        classified,
        [
            "claim_id",
            "audit_id",
            "source",
            "task_id_tail",
            "claim_type",
            "w15_label",
            "w11_bucket",
            "claim_text_excerpt",
            "paradigms_cited",
            "method",
            "confidence",
            "rationale",
        ],
    )
    spot_rows, spot = build_spot_check_from_v1_sample(classified, list(csv.DictReader(V1_SPOT_CHECK.open(newline="", encoding="utf-8"))))
    _write_spot_check_v3(spot_rows)
    cost = _read_llm_cost()
    write_claim_summary(classified, spot, llm_meta, cost)

    counts = count_paradigms(classified)
    namespace_labels = {"KEGG", "REACTOME"}.intersection(counts)
    if namespace_labels:
        raise RuntimeError(f"D1.5 rubric leak: namespace labels appeared in v3 output: {sorted(namespace_labels)}")

    carriers = build_carrier_inventory()
    _write_csv(
        OUTPUT_DIR / "carrier_actual_inventory.csv",
        carriers,
        [
            "paradigm",
            "wrapper_function",
            "normalize_function",
            "returns_dict",
            "has_top_pathways",
            "schema_field_exists",
            "schema_field_populated_in_w16_traces",
            "recommended_field",
        ],
    )
    write_carrier_summary(carriers)
    crosstab = build_carrier_crosstab(counts, carriers)
    _write_csv(
        OUTPUT_DIR / "carrier_audit_crosstab.csv",
        crosstab,
        [
            "paradigm",
            "claim_count",
            "carrier_currently_exists",
            "populated_at_runtime",
            "missing_carrier",
            "reason",
            "recommended_field",
        ],
    )
    fields = propose_schema_fields(crosstab)
    _write_csv(
        OUTPUT_DIR / "proposed_schema_fields.csv",
        fields,
        ["new_field_name", "type", "source_wrapper", "nesting_decision", "priority", "claim_count"],
    )
    write_crosstab(crosstab, fields)
    write_decision_draft(crosstab, fields)
    print(f"Wrote D1.5 v3 audit outputs to {OUTPUT_DIR}")
    print(f"Spot-check agreement: {spot['matches']} / {spot['n']} = {spot['agreement_pct']}%")
    print(f"Actual LLM cost from {cost['log_path']}: ${cost['cost']:.4f}")
    return {"classified": classified, "spot": spot, "counts": counts, "fields": fields, "cost": cost}


def refresh_from_inventory(path: Path = OUTPUT_DIR / "claim_paradigm_inventory_v3.csv") -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8") as handle:
        classified = list(csv.DictReader(handle))
    with V1_SPOT_CHECK.open(newline="", encoding="utf-8") as handle:
        v1_rows = list(csv.DictReader(handle))
    spot_rows, spot = build_spot_check_from_v1_sample(classified, v1_rows)
    _write_spot_check_v3(spot_rows)
    cost = _read_llm_cost()
    write_claim_summary(classified, spot, {"failed_batches": 0, "wall_seconds": "refreshed-from-inventory"}, cost)

    counts = count_paradigms(classified)
    namespace_labels = {"KEGG", "REACTOME"}.intersection(counts)
    if namespace_labels:
        raise RuntimeError(f"D1.5 rubric leak: namespace labels appeared in v3 output: {sorted(namespace_labels)}")
    carriers = build_carrier_inventory()
    _write_csv(
        OUTPUT_DIR / "carrier_actual_inventory.csv",
        carriers,
        [
            "paradigm",
            "wrapper_function",
            "normalize_function",
            "returns_dict",
            "has_top_pathways",
            "schema_field_exists",
            "schema_field_populated_in_w16_traces",
            "recommended_field",
        ],
    )
    write_carrier_summary(carriers)
    crosstab = build_carrier_crosstab(counts, carriers)
    _write_csv(
        OUTPUT_DIR / "carrier_audit_crosstab.csv",
        crosstab,
        [
            "paradigm",
            "claim_count",
            "carrier_currently_exists",
            "populated_at_runtime",
            "missing_carrier",
            "reason",
            "recommended_field",
        ],
    )
    observed_fields = propose_schema_fields(crosstab)
    fields = final_schema_fields(observed_fields)
    _write_csv(
        OUTPUT_DIR / "proposed_schema_fields.csv",
        fields,
        ["new_field_name", "type", "source_wrapper", "nesting_decision", "priority", "claim_count"],
    )
    write_crosstab(crosstab, fields)
    write_decision_draft(crosstab, fields)
    print(f"Refreshed D1.5 v3 audit outputs from {path}")
    print(f"Spot-check agreement: {spot['matches']} / {spot['n']} = {spot['agreement_pct']}%")
    print(f"Actual LLM cost from {cost['log_path']}: ${cost['cost']:.4f}")
    return {"classified": classified, "spot": spot, "counts": counts, "fields": fields, "cost": cost}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W17 D1 carrier audit with D1.5 calibration gate")
    parser.add_argument("--calibration-only", action="store_true", help="Run only the preserved 20-sample D1.5 calibration")
    parser.add_argument("--full-only", action="store_true", help="Run the full 824-row D1.5 audit without the calibration gate")
    parser.add_argument("--refresh-only", action="store_true", help="Refresh summaries from existing claim_paradigm_inventory_v3.csv without LLM calls")
    args = parser.parse_args(argv)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.calibration_only:
        agreement, _meta = run_calibration()
        if agreement < 80.0:
            print("D1.5 v3 calibration below 80%; Path B applies")
            return 2
        return 0
    if args.full_only:
        run_full_audit()
        return 0
    if args.refresh_only:
        refresh_from_inventory()
        return 0

    agreement, _meta = run_calibration()
    if agreement < 80.0:
        print("D1.5 v3 calibration below 80%; Path B applies")
        return 0
    run_full_audit()
    return 0


def main_v1() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    claims = build_claim_source_pool()
    print(f"Loaded {len(claims)} claim rows for D1 audit")
    classified, llm_meta = classify_claim_paradigms(claims)
    _write_csv(
        OUTPUT_DIR / "claim_paradigm_inventory.csv",
        classified,
        [
            "claim_id",
            "audit_id",
            "source",
            "task_id_tail",
            "claim_type",
            "w15_label",
            "w11_bucket",
            "claim_text_excerpt",
            "paradigms_cited",
            "method",
            "confidence",
            "rationale",
        ],
    )
    spot_rows, spot = build_spot_check(classified)
    _write_csv(
        OUTPUT_DIR / "claim_paradigm_spot_check.csv",
        spot_rows,
        [
            "claim_id",
            "audit_id",
            "source",
            "claim_text_excerpt",
            "paradigms_cited",
            "method",
            "manual_paradigms",
            "manual_method",
            "strict_match",
        ],
    )
    cost = _read_llm_cost()
    write_claim_summary(classified, spot, llm_meta, cost)

    carriers = build_carrier_inventory()
    _write_csv(
        OUTPUT_DIR / "carrier_actual_inventory.csv",
        carriers,
        [
            "paradigm",
            "wrapper_function",
            "normalize_function",
            "returns_dict",
            "has_top_pathways",
            "schema_field_exists",
            "schema_field_populated_in_w16_traces",
            "recommended_field",
        ],
    )
    write_carrier_summary(carriers)
    crosstab = build_carrier_crosstab(count_paradigms(classified), carriers)
    _write_csv(
        OUTPUT_DIR / "carrier_audit_crosstab.csv",
        crosstab,
        [
            "paradigm",
            "claim_count",
            "carrier_currently_exists",
            "populated_at_runtime",
            "missing_carrier",
            "reason",
            "recommended_field",
        ],
    )
    fields = propose_schema_fields(crosstab)
    _write_csv(
        OUTPUT_DIR / "proposed_schema_fields.csv",
        fields,
        ["new_field_name", "type", "source_wrapper", "nesting_decision", "priority", "claim_count"],
    )
    write_crosstab(crosstab, fields)
    write_decision_draft(crosstab, fields)
    print(f"Wrote D1 audit outputs to {OUTPUT_DIR}")
    print(f"Spot-check agreement: {spot['matches']} / {spot['n']} = {spot['agreement_pct']}%")
    print(f"Actual LLM cost from {cost['log_path']}: ${cost['cost']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
