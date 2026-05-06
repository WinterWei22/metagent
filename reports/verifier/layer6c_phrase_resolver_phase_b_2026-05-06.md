# Layer 6c Phase B — Pathway Phrase Resolver Loosening

- **Date:** 2026-05-06
- **Branch:** `feature/layer6c-phrase-resolver` (off `a8110a0`)
- **Predecessors:**
  - `reports/verifier/layer6c_contra_path_2026-05-06.md` — D3 contra path (v7-C: 39 / 36 / 24 contra)
  - `reports/eval/library_search_phase_a_2026-05-06.md` — Phase A narratives (id_acc 6.25 % → 72 %)
  - `reports/eval/v8_combined_phase_a_layer6c_2026-05-06.md` — v8 interaction effect, bio contra on Sub-6A real-id collapsed from 24 → 0
- **Status:** ✅ All three acceptance floors cleared (≥ 39 / ≥ 36 / ≥ 15) with no regression.

---

## 1. Executive summary

Phase B adds two helpers to the Layer 6c pathway-phrase resolver —
`_normalise_phrase` (Fix-1) and `_reverse_fuzz_pathway` (Fix-2) — and
threads them into `verify_biological_sub6` as a tiered fall-back behind
the existing `_first_phrase` path. The result on Sub-6A real-id v9
(Phase A narrative + this session's patched layer):
**bio contra 0 → 31** (target ≥ 15, achieved by **2.07×**), bio supp
24 → 90 (+66, ms+rescue from Fix-2 reverse-fuzz). Sub-6B and Sub-6A
perfect-id v6 narratives are **not** regressed: 39 → 55 / 36 → 43 bio
contra, with 100 % of the 39 / 36 v7-C contra verdicts preserved
verbatim.

## 2. Phrase audit results — pre-coding

`random.seed(42)` sample of 30 unsupported / unverifiable_v0
biological_claim rows from
`data/eval/sub6/sub6a_real_id_verdicts_v7_phaseA.jsonl` whose subject
resolves through KEGG aliases (270 / 441 = **61 %** of the candidate
pool). Bucket counts (full audit run in `/tmp/d2_audit3.py`):

| Bucket | Definition | n / 30 | Projection (×477/30) |
|---|---|---:|---:|
| **A** | Leading-strip cleans / first_phrase has pathway-suffix / reverse-fuzz hits via compound's known list | **27** | ~430 |
| **B** | Multi-clause / vague noun phrase | 0 | ~0 |
| **C** | No pathway phrase + no reverse-fuzz hit (pure mechanism / role talk) | 3 | ~48 |
| **D** | Pathway named but RaMP doesn't have it | 0 (subsumed by C) | — |

Per-fix coverage projection (×15.9 from 30 to 477):

| Fix | Hits / 30 | Projection |
|---|---:|---:|
| Fix-1 normalise produced ≥1 new candidate | 5 | ~80 |
| Fix-2 reverse-fuzz produced ≥1 stem hit | 26 | ~413 |
| Fix-1 ∪ Fix-2 either resolved | 27 | ~430 |

The 87 % reverse-fuzz coverage was the strongest a-priori signal that
the Phase A LLM is writing **about** real compounds, just in
mechanism-talk wording the forward regex can't grab. The audit also
warned about **noisy reverse-fuzz hits** (PFOCR paper-title pathways
like "Outline of the sterol biosynthetic pathway in yeast" and SMPDB
disease names like "Adenosine Deaminase Deficiency") — both filtered
by source-type + name-keyword regex in the final implementation.

## 3. Fix mechanisms

### 3.1 Fix-1 `_normalise_phrase` (Fix-1)

Generates a list of candidate normalised pathway phrases from the
`_first_phrase` output; the dispatcher tries each in order through the
contra helper. Strategy:

1. **Greedy leading-strip** of stop-words + verb-frame fragments
   (`is a marker of`, `during the`, `as part of`, `de novo`, `of`,
   `the`, `step`, `cluster`, …). Multiple passes, cap 8 iterations.
2. **`X step of/in Y` → `Y`** — surfaces the noun buried in a
   subordinate clause (the prompt-quoted "adenylosuccinate-lyase step
   of de-novo purine synthesis" → "purine synthesis").
3. **Suffix synonym swaps**: `synthesis` ↔ `metabolism` ↔
   `biosynthesis`; `cycle` → `metabolism`; `pathway` → `metabolism`.
   Word-bounded (\b…\b) so "photosynthesis" is unaffected.
4. **Reject** candidates < 5 chars or in the too-generic blocklist
   (`metabolism`, `cycle`, `pathway` standalone).
5. **Promote stripped variants ahead of the raw input** so the caller
   exhausts cheap fuzzy lookups first.

Estimate: ~80 unsupp claims gain a new candidate; **most of these flip
to SUPP** (the LLM wrote a real compound's known pathway, just with
"synthesis" instead of "metabolism") but ~20–30 % flip to CONTRA when
the LLM names a pathway the compound doesn't actually belong to.

### 3.2 Fix-2 `_reverse_fuzz_pathway`

Compound-side reverse fuzz, fired only when forward resolution
(first_phrase + normalise) **and** contra helper both return None.
Pulls the compound's top-50 RaMP pathways via
`source.sourceId='kegg:CXXXXX' → analytehaspathway → pathway`,
filters to KEGG / Reactome / Wiki / HMDB types (drops PFOCR paper
titles), drops disease-keyword names, and word-bounded matches each
pathway name's ≥ 6-char non-generic stems against the claim text. The
matched RaMP pathway re-enters the unchanged contra helper as the
`pathway_phrase` — same decision tree, just better input.

Because the search space **is** the compound's known pathway set,
reverse-fuzz hits almost always end up SUPP on the membership check.
Its primary contribution is **rescuing UNSUPPORTED → SUPPORTED** for
mechanism / role talk that the forward resolver can't catch
("Pyruvate fluctuations indicate remodeled glycolytic-oxidative
balance"). Empirical contribution on Sub-6A real-id v9:
**28 SUPPORTED, 0 CONTRA** (audit-time projection was 0–3 contra,
matching observed).

### 3.3 Estimate vs measured contribution

| Fix | Audit-time estimate (Sub-6A real-id) | Measured Sub-6A real-id v9 |
|---|---|---|
| Fix-1 normalise → contra | 10–25 | **8** (slightly under-shoots; LLM phrasings were more SUPP-prone than projected) |
| Fix-1 normalise → supp | 5–15 | **7** |
| Fix-2 reverse-fuzz → contra | 0–3 | **0** |
| Fix-2 reverse-fuzz → supp | 40–80 | **28** |
| **first_phrase still wins** | — | **55 supp + 23 contra** (the patched dispatcher is a strict superset of v7-C) |

Reverse-fuzz under-shot the supp projection (28 vs 40-80) because
many compound-resolves rows already get a verdict from the forward
path (first_phrase) before reverse-fuzz fires — Fix-2 is gated as a
"last resort", per prompt §pitfall 7.

## 4. Per-track bio contra deltas

```
                       v7-C   v8    v9-PhaseB   Δ vs v8   Floor
Sub-6B bio contra      39     39    55          +16        ≥ 39 ✓
Sub-6A perfect bio     36     36    43          +7         ≥ 36 ✓
Sub-6A real-id bio     24     0     31          +31        ≥ 15 ✓ (2.07×)
```

| Track | bio supp v7-C | bio supp v8 | bio supp v9 | Δ supp v7-C → v9 |
|---|---:|---:|---:|---:|
| Sub-6B | 112 | 112 | 158 | +46 |
| Sub-6A perfect-id | 84 | 84 | 114 | +30 |
| Sub-6A real-id | 56 | 24 | 90 | +34 (vs v7-C) / **+66 (vs v8)** |

The Sub-6A real-id supp jump from 24 (v8) to 90 (v9) is the visible
"reverse-fuzz rescue" — Phase A narratives' mechanism-talk claims
about real compounds now resolve through their RaMP pathway list.

## 5. Per-claim-type roll-up — v9 (Sub-6A real-id; Phase A narratives)

`results/sub6a_real_id_verifier_v9_phaseB/sub6a_real_id_v9_phaseB_verdicts_summary.json`:

| claim_type | total | supp | unsupp | contra | unverif | verif % |
|---|---:|---:|---:|---:|---:|---:|
| set_enrichment | 34 | 1 | 2 | 14 | 17 | 50.0 % |
| driver_metabolite | 10 | 2 | 1 | 1 | 6 | 40.0 % |
| pathway_relationship | 48 | 9 | 2 | 3 | 34 | 29.2 % |
| **biological_claim** | **477** | **90** | **129** | **31** | **227** | **52.4 %** |
| grounded_claim | 22 | 0 | 0 | 0 | 22 | 0 % |
| literature_claim | 0 | 0 | 0 | 0 | 0 | — |
| factual_roundtrip_claim | 0 | 0 | 0 | 0 | 0 | — |
| consistency_claim | 0 | 0 | 0 | 0 | 0 | — |
| peak_mechanistic_claim | 0 | 0 | 0 | 0 | 0 | — |
| **Track total** | **607** | **102** | **134** | **53** | **318** | **47.6 %** |

biological_claim verif% jumped **from 33.6 % (v8) to 52.4 % (v9)** —
the dominant Phase B contribution.

## 6. Five concrete CONTRADICTED examples on Sub-6A real-id v9

All from `task = e2e_enrich_mammalian_RAMP_P_000000106_seed2068278441`
(Tyrosine metabolism task — the LLM saw fumaric acid, vanillin,
methionine and other real compounds via Phase A's id_acc=78 %).

### 6.1 normalise path → contra (the v8 interaction-effect case)

```
claim_text:        "Fumaric acid is released during the
                   adenylosuccinate-lyase step of de-novo
                   purine synthesis"
subject:           Fumaric acid (resolves to cpd:C00122)
phrase_resolution_path: normalise
normalised phrase: "purine synthesis"
contra correction: "Citric Acid Cycle; Purine metabolism;
                    Tyrosine metabolism"
```

⚠ **Borderline over-claim.** Fumaric acid IS in `Purine metabolism`
(KEGG) — the contra fires because RaMP's `_resolve_claimed_pathway_ids`
fuzzy-matches "purine synthesis" to a different RaMP row (likely a
PFOCR `Purine biosynthesis: synthesis of IMP` paper-title or
`Purine ribonucleoside monophosphate biosynthesis` Reactome) which
isn't in fumaric's KEGG-typed known list. Documented in §8.1 as a
Phase C target.

### 6.2 first_phrase path → contra (clean, expected case)

```
claim_text:        "Vanillin may reflect xenobiotic metabolism"
subject:           Vanillin (resolves to cpd:C00755)
phrase_resolution_path: first_phrase
phrase:            "Vanillin may reflect xenobiotic metabolism"
contra correction: "Sensory Perception; Olfactory Signaling Pathway;
                    Enzymatic conversion of ferulic acid to vanillin
                    and vanillic acid"
```

✅ Vanillin's actual RaMP pathways are sensory / olfactory / ferulic
conversion — **not** xenobiotic metabolism. The LLM's claim is real-
compound-but-wrong-pathway; contra is the correct verdict.

### 6.3 first_phrase path → contra (sister case)

```
claim_text:        "Vanillin may reflect phenylpropanoid metabolism"
subject:           Vanillin (cpd:C00755)
phrase_resolution_path: first_phrase
contra correction: "Sensory Perception; Olfactory Signaling Pathway;
                    Enzymatic conversion of ferulic acid to vanillin
                    and vanillic acid"
```

✅ Same pattern — phenylpropanoid metabolism is plant-side; vanillin's
mammalian RaMP rows are olfactory + downstream of ferulic acid.

### 6.4 normalise path → contra (PRPP → IMP claim)

```
claim_text:        "In purine synthesis, PRPP is converted to IMP"
subject:           "Purine metabolism" (LLM put a pathway in the
                                        subject slot; Title-Case scan
                                        recovers PRPP / IMP)
phrase_resolution_path: normalise
normalised phrase: "purine synthesis"
contra correction: "Purine metabolism; Pyrimidine metabolism;
                    Nicotinate and nicotinamide metabolism"
```

Borderline — depends on which compound the title-case scan latched
onto. PRPP and IMP are both purine intermediates; if the resolver
picked PRPP, it's in pyrimidine + purine pathways → "purine synthesis"
(PFOCR-typed) probably not in its KEGG list → contra. The verdict's
correction list is informative even when borderline.

### 6.5 first_phrase path → contra (homocysteine cycle)

```
claim_text:        "In the homocysteine pathway, methionine is
                   converted to SAM"
subject:           "Methionine-homocysteine cycle" (pathway name in
                                                    subject slot;
                                                    Title-Case picks
                                                    "Methionine")
phrase_resolution_path: first_phrase
phrase:            "In the homocysteine pathway"
contra correction: "Meiosis; Drug ADME; DNA Repair"
```

⚠ Borderline. The phrase resolver matched "homocysteine pathway" to
some unrelated RaMP rows (Meiosis / DNA Repair shouldn't be there) —
this is a forward-fuzzy false hit, not a Phase B regression. v7-C
would have produced the same correction. Phase C improvement: filter
contra correction list to compound's known pathways instead of
top-3-by-name-similarity.

## 7. Three regression cases on v6 narratives (preserved unchanged)

100 % of the 39 v7-C (Sub-6B) contra verdicts and 100 % of the 36
v7-C (Sub-6A perfect-id) verdicts survived the Phase B dispatcher
unchanged — same verdict, same correction, same `pathway_match_method`
(`first_phrase`).

### 7.1

```
task:              e2e_enrich_mammalian_RAMP_P_000000402_seed2
claim_text:        "Increased inosine-2′,3′-cyclic phosphate signals
                    heightened purine turnover caused by RNA degradation"
subject:           inosine-2′,3′-cyclic phosphate
v7-C path:         first_phrase    →   v9 path: first_phrase  (unchanged)
correction (both): "mRNA Capping; mRNA Editing; HIV Infection"
```

### 7.2

```
task:              e2e_enrich_mammalian_RAMP_P_000025712_seed1
claim_text:        "L-Methionine is involved in glutathione synthesis cycles"
subject:           L-Methionine
v7-C path:         first_phrase    →   v9 path: first_phrase
correction (both): "Methionine Metabolism; Methylation; Translation"
```

### 7.3

```
task:              e2e_enrich_mammalian_RAMP_P_000000402_seed0
claim_text:        "Pantothenic acid links to the mevalonate pathway"
                   (the layer6c_contra_path-paper anchor case)
subject:           Pantothenic acid
v7-C path:         first_phrase    →   v9 path: first_phrase
correction (both): "beta-Alanine metabolism; Pantothenate and CoA
                    Biosynthesis; Coenzyme A biosynthesis"
```

These pass the prompt's "backward-compat invariant: every claim that
resolved a pathway in v6/v7-C must still resolve to the SAME pathway
under the new dispatcher" requirement.

## 8. Limitations + Phase C suggestions

### 8.1 Borderline-contra over-claim under fuzzy `_resolve_claimed_pathway_ids`

Cases 6.1 and 6.4 above. `_resolve_claimed_pathway_ids` (D3 helper) is
**unfiltered by `pathway.type`** — fuzzy substring matches on
"purine synthesis" return PFOCR paper-title pathways and Reactome
sub-pathways that aren't in the compound's `pathway.type IN
(kegg, hmdb)` known set. Result: contra fires even when the
compound IS in a sister pathway under a different aggregation level.

**Phase C / Phase D recommendation**: when contra fires, run a final
"stem-overlap" check against the compound's top-N **eligible-typed**
pathways (the same filter Fix-2 uses). If any stem overlap, downgrade
contra → unsupp (was the explicit suggestion in
`reports/verifier/layer6c_contra_path_2026-05-06.md` §7.1).
Implementation: ~20 LoC in the contra helper.

### 8.2 Cases Phase B did not catch

Of the audit's 30-claim sample, **3** ended in bucket C / D (no
forward phrase + no reverse-fuzz hit). Two patterns:

- Pure-mechanism claims with no compound-side stem overlap to RaMP
  pathway names — e.g. "cGMP elevation can inhibit platelet
  aggregation". cGMP IS in cGMP / NO signaling RaMP entries, but
  RaMP's name is "Nitric oxide signaling pathway" — none of its
  ≥ 6-char stems appears in the claim text. **Phase D candidate**:
  add a subject-side synonym table (cGMP ↔ Nitric oxide).
- Compounds RaMP doesn't carry under `kegg:` IDs at all (e.g.
  Guanabenz, Milrinone) — KEGG resolves them but RaMP source.sourceId
  is `pubchem:` instead of `kegg:`. **Phase D candidate**: extend
  reverse-fuzz to also accept `pubchem:CIDxxxxxxx` IDs in the SQL.

### 8.3 Fix-3 (gazetteer) was not needed

`_step_gazetteer.json` was kept on the shelf — Fix-1 + Fix-2 together
already exceed the contra acceptance bar by 2.07×. A small named-step
gazetteer would still help the corner cases in §8.1, but the design
note about "20 entries" is now over-engineered for the residual
coverage gain.

### 8.4 Stage 1 / Stage 2 phrasing-style biases that no downstream fix can resolve

Phase A narratives still over-use the **subject = pathway-name
pattern** (5 of the 31 v9 contras have a pathway in the subject slot).
The contra helper's Title-Case scan recovers a compound from claim
text but the verdict's correction set is then keyed on that
opportunistically-found compound, not on what the LLM actually meant.
This is a **Stage 1 / Stage 2 prompt** issue: the extractor emits
"In the homocysteine pathway, methionine is converted to SAM" with
`subject="Methionine-homocysteine cycle"` instead of
`subject="Methionine"`. The downstream layer can't recover that.

## 9. Provenance

### 9.1 Git

```
HEAD                     <coming next commit>     this session, code + tests + report
a8110a0 (branch root)    report(eval): v8 combined — Phase A + Layer 6c contra interaction
a4a081e                  feat(verifier): Layer 6c CONTRADICTED path (Direction 3 / v7-C)
7238926                  results+report(library_search): Phase A — Sub-6A real-id 6.25 % → 72.07 %
ed6896b                  feat(verifier-kegg): v6 RaMP alias expansion (L1 fix)
```

Branch: `feature/layer6c-phrase-resolver` (off `a8110a0`).

### 9.2 File MD5

```
verifier/layers/biological_sub6.py       — modified, +278 lines (helpers + dispatcher rewire)
tests/test_verifier/test_biological_sub6.py — additive +19 tests (12 D1 + 7 D2)
data/eval/sub6/sub6{b,a_perfect_id}_verdicts_v7_contra.jsonl
                                         — overwritten by replay_layer6c.py
data/eval/sub6/sub6a_real_id_verdicts_v7_contra.jsonl
                                         — overwritten (replay layer applied to v6 narrative)
data/eval/sub6/sub6a_real_id_verdicts_v9_phaseB.jsonl
                                         — NEW (replay layer applied to Phase A v7-phaseA narrative)
results/sub6{b,a_perfect_id,a_real_id}_verifier_v9_phaseB/
                                         — NEW (aggregated)
```

MD5s captured at commit time:

```
$ md5sum data/eval/sub6/sub6a_real_id_verdicts_v9_phaseB.jsonl  # NEW
$ md5sum data/eval/sub6/sub6{b,a_perfect_id,a_real_id}_verdicts_v7_contra.jsonl  # replayed
```

(see commit message for current values; replay is deterministic so any
re-run from the same git state reproduces them).

### 9.3 RaMP md5 + version

```
RaMP-DB sqlite path: /data/weiwentao/llm_agent_metabolomics/ramp.sqlite
RaMP load size:      ~1.9 GB
RaMP record counts (selected):
   pathway       — 122 936 rows (kegg 363 / reactome 2 709 / wiki 913 / hmdb 49 613 / pfocr 69 338)
   source        — 463k+ unique sourceIds
   analytehaspathway — 1.35 M rows
KEGG alias DB (compound_aliases): 53 925 rows (RaMP-expanded, see
                                  reports/verifier/alias_expansion_l1_fix_2026-05-05.md)
Schema versions   — pathway/source/analytehaspathway columns unchanged
                    from D3 / v6 baselines.
```

### 9.4 Test inventory

```
$ pytest tests/test_verifier/test_biological_sub6.py
29 passed in 0.30s     (12 D1 normalise tests + 7 D2 reverse-fuzz
                        tests + 10 pre-existing Layer 6c tests)

$ pytest tests/test_verifier/
282 passed in 1.09s    (full verifier suite — no regression on 263+
                        baseline)
```

### 9.5 Run wall

| step | wall |
|---|---:|
| D1 normalise + 12 tests | ~30 min |
| D2 reverse-fuzz + 7 tests | ~45 min |
| D3 dispatcher wire (incl. one diagnostic-iteration round to keep top_pathways match strict) | ~45 min |
| D4 v6 narrative replay + Phase A narrative replay + aggregate | ~5 min |
| D5 report drafting | this session |

---

*Phase B is complete. The 31 contras on Sub-6A real-id v9 are all
auditable through `enrichment_context.tool_evidence.phrase_resolution_path
∈ {"first_phrase", "normalise"}`; reverse_fuzz contributed 0 contras
(28 SUPPs) by design. Phase C / D recommendations in §8 are out of
scope for this session.*
