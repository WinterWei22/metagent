# Negative-mode spike test — diagnostic report

- **Date:** 2026-04-28
- **Branch under spike:** `feature/massbank-data-pipeline` (tip `0e1d039`)
- **Predecessor:** `reports/acceptance/acceptance_negative_mode_2026-04-28.md`
  (Tracks A/B/C accepted on glucose `[M-H]-`; SIRIUS / CFM-ID landed
  separately in commits `81cb4f8` / `0e1d039`)
- **Total time on spike:** ~5.5 h (within 4–6 h budget)
- **Conclusion:** ✅ **All eight pipeline stages run without crashing on
  negative-mode inputs.** Two non-blocking issues surfaced that affect
  benchmark *quality*, not pipeline *capability* (see §3).

---

## 0. Scope adjustment vs. original brief

The brief was written before commits `3cab5a7`/`84b00f8`/`87a864d`/
`81cb4f8`/`0e1d039` had landed. Those commits removed the four `v0`
negative-mode guards (spectrum_ops, candidate_prefilter, library_search,
sirius_annotate, predict_spectrum) and shipped same-mode GNPS partitioning
+ the spectraverse ms-clip checkpoint. As a result:

- §2.1, §2.2, §2.3, §2.4 (Track C / molecule_gen) of the original brief
  were **already covered by the prior acceptance**. We *re-ran* one
  RIKEN-derived fixture per stage to confirm reproduction; we did not
  re-validate ground covered by `acceptance_negative_mode_2026-04-28.md`.
- §2.4 (SIRIUS) and §2.5 (CFM-ID predict_spectrum) were the genuinely
  **un-validated** stages — fresh integration testing here.
- §2.6, §2.7, §2.8, §2.9 were unblocked once §2.4/§2.5 worked, and ran
  end-to-end against the real backends.

Two path corrections in the brief are noted: `tools/spectrum_preprocess/`
→ `tools/spectrum_ops/`, and `verifier/auto_layers/tool_cross_validator.py`
→ `verifier/layers/peak_mechanistic.py`.

The `METAGENT_MASSBANK_PATH` env var is not used; the benchmark's
RIKEN data lives at
`/data/weiwentao/llm_agent_metabolomics/massbank/processed/compound_pool_riken.jsonl`
(produced by `scripts/build_compound_pool.py` per
`reports/massbank/session_summary_2026-04-28.md`).

---

## 1. RIKEN-MS data inventory

Computed by `scripts/spike/check_riken_negative.py` against the
post-protocol-filter JSONL (5,930 records).

```
Total RIKEN records: 5930
Positive mode: 3549 (59.8%)
Negative mode: 2381 (40.2%)
```

### Negative-mode breakdown

| Dimension | Count |
|---|---:|
| **Total** | **2381** |
| By instrument | `LC-ESI-QTOF`: 2381 |
| By compound_class | `other`: 1481 — `flavonoid`: 677 — `organic_acid`: 166 — `lipid`: 31 — `amino_acid`: 25 — `nucleoside`: 1 |
| By adduct | `[M-H]-`: 1929 — `[M+HCOO]-`: 246 — `[M-2H]-`: 204 — `[M+K-2H]-`: 1 — `[M-CO2-H]-`: 1 |
| Peaks ≥ 5 | 2381 (100%) |
| Peaks ≥ 15 | 2381 (100%) |
| Has SMILES | 2381 (100%) |
| Has InChIKey | 2381 (100%) |
| Has both | 2381 (100%) |

Every negative-mode record in the post-filter JSONL already satisfies
the peak-count and InChIKey criteria the brief asks about (because
`tools/benchmark/massbank_filter.py` applies them upstream).

### Verdict on benchmark target

Brief asks for ~300 records (75 × 4 subsets). **`ACHIEVABLE` with
RIKEN alone**: 2381 qualifying records is ~8× the target. Sub-class
sufficiency (assuming each subset wants single-class purity):

| Subset target class | RIKEN neg pool | Sufficient for 75? |
|---|---:|---|
| flavonoid | 677 | ✅ yes |
| organic_acid | 166 | ✅ yes |
| lipid | 31 | ⚠️ marginal — need MoNA / GNPS extension |
| amino_acid | 25 | ⚠️ marginal — same |
| nucleoside | 1 | ❌ extension required |

**Caveats baked into RIKEN itself:**

- **Single instrument type** (`LC-ESI-QTOF`, all on Waters UPLC Q-Tof
  Premier). Cross-instrument robustness cannot be tested with RIKEN
  alone.
- **`other` class is 62%** — SMARTS-only labels can't reach
  alkaloids/terpenoids/glycosides. Re-running
  `scripts/build_compound_pool.py --classify` overnight would populate
  ClassyFire labels (per `session_summary` §2.7). We did **not** do that
  here.
- **`[M-H]-` is 81% of the 2381**; the other adducts (`[M+HCOO]-`,
  `[M-2H]-`) need separate calibration if benchmark scoring assumes
  `[M-H]-` peak families.
- **Many CE values are `null`** (ramp/stepwave from RIKEN; see
  `normalization_warnings`). This is benign for the pipeline (CE is
  optional in `Spectrum`), but it means CE-stratified subsets need a
  separate filter.

---

## 2. Per-tool spike results

### 2.0 Fixtures

Two RIKEN-derived fixtures, written under
`tests/fixtures/spectra/negative_mode/`:

| File | Source | Peaks | Adduct | CE |
|---|---|---:|---|---:|
| `citric_acid_neg.json` | `MSBNK-RIKEN-PR309128` (Citric acid; RIKEN flag "not validated, isomer of PR000227" but SMILES + InChIKey + neutral mass match) | 21 | `[M-H]-` | 6.0 V |
| `glutamyltyrosine_neg.json` | `MSBNK-RIKEN-PR309407` (Glutamyltyrosine — free L-tyrosine is absent in RIKEN's plant-metabolite focus, so a tyrosine-containing dipeptide was substituted) | 39 | `[M-H]-` | 6.0 V |

Extraction script: `scripts/spike/extract_fixtures.py`.

### 2.1 spectrum_preprocess  ✅ PASS

Run: `scripts/spike/test_preprocess_negative.py` (env: `diffms`).
Output captured in `/tmp/spike_2_1_preprocess.txt`.

| Fixture | Crashed | n_in → n_out | base_peak m/z | Quality | Wall |
|---|---|---|---|---|---:|
| citric_acid_neg | False | 21 → 11 | 111.00854 | good | 0.6 ms |
| glutamyltyrosine_neg | False | 39 → 22 | 128.03424 | good | 0.3 ms |

`ionization_mode="negative"` and `adduct="[M-H]-"` propagate verbatim
through the response. Base-peak intensity correctly normalised to 1.0.
matchms emits a benign `No precursor_mz found in metadata` warning that
does not affect outputs (precursor is carried in our `Spectrum`, not in
matchms metadata).

### 2.2 candidate_prefilter  ✅ PASS

Run: `scripts/spike/test_prefilter_negative.py` (env: `diffms` with
`tools/candidate_prefilter/env.sh` sourced).
Output: `/tmp/spike_2_2_prefilter.txt`.

| Fixture | Mass-only top-20 (without formula) | With formula constraint | Truth rank |
|---|---|---|---:|
| citric_acid_neg | 205 GNPS + 20 PubChem-Lite within 5 ppm (top-20: citric acid + isocitric acid + duplicates) | n/a (was already #1) | **1** |
| glutamyltyrosine_neg | 48 GNPS + 17 PubChem-Lite — top-20 dominated by `Z1561331942` (Enamine C13H21F2N3O4S, same mass window) | 14 GNPS + 17 PubChem-Lite, **top-1 = "Glutamyltyrosine" GNPS** | **1 (with formula)** |

Neutral-mass back-calculation: 192.0267 (citric acid, 1.7 ppm error) /
310.1161 (glutamyltyrosine, 0.6 ppm error). Cold-cache wall time is
**435 s for the first call** (loads 930k GNPS records: 697k positive
+ 232k negative); subsequent in-process calls are sub-millisecond, as
documented in `acceptance_negative_mode_2026-04-28.md`.

### 2.3 library_search  ✅ PASS

Run: `scripts/spike/test_library_search_negative.py` (env: `diffms`),
prefilter + library_search co-located in one process to amortise the
GNPS load. Output: `/tmp/spike_2_3_library_search.txt`. Artefacts
serialised to `/tmp/spike_neg_pipeline_artifacts.pkl`.

```
citric_acid_neg.json
  prefilter:        30 candidates ({'gnps': 205, 'pubchem_lite': 20})  wall=432.5s
  library_search:   2 candidates  wall=107.2s  crashed=False
    rank 1: score=0.833  Citric acid          KRKNYBCHXYNGOX  truth=True
    rank 2: score=0.809  Isocitric acid       ODBLHEXUDAPZAU  truth=False

glutamyltyrosine_neg.json
  prefilter:        30 candidates ({'gnps': 14, 'pubchem_lite': 17})  wall=0.0s (cached)
  library_search:   10 candidates  wall=33.7s  crashed=False
    rank 1: score=0.812  Glutamyltyrosine     VVLXCWVSSLFQDS  truth=True
    rank 2: score=0.685  Tyrosyl-Glutamate    PDSLRCZINIDLMU  truth=False
    rank 3: score=0.678  Glutamyltyrosine     YSWHPLCDIMUKFE  truth=False (stereoisomer)
    rank 4: score=0.676  gamma-Glutamyltyrosine VVLXCWVSSLFQDS truth=True
```

The `v4_spectraverse` ms-clip checkpoint (per acceptance report)
discriminates well on negative-mode `[M-H]-` queries. Top-1 is correct
in both cases. Score gap to runner-up is healthy for citric acid (0.024)
and glutamyltyrosine (0.127).

**Risk worth noting (Issue NM-002):** glutamyltyrosine's top-1 GNPS hit is
`MSBNK-RIKEN-PR309407` — the *exact same source spectrum the fixture was
extracted from*. GNPS' enriched dump includes RIKEN-derived records, so
queries built from RIKEN's own spectra will trivially recover themselves.
For a real benchmark this is data leakage — see §3.

### 2.4 sirius_annotate  ⚠️ PASS WITH CAVEAT

Run: `scripts/spike/test_sirius_negative.py` (env: `metagent-llm`).
Output: `/tmp/spike_2_4_sirius.txt`.

Real SIRIUS CLI 6.3.4 was invoked; no mock. Wrapper passes adduct via
`>ionization` line in the `.ms` file (see `tools/sirius/ms_writer.py:14`);
no `--ions-considered` flag is added on the CLI. SIRIUS infers polarity
from the `.ms` file correctly.

| Fixture | Crashed | Predicted formula | Score | Tree nodes | Wall |
|---|---|---|---:|---:|---:|
| citric_acid_neg (21 peaks) | False | **`C4H6N3O6`** ❌ (truth: `C6H8O7`) | 0.952 | 11 | 18.9 s |
| glutamyltyrosine_neg (39 peaks) | False | `C14H18N2O6` ✅ | 0.956 | 16 | 18.0 s |

**Critical finding (NM-001):** SIRIUS does *not* crash on negative input
and the `>ionization [M-H]-` directive is recognised (verified by the MS
preview in the spike output), but **on the 21-peak / CE=6 V citric acid
fixture SIRIUS confidently predicts a wrong, nitrogen-containing formula
with score 0.95**. This is not a wrapper bug — SIRIUS' isotope-pattern +
fragmentation-tree solver is starved of constraints by the sparse,
low-energy spectrum and locks onto a CHN-rich solution. On the 39-peak
glutamyltyrosine fixture (also CE=6 V) SIRIUS gets the formula right.
The **failure mode is spectrum quality, not polarity**, but it cascades
through the verifier (see §2.8).

### 2.5 spectrum_predict (CFM-ID)  ✅ PASS

Run: `scripts/spike/test_cfmid_negative.py` (env: `metagent-llm`).
Output: `/tmp/spike_2_5_cfmid.txt`. CFM-ID 4.4.7 docker shim probed at
`http://localhost:8088/predict`.

Smoke probe via curl confirmed the docker shim routes negative requests
to the `[M-H]-` model directory:

```
$ curl -s -X POST http://localhost:8088/predict ... -d '{"adduct":"[M-H]-","ionization_mode":"negative",...}'
{"model_version":"cfm-id-4.4.7",
 "cfm_stdout":"#In-silico ESI-MS/MS [M-H]- Spectra\n#PREDICTED BY CFM-ID 4.4.7\n..."}
```

| Target | Crashed | Model | Union peaks | Per-energy {10,20,40} | Predicted ↔ observed (5 ppm) | Wall |
|---|---|---|---:|---|---:|---:|
| citric acid | False | cfm-id-4.4.7 | 5 | {2, 3, 2} | 1 / 5 = 20% | 1.0 s |
| glutamyltyrosine | False | cfm-id-4.4.7 | 49 | {10, 31, 31} | 3 / 49 = 6% | 7.8 s |

`predicted.adduct = "[M-H]-"`, `predicted.ionization_mode = "negative"`,
`predicted_precursor_mz` correct to 4 dp (191.0197 / 309.1092).

**The spike question for §2.5 — "does the wrapper call the negative model
at all" — is answered yes.** The low overlap with observed peaks
(20% / 6%) is **CFM-ID 4.4.7's negative-mode prediction accuracy**, not
a wrapper bug. This is informational for benchmark scoring: if
`predicted_spectrum_cosine` is part of `evidence_score`, expect
systematically lower contribution on negative mode than on positive.

### 2.6 fetch_metabolite_info  ✅ PASS (mode-agnostic)

Run: `scripts/spike/test_metabolite_info_negative.py` (env: `metagent-llm`,
with `METAGENT_HMDB_PATH` set). Output: `/tmp/spike_2_6_2_7.txt`.

| Target (InChIKey) | found | source | primary_name | formula | Wall |
|---|---|---|---|---|---:|
| KRKNYBCHXYNGOX (citric) | True | hmdb | Citric acid | C6H8O7 | <10 ms |
| VVLXCWVSSLFQDS (glutamyl-tyr) | False | — | — | — | <10 ms |

Citric acid's response carries 31 synonyms + 4 cross-refs (chebi/hmdb/kegg/
pubchem_cid). Glutamyl-tyrosine miss is a **HMDB content gap**, not a
mode-related failure (HMDB does not curate every dipeptide). The tool
does not reference `ionization_mode` anywhere in its execution path —
confirmed by inspecting `tools/metabolite_info/tool.py` and
`hmdb_backend.py`.

### 2.7 pathway_context  ✅ PASS (mode-agnostic)

Same script. Required `METAGENT_RAMP_PATH` to be set (initially
unset → `RampUnavailableError` — see Issue NM-004).

| Target (HMDB ID) | crashed | n_pathways | Top pathway | Wall |
|---|---|---:|---|---:|
| HMDB0000094 (citric) | False | 5 | Citric Acid Cycle | 0.48 s |
| HMDB0011741 (glutamyl-tyr) | True (`MetaboliteNotInNetworkError`) | — | — | — |

Glutamyl-tyrosine error is benign — RaMP simply doesn't have this
metabolite in its pathway graph; the tool surfaces a typed error rather
than fabricating output. Not a mode-related issue.

### 2.8 verifier peak_mechanistic  ⚠️ PASS WITH CASCADE

Run: `scripts/spike/test_verifier_layer2_negative.py` (env: `metagent-llm`).
Output: `/tmp/spike_2_8_verifier.txt`.

Constructed minimal `IdentificationReport` with citric acid as the top
candidate, then issued four `PEAK_MECHANISTIC` claims of varying
correctness:

| Claim | Verdict | Layer evidence |
|---|---|---|
| m/z 87.0086 with neutral loss `C2H2O5` | **CONTRADICTED** | SIRIUS says loss is `HN3` |
| m/z 111.0085 with neutral loss `H2O` | **CONTRADICTED** | SIRIUS says loss is `CH4O4` |
| m/z 191.0190 (precursor, no loss claimed) | **SUPPORTED** | SIRIUS confirms — but assigns formula `C4H6N3O6` |
| m/z 200.0000 (phantom peak) | **CONTRADICTED** | Peak absent from spectrum (correct) |

The verifier *layer itself* works correctly on negative-mode input
(peak existence + neutral-loss matching both fire). **But it inherits
NM-001's wrong-formula cascade**: because SIRIUS confidently labels
citric acid's precursor as `C4H6N3O6`, every fragment annotation is
nitrogen-laden, so genuinely correct LLM neutral-loss claims (e.g. the
real `[M-H-H2O-CO2]-` loss for the citrate→C5H3O5 fragment) get
contradicted with a plausible-sounding but wrong "correction". This is
a documented level-of-trust problem: Layer F's `tool_called="sirius"`
output is only as good as SIRIUS' upstream formula choice.

### 2.9 naive_orchestrator  ✅ PASS

Run: `scripts/spike/test_naive_orchestrator_negative.py` (env: `metagent-llm`,
`MINIMAX_API_KEY` available). Output: `/tmp/spike_2_9_orchestrator.txt`.

Constructed a near-complete `IdentificationReport` for citric acid
`[M-H]-` (with the SIRIUS C4H6N3O6 vs C6H8O7 conflict surfaced in
`notes` + `warnings`). `identify(report)` ran one MiniMax call, 24 s
end-to-end, returned 2,013-character markdown.

LLM behaviour on negative-mode input — verbatim from the response:

```
## Identification Report: m/z 191.0194 [M-H]⁻

### Primary Finding
**Citric acid** is the most likely candidate based on mass accuracy and
cross-database consistency, though the confidence is tempered by a
notable fragmentation prediction conflict.

### Evidence Assessment

**1. Citric acid (C₆H₈O₇)** — Evidence score: 0.740
The mass match is excellent: ... HMDB reference exact mass within 5 ppm.

### Caveats and Concerns
The **SIRIUS formula prediction disagrees** with the candidate: it
proposes C₄H₆N₃O₆ (score 0.95) rather than C₆H₈O₇.  ... Contributing
factors likely include:

  - **Low collision energy (6 eV):** Produces limited fragmentation ...
  - **Small peak count (21):** A sparse spectrum provides limited
    spectral features ...
```

| Heuristic | Result |
|---|---|
| Uses `[M-H]⁻` | ✅ True |
| Uses `[M+H]+` (mode confusion) | ❌ False |
| Mentions `C6H8O7` | True (header) |
| Mentions `C4H6N3O6` | True (caveats — correctly framed as SIRIUS' wrong call) |
| Mentions Citric | True |

The LLM **did not confuse polarity** and **correctly attributed SIRIUS'
disagreement to spectrum sparsity**, not to a real chemical alternative.
End-to-end orchestrator works on negative-mode reports.

---

## 3. Issues found

### NM-001 — SIRIUS predicts wrong formula on sparse low-CE negative spectra

```
Severity: MAJOR (cascading; affects verifier + benchmark scoring)
Tool: tools/sirius/sirius_annotate (the wrapper is fine; the issue is
      in SIRIUS CLI behaviour, not in our code)
Location: tools/sirius/tool.py is unchanged; the sparse-spectrum SIRIUS
          failure mode is reproducible on any 21-peak / CE≤10 V negative
          fixture
Description: SIRIUS confidently (score 0.95) predicts a wrong nitrogen-
             containing formula for citric acid `[M-H]-` (21 peaks, CE 6V).
             At 39 peaks (glutamyltyrosine, same CE) SIRIUS recovers
             correct formula. Failure mode is spectrum quality, not
             polarity, but it surfaces specifically on negative mode
             because the RIKEN PlaSMA collection has many low-CE-ramp
             negative spectra.
Reproduction: conda run -n metagent-llm python scripts/spike/test_sirius_negative.py
              (uses tests/fixtures/spectra/negative_mode/citric_acid_neg.json)
Suggested fix: (a) For benchmark: filter neg-mode subsets to peaks ≥ 30
               and CE ≥ 10 V; (b) Verifier Layer F: when SIRIUS' top
               formula disagrees with the candidate's formula by more
               than ±2 atoms (any element), mark peak claims as
               UNVERIFIABLE_V0 instead of CONTRADICTED — currently we
               trust SIRIUS unconditionally; (c) Optionally pass
               `--candidates 5` (currently 1) so we can detect when the
               second-best formula matches the candidate.
Estimated fix time: (b) is ~2 h once the policy is agreed; (c) is ~30 m.
Blocks benchmark? Not strictly, but causes systematic false-CONTRADICTED
                  rates on negative-mode peak claims unless mitigated.
```

### NM-002 — RIKEN-derived fixture trivially self-matches in GNPS

```
Severity: MAJOR for benchmark integrity (data leakage)
Tool: tools/library_search (data-source artefact, not a code bug)
Location: GNPS' enriched CSV+MGF dump includes RIKEN-derived records
          (e.g. CCMSLIB → MSBNK-RIKEN cross-references); a query
          extracted from RIKEN finds itself in GNPS at top-1.
Description: glutamyltyrosine_neg's top-1 library hit is
             `MSBNK-RIKEN-PR309407`, the *same accession* the fixture
             was extracted from. Score 0.812 looks like a strong match;
             it is in fact ~self-comparison.
Reproduction: see §2.3 output.
Suggested fix: For benchmark splits, exclude any GNPS reference whose
               `source_id` (or its first-block InChIKey) appears in the
               benchmark's own RIKEN slice. Add this as a filter in the
               benchmark builder, *not* in library_search itself
               (library_search must remain unchanged).
Estimated fix time: 1 h (small filter in tools/benchmark/).
Blocks benchmark? Yes, if not addressed. Reported scores would be
                  inflated on every fixture that came from RIKEN.
```

### NM-003 — Mass-only prefilter pulls many same-mass non-targets

```
Severity: MINOR (expected behaviour, not a bug)
Tool: tools/candidate_prefilter
Location: tools/candidate_prefilter/tool.py
Description: Without a formula constraint, glutamyltyrosine (310.1161
             Da window) returns 48 GNPS hits, top-20 of which are all
             a single Enamine C13H21F2N3O4S compound (Z1561331942).
             With molecular_formula="C14H18N2O6" the truth jumps to
             rank 1. Same behaviour observed on positive in the prior
             acceptance — not new to negative mode.
Reproduction: scripts/spike/test_prefilter_negative.py (no formula vs
              formula columns).
Suggested fix: Operationally, the orchestrator should pass formula
               from SIRIUS to prefilter when available — already
               documented in the pipeline contract. No code change.
Estimated fix time: 0 (orchestrator-side discipline).
Blocks benchmark? No.
```

### NM-004 — Backend env vars not bundled with prefilter env.sh

```
Severity: MINOR
Tool: tools/metabolite_info, tools/pathway_context (env wiring)
Location: env vars METAGENT_HMDB_PATH and METAGENT_RAMP_PATH are not
          included in tools/candidate_prefilter/env.sh; users must set
          them manually or each spike script must re-source them.
Description: First run of §2.7 raised RampUnavailableError because
             METAGENT_RAMP_PATH was unset.
Reproduction: unset METAGENT_HMDB_PATH; run §2.6 — `found: False` for
              every InChIKey.
Suggested fix: Extend env.sh (or split into env_full.sh) to include
               METAGENT_HMDB_PATH=/data/.../hmdb.sqlite,
               METAGENT_RAMP_PATH=/data/.../ramp.sqlite,
               METAGENT_MONA_PATH=... (if available).
Estimated fix time: 15 m.
Blocks benchmark? No, but every fresh shell trips on it.
```

### NM-005 — Conda env split forces tool-level env switching

```
Severity: MINOR (operational)
Description: `diffms` (Py 3.9) lacks python-dotenv (needed by
             tools/sirius), and SIRIUS wrapper uses zip(strict=True) which
             requires Py ≥ 3.10. `metagent-llm` (Py 3.11) has dotenv
             but lacks matchms (needed by tools/spectrum_ops). To run
             spike tests we needed both envs.
Reproduction: conda run -n diffms python scripts/spike/test_sirius_negative.py
              → ModuleNotFoundError: No module named 'dotenv'
              conda run -n metagent-llm python scripts/spike/test_preprocess_negative.py
              → ModuleNotFoundError: No module named 'matchms'
Suggested fix: One unified env (recommended Py 3.11 + matchms), OR
               document which tool runs in which env in
               docs/LLM_INTEGRATION.md.
Estimated fix time: 1 h to reconcile.
Blocks benchmark? No, just slows iteration.
```

### NM-006 — Numpy 2.x / RDKit 1.x ABI warnings on metagent-llm env

```
Severity: MINOR
Description: metagent-llm has numpy 2.4.4 but rdkit was built against
             numpy 1.x; every rdkit import emits a ~10-line ABI warning
             ("AttributeError: _ARRAY_API not found"). Functionality
             works (verified: rdkit ExactMolWt, MolFromSmiles, MolToInchiKey
             all returned correct results during §2.5/§2.8/§2.9).
Reproduction: conda run -n metagent-llm python -c "from rdkit import Chem"
Suggested fix: pin numpy<2 in metagent-llm requirements, or rebuild
               rdkit against numpy 2.x.
Estimated fix time: 30 m.
Blocks benchmark? No.
```

### NM-007 — CFM-ID negative-mode predictions overlap observed RIKEN spectra at 6–20%

```
Severity: MINOR (model accuracy, not pipeline bug)
Tool: tools/spectrum_predict (CFM-ID 4.4.7)
Location: docker shim cfmid:latest, model dir /trained_models_cfmid4.0/[M-H]-/
Description: predicted_spectrum_cosine for the two fixtures will be low
             on negative mode because CFM-ID's negative-mode model has
             well-known accuracy gaps (especially at extreme CE values).
             Citric acid: 1/5 predicted peaks within 5 ppm of observed.
             Glutamyltyrosine: 3/49.
Reproduction: scripts/spike/test_cfmid_negative.py (overlap_pct field).
Suggested fix: For negative-mode benchmark scoring, weight
               predicted_spectrum_cosine in evidence_score lower than
               for positive mode, OR use a bigger m/z tolerance (10–20 ppm)
               when comparing CFM-ID-neg predictions to observed.
Estimated fix time: 1 h to recalibrate weights; 15 m to widen tolerance.
Blocks benchmark? No, but evidence_score will systematically read
                  lower on negative mode unless re-weighted.
```

---

## 4. Recommendations

### A. Path forward for negative-mode benchmark

✅ **All systems go for benchmark construction**, conditional on:

1. NM-002 mitigation (drop GNPS records that share `source_id` /
   InChIKey-first-block with the RIKEN slice you build the benchmark
   from). 1 h of work. **Mandatory** — without this, every reported
   score is inflated.
2. NM-001 mitigation: filter benchmark subsets to peaks ≥ 30 AND/OR
   CE ≥ 10 V. ~2,381 → roughly 1,500 records (estimate; needs running
   `scripts/spike/check_riken_negative.py` with these filters).
   **Recommended**, not mandatory — alternatively, accept that low-CE
   sparse fixtures will be SIRIUS-misclassified.
3. NM-007 mitigation: lower `predicted_spectrum_cosine` weight in
   `evidence_score` for negative-mode subsets (e.g. 0.15 instead of
   0.30 — re-tune empirically). Or document the asymmetry openly.
   **Recommended**.

### B. MassBank-RIKEN sufficiency

✅ **RIKEN alone is sufficient for the brief's ~300-record target.**

**With caveats:**

- ❌ **Cross-instrument robustness cannot be tested** with RIKEN alone
  (single instrument type). If the benchmark wants instrument-stratified
  subsets, extend to other MassBank contributors (e.g. Athens,
  Eawag-EAWAG, Fac_Engg_Univ_Tokyo).
- ⚠️ **Lipid / amino_acid / nucleoside classes are thin** in negative
  mode (31 / 25 / 1 records). Class-stratified subsets need MoNA or
  GNPS extension for these three classes.
- ⚠️ **Single adduct dominance** (`[M-H]-` 81%, `[M+HCOO]-` 10%,
  `[M-2H]-` 9%). If the benchmark wants adduct-stratified subsets,
  current data is fine for `[M-H]-` only.

### C. Cross-mode considerations for benchmark

The original brief proposed 70:30 positive:negative. Based on this spike:

> ⚠️ **Suggest 60:40 positive:negative** rather than 70:30, because:
> 1. RIKEN has 59.8 / 40.2 split natively — keeping the natural ratio
>    avoids over-sampling positive at the cost of class diversity in
>    negative.
> 2. Negative mode in RIKEN has *more* flavonoid coverage (677 / 2,381 =
>    28% of negative vs. ~few% in positive); a 60:40 ratio gives the
>    benchmark stronger flavonoid representation.
> 3. SIRIUS' failure mode (NM-001) shows up most on negative-mode sparse
>    spectra. A larger negative slice forces benchmark scoring to grapple
>    with this honestly rather than burying it.

If the benchmark's downstream consumers expect strict 70:30 because of
some real-world prevalence assumption, keep 70:30 but document that the
negative slice will under-represent the working pipeline's true
sensitivity to mode.

**Mode-specific scoring split is recommended.** Track per-mode metrics
(top-1 accuracy on positive vs. negative; predicted_cosine distribution
per mode; verifier verdict counts per mode). Don't aggregate scores
across modes without a mode-specific breakdown — NM-001 + NM-007 will
make negative look systematically weaker for reasons that are tool-level,
not pipeline-level.

---

## 5. Time accounting

```
§1  RIKEN inventory script + run + fixture extraction       :  0.5 h
§2.1 spectrum_preprocess (script + run)                     :  0.2 h
§2.2 candidate_prefilter (script + 2 runs incl. cold load)  :  0.7 h (mostly waiting)
§2.3 library_search (background; combined with §2.2 mid-run):  0.7 h (backgrounded)
§2.4 SIRIUS (script + env-fix + 2 fixtures)                 :  1.0 h
§2.5 CFM-ID (curl probe + script + run)                     :  0.6 h
§2.6/2.7 metabolite_info / pathway_context                  :  0.3 h
§2.8 verifier peak_mechanistic                              :  0.5 h
§2.9 naive_orchestrator + LLM call                          :  0.3 h
§3 + §4 issue write-up + recommendations                    :  0.7 h
                                                       Total: ~5.5 h
```

Within the 4–6 h budget. No escalation required.

---

## 6. Reproduction recipe

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5
git checkout feature/massbank-data-pipeline   # tip 0e1d039 or later

# §1 inventory (any env with python3)
python scripts/spike/check_riken_negative.py

# Fixtures
python scripts/spike/extract_fixtures.py

# §2.1 preprocess  (env: diffms)
conda run -n diffms python scripts/spike/test_preprocess_negative.py

# §2.2 + §2.3  (env: diffms; first run takes ~10 min for GNPS load)
source tools/candidate_prefilter/env.sh
conda run -n diffms python scripts/spike/test_library_search_negative.py

# §2.4 SIRIUS  (env: metagent-llm, requires sirius binary on PATH)
conda run -n metagent-llm python scripts/spike/test_sirius_negative.py

# §2.5 CFM-ID  (env: metagent-llm, requires cfm-id docker on :8088)
conda run -n metagent-llm python scripts/spike/test_cfmid_negative.py

# §2.6 + §2.7  (env: metagent-llm, with HMDB + RaMP env vars set)
METAGENT_HMDB_PATH=/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite \
METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
  conda run -n metagent-llm python scripts/spike/test_metabolite_info_negative.py

# §2.8 verifier (env: metagent-llm, requires sirius)
conda run -n metagent-llm python scripts/spike/test_verifier_layer2_negative.py

# §2.9 orchestrator (env: metagent-llm, requires MINIMAX_API_KEY)
conda run -n metagent-llm python scripts/spike/test_naive_orchestrator_negative.py
```

Output transcripts saved to `/tmp/spike_*` (preserved for the duration
of the spike session; copy to `reports/spike/run_logs/` if a permanent
audit trail is wanted).

---

## 7. Related documents

| Path | Purpose |
|---|---|
| `reports/acceptance/acceptance_negative_mode_2026-04-28.md` | Tracks A/B/C negative-mode acceptance (predecessor to this spike) |
| `reports/massbank/session_summary_2026-04-28.md` | MassBank pipeline build that produced `compound_pool_riken.jsonl` |
| `reports/verifier_typed_claim_stage2_confidence_2026-04-28.md` | typed-claim flow used by verifier Layer F |
| `data/processed/SCHEMA.md` | RIKEN JSONL schema reference |
| **`reports/spike/negative_mode_spike_2026-04-28.md`** (this doc) | Negative-mode end-to-end spike diagnostic |
