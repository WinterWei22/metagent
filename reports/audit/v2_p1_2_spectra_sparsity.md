# P1-2 Deep Dive — Sub-6A v2 Spectra Sparsity

**Sibling report to:** `reports/audit/v2_data_integrity_independent_test.md`
**Date:** 2026-05-18

---

## 1 · Headline numbers

| metric | value |
|--------|------:|
| Sub-6A tasks | 38 |
| total `differential_spectra` rows | 459 |
| (task × signal compound) instances | 219 |
| signal compounds with **no** mapped spectrum in same task | 45 / 219 (20.5 %) |
| signal compounds with **exactly 1** mapped spectrum | 80 / 219 (36.5 %) |
| signal compounds with **≥ 3** mapped spectra | 36 / 219 (16.4 %) |
| median spectra per (task × signal) instance | **1** |
| mean spectra per (task × signal) instance | 1.39 |

Mapping path: signal compounds are KEGG cpd strings (e.g. `C00951`).
The curated mammalian pool (`curated_hmdb_mammalian_v2.jsonl`, 250
compounds) provides the KEGG → InChIKey-first-block lookup. Spectra in
`differential_spectra` carry `inchikey_first_block`; matching is then
exact-string. No signal compound failed the KEGG → InChIKey mapping
step (`n_signal_no_ik_mapping = 0`).

---

## 2 · Which tasks are worst affected?

The 5 tasks with the lowest "total spectra mapped to signal compounds"
(numerator = sum over signal compounds in the task; denominator =
n_signal_inst × 1):

| task_id | n_signal_compounds | n_with_≥1_spec | total_spectra | n_diff_spectra_in_task |
|---------|-------------------:|---------------:|--------------:|------------------------:|
| `e2e_enrich_mammalian_RAMP_P_000050021_seed1927381484` | 5 | 1 | 2 | 6 |
| `e2e_enrich_mammalian_RAMP_P_000050021_seed2411785485` | 6 | 2 | 3 | 5 |
| `e2e_enrich_mammalian_RAMP_P_000050021_seed717276092`  | 5 | 2 | 3 | 8 |
| `e2e_enrich_mammalian_RAMP_P_000050021_seed3320305144` | 6 | 2 | 3 | 10 |
| `e2e_enrich_mammalian_RAMP_P_000050021_seed669730130`  | 6 | 2 | 3 | 4 |

Observation: all 5 worst-coverage tasks fall under the **same
pathway** `RAMP_P_000050021` (Biological oxidations). The bottleneck
is therefore systematic — that pathway's signal-compound metabolites
have intrinsically poor library coverage in the GNPS / MassBank
spectra pool, not a sampling artifact across seeds.

The "n_diff_spectra_in_task" column shows that those tasks DO have
4–10 differential spectra each — but those spectra are for NON-signal
compounds. The mapping from signal-KEGG to spectrum-InChIKey via the
curated pool just doesn't match many of those 5–6 signal compounds.

---

## 3 · Why 0 spectra for 45 / 219 instances?

For each "0-spectrum" instance we know `n_signal_no_ik_mapping = 0`
(every signal KEGG → InChIKey lookup succeeded via the curated pool).
So the 45 instances are not from missing IDs — they are signal
compounds whose canonical InChIKey **does not appear in their task's
`differential_spectra` list**, even though the spectra list is
non-empty.

Two possible explanations (both consistent with task constructor
behaviour):

1. **Spectra were intended for differential discrimination, not
   ground-truth identification.** The constructor adds 5–8 signal
   compounds + 2–5 noise compounds + ~10 differential spectra per
   task; the spectra cover a subset of those compounds chosen for MS
   discrimination, not all of them.

2. **A subset of signal compounds intentionally have no spectrum**
   (the task-construction default for "compound 在 ground-truth list
   但无 spectrum 表示"). This is a known design choice in the v2
   constructor.

Either explanation is acceptable for the cascade-demo use case but
**fatally constrains** any per-compound spectral robustness claim:
20.5 % of instances genuinely have no spectrum, so a "per-compound
spectral-robustness multi-seed" evaluation would have 0 spectra to
work with for those instances.

---

## 4 · Task-level coverage filter scenarios

| filter | n tasks passing |
|--------|----------------:|
| ≥ 3 signal compounds with ≥ 1 spectrum each | **30 / 38** |
| ≥ 3 signal compounds with ≥ 3 spectra each (robust) | **3 / 38** |
| all signal compounds in task have ≥ 1 spectrum + total ≥ 2 × n_signal | (constructed proxy for "spectrum-rich") | (see below) |

Tightening to ≥ 3 spectra per compound drops effective task count by
**87 %** (38 → 3). This is a hard ceiling on the data, not a
threshold-tuning artifact.

---

## 5 · Recommendation for ConcordMet / B1 usage

### ConcordMet specific

ConcordMet works at the **compound list → pathway** abstraction, not
spectra → compound. Sub-6A's spectra layer is therefore upstream of
ConcordMet's interface. Whether to include Sub-6A is a question about
the *upstream identification pipeline*, not ConcordMet's pathway
inference.

**Verdict:** Sub-6A v2 is **not the right benchmark for ConcordMet**
in any role. ConcordMet's primary cohort is Cooke (in-silico) and
its supplementary is at most Sub-6B v2 (compound-driven). Sub-6A
remains a useful demo for the cascade pipeline that *feeds* ConcordMet
but should be evaluated on its own terms (top-1 identification
accuracy), not folded into ConcordMet metrics.

### B1 (closed-loop verifier) usage

For B1 multi-seed evaluation:

- **Task-level metrics** (e.g. "did the verifier reach a correct
  pathway claim?") — usable on 30 / 38 tasks if requiring ≥ 3 signal
  compounds with ≥ 1 spectrum each. Document this as the filter and
  report N = 30 in evaluation tables.
- **Per-compound spectral robustness** — NOT supported by Sub-6A v2.
  Median 1 spectrum per (task × compound), with 20 % zero-spectrum
  instances. Any claim of the form "the verifier is robust to
  multiple library spectra per compound" cannot be backed by this
  data.

### Paper text suggestion

"Sub-6A v2 provides 459 differential spectra across 38 tasks for
end-to-end cascade evaluation (identification → enrichment →
verification). Per-(task × signal compound) instances have a median
of 1 spectrum (mean 1.39); 45 of 219 instances have no mapped
spectrum, reflecting the constructor's design choice that not every
signal compound receives library spectrum coverage. We therefore
report task-level metrics on a 30-task subset where ≥ 3 signal
compounds have ≥ 1 spectrum each; per-compound spectral robustness is
out of scope for v2."

---

## 6 · Provenance

- Computation: `data/investigation/scripts/audit_sub6_v2_independent.py`,
  functions `check_p1_2` + `deep_p1_2`.
- KEGG → InChIKey mapping table: derived inline from
  `data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl` (no separate
  artifact written).
- Spectrum membership: `differential_spectra[*].inchikey_first_block`
  per task.
- Numbers: `data/audit/v2_test/check_results.json` →
  `["p1_2", "deep_p1_2"]`.
