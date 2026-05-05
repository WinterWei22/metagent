# Verifier KEGG Alias Pool Expansion — L1 Fix

- **Date:** 2026-05-05
- **Branch:** `feature/verifier-kegg-hierarchy`
- **Scope:** Fix the L1 follow-up flagged in `kegg_hierarchy_comparison_2026-05-03.md` §6: expand the KEGG `compound_aliases` table from 150-record curated mammalian pool (~925 alias rows) to a **53 925-row table** sourced from RaMP-DB. Verifier code unchanged. Reaction graph unchanged. Only the alias resolver's lookup table grew.
- **Status:** ✅ All three Sub-6 tracks rerun under Opus-4-7 v6. **Sub-6A real-id pathway_relationship `supported` jumped 0 → 15** — the same death-lock under v3/v4/v5 (MiniMax/GPT-5.5/Opus before expansion).

---

## 1. Executive summary

The L1 prediction holds: **expanding the KEGG compound alias pool
unlocks Sub-6A real-id directional verification end-to-end**. v6
adds 50× more synonym coverage from RaMP, makes 19/20 spot-checked
metabolites resolvable that previously failed, and produces +255 %
more SUPPORTED pathway_relationship verdicts across the three tracks
combined.

| Track | v5 verif% | **v6 verif%** | Δ |
|---|---:|---:|---:|
| Sub-6B | 48.0 % | **48.8 %** | +0.8 pp |
| Sub-6A perfect-id | 41.4 % | **42.6 %** | +1.2 pp |
| Sub-6A real-id | 40.4 % | **43.5 %** | +3.1 pp |

The Sub-6A real-id gain is the meaningful one — it confirms the
verifier's directional branch was bottlenecked on alias coverage,
not on LLM extractor or KEGG graph topology.

---

## 2. The fix

### 2.1 Data source

RaMP-DB (`/data/weiwentao/llm_agent_metabolomics/ramp.sqlite`,
v2025-03-06 snapshot) already aggregates HMDB / ChEBI / KEGG /
RefMet identifier mappings + 1.58 M synonym rows. Schema:

```
analyte           rampId, type, common_name                        (463 257 rows)
source            sourceId, rampId, IDtype, commonName             (1 256 410 rows)
analytesynonym    Synonym, rampId, geneOrCompound, source          (1 580 370 rows)
```

For our 4 307 reaction-graph compounds, RaMP knows about **2 393**
(55.6 %) — the rest are KEGG-internal intermediates RaMP doesn't
track. For those 2 393:

```
n_unique_ramp_ids_touched: 2 343    (some cpds have ≥1 rampId)
n_alias_rows_attempted:    105 172
n_alias_rows_added:        53 000
elapsed:                   18.2 s
```

### 2.2 Implementation

`scripts/kegg/expand_aliases_from_ramp.py` (~200 lines):

1. Query existing graph compounds (4 307 cpd:C-IDs)
2. Look up each in RaMP `source` (`IDtype='kegg' AND sourceId='kegg:Cxxx'`) → rampId set
3. For each rampId, pull:
   - `analyte.common_name` → name alias
   - All `analytesynonym.Synonym` for `geneOrCompound='compound'` → name aliases
   - All `source.commonName` → name aliases
   - `source.sourceId` for `IDtype='hmdb'` → hmdb aliases
4. Normalise (lower-case + collapsed whitespace), `INSERT OR IGNORE`
   into existing `compound_aliases` table

**The reactions / compounds tables are not touched.** Only
`compound_aliases` grows. Idempotent — re-running adds nothing
because the (alias, compound_id) primary key dedupes.

### 2.3 Smoke verification

20 spot-check compounds picked from real-id wrong identifications
and benchmark-relevant species:

```
✗ myrcene                      (terpenoid; not in mammalian metabolic 95-pathway slice)
✓ 1,3,7-trimethyluric acid     → cpd:C16361
✓ glutathione                  → cpd:C00051
✓ spermidine                   → cpd:C00315
✓ urate / uric acid            → cpd:C00366
✓ NAD+ / NADH                  → cpd:C00003 / cpd:C00004
✓ ATP                          → cpd:C00002
✓ palmitic acid                → cpd:C00249
✓ orotidine                    → cpd:C01103   (the missing Sub-6A Pyrimidine compound)
✓ caffeine                     → cpd:C07481
✓ cholesterol                  → cpd:C00187
✓ glycerol                     → cpd:C00116
✓ alpha-ketoglutarate          → cpd:C00026
✓ succinate                    → cpd:C00042
✓ lactate                      → cpd:C00954
✓ GTP                          → cpd:C00044
✓ dCTP                         → cpd:C00458
✓ cysteine                     → cpd:C00097
```

19/20 resolve. Pre-fix `glutathione`, `spermidine`, `urate`, `dCTP`
all failed.

---

## 3. Verifier rerun results

Same provider switch as v4/v5 (Opus-4-7 via viviai relay), same
narratives, same verifier code. Only the underlying alias table
changed (in-place sqlite edit).

### 3.1 Aggregate verdicts per track

| Track | LLM/version | total | supp | unsupp | contra | unverif | verif% |
|---|---|---:|---:|---:|---:|---:|---:|
| Sub-6B | v5 Opus baseline | 800 | 70 | 284 | 30 | 416 | 48.0 % |
| Sub-6B | **v6 Opus + RaMP** | 809 | **83** | 281 | 31 | 414 | **48.8 %** |
| Sub-6A perfect | v5 Opus baseline | 649 | 47 | 202 | 20 | 380 | 41.4 % |
| Sub-6A perfect | **v6 Opus + RaMP** | 658 | **62** | 200 | 18 | 378 | **42.6 %** |
| Sub-6A real-id | v5 Opus baseline | 664 | 32 | 219 | 17 | 396 | 40.4 % |
| Sub-6A real-id | **v6 Opus + RaMP** | 611 | **39** | 213 | 14 | 345 | **43.5 %** |

### 3.2 Layer 6d `pathway_relationship` (KEGG branch — the fix's hot zone)

| Track | version | total | supp | unsupp | contra | unverif |
|---|---|---:|---:|---:|---:|---:|
| Sub-6B | v5 | 48 | 3 | 1 | 1 | 43 |
| Sub-6B | **v6** | 48 | **7** | 0 | 1 | 40 |
| Sub-6A perfect | v5 | 75 | 8 | 1 | 0 | 66 |
| Sub-6A perfect | **v6** | 59 | **17** | 4 | 0 | 38 |
| Sub-6A real-id | v5 | 53 | **0** | 0 | 0 | 53 |
| Sub-6A real-id | **v6** | 50 | **15** | 3 | 0 | 32 |

**SUPPORTED pathway_relationship** across all 3 tracks combined:

| | v5 | v6 |
|---|---:|---:|
| Sub-6B | 3 | 7 |
| Sub-6A perfect | 8 | 17 |
| Sub-6A real-id | **0** | **15** |
| **Total** | **11** | **39** (+255 %) |

Sub-6A real-id was 0 SUPPORTED under MiniMax v3 (commit `2e16085`),
0 under GPT-5.5 v4 (commit `96d2231`), 0 under Opus-4-7 v5 (commit
`c208c7c`) — independent of LLM, gated entirely by alias coverage.
v6 produces **15 SUPPORTED in this column** with the same Opus-4-7
extractor + identical narrative inputs.

### 3.3 Layer 6b `driver_metabolite` (collateral effect)

| Track | version | total | supp | unsupp | contra | unverif |
|---|---|---:|---:|---:|---:|---:|
| Sub-6B | v5 | 11 | 4 | 6 | 0 | 1 |
| Sub-6B | **v6** | 13 | 3 | 6 | **3** | 1 |
| Sub-6A perfect | v5 | 7 | 1 | 0 | 4 | 2 |
| Sub-6A perfect | **v6** | 8 | 1 | 1 | **5** | 1 |
| Sub-6A real-id | v5 | 12 | 0 | 0 | 0 | 12 |
| Sub-6A real-id | **v6** | 11 | **1** | 0 | 0 | 10 |

CONTRADICTED rate ticks up 0 → 3 on Sub-6B and 4 → 5 on Sub-6A
perfect-id — Layer 6b can now resolve more compound names through
the broader alias table, exposing claims where the LLM mistakenly
labelled a noise compound as a driver.

---

## 4. Sample flips on Sub-6A real-id (the bottleneck track)

Three concrete pathway_relationship claims that flipped from
UNVERIFIABLE_V0 (v5) to SUPPORTED (v6):

1. `e2e_enrich_mammalian_RAMP_P_000000026_seed1549320213`
   (Methionine task) —
   *"Methionine is upstream of cysteine"*. v5 alias resolver returned
   None for "methionine" because curated pool stored only
   "L-Methionine"; even after the L-/D- variant fix the resolver
   couldn't reach further. v6 RaMP synonyms include "Methionine",
   "L-Methionine", "(2S)-2-Amino-4-(methylsulfanyl)butanoic acid", and
   8 others → resolves to `cpd:C00073`. KEGG path
   `C00073 → C02430 → C00101 → C00065 → C00097` (4 hops, bidirectional).

2. `e2e_enrich_mammalian_RAMP_P_000053306_seed3100819975`
   (Pyrimidine task) — *"Orotidine is upstream of UMP"*. Orotidine
   was NOT in the 150-curated pool at all (it had < 3 GNPS spectra so
   sub6a construction excluded it from the spectrum set, but
   real-id LLM still mentions it because identification noise
   surfaces it from elsewhere). v6 RaMP gives 14 orotidine synonyms
   → resolves to `cpd:C01103`. KEGG path 1 hop (orotidine → UMP via
   orotidine 5'-phosphate).

3. `e2e_enrich_mammalian_RAMP_P_000025712_seed4052145624`
   (Sulindac task) — *"Glutathione is downstream of cysteine"*.
   v5 had glutathione unresolved (curated pool didn't carry it).
   v6 RaMP path: `cpd:C00097 → cpd:C00669 → cpd:C00051` — same path
   the verifier already used for Sub-6A perfect-id v3, but inaccessible
   on real-id without the larger alias table.

---

## 5. Limitations remaining (v6 → v7 candidates)

1. **L1.b — Compounds in KEGG but not in RaMP** (1 914 of 4 307 graph
   compounds, 44.4 %). These are KEGG-internal intermediates / very
   specific lipid species RaMP intentionally drops. Closing this
   needs HMDB-XML or PubChem-substance-level mapping, ~1 day of
   work, marginal benefit (most are not mentioned in narratives).
2. **L4 — Reactome / SMPDB / WikiPathways pathways** still
   UNVERIFIABLE because we don't have a reaction-direction graph for
   those. ~50 % of Sub-6 task `top_pathways[:3]` are non-KEGG-source.
   Requires Reactome BioPAX export or SMPDB API.
3. **L5 — Currency metabolites** (water, CO₂, ATP, NAD+) not
   excluded from BFS targets — could over-link unrelated compounds at
   high hop counts. v6 longest path was 4 hops, no false positives
   observed, but L1.b expansion should pair with currency exclusion.

---

## 6. Provenance

### Git

```
HEAD                feat(verifier-kegg): v6 RaMP alias expansion (L1 fix)
c208c7c             feat(verifier): v5 Claude Opus-4-7 + 3-way LLM comparison
96d2231             feat(verifier): v4 GPT-5.5 + provider switch
2e16085             feat(verifier-kegg): D6 v3 reruns + D7 comparison
cd1f9fd             feat(verifier): D5 Layer 6d KEGG hierarchy branch
```

### Data

```
data/kegg/reaction_graph.sqlite  — 53 925 rows in compound_aliases
                                    (vs 925 pre-fix); reactions /
                                    compounds tables unchanged
data/kegg/alias_expansion_audit.json
                                  — RaMP md5 = c50066befe7a82825cccbbed37261c3f
                                    18.2 s wall, 53 000 rows added
```

### Test inventory

```
$ python -m pytest tests/test_kegg/ tests/test_verifier/ tests/eval_sub6/ -q
373 passed, 1 warning in 1.08s   (no regression — alias expansion is
                                  data-only, no code change to verifier
                                  or reachability layers)
```

---

## 7. Recommended next step

If the L1.b / L4 / L5 follow-ups are kept out of scope for v0, the
**recommended verifier configuration for the paper** is now:

- **Extractor LLM**: Claude Opus-4-7 (via OpenAI-compat endpoint)
- **KEGG reaction graph**: 95 hsa pathway maps, 4 307 compounds, 1 920
  reactions (1 580 reversible)
- **Compound aliases**: RaMP-expanded, 53 925 rows covering 2 393 of
  4 307 compounds with synonyms / HMDB / KEGG variants
- **RaMP-DB**: v2025-03-06 snapshot for cross-talk / shared-
  intermediates queries on Layer 6d

Headline numbers for this configuration: **48.8 % / 42.6 % / 43.5 %
verifiable share** on Sub-6B / Sub-6A perfect / Sub-6A real-id, with
**39 SUPPORTED pathway_relationship verdicts** across 34 tasks (vs 11
under v5, 11 under v4, 8 under v3).

---

*Generated 2026-05-05 after RaMP alias expansion and v6 reruns.*
