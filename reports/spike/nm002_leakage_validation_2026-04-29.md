# NM-002 leakage filter — validation against spike fixtures

- **Date:** 2026-04-29
- **Audit upstream:** `reports/nm002_leakage_audit_2026-04-29.md`
- **Spike to compare against:** `reports/spike/negative_mode_spike_2026-04-28.md` §2.3
- **Filter artefact:** `data/processed/nm002_excluded_gnps_ids.json` (76,783 GNPS spectrum_ids)
- **Validation script:** `scripts/spike/test_nm002_filter_validation.py`
- **Conclusion:** ✅ **The leakage filter eliminates the data-leakage top-1 on
  both negative-mode spike fixtures.** The pre-fix top-1 — which the spike
  showed was a self-match in both cases — is now correctly excluded.

---

## 1. Method

The `library_search` tool itself remains unchanged (per the
`leakage_filter` design contract — exclusion lives in the benchmark
layer). For validation we replay the spike's cached
`library_search` output (`/tmp/spike_neg_pipeline_artifacts.pkl`) and
post-hoc filter every candidate whose `source_id` appears in
`nm002_excluded_gnps_ids.json`.

This is sound because `library_search`'s ranking depends only on the
ms-clip score against the query spectrum and not on the order of the
input pool — pruning leaked records can only **remove** candidates,
never reorder the survivors. The post-hoc top-1 is therefore identical
to what `library_search` would have produced if it had been called
with the excluded ids stripped from the GNPS pool up front.

The `leakage_filter` unit + integration tests pass independently:

```
$ conda run -n metagent-llm pytest tests/benchmark/test_leakage_filter.py \
        tests/benchmark/test_leakage_filter_integration.py -q
...................s                                                     [100%]
19 passed, 1 skipped in 0.19s
```

---

## 2. Per-fixture results

### 2.1 `glutamyltyrosine_neg.json`  (the canonical NM-002 case)

Truth InChIKey first-block: `VVLXCWVSSLFQDS` (γ-L-Glutamyl-L-Tyrosine).

| Rank | source_id | name | score | Leaked? | InChIKey-match |
|---:|---|---|---:|---|---|
| **Pre-fix top-1** | `MSBNK-RIKEN-PR309407` | Glutamyltyrosine | 0.812 | **YES** (same accession the fixture was extracted from) | ✅ |
| 2 | `HMDB0029104` | Tyrosyl-Glutamate | 0.685 | no | (different stereo) |
| 3 | `HMDB0028831` | Glutamyltyrosine | 0.678 | no | (different stereo) |
| 4 | `HMDB0011741` | γ-Glutamyltyrosine | 0.676 | no | ✅ |
| **Post-fix top-1** | `HMDB0029104` | Tyrosyl-Glutamate | 0.685 | n/a | (different stereo) |

Prefilter pool: 30 candidates total, **1 excluded** by the filter.
Library_search top-10 → 9 survivors after exclusion. The leaked
`MSBNK-RIKEN-PR309407` is no longer reachable; the pipeline now
ranks the structurally-similar dipeptide isomers first, with the true
γ-Glutamyltyrosine surviving at rank 3 (post-fix).

This matches the spike report's exact prediction — *"glutamyltyrosine's
top-1 GNPS hit is `MSBNK-RIKEN-PR309407` — the same accession the
fixture was extracted from"* — and confirms the audit's headline
finding (audit §9 row 2: "✅ 2 GNPS record(s) excluded for this
query: MSBNK-RIKEN-PR309407, MSBNK-RIKEN-PR311057").

### 2.2 `citric_acid_neg.json`

Truth InChIKey first-block: `KRKNYBCHXYNGOX` (citric acid).

| Rank | source_id | name | score | Leaked? | InChIKey-match |
|---:|---|---|---:|---|---|
| **Pre-fix top-1** | `CCMSLIB00000479610` | Citric acid | 0.833 | **YES** (same compound, different GNPS submitter) | ✅ |
| 2 | `CCMSLIB00000479707` | Isocitric acid | 0.809 | no | (positional isomer) |
| **Post-fix top-1** | `CCMSLIB00000479707` | Isocitric acid | 0.809 | n/a | (positional isomer) |

Prefilter pool: 30 candidates total, **25 excluded** by the filter.
Library_search top-2 → 1 survivor. The pre-fix top-1 was *not* a
RIKEN cross-reference; it was a CCMSLIB submission of the same
compound, caught by the InChIKey-first-block trigger
(audit §3 row 1: 7.77% of GNPS — same-compound re-imports).

The post-fix top-1 is the structural isomer **isocitric acid**, which
is the most chemically plausible non-leaked candidate. The library
contains no other citric acid spectrum that survives the InChIKey
trigger (because, by definition, every same-compound record gets
caught — see §3 below).

---

## 3. The InChIKey trigger trade-off

The InChIKey-first-block trigger removes **7.77% of GNPS** (76,611 of
985,492 records, audit §3) — far more than the cross-reference (0.55%)
or exact-source-id (0.55%) triggers.

This is the conservative-by-design choice the audit makes. Spike §2.3
showed that a single same-compound record dominates ranking with score
~1.0; removing only the literal RIKEN cross-references would let any
other GNPS submission of the same molecule (e.g. ~1,000 different
contributors uploading citric acid) take the top slot and produce the
same self-match score. The audit explicitly documents this
(§7 caveats): the strict per-query intersection is a tight upper bound,
and the spike `score=0.812` self-match supports that the full
removal is needed.

The downstream consequence visible in §2.2 is that benchmark accuracy
on common metabolites (citric acid has the second-most GNPS records of
any compound) drops to "find the closest *non-identical* structural
isomer". This is what an honest benchmark looks like — the LLM-driven
identification system should be able to recognise the candidate
without a trivial library hit.

---

## 4. Post-fix verdict on the spike's NM-002 entry

The spike report `negative_mode_spike_2026-04-28.md` §3 NM-002 entry
flagged this issue as **MAJOR for benchmark integrity** and recommended:

> Suggested fix: For benchmark splits, exclude any GNPS reference whose
> `source_id` (or its first-block InChIKey) appears in the benchmark's
> own RIKEN slice. Add this as a filter in the benchmark builder, *not*
> in library_search itself (library_search must remain unchanged).

The implemented filter does exactly that. The `library_search` tool is
untouched (audit confirms via `tools/benchmark/leakage_filter.py`
docstring); the exclusion list is consumed by the benchmark layer.

**Verdict on NM-002:** mitigated. The 100.0% → 0.0% self-match rate
the audit reports (§7) is reproducible on both spike fixtures; the
post-fix top-1 in both cases is a chemically-different molecule.

---

## 5. Interaction with Layer F cross-validation

This is also a clean operational test that the Layer F changes from
the prior session do not affect upstream `library_search`. Both top-K
lists pre-NM-002 (in the cached spike artefact) were produced before
the Layer F refactor, and the post-fix top-K is just a deterministic
filter over them — no Layer F call is made. The two fixes are
orthogonal:

- **Layer F (verifier)** mitigates SIRIUS' wrong-formula cascade after
  candidates are scored (`reports/spike/layer_f_cross_validation_validation_2026-04-28.md`).
- **NM-002 (benchmark layer)** mitigates same-source/same-compound
  leakage in the candidate pool itself (this report).

Together they let the negative-mode benchmark slice be reported
honestly: the candidate pool no longer contains self-matches, and the
verifier does not rubber-stamp claims that depend on a wrong precursor
formula.

---

## 6. Reproduction recipe

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5
git checkout feature/layer-f-cross-validation

# Filter unit + integration tests (always run)
conda run -n metagent-llm pytest tests/benchmark/test_leakage_filter.py \
    tests/benchmark/test_leakage_filter_integration.py -q

# Validation against spike fixtures (uses cached artefact at
# /tmp/spike_neg_pipeline_artifacts.pkl, regenerated by §2.3 if absent)
conda run -n metagent-llm python scripts/spike/test_nm002_filter_validation.py
```

If the cache is missing, regenerate with the §2.3 spike script
(takes ~7 min for the GNPS load):

```bash
conda run -n diffms python scripts/spike/test_library_search_negative.py
```

---

## 7. Open follow-ups

- **Inhouse-library leakage** is not yet audited — the filter only
  applies to GNPS. If benchmark spectra ever reach the in-house
  reference set, a parallel audit is needed.
- **MoNA / MassBank-Athens extension** — when the negative-mode
  benchmark expands beyond RIKEN, the same filter must be re-built
  against the new query set (the audit script supports this via
  `--benchmark-pool`).
- **Top-K cutoff for leaked-pool fixtures.** On `citric_acid_neg`
  the surviving top-K is just 1 candidate because the original
  spike script set `top_k=10` against a 2-candidate library_search
  output. Re-running with a wider candidate pool would reveal more
  ranked survivors and let us measure the pipeline's true accuracy
  on common metabolites.
