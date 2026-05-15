"""Run verifier.agent.verify_sub6 on a narratives JSONL.

For each narrative produced by ``run_sub6{a,b}_batch``, build a
``SubsixSourceReport`` from the matching task record and call
``verify_sub6``. Emit one JSONL line per task with the verdict
breakdown (verdicts by claim type, totals, layer 6d shared-compound
counts when available, etc.).

The driver_lookup is pre-loaded from the curated pool once and threaded
into ``verify_sub6`` so layer 6b doesn't reload per claim (eval guide
hand-off note from the verifier delivery report).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.compound_lookup import CompoundLookup
from evaluation.sub6.io_utils import append_jsonl, load_completed_task_ids


def _build_driver_lookup(curated_path: Path) -> dict[str, str]:
    """Build the keyed lookup expected by verifier.layers.driver_metabolite.

    Layer 6b expects keys to include compound names (lowercased), KEGG
    IDs, HMDB IDs, and InChIKey first-blocks; values are InChIKey
    first-blocks. We mirror what the layer's default loader builds.
    """
    out: dict[str, str] = {}
    with curated_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            ik = r.get("inchikey_first_block")
            if not ik:
                continue
            for key in (
                r.get("name"),
                r.get("kegg_id"),
                r.get("hmdb_id"),
                ik,
            ):
                if key:
                    out[str(key).strip().lower()] = ik
    return out


def _build_source_report(task: dict):
    """Construct a SubsixSourceReport from one task JSONL record."""
    from schemas.sub6_report import SubsixSourceReport

    return SubsixSourceReport(
        task_id=task["task_id"],
        task_type=task["task_type"],
        domain=task.get("domain", "mammalian"),
        ground_truth_pathway=task["ground_truth_pathway"],
        ground_truth_signal_compounds=task["ground_truth_signal_compounds"],
        ground_truth_noise_compounds=task["ground_truth_noise_compounds"],
        ramp_enrichment_result=task["ramp_enrichment_result"],
        differential_metabolites=task.get("differential_metabolites"),
        differential_spectra=task.get("differential_spectra"),
    )


def _summarise_verdicts(verified_claims) -> dict:
    """Per-claim-type Counter of verdicts. Verdicts are pydantic enums."""
    by_type: dict[str, Counter] = {}
    by_subtype: dict[str, Counter] = {}
    total: Counter = Counter()
    for c in verified_claims:
        v = getattr(c.verdict, "value", str(c.verdict))
        ct = getattr(c.claim_type, "value", str(c.claim_type))
        st = getattr(getattr(c, "claim_subtype", None), "value", None) or "_"
        by_type.setdefault(ct, Counter())[v] += 1
        by_subtype.setdefault(f"{ct}.{st}", Counter())[v] += 1
        total[v] += 1
    return {
        "verdicts_total": dict(total),
        "verdicts_by_type": {k: dict(v) for k, v in by_type.items()},
        "verdicts_by_subtype": {k: dict(v) for k, v in by_subtype.items()},
    }


def _claim_to_dict(c) -> dict:
    """Best-effort serialisation of a VerifiedClaim — pydantic where
    possible, fall back to attribute reading."""
    try:
        return c.model_dump(mode="json")
    except Exception:
        d = {
            "claim_text": getattr(c, "claim_text", None),
            "claim_type": getattr(getattr(c, "claim_type", None), "value", None),
            "verdict": getattr(getattr(c, "verdict", None), "value", None),
            "correction": getattr(c, "correction", None),
        }
        return d


def grade_narrative_file(
    narratives_path: Path,
    tasks_path: Path,
    out_path: Path,
    *,
    curated_path: Path,
    track: str,
    ramp_db_path: str | None,
) -> list[dict]:
    """Grade every narrative in ``narratives_path`` against the matching
    task in ``tasks_path``. Idempotent — completed task_ids in
    ``out_path`` are skipped.
    """
    from verifier.agent import verify_sub6

    tasks_by_id = {}
    with tasks_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                t = json.loads(line)
                tasks_by_id[t["task_id"]] = t

    driver_lookup = _build_driver_lookup(curated_path)
    logging.getLogger(__name__).info(
        "loaded %d driver-lookup keys from %s", len(driver_lookup), curated_path
    )

    completed = load_completed_task_ids(out_path)

    results: list[dict] = []
    with narratives_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            tid = rec["task_id"]
            if tid in completed:
                continue
            narrative = rec.get("narrative") or ""
            if not narrative:
                logging.getLogger(__name__).warning(
                    "skipping %s — empty narrative", tid
                )
                continue
            task = tasks_by_id.get(tid)
            if task is None:
                logging.getLogger(__name__).warning(
                    "no task found for %s — skipping", tid
                )
                continue
            source_report = _build_source_report(task)
            t0 = time.perf_counter()
            try:
                ver = verify_sub6(
                    narrative,
                    source_report,
                    trace_id=f"{track}.{tid}",
                    ramp_db_path=ramp_db_path,
                    driver_lookup=driver_lookup,
                )
                err = None
                claims = list(getattr(ver, "claims_v1", []) or [])
                summary = _summarise_verdicts(claims)
                claim_dicts = [_claim_to_dict(c) for c in claims]
                warnings = list(getattr(ver, "warnings", []) or [])
                llm_calls = getattr(ver, "llm_calls", None)
                # Phase B1 D4: surface task_outcome + dropped count to the
                # JSONL so the aggregator can bucket per-outcome and so
                # the audit trail records what the LLM emitted.
                task_outcome_val = getattr(
                    getattr(ver, "task_outcome", None), "value", "normal"
                )
                dropped_count = len(getattr(ver, "dropped_claims", []) or [])
            except Exception as exc:
                logging.getLogger(__name__).exception(
                    "verify_sub6 crashed on %s", tid
                )
                err = f"{type(exc).__name__}: {exc}"
                summary = {}
                claim_dicts = []
                warnings = []
                llm_calls = None
                task_outcome_val = "empty_system_failure"
                dropped_count = 0
            elapsed = time.perf_counter() - t0
            out_rec = {
                "task_id": tid,
                "track": track,
                "elapsed_seconds": elapsed,
                "verifier_llm_calls": llm_calls,
                "warnings": warnings,
                "error": err,
                "task_outcome": task_outcome_val,
                "dropped_by_grammar": dropped_count,
                **summary,
                "claims": claim_dicts,
            }
            append_jsonl(out_path, out_rec)
            results.append(out_rec)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--narratives",
        required=True,
        help="JSONL produced by run_sub6{a,b}_batch (column: task_id, narrative)",
    )
    p.add_argument(
        "--tasks",
        required=True,
        help="Source tasks JSONL — used to build SubsixSourceReport",
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output JSONL — per-task verifier verdicts and claim list",
    )
    p.add_argument(
        "--curated",
        default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl",
    )
    p.add_argument("--track", default="sub6", help="Trace-id prefix")
    p.add_argument(
        "--ramp-db",
        default=os.environ.get(
            "METAGENT_RAMP_PATH",
            "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
        ),
        help="Path to RaMP-DB sqlite (used by layer 6d). None to skip 6d.",
    )
    p.add_argument(
        "--no-ramp",
        action="store_true",
        help="Skip Layer 6d (pathway_relationship); useful when RaMP unavailable",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Load API key for Stage 1/2 extract+classify LLM calls.
    if not os.environ.get("MINIMAX_API_KEY"):
        keyfile = Path(_REPO_ROOT) / "api_key.txt"
        if keyfile.is_file():
            os.environ["MINIMAX_API_KEY"] = keyfile.read_text().strip()
    if not os.environ.get("MINIMAX_API_KEY"):
        sys.stderr.write("ERROR: MINIMAX_API_KEY not set and api_key.txt not found.\n")
        return 2

    ramp = None if args.no_ramp else args.ramp_db
    if ramp and not Path(ramp).is_file():
        print(
            f"WARN: RaMP-DB not found at {ramp}; Layer 6d will downgrade "
            f"to UNVERIFIABLE_V0 for all pathway_relationship claims",
            file=sys.stderr,
        )
        ramp = None

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results = grade_narrative_file(
        narratives_path=Path(args.narratives),
        tasks_path=Path(args.tasks),
        out_path=out_path,
        curated_path=Path(args.curated),
        track=args.track,
        ramp_db_path=ramp,
    )

    print(f"Graded {len(results)} narratives → {out_path}")
    if results:
        # Pretty summary aggregating verdict totals.
        total: Counter = Counter()
        for r in results:
            for v, n in (r.get("verdicts_total") or {}).items():
                total[v] += n
        print("Aggregate verdict totals:")
        for v, n in total.most_common():
            print(f"  {v:>20}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
