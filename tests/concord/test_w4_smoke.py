"""W4 end-to-end smoke — 3 methods串跑 + MetaNetX cross-check.

Per W4 spec end-to-end checklist:
  1. Pick 1 task from Session 4 N=30 (RAMP_P_000052855 excluded)
  2. Build CompoundRefs via ChebiLookup
  3. Run sspa ORA + mummichog + RaMP wrappers
  4. Assert all 3 EnrichmentResults pass v0.3 validator
     (namespace OK, metabolites_hit populated)
  5. Feed each result's metabolites_hit to MetaNetX validator
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

CHEBI_DB = WORKTREE / "data" / "concord" / "chebi.sqlite"
RAMP_DB = Path("/data/weiwentao/llm_agent_metabolomics/ramp.sqlite")
MNX_DB = WORKTREE / "data" / "concord" / "metanetx.sqlite"
N30_SUMMARY = WORKTREE / "data" / "investigation" / "fig3_toy" / "summary_n30.json"

pytestmark = pytest.mark.skipif(
    not (CHEBI_DB.exists() and RAMP_DB.exists() and MNX_DB.exists()
         and N30_SUMMARY.exists()),
    reason="W4 dependencies missing (ChEBI / RaMP / MetaNetX / Session 4 data)",
)


def _pick_task() -> dict:
    summary = json.loads(N30_SUMMARY.read_text())
    target_tid = next(
        t for t in summary["task_ids"]
        if "RAMP_P_000052855" not in t
    )
    # task 2 = lm_pathway_WP167_seed5 (lipid)
    benchmark = WORKTREE / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks_v3.jsonl"
    with benchmark.open() as f:
        for line in f:
            t = json.loads(line)
            if t["task_id"] == target_tid:
                return t
    raise RuntimeError(f"task {target_tid} not found")


def test_w4_three_method_smoke():
    """sspa ORA + mummichog + RaMP串跑 → 3× v0.3 EnrichmentResult → MetaNetX cross-check."""
    from concord.lookup.chebi import ChebiLookup
    from concord.normalize.mummichog_norm import normalize_mummichog_output
    from concord.normalize.ramp_norm import normalize_ramp_output
    from concord.normalize.sspa_norm import normalize_sspa_output
    from concord.schema.enrichment import (
        COMPOUND_NAMESPACES, CompoundRef, EnrichmentResult,
        PATHWAY_NAMESPACES, resolve_primary_id,
    )
    from concord.schema.peak import PeakRecord
    from concord.validate.metanetx_validator import validate_cross_namespace_consistency
    from concord.wrappers.mummichog_wrapper import run_mummichog
    from concord.wrappers.ramp_wrapper import run_ramp_enrichment
    from concord.wrappers.sspa_wrapper import run_sspa

    chebi = ChebiLookup(db_path=CHEBI_DB)
    task = _pick_task()
    print(f"\n[w4 smoke] task: {task['task_id'][:60]}")
    print(f"[w4 smoke] n_metabolites: {len(task['differential_metabolites'])}")

    # Build CompoundRefs
    refs = []
    for m in task["differential_metabolites"]:
        rec = None
        if m.get("kegg_id"):
            rec = chebi.lookup_by_xref("KEGG", m["kegg_id"])
        if rec is None and m.get("hmdb_id"):
            rec = chebi.lookup_by_xref("HMDB", m["hmdb_id"])
        if rec is None or not rec.inchikey:
            continue
        refs.append(CompoundRef(
            primary_id=resolve_primary_id(chebi_id=rec.primary_id, inchikey=rec.inchikey),
            inchikey=rec.inchikey, display_name=rec.name,
            chebi_id=rec.primary_id,
            hmdb_id=f"HMDB:{m.get('hmdb_id')}" if m.get("hmdb_id") else None,
            kegg_compound_id=f"KEGG:{m.get('kegg_id')}" if m.get("kegg_id") else None,
        ))
    print(f"[w4 smoke] resolved {len(refs)} CompoundRefs")
    assert len(refs) >= 4

    # 1. sspa ORA
    sspa_raw = run_sspa(compound_refs=refs, method="ora", pathway_db="reactome")
    sspa_er = normalize_sspa_output(sspa_raw, top_n=10, chebi_lookup=chebi)
    print(f"[w4 smoke] sspa: {len(sspa_er.pathways)} pathways, "
          f"{sum(len(p.metabolites_hit) for p in sspa_er.pathways)} hits")

    # 2. mummichog (synthetic peaks from metabolite exact_mass)
    rng = random.Random(42)
    peaks = []
    for m in task["differential_metabolites"]:
        em = m.get("exact_mass") or 0.0
        if em > 50:
            peaks.append(PeakRecord(mz=em + 1.00784, p_value=0.001, t_score=4.5,
                                    retention_time=rng.uniform(30, 600)))
    for _ in range(200):
        peaks.append(PeakRecord(mz=rng.uniform(80, 800),
                                p_value=rng.uniform(0.1, 0.95),
                                t_score=rng.normalvariate(0, 1)))
    mc_raw = run_mummichog(peaks, mode="positive", permutations=20)
    mc_er = normalize_mummichog_output(mc_raw, top_n=10, chebi_lookup=chebi)
    print(f"[w4 smoke] mummichog: {len(mc_er.pathways)} pathways, "
          f"{sum(len(p.metabolites_hit) for p in mc_er.pathways)} hits")

    # 3. RaMP
    ramp_raw = run_ramp_enrichment(refs, top_n=10, ramp_db_path=str(RAMP_DB))
    ramp_er = normalize_ramp_output(ramp_raw, top_n=10, chebi_lookup=chebi)
    print(f"[w4 smoke] ramp: {len(ramp_er.pathways)} pathways, "
          f"{sum(len(p.metabolites_hit) for p in ramp_er.pathways)} hits")

    # Assert all 3 are v0.3, namespace OK, metabolites_hit non-empty
    for name, er in [("sspa", sspa_er), ("mummichog", mc_er), ("ramp", ramp_er)]:
        assert isinstance(er, EnrichmentResult), name
        assert er.schema_version == "concordmet_v0.3", name
        assert len(er.pathways) >= 1, name
        n_hits = sum(len(p.metabolites_hit) for p in er.pathways)
        assert n_hits > 0, f"{name} 0 metabolites_hit"
        # Namespace whitelist verification
        for hit in er.pathways:
            ns = hit.pathway_id.split(":", 1)[0]
            assert ns in PATHWAY_NAMESPACES, f"{name} pathway_id {hit.pathway_id}"
            for m_ref in hit.metabolites_hit:
                cns = m_ref.primary_id.split(":", 1)[0]
                assert cns in COMPOUND_NAMESPACES, f"{name} compound {m_ref.primary_id}"

    # 4. MetaNetX cross-check: dedupe all metabolites_hit and run validator
    all_hits = []
    seen = set()
    for er in (sspa_er, mc_er, ramp_er):
        for p in er.pathways:
            for m_ref in p.metabolites_hit:
                if m_ref.primary_id not in seen:
                    seen.add(m_ref.primary_id)
                    all_hits.append(m_ref)
    print(f"[w4 smoke] dedup hits across 3 methods: {len(all_hits)}")
    report = validate_cross_namespace_consistency(all_hits, db_path=MNX_DB)
    print(f"[w4 smoke] MetaNetX validation: "
          f"consistent={report.n_consistent} "
          f"inconsistent={report.n_inconsistent} "
          f"uncoverable={report.n_uncoverable} "
          f"critical={report.summary()['n_critical_conflicts']}")
    # Cross-check should produce 0 critical conflicts on unified ChEBI-rooted refs
    assert report.summary()["n_critical_conflicts"] == 0
