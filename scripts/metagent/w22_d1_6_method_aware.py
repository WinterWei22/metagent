from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verifier.claim_classifier import classify_claims
from verifier.claim_extractor import extract_claims_from_json, extract_claims_rulebased
from verifier.schemas import ClaimVerdict, VerifiedClaim

import scripts.metagent.w22_uv_attribution as d1
import scripts.metagent.w22_d1_5_validate as d15


OUT_DIR = ROOT / "data/metagent/w22_uv_attribution"
METRICS_OUT = OUT_DIR / "d1_6_method_aware_metrics.json"
SPOTCHECK_OUT = OUT_DIR / "d1_6_spotcheck.csv"
SUMMARY_OUT = OUT_DIR / "d1_6_summary.md"
D1_PER_CLAIM = OUT_DIR / "per_claim_verdicts.csv"


UV_VERDICTS = {ClaimVerdict.UNVERIFIABLE_V0.value, ClaimVerdict.ERROR.value}
NON_UV_VERDICTS = {
    ClaimVerdict.SUPPORTED.value,
    ClaimVerdict.CONTRADICTED.value,
    ClaimVerdict.UNSUPPORTED.value,
    ClaimVerdict.NEEDS_HUMAN_REVIEW.value,
}


@dataclass(frozen=True)
class Arm:
    task_id: str
    arm: str
    source_claims: int
    dropped: int
    claims: list[dict[str, Any]]
    drop_reasons: dict[str, int]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    task_ids = d1._read_clean_task_ids()
    tasks = d1._read_tasks(task_ids)
    dumps = d1._read_full_dumps(task_ids)

    arms: list[Arm] = []
    for task_id in task_ids:
        carrier = _carrier_for(task_id, tasks[task_id], dumps[task_id])
        final = dumps[task_id]["final_react_result"]
        arms.append(_prose_arm(task_id, final.get("final_narrative_text") or "", carrier))
        arms.append(_struct_arm(task_id, final.get("final_claims") or [], carrier))

    per_claim = [claim for arm in arms for claim in arm.claims]
    attribution = _attribute(arms)
    spotcheck = _spotcheck(attribution, per_claim)
    metrics = _metrics(arms, attribution, spotcheck)
    _write_json(METRICS_OUT, metrics)
    _write_csv(OUT_DIR / "d1_6_per_claim_verdicts.csv", per_claim)
    _write_csv(OUT_DIR / "d1_6_per_claim_attribution.csv", attribution)
    _write_csv(SPOTCHECK_OUT, spotcheck)
    _write_summary(metrics)


def _prose_arm(task_id: str, narrative: str, carrier: dict[str, Any]) -> Arm:
    extracted = extract_claims_rulebased(narrative, trace_id=f"w22.d16.{task_id}.prose.extract")
    classified, _calls = _classify_no_llm(extracted, trace_id=f"w22.d16.{task_id}.prose.classify")
    rows = []
    for idx, claim in enumerate(classified):
        rows.append(_verify_claim(task_id, "prose", idx, claim.claim_text, claim.claim_type.value, carrier))
    return Arm(task_id, "prose", len(extracted), 0, rows, {})


def _struct_arm(task_id: str, raw_claims: list[dict[str, Any]], carrier: dict[str, Any]) -> Arm:
    converted = []
    drop_reasons: Counter[str] = Counter()
    raw_by_text: dict[str, dict[str, Any]] = {}
    for raw in raw_claims:
        obj = d1._convert_final_claim(raw)
        if obj is None:
            drop_reasons[f"conversion_missing:{raw.get('claim_type') or 'unknown'}"] += 1
            continue
        converted.append(obj)
        raw_by_text[obj["claim_text"]] = raw
    extracted, dropped = extract_claims_from_json(
        {"narrative_text": "", "claims": converted},
        trace_id=f"w22.d16.{task_id}.struct.extract",
    )
    for dropped_claim in dropped:
        drop_reasons[dropped_claim.drop_reason or "grammar_drop:unknown"] += 1
    classified, _calls = _classify_no_llm(extracted, trace_id=f"w22.d16.{task_id}.struct.classify")
    rows = []
    for idx, claim in enumerate(classified):
        raw = raw_by_text.get(claim.claim_text, {})
        rows.append(
            _verify_claim(
                task_id,
                "struct",
                idx,
                claim.claim_text,
                claim.claim_type.value,
                carrier,
                raw=raw,
            )
        )
    return Arm(task_id, "struct", len(raw_claims), sum(drop_reasons.values()), rows, dict(drop_reasons))


def _classify_no_llm(extracted: list[Any], *, trace_id: str) -> tuple[list[Any], int]:
    import verifier.claim_classifier as classifier

    original = classifier._llm_classify
    try:
        classifier._llm_classify = lambda texts, trace_id: [None] * len(texts)
        classified, _calls = classify_claims(extracted, trace_id=trace_id)
    finally:
        classifier._llm_classify = original
    return classified, 0


def _verify_claim(
    task_id: str,
    arm: str,
    idx: int,
    text: str,
    claim_type: str,
    carrier: dict[str, Any],
    *,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = raw or {}
    if _is_enrichment_like(text, raw, claim_type):
        method = _method_from(raw, text)
        verdict, evidence, source_field = _verify_enrichment_method_aware(text, raw, carrier, method)
        layer = "method_aware_enrichment"
    else:
        # Keep non-enrichment claims comparable to the D1 baseline. D1.6 is
        # measuring the enrichment method-routing bug, not replacing every
        # deterministic verifier layer with UV.
        method = _method_from(raw, text)
        baseline = _baseline_claim(task_id, arm, idx)
        verdict = baseline.get("verdict", ClaimVerdict.UNVERIFIABLE_V0.value)
        evidence = baseline.get("evidence") or "Inherited D1 offline verifier baseline."
        source_field = baseline.get("subject") or ""
        layer = baseline.get("verifier_layer") or "d1_baseline_fallback"
    return {
        "task_id": task_id,
        "arm": arm,
        "claim_index": idx,
        "claim_type": claim_type,
        "method": method,
        "verdict": verdict,
        "verifier_layer": layer,
        "source_field": source_field,
        "evidence": evidence,
        "claim_text": text,
    }


_BASELINE_CACHE: dict[tuple[str, str, int], dict[str, str]] | None = None


def _baseline_claim(task_id: str, arm: str, idx: int) -> dict[str, str]:
    global _BASELINE_CACHE
    if _BASELINE_CACHE is None:
        cache: dict[tuple[str, str, int], dict[str, str]] = {}
        with D1_PER_CLAIM.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                cache[(row["task_id"], row["arm"], int(row["claim_index"]))] = row
        _BASELINE_CACHE = cache
    return _BASELINE_CACHE.get((task_id, arm, idx), {})


def _is_enrichment_like(text: str, raw: dict[str, Any], claim_type: str) -> bool:
    if raw.get("claim_type") == "PATHWAY_ENRICHMENT":
        return True
    low = text.lower()
    return (
        "rank" in low
        or "fdr" in low
        or "p-value" in low
        or "p_value" in low
        or re.search(r"\bp\s*=", low) is not None
        or any(tok in low for tok in ("mummichog", "metaboanalyst", "ramp", "sspa", "fella"))
    )


def _verify_enrichment_method_aware(
    text: str,
    raw: dict[str, Any],
    carrier: dict[str, Any],
    method: str,
) -> tuple[str, str, str]:
    rows, base = _carrier_rows(carrier, method)
    if not rows:
        return ClaimVerdict.UNVERIFIABLE_V0.value, f"{method} carrier not populated", base
    hint = _pathway_hint(raw, text)
    matched_idx, matched = _find_row(rows, hint)
    if matched is None:
        return ClaimVerdict.CONTRADICTED.value, f"No {method} carrier row matched {hint!r}", base
    claimed_rank = _claimed_rank(raw, text)
    claimed_score = _claimed_score(raw, text)
    observed_rank = _row_rank(matched, matched_idx)
    observed_score = _row_score(matched)
    rank_ok = claimed_rank is None or _rank_matches(claimed_rank, observed_rank)
    score_ok = claimed_score is None or _score_matches(claimed_score, observed_score)
    if rank_ok and score_ok:
        return (
            ClaimVerdict.SUPPORTED.value,
            f"{method} carrier match pathway_id={matched.get('pathway_id')} rank={observed_rank} score={observed_score}",
            f"{base}[{matched_idx}]",
        )
    return (
        ClaimVerdict.CONTRADICTED.value,
        (
            f"{method} carrier row matched {hint!r} but claimed_rank={claimed_rank}, "
            f"observed_rank={observed_rank}, claimed_score={claimed_score}, observed_score={observed_score}"
        ),
        f"{base}[{matched_idx}]",
    )


def _carrier_for(task_id: str, task: dict[str, Any], dump: dict[str, Any]) -> dict[str, Any]:
    carrier = {"ramp_enrichment_result": task.get("ramp_enrichment_result") or {}}
    carrier.update((dump.get("final_react_result") or {}).get("enrichment_carriers") or {})
    return carrier


def _carrier_rows(carrier: dict[str, Any], method: str) -> tuple[list[dict[str, Any]], str]:
    if method == "mummichog":
        c = carrier.get("mummichog_enrichment_result") or {}
        return list(c.get("pathways") or c.get("top_pathways") or []), "mummichog_enrichment_result.pathways"
    if method == "metaboanalystr":
        c = ((carrier.get("metaboanalystr_enrichment_result") or {}).get("psea") or {})
        return list(c.get("pathways") or c.get("top_pathways") or []), "metaboanalystr_enrichment_result.psea.pathways"
    if method == "sspa":
        c = carrier.get("sspa_enrichment_result") or {}
        return list(c.get("pathways") or c.get("top_pathways") or []), "sspa_enrichment_result.pathways"
    if method == "fella":
        c = carrier.get("fella_enrichment_result") or {}
        return list(c.get("pathways") or c.get("top_pathways") or []), "fella_enrichment_result.pathways"
    rows = list((carrier.get("ramp_enrichment_result") or {}).get("top_pathways") or [])
    return rows, "ramp_enrichment_result.top_pathways"


def _method_from(raw: dict[str, Any], text: str) -> str:
    method = str(raw.get("evidence_method") or "").lower()
    if "mummichog" in method:
        return "mummichog"
    if "metaboanalystr" in method or "metaboanalyst" in method or "psea" in method or "msea" in method:
        return "metaboanalystr"
    if "sspa" in method:
        return "sspa"
    if "fella" in method:
        return "fella"
    if "ramp" in method:
        return "ramp"
    return d15._method(text)


def _pathway_hint(raw: dict[str, Any], text: str) -> str:
    for key in ("pathway_id", "pathway_name"):
        value = raw.get(key)
        if value:
            return str(value)
    return d15._pathway_hint(text)


def _find_row(rows: list[dict[str, Any]], hint: str) -> tuple[int, dict[str, Any] | None]:
    if not rows:
        return -1, None
    if not hint:
        return 0, rows[0]
    norm_hint = _norm(hint)
    for idx, row in enumerate(rows):
        values = [
            row.get("pathway_id"),
            row.get("pathway_name"),
            row.get("pathway_id_native"),
            row.get("pathway_external_id"),
        ]
        if any(_pathway_matches(norm_hint, _norm(str(value or ""))) for value in values):
            return idx, row
    return -1, None


def _pathway_matches(hint: str, value: str) -> bool:
    if not hint or not value:
        return False
    # Avoid matching every KEGG:* claim to a generic KEGG carrier row.
    weak_prefixes = ("kegg", "wp", "smpdb", "react", "mumm")
    if hint in weak_prefixes or value in weak_prefixes:
        return False
    return hint == value or hint in value or value in hint


def _claimed_rank(raw: dict[str, Any], text: str) -> int | None:
    if raw.get("rank") is not None:
        try:
            return int(raw["rank"])
        except (TypeError, ValueError):
            pass
    return d15._rank_claimed(text)


def _claimed_score(raw: dict[str, Any], text: str) -> float | None:
    if raw.get("score") is not None:
        try:
            return float(raw["score"])
        except (TypeError, ValueError):
            pass
    return d15._score_claimed(text)


def _row_rank(row: dict[str, Any], idx: int) -> int | None:
    if row.get("rank") is not None:
        try:
            return int(row["rank"])
        except (TypeError, ValueError):
            return None
    return idx if idx >= 0 else None


def _row_score(row: dict[str, Any]) -> float | None:
    return d15._carrier_score(row)


def _rank_matches(claimed: int, observed: int | None) -> bool:
    if observed is None:
        return False
    return claimed == observed or (claimed > 0 and claimed - 1 == observed)


def _score_matches(claimed: float, observed: float | None) -> bool:
    return d15._score_matches(claimed, observed)


def _norm(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _attribute(arms: list[Arm]) -> list[dict[str, Any]]:
    by_task_arm: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for arm in arms:
        by_task_arm[(arm.task_id, arm.arm)] = arm.claims
    rows = []
    task_ids = sorted({arm.task_id for arm in arms})
    for task_id in task_ids:
        prose = by_task_arm[(task_id, "prose")]
        struct = by_task_arm[(task_id, "struct")]
        for prose_claim in prose:
            if prose_claim["verdict"] not in UV_VERDICTS:
                continue
            match_idx, match, score = _best_match(prose_claim, struct)
            if match is None or score < 0.28:
                attr = "UNMAPPABLE"
                matched_verdict = ""
            elif match["verdict"] == ClaimVerdict.SUPPORTED.value:
                attr = "PIPELINE-LOST"
                matched_verdict = match["verdict"]
            elif match["verdict"] in UV_VERDICTS:
                attr = "REACT-UNGROUNDED"
                matched_verdict = match["verdict"]
            else:
                attr = "STRUCT-NON-UV-NON-SUPPORTED"
                matched_verdict = match["verdict"]
            rows.append({
                "task_id": task_id,
                "prose_claim_index": prose_claim["claim_index"],
                "prose_verdict": prose_claim["verdict"],
                "prose_claim_text": prose_claim["claim_text"],
                "matched_struct_index": "" if match_idx is None else match_idx,
                "match_score": round(score, 4),
                "matched_struct_verdict": matched_verdict,
                "matched_struct_layer": "" if match is None else match["verifier_layer"],
                "matched_struct_claim_text": "" if match is None else match["claim_text"],
                "attribution": attr,
            })
    return rows


def _best_match(claim: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[int | None, dict[str, Any] | None, float]:
    best: tuple[int | None, dict[str, Any] | None, float] = (None, None, 0.0)
    text = claim["claim_text"].lower()
    for idx, candidate in enumerate(candidates):
        score = SequenceMatcher(None, text, candidate["claim_text"].lower()).ratio()
        if score > best[2]:
            best = (idx, candidate, score)
    return best


def _spotcheck(attribution: list[dict[str, Any]], per_claim: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pipeline = [
        row for row in attribution
        if row["attribution"] == "PIPELINE-LOST"
        and row["matched_struct_layer"] == "method_aware_enrichment"
    ]
    contrad = [
        row for row in per_claim
        if row["arm"] == "struct"
        and row["verdict"] == ClaimVerdict.CONTRADICTED.value
        and row["verifier_layer"] == "method_aware_enrichment"
    ]
    rows = []
    for row in _pick_diverse(pipeline, "matched_struct_claim_text", 10):
        rows.append(_spot_row("PIPELINE_LOST_TO_SUPPORTED", row["task_id"], row["matched_struct_claim_text"], row))
    for row in _pick_diverse(contrad, "claim_text", 10):
        rows.append(_spot_row("STRUCT_NEW_CONTRADICTED", row["task_id"], row["claim_text"], row))
    return rows


def _pick_diverse(rows: list[dict[str, Any]], text_key: str, n: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {"ramp": [], "mummichog": [], "metaboanalystr": [], "sspa": [], "fella": [], "other": []}
    for row in rows:
        method = row.get("method") or d15._method(row[text_key])
        buckets.setdefault(method, []).append(row)
    out = []
    while len(out) < n and any(buckets.values()):
        for key in ("ramp", "mummichog", "metaboanalystr", "sspa", "fella", "other"):
            if buckets.get(key) and len(out) < n:
                out.append(buckets[key].pop(0))
    return out


def _spot_row(group: str, task_id: str, text: str, source: dict[str, Any]) -> dict[str, Any]:
    task = _task_by_id(task_id)
    dump = _dump_by_id(task_id)
    carrier = _carrier_for(task_id, task, dump)
    method = source.get("method") or d15._method(text)
    rows, base = _carrier_rows(carrier, method)
    hint = d15._pathway_hint(text)
    idx, matched = _find_row(rows, hint)
    if matched is None:
        label = "FALSE" if group == "PIPELINE_LOST_TO_SUPPORTED" else "TRUE"
        rationale = f"No matching {method} carrier row for {hint!r} in {base}."
        carrier_rows = rows[:3]
    else:
        claimed_rank = d15._rank_claimed(text)
        claimed_score = d15._score_claimed(text)
        observed_rank = _row_rank(matched, idx)
        observed_score = _row_score(matched)
        rank_ok = claimed_rank is None or _rank_matches(claimed_rank, observed_rank)
        score_ok = claimed_score is None or _score_matches(claimed_score, observed_score)
        true_support = rank_ok and score_ok
        label = "TRUE" if (group == "PIPELINE_LOST_TO_SUPPORTED" and true_support) or (group == "STRUCT_NEW_CONTRADICTED" and not true_support) else "FALSE"
        rationale = (
            f"Matched {base}[{idx}] pathway_id={matched.get('pathway_id')} "
            f"name={matched.get('pathway_name')} rank={observed_rank} score={observed_score}; "
            f"claimed_rank={claimed_rank}; claimed_score={claimed_score}."
        )
        carrier_rows = [matched]
    return {
        "sample_group": group,
        "task_id": task_id,
        "method": method,
        "pathway_hint": hint,
        "claim_text": text,
        "script_verdict": source.get("matched_struct_verdict") or source.get("verdict") or "",
        "carrier_rows_examined": json.dumps(carrier_rows, ensure_ascii=False, sort_keys=True)[:4000],
        "manual_label": label,
        "manual_rationale": rationale,
    }


_TASK_CACHE: dict[str, dict[str, Any]] | None = None
_DUMP_CACHE: dict[str, dict[str, Any]] | None = None


def _task_by_id(task_id: str) -> dict[str, Any]:
    global _TASK_CACHE
    if _TASK_CACHE is None:
        ids = d1._read_clean_task_ids()
        _TASK_CACHE = d1._read_tasks(ids)
    return _TASK_CACHE[task_id]


def _dump_by_id(task_id: str) -> dict[str, Any]:
    global _DUMP_CACHE
    if _DUMP_CACHE is None:
        ids = d1._read_clean_task_ids()
        _DUMP_CACHE = d1._read_full_dumps(ids)
    return _DUMP_CACHE[task_id]


def _metrics(arms: list[Arm], attribution: list[dict[str, Any]], spotcheck: list[dict[str, Any]]) -> dict[str, Any]:
    arm_metrics = {}
    for arm_name in ("prose", "struct"):
        selected = [arm for arm in arms if arm.arm == arm_name]
        claims = [claim for arm in selected for claim in arm.claims]
        counts = Counter(claim["verdict"] for claim in claims)
        source = sum(arm.source_claims for arm in selected)
        dropped = sum(arm.dropped for arm in selected)
        drop_reasons = Counter()
        for arm in selected:
            drop_reasons.update(arm.drop_reasons)
        uv = counts.get(ClaimVerdict.UNVERIFIABLE_V0.value, 0) + counts.get(ClaimVerdict.ERROR.value, 0)
        arm_metrics[arm_name] = {
            "tasks": len(selected),
            "source_claims": source,
            "verified_claims": len(claims),
            "dropped": dropped,
            "verdict_counts": dict(sorted(counts.items())),
            "drop_reasons": dict(drop_reasons.most_common()),
            "supported_rate_honest": round(counts.get(ClaimVerdict.SUPPORTED.value, 0) / source, 6) if source else None,
            "contradicted_rate_honest": round(counts.get(ClaimVerdict.CONTRADICTED.value, 0) / source, 6) if source else None,
            "uv_rate_honest": round(uv / source, 6) if source else None,
            "unlanded_rate_honest": round((uv + dropped) / source, 6) if source else None,
        }
    d1_metrics = json.loads((OUT_DIR / "two_arm_metrics.json").read_text())
    method_bug = {
        "prose_supported_gain_pp": _pp(arm_metrics["prose"]["supported_rate_honest"] - d1_metrics["arms"]["prose"]["supported_rate"] if arm_metrics["prose"]["supported_rate_honest"] is not None else 0),
        "struct_supported_gain_pp": _pp(arm_metrics["struct"]["supported_rate_honest"] - (d1_metrics["arms"]["struct"]["verdict_counts"].get("supported", 0) / d1_metrics["arms"]["struct"]["source_claims"])),
        "struct_contradicted_change_pp": _pp(arm_metrics["struct"]["contradicted_rate_honest"] - (d1_metrics["arms"]["struct"]["verdict_counts"].get("contradicted", 0) / d1_metrics["arms"]["struct"]["source_claims"])),
    }
    input_contract_gain = {
        "supported_gain_pp_method_aware_struct_minus_prose": _pp(arm_metrics["struct"]["supported_rate_honest"] - arm_metrics["prose"]["supported_rate_honest"]),
        "unlanded_change_pp_method_aware_struct_minus_prose": _pp(arm_metrics["struct"]["unlanded_rate_honest"] - arm_metrics["prose"]["unlanded_rate_honest"]),
    }
    spot_counts = {
        group: dict(Counter(row["manual_label"] for row in spotcheck if row["sample_group"] == group))
        for group in sorted({row["sample_group"] for row in spotcheck})
    }
    return {
        "input": {"tasks": 59, "cost_usd": 0.0, "production_verifier_modified": False},
        "arms": arm_metrics,
        "attribution_counts": dict(Counter(row["attribution"] for row in attribution)),
        "spotcheck": spot_counts,
        "method_bug_only": method_bug,
        "input_contract_incremental": input_contract_gain,
        "gate": _gate(spot_counts, input_contract_gain),
    }


def _pp(value: float) -> float:
    return round(value * 100, 2)


def _gate(spot_counts: dict[str, dict[str, int]], input_contract_gain: dict[str, float]) -> dict[str, Any]:
    rates = {}
    passed = True
    for group, counts in spot_counts.items():
        total = sum(counts.values())
        rate = counts.get("TRUE", 0) / total if total else 0.0
        rates[group] = round(rate, 4)
        if rate < 0.8:
            passed = False
    supported_gain = input_contract_gain["supported_gain_pp_method_aware_struct_minus_prose"]
    return {
        "spotcheck_true_rates": rates,
        "spotcheck_pass": passed,
        "supported_gain_pp": supported_gain,
        "recommended_branch": (
            "GO_IMPLEMENTATION_DESIGN" if passed and supported_gain >= 3.0
            else "PING_SMALL_GAIN" if passed
            else "STOP_REVIEW_PROTOTYPE"
        ),
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(metrics: dict[str, Any]) -> None:
    prose = metrics["arms"]["prose"]
    struct = metrics["arms"]["struct"]
    lines = [
        "# W22 D1.6 Method-aware Remeasure",
        "",
        "## Scope",
        "",
        "- Offline only, cost $0.",
        "- No ReAct rerun and no production verifier changes.",
        "- Enrichment claims route by method: RaMP, mummichog, MetaboAnalystR, SSPA, FELLA.",
        "",
        "## Honest Metrics",
        "",
        "| arm | source | verified | dropped | supported | contradicted | unsupported | UV | supported honest | unlanded honest |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, arm in (("prose", prose), ("struct", struct)):
        counts = arm["verdict_counts"]
        uv = counts.get("unverifiable_v0", 0) + counts.get("error", 0)
        lines.append(
            f"| {name} | {arm['source_claims']} | {arm['verified_claims']} | {arm['dropped']} | "
            f"{counts.get('supported', 0)} | {counts.get('contradicted', 0)} | {counts.get('unsupported', 0)} | {uv} | "
            f"{arm['supported_rate_honest']:.2%} | {arm['unlanded_rate_honest']:.2%} |"
        )
    lines += [
        "",
        "## Gain Split",
        "",
        f"- Method bug only, prose supported gain vs D1: {metrics['method_bug_only']['prose_supported_gain_pp']:+.2f} pp",
        f"- Method bug only, struct supported gain vs D1: {metrics['method_bug_only']['struct_supported_gain_pp']:+.2f} pp",
        f"- Method bug only, struct contradicted change vs D1: {metrics['method_bug_only']['struct_contradicted_change_pp']:+.2f} pp",
        f"- Input contract incremental supported gain, struct minus prose after method-aware: {metrics['input_contract_incremental']['supported_gain_pp_method_aware_struct_minus_prose']:+.2f} pp",
        f"- Input contract unlanded change, struct minus prose after method-aware: {metrics['input_contract_incremental']['unlanded_change_pp_method_aware_struct_minus_prose']:+.2f} pp",
        "",
        "## Spotcheck Gate",
        "",
    ]
    for group, counts in metrics["spotcheck"].items():
        total = sum(counts.values())
        true = counts.get("TRUE", 0)
        lines.append(f"- {group}: {true}/{total} TRUE = {true/total:.0%}")
    lines += [
        "",
        f"- Recommended branch: `{metrics['gate']['recommended_branch']}`",
    ]
    SUMMARY_OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
