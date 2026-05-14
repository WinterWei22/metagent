"""Real-data smoke test for Sub-6 verifier layers.

Covers the gaps left by the unit + integration tests:
  - Layer 6b: load real curated_hmdb_mammalian.jsonl (150 records)
              instead of injecting synthetic lookup
  - Layer 6d: query real RaMP-DB (~3.7M analytehaspathway rows)
              instead of the in-memory 12-row fixture
  - Layer 6c (biological_sub6): had no unit tests; smoke it here
  - All four layers: drive against the real first 3 sub6b tasks (not
    just the first one)

Run:
    METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \\
      conda run -n metagent-llm python scripts/spike/sub6_real_data_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.sub6_report import SubsixSourceReport  # noqa: E402
from verifier.layers.biological_sub6 import verify_biological_sub6  # noqa: E402
from verifier.layers.driver_metabolite import (  # noqa: E402
    _get_default_lookup,
    reset_lookup_cache,
    verify_driver_metabolite,
)
from verifier.layers.pathway_relationship import (  # noqa: E402
    verify_pathway_relationship,
)
from verifier.layers.set_enrichment import verify_set_enrichment  # noqa: E402
from verifier.schemas import (  # noqa: E402
    ClaimExtractedFields,
    ClaimType,
    ClassifiedClaim,
)


JSONL = ROOT / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks.jsonl"
CURATED = ROOT / "data" / "benchmark" / "sub6" / "curated_hmdb_mammalian.jsonl"


def _claim(text: str, ct: ClaimType, **fields) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        claim_type=ct,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(**fields),
    )


def load_tasks(n: int = 3) -> list[SubsixSourceReport]:
    out: list[SubsixSourceReport] = []
    with JSONL.open() as f:
        for i, line in enumerate(f):
            if i >= n:
                break
            r = json.loads(line)
            out.append(
                SubsixSourceReport(
                    task_id=r["task_id"],
                    task_type=r["task_type"],
                    domain=r.get("domain", "mammalian"),
                    ground_truth_pathway=r["ground_truth_pathway"],
                    ground_truth_signal_compounds=r["ground_truth_signal_compounds"],
                    ground_truth_noise_compounds=r["ground_truth_noise_compounds"],
                    ramp_enrichment_result=r["ramp_enrichment_result"],
                    differential_metabolites=r.get("differential_metabolites"),
                )
            )
    return out


def smoke_set_enrichment(tasks: list[SubsixSourceReport]) -> dict:
    print("\n" + "=" * 60)
    print("Layer 6a (set_enrichment) — real Sub-6B tasks")
    print("=" * 60)
    results = []
    for task in tasks:
        gt_name = task.ground_truth_pathway["pathway_name"]

        # Case 1: claim names the canonical top-1 pathway (should SUPPORT)
        claim_correct = _claim(
            f"These differential metabolites are enriched in {gt_name}.",
            ClaimType.SET_ENRICHMENT,
        )
        r1 = verify_set_enrichment(claim_correct, task)

        # Case 2: claim names a pathway that's nowhere in top_pathways (CONTRADICT)
        claim_wrong = _claim(
            "These metabolites are enriched in Caffeine biosynthesis pathway.",
            ClaimType.SET_ENRICHMENT,
        )
        r2 = verify_set_enrichment(claim_wrong, task)

        print(f"\n  task: {task.task_id}")
        print(f"  GT pathway: {gt_name}")
        print(f"  correct-name claim     → {r1.verdict.value}  rank={r1.enrichment_context.best_match.rank if r1.enrichment_context.best_match else None}")
        print(f"  fake-pathway claim     → {r2.verdict.value}")
        results.append((r1.verdict.value, r2.verdict.value))
    return {"set_enrichment": results}


def smoke_driver_metabolite(tasks: list[SubsixSourceReport]) -> dict:
    print("\n" + "=" * 60)
    print("Layer 6b (driver_metabolite) — load real curated_hmdb_mammalian.jsonl")
    print("=" * 60)
    reset_lookup_cache()
    t0 = time.perf_counter()
    lookup = _get_default_lookup()
    dt = time.perf_counter() - t0
    print(f"  loaded {len(lookup)} keys from {CURATED.name} in {dt*1000:.1f} ms")
    if not lookup:
        return {"driver_metabolite": "lookup_load_failed"}

    results = []
    for task in tasks:
        # Build a claim that names two real signal compounds via KEGG ID.
        # (Driver-name regex would also pick these up via word-bounded match.)
        sigs = task.ground_truth_signal_compounds[:2]
        if len(sigs) < 2:
            continue
        claim_correct = _claim(
            f"The enrichment is primarily driven by {sigs[0]} and {sigs[1]}.",
            ClaimType.DRIVER_METABOLITE,
        )
        r1 = verify_driver_metabolite(claim_correct, task, lookup=lookup)

        # Build a claim that includes a noise compound (when present).
        noise = task.ground_truth_noise_compounds[:1]
        r2 = None
        if noise:
            claim_with_noise = _claim(
                f"Key drivers of this enrichment are {sigs[0]} and {noise[0]}.",
                ClaimType.DRIVER_METABOLITE,
            )
            r2 = verify_driver_metabolite(
                claim_with_noise, task, lookup=lookup,
            )

        print(f"\n  task: {task.task_id}")
        print(f"  signal-only claim ({sigs}) → {r1.verdict.value}")
        if r1.enrichment_context:
            print(
                f"    matched_signal={r1.enrichment_context.matched_signal_drivers} "
                f"unresolved={r1.enrichment_context.unresolved_drivers} "
                f"P={r1.enrichment_context.driver_precision} "
                f"R={r1.enrichment_context.driver_recall}"
            )
        if r2:
            print(f"  signal+noise claim ({sigs[0]}, {noise[0]}) → {r2.verdict.value}")
            if r2.enrichment_context:
                print(
                    f"    matched_noise={r2.enrichment_context.matched_noise_drivers}"
                )
        results.append((r1.verdict.value, r2.verdict.value if r2 else None))
    return {"driver_metabolite": results, "lookup_size": len(lookup)}


def smoke_pathway_relationship(tasks: list[SubsixSourceReport]) -> dict:
    print("\n" + "=" * 60)
    print("Layer 6d (pathway_relationship) — real RaMP-DB")
    print("=" * 60)
    db = os.environ.get("METAGENT_RAMP_PATH")
    if not db:
        print("  METAGENT_RAMP_PATH unset; skipping")
        return {"pathway_relationship": "skipped_no_ramp"}

    results = []
    for task in tasks:
        gt_name = task.ground_truth_pathway["pathway_name"]
        # Pick a runner-up pathway from top_pathways[1] for a related-pathway claim.
        runner_up = (
            task.ramp_enrichment_result.get("top_pathways", [{}, {}])[1]
            .get("pathway_name", "Glycolysis")
        )

        # shared_intermediates between top-1 and top-2 — usually SUPPORTED
        # because top-2 in real Sub-6 tasks is often a related pathway.
        c1 = _claim(
            f"{gt_name} and {runner_up} share several intermediates.",
            ClaimType.PATHWAY_RELATIONSHIP,
        )
        t0 = time.perf_counter()
        r1 = verify_pathway_relationship(c1, task, db_path=db)
        dt1 = time.perf_counter() - t0

        # upstream claim — RaMP has no hierarchy → UNVERIFIABLE_V0
        c2 = _claim(
            f"{gt_name} is upstream of {runner_up}.",
            ClaimType.PATHWAY_RELATIONSHIP,
        )
        r2 = verify_pathway_relationship(c2, task, db_path=db)

        print(f"\n  task: {task.task_id}")
        print(f"  pathway_a: {gt_name}")
        print(f"  pathway_b: {runner_up}")
        print(f"  shared-intermediates claim → {r1.verdict.value} ({dt1*1000:.0f} ms)")
        if r1.enrichment_context:
            print(
                f"    pathway_a_id={r1.enrichment_context.pathway_a_id} "
                f"pathway_b_id={r1.enrichment_context.pathway_b_id} "
                f"shared_count={r1.enrichment_context.shared_compound_count}"
            )
        print(f"  upstream claim → {r2.verdict.value} (hierarchy_available={r2.enrichment_context.hierarchy_data_available})")
        results.append((r1.verdict.value, r2.verdict.value))
    return {"pathway_relationship": results}


def smoke_biological_sub6(tasks: list[SubsixSourceReport]) -> dict:
    print("\n" + "=" * 60)
    print("Layer 6c (biological_sub6) — real Sub-6B tasks")
    print("=" * 60)
    db = os.environ.get("METAGENT_RAMP_PATH")
    results = []
    for task in tasks:
        gt_name = task.ground_truth_pathway["pathway_name"]

        # Case 1: pathway membership (canonical pathway name → SUPPORTED)
        c1 = _claim(
            f"{gt_name} plays a role in mammalian metabolism.",
            ClaimType.BIOLOGICAL,
        )
        r1 = verify_biological_sub6(c1, task, db_path=db)

        # Case 2: disease keyword → UNVERIFIABLE_V0 (declared limitation)
        c2 = _claim(
            f"{gt_name} is dysregulated in metabolic disease.",
            ClaimType.BIOLOGICAL,
        )
        r2 = verify_biological_sub6(c2, task, db_path=db)

        # Case 3: unrelated pathway → UNSUPPORTED
        c3 = _claim(
            "Caffeine biosynthesis pathway is involved in this signal.",
            ClaimType.BIOLOGICAL,
        )
        r3 = verify_biological_sub6(c3, task, db_path=db)

        print(f"\n  task: {task.task_id}")
        print(f"  GT pathway: {gt_name}")
        print(f"  membership claim   → {r1.verdict.value} (layer={r1.verifier_layer})")
        print(f"  disease claim      → {r2.verdict.value}")
        print(f"  unrelated claim    → {r3.verdict.value}")
        results.append((r1.verdict.value, r2.verdict.value, r3.verdict.value))
    return {"biological_sub6": results}


def main() -> None:
    if not JSONL.exists():
        print(f"FATAL: Sub-6B jsonl missing: {JSONL}", file=sys.stderr)
        sys.exit(1)

    tasks = load_tasks(n=3)
    print(f"Loaded {len(tasks)} real Sub-6B tasks for smoke test")
    for t in tasks:
        print(f"  {t.task_id}  → ground-truth: {t.ground_truth_pathway['pathway_name']}")

    summary: dict = {}
    summary.update(smoke_set_enrichment(tasks))
    summary.update(smoke_driver_metabolite(tasks))
    summary.update(smoke_pathway_relationship(tasks))
    summary.update(smoke_biological_sub6(tasks))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
