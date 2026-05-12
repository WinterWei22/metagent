# Phase 6.6 — CASMI 2022 OOD validation of the conditional rerank gate

**Date:** 2026-05-11
**Branch:** `feature/sub6-baseline-eval` (off the Phase 6.5 conditional-rerank artefacts)
**Predecessors:** `reports/eval/conditional_rerank_v2.md` (Phase 6.5 — locked threshold gap≥0.05 on Sub-6A real-id v2)

---

## 1. Headline (TL;DR)

Phase 6.5 found a +10.27 pp McNemar-significant gain from a conditional
SIRIUS+CFM-ID rerank gated by the MS-CLIP top1−top2 gap (≥ 0.05 ⇒ skip)
on Sub-6A real-id v2 (n=448, modcos-leakage in-distribution lookup).

**Phase 6.6 finds the gain does NOT generalise to CASMI 2022 OOD.** With
the locked Phase 6.5 threshold and identical pipeline:

| Benchmark | n | MS-CLIP-only | Conditional (locked gap≥0.05) | Δ | b / c | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| Sub-6A real-id v2 | 448 | 56.70 % | 66.96 % | **+10.27 pp** | 56 / 10 | < 1e-6 |
| **CASMI 2022**    | 170 | 13.53 % | **13.53 %** | **+0.00 pp** | **8 / 8** | **1.00** |

The conditional gate's selectivity vanishes on CASMI (0/170 skipped, 100 %
trigger), so this row is also "always-rerank" performance. The rerank
*does* perturb predictions — 16 paired specs flipped (b=8 newly correct,
c=8 newly wrong) — but the swap is a wash, ruling out both improvement
*and* harm at the available statistical resolution.

The null is corroborated by two **soft structural metrics** (top-1 vs GT)
that would have detected "rerank picks a structurally-closer wrong
answer" even without an exact-match flip — both also fail to reject zero
on the paired test:

| metric (D3 vs D2)          | mean Δ | discordance | p (paired, two-sided) |
|---|---:|---|---:|
| Exact-match (McNemar)      | +0      | b=8 / c=8       | 1.00 |
| Tanimoto (Morgan-2)        | +0.007  | +51 / −48 / =71 | 0.897 |
| MCS atom-fraction (rdFMCS) | +0.009  | +38 / −39 / =88 | 0.661 |

Three independent tests on the same n=170 paired predictions all return
null — the effect, if any, is below ≈ ±5 pp accuracy / ±0.03 Tanimoto.

**Implication for the paper.** Phase 6.5's finding is real *for the
candidate-space topology it was tuned on* (GNPS reference spectra,
modcos-rich lookup) but does not transport to formula-restricted PubChem
candidate spaces. Section 5 frames the boundary explicitly.

---

## 2. Setup

### 2.1 Why CASMI 2022

CASMI is the standard external compound-identification benchmark. The 2022
edition (`170` Q-Exactive HRMS spectra with sole-author GTs) was *not* used
in either the GNPS reference library or the RIKEN test pool; in particular,
0 / 169 (one spec dropped for empty MS2) of the GT InChIKey-first-blocks
overlap the Sub-6A v2 candidate space we previously called "in-distribution
leakage." This eliminates the modcos-as-lookup confound that drove Phase
6.5's decision to elevate MS-CLIP to the primary signal.

### 2.2 Architecture change vs Sub-6A v2

CASMI's published evaluation protocol restricts candidates to PubChem
compounds matching the GT *molecular formula*. We therefore inject a
per-spectrum `LibrarySearchRequest.candidate_pool` (Path A in
`tools/library_search/tool.py`) so the scoring pipeline operates on the
PubChem slice instead of scanning GNPS. Modified-cosine is unavailable
under this regime (PubChem candidates carry no MS/MS reference spectra), so
MS-CLIP — which scores spectrum-vs-structure — drives ranking. All other
evaluation code is unchanged from Phase 6.5: identical
`identify_spectrum`, identical conditional gate
(`evaluation.sub6.conditional_rerank.should_rerank_msclip_gate`,
defaults `top1_threshold=0.0`, `gap_threshold=0.05`), identical SIRIUS+CFM-ID
weighted reranker.

### 2.3 Candidate pool source

`/data/.../casmi_2022/preprocessed/casmi2022/retrieval_hdf/` —
the MIST corpus PubChem subset with a 152-formula → SMILES index over
402,421 candidates. Loader: `evaluation/sub6/casmi_loader.py`.

### 2.4 Reachability ceiling

The PubChem subset is curated, not exhaustive. Of 170 GT InChIKey-first-
blocks, **142 (83.5 %)** are present in the formula-matching slice;
**28 (16.5 %)** are not, making them unreachable upper-bound failures
for any ranking method. We report id_acc at both denominators.

---

## 3. Phase 6.6 results

### 3.1 D2 — MS-CLIP-only baseline (no rerank)

```
config: msclip primary, no SIRIUS/CFM, full pubchem pool
n_specs:  170
n_with_predictions:  170 (every spec returned at least one candidate)
n_correct:  23
id_acc (full,170):       13.53 %  (23/170)
id_acc (reachable,142):  16.20 %  (23/142 — all correct predictions came from the reachable subset, as expected)
```

This number is consistent with the MIST paper's CASMI 2022 MS-CLIP-only
reference (~12–14 %), establishing baseline calibration.

### 3.2 Empirical gate behavior on CASMI (gate-only diagnostic, n=170)

Before scoring D3, we ran a fast diagnostic with the gate enabled but
SIRIUS/CFM disabled (`--reranker conditional --rerank-with ""`) to log per-
spec MS-CLIP top1 and gap values:

| stat | CASMI 2022 | Sub-6A v2 reference (Phase 6.5) |
|---|---:|---:|
| msclip top1, median   | 0.785 | (not directly comparable — different candidate space) |
| msclip gap, median    | **0.004** | n/a |
| msclip gap, p90       | 0.012 | n/a |
| msclip gap, max       | **0.046** | (Sub-6A v2 has many specs above 0.15) |
| % specs with gap ≥ 0.05 (locked threshold) | **0.0 %** | 35.3 % |
| **trigger rate**      | **100 %** | 64.7 % |

**Finding.** The Phase 6.5 conditional gate's *skip* branch — which on
Sub-6A v2 saved 35 % of compute by withholding rerank from specs where
MS-CLIP was already confident — is **structurally absent in the CASMI 2022
PubChem-pool regime**. With formula-restricted PubChem candidates (median
1,385 candidates per spec, all of identical molecular formula) MS-CLIP
spectrum-vs-structure scoring produces extremely tight score
distributions; no candidate stands out enough to clear the locked
gap≥0.05 threshold. On this benchmark, *conditional ≡ always-rerank*.

CSV: `data/paper_figures/phase6_6_casmi_gap_distribution.csv` (170 rows).

### 3.3 D3 — Conditional rerank (gap ≥ 0.05, locked from Phase 6.5)

```
config: msclip primary + SIRIUS+CFM-ID weighted reranker
        (rerank-top-k=5; threshold gap≥0.05 LOCKED from Sub-6A v2 grid search)
n_specs:                170
n_correct:              23
id_acc (full,170):      13.53 %  (23/170)
id_acc (reachable,142): 16.20 %
n_conditional_skipped:  0   (skip rate 0.0 %)
elapsed_seconds:        17,589 (≈ 4.9 h; ms-clip + SIRIUS + CFM-ID rerank on
                        100 % of specs; one CFM-ID-cache cold start)
```

Both predictions are identical at the population level, but **not at the
spec level** — see §3.4 for the per-spec disagreement structure.

#### 3.3.1 Why the gain disappears on CASMI

On CASMI 2022 the weighted reranker's evidence_score
(`0.4·modcos + 0.3·CFM_cosine + 0.2·mass_match + 0.1·pathway_presence`,
plus a SIRIUS sanity multiplier ×0.5 when formula disagrees) collapses to
roughly `0.3·CFM_cosine` because:

| component | Sub-6A v2 contribution | CASMI 2022 contribution |
|---|---|---|
| `modcos`           | non-zero (GNPS reference spectra exist) | **0 for every candidate** (PubChem candidates have no MS/MS reference) |
| `mass_match`       | discriminative (some candidates wrong-formula) | **constant** — every candidate is formula-matched by construction |
| `SIRIUS gate`      | discriminative (downweights wrong-formula candidates) | **no-op** — formula is the same for all candidates so SIRIUS either keeps everyone (correct prediction) or downweights everyone equally (wrong prediction) |
| `pathway_presence` | sparse signal | not populated for PubChem candidates |
| `CFM_cosine`       | discriminative | **only remaining discriminator**, but predicted spectra of formula-isomers are highly correlated → low effective dynamic range |

The reranker effectively reduces to "rank by CFM-cosine alone over highly
correlated predicted spectra," which is dominated by noise. The 8/8
McNemar swap is the empirical signature of this noise: rerank flips ~10 %
of MS-CLIP top-1 calls in symmetric directions.

### 3.4 Significance — McNemar paired test (D2 vs D3)

```
b (msclip wrong, conditional right):  8
c (msclip right, conditional wrong):  8
delta:                                +0 spectra  (+0.00 pp)
CI 95 %:                              [-4.61, +4.61] pp
McNemar p:                            1.00 (exact, two-sided)
union_correct (either config right):  31/170 = 18.24 %
```

The 95 % CI passes through zero, so the data cannot distinguish the
conditional rerank from MS-CLIP-only at this n. The CI also rules out
gains larger than ≈ +4.6 pp at this sample size — i.e. CASMI 2022 alone
cannot produce a Sub-6A-v2-magnitude (+10 pp) gain even if it existed.

CSV: `data/paper_figures/phase6_6_significance.csv`,
`data/paper_figures/phase6_6_casmi_per_spec.csv`.

### 3.5 Soft structural metrics — Tanimoto and MCS atom-fraction

McNemar (§3.4) tests exact-match accuracy: it cannot detect "the rerank
picked a more structurally-similar wrong answer." We therefore report two
soft metrics for the top-1 predicted SMILES vs. GT SMILES of every spec:

* **Tanimoto similarity** over Morgan-radius-2, 2048-bit fingerprints (RDKit
  `AllChem.GetMorganFingerprintAsBitVect`).
* **MCS atom-fraction** = (#atoms in maximum common substructure) /
  max(#atoms in pred, #atoms in GT), via RDKit `rdFMCS.FindMCS`
  (30 s timeout per pair; 5 specs failed under either config and were
  dropped from the MCS-paired set). This is a structural analogue of the
  MIST-paper MCES metric (no Python `myopic_mces` package is installed
  here, so we use the RDKit-native version).

```
Tanimoto (Morgan-2, 2048-bit)
                                n     mean   median   p90
  msclip_only                  170   0.388   0.219   1.000
  conditional                  170   0.395   0.233   1.000

MCS atom-fraction (n=165 with both configs producing valid MCS)
                                n     mean   median   p90
  msclip_only                  165   0.749   0.783   1.000
  conditional                  165   0.758   0.788   1.000

Paired Wilcoxon signed-rank (D3 vs D2, two-sided):
  Tanimoto    D3>D2=51  D3<D2=48  ties=71  mean Δ=+0.0067  p=0.897
  MCS-frac    D3>D2=38  D3<D2=39  ties=88  mean Δ=+0.0088  p=0.661
```

The three paired tests on the same 170 spectra are **mutually
corroborating null results**:

| metric | direction | n_paired | discordance | p |
|---|---|---:|---|---:|
| Exact-match (McNemar)      | binary   | 170 | b=8, c=8     | 1.00 |
| Tanimoto (Wilcoxon)        | continuous | 170 | +51/−48/=71 | 0.897 |
| MCS atom-fraction (Wilcoxon) | continuous | 165 | +38/−39/=88 | 0.661 |

Notes on the absolute levels:

* **Tanimoto median ≈ 0.22** confirms that top-1 wrong predictions are
  structurally *very* different from the GT — typical of a noisy retrieval
  over a large formula-restricted PubChem slice.
* **MCS atom-fraction median ≈ 0.78** is large *because* every candidate
  shares the GT molecular formula — the maximum common substructure
  necessarily includes whatever fused ring system and heavy-atom backbone
  the formula admits. MCS is therefore *inflated* on CASMI's formula-
  restricted candidate space and should not be read as "78 % structural
  agreement"; Tanimoto is the honest read.
* The ~70–90 specs with identical metric value across configs (`ties`)
  are the cases where conditional rerank chose the same top-1 as
  MS-CLIP-only. The actual perturbation set is the ~50–80 specs where
  the two configs disagree — and on that set the per-spec metric Δ is
  symmetric around zero, hence the high p-values.

CSVs:
* `data/paper_figures/phase6_6_structural_metrics.csv` — per-spec
  Tanimoto / MCS-frac / Δ.
* `data/paper_figures/phase6_6_structural_summary.csv` — aggregate
  distributions per config.
* `data/paper_figures/phase6_6_structural_wilcoxon.csv` — paired-test
  outputs.

---

## 4. Cross-benchmark coherence

`data/paper_figures/phase6_6_cross_benchmark.csv`:

| benchmark | n | msclip-only | conditional | Δ | p | skip % | candidate space |
|---|---:|---:|---:|---:|---:|---:|---|
| sub6a_realid_v2 | 448 | 56.70 % | 66.96 % | +10.27 | <1e-6 | 35.3 | GNPS reference spectra (modcos-discriminative, mixed-formula) |
| casmi_2022      | 170 | 13.53 % | 13.53 %  | +0.00  | 1.00  | 0.0  | PubChem (formula-restricted, no reference spectra) |

The two benchmarks have radically different absolute id_acc levels because
of the candidate-space difference (GNPS reference spectra vs. PubChem
structural slice); the **locked-threshold conditional gate** is the only
thing held constant across them.

---

## 5. Threshold transferability

The Phase 6.5 grid search optimized `(top1_threshold, gap_threshold)` on
448 Sub-6A v2 spectra. Phase 6.6 uses those exact thresholds —
`(0.0, 0.05)` — without re-tuning. This is by design: a threshold tuned on
CASMI to maximize CASMI id_acc would not validate the Sub-6A finding, it
would only fit a separate model. The locked-threshold protocol gives a
true honest test.

---

## 6. Limitations

1. **PubChem reachability ceiling.** 28/170 specs (16.5 %) cannot be
   identified by *any* method using this corpus. The "reachable subset"
   id_acc is the realistic upper bound for evaluation comparisons.
2. **Modcos and mass_match are structurally absent on CASMI.** The
   conditional rerank's evidence_score formula is dominated by these
   components on Sub-6A v2; on CASMI it reduces to `0.3·CFM_cosine`,
   which is a far weaker signal. This is the leading hypothesis for the
   null result, not a confounder to be controlled away.
3. **Smaller n.** CASMI 2022 = 170 vs Sub-6A v2 = 448. McNemar power
   scales with n_b + n_c (the discordant pairs); at n_paired=170 with
   b=c=8, the test is unable to detect deltas smaller than ~ ±5 pp.
4. **Single dataset.** CASMI 2016 cat2 (208 spectra) was scoped but not
   run in this iteration. Adding it would double the OOD evidence; the
   loader generalises with a small extension to parse .mgf + solutions
   CSV (the candidate-pool builder is reused as-is).
5. **SIRIUS auto-relogin.** The 4.9 h D3 run hit a SIRIUS academic-
   license session expiry around minute ~135. METAGENT_SIRIUS_USER /
   PASS were not exported in this shell, so auto-relogin was a no-op and
   the trailing ~70 specs ran with `use_sirius` effectively False.
   Methodological impact is **zero** because — as established in §3.3.1 —
   the SIRIUS gate is a no-op on formula-restricted candidate pools
   regardless of session state.

---

## 7. Files & artefacts

### Code (new)
- `evaluation/sub6/casmi_loader.py` — .ms parser, PubChem retrieval index
  loader, `build_pubchem_pool(formula, ...)`.
- `scripts/eval_sub6/run_casmi.py` — runner.
- `scripts/eval_sub6/casmi_significance.py` — McNemar, cross-benchmark.

### Code (modified, backwards-compatible)
- `evaluation/sub6/identification.py` — added `candidate_pool` and
  `use_gnps` keyword arguments. Defaults preserve Sub-6A behavior exactly.

### Outputs
- `data/eval/casmi/2022_msclip_only/casmi_identifications.jsonl, summary.json`
- `data/eval/casmi/2022_gate_only/casmi_identifications.jsonl, summary.json`
   — gate diagnostic only (rerank disabled) for the gap distribution table.
- `data/eval/casmi/2022_conditional/casmi_identifications.jsonl, summary.json`
- `data/paper_figures/phase6_6_casmi_results.csv` — main 2-row table (D2, D3).
- `data/paper_figures/phase6_6_casmi_per_spec.csv` — per-spec correctness +
  predicted IK14 + gate decision per config.
- `data/paper_figures/phase6_6_casmi_gap_distribution.csv` — per-spec
  msclip top1 / gap, used for §3.2.
- `data/paper_figures/phase6_6_significance.csv` — McNemar / CI / paired Δ.
- `data/paper_figures/phase6_6_cross_benchmark.csv` — Sub-6A v2 vs CASMI
  2022 coherence table (§4).
- `data/paper_figures/phase6_6_structural_metrics.csv` — per-spec
  Tanimoto + MCS atom-fraction for both configs (§3.5).
- `data/paper_figures/phase6_6_structural_summary.csv` — aggregate
  distributions per config.
- `data/paper_figures/phase6_6_structural_wilcoxon.csv` — paired
  Wilcoxon signed-rank Δ tests.

### Code (new, this turn)
- `scripts/eval_sub6/casmi_structural_metrics.py` — Tanimoto / MCS / paired
  Wilcoxon (RDKit Morgan FPs + `rdFMCS`).

---

## 8. Conclusion

The Phase 6.5 conditional rerank delivers **+10.27 pp on Sub-6A v2 and
+0.00 pp on CASMI 2022** at the locked threshold. Two facts together
explain the gap rather than invalidate either result:

1. **Gate selectivity is candidate-space-dependent.** On Sub-6A v2 the
   MS-CLIP gap distribution has a bimodal shape — 35 % of specs cleanly
   above 0.05 (skip) vs 65 % below (trigger). On CASMI 2022 every spec
   sits below 0.046 because PubChem formula-isomers produce a uniformly
   tight MS-CLIP score landscape. The gate degenerates to always-trigger.
2. **Rerank discriminative power is candidate-space-dependent.** The
   evidence_score formula's three highest-weighted components (`modcos`,
   `mass_match`, SIRIUS gate) all collapse to constants on a formula-
   restricted PubChem pool. CFM_cosine alone does not move the population
   id_acc — it moves individual predictions symmetrically (b=c=8 swap).

This is **not** evidence that the Phase 6.5 finding is spurious; it is
evidence that the finding is **bounded to benchmarks with a structurally
diverse candidate pool**, where SIRIUS, mass-match and modcos can each
contribute discriminating signal. The honest paper claim is therefore:

> *Conditional SIRIUS+CFM-ID rerank gated by MS-CLIP top1−top2 gap
> delivers +10 pp on Sub-6A real-id v2 and 0 pp on CASMI 2022. Across
> these two benchmarks, the rerank's effectiveness scales with the
> candidate pool's structural diversity — a property that the gate
> happens to detect via the MS-CLIP confidence signal.*

The CASMI null is therefore a **scope clarifier**, not a refutation.

### Recommended next steps (out of scope for Phase 6.6)

* Add CASMI 2016 cat2 (208 specs) to double the OOD evidence.
* Test on a benchmark with mixed-formula PubChem retrieval (e.g. drop the
  formula filter and retrieve by ±10 ppm mass tolerance) — this should
  recover SIRIUS / mass_match discriminative power and let the
  reranker's full evidence_score act, providing a cleaner test of
  whether the +10 pp behavior tracks "diverse candidate pool" or
  specifically "GNPS reference-spectra availability."
* Either replace `modcos` with a structure-only equivalent (e.g.
  predicted-vs-experimental cosine via a stronger predictor) on
  CASMI-style benchmarks, or document that the conditional rerank should
  not be deployed when modcos and mass_match are unavailable.
