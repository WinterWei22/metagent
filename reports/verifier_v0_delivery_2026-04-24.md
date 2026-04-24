# Track V — Verifier v0 Delivery

- **Date:** 2026-04-24
- **Branch:** `integration-day1`
- **Predecessor:** Track O1 naive orchestrator (`reports/orchestrator_naive_v0_delivery_2026-04-23.md`)
- **LLM env:** `metagent-llm` (python 3.11, `openai==0.28.1`, `pydantic==2.13.3`)
- **LLM backend:** MiniMax-M2.7 via the OpenAI-compatible endpoint

---

## 1. Summary

This session adds the first hallucination-control layer on top of the
naive orchestrator. Architecturally independent from `orchestrator/`
(no imports either way), the verifier consumes
`(llm_output, source_report, trace_id)` and returns a
`VerifiedIdentification` with per-claim verdicts, rewritten output, and
budget accounting.

Designed against the eight observations recorded in Track O1's delivery
§5 — every layer and every test traces to one of them. The unit suite
(109 tests) passes against the three real fixtures using mocked LLM
responses; one live integration run on the glucose fixture exercises
the whole cascade against MiniMax in 245 s wall-clock and 7 LLM calls,
catching H1 (D-Gulose `C₇H₁₄O₇` → `C₆H₁₂O₆`) both at Layer A and at
Layer D, then auto-correcting the rewritten output.

**Nothing in `orchestrator/` was modified.** The O1 contract holds —
the wrong formulas in the original `source_llm_output` are preserved
verbatim; corrections appear only in `rewritten_output`.

---

## 2. Design — 4-stage cascade, 4-layer claim taxonomy

| | What |
|---|---|
| Stage 1 | Extract atomic claims (LLM call #1) |
| Stage 2 | Classify claims into 4 types (rules first, single batched LLM fallback) |
| Stage 3 | Verify each claim via Layer A/B/C; run Layer D consistency sweep across all claims |
| Stage 4 | If any v1 verdict is actionable: rewrite (LLM #4), re-extract (LLM #5), reclassify (LLM #6 if ambiguous), re-Layer-D (LLM #7) |

**Claim types and which O1 observations they target:**

| Type | Module | O1 catches | O1 tolerates |
|---|---|---|---|
| `grounded_claim` (Type 1) | `verifier/layers/grounded.py` | **H1** D-Gulose formula contradiction; **H2** "<1 ppm" scalar (field-shape mismatch with binary `mass_match_indicator`) | — |
| `factual_roundtrip_claim` (Type 2) | `verifier/layers/factual.py` (calls `fetch_metabolite_info`; `fetcher` is dependency-injected for tests) | **H4** KEGG ID round-trip | **H5** synonym/isomer naming — never CONTRADICTED on names alone, falls back to `unverifiable_v0` |
| `biological_claim` (Type 3) | `verifier/layers/biological.py` (source-first lookup in `pathway_context.pathways`) | **H3** "galactose metabolism / galactosemia / Fabry disease" | Neighbour & cooccurrence claims → `unverifiable_v0` per D/E P-2/3/4/6 |
| `consistency_claim` (Type 4) | `verifier/layers/consistency.py` (single batched LLM call) | **H1** independently as intra-document mismatch | **H7** chemistry-knowledge assertions ("silicon-containing candidate is implausible for biological matrices") — prompt explicitly forbids flagging externally-grounded claims |

**Out of scope for v0:** H8 (length budget — not a truth claim) and H6 (handled by *not* injecting the fixture name; verifier verifies what was said, not what should have been said).

---

## 3. Verification results

### 3.1 glucose (live-LLM run)

Real MiniMax-M2.7 cascade against `_O1_GLUCOSE_OUTPUT` (the verbatim
o1-part4-glucose_pos response). Trace:
`o1-part4-glucose_pos_verified_it`. Log:
`/tmp/verifier_e2e_lastrun.jsonl` (7 rows).

| # | Stage | Caller | Wall-clock | completion tokens |
|---:|---|---|---:|---:|
| 1 | extract v1 | `verifier.stage1.extract_claims` | 88.5 s | 3 631 |
| 2 | classify v1 | `verifier.stage2.classify_ambiguous` | 22.8 s | 884 |
| 3 | consistency v1 | `verifier.stage3.check_consistency` | 52.1 s | 2 465 |
| 4 | rewrite | `verifier.stage4.rewrite` | 14.9 s | 1 085 |
| 5 | extract v2 | `verifier.stage1.extract_claims` | 14.3 s | 1 135 |
| 6 | classify v2 | `verifier.stage2.classify_ambiguous` | 5.7 s | 302 |
| 7 | consistency v2 | `verifier.stage3.check_consistency` | 47.1 s | 1 608 |
| | | **TOTAL** | **245.4 s** | **11 110** |

`overall_verdict = partially_verified`. `llm_call_count = 7`.
`source_llm_output` preserved verbatim (assertion in test passes).

**Per-claim verdicts (24 v1 claims surfaced after extraction; H-numbers cross-link to O1 §5):**

| # | verdict | layer / type | claim text |
|--:|---|---|---|
| 1 | supported | A grounded | molecular formula is C₆H₁₂O₆ |
| 2 | unverifiable_v0 | A grounded | C₆H₁₂O₆ is a hexose monosaccharide |
| 3 | supported | A grounded | D-Gulose evidence_score 0.771 |
| 4 | supported | A grounded | D-Gulose cosine 0.423 |
| 5 | **supported** (H3) | C biological | linked to galactose metabolism pathway |
| 6 | **supported** (H3) | C biological | linked to galactosemia pathway |
| 7 | **supported** (H3) | C biological | linked to Fabry disease pathway |
| 8 | supported | A grounded | predicted spectral match cosine 0.423 |
| 9 | supported | A grounded | B/C score 0.860 |
| 10 | supported | A grounded | Glucose has molecular formula C₆H₁₂O₆ |
| 11 | supported | A grounded | Glucose cosine 0.423 |
| 12 | unverifiable_v0 | C biological | Glucose is a central metabolic hub |
| 13 | unverifiable_v0 | C biological | Glucose is statistically probable in biological samples |
| 14 | supported | C biological | Gulose maps to galactose metabolism (SMPDB/KEGG) |
| 15 | supported | C biological | Gulose maps to galactosemia (SMPDB/KEGG) |
| 16 | unverifiable_v0 | C biological | Glucose connects to a broader range of metabolic contexts |
| 17 | **CONTRADICTED** (H1) | A grounded | **D-Gulose has molecular formula C₇H₁₄O₇** → correction `C6H12O6` (`source_field=candidates[0].metabolite_info.molecular_formula`) |
| 18 | **CONTRADICTED** (H1, ind.) | D consistency | **Intra-document contradiction across claims [0],[10]** — Layer D independently caught header `C6H12O6` ↔ body `C7H14O7` |
| (rest abridged: a mix of `unsupported` paraphrases and `supported` claims that did not change behaviour) | | | |

**v2 (after rewrite) — 22 claims, 0 CONTRADICTED.** `D-Gulose has molecular formula C6H12O6` now resolves SUPPORTED. The intra-document contradiction is gone because the rewriter unified the formulas.

#### Stage 4 rewritten_output (verbatim from MiniMax)

```
## Identification Report

**Molecular Formula:** C₆H₁₂O₆

---

### Most Likely Candidate: D-Gulose (evidence_score: 0.771)

D-Gulose ranks highest by a narrow margin (0.771 vs 0.761). D-Gulose appears in galactose-related metabolic pathways. The predicted spectral match (cosine 0.423) is the best among candidates, and its B/C score (0.860) is the highest in the list.

---

### Top Candidates

**1. D-Gulose (C₆H₁₂O₆)**
Score: 0.771 | Cosine: 0.423
Linked to galactose metabolism, galactosemia, and Fabry disease pathways. The pathway enrichment provides biological context supporting this identification.

**2. Glucose (C₆H₁₂O₆)**
Score: 0.761 | Cosine: 0.423
Identical predicted spectral similarity and formula. Glucose may be a central metabolic hub, potentially making it statistically probable in biological samples.

### Pathway Context
Gulose maps to galactose metabolism and galactosemia pathways (SMPDB/KEGG). Glucose may connect to a broader range of metabolic contexts.
```

**Compare to source line 17:** the original wrote `**1. D-Gulose (C₇H₁₄O₇)**`. The rewriter substituted with the verifier-supplied correction. Some "may"-hedging was added by the model around lower-evidence claims (`unverifiable_v0`); not strictly required by the prompt but harmless.

### 3.2 caffeine (live-LLM run)

Real MiniMax-M2.7 cascade against `_O1_CAFFEINE_OUTPUT`. Trace:
`o1-part4-caffeine_pos_verified_it`. Log:
`/tmp/verifier_e2e_caffeine_lastrun.jsonl` (7 rows). Wall-clock 205.8 s,
8 020 completion tokens.

`overall_verdict = partially_verified`. `llm_call_count = 7`.
21 v1 claims surfaced.

| H | claim | verdict | layer |
|---|---|---|---|
| **H2** | `Mass accuracy is <1 ppm vs. HMDB reference` | **unsupported** ✓ | A grounded |
| **H4** | `Caffeine maps to KEGG pathway map00232` | **supported** ✓ | C biological |
| **H4** | `Caffeine maps to SMPDB caffeine metabolism pathways` | supported ✓ | C biological |
| **H5** | `Isocaffeine is a structural isomer of caffeine with identical molecular formula` | unsupported (NOT contradicted ✓) | A grounded |
| | `Caffeine has evidence_score 0.785` | supported ✓ | A grounded |
| | `Caffeine has library candidate score B/C = 0.975` | supported ✓ | A grounded |
| | `Caffeine has molecular formula C8H10N4O2` | supported ✓ | A grounded |
| | `Isocaffeine has evidence_score 0.651` | supported ✓ | A grounded |
| | `Isocaffeine has predicted-spectrum cosine of 0.439` | supported ✓ | A grounded |

Stage 4 rewritten output (verbatim) — H2 ppm wording dropped, H4 KEGG
pathway claim preserved, H5 Isocaffeine entry preserved:

```
## Metabolite Identification Report

### Summary
The experimental spectrum (m/z 195.0877 [M+H]+, neutral mass 194.0804 Da) matches molecular formula **C8H10N4O2**. The top five candidates are structural isomers within the imidazopyrimidine/purine-dione chemical class. **Caffeine** is the most likely identification based on the available evidence.

---

### 1. Caffeine (evidence_score: 0.785) — **Most Likely**

Caffeine ranks highest primarily due to its exceptional library candidate score (B/C = 0.975) and may have cross-referencing across HMDB, KEGG, and ChEBI. The mass accuracy is excellent.

### 2. Isocaffeine (evidence_score: 0.651)

It shows the highest predicted-spectrum cosine (0.439) among candidates, but may lack pathway associations and database cross-references.
```

### 3.3 lcarnitine (live-LLM run)

Real MiniMax-M2.7 cascade against `_O1_LCARNITINE_OUTPUT`. Trace:
`o1-part4-lcarnitine_pos_verified_it`. Log:
`/tmp/verifier_e2e_lcarnitine_lastrun.jsonl` (7 rows). Wall-clock 271.3 s,
11 475 completion tokens.

`overall_verdict = partially_verified`. `llm_call_count = 7`.
19 v1 claims surfaced.

| H | claim | verdict | layer |
|---|---|---|---|
| **H6** | (no v1 or v2 claim mentions "L-carnitine") | ✓ respected | — |
| **H7** | `[dimethyl-(trimethylsilylamino)silyl]methane is unlikely to arise in biological samples` | unverifiable_v0 ✓ (NOT contradicted) | C biological |
| **H7** | `Candidate #2 is chemically implausible for most biological matrices` | unverifiable_v0 ✓ (NOT contradicted) | C biological |
| | `2-[2-hydroxyethyl(methyl)amino]ethyl acetate has an evidence score of 0.529` | supported ✓ | A grounded |
| | `3-[2-(dimethylamino)ethoxy]propanoic acid has an evidence score of 0.499` | supported ✓ | A grounded |
| | `[dimethyl-(trimethylsilylamino)silyl]methane has an evidence score of 0.499` | supported ✓ | A grounded |
| | `2-[2-hydroxyethyl(methyl)amino]ethyl acetate has CID:218057` | unverifiable_v0 (was CONTRADICTED on first run — see §5 #4) | B factual |
| | `2-[2-hydroxyethyl(methyl)amino]ethyl acetate has molecular formula C7H15NO3` | unsupported (`metabolite_info=None` in source — pipeline degradation) | A grounded |

Stage 4 rewritten output (verbatim) — H6 honoured (still no L-carnitine
injected), H7 silicon warning preserved with hedging:

```
## Identification Report

### Most Likely Candidate
**2-[2-hydroxyethyl(methyl)amino]ethyl acetate** with an evidence score of 0.529.

### Top 3 Candidates

1. **2-[2-hydroxyethyl(methyl)amino]ethyl acetate** — May contain a tertiary amine, an ester, and a hydroxyl group.

2. **3-[2-(dimethylamino)ethoxy]propanoic acid** (evidence_score: 0.499) — Also C₇H₁₅NO₃ with potential zwitterionic character.

3. **[dimethyl-(trimethylsilylamino)silyl]methane** (evidence_score: 0.499) — May contain silicon and may be an atypical organosilane that could be unlikely to arise in biological samples.

### Limitations and Caveats
- **Silicon-containing candidate**: Candidate #2 may be chemically implausible for most biological matrices.
```

---

## 4. Measured budget — across 3 live runs

| fixture | LLM calls | wall-clock | completion tokens |
|---|---:|---:|---:|
| glucose_pos | 7 | 245.4 s | 11 110 |
| caffeine_pos | 7 | 205.8 s | 8 020 |
| lcarnitine_pos | 7 | 271.3 s | 11 475 |
| **mean** | **7** | **240.8 s** | **10 202** |
| **total** | 21 | 12.0 min | 30 605 |

Best-case theoretical: 2 calls (extract + consistency, all v1 SUPPORTED, no
Stage 4). Floor (all v1 SUPPORTED, single claim, no consistency): 1.

The original design doc said worst case = 6. The first live run hit 7
because Stage 2 LLM-fallback fired in **both** v1 and v2 — the budget
table mis-counted Stage 2 as one-shot. **All three live runs used 7**
because every output had ≥1 ambiguous claim per pass. The schema
docstring, agent docstring, and tests have been corrected to 7.

Cost estimate at $0.01/call (rough MiniMax-M2.7 reference) = **~$0.07
per identification**, **~$0.21 for the full 3-fixture pass**.

---

## 5. Known limitations

1. **Three-fixture live verification — but only ~60 distinct claims observed.**
   All three O1 outputs ran end-to-end against live MiniMax (21 LLM
   calls total). 60 distinct v1 claims surfaced across the three runs.
   Generalising the precision/recall numbers below to "the verifier
   catches X% of hallucinations" requires expanding to 20-30 fixtures
   in the next evaluation session.

2. **MiniMax non-determinism at temperature 0.** During development one
   live cascade call timed out at the 600 s upstream limit; the next
   succeeded in 88.5 s. `<think>` block length varies wildly run-to-run
   (3 600 – 29 000 chars observed). Budget the integration tests at
   ≥10 min per call wall-clock when running CI; current CI is
   best-effort.

3. **Common-helper bug worked around.** `common.llm_client.extract_json_list`
   uses `rfind("[")` / `rfind("}")` for bracket extraction, which
   corrupts results when the LLM's claim list contains substrings like
   `"[M+H]+"` — collapses 32 well-formed claims to 1 because the
   `rfind("[")` lands inside a claim text. The verifier ships a local
   replacement (`verifier.claim_extractor._parse_claim_list`) that
   strips markdown code fences then uses `find("[")` (first), not
   `rfind`. Track V was forbidden from modifying `common/`; a separate
   session should fix the upstream helper.

4. **Layer B softened: `found=False` is now `unverifiable_v0`, not
   `contradicted`.** First lcarnitine live run flagged
   `2-[2-hydroxyethyl(methyl)amino]ethyl acetate has CID:218057` as
   CONTRADICTED. The CID is genuinely valid in PubChem (it's the source
   pipeline's actual top candidate), but the local
   `fetch_metabolite_info` only queries HMDB by default; PubChem
   requires `METAGENT_ALLOW_PUBCHEM=1`. Without disambiguation, treating
   "ID not in HMDB" as "ID hallucinated" is a false positive. Layer B
   was updated to return `unverifiable_v0` on `found=False` regardless
   of whether a subject was named — an absence of evidence is not
   evidence of absence. Two unit tests in `test_layer_factual.py`
   (`test_roundtrip_id_not_found_is_unverifiable_*`) lock in the new
   behaviour.

5. **Layer C is membership-only in v0.** Per Track V design and the
   D/E P-2/3/4/6 audit, `upstream_neighbours` / `downstream_neighbours`
   / `cooccurrence_score` claims are blanket-marked `unverifiable_v0`.
   When Track D ships those fixes, lift the gate in
   `verifier/layers/biological.py` and add neighbour-membership tests.

6. **Literature-claim verification not implemented.** Track F is
   descoped; any LLM claim about PMIDs / DOIs / journal references will
   currently be classified as `factual_roundtrip_claim` and likely
   resolved as `unverifiable_v0`. Add a Type-5 layer when Track F
   delivers `literature_search`.

7. **Three-fixture seed is acknowledged seed, not statistical sample.**
   Track V was designed against 3 outputs containing 8 observations
   (~24 distinct claim-shape patterns at most). Generalisations beyond
   these seeds — including the rule-based-classification 80% target —
   are unverified.

---

## 6. Handoff notes for the next session

- **Expand fixtures.** Generate 20-30 additional naive-orchestrator
  outputs (mix of fixtures and synthetic cases). Per-fixture: re-run
  `verify()` against real MiniMax, record (claims_v1 verdict
  distribution, llm_call_count, rewritten_output). Annotate each
  CONTRADICTED / UNSUPPORTED / UNVERIFIABLE_V0 verdict by hand to build
  a precision/recall baseline.
- **Watch for over-fired classifications.** The classifier's regex
  library was tuned against 3 fixtures. Re-tune if the
  `classifier_source == "fallback"` rate exceeds 5 % across the
  expanded set.
- **Stage 4 hedging behaviour.** The live-glucose rewriter spontaneously
  added "may" / "potentially" hedges around `unverifiable_v0` claims it
  was asked to soften. Decide whether this is desirable language; if
  not, tighten `verifier/prompts/rewrite_verified.py`.
- **Layer D over-fire watch.** The current consistency prompt is
  conservative ("do not flag claims that are merely surprising"). If
  the expanded fixture set shows Layer D firing on H7-style chemistry
  knowledge claims, the prompt needs another guard.
- **Cost ceiling.** $0.07 / identification × 30 fixtures = ~$2 for the
  next live evaluation pass. Budget accordingly.
- **Replace `common.llm_client.extract_json_list`.** The verifier ships
  a local workaround (see §5 #3). When the upstream helper is fixed,
  delete `_parse_claim_list` from `verifier/claim_extractor.py` and
  switch back.
- **Two unit tests pin design constants** —
  `test_budget_ceiling_is_seven` (in `test_agent_cascade.py`) and the
  per-fixture call-count assertions in `test_agent_real_o1_outputs.py`.
  Bump them in lockstep with the design doc when the cascade shape
  changes.

---

## 7. Files added / modified this session

```
verifier/                              new package — top-level entry verify()
├── __init__.py
├── agent.py                           4-stage cascade orchestration
├── claim_classifier.py                Stage 2: rules + 1 batched LLM fallback
├── claim_extractor.py                 Stage 1: 1 LLM call, robust JSON parse
├── layers/
│   ├── biological.py                  Layer C (Type 3, source-first)
│   ├── consistency.py                 Layer D (Type 4, batched LLM)
│   ├── factual.py                     Layer B (Type 2, source-first + tool round-trip)
│   └── grounded.py                    Layer A (Type 1, pure source lookup)
├── prompts/                           4 prompt templates (no anti-hallucination phrasing)
├── rewriter.py                        Stage 4: rewrite-only; agent.py orchestrates re-verify
├── schemas.py                         ClaimType, ClaimVerdict, ExtractedClaim, ClassifiedClaim, VerifiedClaim, VerifiedIdentification
└── source_lookup.py                   field-path navigator over IdentificationReport

tests/test_verifier/                   new unit suite — 109 tests, all mocked
├── conftest.py                        glucose / caffeine / lcarnitine fixtures
├── test_agent_cascade.py
├── test_agent_real_o1_outputs.py      H1–H7 acceptance tests against verbatim O1 outputs
├── test_claim_classifier.py
├── test_claim_extractor.py
├── test_layer_biological.py
├── test_layer_consistency.py
├── test_layer_factual.py
├── test_layer_grounded.py
├── test_rewriter.py
└── test_source_lookup.py

tests/integration/test_verifier_e2e.py new gated test — runs once on glucose under MINIMAX_API_KEY
```

No file under `orchestrator/`, `tools/`, `schemas/`, `common/`, or
`docs/` was modified. The naive orchestrator's outputs continue to
land in `logs/llm_calls.jsonl` exactly as before; verifier rows join
them via `caller="verifier.<stage>.<func>"` and
`trace_id="<orchestrator_trace_id>_verified[_it]"`.
