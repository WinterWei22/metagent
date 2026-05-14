# Track Layer 6c Phase B — Pathway Phrase Resolver Loosening

**Session ID:** `track_layer6c_phrase_resolver_phase_b`

**Branch:** `feature/layer6c-phrase-resolver`

**Estimated work:** 1 day

---

## Context

The v8 combined report (`reports/eval/v8_combined_phase_a_layer6c_2026-05-06.md`)
documented an **interaction effect**:

- **Phase A** (commit `8588a62`/`7238926`) raised Sub-6A real-id
  `id_acc` from 6.25 % to 72.07 % by adding a precursor-mass window
  to `library_search`. The LLM now sees real compound names.
- **Direction 3 / Layer 6c contra** (commit `a4a081e`) added a
  CONTRADICTED branch on biological_claim that fires when (compound
  resolvable) ∧ (pathway resolvable) ∧ (no overlap in RaMP
  `analytehaspathway`). On v6 narratives this produced 39 / 36 / 24
  contra across the three tracks.
- **v8 (combined)**: on Sub-6A real-id, the LLM (now writing about
  real compounds) uses *more specific sub-pathway phrasing* —
  "Fumaric acid is released during the adenylosuccinate-lyase step
  of de-novo purine synthesis" — and Layer 6c's pathway phrase
  resolver fails on these multi-clause phrases. **bio contra
  drops from 24 (v7-C) to 0 (v8) on Sub-6A real-id.**

**223 of 477 Sub-6A real-id v7-phaseA biological_claim rows have a
RaMP-resolvable compound subject; only ~5 also have a resolvable
pathway phrase.** 218 contra opportunities are sitting on the table.

This session loosens Layer 6c's pathway phrase resolver so D3's contra
path can fire on Phase A narratives, recovering bio contra to a
target of **≥ 15 on Sub-6A real-id v8** without regressing the 39 / 36
contra counts on the other two tracks.

---

## Hard scope boundaries

**You MAY:**

- Modify `verifier/layers/biological_sub6.py` —
  **only the pathway-resolution helpers** (`_first_phrase`,
  `_resolve_pathway` if used, plus any new helpers you add at the
  bottom of the file).
- Modify `verifier/claim_fields.py` only if you find the regex
  there (`_PATHWAY_PHRASE_RE`) needs widening; if so, add new
  patterns rather than editing existing ones.
- Add helper(s) at the bottom of `biological_sub6.py` (e.g.
  `_normalise_phrase`, `_reverse_fuzz_pathway`).
- Open RaMP-DB read-only via the same `_get_connection` pattern
  Layer 6d / D3 use.
- Modify `tests/test_verifier/test_biological_sub6.py` (additive).
- Re-run the verifier on saved narratives via the existing
  `scripts/eval_sub6/replay_layer6c.py` (see D5).
- Write a new comparison report under `reports/verifier/`.

**You MAY NOT:**

- Modify `verifier/layers/{set_enrichment,driver_metabolite,
  pathway_relationship}.py`. Other layers stay frozen.
- Add a new ClaimType or ClaimSubtype.
- Modify `verifier/agent.py` (the dispatcher).
- Modify the contra branch's verdict logic itself
  (`_check_compound_pathway_membership_in_ramp` from D3 —
  unchanged). You're improving the inputs that flow into it, not
  its decision tree.
- Modify Sub-6 task data, KEGG reaction graph, or compound aliases.
- Re-run baseline LLM narratives — the v3, v6, and Phase A
  narratives are FROZEN. Use `replay_layer6c.py` for token-free
  reruns.
- Touch `verifier/claim_classifier.py` or any Stage 1 / Stage 2
  code.
- Lower `MIN_KNOWN_PATHWAYS_FOR_CONTRA` to compensate for poor
  phrase resolution. The threshold = 3 is locked.

---

## Background reading (mandatory before first action)

1. `reports/eval/v8_combined_phase_a_layer6c_2026-05-06.md` §4 — the
   interaction-effect mechanism + 223-vs-5 quantification.
2. `reports/verifier/layer6c_contra_path_2026-05-06.md` §7.1 +
   §7.2 — RaMP coverage gaps + phrase-regex limitation
   ("UNSUPPORTED-vs-CONTRADICTED conflation").
3. `reports/eval/library_search_phase_a_2026-05-06.md` §5 (LLM
   metrics) — Phase A narrative shape changes vs v3.
4. `verifier/layers/biological_sub6.py` — read whole file. Pay
   attention to:
   - `_PATHWAY_PHRASE_RE` (imported from `verifier/claim_fields.py`)
   - `_first_phrase` (line ~300)
   - `_check_compound_pathway_membership_in_ramp` (line ~250-490 —
     this consumes the resolved pathway IDs; you do NOT modify it)
5. `verifier/claim_fields.py` — find the regex actually used.
6. `data/eval/sub6/sub6a_real_id_verdicts_v7_phaseA.jsonl` — load 30
   biological_claim rows with `verdict='unsupported'` and inspect
   their phrasing patterns (the "diagnosis" step below).
7. `scripts/eval_sub6/replay_layer6c.py` — D4's replay tool you
   reuse.

---

## First-action checklist (return to me, do NOT start coding)

1. Confirm reading of the 7 background files.
2. **Phrase audit** — Sample 30 random
   `biological_claim` rows from
   `data/eval/sub6/sub6a_real_id_verdicts_v7_phaseA.jsonl` where
   verdict ∈ {unsupported, unverifiable_v0} AND `subject` resolves
   via `tools.kegg.reachability.resolve_compound_to_kegg`. For each:
   - what does `_first_phrase(claim_text)` return today?
   - if you mentally normalise to a "canonical pathway name", what
     would it become? (e.g. "the de-novo purine synthesis pathway"
     → "purine metabolism")
   - does that canonical name resolve in RaMP `pathway` table?
   Categorise by phrasing pattern:
   - **A. leading prepositional / verb fragment** — "during the X
     step of Y", "as part of the Y", "in the Z pathway" → strippable
   - **B. embedded pathway in subordinate clause** — "X is released
     in the Y pathway as part of the Z step" — multi-pathway phrase
   - **C. no recognisable pathway phrase** — pure mechanism /
     process talk
   - **D. pathway is named but RaMP doesn't have it** —
     "carnitine palmitoyl-CoA shuttle"
   Report per-bucket counts.
3. **RaMP coverage probe** — for the same 30 claims, check if the
   compound's top-3 RaMP pathways (queried from
   `analytehaspathway`) contain a stem (≥ 4-character word, lower-cased)
   that appears in the claim text. Count how many claims would gain
   resolution via this "compound-side reverse-fuzz" approach.
4. Pick the **two (or three) most promising fixes** based on your
   audit. Recommended starting set:
   - **Fix-1 (small)**: `_normalise_phrase` strips leading prepositional /
     verb fragments and trims trailing "step of", "metabolism pathway"
     → "metabolism", etc.
   - **Fix-2 (medium)**: when `_first_phrase` returns None or its
     RaMP lookup fails, fall back to "compound-side reverse-fuzz" —
     enumerate the compound's top-N RaMP pathways and check whether
     any of them appears (stem-match) in the claim text.
5. Estimate per-fix the bio contra recovery on Sub-6A real-id v8
   (pre-coding rough estimate).
6. Confirm that your fixes do NOT regress the 39 / 36 / 24 v7-C bio
   contra counts (run replay_layer6c.py on v6 narratives after
   patching, verify counts are ≥ 39 / ≥ 36 / ≥ 24).
7. Ask any clarifying questions.

Do NOT start coding until I confirm.

---

## Proposed design — subject to confirmation in step 7

### Fix-1: `_normalise_phrase` (strip-and-canonicalise)

```python
def _normalise_phrase(raw: str) -> str | None:
    """Reduce a noisy LLM-emitted pathway phrase to a stem that
    RaMP's pathway name lookup is more likely to match.

    Steps:
      1. Strip a leading prepositional / verb fragment up to the
         first capitalised word OR pathway-keyword stem
         ("purine", "methionine", ...).
      2. Trim trailing scaffolding ("step of", "pathway", "cycle"
         when redundant) — keeping the stem.
      3. Drop "de-novo", "de novo", "salvage" qualifiers when stem
         + qualifier is not in RaMP but stem alone is.
      4. Compound transformations: try original → strip-leading →
         strip-leading + trim-trailing — return first that
         resolves in RaMP.
    """
```

Examples:

| LLM phrase | _first_phrase before | _normalise_phrase | RaMP match |
|---|---|---|---|
| "is released during the adenylosuccinate-lyase step of de-novo purine synthesis" | "step of de-novo purine synthesis" | "purine synthesis" → "purine metabolism" | ✅ |
| "in the carnitine palmitoyl-CoA shuttle pathway" | "carnitine palmitoyl-CoA shuttle pathway" | "carnitine pathway" → "Carnitine biosynthesis" | ✅ |
| "as part of the BH4 regeneration cycle" | "BH4 regeneration cycle" | "BH4 metabolism" → no match; try "tetrahydrobiopterin" → ✅ | ✅ |

### Fix-2: compound-side reverse-fuzz

When Fix-1 still doesn't resolve, query RaMP for the compound's top-N
known pathways and look for any one of them appearing as a phrase in
the claim text:

```python
def _reverse_fuzz_pathway(claim_text: str, compound_rampId: str,
                           ramp_conn) -> list[str] | None:
    """Last-resort pathway resolution.

    Pull the top-N (default 50) most-pathway-pop pathways for this
    compound from RaMP. For each, check whether the pathway's
    canonical name (or any 4+-character stem from it) appears
    word-bounded in `claim_text`. Return the matched
    pathwayRampIds (sorted by descending stem length, so longer
    matches win)."""
```

This catches the case where the LLM uses an aggregated name the
phrase regex won't naturally extract:

```
LLM: "Fumaric acid is released during the adenylosuccinate-lyase step
      of de-novo purine synthesis"

Compound = Fumaric acid (rampId RAMP_C_000218XXX)
Top-50 RaMP pathways for Fumaric acid include "Purine metabolism"
"Purine" appears in the claim text → match
→ return ["RAMP_P_xxx for Purine metabolism"]
```

### Fix-3 (optional, if first two underperform): named-step gazetteer

A small hand-curated list of {step name → canonical pathway name}
for ~20 common steps the LLM mentions ("adenylosuccinate-lyase
step" → "Purine metabolism", "BH4 regeneration" →
"Tetrahydrobiopterin metabolism", etc.). Drop in `verifier/layers/_step_gazetteer.json`.

Use this only if Fix-1 + Fix-2 together leave > 50 claims still
unresolved on Sub-6A real-id v8.

---

## Deliverables

### D1 — `_normalise_phrase` + tests

**Files:**
- `verifier/layers/biological_sub6.py` — add `_normalise_phrase`
  helper at file bottom; call from `_first_phrase` (or an enriched
  caller) before the existing `_PATHWAY_PHRASE_RE` lookup.
- `tests/test_verifier/test_biological_sub6.py` — add 8-12 tests
  covering the patterns from your audit.

Tests must include:
- 5+ test cases from the actual audit (verbatim claim text)
- 3 negative cases (where phrase normalisation should still return
  None — pure-mechanism claims)
- 2 regression cases (existing v6 phrasings still resolve to the
  same pathway as before)

### D2 — `_reverse_fuzz_pathway` + tests

**Files:**
- `verifier/layers/biological_sub6.py` — add helper.
- `tests/test_verifier/test_biological_sub6.py` — add 5+ tests.

The reverse-fuzz must:
- Use a configurable top-N parameter (default 50) — bigger N
  increases recall but also false-positive risk
- Word-bounded matching only (avoid "purine" matching "purinergic")
- Sorted by descending stem length when multiple pathways match
- Honor the existing `MIN_KNOWN_PATHWAYS_FOR_CONTRA = 3` threshold
  (a compound with < 3 RaMP pathways still falls through)

### D3 — Wire fixes into `verify_biological_sub6` dispatch

The dispatcher's pathway-resolution call site should try in order:

1. Existing `_first_phrase` + `_PATHWAY_ID_RE` (no change)
2. **NEW**: `_normalise_phrase` if step 1 returned None or didn't resolve
3. **NEW**: `_reverse_fuzz_pathway` (if compound resolved AND step 2
   still no match)
4. Fallback to UNVERIFIABLE_V0 / UNSUPPORTED as today

**Backward-compat invariant**: every claim that resolved a pathway in
v6/v7-C must still resolve to the SAME pathway under the new
dispatcher. The new logic only adds additional resolution attempts
when the existing ones fail.

### D4 — Replay reruns

Replay both narrative families with the patched layer:

```bash
# v6 narratives (unchanged from D3) — must produce ≥ 39 / 36 / 24 contra
METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
  python scripts/eval_sub6/replay_layer6c.py
# Check that v7_contra/* still has bio contra ≥ 39 / 36 / 24 — REGRESSION CHECK
```

Then add a new replay against Phase A narratives (Sub-6A real-id only):

```python
# Adapter (write a small one-off — like the v8 combined orchestrator
# I wrote in main session — that takes Phase A's v7-phaseA verdict
# file and replays the patched Layer 6c on it)

src = "data/eval/sub6/sub6a_real_id_verdicts_v7_phaseA.jsonl"
dst = "data/eval/sub6/sub6a_real_id_verdicts_v9_phaseB.jsonl"
```

Aggregate via existing
`scripts/eval_sub6/aggregate_verifier.py` into:

- `results/sub6{b,a_perfect_id,a_real_id}_verifier_v9_phaseB/`
  (yes, sub6b and sub6a_perfect_id should also be re-aggregated to
  confirm zero regression — their narratives are still v6, but the
  Layer 6c patches affect them too)

### D5 — Comparison report

**File:** `reports/verifier/layer6c_phrase_resolver_phase_b_2026-XX-XX.md`

Required sections:

1. **Executive summary** (3 sentences)
   - Sub-6A real-id v9 bio contra (target ≥ 15)
   - v6-narrative tracks (Sub-6B / Sub-6A perfect) bio contra
     unchanged
   - v3 → v9 final headline numbers across all 3 tracks

2. **Phrase audit results** — your 30-claim categorisation from
   First-action checklist (A / B / C / D bucket counts)

3. **Fix mechanisms** — per-fix description + audit-time estimate
   vs measured contribution

4. **Per-track bio contra deltas** (the headline)

   ```
                       v7-C   v8     v9-PhaseB   Δ vs v8
   Sub-6B bio contra   39     39     N           +N
   Sub-6A perfect      36     36     M           +M
   Sub-6A real-id      24     0      P           +P    ← target ≥ 15
   ```

5. **Per-claim-type roll-up** for v9 (full breakdown)

6. **5 concrete CONTRADICTED examples on Sub-6A real-id v9** — each
   with verbatim Phase A claim text, Fix-1/Fix-2 trace
   ("Fix-1 normalised to X", "Fix-2 reverse-fuzzed to Y"),
   final verdict + correction

7. **3 regression cases** showing v6 narratives' v7-C verdicts
   preserved exactly (sample 3 contra claims from
   `sub6b_verifier_v7_contra` — verify they're still contra in v9)

8. **Limitations + Phase C suggestions**
   - Cases your fix missed (the 30 unresolved-after-Phase-B from
     the audit if applicable)
   - Whether Fix-3 (gazetteer) was needed and what's still left
   - Stage 1/2 (extract/classify) phrasing-style biases that no
     downstream fix can resolve

9. **Provenance** — git commit, file MD5s, RaMP md5 + version

---

## Quality bar

- **Acceptance** (hard floors):
  - Sub-6A real-id v9 bio contra ≥ **15** (was 0 in v8)
  - Sub-6B v9 bio contra ≥ **39** (no regression from v7-C)
  - Sub-6A perfect-id v9 bio contra ≥ **36** (no regression)
- **No SUPPORTED regression**: Sub-6B + Sub-6A perfect bio supp
  in v9 ≥ 95 % of v7-C value (v7-C: 112 / 84). i.e. Fix-1's
  normalisation must not delete supp claims.
- **Existing Layer 6c tests still pass**: full
  `tests/test_verifier/test_biological_sub6.py` suite green; full
  `tests/test_verifier/` 263+ test count maintained.
- **Phrase-resolution decision is auditable** — `tool_evidence`
  carries `phrase_resolution_path: "first_phrase" | "normalise" |
  "reverse_fuzz"` so the report can stratify contra by which fix
  produced it.
- **No accidental over-claim**: Sub-6A real-id v9 contra rate
  (contra / total bio) ≤ 25 %. Above that, the resolver is firing
  too aggressively and producing false positives.

---

## Pitfalls

1. **Don't match "purinergic" with "purine" stem** — use word
   boundaries `\b` in your reverse-fuzz regex.

2. **Don't lower `MIN_KNOWN_PATHWAYS_FOR_CONTRA`** — the threshold
   guards against contra firing on under-characterised compounds.
   D3 deliberately set 3; phase B keeps it.

3. **Don't accidentally upgrade UNVERIFIABLE_V0 to UNSUPPORTED** —
   if the disease-keyword early-return fires, stay on UV0 path.
   New phrase resolvers run only AFTER disease check.

4. **Don't normalise phrases to wildly different pathways** —
   `_normalise_phrase` should be conservative. If it strips down to
   a 1-word stem like "metabolism", that matches everything. Reject
   normalised phrases shorter than 5 characters.

5. **Beware overlapping stems**: "salvage" could match
   "Pyrimidine salvage" or "Purine salvage". When multiple match,
   prefer the one whose **other tokens** also appear in the claim
   text.

6. **Stage 1 LLM noise**: replay_layer6c is NOT re-extracting; it's
   re-dispatching the existing v6 / v7-phaseA classified claims
   through the patched layer. Don't be confused if claim count
   stays identical — Layer 6c isn't supposed to change claim count.

7. **The dispatcher branches must short-circuit correctly**: if
   `_first_phrase` resolves, do NOT also call `_normalise_phrase`
   and risk double-resolution. Run-once-stop semantics.

8. **`_reverse_fuzz_pathway` MUST require compound to be resolved**
   first. Don't run it on unresolved compounds (it would loop over
   all 463 k RaMP rampIds).

9. **Don't add a new ClaimType / ClaimSubtype** — same constraint as
   D3.

10. **Test isolation**: your unit tests must inject a tiny sqlite
    fixture, not the real RaMP. RaMP is 1.9 GB and tests should
    run < 5 s.

---

## Time budget (1 day)

- 08:00 – 09:00 First-action checklist (30-claim phrase audit)
- 09:00 – 09:30 Clarifying Q + my approval
- 09:30 – 11:00 D1 `_normalise_phrase` + 8-12 tests + suite green
- 11:00 – 12:30 D2 `_reverse_fuzz_pathway` + tests + suite green
- 12:30 – 13:30 Lunch
- 13:30 – 14:00 D3 wire into dispatch + suite still green
- 14:00 – 14:30 D4 replay — quick smoke (sub6a real-id v9)
- 14:30 – 15:00 D4 full reruns + aggregate (Sub-6B / 6A perfect /
  6A real-id)
- 15:00 – 16:30 D5 report writing
- 16:30 – 17:00 Buffer + commit + push

If you finish in < 6 hours, **stop**. Don't speculatively try
Fix-3 (gazetteer) unless audit data showed it's needed.

---

## File manifest expected at end of session

**Modified (existing files, additive only):**
- `verifier/layers/biological_sub6.py` — add `_normalise_phrase` +
  `_reverse_fuzz_pathway` + dispatcher changes

**New code:**
- `tests/test_verifier/test_biological_sub6.py` — additive only

**New data:**
- `data/eval/sub6/sub6{b,a_perfect_id,a_real_id}_verdicts_v9_phaseB.jsonl`

**New results dirs:**
- `results/sub6{b,a_perfect_id,a_real_id}_verifier_v9_phaseB/`

**New report:**
- `reports/verifier/layer6c_phrase_resolver_phase_b_2026-XX-XX.md`

---

## When you finish

1. Push branch `feature/layer6c-phrase-resolver`.
2. Reply with:
   - Sub-6A real-id v9 bio contra count (the headline)
   - Sub-6B + Sub-6A perfect bio contra (regression check)
   - Confirm acceptance bar passed
   - link to comparison report
3. **Do NOT touch Phase A code.** Don't commit anything outside
   `verifier/layers/biological_sub6.py` and the test/results/report
   files listed above.

---

*Derived from session-state as of 2026-05-06 (commit `a8110a0` on
feature/library-search-mass-filter).*
