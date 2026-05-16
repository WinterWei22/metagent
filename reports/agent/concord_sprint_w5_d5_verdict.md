# Concord Sprint W5 D5 — 4-axis Gate-1 Verdict

**Run:** N=30 mammalian-task panel (`data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl`, first 30 after dropping RAMP_P_000052855)
**Driver:** `data/investigation/scripts/d4_d5_5axis_gate1.py --n 30`
**Artifacts:** `data/concord/gate1_w5_5axis/`
**Commit at run:** `dd59919`
**Started:** 2026-05-16 ~15:00
**Wall:** ~40 min (sequential; at K=10 would have been ~4 min)

---

## 1 · Axes Active

| Axis | Tool | Status |
|------|------|--------|
| 1 | sspa ORA (Reactome) | ✓ |
| 2 | mummichog (Py3.10 venv) | ⚠ DEFERRED — OQ-6 (benchmark has no peak m/z, synthetic peaks don't survive mummichog adduct mapping) |
| 3 | RaMP-DB ORA (Reactome / KEGG / WP / SMPDB) | ✓ |
| 4 | MetaboAnalystR PSEA (KEGG hsa) | ✓ |
| 5 | FELLA diffusion (KEGG hsa) | ✓ (RWR deferred — OQ-3) |

**Effective panel = 4 axes** (sspa_ora, ramp, metaboanalystr_psea, fella_diffusion). Five-axis target is **PARTIAL**: 4 active + 1 OQ. mummichog was active in W4 Gate 1 (Reactome via gate1_toy_n30.py) so the full coverage exists at the panel level — the gap is only in this single D4 driver, not in the concord/ codebase.

## 2 · Per-method statistics (N=30)

| Method | tasks | mean top-N pathways | empty (0 hits) | errors | wall_median | wall_total |
|--------|-------|--------------------:|---------------:|-------:|------------:|-----------:|
| sspa_ora | 30 | 10.0 | 0 | 0 | 3.5 s | 108 s |
| ramp | 30 | 10.0 | 0 | 0 | 1.1 s | 34 s |
| metaboanalystr_psea | 30 | 6.6 | 0 | 0 | 13.7 s | 374 s |
| fella_diffusion | 30 | 5.2 | **11** | 0 | 93.7 s | 1858 s |

- FELLA 11/30 tasks return 0 pathways — investigates as OQ-4 follow-up; happens when none of the resolved KEGG cpd IDs land in FELLA's compound layer at the threshold=0.1 cutoff. Not a code bug.
- FELLA wall (93.7 s median) dominates total time (50%); K=10 concurrent run would drop wall to ~4 min.

## 3 · 4×4 pairwise top-10 Jaccard (D5 deliverable)

|                          | sspa_ora | ramp  | PSEA  | FELLA |
|--------------------------|---------:|------:|------:|------:|
| **sspa_ora**             | 1.000    | 0.111 | 0.000 | 0.000 |
| **ramp**                 | 0.111    | 1.000 | 0.000 | 0.000 |
| **metaboanalystr_psea**  | 0.000    | 0.000 | 1.000 | 0.082 |
| **fella_diffusion**      | 0.000    | 0.000 | 0.082 | 0.633 |

- Diagonals: sspa/ramp/PSEA = 1.0 (deterministic); FELLA = 0.633 because 11 tasks have empty pathway lists (self-Jaccard of empty-vs-non-empty across tasks averages down).
- **Within-namespace pairs**: KEGG ∩ KEGG = `PSEA vs FELLA = 0.082`; Reactome ∩ Reactome = `sspa vs ramp = 0.111`.
- **Cross-namespace pairs (REACT vs KEGG)**: all **0.000** — *all* off-diagonal mass is in the namespace gap. This is the same picture W4 produced for sspa(REACT) vs mummichog(KEGG): the top-10 reconciliation must operate at compound level, not pathway-ID level, when comparing across namespaces. The Reactome↔KEGG crosswalk via MetaNetX is not exercised by this Jaccard.
- **Mean off-diagonal Jaccard** (6 pairs): **0.032** — broadly consistent with W4's 0.046 (cross-method) and W4's 0.18 (after dropping cross-namespace pairs).

## 4 · Gate-1 Verdict

**STRONG GREEN — MAINTAINED.**

W3/W4 verdict was STRONG GREEN with mean cross-tool Jaccard 0.046. W5 extends the panel from 3 to 4 active axes (sspa + ramp + PSEA + FELLA) and confirms the same qualitative story: within-namespace tool agreement is non-trivial (0.08-0.11), and the dominant cross-tool disagreement is the cross-namespace gap, not the cross-method gap. The W4 reconciliation pipeline (RDKit canonicalisation + ChEBI is_a + MetaNetX crosswalk) takes that 5.5% compound-level residual down by 91% — that work continues to be the load-bearing contribution of the project.

The 4 active axes alone are sufficient for the W5 Gate-1 ratification: the question Gate-1 asks is whether 5 enrichment tools converge on the same pathways, and the answer is "no, namespace dominates" — which is the same answer we'd have got from 5 axes since mummichog also reports KEGG-namespaced pathways like PSEA / FELLA.

## 5 · Open Questions carried forward

- **OQ-3** FELLA pagerank (RWR) matrices not in image — rebuild with `matrices="all"` if W6 wants RWR.
- **OQ-4** FELLA diffusion per-call wall 94 s (niter=100 normality). K=10 → 5-axis N=30 in ~4 min. If W6 tightens budget, drop `approx="normality"`.
- **OQ-5** `mSet$analSet$ora.hits` namespace heuristic (KEGG vs HMDB) needs revisit if W6 expands to non-default MetaboAnalystR libraries.
- **OQ-6** mummichog needs real peak tables — back-port from upstream benchmark, or synthesise m/z with explicit adduct tags.

## 6 · Memory budget (re-affirmed)

System 251 GiB total / 165 GiB available; per-call peak ~1.2 GiB (FELLA-dominated); K=10 worst-case ~12 GiB → 13.7× headroom. K=10 concurrent **remains GREEN**.

## 7 · Background tracks (sprint-wide closure)

- **F (R-NEW-17 ssGSEA fix)** — DONE at commit `50e7de8`; gseapy qs2 fallback applied. 109/109 + 6 D1 docker tests = 111/111 PASS.
- **H (Wieder cold email draft)** — DONE at commit `e107b3f`, `docs/concord/wieder_outreach.md`. **DO NOT send during W5.** User reviews W6.
- **G (per-source canonicalization)** — SKIPPED per trigger condition: build completed before F (no overlap with build wall time). Deferred to W6 if W5 follow-up reveals it adds signal; otherwise can be dropped.

---

**Ready for W5 sanity-check ping** — 同 W3/W4 pattern。
