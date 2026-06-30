# ConcordMet W11 UV diagnosis report

**Generated:** 2026-05-22
**Source data:** `data/concord/w10_d4_path_x_full/path_x_full/*.json` (63 task × 3 iter ConcordFeedbackResult dumps, W10 D4 run on metagent-v2 commit `52613ac`)
**Output dir:** `data/concord/w11_uv_diagnosis/`
**Scope:** classify the 1102 UNVERIFIABLE_V0 claims from W10 D4 final-iter into 9 mutually-exclusive categories (C1..C9) using LLM-assisted batch classification + 50-claim manual QC.

---

## 1 · Methodology

**Extraction.** Per-task JSON dump in `data/concord/w10_d4_path_x_full/path_x_full/` contains a stringified `VerifiedIdentification` pydantic repr (via `dataclasses.asdict(fb, default=str)` in the D4 driver). Each task's `iterations[final_iter_idx].verification.verdict` was regex-parsed to extract the `claims_v1` list — paren-balanced scan to locate each `VerifiedClaim(...)` block, then field-level regex for `claim_id`, `claim_text`, `claim_type`, `verdict`, `evidence`, `grammar`. Claims with `verdict == UNVERIFIABLE_V0` were retained.

Extraction script: `scripts/concord/w11_extract_uv_claims.py`.

**Counts.** 2100 `VerifiedClaim` blocks parsed (all final-iter, all 4 verdicts). 1102 UV claims extracted. Expected UV from W10 D4 summary jsonl: 1112 (delta −10 = 0.9%, below the spec-stop threshold of 50). 42 blocks matched the outer paren but failed field-regex (mostly long `evidence` fields with embedded quotes); these did not contribute to the UV count.

**LLM classifier.** MiniMax-M2.7 (the same model used to generate the D4 narratives), `temperature=0.0`, `response_format={'type': 'json_object'}`. System prompt enumerated 9 category definitions + 1-2 examples each; user message batched 20 claims per call with `claim_id` + `claim_text[:400]`. Prompt verbatim at `data/concord/w11_uv_diagnosis/llm_prompt_used.md`.

**Classifier script:** `scripts/concord/w11_classify_uv_claims.py`.

**API cost (from `logs/concord/w11_uv_classify.jsonl`):** 56 LLM calls, 71,951 prompt tokens + 262,464 completion tokens, ≈ **$0.34** at the MiniMax public rate ($0.30 / M prompt + $1.20 / M completion). Well under the $3 budget.

**Failed batches.** 3 of 56 batches returned 19 entries instead of 20; the missing 4 claims were marked `UNCLASSIFIED` in the output. All other 1098 claims received a category label. Wall: 72 minutes (MiniMax inference time).

**Manual QC.** 50 random claims from the classified set were reviewed by the session author against the LLM's labels. Output at `data/concord/w11_uv_diagnosis/uv_manual_qc.csv`.

| outcome | n / 50 | percent |
|---|---:|---:|
| LLM label == reviewer label | 33 | 66% |
| Marginal (LLM picked a valid but non-primary bucket) | 8 | 16% |
| Hard disagreement (LLM picked a clearly wrong bucket) | 9 | 18% |

**Hard disagreement breakdown (LLM → reviewer):**

| LLM | reviewer | n |
|---|---|---:|
| C3 | C6 | 2 |
| C3 | C1 | 2 |
| C9 | C3 | 1 |
| C7 | C5 | 1 |
| C1 | C9 | 1 |
| C4 | C9 | 1 |
| C3 | C9 | 1 |

Stop-condition check (W11 spec §4 #3): disagreement > 30% triggers re-design. Hard-only rate 18% is within the spec-expected < 20% band. Hard+marginal rate 34% is over the 30% line; per user decision on the QC ping, the workflow continues with Option A (current classification stands, both numbers reported for transparency).

---

## 2 · Category distribution

| Code | Label | Count | Percent | Bar (1 char = 2 pp) |
|---|---|---:|---:|---|
| C1 | cross_method_consensus | 90 | 8.2% | ████ |
| C2 | method_disagreement | 26 | 2.4% | █ |
| C3 | signal_evidence | 320 | 29.0% | ██████████████ |
| C4 | uncertainty_qualifier | 34 | 3.1% | █ |
| C5 | intermediate_biology | 220 | 20.0% | █████████ |
| C6 | literature_reference | 34 | 3.1% | █ |
| C7 | namespace_form | 226 | 20.5% | ██████████ |
| C8 | empty_or_noise | 9 | 0.8% |  |
| C9 | other | 139 | 12.6% | ██████ |
| UNCLASSIFIED | (LLM missed) | 4 | 0.4% |  |
| **TOTAL** | | **1102** | **100.0%** | |

CSV: `data/concord/w11_uv_diagnosis/uv_category_distribution.csv`.

---

## 3 · Per-category samples (10 per category)

Sampling: `random.seed(42)`, `random.sample(bucket, min(10, len(bucket)))`. Each row shows `claim_id`, `task_id` tail, `claim_type` (verifier's internal class label), and the verbatim `claim_text`.

### C1 — cross_method_consensus (n=90)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c001 | an_RAMP_P_000050021_seed8 | CONSISTENCY | The three paradigms converged on two distinct biological themes |
| v1:c019 | an_RAMP_P_000052855_seed0 | GROUNDED | Estrone appears in the metabolites_hit list from both RaMP and Mummichog |
| v1:c000 | an_RAMP_P_000000141_seed1 | PATHWAY_RELATIONSHIP | Three independent enrichment paradigms converge on tryptophan metabolism as the dominant perturbed pathway |
| v1:c000 | an_RAMP_P_000000421_seed8 | PATHWAY_RELATIONSHIP | Three independent enrichment paradigms converge on androgen and estrogen metabolism |
| v1:c003 | an_RAMP_P_000000106_seed2 | GROUNDED | RaMP multi-database ORA supports the finding |
| v1:c000 | an_RAMP_P_000053306_seed1 | PATHWAY_RELATIONSHIP | Three complementary enrichment paradigms converge on pyrimidine metabolism as the dominant disturbed pathway |
| v1:c021 | an_RAMP_P_000000398_seed9 | CONSISTENCY | Mummichog provides orthogonal empirical support |
| v1:c000 | an_lm_pathway_WP167_seed2 | PATHWAY_RELATIONSHIP | Eight differentially abundant metabolites converge on arachidonic acid metabolism and downstream eicosanoid biosynthesis |
| v1:c031 | an_lm_pathway_WP167_seed1 | PATHWAY_RELATIONSHIP | Three independent enrichment analyses converge on a lipid-eicosanoid biological signal |
| v1:c010 | an_RAMP_P_000000421_seed5 | DRIVER_METABOLITE | Five sex-steroid metabolites drove the convergence |

### C2 — method_disagreement (n=26)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c042 | an_RAMP_P_000000398_seed8 | BIOLOGICAL | D-glucose shows no consistent cross-paradigm enrichment |
| v1:c021 | an_RAMP_P_000000106_seed3 | SET_ENRICHMENT | N-acetylgalactosamine shows no enrichment in Mummichog analysis |
| v1:c027 | an_RAMP_P_000050099_seed6 | GROUNDED | Guanidinoacetic acid and oxalic acid are not enriched in the ORA top results |
| v1:c017 | an_RAMP_P_000000106_seed3 | SET_ENRICHMENT | N-acetylgalactosamine shows no enrichment in MetaboAnalystR PSEA |
| v1:c016 | an_RAMP_P_000000106_seed3 | SET_ENRICHMENT | 1,2,3-trihydroxybenzene shows no enrichment in MetaboAnalystR PSEA |
| v1:c022 | an_RAMP_P_000000106_seed3 | SET_ENRICHMENT | Elemental iron shows no enrichment in Mummichog analysis |
| v1:c024 | an_RAMP_P_000000106_seed3 | SET_ENRICHMENT | 1,2,3-trihydroxybenzene shows no enrichment in RaMP analysis |
| v1:c016 | an_RAMP_P_000053306_seed1 | GROUNDED | CDP does not appear in the ORA hit list |
| v1:c023 | an_RAMP_P_000000398_seed9 | CONSISTENCY | fructose 1-phosphate did not map to the galactose cluster in any tool |
| v1:c018 | an_RAMP_P_000000106_seed3 | SET_ENRICHMENT | Elemental iron shows no enrichment in MetaboAnalystR PSEA |

### C3 — signal_evidence (n=320)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c000 | an_RAMP_P_000050021_seed3 | GROUNDED | RaMP multi-database ORA returns three WikiPathways hits |
| v1:c004 | an_RAMP_P_000000421_seed3 | GROUNDED | RaMP ORA captured dehydroepiandrosterone |
| v1:c030 | an_RAMP_P_000050096_seed6 | GROUNDED | The mummichog hit expanded to five compounds |
| v1:c025 | an_RAMP_P_000050021_seed0 | GROUNDED | Mummichog returned zero resolved results |
| v1:c009 | an_RAMP_P_000000141_seed8 | GROUNDED | The overlap is 11 of 12 input features. |
| v1:c028 | an_RAMP_P_000050021_seed0 | GROUNDED | MetaboAnalystR resolved with results |
| v1:c024 | an_RAMP_P_000025682_seed2 | DRIVER_METABOLITE | The primary driver cluster consists of six arachidonic acid oxygenated metabolites |
| v1:c003 | an_RAMP_P_000000398_seed4 | BIOLOGICAL | Galactosemia has FDR = 1.43Ã10â»Â¹Â¹ |
| v1:c010 | an_RAMP_P_000000398_seed9 | DRIVER_METABOLITE | Four input metabolites drive the enrichment |
| v1:c010 | an_RAMP_P_000000106_seed2 | GROUNDED | Mummichog overlap is 11 out of 11 metabolites |

### C4 — uncertainty_qualifier (n=34)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c027 | an_RAMP_P_000000421_seed5 | OTHER | Tetrahydrobiopterin is consistent with but not definitively linked to the steroid signal in this dataset |
| v1:c006 | an_RAMP_P_000050021_seed6 | GROUNDED | The top-ranked hits are driven by glutathione and phosphoserine co-enrichment |
| v1:c022 | an_lm_pathway_WP167_seed9 | OTHER | Phenytoin is treated as a background signal |
| v1:c027 | an_RAMP_P_000050021_seed5 | SET_ENRICHMENT | N-formyl-L-glutamic acid and pyrroline hydroxycarboxylic acid suggest broader amino-acid and redox stress |
| v1:c031 | an_RAMP_P_000000421_seed8 | DRIVER_METABOLITE | The five non-steroid metabolites may represent treatment-specific secondary perturbations |
| v1:c034 | an_RAMP_P_000000398_seed7 | BIOLOGICAL | The perturbation is potentially consistent with an intervention that impairs galactose-to-glucose interconversion |
| v1:c028 | an_lm_pathway_WP167_seed1 | FACTUAL | Methylmalonic acid lacks confirmed membership in the eicosanoid synthesis roster |
| v1:c030 | an_lm_pathway_WP167_seed1 | FACTUAL | 6-methylmercaptopurine lacks confirmed membership in the eicosanoid synthesis roster |
| v1:c039 | an_RAMP_P_000050096_seed6 | BIOLOGICAL | Squalene is consistent with a side-arm of the broader metabolic perturbation |
| v1:c033 | an_RAMP_P_000000398_seed7 | BIOLOGICAL | The perturbation is potentially consistent with galactosemia |

### C5 — intermediate_biology (n=220)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c019 | an_lm_pathway_WP167_seed2 | BIOLOGICAL | Arachidonic acid feeds the cytochrome-P450 epoxygenase branch |
| v1:c025 | an_RAMP_P_000000398_seed9 | GROUNDED | The convergence across ORA, KEGG PSEA and m/z-network ranking constitutes a strong consensus finding |
| v1:c041 | an_lm_pathway_WP167_seed8 | BIOLOGICAL | 5-HETE branches from arachidonic acid via 5-LOX |
| v1:c026 | an_lm_pathway_WP167_seed6 | BIOLOGICAL | Elevation of 15d-PGJ2 implicates oxidative-stress-responsive Nrf2 activation |
| v1:c031 | an_lm_pathway_WP167_seed6 | BIOLOGICAL | The compensatory anti-oxidative response co-occurs with elevated cyclopentenone prostaglandins |
| v1:c019 | an_RAMP_P_000000016_seed4 | PATHWAY_RELATIONSHIP | Cystathionine is an intermediate linking glycine to the methionine-cysteine-sulfur axis |
| v1:c034 | an_RAMP_P_000000141_seed2 | BIOLOGICAL | Acrolein, doxycycline, and milrinone belong to distinct biological processes or reflect off-target drug effects |
| v1:c030 | an_lm_pathway_WP167_seed8 | BIOLOGICAL | Cystathionine is the direct trans-sulfuration node linking homocysteine to cysteine |
| v1:c049 | an_RAMP_P_000000016_seed1 | OTHER | Lipoic acid contributes to sulfur-cofactor biology |
| v1:c024 | an_lm_pathway_WP167_seed8 | BIOLOGICAL | The metabolites span the 5-LOX branch |

### C6 — literature_reference (n=34)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c008 | an_RAMP_P_000000421_seed6 | FACTUAL | 17Î²-hydroxy-5Î±-androstan-3-one is also known as dihydrotestosterone |
| v1:c014 | an_RAMP_P_000050021_seed7 | BIOLOGICAL | Norepinephrine is a canonical product of the tyrosine to L-DOPA to dopamine to norepinephrine cascade |
| v1:c033 | an_RAMP_P_000000421_seed3 | FACTUAL | N-acetylgalactosamine has InChIKey OVRNDRQMDRJTHS |
| v1:c016 | an_RAMP_P_000000016_seed2 | OTHER | S-adenosylmethionine is a universal methyl donor |
| v1:c029 | an_RAMP_P_000000016_seed2 | FACTUAL | Phosphorylcholine has KEGG ID C00588 |
| v1:c034 | an_RAMP_P_000000421_seed3 | FACTUAL | N-acetylgalactosamine resolved via InChIKey to N-acetyl-D-glucosamine |
| v1:c019 | an_RAMP_P_000050021_seed0 | OTHER | Benzo[a]pyrene-7,8-dihydrodiol-9,10-oxide is a known pre-carcinogen |
| v1:c053 | an_RAMP_P_000000016_seed7 | OTHER | Lipoate is the essential cofactor for pyruvate dehydrogenase complex |
| v1:c027 | an_lm_pathway_WP167_seed2 | FACTUAL | 3,4-dihydroxybenzeneacetic acid and 4-hydroxybenzoic acid are non-eicosanoid phenyl derivatives |
| v1:c029 | an_lm_pathway_WP167_seed6 | OTHER | Acetylcysteine is an electrophilic scavenger |

### C7 — namespace_form (n=226)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c006 | an_RAMP_P_000025682_seed2 | FACTUAL | 8(S)-HPETE maps to KEGG ID C14823 |
| v1:c011 | an_RAMP_P_000000421_seed3 | FACTUAL | 17Î²-hydroxy-5Î±-androstan-3-one has CHEBI ID CHEBI:16330 |
| v1:c020 | an_RAMP_P_000050021_seed9 | FACTUAL | Coumarin has CHEBI ID 28794 |
| v1:c009 | an_RAMP_P_000000421_seed6 | FACTUAL | Androst-4-ene-3,17-dione has KEGG ID C00280 |
| v1:c031 | an_RAMP_P_000000106_seed2 | BIOLOGICAL | Pyrocatechol appears in Dopamine Î²-hydroxylase deficiency |
| v1:c010 | an_RAMP_P_000000398_seed3 | GROUNDED | MUMM:galactose_metabolism has p=0.0052 |
| v1:c030 | an_RAMP_P_000000106_seed2 | BIOLOGICAL | 3,4-dihydroxyphenylacetaldehyde appears in Dopamine Î²-hydroxylase deficiency |
| v1:c040 | an_RAMP_P_000000398_seed0 | FACTUAL | Dopamine has KEGG ID C03758 |
| v1:c012 | an_lm_pathway_WP167_seed0 | GROUNDED | CDP mapped to MUMM:n_glycan_biosynthesis at rank-6 |
| v1:c033 | an_RAMP_P_000050021_seed5 | FACTUAL | Coumarin has KEGG identifier C05851 |

### C8 — empty_or_noise (n=9)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c026 | an_lm_pathway_WP167_seed9 | OTHER | 3-methyladenine is treated as a background signal |
| v1:c025 | an_RAMP_P_000050021_seed5 | FACTUAL | N-formyl-L-glutamic acid has KEGG identifier C01045 |
| v1:c026 | an_RAMP_P_000050021_seed5 | FACTUAL | Pyrroline hydroxycarboxylic acid has KEGG identifier C04281 |
| v1:c001 | an_RAMP_P_000052855_seed0 | GROUNDED | The three paradigms are RaMP multi-database ORA, MetaboAnalystR KEGG-set enrichment, and Mummichog m/z-direct activity scoring |
| v1:c006 | an_RAMP_P_000050021_seed5 | FACTUAL | Dihydrouracil has CHEBI identifier 15901 |
| v1:c027 | an_RAMP_P_000050021_seed9 | FACTUAL | Mummichog links coumarin to the CYP2A6 reaction |
| v1:c021 | an_RAMP_P_000000421_seed4 | GROUNDED | N-acetylgalactosamine appears in peripheral hits |
| v1:c020 | an_RAMP_P_000000421_seed4 | GROUNDED | coumarin appears in peripheral hits |
| v1:c005 | an_RAMP_P_000050021_seed5 | FACTUAL | Dihydrouracil has KEGG identifier C00429 |

### C9 — other (n=139)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c000 | an_lm_pathway_WP167_seed6 | SET_ENRICHMENT | The differentially abundant metabolites map onto a single dominant biological axis |
| v1:c023 | an_lm_pathway_WP167_seed1 | CONSISTENCY | Dehydroascorbic acid does not meet enrichment thresholds in any paradigm |
| v1:c020 | an_RAMP_P_000000016_seed9 | OTHER | L-Glutamic acid and dihydrolipoate support the glutamate dehydrogenase equilibrium |
| v1:c029 | an_RAMP_P_000000016_seed7 | GROUNDED | Threonine has molecular formula C4H9NO3 |
| v1:c020 | an_RAMP_P_000000106_seed0 | GROUNDED | The mummichog result corroborates the involvement of homocysteine |
| v1:c011 | an_RAMP_P_000000106_seed8 | DRIVER_METABOLITE | Tyramine is a driver metabolite of the enrichment |
| v1:c012 | an_RAMP_P_000000106_seed8 | DRIVER_METABOLITE | Pyrocatechol is a driver metabolite of the enrichment |
| v1:c006 | an_RAMP_P_000050021_seed9 | FACTUAL | 2,5-dihydroxybenzoic acid has KEGG ID C00628 |
| v1:c040 | an_RAMP_P_000000016_seed7 | FACTUAL | 15(S)-HETE corresponds to KEGG:C04742 |
| v1:c026 | an_RAMP_P_000050021_seed6 | GROUNDED | Five metabolites resolved to clean ChEBI canonical forms with no InChIKey conflicts |

### UNCLASSIFIED — (LLM missed) (n=4)

| claim_id | task tail | claim_type | claim_text |
|---|---|---|---|
| v1:c040 | an_RAMP_P_000050096_seed6 | CONSISTENCY | Squalene did not replicate in the ORA tools |
| v1:c010 | an_RAMP_P_000000141_seed8 | CONSISTENCY | The analysis demonstrates network-level activity independent of prior annotation. |
| v1:c039 | an_RAMP_P_000000141_seed3 | FACTUAL | Ureidosuccinic acid is N-carbamoyl-L-aspartic acid |
| v1:c033 | an_RAMP_P_000000016_seed7 | GROUNDED | L-glutamic acid has molecular formula C5H9NO4 |

---

## 4 · Per-pathway × category matrix

Rows are W10 D4 ground-truth pathways; columns are category codes. Cell = number of UV claims from that pathway falling into that category. Final column = row total (= n_uv_final_iter for that pathway).

| pathway | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | C9 | UNCLASSIFIED | TOTAL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Androgen and Estrogen Metabolism | 11 | · | 39 | 3 | 22 | 8 | 47 | 2 | 9 | · | 141 |
| Biological oxidations | 11 | · | 44 | 4 | 37 | 7 | 34 | 5 | 23 | · | 165 |
| Celecoxib Action Pathway | · | · | 7 | · | 2 | · | 5 | · | · | · | 14 |
| Eicosanoid synthesis | 18 | 2 | 64 | 15 | 59 | 5 | 36 | 1 | 14 | · | 214 |
| Galactose Metabolism | 13 | 8 | 52 | 5 | 16 | 2 | 24 | · | 11 | · | 131 |
| Glycine, serine and threonine metabolism | 4 | · | 27 | · | 41 | 12 | 22 | · | 25 | 1 | 132 |
| Metabolism of amino acids and derivative | · | · | 7 | 1 | 4 | · | 7 | · | 6 | 1 | 26 |
| Pyrimidine catabolism | 3 | 2 | 3 | · | · | · | 6 | · | 2 | · | 16 |
| Pyrimidine metabolism | 2 | 1 | 8 | 1 | 8 | · | 11 | · | 3 | · | 34 |
| Steroid biosynthesis | · | · | · | · | 3 | · | · | · | 1 | · | 4 |
| Sulfatase and aromatase pathway | 7 | · | 10 | · | · | · | · | 1 | 2 | · | 20 |
| Tryptophan metabolism | 11 | 1 | 38 | 2 | 15 | · | 3 | · | 26 | 2 | 98 |
| Tyrosine metabolism | 10 | 12 | 21 | 3 | 13 | · | 31 | · | 17 | · | 107 |

CSV: `data/concord/w11_uv_diagnosis/uv_per_pathway_x_category.csv`.

---

## 5 · Files produced

```
data/concord/w11_uv_diagnosis/
├── uv_claims_raw.jsonl                  1102 UV claims with metadata
├── uv_classified.jsonl                  1102 UV claims + LLM category
├── uv_category_distribution.csv         distribution table + 5 samples/cat
├── uv_per_pathway_x_category.csv        pathway × category matrix
├── uv_category_samples_10each.json      10 samples per category
├── uv_manual_qc.csv                     50 manual-review samples
├── llm_prompt_used.md                   classifier prompt + system message
├── extraction_stats.json                per-task extraction stats
└── _qc_sample_for_review.csv            intermediate (50 picks for QC)

scripts/concord/
├── w11_extract_uv_claims.py             Step 1 — regex parse + UV filter
└── w11_classify_uv_claims.py            Step 2 — MiniMax batch classification

logs/concord/
└── w11_uv_classify.jsonl                LLM call log (token usage / cost)
```

