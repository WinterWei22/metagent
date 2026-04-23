# Track D follow-ups resolved — `pathway_context` + `fetch_metabolite_info`

**Date:** 2026-04-23
**Fix plan:** follow-up brief (no separate document) — closes Tier-2 debt from
`reports/integration_report_de_2026-04-23.md` (P-2, P-3, P-4, P-6, D-1).
**Branch:** `integration-day1`
**Commits landed (5, one per finding):**

```
9d30aca  test(metabolite_info): pin D-1 L-carnitine cation propagation
4e968fa  fix(pathway_context): resolve P-4 cofactor noise in neighbours
8432cbe  fix(pathway_context): resolve P-3 non-HMDB/KEGG ID leaks in neighbours
90257f2  test(pathway_context): rename P-6 regression to fix-plan name
afd044f  fix(pathway_context): resolve P-2 upstream == downstream collapse
```

## Before / after

| # | Before | After | Measured on production dump |
|---|---|---|---|
| **P-2** upstream == downstream | Pyruvate, glucose, caffeine all had `set(up) == set(down)` | Non-empty symmetric difference | pyruvate 118↑/94↓ (only-up 96 / only-down 72); glucose 98/12; caffeine 4/7 |
| **P-3** non-HMDB/KEGG prefixes in neighbours | 42% of pyruvate's neighbours were `chebi:`/`rhea-comp:`/`polymer:` | 100% hmdb:/kegg: | pyruvate 193→112; glucose 143→60 (non-H/K rampIds dropped) |
| **P-4** cofactors flood central-metabolite neighbours | H₂O, ATP, NADH, NAD⁺, H⁺ dominated lists | None of those appear | pyruvate lost 11 cofactor rows (204→193). CO₂ (HMDB0001967) still appears for decarboxylation reactions — RaMP annotates it `is_cofactor=0` there, i.e. it's treated as a primary product; respecting RaMP's annotation is the contract. |
| **P-6** `cooccurrence_score` deflated on unresolvable co-obs | 1 real match + 9 typos → 0.1 | 1.0; `explain` surfaces `9 of 10 … could not be resolved against RaMP` | Already fixed in commit 7d8b097; this round only renamed the regression test to `test_p6_cooccurrence_only_counts_resolvable`. |
| **D-1** HMDB stores L-carnitine as protonated cation | Docs only in commit 7d8b097; no test pinning behaviour | Regression `test_d1_lcarnitine_returns_hmdb_cation_form` asserts `C7H16NO3` / 162.113 / InChIKey `-O` propagated verbatim | Tool continues to propagate HMDB's cation form — no silent renormalisation. Verifier still responsible for back-computing neutral mass from SMILES. |

## Schema changes proposed

**None.** The fix plan explicitly allowed a schema change for P-3 (typed
`NeighbourEntry { id, id_type }`) and for P-4 (`include_cofactors: bool`
request field). Both were avoided:

- P-3 is a simple prefix filter (`IDtype IN ('hmdb','kegg')` on the
  source-table join) — no new output type needed.
- P-4 is a hardcoded `is_cofactor = 0` default. No caller has
  requested the cofactor-inclusion knob; adding one would be a
  `PathwayContextRequest` field change that ripples into the
  orchestrator's `IdentificationReport` schema.

Contracts / schemas untouched: `schemas/*`, `common/*`, `docs/TOOL_CONTRACTS.md`,
`tests/integration/*`.

## Non-obvious findings logged here for the next integration session

### NF-1 — RaMP v3 substrate_product semantics are inverted vs. the audit's assumption

Verified empirically against `rhea:10269 LR "A => B + C"`: compound A
carries `substrate_product=0`, compounds B and C carry
`substrate_product=1`. So **0 is the equation LEFT side (substrate of
the forward-written equation)** and **1 is the equation RIGHT side
(product)**. Audit report R-2 and the pre-fix code both assumed the
opposite. The mini-DB fixture in `test_pathway_context.py` now matches
the production semantics exactly.

Old code "worked" because the up/down symmetry collapse (P-2) masked the
inversion: whichever value it mis-labelled, both lists still converged
to the same set.

### NF-2 — Rhea quartets duplicate every chemical reaction 4 times

Each chemical reaction Rhea curates is issued as four consecutive
`rxn_source_id`s — one each under direction `UN`, `LR`, `RL`, `BD`.
RaMP stores each as a distinct `ramp_rxn_id` with independent
`reaction2met` rows. The LR and RL variants **swap equation
orientation**, so `reaction2met.substrate_product` flips between them
for the same compound. Counting partners from more than one variant
per chemical reaction double-counts every edge and re-collapses up == down.

The P-2 fix handles this by trusting only the `LR` variant (Rhea's
canonical forward write), dropping `RL` / `BD` / `UN` siblings. This
loses the explicit "bidirectional" signal from `BD` for genuinely
reversible reactions, but that signal does not reach the caller's
decision loop in v0 anyway. A v1 refinement could duplicate a reaction's
partners into both up and down when a `BD` sibling exists under the
same Rhea number mod 4 — tracked as future work, not a correctness
issue.

### NF-3 — RaMP's `is_cofactor` is context-sensitive

`reaction2met.is_cofactor` is reaction-specific, not compound-specific.
Pyruvate carries rows with `is_cofactor=1` in some reactions and `=0`
in others; CO₂ is annotated `is_cofactor=0` in pyruvate's
decarboxylation reactions (RaMP treats it as a primary product).
Consequence: the P-4 filter respects RaMP's annotation verbatim, which
means CO₂ and other biologically "not-cofactor-in-this-context" species
will continue to appear in some neighbour lists. That is the right
behaviour for a trust anchor — the alternative is a hand-curated
blacklist that disagrees with RaMP.

### NF-4 — Impact on neighbour-list sizes

For reference when downstream consumers size their displays:

| focal | pre-all-fixes | after P-3 + P-4 | after P-2 (LR-only) |
|---|---|---|---|
| pyruvate (HMDB0000243) | 204↑ / 204↓ | 112↑ / 112↓ | 118↑ / 94↓ |
| glucose (HMDB0000122) | 143 / 143 | 60 / 60 | 98 / 12 |
| caffeine (HMDB0001847) | 10 / 10 | 6 / 6 | 4 / 7 |

Note the post-P-2 counts can be larger than post-P-3-only because P-2
collects partners from all LR reactions irrespective of neighbour `s_p`,
then dedupes — whereas the intermediate step asked for a specific
neighbour `s_p`. Final numbers are the ones the verifier will see.

## Regression sweep

| Suite | Result | Comment |
|---|---|---|
| `tests/tool_tests/test_metabolite_info.py` | **15 pass** | +1 new regression (D-1) |
| `tests/tool_tests/test_pathway_context.py` | **20 pass** | +4 new regressions (P-2 ×2, P-3, P-4) in addition to the 3 from the prior round |
| `tests/integration/test_facts_d.py` | **21 pass** | mock + real, existing `TestPerPathwayHitCount{Mock,Real}` still green |
| `tests/integration/test_pipeline_e2e.py` | **16 pass / 4 skip** | the previously-failing `test_prefilter_returns_at_least_one_candidate[lcarnitine_pos]` now passes under the integration harness (flexible comparators introduced by the integration session handle the D-1 cation form correctly) |
| Full repo `pytest tests/` | **193 pass / 25 skip / 3 pre-existing fail** | 3 failures are `test_library_search.py` hitting `matchms.similarity.ModifiedCosine` import — unrelated Track B issue documented in `reports/f14_f15_gnps_loader_followup_2026-04-23.md` |
| `scripts/audit_de.py` (with real envs) | exit 0, both Track D tools OK | 450 ms on glucose with full production RaMP |
| `acceptance_hmdb_smoke.py` | 8/10 | Same D-2 fixture drift (glucose α-form, L-carnitine cation) — NOT a tool issue |
| `acceptance_pathway_smoke.py` | **ALL CHECKS PASSED** | co-occurrence lift 1.000 vs 0.000, orphan raises, summary names compound, KEGG/HMDB paths equivalent |

## What's explicitly deferred to v1

- Bidirectional-reaction signal restoration (Rhea `BD` variant coupling). See NF-2.
- Direction-aware pathway ordering (P-7 is not in this round).
- `NeighbourEntry { id, id_type }` typed output type if the orchestrator
  or verifier later wants to inspect the source prefix before calling
  `fetch_metabolite_info`. Not needed in v0 — everything emitted is
  either `hmdb:` or `kegg:` prefixed now.
- Fixture refresh for `tests/fixtures/hmdb_ids/expected.json` (α-glucose
  / carnitine cation) — still owned by the fixture-refresh session.

## Sign-off

- 35 / 35 Track D unit tests pass in a clean env.
- 21 / 21 `test_facts_d.py` pass on both mock and real backends.
- Real-RaMP end-to-end smoke passes every check.
- Real-HMDB end-to-end smoke passes every meaningful check (2 mismatches
  are documented fixture drift).
- Full-repo baseline unchanged: same 3 pre-existing `test_library_search`
  failures; Track D contributes zero new failures.

Track D's Tier-1 + Tier-2 debt from the D-E integration audit is fully
closed.
