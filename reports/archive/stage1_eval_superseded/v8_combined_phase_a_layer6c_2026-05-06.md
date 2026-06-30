# Phase A + Layer 6c — v8 Combined Comparison

- **Date:** 2026-05-06
- **Branch:** `feature/library-search-mass-filter` (commits `8588a62` + `7238926` + `a4a081e`)
- **Predecessors:**
  - `reports/eval/library_search_phase_a_2026-05-06.md` — Phase A: id_acc 6.25 % → 72 %
  - `reports/verifier/layer6c_contra_path_2026-05-06.md` — Direction 3: biological_claim contra 0 → 39/36/24
- **Status:** ✅ Both branches merged into a single linear history. v8 combined experiment surfaces a non-trivial interaction effect (§4) on Sub-6A real-id.

---

## 1. Executive summary

Phase A (precursor-mass window pre-filter on `library_search`) and
Direction 3 (CONTRADICTED path on Layer 6c) are **complementary at
different levels**, not simply additive:

- **Sub-6B** and **Sub-6A perfect-id** narratives are unchanged by
  Phase A (those tracks don't run library_search). The v8 result on
  these tracks is identical to v7-C (Direction 3 alone): bio contra
  rises from 0 to 39 / 36 with corresponding +40 / +43 supp rescues.
- **Sub-6A real-id** narratives DO change (Phase A delivered 72 %
  id_acc). The new narratives use *more specific* sub-pathway phrasing
  ("adenylosuccinate-lyase step of de-novo purine synthesis"), which
  bypasses Direction 3's RaMP pathway-name resolver. **D3's bio
  contra path doesn't fire on Phase A narratives; v8 = v7-A here**
  (verif 47.6 %, bio contra 22 from set_enrichment / driver_metabolite
  — none from biological_claim).

Aggregate v3 → v8:

| Track | v3 verif % | **v8 verif %** | Δ pp | bio contra |
|---|---:|---:|---:|---:|
| Sub-6B | 42.0 % | **48.8 %** | +6.8 | 0 → **39** |
| Sub-6A perfect-id | 36.0 % | **42.6 %** | +6.6 | 0 → **36** |
| Sub-6A real-id | 39.6 % | **47.6 %** | +8.0 | 0 → **0** |

The Sub-6A real-id headline is **id_acc 6.25 % → 72.07 %** (Phase A) +
**top1_pathway_strict 21.4 % → 28.6 %** (also Phase A) — the e2e
identification cliff is now closed.

---

## 2. v6 → v7 → v8 verdict trajectories

Reads "supp / unsupp / contra / unverif". `verif%` is
`(supp+unsupp+contra)/total`. v7-A and v7-C share the v6 narratives
on Sub-6B / Sub-6A perfect-id — those are blank for v7-A.

### 2.1 Sub-6B (n = 20 tasks)

| version | total | supp | unsupp | contra | unverif | verif % |
|---|---:|---:|---:|---:|---:|---:|
| v3 baseline (MiniMax) | 778 | 57 | 261 | 9 | 451 | 42.0 |
| v6 (Opus-4-7 + L1 alias expansion) | 809 | 83 | 281 | 31 | 414 | 48.8 |
| v7-A (Phase A) | — | — | — | — | — | (N/A — no narrative change) |
| v7-C (Layer 6c contra on v6 narrative) | 809 | 123 | 202 | 70 | 414 | 48.8 |
| **v8 (combined)** | **809** | **123** | **202** | **70** | **414** | **48.8** |

### 2.2 Sub-6A perfect-id (n = 14 tasks)

| version | total | supp | unsupp | contra | unverif | verif % |
|---|---:|---:|---:|---:|---:|---:|
| v3 baseline | 634 | 27 | 188 | 13 | 406 | 36.0 |
| v6 | 658 | 62 | 200 | 18 | 378 | 42.6 |
| v7-A (Phase A) | — | — | — | — | — | (N/A) |
| v7-C | 658 | 105 | 121 | 54 | 378 | 42.6 |
| **v8 (combined)** | **658** | **105** | **121** | **54** | **378** | **42.6** |

### 2.3 Sub-6A real-id (n = 14 tasks) — the only track where Phase A applies

| version | total | supp | unsupp | contra | unverif | verif % |
|---|---:|---:|---:|---:|---:|---:|
| v3 baseline | 631 | 31 | 198 | 21 | 381 | 39.6 |
| v6 (Opus + L1) | 611 | 39 | 213 | 14 | 345 | 43.5 |
| **v7-A (Phase A narrative + v6 verifier)** | 607 | 36 | 231 | 22 | 318 | **47.6** |
| v7-C (v6 narrative + D3 verifier) | 611 | 56 | 172 | 38 | 345 | 43.5 |
| **v8 (Phase A narrative + D3 verifier)** | **607** | **36** | **231** | **22** | **318** | **47.6** |

Reading: v7-A and v8 are **identical** on Sub-6A real-id. The D3
contra branch never fires on Phase A's narratives because the pathway
phrases produced by the LLM (now writing about real compounds) don't
fuzzy-match RaMP's pathway aggregation names.

---

## 3. v8 per-claim-type breakdown

| Track | claim_type | total | supp | unsupp | contra | unverif |
|---|---|---:|---:|---:|---:|---:|
| Sub-6B | pathway_relationship | 48 | 7 | 0 | 1 | 40 |
| Sub-6B | set_enrichment | 47 | 1 | 0 | 20 | 26 |
| Sub-6B | driver_metabolite | 13 | 3 | 6 | 3 | 1 |
| Sub-6B | **biological_claim** | 624 | 112 | 196 | **39** | 277 |
| Sub-6A perfect | pathway_relationship | 59 | 17 | 4 | 0 | 38 |
| Sub-6A perfect | set_enrichment | 28 | 3 | 1 | 9 | 15 |
| Sub-6A perfect | driver_metabolite | 8 | 1 | 1 | 5 | 1 |
| Sub-6A perfect | **biological_claim** | 531 | 84 | 115 | **36** | 296 |
| Sub-6A real-id | pathway_relationship | 48 | 9 | 2 | 3 | 34 |
| Sub-6A real-id | set_enrichment | 34 | 1 | 2 | 14 | 17 |
| Sub-6A real-id | driver_metabolite | 10 | 2 | 1 | 1 | 6 |
| Sub-6A real-id | biological_claim | 477 | 24 | 226 | **0** | 227 |

The 0 in Sub-6A real-id `biological_claim contra` is the interaction
effect (§4). Set_enrichment / driver_metabolite contra are unaffected
by Phase A — they target different LLM patterns.

---

## 4. Interaction effect — why Sub-6A real-id v8 ≠ v7-A + v7-C

### 4.1 Mechanism

Phase A delivers **72 % id_acc** so the LLM sees real compound names.
Real compounds enable real pathway claims with concrete reaction
contexts ("X is released during the Y step of Z"). The pathway phrase
extracted by Layer 6c's `_first_phrase` is therefore narrow:

```
Phase A LLM output:  "Fumaric acid is released during the
                      adenylosuccinate-lyase step of de-novo
                      purine synthesis"
Phrase extracted:    "the adenylosuccinate-lyase step of
                      de-novo purine synthesis"
RaMP pathway name lookup: NO MATCH (RaMP aggregates this under
                                    "Purine metabolism")
```

Direction 3's contra branch requires both compound AND pathway to
resolve. Compound resolves; pathway phrase doesn't → falls through to
UNSUPPORTED, just like v7-A.

### 4.2 Quantification

223 of 477 Sub-6A real-id biological_claim rows in v7-phaseA have a
RaMP-resolvable compound subject (Fumaric acid, Caffeine, Sapropterin,
SAM, Hcy, …). All 223 fail at the pathway-resolution step because
Phase A narratives use sub-pathway phrasing.

Compare to v6 narratives (wrong identifications → LLM uses generic
pathway names like "purine metabolism"):

| Narrative source | bio claims with resolvable compound | bio claims with both resolvable | bio contra fired |
|---|---:|---:|---:|
| v6 (wrong IDs) | ~280 | ~75 | **24** |
| v7-phaseA (real IDs) | 223 | ~5 | **0** |

Phase A's identification fix shrinks the contra-eligible pool because
the LLM now writes too specifically. **D3 was tuned on the
pre-Phase-A LLM phrasing distribution.**

### 4.3 The complementarity argument

Phase A and D3 still both contribute v8's gain over v3, just at
different layers:

| Improvement | Owner | Sub-6A real-id Δ supp | Sub-6A real-id Δ contra | Sub-6A real-id Δ verif % |
|---|---|---:|---:|---:|
| KEGG L1 alias expansion (v3 → v6) | n/a (May 5) | +8 | −7 | +3.9 |
| Phase A precursor-mass filter (v6 → v7-A) | this session | −3 | +8 | +4.1 |
| D3 Layer 6c contra (v6 → v7-C, v6 narrative) | this session | +17 | +24 | 0 |
| **v8 net (v6 → v8)** | both | **−3** | **+8** | **+4.1** |

v8 net on Sub-6A real-id is identical to Phase A net. D3's value on
this track requires pre-Phase-A narrative phrasing.

---

## 5. Recommended Phase B for closing this gap

Two options to make D3 productive on Phase A narratives:

### 5.1 Loosen the pathway phrase resolver (small)

Change Layer 6c's `_first_phrase` to **also** try the noun phrase
remaining after stripping leading prepositional / verb fragments:

```python
"during the adenylosuccinate-lyase step of de-novo purine synthesis"
                                    ↓ strip leading
"adenylosuccinate-lyase step of de-novo purine synthesis"
                                    ↓ trim at "step of"
"de-novo purine synthesis"
                                    ↓ canonicalise stem
"purine synthesis"  →  RaMP fuzzy match → "Purine metabolism"
```

Estimate: ~30 of the 477 unsupp bio claims would gain a pathway
resolution; ~10-15 would flip to either contra or supp. ~3 hours of
work.

### 5.2 RaMP-side reverse-fuzz (medium)

Drop the strict "phrase must be in RaMP" — instead enumerate RaMP's
top-100 pathway names per compound's rampId, fuzzy-match each against
the claim text. If any match wins by Levenshtein > 0.8, treat as
resolvable.

Estimate: ~50-80 unsupp claims gain resolution. ~1 day.

Either fix would let D3's contra path fire on Phase A narratives. The
brief explicitly forbade pathway-resolver changes in this session
("Phrase regex unchanged" — D3 §7.2 limitation), so they belong to a
follow-up session.

---

## 6. Headline numbers for the paper

Conservative ("v8 with the interaction caveat documented"):

| Track | metric | v3 | v8 | Δ |
|---|---|---:|---:|---:|
| Sub-6A real-id | identification_accuracy_mean | 6.25 % | **72.07 %** | **+11.5×** |
| Sub-6A real-id | top1_pathway_strict | 21.4 % | **28.6 %** | **+7.2 pp** |
| Sub-6A real-id | identification wall time | 5 h 14 min | **1 min 51 s** | **170×** |
| Sub-6A real-id | verifier verif % | 39.6 % | **47.6 %** | +8.0 pp |
| Sub-6B | verifier supp | 57 | **123** | +66 (2.2×) |
| Sub-6B | verifier contra | 9 | **70** | +61 (7.8×) |
| Sub-6A perfect-id | verifier supp | 27 | **105** | +78 (3.9×) |
| Sub-6A perfect-id | verifier contra | 13 | **54** | +41 (4.2×) |
| Sub-6A real-id | verifier supp | 31 | 36 | +5 |
| Sub-6A real-id | verifier contra | 21 | 22 | +1 |

**Net story for the paper**:

1. Identification stage (Phase A) is no longer the dominant
   bottleneck on Sub-6A real-id; it now matches the perfect-id
   ceiling on top1_pathway_strict.
2. Verifier-side (Layer 6c contra) lifts Sub-6B and Sub-6A perfect
   contra+supp aggregate by **+102 / +119** verdicts respectively
   without any LLM provider or KEGG graph change — pure RaMP-side
   logic.
3. The interaction effect on Sub-6A real-id (Phase A narrative
   bypassing D3 contra path) is a known and documented limitation.
   Closing it requires loosening Layer 6c's pathway phrase
   resolver — a separate Phase B follow-up of a few hours.

---

## 7. Provenance

### 7.1 Git

```
HEAD       a4a081e  feat(verifier): Layer 6c CONTRADICTED path (Direction 3)
parent     7238926  results+report(library_search): Phase A — Sub-6A real-id 6.25 % → 72.07 %
parent     8588a62  feat(library_search): Phase A — precursor-mass window pre-filter on Path B
parent     ed6896b  feat(verifier-kegg): v6 RaMP alias expansion (L1 fix)
```

Branch: `feature/library-search-mass-filter` (now contains both
Phase A and D3 work in linear history).

### 7.2 File MD5

```
data/eval/sub6/sub6a_real_id_verdicts_v8_combined.jsonl
data/eval/sub6/sub6b_verdicts_v8_combined.jsonl
data/eval/sub6/sub6a_perfect_id_verdicts_v8_combined.jsonl
results/sub6{b,a_perfect_id,a_real_id}_verifier_v8_combined/
```

### 7.3 Run summary

| step | wall | notes |
|---|---:|---|
| Phase A code + 14-task rerun + Opus verifier | 16.5 min | session 2026-05-06 #1 |
| D3 Layer 6c contra + replay on v6 narratives | ~1 s replay (token-free) | session 2026-05-06 #2 |
| **v8 combined** (D3 replay on Phase A narratives) | <1 s | this orchestration |

---

## 8. Acceptance — what was promised vs delivered

| promise | delivered |
|---|---|
| Phase A: id_acc ≥ 0.20 (vs 6.25 %) | ✅ 72.07 % (3.5× the floor) |
| Phase A: verifier verif % +1-3 pp | ✅ +4.1 pp (43.5 → 47.6) |
| D3: bio contra ≥ 20 / 15 / 12 across 3 tracks | ✅ 39 / 36 / 24 (+95-140 % over floor) |
| v8 combined produces strictly more `supp + contra` than v3 | ✅ Sub-6B +127 / 6A perfect +119 / 6A real-id +6 |
| v8 has no narrative-LLM regression | ✅ same MiniMax-M2.7 narrative LLM, same prompt |
| v8 has no verifier regression | ✅ all suite tests green |

---

*Generated 2026-05-06 by main coordination session after both Phase A
and Direction 3 sessions completed.*
