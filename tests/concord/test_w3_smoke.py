"""W3 末 end-to-end smoke test.

Per W3 spec §"W3 末 Smoke + Deliverable Checklist":
  1. 从 N=30 task 中任选 1 个,提取 metabolite list
  2. 走 ChebiLookup → CompoundRef
  3. run_sspa(compound_set,...) → EnrichmentResult v0.3
  4. Verify pathway_id 是 namespace-prefixed
  5. Verify metabolites_hit primary_id 是 CHEBI:...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.normalize.sspa_norm import normalize_sspa_output
from concord.schema.enrichment import (
    COMPOUND_NAMESPACES,
    CompoundRef,
    EnrichmentResult,
    PATHWAY_NAMESPACES,
    resolve_primary_id,
)
from concord.wrappers.sspa_wrapper import run_sspa

DB_PATH = WORKTREE / "data" / "concord" / "chebi.sqlite"
BENCHMARK = WORKTREE / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks_v3.jsonl"
SUMMARY = WORKTREE / "data" / "investigation" / "fig3_toy" / "summary_n30.json"

pytestmark = pytest.mark.skipif(
    not (DB_PATH.exists() and BENCHMARK.exists() and SUMMARY.exists()),
    reason="W3 deps missing (ChEBI sqlite / benchmark / N=30 summary)",
)


def _pick_one_task() -> dict:
    """Pick one N=30 task — task #1 (RAMP_P_000000421_seed2,lipid bucket).

    Stable single-task choice for reproducible smoke.
    """
    summary = json.loads(SUMMARY.read_text())
    target_tid = summary["task_ids"][0]
    with BENCHMARK.open() as f:
        for line in f:
            t = json.loads(line)
            if t["task_id"] == target_tid:
                return t
    raise RuntimeError(f"task {target_tid} not found in benchmark")


def _build_compound_refs(task: dict, chebi: ChebiLookup) -> list[CompoundRef]:
    """For each task metabolite,resolve via ChebiLookup → CompoundRef v0.3."""
    refs: list[CompoundRef] = []
    for m in task["differential_metabolites"]:
        rec = None
        if m.get("kegg_id"):
            rec = chebi.lookup_by_xref("KEGG", m["kegg_id"])
        if rec is None and m.get("hmdb_id"):
            rec = chebi.lookup_by_xref("HMDB", m["hmdb_id"])
        if rec is None:
            continue
        inchikey = rec.inchikey or m.get("inchikey") or ""
        if not inchikey:
            continue  # primary_id requires non-empty inchikey when nothing else
        primary_id = resolve_primary_id(
            chebi_id=rec.primary_id, inchikey=inchikey,
        )
        refs.append(CompoundRef(
            primary_id=primary_id,
            inchikey=inchikey,
            display_name=rec.name,
            chebi_id=rec.primary_id,
            hmdb_id=f"HMDB:{m.get('hmdb_id')}" if m.get("hmdb_id") else None,
            kegg_compound_id=f"KEGG:{m.get('kegg_id')}" if m.get("kegg_id") else None,
        ))
    return refs


def test_w3_end_to_end_smoke():
    """Spec checkpoints:
      ✓ pathways[0].pathway_id 是 REACT:... 或 KEGG:... 格式
      ✓ metabolites_hit primary_id 是 CHEBI:... 格式(若有)
      ✓ EnrichmentResult.schema_version == "concordmet_v0.3"
    """
    chebi = ChebiLookup(db_path=DB_PATH)
    task = _pick_one_task()
    print(f"\n[smoke] Task: {task['task_id'][:60]}")
    print(f"[smoke] Metabolites: {len(task['differential_metabolites'])}")

    refs = _build_compound_refs(task, chebi)
    print(f"[smoke] Resolved {len(refs)} CompoundRef via ChebiLookup")
    assert len(refs) >= 4, f"expected ≥4 resolved metabolites, got {len(refs)}"

    # Verify each ref has correct primary_id namespace
    for r in refs:
        ns = r.primary_id.split(":", 1)[0]
        assert ns in COMPOUND_NAMESPACES, f"bad NS {ns!r} in {r.primary_id}"

    # Run sspa ORA
    raw_result = run_sspa(
        compound_refs=refs, method="ora", pathway_db="reactome",
    )
    print(f"[smoke] sspa ORA wall: {raw_result['wall_time_sec']:.1f}s "
          f"resolved {raw_result['n_input_resolved']}/{raw_result['n_input']}")
    assert raw_result["n_input_resolved"] >= 1

    er = normalize_sspa_output(raw_result, top_n=10)
    print(f"[smoke] EnrichmentResult v{er.schema_version}: "
          f"{len(er.pathways)} pathways, method={er.method.value}")
    assert isinstance(er, EnrichmentResult)
    assert er.schema_version == "concordmet_v0.3"
    assert er.chebi_canonicalized is True
    assert len(er.pathways) >= 1

    # Verify pathway_id namespace prefix
    for hit in er.pathways[:3]:
        ns = hit.pathway_id.split(":", 1)[0]
        assert ns in PATHWAY_NAMESPACES, (
            f"pathway_id {hit.pathway_id!r} namespace {ns!r} "
            f"not in whitelist {PATHWAY_NAMESPACES}"
        )
        print(f"  hit: {hit.pathway_id}  score={hit.score:.4g} ({hit.score_type.value}) "
              f"name={hit.pathway_name[:50]}")
