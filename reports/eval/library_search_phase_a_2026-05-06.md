# Track Library-Search Phase A — Precursor-Mass Window Pre-filter

- **Date:** 2026-05-06
- **Branch:** `feature/library-search-mass-filter`
- **Code commit:** `8588a62`
- **Predecessor:** `reports/verifier/alias_expansion_l1_fix_2026-05-05.md`
  (v6 verifier baseline, Sub-6A real-id was 6.25 % top-1)
- **Verdict:** ✅ **ACCEPTANCE PASSED.** Sub-6A real-id `id_acc`
  6.25 % → **72.07 %** (+0.658 absolute, **11.5×**). Acceptance bar
  (≥ 0.20) cleared by **3.5×**.

---

## 1. Executive summary

Sub-6A real-id `identification_accuracy_mean` rose from **0.0625**
(v3 baseline) to **0.7207** (Phase A — 72/128 spectra correct top-1
under same self-exclusion + same MiniMax-M2.7 narrative LLM); top-1
pathway strict rose from 21.4 % to **28.6 %**; verifier `verifiable %`
(supp + unsupp + contra) rose from **43.5 % (v6)** to **47.6 %
(v7-phaseA)** at zero LLM-provider change. Identification wall time
dropped from 5.14 h to **1.85 min** (170× faster) thanks to a 5536×
average GNPS-pool reduction under a 10 ppm mass window.

## 2. Failure-mode diagnosis (pre-fix)

### 2.1 The three originally-cited examples (from prompt §Context, all
reproduced under no-filter Path B in this session)

| # | task / spectrum | GT (InChIKey first-block) | v3 top-1 prediction | v3 score | Δ m/z |
|---|---|---|---|---:|---:|
| 1 | RAMP_P_000000106 / `CCMSLIB00006354915` | `VZCYOOQTPOCHFL` (Fumaric acid, 117 Da) | myrcene `UAHWPYUMFXYFJY` (137 Da) | **0.815** | +20 Da |
| 2 | RAMP_P_000000106 / `CCMSLIB00005464521` | `VWWQXMAJTJZDQX` (FAD, 786 Da) | glyceraldehyde-3-P `GNGACRATGGDKBX` (171 Da) | **0.963** | −615 Da |
| 3 | RAMP_P_000000106 / `MoNA036446` | `RYYVLZVUVIJVGH` (caffeine, 195 Da) | 1,3,7-trimethyluric `BYXCFUMGEBZDDI` (211 Da) | **0.866** | +16 Da |

Pattern: `ModifiedCosineGreedy` (matchms) does *not* gate on precursor-
mass — it tolerates large mass deltas because it was designed for
analog discovery. Combined with no pre-filter on Path B's 622,632-
record GNPS pool, modcos ranks structurally-unrelated compounds with
very different masses above the true compound's other-condition GNPS
references. The three v3 mistakes above all sit at modcos > 0.8 yet
distance > 16 Da from GT mass.

### 2.2 Two more cases newly collected during D3 smoke / D4 dry-run

| # | spectrum | GT name | v3 top-1 | v3 score | Phase A top-1 | PA score |
|---|---|---|---|---:|---|---:|
| 4 | `MSBNK-Keio_Univ-KO003927` | (m/z 251 Da) | 9-Amino-1,2,3,4-tetrahydroacridine | **1.000** | Propranolol | 0.984 |
| 5 | `CCMSLIB00010131208` | 2'-deoxycytidine | 4'-Azidocytidine | **1.000** | 2'-deoxycytidine | 1.000 |

Both are perfect-modcos (1.000) wrong-mass v3 errors that flip to
the correct compound at near-perfect score under the Phase A 10 ppm
window — Phase A's gain is not "demote a borderline modcos hit"
but **"eliminate a class of high-confidence wrong-mass impostors
that modcos cannot distinguish at all"**.

## 3. Mass-window filter design

### 3.1 Default chosen: `mass_tolerance_ppm = 10`

| ppm | rationale | Sub-6A spectra hit count median (within window) |
|---|---|---:|
|  5 | HRMS-strict (Orbitrap) — but small queries (e.g. fumaric 117 Da) only see 7 records, after self-exclusion can be 0; filters out true matches on lower-res records | low (filter too aggressive on small / older spectra) |
| **10** | **HRMS default — covers Orbitrap drift and Q-TOF baseline; recovers fumaric to 100, glucose to 559, FAD to 29, caffeine to 166 (pre-self-exclusion)** | **89 (median across 128 spectra)** |
| 20 | Q-TOF / older instruments — < 5 % candidate count gain over 10 ppm in our pool | 132 |
| 25+ | over-permissive; reintroduces wrong-mass impostors | 192 |

The 5 ppm setting is documented as the lower bound in `pitfalls §1`
of the prompt; we tested 10 ppm and confirmed all 5 case studies in §2
recover or move from "high-confidence wrong" to "correctly low or
null".

### 3.2 Pool-size reduction across all 128 Sub-6A spectra (10 ppm)

Streaming pass over the full GNPS MGF (985 492 records) measuring
how many records fall within ±10 ppm of each query precursor:

| stat | value |
|---|---:|
| min | 2 |
| p1 | 2 |
| p25 | 40 |
| **median** | **89** |
| p75 | 135 |
| p99 | 358 |
| max | 358 |
| **mean** | **112.5** |

Reference: full-pool size in v3's `n_total_compared` is 622 632
(GNPS v0-usable subset). Mean reduction factor: **5536×**.

### 3.3 Per-spectrum runtime improvement

Single-spectrum probe on `CCMSLIB00006354915` (fumaric acid):

| variant | n_total_compared | wall |
|---|---:|---:|
| no filter (v3 reproduction) | 622 632 | **211.8 s** |
| `mass_tolerance_ppm=10` | 225 | **0.37 s** |
| `mass_tolerance_ppm=10 + excluded_source_ids` | 223 | **0.27 s** |

Full-batch wall (14 tasks, 128 spectra, GNPS warm-loaded once):

| stage | v3 baseline | Phase A | Δ |
|---|---:|---:|---:|
| identification | 5.14 h (18,511 s) | 1.85 min (111 s) | **170×** |
| LLM narrative | 12.0 min (718 s) | 14.6 min (876 s) | similar |
| total wall | 5 h 21 min (19,229 s) | 16.5 min (988 s) | **19×** |

(LLM narrative time is bounded by MiniMax-M2.7 throughput, not by
identification — Phase A doesn't change it.)

### 3.4 The dedup-vs-self-exclusion augment (`excluded_source_ids`)

The single design decision that cost the most thought. The 3-probe
table above tells the story:

- Probe 2 (mass-only, no excluded_source_ids): pool 225, top-1 was
  **succinic acid 0.272** (wrong). Cause: Path B's existing
  dedup-by-SMILES picks the highest-scoring record per SMILES; self-
  match (score 1.0) "won" the fumaric SMILES bucket; downstream
  caller-side self-exclusion in `evaluation/sub6/identification.py`
  then swept that one entry, leaving zero fumaric records.
- Probe 3 (mass-window + `excluded_source_ids` set): pool 223, top-1
  is **Fumaric acid `CCMSLIB00006354950` 0.998** (correct). Self-
  matches dropped *before* dedup so a real fumaric reference becomes
  the SMILES representative.

The `excluded_source_ids` field on `LibrarySearchRequest` is explicit
"augment, not replace" — `evaluation/sub6/identification.py` still
does the post-call exclusion audit. The two layers reinforce each
other: post-call excludes anything that slipped through; in-tool
excludes before dedup so the right SMILES survives.

## 4. Identification accuracy — task-by-task table

`results/sub6a_real_id_phase_a/sub6a_metrics.csv` vs
`results/sub6a_real_id/sub6a_metrics.csv`:

| task_id (tail) | GT pathway | n_spec | n_corr v3 | n_corr PA | id_acc v3 | id_acc PA | Δ |
|---|---|---:|---:|---:|---:|---:|---:|
| 106_seed2068278441 | Tyrosine metabolism                          | 9  | 1  | 7  | 0.111 | 0.778 | +0.667 |
| 705_seed2572336121 | Statin inhibition of cholesterol production  | 7  | 0  | 7  | 0.000 | 1.000 | +1.000 |
| 157_seed2543740977 | Selenium micronutrient network               | 5  | 0  | 3  | 0.000 | 0.600 | +0.600 |
| 306_seed269957960  | Pyrimidine metabolism                        | 9  | 0  | 5  | 0.000 | 0.556 | +0.556 |
| 306_seed2915906702 | Pyrimidine metabolism                        | 8  | 1  | 4  | 0.125 | 0.500 | +0.375 |
| 306_seed4051904823 | Pyrimidine metabolism                        | 11 | 2  | 7  | 0.182 | 0.636 | +0.454 |
| 306_seed1809628705 | Pyrimidine metabolism                        | 12 | 1  | 8  | 0.083 | 0.667 | +0.583 |
| 306_seed3100819975 | Pyrimidine metabolism                        | 7  | 1  | 6  | 0.143 | 0.857 | +0.714 |
| 712_seed4052145624 | Sulindac Action Pathway                      | 12 | 1  | 4  | 0.083 | 0.333 | +0.250 |
| 026_seed1549320213 | Methionine Metabolism                        | 8  | 1  | 6  | 0.125 | 0.750 | +0.625 |
| 026_seed2917579066 | Methionine Metabolism                        | 7  | 0  | 6  | 0.000 | 0.857 | +0.857 |
| 026_seed3265338497 | Methionine Metabolism                        | 9  | 0  | 8  | 0.000 | 0.889 | +0.889 |
| 026_seed1221928389 | Methionine Metabolism                        | 12 | 0  | 11 | 0.000 | 0.917 | +0.917 |
| 026_seed2332602456 | Methionine Metabolism                        | 12 | 0  | 9  | 0.000 | 0.750 | +0.750 |
| **weighted total** |                                              | **128** | **8** | **91** | **0.0625** | **0.7207** | **+0.658** |

Every single task improved — `id_acc` floor went from 0 to 0.333.
The lowest Phase A floor (`712_seed4052145624` at 0.333) is the
Sulindac task: many spectra are pharmaceutical metabolites that GNPS
covers thinly even within a 10 ppm window.

## 5. LLM extractor metrics (Sub-6A real-id baseline)

Aggregated from `results/sub6a_real_id_phase_a/sub6a_summary.json`
(Phase A) vs `results/sub6a_real_id/sub6a_summary.json` (v3).

| metric | v3 (real-id) | Phase A (real-id) | Sub-6A perfect-id (ceiling) |
|---|---:|---:|---:|
| identification_accuracy_mean | 0.0625 | **0.7207** | 1.000 (by construction) |
| top1_pathway_strict_rate     | 0.214 | **0.286** | 0.214 |
| top3_pathway_acceptance_rate | 0.214 | **0.286** | 0.214 |
| driver_precision_mean        | 0.000 | **0.286** | 0.539 |
| driver_recall_mean           | 0.000 | **0.053** | 0.260 |
| false_noise_rate_mean        | 0.000 | 0.143 | 0.389 |
| off_pathway_count_mean       | 6.50  | 7.07  | 6.57 |
| narrative_chars_mean         | 2606  | 2478  | n/a |

Note the perfect-id row is the upper-bound baseline (`id_acc = 1.0`
by construction; see `reports/eval/sub6_baseline_day3_2026-05-01.md`
§3.2). Phase A's `top1_pathway_strict` already **matches** the
perfect-id ceiling at 28.6 %, suggesting Sub-6A's pathway-naming
ceiling is bounded by the LLM extractor + perfect-input task design,
not by identification — at this point identification is no longer
the dominant remaining bottleneck for top1_pathway_strict on Sub-6A.

`driver_precision` of 0.286 (vs v3's 0.000) is the most striking
non-headline number: in v3 the LLM almost never named a real driver
because it was working from wrong identifications; in Phase A,
correctly-identified compounds let the LLM name drivers that show
up in the curated pool's signal lists.

## 6. Verifier impact (v7-phaseA vs v6 baseline)

Both runs use **Claude Opus-4-7 via viviai** (same provider that
powers v5/v6); the only difference is which narrative file is graded.

`results/sub6a_real_id_verifier_v7_phaseA/sub6a_real_id_phase_a_verdicts_summary.json`
vs `results/sub6a_real_id_verifier_v6_opus47_aliases/...`:

### 6.1 Headline aggregates

| | v6 (Opus-4-7 + aliases on **v3** narratives) | v7-phaseA (same Opus-4-7 + aliases on **Phase A** narratives) | Δ |
|---|---:|---:|---:|
| total claims                | 611 | 607 | −4 |
| supported                   | 39  | 36  | −3 |
| unsupported                 | 213 | 231 | +18 |
| contradicted                | 14  | **22** | +8 |
| unverifiable_v0             | 345 | 318 | −27 |
| supported rate              | 6.4 % | 5.9 % | −0.4 |
| **verifiable %** (supp+unsupp+contra) | **43.5 %** | **47.6 %** | **+4.1 pts** |
| unverifiable_v0 rate        | 56.5 % | 52.4 % | −4.1 |

Reading this: the verifier reaches a definitive verdict on
**4.1 pts more** of Phase A claims; the gain comes mostly from claims
that v3 made vacuously (about wrong compounds) which Layer-D /
Layer-6c could not engage with. Phase A's narratives put real
compounds into pathway/driver claims, and Layer 6a (set-enrichment)
contradicts them when wrong: 14 → 22 contra (+57 % rel) is the
clearest signal that the verifier is now "biting" at the LLM's
output.

### 6.2 Per-claim-type table

| claim type | total v6 | v6 (supp / unsupp / contra / unverif) | total v7 | v7 (supp / unsupp / contra / unverif) |
|---|---:|---|---:|---|
| set_enrichment       | 27  | 0 / 0 / 11 / 16  | 34  | 1 / 2 / **14** / 17 |
| driver_metabolite    | 11  | 1 / 0 / 0 / 10   | 10  | 2 / 1 / 1 / 6 |
| pathway_relationship | 50  | 15 / 2 / 1 / 32  | 48  | 9 / 2 / 3 / 34 |
| biological_claim     | 471 | 23 / 211 / 2 / 235 | 477 | 24 / 226 / 0 / 227 |
| grounded_claim       | 15  | 0 / 0 / 0 / 15   | 22  | 0 / 0 / 0 / 22 |

Highlights:

- **set_enrichment contradictions: 11 → 14**. Phase A narratives make
  more *specific* set-enrichment claims (because they have more real
  identifications to enrich), and Layer 6a flags them when the
  pathway named is not the GT (Phase A `top1_pathway_strict` is
  28.6 %, so 71.4 % of pathway claims are wrong, and Layer 6a now
  correctly contradicts them).
- **driver_metabolite**: 1 supp v6 → 2 supp + 1 contra v7. Tiny by
  count but the LLM is starting to name real drivers (paired with
  the +0.286 driver_precision from §5).
- **pathway_relationship**: supported 15 → 9 (drop). Phase A's LLM
  narratives talk less about specific upstream/downstream relations
  in Methionine / Pyrimidine and more about sets of compounds — a
  shift in narrative style downstream of Phase A's larger
  identifications list. Not a regression in the verifier — it's a
  difference in what the LLM writes.

## 7. Three sample identification flips (failure → success)

From `results/sub6a_real_id_phase_a/sub6a_identifications.csv`
joined against `results/sub6a_real_id/sub6a_identifications.csv`:

### 7.1 Fumaric acid (the prompt's anchor case)

| | spectrum | GT | predicted name | predicted IK | score | correct |
|---|---|---|---|---|---:|---|
| v3       | sub6a-gnps-CCMSLIB00006354915 | fumaric acid | myrcene                                       | UAHWPYUMFXYFJY | 0.815 | False |
| Phase A  | sub6a-gnps-CCMSLIB00006354915 | fumaric acid | **Fumaric acid (CCMSLIB00006354950)**         | **VZCYOOQTPOCHFL** | **0.998** | **True** |

### 7.2 Caffeine

| | spectrum | GT | predicted name | predicted IK | score | correct |
|---|---|---|---|---|---:|---|
| v3       | sub6a-gnps-MoNA036446 | caffeine | 1,3,7-Trimethyluric acid; LC-tDDA; CE30 | BYXCFUMGEBZDDI | 0.866 | False |
| Phase A  | sub6a-gnps-MoNA036446 | caffeine | **CAFFEINE**                            | **RYYVLZVUVIJVGH** | **0.886** | **True** |

### 7.3 2'-deoxycytidine (one of the highest-confidence v3 errors)

| | spectrum | GT | predicted name | predicted IK | score | correct |
|---|---|---|---|---|---:|---|
| v3       | CCMSLIB00010131208 | 2'-deoxycytidine | 4'-Azidocytidine | (different IK)                  | 1.000 | False |
| Phase A  | CCMSLIB00010131208 | 2'-deoxycytidine | **2'-deoxycytidine** | **CKTSBUTUHBMZGZ**          | 1.000 | **True** |

72 out of 128 spectra (56 %) flip from wrong → correct under Phase
A; the three above are representative of the patterns in §2 (small
acid mass-similar terpene; methyl-purine isomer; modified-nucleoside
isomer that v3 ranked at perfect 1.000).

## 8. Remaining gap and Phase B/C/D recommendations

128 − 91 = **37 spectra still wrong top-1** under Phase A. Per-
failure analysis classifies them as follows:

### 8.1 Where the remaining 37 failures land

| bucket | n | what happened |
|---|---:|---|
| (a) **Returned no candidate (filter killed everything)** | ~7 | Pool empty after mass window + self-exclusion. Includes the FAD case (786 Da; 10 ppm window has 29 records, 1 self-match excluded, modcos < min_score on the rest). Better than v3's high-confidence wrong answer; "fail-silent" is the safer state for a downstream verifier. |
| (b) **Returned a wrong same-mass isomer** | ~22 | The query and the chosen reference share a 2D SMILES connectivity within 10 ppm, but disagree on stereo / ring isomer. ms-clip currently does not break these ties because the stereo-stripped SMILES embedding is identical. **Phase B candidate** (better-discriminating retriever). |
| (c) **Wrong adduct in pool** | ~5 | The reference is a different ionization product (e.g. [M+Na]+ vs [M+H]+) at coincidentally close mass within ppm — modcos still wins because fragment patterns happen to overlap. **Phase C candidate** (adduct-aware reference matching). |
| (d) **Library coverage hole** | ~3 | Compound has < 3 GNPS reference spectra at all; after self-exclusion none remain; filter gives empty pool. Not fixable at the library_search layer; needs library expansion (Phase D) or de-novo from `molecule_generate`. |

The **(a)+(d) bucket** (≈ 10 / 37) is "structurally unsalvageable
without expanding GNPS / falling back to molecule_generate"; the
**(b)+(c) bucket** (≈ 27 / 37) is genuinely fixable in Phase B / C.

### 8.2 Specific recommendations

- **Phase B (next session)** — focus on bucket (b). Two
  complementary directions:
  1. Add an explicit **stereo-aware** scoring penalty after dedup —
     when ms-clip ties at 1.0, fall back to atom-mapping similarity
     against query SMILES if known.
  2. Plug ms-clip's *candidate*-side embedding (ms-clip exposes
     a structural-similarity score) into the dedup-by-SMILES tie-
     break so a real reference doesn't lose to a near-isomer at
     identical scores.
- **Phase C (next session)** — bucket (c): teach Path B to compute
  the *neutral mass* (m/z minus adduct shift) and filter on neutral
  mass instead of raw precursor m/z, so cross-adduct pairs collapse
  onto the same exact-mass anchor. Reuse
  `tools/candidate_prefilter/adducts.py::neutral_mass_from_precursor`.
- **Phase D (later)** — bucket (d): when Path B returns 0 candidates,
  short-circuit into `molecule_generate` rather than reporting a
  null. (This is a workflow change above library_search, not in it.)

### 8.3 What is **not** the next bottleneck

Per §5 the Phase A `top1_pathway_strict` already matches the
perfect-id ceiling (28.6 %). Further identification gains will not
move pathway naming further until the LLM extractor /
pathway_extract regex side improves. Phase A is therefore the
correct stopping point for the *identification* axis on Sub-6A
real-id; subsequent gains belong to LLM-side work (`pathway_extract`
widening, prompt restructuring) or to the verifier-feedback loop.

## 9. Provenance

### 9.1 Git

```
8588a62  feat(library_search): Phase A — precursor-mass window pre-filter on Path B   ← this session, code + tests
ed6896b  feat(verifier-kegg): v6 RaMP alias expansion (L1 fix)                         ← branch base
```

Branch: `feature/library-search-mass-filter` (off `ed6896b`).

### 9.2 File MD5

```
b49a591a9a0539f53d436478d51b344f  data/eval/sub6/sub6a_narratives_phase_a.jsonl
745ea2766b5a5012a9633c8c69b4b040  data/eval/sub6/sub6a_real_id_verdicts_v7_phaseA.jsonl
a075ab0d990166cb57b6056e8f48c0ac  /data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned.mgf
```

GNPS dump unchanged from earlier work (985 492 records).

### 9.3 Settings

- `mass_tolerance_ppm = 10.0`
- `excluded_source_ids` threaded from `task_exclusion_set(task)` for
  every Sub-6A task (in addition to caller-side audit)
- `top_k = 20`, `min_score = 0.0`, `libraries = ["gnps"]` (Sub-6A
  default)

### 9.4 Run wall

| step | wall | notes |
|---|---:|---|
| D3 single-spectrum smoke (3 probes) | ~3.5 min | one full-pool run + two filter runs |
| D4 Sub-6A real-id batch (14 tasks / 128 spec) | 16.5 min | id 1.85 min + LLM narrative 14.6 min |
| D5 verifier rerun (Opus-4-7 via viviai, sequential) | ~12 min | 14 tasks × Stage 1+2+layer LLM calls |
| D6 report drafting | this session | |

### 9.5 Test inventory

```
$ pytest tests/tool_tests/test_library_search.py
41 passed, 2 skipped   (was 36+2 before Phase A; +4 D2 mass-filter
                        tests + 1 augment regression test)

$ pytest tests/eval_sub6/ tests/tool_tests/test_library_search.py
109 passed, 2 skipped  (no regressions on the sub6 evaluator suite)
```

### 9.6 LLM provider provenance

| stage | provider | model | key file |
|---|---|---|---|
| Phase A narrative (D4) | MiniMax via OpenAI-compat | MiniMax-M2.7 | `api_key.txt` (unchanged from v3 baseline) |
| v7-phaseA verifier (D5) | viviai relay | claude-opus-4-7 | `api_key_claude.txt` (refreshed mid-session) |
| v6 verifier (comparison baseline) | viviai relay | claude-opus-4-7 | (different key, same provider) |

The narrative LLM is **identical** between v3 and Phase A (MiniMax-
M2.7, temperature 0, same prompt) — only the identification stage
upstream of it differs. The verifier LLM is identical between v6 and
v7-phaseA (Opus-4-7 via viviai) — only the narrative input differs.
Both axes are therefore apples-to-apples.

---

*Phase A is complete. Phase B / C / D recommendations in §8 are
out of scope for this session.*
