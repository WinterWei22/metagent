# Sub-6 Verifier `unverifiable_v0` Diagnosis

- **Date:** 2026-05-03
- **Branch:** `feature/verifier-diagnosis`
- **Type:** Read-only diagnostic. No code changes, no LLM calls, no data
  modifications.
- **Inputs:**
  - `data/eval/sub6/sub6b_verdicts_v2.jsonl` (post-P1+P2)
  - `data/eval/sub6/sub6a_perfect_id_verdicts_v2.jsonl` (post-P1+P2)
  - `data/eval/sub6/sub6a_real_id_verdicts.jsonl` (no `_v2` exists; this
    is the real-id verdict file from the P1+P2 re-run)
- **Aggregation tool:** `scripts/diag/sub6_unverifiable_diag.py` —
  evidence-text prefix matching against the 11 unverifiable_v0 branches
  catalogued from `verifier/layers/{biological_sub6,pathway_relationship,
  set_enrichment,driver_metabolite}.py` + the `verify_sub6` dispatcher.
  All 1,214 unverifiable_v0 claims across 3 tracks matched a known
  branch (0 unmatched).

---

## §1 Headline distribution

### 1.1 Per-track totals

| Track | Total claims | unverifiable_v0 | % |
|---|---:|---:|---:|
| Sub-6B (v2) | 772 | **434** | 56.2% |
| Sub-6A perfect-id (v2) | 648 | **399** | 61.6% |
| Sub-6A real-id | 631 | **381** | 60.4% |

### 1.2 Unverifiable rate by claim_type

```
                          Sub-6B (v2)         Sub-6A perfect (v2)   Sub-6A real-id
biological_claim        292 / 585  (49.9%)   273 / 497  (54.9%)   230 / 445  (51.7%)
pathway_relationship     45 /  45 (100.0%)    45 /  47  (95.7%)    44 /  44 (100.0%)
set_enrichment           17 /  35  (48.6%)    26 /  38  (68.4%)    21 /  39  (53.8%)
driver_metabolite         1 /  20   (5.0%)     1 /   5  (20.0%)    11 /  21  (52.4%)
factual_roundtrip_claim  26 /  26 (100.0%)    32 /  32 (100.0%)    42 /  42 (100.0%)
grounded_claim           46 /  46 (100.0%)    18 /  18 (100.0%)    22 /  22 (100.0%)
consistency_claim         7 /  15  (46.7%)     4 /  11  (36.4%)     8 /  15  (53.3%)
literature_claim          —                    —                    2 /   2 (100.0%)
peak_mechanistic_claim    —                    —                    1 /   1 (100.0%)
```

Three claim types are **100% unverifiable_v0 in every track**:
`pathway_relationship`, `factual_roundtrip_claim`, `grounded_claim`.
`pathway_relationship` is data-limited (Cat A); the other two are
schema-mismatched dispatcher-deferred (Cat D). See §2 / §4.

### 1.3 Unverifiable by responsible layer

| Layer | Sub-6B | 6A perfect | 6A real-id |
|---|---:|---:|---:|
| `biological_sub6` | 292 (67.3%) | 273 (68.4%) | 230 (60.4%) |
| `verify_sub6` (dispatcher) | 79 (18.2%) | 54 (13.5%) | 75 (19.7%) |
| `pathway_relationship` | 45 (10.4%) | 45 (11.3%) | 44 (11.5%) |
| `set_enrichment` | 17 (3.9%) | 26 (6.5%) | 21 (5.5%) |
| `driver_metabolite` | 1 (0.2%) | 1 (0.3%) | 11 (2.9%) |

---

## §2 By unverifiable reason (code-branch level)

Every unverifiable_v0 claim is mapped to one of 11 code branches across
4 layers + 1 dispatcher. Counts and category (A/B/C/D — see §4) below.

### 2.1 Sub-6B (n=434)

| Cat | Layer | Reason key | Count | % | Source line |
|:---:|---|---|---:|---:|---|
| D | `biological_sub6` | `free_text_biological_role` | **281** | 64.7% | `biological_sub6.py:118-127` |
| D | `verify_sub6_dispatcher` | `claim_type_unsupported` | 79 | 18.2% | dispatcher schema-mismatch path |
| A | `pathway_relationship` | `ramp_no_hierarchy_table` | 36 | 8.3% | `pathway_relationship.py:133-143` |
| C | `set_enrichment` | `no_pathway_phrase` | 17 | 3.9% | `set_enrichment.py:168-177` |
| A | `biological_sub6` | `disease_keyword_defer` | 11 | 2.5% | `biological_sub6.py:96-106` |
| C | `pathway_relationship` | `pathway_resolution_failed` | 5 | 1.2% | `pathway_relationship.py:201-214` |
| C | `pathway_relationship` | `no_relationship_keyword` | 4 | 0.9% | `pathway_relationship.py:123-131` |
| C | `driver_metabolite` | `drivers_unresolved` | 1 | 0.2% | `driver_metabolite.py:127-141` |

### 2.2 Sub-6A perfect-id (n=399)

| Cat | Layer | Reason key | Count | % |
|:---:|---|---|---:|---:|
| D | `biological_sub6` | `free_text_biological_role` | **267** | 66.9% |
| D | `verify_sub6_dispatcher` | `claim_type_unsupported` | 54 | 13.5% |
| A | `pathway_relationship` | `ramp_no_hierarchy_table` | 33 | 8.3% |
| C | `set_enrichment` | `no_pathway_phrase` | 26 | 6.5% |
| C | `pathway_relationship` | `no_relationship_keyword` | 7 | 1.8% |
| A | `biological_sub6` | `disease_keyword_defer` | 6 | 1.5% |
| C | `pathway_relationship` | `pathway_resolution_failed` | 5 | 1.3% |
| C | `driver_metabolite` | `drivers_unresolved` | 1 | 0.3% |

### 2.3 Sub-6A real-id (n=381)

| Cat | Layer | Reason key | Count | % |
|:---:|---|---|---:|---:|
| D | `biological_sub6` | `free_text_biological_role` | **230** | 60.4% |
| D | `verify_sub6_dispatcher` | `claim_type_unsupported` | 75 | 19.7% |
| A | `pathway_relationship` | `ramp_no_hierarchy_table` | 36 | 9.4% |
| C | `set_enrichment` | `no_pathway_phrase` | 21 | 5.5% |
| C | `driver_metabolite` | `drivers_unresolved` | 7 | 1.8% |
| C | `pathway_relationship` | `no_relationship_keyword` | 6 | 1.6% |
| C | `driver_metabolite` | `no_driver_names` | 4 | 1.0% |
| C | `pathway_relationship` | `pathway_resolution_failed` | 2 | 0.5% |

### 2.4 Branches that never fired (good news)

The following branches exist in code but produced **0 unverifiable_v0**
across all 3 tracks:

- `biological_sub6` *unsupported* path (the layer reaches a verdict, not unverifiable, when a pathway phrase exists but doesn't match top-10 — that path returns UNSUPPORTED instead).
- `set_enrichment / top_pathways_empty` — every Sub-6 task had populated `ramp_enrichment_result.top_pathways`. Curation worked.
- `pathway_relationship / ramp_db_unavailable` — RaMP was always available.
- `pathway_relationship / same_pathway_pair` — never triggered.
- `driver_metabolite / policy_fallback` — defensive path, correctly unreached.

---

## §3 Sample claims per top reason category

3 verbatim samples per track per top bucket, sampled with `random.seed(42)`.

### 3.1 [D] `biological_sub6 / free_text_biological_role` — 778 total (64% of all unverifiable)

The layer's own evidence text is:
> *"Layer biological_sub6 found no pathway phrase / ID and no concrete entity to verify. **Free-text biological role claims are out of v0 scope.**"*

**Sub-6B samples:**
1. *"Silica exposure response is part of the inflammatory response"*
2. *"Homocysteine is linked to Methionine"*
3. *"HPETEs modulate immune cell activity"*

**Sub-6A perfect samples:**
1. *"β-alanine is generated when uracil undergoes ring opening"*
2. *"UDP is phosphorylated to UTP by NDPK"*
3. *"Uridine to UMP to UTP are classic intermediates of pyrimidine salvage routes"*

**Sub-6A real-id samples:**
1. *"The treatment is reshaping redox homeostasis"*
2. *"Plant compound accumulation may indicate detoxification"*
3. *"NAC is involved in Antioxidant defense"*

**Comment:** these are LLM narrative claims about *biological roles*,
*enzymatic conversions*, or *physiological responses* — not pathway-set
membership. They have no RaMP-resolvable anchor. The verifier
**deliberately** declares them out of v0 scope (the Sub-6 enrichment
verifier is scoped to pathway / driver / hierarchy claims, not
biochemistry tutoring). This is structural to v0, not a bug.

### 3.2 [D] `verify_sub6_dispatcher / claim_type_unsupported` — 208 total (17% of all unverifiable)

> *"Sub-6 verifier does not support claim_type 'X': existing layer requires IdentificationReport (spectrum-centric), but Sub-6 supplies SubsixSourceReport. Treated as declared limitation."*

Affected claim_types: `factual_roundtrip_claim`, `grounded_claim`,
`consistency_claim`, `literature_claim`, `peak_mechanistic_claim`. These
are the **identification-pipeline** verifier layers reused as-is — they
need an `IdentificationReport` and Sub-6 doesn't supply one (no
spectra-to-compound roundtrip in Sub-6B; in Sub-6A the dispatcher still
routes the LLM-extracted *claims* through the Sub-6 source report).

**Sub-6B samples:**
1. *"Uroporphyrinogen I has KEGG identifier C05766"* (factual_roundtrip)
2. *"All share a common structural feature: the 16:1(9Z) fatty acid"* (grounded)
3. *"Purine and pyrimidine salvage (inosine-2′,3′-cP, dCMP) shows modest changes"* (grounded)

**Sub-6A perfect samples:**
1. *"Carbamoyl phosphate combines with Aspartate"* (factual_roundtrip)
2. *"Squalene converts to Lanosterol"* (factual_roundtrip)
3. *"BH4 appears as a secondary indicator"* (grounded)

**Sub-6A real-id samples:**
1. *"Bisoprolol is a beta-blocker"* (factual_roundtrip)
2. *"Cytarabine is used in chemotherapy"* (factual_roundtrip)
3. *"Carbamoyl-aspartate is the direct product of aspartate transcarbamoylase"* (factual_roundtrip)

**Comment:** dispatcher correctly reports its limitation. These claims
are real and many are factually checkable — but the existing Sub-1
verifier layers can't be reused on Sub-6's source-report shape.

### 3.3 [A] `pathway_relationship / ramp_no_hierarchy_table` — 105 total (9% of all unverifiable)

> *"Claim asserts a {upstream/downstream} relationship, but RaMP-DB v2025-03-06 has no pathway-hierarchy table (no `pathwayhaspathway` or analogue). Cannot adjudicate directional claims at v0."*

**Sub-6B samples:**
1. *"Putrescine is upstream of 4-aminobutanal in polyamine metabolism"*
2. *"DOPAL formation is downstream of monoamine oxidase activity"*
3. *"Succinyl-CoA feeds into porphyrin synthesis at the ALA step"*

**Sub-6A perfect samples:**
1. *"Putrescine feeds into the synthesis of spermidine"*
2. *"Guanine nucleotides are upstream of uric acid production"*
3. *"Methionine is upstream of homocysteine"*

**Sub-6A real-id samples:**
1. *"Methylation reactions are downstream of SAM"*
2. *"UTP is upstream of RNA synthesis"*
3. *"Molinate is upstream of CYP450 enzymes"*

**Comment:** these are real, specific, semantically grounded
upstream/downstream claims — the kind a reviewer would want verified.
But the verifier delivery report (verifier_sub6 §4.3) explicitly
documented that RaMP v2025-03-06 has no hierarchy table. Resolution
requires either KEGG reaction graph, Reactome hierarchy export, or a
hand-curated metabolic-graph DB.

### 3.4 [C] `set_enrichment / no_pathway_phrase` — 64 total (5% of all unverifiable)

> *"Layer 6a found no pathway ID or name in the claim, and no top_pathways canonical name appears verbatim in the claim text. Cannot map to a verdict."*

**Sub-6B samples:**
1. *"The lipid signature represents a downstream readout of SCD activity"*
2. *"The coordinated changes suggest altered methylation capacity"*
3. *"The combination suggests a treatment effect on membrane dynamics"*

**Sub-6A perfect samples:**
1. *"Ureidosuccinic acid, UMP, and UTP represent sequential phosphorylation"*
2. *"Coordinated changes in pyrimidine intermediates suggest altered nucleotide flux"*
3. *"The data reflect an auxiliary catabolic route"*

**Sub-6A real-id samples:**
1. *"Parallel elevation of allantoin suggests global nucleotide turnover is affected"*
2. *"The coordinated increase of these metabolites points to a cytoprotective shift in the treated cells"*
3. *"The experimental profile most likely reflects perturbation of the oxidative-stress / detoxification axis"*

**Comment:** P1's classifier widening pulled these into SET_ENRICHMENT
(was BIOLOGICAL pre-P1), but Layer 6a's regex+reverse-match still
can't find a canonical pathway name to anchor against. Many are vague
references to *processes* ("oxidative-stress axis", "membrane dynamics")
rather than named pathways. Some have a real underlying pathway
(e.g. "altered methylation capacity" → SAM/methionine cycle) that the
LLM didn't name verbatim.

### 3.5 [A] `biological_sub6 / disease_keyword_defer` — 17 total (1.4%)

> *"Disease / clinical-significance claims fall outside Sub-6 v0 scope: no curated disease-pathway DB is available."*

**Sub-6B samples:**
1. *"Uroporphyrinogen-III synthase deficiency may cause a downstream bottleneck"*
2. *"FAD deficiency could impair electron transport"*
3. *"Polyamine dysregulation affects proliferation"*

**Sub-6A perfect samples:**
1. *"Heightened proliferative or repair activity includes tumor cell growth"*
2. *"Multi-pathway alterations are typical in metabolic syndrome"*
3. *"Co-occurrence with metformin suggests metabolic stress or therapeutic intervention affecting nucleotide homeostasis"*

**Comment:** the disease-keyword guard fires before Layer 6c attempts
RaMP lookup. **Mild data-limitation flavor**: a few of these reference
diseases that ARE RaMP pathway entries (`Alkaptonuria`, `Tyrosinemia`
appear as pathway names in our `top_pathways[1..3]`). The guard is
slightly over-aggressive, but the sample size (17 total, 1.4%) is too
small to be the highest-leverage fix.

### 3.6 [C] `pathway_relationship / no_relationship_keyword` — 17 total (1.4%)

> *"Layer 6d could not detect a recognised relationship keyword (upstream / downstream / cross-talk / shared)."*

**Sub-6B samples:**
1. *"Pyruvate and 2-ketobutyrate feed into methionine synthesis"*
2. *"The pyrimidine-TCA link via fumarate is notable"*
3. *"dCMP can feed into uracil degradation"*

**Comment:** classifier routed these to PATHWAY_RELATIONSHIP based on
"link", "feed into", "via", but Layer 6d's keyword set requires
literal `upstream / downstream / cross-talk / shared`. Either the
classifier should not route here, or Layer 6d should accept
"feeds into / link / via" as relationship vocabulary.

### 3.7 [C] `pathway_relationship / pathway_resolution_failed` — 12 total (1.0%)

> *"Pathway resolution failed after regex + reverse-match: 'X' → N match(es), 'Y' → M match(es). Both must resolve to ≥1 RaMP pathway id."*

**Sub-6B samples:**
1. *"Orotic acid suggests purine/pyrimidine cross-talk potentially downstream of mitochondrial dysfunction"*
2. *"Aminoadipic acid suggests cross-talk with amino acid catabolism"*

**Comment:** Layer 6d demands BOTH endpoints resolve to RaMP pathway
IDs. When the LLM names a compound on one side ("Orotic acid",
"Aminoadipic acid") and a vague concept on the other side
("mitochondrial dysfunction", "amino acid catabolism"), the second
can't be resolved.

### 3.8 [C] `driver_metabolite / drivers_unresolved` + `no_driver_names` — 13 total (1.1%)

**Sub-6A real-id samples (`drivers_unresolved`):**
1. *"Cystine is a core driver of this response"*
2. *"Molinate is a key driver in xenobiotic metabolism"*
3. *"Amifostine and Raphin1 act as the principal drivers of the oxidative-stress response"*

**Sub-6A real-id samples (`no_driver_names`):**
1. *"1-arachidonoylglycerol and 13,14-dihydro-15-keto-PGJ₂ are the most informative lipid signals in the eicosanoid/endocannabinoid axis"*
2. *"Raphin1 acts as the principal driver of the oxidative-stress response"*

**Comment:** appears 11× in Sub-6A real-id specifically because the
real-id pipeline's library_search produces hits like "Molinate" and
"Raphin1" that are **out of the curated pool by design** (the Sub-6
curated pool is the 150 HMDB-Mammalian compounds, not the wider
library). Layer 6b correctly refuses to adjudicate.

---

## §4 Root-cause categorization

Categories (per brief):
- **A** — Data limitation: RaMP / curated DB lacks the field
- **B** — Layer logic gap: data exists, layer doesn't reach it
- **C** — Claim-extraction artifact: claim too vague / unparseable
- **D** — By-design v0 limitation: declared scope

### 4.1 Cross-track Cat A/B/C/D split

| Cat | Sub-6B | Sub-6A perfect | Sub-6A real-id | Aggregate |
|:---:|---:|---:|---:|---:|
| **A** Data limitation | 47 (10.8%) | 39 (9.8%) | 36 (9.4%) | 122 (10.0%) |
| **B** Layer logic gap | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | **0 (0.0%)** |
| **C** Extraction artifact | 27 (6.2%) | 39 (9.8%) | 40 (10.5%) | 106 (8.7%) |
| **D** By-design v0 | 360 (82.9%) | 321 (80.5%) | 305 (80.1%) | **986 (81.2%)** |
| Sum | 434 | 399 | 381 | 1,214 |

Sums to 100% — no residual.

### 4.2 What Cat A actually contains

| Bucket | Count | Fixable by |
|---|---:|---|
| `pathway_relationship / ramp_no_hierarchy_table` | 105 | Adding KEGG reaction-graph or Reactome hierarchy import to RaMP, OR a separate hierarchy DB. **Effort: moderate** (off-the-shelf KGML parsers exist). |
| `biological_sub6 / disease_keyword_defer` | 17 | Curated disease-pathway DB (HMDB has disease_associations_json), OR relax guard so disease-named pathways in `top_pathways[:3]` get a chance at substring match. **Effort: small** (relaxation), **moderate** (DB build). |
| **Total Cat A** | **122** | |

### 4.3 What Cat B actually contains

**Empty.** Every code branch we identified has a defensible reason for
returning unverifiable_v0 — none is a layer-logic gap where the data
exists but the layer fails to reach it. The closest case is
`disease_keyword_defer` (17 claims, classified as Cat A above): the
guard fires *before* the layer tries top_pathways substring match,
and a few disease-named pathways in top_pathways are reachable. We
keep that in Cat A because the canonical fix is data — adding a
disease-pathway DB or an explicit disease-pathway whitelist — not
restructuring layer flow.

If you want a Cat B-flavored micro-fix: relax the disease-keyword
guard to attempt top_pathways match before deferring. Estimated
recoverable: ≤17 claims (1.4% of unverifiable). Low impact.

### 4.4 What Cat C actually contains

| Bucket | Count | Notes |
|---|---:|---|
| `set_enrichment / no_pathway_phrase` | 64 | LLM narratives say "altered nucleotide flux" instead of naming "Pyrimidine metabolism". Could be tightened by a richer extraction prompt that asks the LLM to canonicalize pathway names. |
| `pathway_relationship / no_relationship_keyword` | 17 | Classifier over-routes "feeds into / link / via" claims. Layer 6d's keyword set could be widened to match. |
| `pathway_relationship / pathway_resolution_failed` | 12 | LLM names compound ↔ vague concept; second endpoint not resolvable. |
| `driver_metabolite / drivers_unresolved` + `no_driver_names` | 13 | Mostly Sub-6A real-id where library_search returns out-of-pool compounds. Real-id artifact, not a generalizable fix. |
| **Total Cat C** | **106** | Aggregate fixable upper bound: ~70 claims if extraction prompt + classifier widening land. |

### 4.5 What Cat D actually contains

| Bucket | Count | By-design rationale |
|---|---:|---|
| `biological_sub6 / free_text_biological_role` | 778 | Free-text biological narrative claims are explicitly **out of v0 scope** per layer evidence text. v0 verifies pathway/driver/hierarchy claims, not biochemistry tutoring. |
| `verify_sub6_dispatcher / claim_type_unsupported` | 208 | `factual_roundtrip_claim`, `grounded_claim`, `consistency_claim`, `literature_claim`, `peak_mechanistic_claim` need an `IdentificationReport`; Sub-6 supplies `SubsixSourceReport`. Schema mismatch is documented. |
| **Total Cat D** | **986** | |

### 4.6 Notable: Cat D dominance varies between layers, not between tracks

Cat D / Cat C / Cat A ratios are remarkably stable across tracks
(82/6/11, 80/10/10, 80/11/9 — within ±2pp). The dominant driver of
"60% unverifiable" is the same in Sub-6B (compound-only) as in Sub-6A
(end-to-end): LLM narrative style, not pipeline differences.

The **identification stage** of Sub-6A real-id changes which compounds
reach the LLM, but does not materially shift the verifier-side
verdict distribution (Sub-6A real-id has slightly more
`drivers_unresolved` and slightly fewer `disease_keyword_defer`, but
the headline 60% holds).

---

## §5 Bottom-line summary

### Headline

**1,214 unverifiable_v0 claims across 3 tracks (~60% of all claims).**
The split is dominated by Cat D (by-design): **81% of unverifiable
claims are claims the v0 verifier was never built to verify.**

### Top 3 contributors (aggregate across tracks)

1. **`biological_sub6 / free_text_biological_role`** — 778 claims
   (64% of all unverifiable). LLM narratives like *"Methionine is linked
   to Homocysteine"*, *"NAC is involved in Antioxidant defense"*. v0
   declares these out of scope.
2. **`verify_sub6_dispatcher / claim_type_unsupported`** — 208 claims
   (17%). Identification-pipeline claim_types (`factual_roundtrip`,
   `grounded`, `consistency`) routed but rejected by the Sub-6 source
   schema.
3. **`pathway_relationship / ramp_no_hierarchy_table`** — 105 claims
   (9%). Specific upstream/downstream claims, blocked by RaMP v2025-03-06
   missing `pathwayhaspathway` table.

### Cat A/B/C/D split

```
A (data limitation):   122 ( 10.0%)   ←  KEGG reaction graph would absorb 105 of 122
B (layer logic gap):     0 (  0.0%)
C (extraction artifact): 106 (  8.7%)   ←  prompt + regex tightening absorbs ~70
D (by-design v0):       986 ( 81.2%)   ←  not fixable as bugs; reframe as scope
```

### The single highest-impact "fix"

**There is no high-impact code fix.** The 60% unverifiable rate is
dominated (81%) by claims the v0 verifier was scoped not to verify.
The honest answer to "fix verifier coverage or accept this" is:

> **Accept it, but reframe.** The 60% unverifiable_v0 number is not a
> verifier coverage failure — it is the v0 scope made visible. The
> paper should report:
> - "60% of LLM narrative claims fall outside v0 verifier scope (free-
>   text biological narration + identification-pipeline claim types
>   that need a different source schema)"
> - "Of the in-scope 40%: X% supported, Y% unsupported, Z% contradicted,
>   W% data-limited (RaMP hierarchy)"

If you DO want to absorb unverifiable budget, the ranked options are:

| Option | Recoverable | Effort | Notes |
|---|---:|---|---|
| Cat A — add KEGG reaction graph for upstream/downstream | ~105 | Moderate (existing KGML parsers; RaMP-style sqlite import) | Most concrete; clean wins; re-enables Layer 6d for `upstream/downstream` claims. |
| Cat C — tighten Layer 6a/6d extraction (regex + classifier widening) | ~50–70 | Small (regex patches, prompt revision) | Diminishing returns past first iteration. |
| Cat A — add disease-pathway whitelist or relax disease guard | ~17 | Small | Low impact. |
| Cat D — extend dispatcher to pass non-Sub-6 claim types into Sub-1 verifier with a pseudo IdentificationReport | ~208 | Large (cross-pipeline verifier) | Re-architecture; not a coverage gap, a scope expansion. |
| Cat D — write a "biological-role" verifier (free-text NL inference vs. RaMP/HMDB role tags) | ~778 | Large + LLM-call heavy | Out of v0 by design; v1 territory. |

**Recommended single highest-impact action (if any one): Cat A KEGG
reaction-graph import.** Buys 105 claims of recovered coverage,
moderate effort, and makes paper claim "we verify upstream/downstream
relationships at the metabolic-graph level" technically true rather
than declaratively deferred.

---

## §6 Aggregation method (reproducibility)

Built `scripts/diag/sub6_unverifiable_diag.py`:

1. Read 3 verdicts JSONL files (no LLM, no DB queries — pure file I/O).
2. Filter to `verdict == "unverifiable_v0"`.
3. For each claim, prefix-match `evidence` text against 13 catalogued
   evidence prefixes (one per code branch in
   `verifier/layers/{biological_sub6,pathway_relationship,
   set_enrichment,driver_metabolite}.py` plus `verify_sub6` dispatcher).
4. **0 claims unmatched across all 3 tracks** — every unverifiable
   verdict's evidence text matches a catalogued branch.
5. Tag each branch with category A/B/C/D per the §4 logic.
6. Aggregate counts + sample 3 verbatim claims per bucket per track
   with `random.seed(42)`.

To re-run:
```bash
python -m scripts.diag.sub6_unverifiable_diag
```

---

## §7 What this report does NOT claim

- No code change recommendations beyond §5's "if you want to absorb
  unverifiable budget" option ranking. Per brief, fix design is the
  next session's job.
- No bug claim about the verifier — every unverifiable_v0 traced has
  a defensible reason in code or in the v0 scope statement.
- No comparative claim against Sub-1/Sub-2/Sub-3 verifier coverage.
- No claim about whether 60% unverifiable is "good" or "bad" —
  diagnostic only.
