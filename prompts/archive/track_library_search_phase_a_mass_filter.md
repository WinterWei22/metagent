# Track Library-Search Phase A — Precursor-Mass Window Pre-filter

**Session ID:** `track_library_search_phase_a_mass_filter`

**Branch:** `feature/library-search-mass-filter`

**Estimated work:** 1 day (1 person)

---

## Context

The Sub-6A real-id end-to-end pipeline (`reports/eval/sub6_baseline_day3_2026-05-01.md`)
has identification accuracy = **6.25 % top-1** (8 / 128 spectra correct).
Verifier pipeline reports flowing from this (`reports/verifier/llm_3way_comparison_2026-05-05.md`,
`reports/verifier/alias_expansion_l1_fix_2026-05-05.md`) document that the
identification stage is the dominant remaining bottleneck for Sub-6A
real-id — independent of LLM extractor and KEGG graph topology.

**Diagnosis (`reports/verifier/alias_expansion_l1_fix_2026-05-05.md` §5.b
+ Day 3 §5b)**: `library_search` returns wrong-mass candidates because
`tools/library_search/` currently scans the full GNPS pool (~622 k
spectra) without a precursor-mass-window filter. Three actual
failures from v3 logs:

```
GT: fumaric acid    (m/z 117.02)  →  myrcene              (m/z 137.13), modcos 0.815
GT: FAD             (m/z 786.16)  →  glyceraldehyde-3-P   (m/z 170.99), modcos 0.963
GT: caffeine        (m/z 195.09)  →  1,3,7-trimethyluric  (m/z 211.08), modcos 0.866
```

`ModifiedCosineGreedy` (matchms) is designed for analog discovery and
tolerates large precursor-mass deltas; combined with no pre-filter, it
ranks structurally unrelated compounds with very different masses
above the true compound's other-condition reference spectra.

**Phase A goal:** add a precursor-mass window filter (default ±10 ppm)
to `_score_path_b` (the no-candidate-pool fallback path of
`library_search`). Expected to lift Sub-6A real-id `id_acc` from
6.25 % to **≥ 25 %** with no other architectural changes.

---

## Hard scope boundaries

**You MAY:**

- Modify `tools/library_search/tool.py` — only the `_score_path_b`
  branch (the no-candidate-pool fallback). Do NOT touch `_score_path_a`
  (the already-prefiltered path).
- Add an optional `mass_tolerance_ppm: float | None = 10` field to
  `schemas.LibrarySearchRequest` (additive — default keeps current
  behaviour unchanged when the field is None).
- Add unit tests under `tests/tool_tests/test_library_search.py`
  (additive only).
- Re-run Sub-6A real-id baseline (`scripts/eval_sub6/run_baseline.py
  --sub6a --id-strategy library_search`) into `data/eval/sub6/
  sub6a_narratives_phase_a.jsonl` (new path; do NOT clobber the
  existing v3 / v6 narrative output).
- Re-run verifier on the new narrative file via the same provider
  switch as v6 (Claude Opus-4-7 via viviai).
- Add reports + CSVs under `results/sub6a_real_id_phase_a/` and
  `results/sub6a_real_id_verifier_v7_phaseA/`.

**You MAY NOT:**

- Modify `_score_path_a`, `scoring.py::fuse_scores`, or any other
  scorer (`modified_cosine_score`, `MSClipRetriever`). These are
  Phase B / C / D — out of scope here.
- Modify `tools/sirius/`, `tools/spectrum_predict/`, or any other tool.
- Modify the verifier (`verifier/`), reaction graph
  (`tools/kegg/`), or compound alias table.
- Re-run the LLM narratives — `results/sub6a_real_id/sub6a_narratives.jsonl`
  was generated in 5 hours of LLM time and is FROZEN.
  **You re-run library_search to produce a NEW narrative because
  the LLM input (identified compounds) changes when ID changes.**
  But the LLM model + temperature + prompt template all stay
  identical to the original Sub-6A real-id baseline.
- Run Phase B / C / D — only Phase A this session.
- Touch `data/benchmark/sub6/` or any other Sub-6 data.

---

## Background reading (mandatory before first action)

1. `reports/eval/sub6_baseline_day3_2026-05-01.md` §3, §5b
   (Sub-6A real-id baseline + identification failure samples)
2. `reports/eval/sub6_fixes_comparison_2026-05-01.md` §4
   (Sub-6A real-id D5 first run, 5 h 21 min wall, id_acc 6.25 %)
3. `reports/verifier/alias_expansion_l1_fix_2026-05-05.md` §6 L1
   ("identification is the next bottleneck for Sub-6A real-id")
4. `tools/library_search/tool.py` — read the whole file, especially
   `_score_path_b` (the fallback path you'll modify).
5. `tools/library_search/scoring.py::modified_cosine_score` — note
   the matchms 0.32 compat shim. Don't touch the inner logic.
6. `schemas/spectrum.py::LibrarySearchRequest` — schema you'll extend.
7. `evaluation/sub6/identification.py::identify_spectrum` — runner
   that wraps library_search; check it doesn't override the new
   field with a hard-coded value.
8. `evaluation/sub6/run_sub6a.py::run_sub6a_batch` — full Sub-6A
   pipeline; understand how identifications feed the LLM.

---

## First-action checklist (return to me, do NOT start coding)

1. Confirm reading of the 8 background files above.
2. Probe the current GNPS pool: how many records, what's the
   distribution of `precursor_mz`?
3. Probe one failing spectrum (`sub6a-gnps-CCMSLIB00006354915` —
   GT InChIKey `VZCYOOQTPOCHFL`, fumaric acid, expected mass 116.01 g/mol):
   - How many GNPS records have precursor mass within ±10 ppm of
     117.02 (the spectrum's [M+H]+ precursor)?
   - Is fumaric acid (cpd:C00122) IN that filtered set?
   - What were modcos / ms-clip scores against the filtered set vs
     full pool? (compute a small experiment offline)
4. Recommend a default `mass_tolerance_ppm`:
   - 5 ppm is HRMS-strict (Orbitrap)
   - 10 ppm is HRMS-default
   - 20-25 ppm covers Q-TOF / lower-res instruments
   - Some Sub-6A spectra are MoNA-MassBank with `instrument_type=ESI`
     but unknown analyser — investigate before fixing the default
5. Estimate expected GNPS pool size after filtering (50? 500? 5000?).
6. Estimate runtime impact: 14 task × 9 spectra × ? seconds new.
7. Ask any clarifying questions.

Do NOT start coding until I confirm.

---

## Deliverables

### D1 — Schema + library_search code change

**Files:**
- `schemas/spectrum.py::LibrarySearchRequest` — add field
- `tools/library_search/tool.py` — add filter in `_score_path_b`

**Behaviour:**

- New field `mass_tolerance_ppm: float | None = None` on
  `LibrarySearchRequest` (default None = current behaviour
  preserved for backward compatibility).
- When set, in `_score_path_b`:
  ```python
  if req.mass_tolerance_ppm is not None:
      query_mz = req.spectrum.precursor_mz
      tol_da = query_mz * req.mass_tolerance_ppm / 1e6
      gnps_records = [
          rec for rec in gnps_records
          if abs(rec.precursor_mz - query_mz) <= tol_da
      ]
  ```
- Filter happens **before** modcos / ms-clip scoring.
- Log to debug: `f"mass-window filter: {n_before} → {n_after} records"`
- If `n_after == 0`, return empty result with
  `explain="no GNPS records within ±N ppm of precursor m/z"`.

**Backward compat invariant:** every existing test that doesn't pass
`mass_tolerance_ppm` must produce bit-identical output to current
behaviour. Verify by running the full
`tests/tool_tests/test_library_search.py` suite — every test should
still pass without code changes to those tests.

### D2 — Unit tests

**File:** `tests/tool_tests/test_library_search.py` (additive)

Cover:
- `test_mass_filter_narrows_pool`: provide a small in-memory pool with
  3 records at different precursor masses; query within ±10 ppm of
  one; assert only that record scored.
- `test_mass_filter_zero_records_returns_empty`: query with no
  matching mass; assert `candidates == []` and explain contains
  "no GNPS records within".
- `test_mass_filter_default_none_preserves_behaviour`: do NOT set
  `mass_tolerance_ppm`; assert pool size + scoring output identical
  to current behaviour (use `MockInHouseRetriever` to make this
  deterministic).
- `test_mass_filter_ppm_arithmetic`: query at m/z = 200.000, tol = 10;
  pool with records at 200.001 (5 ppm), 200.005 (25 ppm); assert only
  the first one passes.
- All 4 new tests must pass; all existing 36 tests must still pass.

### D3 — Single-spectrum smoke

Pick one spectrum from Sub-6A real-id where v3/v6 returned a
**wrong** identification (e.g.
`sub6a-gnps-CCMSLIB00006354915` GT=fumaric acid, predicted=myrcene).

Run two probes back-to-back:

1. Without `mass_tolerance_ppm` (current behaviour) — confirm myrcene
   still returned.
2. With `mass_tolerance_ppm=10` — report:
   - new pool size
   - new top-1 prediction
   - whether GT (cpd:C00122) is in the candidate list

Report both as JSON in the comparison report. **If the smoke shows
the filter doesn't help (e.g., pool empty, or true compound still not
top-1), pause and report — do not run the full batch.**

### D4 — Full Sub-6A real-id rerun under Phase A

```bash
bash -c '
source tools/candidate_prefilter/env.sh
export METAGENT_LLM_PROVIDER=openai
export METAGENT_OPENAI_BASE_URL=https://api.viviai.cc/v1
export METAGENT_OPENAI_API_KEY=$(cat api_key.txt | tr -d "[:space:]")
export METAGENT_OPENAI_MODEL=claude-opus-4-7
# IMPORTANT: pass mass_tolerance_ppm via a new CLI flag — must add to
# scripts/eval_sub6/run_baseline.py and threaded down through
# evaluation/sub6/run_sub6a.py and identification.py
python scripts/eval_sub6/run_baseline.py \
    --sub6a --id-strategy library_search \
    --mass-tolerance-ppm 10 \
    --out-dir data/eval/sub6 \
    --output-suffix _phase_a
'
```

The CLI flag `--output-suffix` is also new — make filename
`data/eval/sub6/sub6a_narratives_phase_a.jsonl` so the original
`sub6a_narratives.jsonl` (frozen) is preserved.

Expected runtime: 14 task × 9 spectra × ~5 s/spectrum (after mass
filter narrows the pool from 622 k to a few hundred) = ~10 minutes
identification + 14 × 60 s LLM narrative = ~25 minutes total wall.

Aggregate via `scripts/eval_sub6/aggregate_sub6a.py --narratives
data/eval/sub6/sub6a_narratives_phase_a.jsonl --out-dir
results/sub6a_real_id_phase_a`.

**Required headline numbers (compared to v3/v6 baselines):**

| metric | v3 baseline | **Phase A** |
|---|---:|---:|
| identification_accuracy_mean | 0.0625 | _measured_ |
| top1_pathway_strict | 0.214 | _measured_ |
| driver_precision | 0.000 | _measured_ |
| driver_recall | 0.000 | _measured_ |
| total wall time | 5h 21min | _measured_ |

Acceptance: id_acc ≥ 0.20 (i.e., ≥ 26 / 128 spectra correct top-1).
If id_acc < 0.15, escalate before running verifier.

### D5 — Verifier rerun on Phase A narratives (v7)

Use Claude Opus-4-7 via viviai relay (same as v5/v6 LLM provider).

```bash
bash -c '
export METAGENT_LLM_PROVIDER=openai
export METAGENT_OPENAI_BASE_URL=https://api.viviai.cc/v1
export METAGENT_OPENAI_API_KEY=$(cat api_key.txt | tr -d "[:space:]")
export METAGENT_OPENAI_MODEL=claude-opus-4-7
export MINIMAX_API_KEY=$METAGENT_OPENAI_API_KEY  # legacy, scripts read it
python scripts/eval_sub6/grade_with_verifier.py \
    --narratives data/eval/sub6/sub6a_narratives_phase_a.jsonl \
    --tasks data/benchmark/sub6/sub6a_e2e_tasks.jsonl \
    --out data/eval/sub6/sub6a_real_id_verdicts_v7_phaseA.jsonl \
    --track sub6a_real_id_phase_a
'
```

Then aggregate:

```bash
python scripts/eval_sub6/aggregate_verifier.py \
    --verdicts data/eval/sub6/sub6a_real_id_verdicts_v7_phaseA.jsonl \
    --narratives data/eval/sub6/sub6a_narratives_phase_a.jsonl \
    --tasks data/benchmark/sub6/sub6a_e2e_tasks.jsonl \
    --track sub6a_real_id_phase_a \
    --out-dir results/sub6a_real_id_verifier_v7_phaseA
```

Expected runtime: ~10 minutes (14 narratives × ~40 s sequential).

**Sequential, not parallel** — the viviai relay's SSL contention
under concurrent load was 23 % failure on v4 (see
`llm_provider_comparison_2026-05-04.md` §5).

Retries: if any narrative gets `error: "...timeout..."` or `SSL`,
strip the failed rows from the output JSONL and re-run the same
command (idempotent — only missing task_ids re-process).

### D6 — Comparison report

**File:** `reports/eval/library_search_phase_a_2026-XX-XX.md`

Required sections:

1. **Executive summary** (3 sentences)
   - Phase A id_acc number vs v3 baseline 6.25 %
   - Top1 pathway strict vs v3 21.4 %
   - Verifier verifiable% on Sub-6A real-id v6 (43.5 %) vs v7 phase A

2. **Failure-mode diagnosis** — pre-fix
   - Same 3 examples from this prompt (fumaric acid → myrcene etc.)
   - Plus: 2 more newly-collected from your D3 smoke

3. **Mass-window filter design**
   - chosen `mass_tolerance_ppm` default + justification
   - pool-size reduction stats (mean, median, p99 across 128 spectra)
   - per-spectrum runtime improvement

4. **Identification accuracy** — task-by-task table
   - 14 rows, columns: task_id, n_spectra, n_correct_v3, n_correct_phaseA,
     id_acc_phaseA, Δ
   - Footer: weighted means

5. **LLM extractor metrics (Sub-6A real-id baseline)**
   - top1_strict, top3_acceptance, driver_prec, driver_recall, false_noise
   - vs v3 (6.25 % id_acc) and Sub-6A perfect-id (100 % id_acc, the
     ceiling)

6. **Verifier impact (v7 vs v6)**
   - Per-claim-type table:
     pathway_relationship / set_enrichment / driver_metabolite /
     biological_claim — supp / unsupp / contra / unverif counts
   - Headline: Sub-6A real-id verifiable % v6 → v7

7. **3 sample identification flips** (failure → success)
   - For 3 spectra where v3 returned wrong compound and v7 returns
     correct compound: show GT, v3 prediction, v7 prediction, scores

8. **Remaining gap and Phase B/C/D recommendations**
   - Cite per-failure analysis: which spectra still fail, why
     (e.g., compound has zero remaining GNPS reference after
     self-exclusion → no signal possible at any mass tolerance)
   - Quantify: of the (128 − n_correct_phaseA) failures, what
     fraction is "structurally unsalvageable" vs "fixable in B/C/D"

9. **Provenance**
   - git commits in this session
   - file MD5 of the new JSONL outputs
   - `mass_tolerance_ppm` setting + GNPS pool md5 / size
   - run wall time

---

## Quality bar

- **Acceptance**: Sub-6A real-id `id_acc` ≥ 0.20 under Phase A
  (vs 0.0625 baseline). If you can't reach this without other
  architectural changes, escalate.
- All 36 existing library_search unit tests still pass.
- 4 new unit tests (D2) all pass.
- New runs preserve original v3 / v6 outputs at their original paths.
- Backward-compat invariant: `LibrarySearchRequest` calls without
  `mass_tolerance_ppm` produce bit-identical responses to current
  behaviour (tested in D2).
- Comparison report has clear before/after numbers, NOT
  "improved" without quantification.
- Verifier wall time stays under 30 minutes.
- Sub-6A real-id baseline rerun stays under 1 hour wall.

---

## Pitfalls

1. **Don't lower mass_tolerance_ppm below 5 ppm**. Some Sub-6A
   spectra are from MoNA / older instruments with limited mass
   accuracy. < 5 ppm filters out true matches.

2. **Don't set mass_tolerance_ppm > 25 ppm without a strong reason**.
   Wider window means more candidates, less discrimination, less
   gain. The whole point of Phase A is tighter filtering.

3. **Beware [M+H]+ vs [M-H]- adduct mixing**. Query precursor m/z
   must be compared against reference precursor m/z for the SAME
   adduct. Some sub6a spectra are [M-H]- (negative mode); their
   precursor m/z is M − 1.0073, while [M+H]+ references at M + 1.0073
   would falsely fail the filter. Check that comparison happens
   between same-adduct records or the filter is robust to it.

   Easy fix: compute the *neutral* monoisotopic mass for both query
   and reference (`mz_neutral = mz - adduct_mass_shift`), filter on
   neutral mass ±tol_ppm.

4. **The exclusion list for self-matching is upstream of this
   filter**. Don't move or replicate it. Existing `evaluation/sub6/
   identification.py::identify_spectrum::exclusion_source_ids` logic
   stays.

5. **`scripts/eval_sub6/run_baseline.py` may not currently accept
   `--mass-tolerance-ppm` or `--output-suffix`** — you'll need to add
   both. Thread the value through `run_sub6a_batch` →
   `run_sub6a` → `identify_spectrum` →
   `LibrarySearchRequest(mass_tolerance_ppm=...)`.

6. **GNPS pool md5 / size**: data lives at
   `/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned.mgf`
   (the .mgf path comes from `tools/candidate_prefilter/env.sh`).
   Don't re-download. Reuse the existing cached pool.

7. **Per-task GNPS exclusion list audit**:
   `evaluation/sub6/identification.py` already produces per-spectrum
   `excluded_source_ids_hit` audit. Phase A doesn't change this —
   verify your reruns still log it correctly.

8. **The viviai relay HTTP/2 issue**: `tools/library_search` doesn't
   touch this (it's a local sqlite + matchms call). But `verifier`
   does. Force HTTP/1.1 in any new requests code if needed (see
   `common/llm_client.py`).

9. **Don't accidentally regenerate baseline narratives with a
   different LLM**. The Phase A baseline must use Sub-6A's original
   `MiniMax-M2.7` narrative LLM (matching v3) so results compare
   apples-to-apples. If you accidentally use Opus-4-7 for the
   *narrative generation*, the comparison is contaminated. (Verifier
   step uses Opus-4-7 — that's correct.)

10. **Don't claim Phase B/C/D wins in this report**. Phase A only.

---

## Time budget (1 day)

- **08:00 – 09:00** First-action checklist + clarifying Q
- **09:00 – 10:00** D1 schema/code change + D2 unit tests
- **10:00 – 10:30** D3 single-spectrum smoke
- **10:30 – 12:00** D4 Sub-6A real-id full rerun (~25 min) + aggregate
- **12:00 – 13:00** Lunch
- **13:00 – 13:30** D5 verifier rerun (~10 min) + aggregate
- **13:30 – 16:00** D6 report writing + provenance MD5s
- **16:00 – 17:00** Buffer / re-runs / commit + branch push

If you finish in < 6 hours, **stop and don't try to do Phase B**.
Phase B / C / D are separate sessions with their own scope.

---

## File manifest expected at end of session

**New code (additive only):**
- `schemas/spectrum.py` (1 field added)
- `tools/library_search/tool.py` (mass-filter block in `_score_path_b`)
- `scripts/eval_sub6/run_baseline.py` (`--mass-tolerance-ppm`,
  `--output-suffix` flags)
- `evaluation/sub6/run_sub6a.py` (thread `mass_tolerance_ppm` kwarg)
- `evaluation/sub6/identification.py` (thread `mass_tolerance_ppm`
  kwarg)
- `tests/tool_tests/test_library_search.py` (4 new tests, additive)

**New data:**
- `data/eval/sub6/sub6a_narratives_phase_a.jsonl`
- `data/eval/sub6/sub6a_real_id_verdicts_v7_phaseA.jsonl`

**New results dirs:**
- `results/sub6a_real_id_phase_a/`
- `results/sub6a_real_id_verifier_v7_phaseA/`

**New report:**
- `reports/eval/library_search_phase_a_2026-XX-XX.md`

**Modified (existing files, additive only):**
- `tools/library_search/tool.py` (1 block added, no logic changed)
- `schemas/spectrum.py` (1 field added)
- `scripts/eval_sub6/run_baseline.py` (2 flags added)

---

## When you finish

1. Push branch `feature/library-search-mass-filter`.
2. Reply with:
   - id_acc number (the headline)
   - top1_pathway_strict number
   - verifiable% number
   - whether acceptance bar (id_acc ≥ 0.20) passed
   - link to the comparison report
3. **Do not start Phase B**.

---

*Derived from session-state as of 2026-05-05 (commit ed6896b on
feature/verifier-kegg-hierarchy).*
