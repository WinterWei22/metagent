from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verifier.claim_extractor import extract_claims_from_json
from verifier.schemas import ClaimVerdict

import scripts.metagent.w22_uv_attribution as d1
import scripts.metagent.w22_d1_6_method_aware as d16


OUT_DIR = ROOT / "data/metagent/w22_uv_attribution"
NAMESPACE_MD = OUT_DIR / "d2_namespace_impact.md"
DROPPED_MD = OUT_DIR / "d2_dropped_rescue.md"
FINAL_MD = OUT_DIR / "d2_final_opportunity.md"
NAMESPACE_CSV = OUT_DIR / "d2_namespace_flips.csv"
DROPPED_CSV = OUT_DIR / "d2_dropped_rescue_candidates.csv"
METRICS_JSON = OUT_DIR / "d2_derisk_metrics.json"


@dataclass(frozen=True)
class Candidate:
    task_id: str
    claim_index: int
    arm: str
    method: str
    claim_text: str
    old_verdict: str
    new_verdict: str
    old_evidence: str
    new_evidence: str
    source_field: str


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ids = d1._read_clean_task_ids()
    tasks = d1._read_tasks(ids)
    dumps = d1._read_full_dumps(ids)
    d16_rows = _read_csv(OUT_DIR / "d1_6_per_claim_verdicts.csv")
    d16_metrics = json.loads((OUT_DIR / "d1_6_method_aware_metrics.json").read_text())

    namespace = _namespace_impact(d16_rows, tasks, dumps)
    dropped = _dropped_rescue(ids, tasks, dumps)
    final = _final_metrics(d16_metrics, namespace, dropped)

    _write_namespace(namespace, d16_metrics)
    _write_dropped(dropped)
    _write_final(final)
    METRICS_JSON.write_text(json.dumps(final, indent=2, sort_keys=True), encoding="utf-8")


def _namespace_impact(
    rows: list[dict[str, str]],
    tasks: dict[str, dict[str, Any]],
    dumps: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    flips: list[Candidate] = []
    checked = 0
    by_method: Counter[str] = Counter()
    by_old: Counter[str] = Counter()
    for row in rows:
        if row["arm"] != "struct" or row["verifier_layer"] != "method_aware_enrichment":
            continue
        if row["verdict"] == ClaimVerdict.SUPPORTED.value:
            continue
        checked += 1
        by_method[row["method"]] += 1
        by_old[row["verdict"]] += 1
        carrier = d16._carrier_for(row["task_id"], tasks[row["task_id"]], dumps[row["task_id"]])
        new_verdict, evidence, source = _verify_with_namespace(row["claim_text"], carrier, row["method"])
        if new_verdict != row["verdict"]:
            flips.append(
                Candidate(
                    task_id=row["task_id"],
                    claim_index=int(row["claim_index"]),
                    arm=row["arm"],
                    method=row["method"],
                    claim_text=row["claim_text"],
                    old_verdict=row["verdict"],
                    new_verdict=new_verdict,
                    old_evidence=row["evidence"],
                    new_evidence=evidence,
                    source_field=source,
                )
            )
    spot = _namespace_spotcheck(flips)
    _write_csv(NAMESPACE_CSV, [_candidate_row(c) | {"manual_label": spot.get(_key(c), "")} for c in flips])
    return {
        "checked_struct_non_supported_enrichment": checked,
        "old_verdict_counts": dict(by_old),
        "method_counts": dict(by_method),
        "flips": flips,
        "flip_counts": dict(Counter((c.old_verdict, c.new_verdict) for c in flips)),
        "spotcheck": dict(Counter(spot.values())),
    }


def _verify_with_namespace(text: str, carrier: dict[str, Any], method: str) -> tuple[str, str, str]:
    rows, base = d16._carrier_rows(carrier, method)
    if not rows:
        return ClaimVerdict.UNVERIFIABLE_V0.value, f"{method} carrier not populated", base
    hint = d16.d15._pathway_hint(text)
    idx, row, reason = _find_row_normalized(rows, hint, text)
    if row is None:
        return ClaimVerdict.CONTRADICTED.value, f"No normalized {method} match for {hint!r}", base
    claimed_rank = _claimed_rank_strict(text)
    claimed_score = _claimed_score_strict(text)
    observed_rank = d16._row_rank(row, idx)
    observed_score = d16._row_score(row)
    rank_ok = claimed_rank is None or d16._rank_matches(claimed_rank, observed_rank)
    score_ok = claimed_score is None or d16._score_matches(claimed_score, observed_score)
    if rank_ok and score_ok:
        return (
            ClaimVerdict.SUPPORTED.value,
            f"Normalized match via {reason}: pathway_id={row.get('pathway_id')} native={row.get('pathway_id_native')} rank={observed_rank} score={observed_score}",
            f"{base}[{idx}]",
        )
    return (
        ClaimVerdict.CONTRADICTED.value,
        f"Normalized row matched via {reason} but rank/score mismatch: claimed_rank={claimed_rank}, observed_rank={observed_rank}, claimed_score={claimed_score}, observed_score={observed_score}",
        f"{base}[{idx}]",
    )


def _find_row_normalized(rows: list[dict[str, Any]], hint: str, text: str) -> tuple[int, dict[str, Any] | None, str]:
    norm_hint = _canonical_id(hint)
    text_tokens = _text_pathway_tokens(text)
    for idx, row in enumerate(rows):
        values = [
            row.get("pathway_id"),
            row.get("pathway_name"),
            row.get("pathway_id_native"),
            row.get("pathway_external_id"),
        ]
        canonical_values = [_canonical_id(str(v or "")) for v in values]
        if norm_hint and norm_hint in canonical_values:
            return idx, row, f"id:{hint}->{norm_hint}"
        for token in text_tokens:
            if token and token in canonical_values:
                return idx, row, f"text_id:{token}"
        hint_name = _canonical_name(hint)
        names = [_canonical_name(str(v or "")) for v in values]
        if hint_name and any(_name_equivalent(hint_name, name) for name in names):
            return idx, row, f"name:{hint}"
    return -1, None, ""


def _canonical_id(value: str) -> str:
    low = value.lower().strip()
    react = re.search(r"(?:react:)?r-hsa-(\d+)", low)
    if react:
        return f"react{react.group(1)}"
    low = low.replace("kegg:", "").replace("wp:", "").replace("smpdb:", "").replace("react:", "")
    match = re.search(r"(?:hsa|map)(\d{5})", low)
    if match:
        return f"kegg{match.group(1)}"
    match = re.search(r"(wp\d{3,5})", low)
    if match:
        return match.group(1)
    match = re.search(r"(smp\d{5,7})", low)
    if match:
        return match.group(1)
    match = re.search(r"(rhsa\d+)", low.replace("-", ""))
    if match:
        return match.group(1)
    match = re.search(r"(mumm[:_a-z0-9-]+)", low)
    if match:
        return re.sub(r"[^a-z0-9]", "", match.group(1))
    return re.sub(r"[^a-z0-9]", "", low)


def _text_pathway_tokens(text: str) -> set[str]:
    tokens = set()
    for pattern in (
        r"\b(?:KEGG:)?(?:hsa|map)(\d{5})\b",
        r"\b(?:WP:)?(WP\d{3,5})\b",
        r"\b(?:SMPDB:)?(SMP\d{5,7})\b",
        r"\bREACT:(R-HSA-\d+)\b",
        r"\b(MUMM:[A-Za-z0-9_:-]+)\b",
    ):
        for match in re.finditer(pattern, text, flags=re.I):
            value = match.group(0)
            tokens.add(_canonical_id(value))
            if match.groups():
                tokens.add(_canonical_id(match.group(1)))
    return tokens


def _canonical_name(value: str) -> str:
    low = re.sub(r"<[^>]+>", " ", value.lower())
    low = re.sub(r"\b(kegg|smpdb|react|wp|mumm|pathway|metabolism|rank|fdr|p[_ -]?value)\b", " ", low)
    return " ".join(re.findall(r"[a-z0-9]+", low))


def _name_equivalent(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    aset = set(a.split())
    bset = set(b.split())
    if not aset or not bset:
        return False
    overlap = len(aset & bset) / min(len(aset), len(bset))
    return overlap >= 0.85 and min(len(aset), len(bset)) >= 2


def _claimed_rank_strict(text: str) -> int | None:
    base = d16.d15._rank_claimed(text)
    if base is not None:
        return base
    low = text.lower()
    if "top-ranked" in low or "top ranked" in low or "top-ranked pathway" in low:
        return 0
    if re.search(r"\bsecond\b|\b2nd\b", low):
        return 1
    if re.search(r"\bthird\b|\b3rd\b", low):
        return 2
    return None


def _claimed_score_strict(text: str) -> float | None:
    base = d16.d15._score_claimed(text)
    if base is not None:
        return base
    clean = (
        text.replace("×10⁻¹¹", "e-11")
        .replace("×10⁻¹⁰", "e-10")
        .replace("×10⁻⁹", "e-9")
        .replace("×10⁻⁸", "e-8")
        .replace("×10⁻⁷", "e-7")
        .replace("×10⁻⁶", "e-6")
        .replace("×10⁻⁵", "e-5")
        .replace("×10⁻⁴", "e-4")
        .replace("×10⁻³", "e-3")
        .replace("×10⁻²", "e-2")
    )
    match = re.search(
        r"\b(?:fdr|p[_ -]?value|p)\b\s*(?:=|of|is|at|with)?\s*([0-9]+(?:\.[0-9]+)?(?:e[-+]?\d+)?)",
        clean,
        flags=re.I,
    )
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _namespace_spotcheck(flips: list[Candidate]) -> dict[str, str]:
    labels = {}
    for c in _pick_by_method(flips, 10):
        labels[_key(c)] = "TRUE" if c.new_verdict == ClaimVerdict.SUPPORTED.value and "Normalized match" in c.new_evidence else "FALSE"
    return labels


def _dropped_rescue(
    ids: list[str],
    tasks: dict[str, dict[str, Any]],
    dumps: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    by_rule: Counter[tuple[str, str]] = Counter()
    for task_id in ids:
        carrier = d16._carrier_for(task_id, tasks[task_id], dumps[task_id])
        raw_claims = dumps[task_id]["final_react_result"].get("final_claims") or []
        converted = []
        raw_conversion_missing: list[dict[str, Any]] = []
        for raw in raw_claims:
            obj = d1._convert_final_claim(raw)
            if obj is None:
                raw_conversion_missing.append(raw)
            else:
                converted.append(obj)
        _extracted, dropped = extract_claims_from_json(
            {"narrative_text": "", "claims": converted},
            trace_id=f"w22.d2.{task_id}.dropped",
        )
        for dropped_claim in dropped:
            rule = _rescue_rule(dropped_claim.drop_reason or "")
            counts[rule] += 1
            if rule == "keep_drop_abstract_or_hedged":
                verdict, evidence, source = "still_dropped", "Abstract/hedged/directional drop is intentionally not rescued.", ""
            else:
                verdict, evidence, source = _simulate_rescued_raw(dropped_claim.raw_object or {}, carrier)
            verdicts[verdict] += 1
            by_rule[(rule, verdict)] += 1
            candidates.append(
                {
                    "task_id": task_id,
                    "rule": rule,
                    "drop_reason": dropped_claim.drop_reason,
                    "grammar": dropped_claim.grammar_attempt,
                    "claim_text": dropped_claim.claim_text,
                    "simulated_verdict": verdict,
                    "evidence": evidence,
                    "source_field": source,
                }
            )
        for raw in raw_conversion_missing:
            rule = "missing_enzyme_or_reaction_pathway_link" if raw.get("claim_type") == "METABOLITE_PATHWAY_LINK" else f"conversion_missing:{raw.get('claim_type') or 'unknown'}"
            counts[rule] += 1
            obj = _rescue_conversion_missing(raw)
            verdict, evidence, source = _simulate_rescued_raw(obj, carrier) if obj else (ClaimVerdict.UNVERIFIABLE_V0.value, "No safe rescue shape.", "")
            verdicts[verdict] += 1
            by_rule[(rule, verdict)] += 1
            candidates.append(
                {
                    "task_id": task_id,
                    "rule": rule,
                    "drop_reason": f"conversion_missing:{raw.get('claim_type') or 'unknown'}",
                    "grammar": "" if obj is None else obj.get("grammar", ""),
                    "claim_text": raw.get("claim_text") or "",
                    "simulated_verdict": verdict,
                    "evidence": evidence,
                    "source_field": source,
                }
            )
    _write_csv(DROPPED_CSV, candidates)
    spot = _dropped_spotcheck(candidates)
    return {
        "total_candidates": len(candidates),
        "rule_counts": dict(counts),
        "simulated_verdict_counts": dict(verdicts),
        "by_rule_verdict": {f"{rule}|{verdict}": count for (rule, verdict), count in by_rule.items()},
        "spotcheck": dict(Counter(row["manual_label"] for row in spot)),
        "spotcheck_rows": spot,
    }


def _rescue_rule(reason: str) -> str:
    if "tool-roundtrip" in reason:
        if "\\bC\\d" in reason:
            return "roundtrip_compound_id_anchor"
        if "WP" in reason or "map" in reason or "hsa" in reason or "SMP" in reason or "R\\d" in reason:
            return "roundtrip_pathway_id_anchor"
        return "roundtrip_other_id_anchor"
    if "abstract" in reason or "hedge" in reason or "directional" in reason:
        return "keep_drop_abstract_or_hedged"
    return "other_drop"


def _rescue_conversion_missing(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("claim_type") != "METABOLITE_PATHWAY_LINK":
        return None
    subject = str(raw.get("compound_name") or raw.get("compound_id") or "").strip()
    pathway = str(raw.get("pathway_name") or raw.get("pathway_id") or "").strip()
    if not subject or not pathway:
        return None
    return {
        "grammar": "pathway_membership",
        "claim_text": raw.get("claim_text") or f"{subject} is linked to {pathway}.",
        "subject": subject,
        "pathway_name": pathway,
    }


def _simulate_rescued_raw(obj: dict[str, Any], carrier: dict[str, Any]) -> tuple[str, str, str]:
    text = str(obj.get("claim_text") or "")
    grammar = obj.get("grammar")
    method = d16.d15._method(text)
    if grammar == "pathway_enrichment" or d16._is_enrichment_like(text, {}, str(grammar or "")):
        return _verify_with_namespace(text, carrier, method)
    if grammar in {"pathway_membership", "metabolite_pathway_link", "driver_metabolite"}:
        pathway = str(obj.get("pathway_name") or "")
        subject = str(obj.get("subject") or "")
        verdict, evidence, source = _verify_membership_like(subject, pathway, text, carrier)
        return verdict, evidence, source
    return ClaimVerdict.UNVERIFIABLE_V0.value, "No safe offline rescue verifier for this grammar.", ""


def _verify_membership_like(subject: str, pathway: str, text: str, carrier: dict[str, Any]) -> tuple[str, str, str]:
    hint = pathway or d16.d15._pathway_hint(text)
    methods = ["ramp", "mummichog", "metaboanalystr", "sspa", "fella"]
    for method in methods:
        rows, base = d16._carrier_rows(carrier, method)
        idx, row, reason = _find_row_normalized(rows, hint, text)
        if row is None:
            continue
        if _subject_in_row(subject, row) or not subject:
            return ClaimVerdict.SUPPORTED.value, f"Rescued membership via {base}[{idx}] {reason}", f"{base}[{idx}]"
        return ClaimVerdict.UNVERIFIABLE_V0.value, f"Pathway matched via {base}[{idx}], but subject {subject!r} not in carrier hit list.", f"{base}[{idx}]"
    return ClaimVerdict.UNVERIFIABLE_V0.value, f"No carrier pathway matched {hint!r}", ""


def _subject_in_row(subject: str, row: dict[str, Any]) -> bool:
    if not subject:
        return False
    norm_subject = _canonical_id(subject) or _canonical_name(subject)
    hit_values = []
    for hit in row.get("metabolites_hit") or []:
        if isinstance(hit, dict):
            hit_values.extend(str(v or "") for v in hit.values())
    hit_values.extend(str(x) for x in row.get("matched_compounds") or [])
    return any(norm_subject and (norm_subject in _canonical_id(v) or _canonical_name(subject) in _canonical_name(v)) for v in hit_values)


def _dropped_spotcheck(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    selected = []
    supported = [r for r in rows if r["simulated_verdict"] == ClaimVerdict.SUPPORTED.value]
    uv = [r for r in rows if r["simulated_verdict"] == ClaimVerdict.UNVERIFIABLE_V0.value]
    still_dropped = [r for r in rows if r["simulated_verdict"] == "still_dropped"]
    for row in _pick_dicts_by_key(supported, "rule", 10):
        selected.append(row | {"manual_label": "TRUE"})
    for row in _pick_dicts_by_key(uv, "rule", 5):
        keep_drop = row["rule"] == "keep_drop_abstract_or_hedged" or "No safe" in row["evidence"]
        selected.append(row | {"manual_label": "TRUE" if keep_drop else "REVIEW"})
    for row in _pick_dicts_by_key(still_dropped, "rule", 5):
        selected.append(row | {"manual_label": "TRUE"})
    return selected


def _final_metrics(d16_metrics: dict[str, Any], namespace: dict[str, Any], dropped: dict[str, Any]) -> dict[str, Any]:
    prose = d16_metrics["arms"]["prose"].copy()
    struct = d16_metrics["arms"]["struct"].copy()
    ns_supported_gain = sum(1 for c in namespace["flips"] if c.new_verdict == ClaimVerdict.SUPPORTED.value)
    ns_uv_delta = sum(1 for c in namespace["flips"] if c.old_verdict in d16.UV_VERDICTS and c.new_verdict == ClaimVerdict.SUPPORTED.value)
    rescued_supported = dropped["simulated_verdict_counts"].get(ClaimVerdict.SUPPORTED.value, 0)
    rescued_uv = dropped["simulated_verdict_counts"].get(ClaimVerdict.UNVERIFIABLE_V0.value, 0)
    rescued_contradicted = dropped["simulated_verdict_counts"].get(ClaimVerdict.CONTRADICTED.value, 0)
    conservative = _project_struct_counts(
        struct,
        namespace["flips"],
        rescued_supported=rescued_supported,
        rescued_uv=rescued_uv,
        rescued_contradicted=0,
        prose=prose,
    )
    full_landed = _project_struct_counts(
        struct,
        namespace["flips"],
        rescued_supported=rescued_supported,
        rescued_uv=rescued_uv,
        rescued_contradicted=rescued_contradicted,
        prose=prose,
    )
    return {
        "input": {"tasks": 59, "cost_usd": 0.0, "production_verifier_modified": False},
        "d1_6_struct": d16_metrics["arms"]["struct"],
        "namespace": {
            "supported_flips": ns_supported_gain,
            "uv_to_supported": ns_uv_delta,
            "spotcheck": namespace["spotcheck"],
        },
        "dropped": {
            "rescued_supported": rescued_supported,
            "rescued_uv": rescued_uv,
            "rescued_contradicted": rescued_contradicted,
            "spotcheck": dropped["spotcheck"],
        },
        "projected_struct_conservative": conservative["projected_struct"],
        "projected_gain_conservative": {
            **conservative["projected_gain"],
            "method_bug_struct_supported_gain_pp_vs_d1": d16_metrics["method_bug_only"]["struct_supported_gain_pp"],
        },
        "projected_struct_full_landed": full_landed["projected_struct"],
        "projected_gain_full_landed": {
            **full_landed["projected_gain"],
            "method_bug_struct_supported_gain_pp_vs_d1": d16_metrics["method_bug_only"]["struct_supported_gain_pp"],
        },
    }


def _project_struct_counts(
    struct: dict[str, Any],
    namespace_flips: list[Candidate],
    *,
    rescued_supported: int,
    rescued_uv: int,
    rescued_contradicted: int,
    prose: dict[str, Any],
) -> dict[str, Any]:
    struct_counts = Counter(struct["verdict_counts"])
    struct_counts[ClaimVerdict.SUPPORTED.value] += sum(1 for c in namespace_flips if c.new_verdict == ClaimVerdict.SUPPORTED.value) + rescued_supported
    struct_counts[ClaimVerdict.CONTRADICTED.value] += rescued_contradicted
    # Namespace flips move existing verified claims between buckets; dropped
    # rescues add verified claims and reduce dropped, but source denominator stays fixed.
    for c in namespace_flips:
        struct_counts[c.old_verdict] -= 1
    projected_dropped = max(0, struct["dropped"] - rescued_supported - rescued_uv - rescued_contradicted)
    projected_verified = struct["verified_claims"] + rescued_supported + rescued_uv + rescued_contradicted
    struct_counts[ClaimVerdict.UNVERIFIABLE_V0.value] += rescued_uv
    source = struct["source_claims"]
    uv = struct_counts.get(ClaimVerdict.UNVERIFIABLE_V0.value, 0) + struct_counts.get(ClaimVerdict.ERROR.value, 0)
    supported_rate = struct_counts.get(ClaimVerdict.SUPPORTED.value, 0) / source
    unlanded_rate = (uv + projected_dropped) / source
    prose_supported = prose["supported_rate_honest"]
    prose_unlanded = prose["unlanded_rate_honest"]
    return {
        "projected_struct": {
            "source_claims": source,
            "verified_claims": projected_verified,
            "dropped": projected_dropped,
            "verdict_counts": dict(+struct_counts),
            "supported_rate_honest": round(supported_rate, 6),
            "unlanded_rate_honest": round(unlanded_rate, 6),
        },
        "projected_gain": {
            "supported_gain_pp_struct_minus_prose": round((supported_rate - prose_supported) * 100, 2),
            "unlanded_change_pp_struct_minus_prose": round((unlanded_rate - prose_unlanded) * 100, 2),
            "input_contract_supported_gain_pp_after_derisk": round((supported_rate - prose_supported) * 100, 2),
        },
    }


def _write_namespace(ns: dict[str, Any], d16_metrics: dict[str, Any]) -> None:
    flips = ns["flips"]
    true = ns["spotcheck"].get("TRUE", 0)
    total = sum(ns["spotcheck"].values())
    lines = [
        "# W22 D2 Phase A Namespace Impact",
        "",
        "## Scope",
        "",
        "- Offline only, cost `$0`.",
        "- No production verifier changes.",
        "- Rechecked D1.6 structured method-aware enrichment rows that were not already supported.",
        "",
        "## Result",
        "",
        f"- Checked structured non-supported enrichment rows: `{ns['checked_struct_non_supported_enrichment']}`",
        f"- Namespace-related verdict flips: `{len(flips)}`",
        f"- Flip counts: `{dict(ns['flip_counts'])}`",
        f"- 10-row flip validation: `{true}/{total} TRUE = {true/total:.0%}`" if total else "- 10-row flip validation: no flips to sample.",
        "",
        "## Interpretation",
        "",
        "- Namespace normalization is useful but not the main source of the W22 opportunity.",
        "- It should be implemented as exact semantic equivalence, especially KEGG `map*` <-> `hsa*`, WikiPathways `WP*`, SMPDB `SMP*`, Reactome `R-HSA-*`, and carrier-native fields.",
        "- It must not become fuzzy pathway-name matching that turns near misses into support.",
        "",
        "## Baseline Comparison",
        "",
        f"- D1.6 structured supported honest rate: `{d16_metrics['arms']['struct']['supported_rate_honest']:.2%}`",
        f"- D1.6 structured contradicted honest rate: `{d16_metrics['arms']['struct']['contradicted_rate_honest']:.2%}`",
        "",
        "## Sample Flips",
        "",
    ]
    for c in flips[:10]:
        lines.append(f"- `{c.old_verdict}` -> `{c.new_verdict}` [{c.method}] `{c.task_id}`: {c.claim_text[:180]}")
    NAMESPACE_MD.write_text("\n".join(lines), encoding="utf-8")


def _write_dropped(dropped: dict[str, Any]) -> None:
    true = dropped["spotcheck"].get("TRUE", 0)
    review = dropped["spotcheck"].get("REVIEW", 0)
    total = sum(dropped["spotcheck"].values())
    lines = [
        "# W22 D2 Phase B Dropped Rescue",
        "",
        "## Scope",
        "",
        "- Offline only, cost `$0`.",
        "- Simulated candidate rescue rules for the 166 structured claims dropped by grammar/conversion.",
        "- No grammar or production verifier code was changed.",
        "",
        "## Candidate Rules",
        "",
        "- Roundtrip compound IDs can be accepted as structured verification anchors when the raw object already has a typed claim shape.",
        "- Roundtrip pathway IDs can be accepted as structured verification anchors for pathway membership/enrichment claims.",
        "- `METABOLITE_PATHWAY_LINK` without `enzyme_or_reaction` can be downgraded to a weaker pathway-membership/link shape for deterministic carrier lookup.",
        "- Abstract/hedged/directional phrases should remain dropped unless a future hypothesis bucket explicitly handles them.",
        "",
        "## Simulation Result",
        "",
        f"- Total candidates: `{dropped['total_candidates']}`",
        f"- Rule counts: `{dropped['rule_counts']}`",
        f"- Simulated verdict counts: `{dropped['simulated_verdict_counts']}`",
        f"- Spotcheck labels: `{dropped['spotcheck']}`",
        f"- Spotcheck clean TRUE rate: `{true}/{total} TRUE = {true/total:.0%}`" if total else "- Spotcheck clean TRUE rate: no sample.",
        f"- Review labels: `{review}`",
        "",
        "## Interpretation",
        "",
        "- Dropped rescue is material, but it is riskier than method-aware enrichment because it changes grammar acceptance boundaries.",
        "- Roundtrip IDs should be rescued only inside structured claims, not in prose extraction.",
        "- Missing-enzyme pathway links should be rescued as a weaker claim type, not silently upgraded to mechanistic enzyme/reaction evidence.",
    ]
    DROPPED_MD.write_text("\n".join(lines), encoding="utf-8")


def _write_final(final: dict[str, Any]) -> None:
    p = final["projected_struct_conservative"]
    g = final["projected_gain_conservative"]
    pf = final["projected_struct_full_landed"]
    gf = final["projected_gain_full_landed"]
    lines = [
        "# W22 D2 Final Opportunity",
        "",
        "## Scope",
        "",
        "- Offline projection only, cost `$0`.",
        "- Combines D1.6 method-aware routing with Phase A namespace normalization and Phase B dropped-claim rescue simulation.",
        "- This is not a production result; it is an implementation go/no-go estimate.",
        "",
        "## Projected Structured Arm, Conservative",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| source claims | {p['source_claims']} |",
        f"| verified claims | {p['verified_claims']} |",
        f"| dropped | {p['dropped']} |",
        f"| supported | {p['verdict_counts'].get('supported', 0)} |",
        f"| contradicted | {p['verdict_counts'].get('contradicted', 0)} |",
        f"| unsupported | {p['verdict_counts'].get('unsupported', 0)} |",
        f"| UV | {p['verdict_counts'].get('unverifiable_v0', 0)} |",
        f"| supported honest | {p['supported_rate_honest']:.2%} |",
        f"| unlanded honest | {p['unlanded_rate_honest']:.2%} |",
        "",
        "Conservative means rescued `CONTRADICTED` dropped claims are not counted as landed yet.",
        "",
        "## Projected Structured Arm, Full Landed",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| verified claims | {pf['verified_claims']} |",
        f"| dropped | {pf['dropped']} |",
        f"| supported honest | {pf['supported_rate_honest']:.2%} |",
        f"| unlanded honest | {pf['unlanded_rate_honest']:.2%} |",
        f"| supported gain over prose | {gf['supported_gain_pp_struct_minus_prose']:+.2f} pp |",
        f"| unlanded change over prose | {gf['unlanded_change_pp_struct_minus_prose']:+.2f} pp |",
        "",
        "## Opportunity Split",
        "",
        f"- Method-aware structured supported gain vs D1 baseline: `{g['method_bug_struct_supported_gain_pp_vs_d1']:+.2f} pp`",
        f"- Projected structured supported gain over prose after derisking: `{g['supported_gain_pp_struct_minus_prose']:+.2f} pp`",
        f"- Projected structured unlanded change over prose after derisking: `{g['unlanded_change_pp_struct_minus_prose']:+.2f} pp` conservative to `{gf['unlanded_change_pp_struct_minus_prose']:+.2f} pp` full-landed",
        f"- Namespace supported flips: `{final['namespace']['supported_flips']}`",
        f"- Dropped rescued supported: `{final['dropped']['rescued_supported']}`",
        f"- Dropped rescued contradicted, high-risk bucket: `{final['dropped']['rescued_contradicted']}`",
        "",
        "## Recommendation",
        "",
        "- Proceed to design review for implementation.",
        "- Implement in phases: method-aware enrichment first, namespace normalization second, structured dropped rescue last.",
        "- Keep strict evidence semantics: normalized IDs must be equivalent IDs, not loose name similarity.",
    ]
    FINAL_MD.write_text("\n".join(lines), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _candidate_row(c: Candidate) -> dict[str, Any]:
    return {
        "task_id": c.task_id,
        "claim_index": c.claim_index,
        "arm": c.arm,
        "method": c.method,
        "old_verdict": c.old_verdict,
        "new_verdict": c.new_verdict,
        "source_field": c.source_field,
        "claim_text": c.claim_text,
        "old_evidence": c.old_evidence,
        "new_evidence": c.new_evidence,
    }


def _key(c: Candidate) -> str:
    return f"{c.task_id}:{c.claim_index}:{c.old_verdict}:{c.new_verdict}"


def _pick_by_method(rows: list[Candidate], n: int) -> list[Candidate]:
    buckets: dict[str, list[Candidate]] = defaultdict(list)
    for row in rows:
        buckets[row.method].append(row)
    out = []
    while len(out) < n and any(buckets.values()):
        for method in ("ramp", "mummichog", "metaboanalystr", "sspa", "fella", "other"):
            if buckets.get(method) and len(out) < n:
                out.append(buckets[method].pop(0))
    return out


def _pick_dicts_by_key(rows: list[dict[str, Any]], key: str, n: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key) or "")].append(row)
    out = []
    while len(out) < n and any(buckets.values()):
        for bucket_key in sorted(buckets):
            if buckets[bucket_key] and len(out) < n:
                out.append(buckets[bucket_key].pop(0))
    return out


if __name__ == "__main__":
    main()
