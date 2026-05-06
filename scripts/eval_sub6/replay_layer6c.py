"""Replay v6 verdict files through the patched layer 6c only.

Brief acceptance: "Per-claim-type verdict roll-up — full breakdown ...
showing only biological_claim row changed." This script implements
that exact contract by re-dispatching only ``biological_claim`` rows
through ``verify_biological_sub6`` and keeping every other claim row
verbatim from v6.

Why not run the full ``verify_sub6`` pipeline? The v6 narratives have
already been Stage-1 extracted and Stage-2 classified by
claude-opus-4-7. Re-running those stages would (a) cost ~25 min of
wall time, (b) introduce LLM nondeterminism, (c) require a working
viviai token. Replay isolates the layer-only change cleanly.

Usage:
    METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \\
      conda run -n metagent-llm python scripts/eval_sub6/replay_layer6c.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.biological_sub6 import verify_biological_sub6
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClassifiedClaim,
    SubjectKind,
)


SUB6B_TASKS = ROOT / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks.jsonl"
SUB6A_TASKS = ROOT / "data" / "benchmark" / "sub6" / "sub6a_e2e_tasks.jsonl"

PAIRS = [
    (
        "data/eval/sub6/sub6b_verdicts_v6_opus47_aliases.jsonl",
        "data/eval/sub6/sub6b_verdicts_v7_contra.jsonl",
        SUB6B_TASKS,
        "sub6b",
    ),
    (
        "data/eval/sub6/sub6a_perfect_id_verdicts_v6_opus47_aliases.jsonl",
        "data/eval/sub6/sub6a_perfect_id_verdicts_v7_contra.jsonl",
        SUB6A_TASKS,
        "sub6a_perfect",
    ),
    (
        "data/eval/sub6/sub6a_real_id_verdicts_v6_opus47_aliases.jsonl",
        "data/eval/sub6/sub6a_real_id_verdicts_v7_contra.jsonl",
        SUB6A_TASKS,
        "sub6a_real",
    ),
]


def load_tasks(path: Path) -> dict[str, SubsixSourceReport]:
    out: dict[str, SubsixSourceReport] = {}
    with path.open() as f:
        for line in f:
            t = json.loads(line)
            out[t["task_id"]] = SubsixSourceReport(
                task_id=t["task_id"],
                task_type=t["task_type"],
                domain=t.get("domain", "mammalian"),
                ground_truth_pathway=t["ground_truth_pathway"],
                ground_truth_signal_compounds=t["ground_truth_signal_compounds"],
                ground_truth_noise_compounds=t["ground_truth_noise_compounds"],
                ramp_enrichment_result=t["ramp_enrichment_result"],
                differential_metabolites=t.get("differential_metabolites"),
                differential_spectra=t.get("differential_spectra"),
            )
    return out


def reclassify_claim(c: dict) -> ClassifiedClaim:
    """Rebuild a frozen ClassifiedClaim from a v6 verdict dict.

    Only the fields that ``verify_biological_sub6`` reads are required;
    others use defaults.
    """
    fields = c.get("extracted_fields") or {}
    valid_field_keys = ClaimExtractedFields.model_fields.keys()
    cleaned = {k: v for k, v in fields.items() if k in valid_field_keys}
    try:
        ef = ClaimExtractedFields(**cleaned)
    except Exception:
        ef = ClaimExtractedFields()
    return ClassifiedClaim(
        claim_id=c.get("claim_id"),
        claim_text=c.get("claim_text") or "",
        normalized_text=None,
        subject=c.get("subject"),
        claim_type=ClaimType(c.get("claim_type") or "biological_claim"),
        classifier_source="rule",
        peak_mz=None,
        neutral_loss=None,
        claim_subtype=_safe_subtype(c.get("claim_subtype")),
        subject_kind=_safe_subjectkind(c.get("subject_kind")),
        candidate_ref=None,
        extracted_fields=ef,
    )


def _safe_subtype(v) -> ClaimSubtype:
    try:
        return ClaimSubtype(v) if v else ClaimSubtype.UNKNOWN
    except Exception:
        return ClaimSubtype.UNKNOWN


def _safe_subjectkind(v) -> SubjectKind:
    try:
        return SubjectKind(v) if v else SubjectKind.UNKNOWN
    except Exception:
        return SubjectKind.UNKNOWN


def replay_record(record: dict, tasks: dict[str, SubsixSourceReport]) -> dict:
    task = tasks.get(record["task_id"])
    if task is None:
        return record  # leave untouched if no matching task

    new_claims: list[dict] = []
    flip_count = 0
    for c in record.get("claims", []):
        if (c.get("claim_type") or "").lower() != "biological_claim":
            new_claims.append(c)
            continue
        cl = reclassify_claim(c)
        v = verify_biological_sub6(cl, task)
        new = v.model_dump(mode="json")
        # Carry the v6 claim_id forward if we lost it.
        if not new.get("claim_id") and c.get("claim_id"):
            new["claim_id"] = c["claim_id"]
        if (c.get("verdict") or "").lower() != (new.get("verdict") or "").lower():
            flip_count += 1
        new_claims.append(new)

    # Recompute aggregates.
    by_type: dict[str, dict[str, int]] = {}
    by_subtype: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for c in new_claims:
        ct = (c.get("claim_type") or "").lower()
        cs = (c.get("claim_subtype") or "").lower()
        v = (c.get("verdict") or "").lower()
        by_type.setdefault(ct, {})[v] = by_type.setdefault(ct, {}).get(v, 0) + 1
        by_subtype.setdefault(cs, {})[v] = by_subtype.setdefault(cs, {}).get(v, 0) + 1
        totals[v] = totals.get(v, 0) + 1

    out = dict(record)
    out["claims"] = new_claims
    out["verdicts_total"] = totals
    out["verdicts_by_type"] = by_type
    out["verdicts_by_subtype"] = by_subtype
    out["track"] = record.get("track", "") + "+layer6c_contra"
    out["replay_layer6c_flips"] = flip_count
    return out


def main() -> int:
    summary = []
    for v6_rel, v7_rel, tasks_path, label in PAIRS:
        v6_path = ROOT / v6_rel
        v7_path = ROOT / v7_rel
        if not v6_path.exists():
            print(f"  skip {label}: {v6_path} missing", file=sys.stderr)
            continue
        if not tasks_path.exists():
            print(f"  skip {label}: {tasks_path} missing", file=sys.stderr)
            continue
        tasks = load_tasks(tasks_path)
        v6_records = [json.loads(l) for l in v6_path.open()]
        v7_records = [replay_record(r, tasks) for r in v6_records]
        with v7_path.open("w") as f:
            for r in v7_records:
                f.write(json.dumps(r) + "\n")
        total_flips = sum(r.get("replay_layer6c_flips", 0) for r in v7_records)
        print(f"  {label:<14}  → {v7_path.name}  ({len(v7_records)} records, "
              f"{total_flips} biological_claim verdict flips)")
        summary.append((label, len(v7_records), total_flips))
    print("\nDone:")
    for label, n, flips in summary:
        print(f"  {label}: {n} records, {flips} flips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
