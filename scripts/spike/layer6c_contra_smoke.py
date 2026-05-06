"""3-narrative smoke for the layer 6c contra path.

Picks three Sub-6B v6 records that we know contain biological_claim
verdicts that *should* be CONTRADICTED, replays each affected claim
through the patched ``verify_biological_sub6``, and prints
before/after verdicts so reviewers can confirm the contra path is
firing on real data without regressions.

Usage:
    METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \\
      conda run -n metagent-llm python scripts/spike/layer6c_contra_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.biological_sub6 import verify_biological_sub6
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimType,
    ClassifiedClaim,
)


JSONL = ROOT / "data" / "eval" / "sub6" / "sub6b_verdicts_v6_opus47_aliases.jsonl"

# Candidate (task_id_substr, claim_text_substr) tuples — picked from the
# first-action checklist categorisation as A-class candidates.
TARGETS = [
    # Pantothenic acid (B5, n_known=63) is NOT in mevalonate pathway —
    # RaMP places it in CoA biosynthesis instead. Strong contra signal.
    (
        "RAMP_P_000000402_seed0",
        "Pantothenic acid links to the mevalonate pathway",
    ),
    # Acrolein (n_known=15) is in cyclophosphamide / cancer-action
    # pathways per RaMP, NOT in oxidative-stress / lipid-peroxidation
    # pathway as the LLM claimed.
    (
        "RAMP_P_000053157_seed5",
        "Acrolein is associated with the lipid peroxidation/oxidative stress pathway",
    ),
    # Glycineamideribotide (GAR, n_known=23) is in purine biosynthesis
    # (adenine / AICA pathways) per RaMP — NOT in any pathway named
    # "nucleotide metabolism" (RaMP does not aggregate at that level).
    (
        "RAMP_P_000053157_seed2",
        "Glycineamideribotide points to disrupted one-carbon/nucleotide metabolism",
    ),
]


def find_target(records: list[dict], task_substr: str, text_substr: str):
    for r in records:
        if task_substr not in r["task_id"]:
            continue
        for c in r.get("claims", []):
            if (c.get("claim_type") or "").lower() != "biological_claim":
                continue
            if (c.get("verdict") or "").lower() != "unsupported":
                continue
            if text_substr.lower() not in (c.get("claim_text") or "").lower():
                continue
            return r, c
    return None, None


def claim_from_record(c: dict) -> ClassifiedClaim:
    fields = c.get("extracted_fields") or {}
    return ClassifiedClaim(
        claim_text=c["claim_text"],
        subject=c.get("subject"),
        claim_type=ClaimType.BIOLOGICAL,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(**{
            k: v for k, v in fields.items()
            if k in ClaimExtractedFields.model_fields
        }),
    )


def task_from_record(r: dict) -> SubsixSourceReport:
    """Reconstruct a minimal SubsixSourceReport from a verdict record.

    The verdict records don't carry the full task data, so we rebuild
    enough of it from the original task jsonl.
    """
    task_jsonl = ROOT / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks.jsonl"
    with task_jsonl.open() as f:
        for line in f:
            t = json.loads(line)
            if t["task_id"] == r["task_id"]:
                return SubsixSourceReport(
                    task_id=t["task_id"],
                    task_type=t["task_type"],
                    domain=t.get("domain", "mammalian"),
                    ground_truth_pathway=t["ground_truth_pathway"],
                    ground_truth_signal_compounds=t["ground_truth_signal_compounds"],
                    ground_truth_noise_compounds=t["ground_truth_noise_compounds"],
                    ramp_enrichment_result=t["ramp_enrichment_result"],
                )
    raise RuntimeError(f"Task {r['task_id']} not found in source jsonl")


def main() -> int:
    if not JSONL.exists():
        print(f"FATAL: {JSONL} not found", file=sys.stderr)
        return 2

    records = [json.loads(line) for line in JSONL.open()]

    print(f"Replaying {len(TARGETS)} biological_claim targets through patched layer 6c")
    print("=" * 72)

    flips = Counter()
    examples_for_report: list[dict] = []

    for i, (task_substr, text_substr) in enumerate(TARGETS, 1):
        rec, claim_dict = find_target(records, task_substr, text_substr)
        if rec is None:
            print(f"[{i}] target not found: {task_substr!r} / {text_substr!r}")
            continue

        v6_verdict = (claim_dict.get("verdict") or "").lower()
        v6_evidence = (claim_dict.get("evidence") or "")[:160]
        task = task_from_record(rec)
        cl = claim_from_record(claim_dict)
        result = verify_biological_sub6(cl, task)

        new_verdict = result.verdict.value.lower()
        flips[(v6_verdict, new_verdict)] += 1

        print(f"\n[{i}] task: {rec['task_id']}")
        print(f"    claim: {cl.claim_text}")
        print(f"    subject: {cl.subject!r}")
        print(f"    v6 verdict: {v6_verdict.upper()}")
        print(f"    v6 evidence: {v6_evidence}…")
        print(f"    v7 verdict: {new_verdict.upper()}")
        print(f"    v7 evidence: {(result.evidence or '')[:200]}")
        if result.correction:
            print(f"    v7 correction: {result.correction}")
        te = (result.enrichment_context.tool_evidence
              if result.enrichment_context else None)
        if te:
            print(f"    v7 tool_evidence: "
                  f"check={te.get('membership_check')} "
                  f"n_known={te.get('n_pathways_known')} "
                  f"compound={te.get('kegg_compound_id')} "
                  f"top3={te.get('top_actual_pathways')}")
        examples_for_report.append({
            "task_id": rec["task_id"],
            "claim_text": cl.claim_text,
            "v6_verdict": v6_verdict,
            "v7_verdict": new_verdict,
            "v7_correction": result.correction,
            "v7_evidence": result.evidence,
            "v7_tool_evidence": te,
        })

    print("\n" + "=" * 72)
    print("FLIP SUMMARY")
    print("=" * 72)
    for (v6, v7), n in flips.most_common():
        marker = "✅" if v6 != v7 else "·"
        print(f"  {marker} {v6} → {v7}: {n}")

    out = ROOT / "reports" / "verifier" / "_layer6c_smoke_examples.json"
    out.write_text(json.dumps(examples_for_report, indent=2))
    print(f"\nFlip examples saved to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
