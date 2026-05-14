# Track Layer 6c — Add CONTRADICTED Path to biological_claim Verifier

**Session ID:** `track_layer6c_contra_path`

**Branch:** `feature/layer6c-contra-path`

**Estimated work:** 1 day (1 person)

---

## Context

Layer 6c (`verify_biological_sub6` in
`verifier/layers/biological_sub6.py`) currently handles three verdicts
for `BIOLOGICAL` typed claims about Sub-6 narratives:

| Verdict | Trigger |
|---|---|
| `SUPPORTED` | claim's pathway phrase resolves to `task.top_pathways[:10]` or RaMP `pathway` table |
| `UNSUPPORTED` | claim resolves but pathway not found in either |
| `UNVERIFIABLE_V0` | disease keyword detected OR no pathway phrase extractable |

**It never returns `CONTRADICTED`.** This is a deliberate v0 conservative
choice — but it leaves a real distinction unmade. Today the layer
**cannot tell apart**:

- *"Acrolein is part of polyamine biosynthesis"*
  — Acrolein (cpd:C01471) is verifiably **not** in polyamine biosynthesis;
  RaMP `analytehaspathway` lists Acrolein's pathways and "polyamine biosynthesis" isn't one.
  → currently UNSUPPORTED. **Should be CONTRADICTED.**

- *"GlcNAc-1-P elevation may represent compensatory hexosamine pathway activation"*
  — GlcNAc-1-P (cpd:C04256) IS in the hexosamine pathway. Strong support.
  → already SUPPORTED. (correct)

- *"Glutathione is involved in oxidative stress response"*
  — vague, no specific pathway, no RaMP claim to check.
  → UNVERIFIABLE_V0. (correct, no change wanted)

We want the layer to **distinguish "RaMP says no" from "I don't know"**
because:

- Downstream rewriter / orchestrator can act on CONTRADICTED but not on
  UNSUPPORTED (the latter is too soft to flag)
- The audit log gets sharper (consumer reading verdicts can tell
  hard errors apart)
- Sub-6B biological_claim today: 624 total / 275 unsupp / 0 contra.
  Estimate: ~50-100 of those 275 are real CONTRADICTED material being
  buried in UNSUPPORTED. After fix: contra ratio goes from 0% to ~3-7%
  on biological_claim.

This session adds the contra path **without changing supp / unverif
behaviour**.

---

## Hard scope boundaries

**You MAY:**

- Modify `verifier/layers/biological_sub6.py` —
  **only the `verify_biological_sub6` function body** (its dispatch logic).
- Add helper(s) at the bottom of `biological_sub6.py` (e.g.
  `_check_compound_pathway_membership_in_ramp`).
- Read RaMP via the same `_get_connection` pattern Layer 6d uses
  (don't re-implement).
- Modify `tests/test_verifier/test_biological_sub6.py` (add tests; do
  not modify existing ones unless the test specifically asserted "no
  contra ever" — in which case rewrite the test name + body to assert
  the new behaviour).
- Re-run the verifier against saved narratives via
  `scripts/eval_sub6/grade_with_verifier.py` (see D5).
- Write a new comparison report under `reports/verifier/`.

**You MAY NOT:**

- Modify `verifier/layers/{set_enrichment,driver_metabolite,
  pathway_relationship}.py`. Other layers stay frozen.
- Add a new ClaimType or ClaimSubtype.
- Modify `verifier/agent.py` (the dispatcher already routes
  `BIOLOGICAL` to this layer).
- Modify Sub-6 task data, KEGG reaction graph, or compound aliases.
- Re-run baseline LLM narratives — only the verifier reruns.
- Touch `verifier/claim_classifier.py` or any Stage 1 / Stage 2 code.
- Conflict-zone rule: **do NOT add disease-pathway database lookup**
  (`disgenet`, `omim`, etc.) — that's a separate session's scope.
  If you find yourself wanting to defer to a disease DB, return
  UNVERIFIABLE_V0 as today.

---

## Background reading (mandatory before first action)

1. `reports/verifier/verifier_sub6_enrichment_layers_delivery_2026-05-01.md`
   §4 (`Layer 6c — biological_sub6`) — current verdict policy.
2. `reports/verifier/llm_3way_comparison_2026-05-05.md` §4
   (`biological_claim` per-track verdict drilldown — sets v6 baselines:
   624 / 531 / 471 total claims, 0 contra everywhere).
3. `reports/verifier/alias_expansion_l1_fix_2026-05-05.md` §3.3
   (driver_metabolite collateral effect — illustrates how RaMP
   expansion lets the verifier resolve more compound names; same
   benefit applies here).
4. `verifier/layers/biological_sub6.py` — read whole file.
5. `verifier/layers/pathway_relationship.py::_shared_compounds` — same
   `analytehaspathway` query pattern you'll mirror.
6. `data/kegg/reaction_graph.sqlite` — for the alias resolver
   (`compound_aliases` table, 53 925 rows, expanded by L1 fix).
7. `tools/kegg/reachability.py::resolve_compound_to_kegg` — alias
   resolver to call for compound → cpd:C-id.

---

## First-action checklist (return to me, do NOT start coding)

1. Confirm reading of the 7 background files.
2. Sample 30 random `biological_claim` rows from
   `data/eval/sub6/sub6b_verdicts_v6_opus47_aliases.jsonl` whose
   verdict is currently UNSUPPORTED. Categorise them:
   - **A. true CONTRADICTED material** — claim names a specific
     compound + specific pathway, and RaMP `analytehaspathway` should
     be able to confirm "X is NOT in Y" with some baseline data
   - **B. genuinely UNSUPPORTED** — claim is vague, single-compound
     role / process / generic biology
   - **C. should have been SUPPORTED** — false negative under current
     logic
   Report counts.
3. **Critical sanity probe**: pick 3 candidate claims from category A.
   For each, run the proposed contra-detection logic by hand:
   - resolve compound name → cpd:C-id (via `compound_aliases`)
   - resolve pathway phrase → RaMP `pathwayRampId`
   - query RaMP `analytehaspathway` for (compound rampId, pathway rampId)
   - confirm: returns 0 rows, AND the compound HAS at least N other
     pathways (so we know we have data for it, not just an unmapped
     compound)
   Report the threshold N you recommend (1? 3? 5?). Higher = more
   conservative, fewer false-positive contra.
4. Estimate: how many of the 275 UNSUPPORTED Sub-6B biological claims
   would flip to CONTRADICTED under your proposed N? Same for the
   other tracks.
5. Confirm that your design does NOT regress any current SUPPORTED or
   UNVERIFIABLE_V0 verdict (verify by walking the existing decision
   tree).
6. Ask any clarifying questions.

Do NOT start coding until I confirm.

---

## Design — proposed contra path (subject to confirmation in step 6)

```python
# Pseudo-code for the new contra branch (added near the END of
# verify_biological_sub6's dispatch logic, AFTER the existing
# "found in top_pathways or RaMP → SUPPORTED" branch).

def verify_biological_sub6(claim, source_report, *, conn=None):
    # ... existing extraction + disease-keyword + pathway-phrase
    # logic stays untouched ...

    if pathway phrase resolved to one or more RaMP pathwayIds AND
       claim's compound subject resolved to cpd:C-id:

        compound_ramp_id = lookup compound_id in RaMP source where
                           IDtype='kegg' AND sourceId=cpd_id

        membership_rows = SELECT 1 FROM analytehaspathway
                          WHERE rampId = compound_ramp_id
                            AND pathwayRampId IN (resolved_pathway_ids)

        if any membership_rows:
            return SUPPORTED   # existing behaviour, unchanged

        # No membership — but we need to ensure RaMP has data on this
        # compound at all (otherwise "no membership found" is just
        # missing data, not a real contradiction)
        N_PATHWAYS_KNOWN = SELECT COUNT(*) FROM analytehaspathway
                            WHERE rampId = compound_ramp_id

        if N_PATHWAYS_KNOWN >= MIN_KNOWN_PATHWAYS_FOR_CONTRA:
            # We KNOW this compound's pathway memberships, and the
            # claimed pathway isn't one. This is a real CONTRADICTED.
            return CONTRADICTED with evidence:
                "RaMP-DB knows compound X is in {N_PATHWAYS_KNOWN}
                 pathways; the claimed pathway Y is not among them."
                + correction = "Compound X is associated with
                                {top-3 actual pathways} per RaMP."
        else:
            # We don't have enough RaMP data to make a strong call.
            return UNSUPPORTED   # existing behaviour
```

**Recommended `MIN_KNOWN_PATHWAYS_FOR_CONTRA` default: 3** — based on
analyte coverage in RaMP (compounds with < 3 pathway memberships are
typically poorly characterised; refusing to contra them avoids false
positives from incomplete data).

`enrichment_context.tool_evidence` should record:
```python
{
    "ramp_compound_id": "RAMP_C_xxx",
    "ramp_pathway_ids_claimed": ["RAMP_P_xxx", ...],
    "n_pathways_known": int,
    "membership_check": "no_intersection",
    "top_actual_pathways": ["pathway A", "pathway B", "pathway C"],
}
```

---

## Deliverables

### D1 — Code change

**Files:**
- `verifier/layers/biological_sub6.py` — add `_check_compound_pathway_membership_in_ramp` helper at file bottom; insert contra branch in main dispatch
- `verifier/schemas.py` — only if new ClaimSubtype values are needed (likely **no**; subtype `pathway_membership` already exists)

Keep the function pure-additive: every existing claim that previously
got SUPPORTED / UNSUPPORTED / UNVERIFIABLE_V0 must produce the same
verdict UNLESS the new branch genuinely upgrades it.

### D2 — Unit tests

**File:** `tests/test_verifier/test_biological_sub6.py` (additive)

Add at minimum:

- `test_biological_contra_compound_not_in_pathway`: synthetic compound
  in RaMP with 5 pathway memberships, claim names a different
  pathway → CONTRADICTED with correction
- `test_biological_unsupp_when_compound_underexplored`: compound with
  only 1 known pathway → UNSUPPORTED (not contra) under threshold 3
- `test_biological_supp_unchanged_when_compound_in_pathway`: existing
  SUPPORTED case still SUPPORTED, no regression
- `test_biological_unverif_disease_keyword_unchanged`: disease keyword
  still triggers UNVERIFIABLE_V0
- `test_biological_no_compound_resolution_unchanged`: claim with
  unresolvable compound subject still goes through existing path

All 4 new tests pass; 25+ existing biological_sub6 tests still pass.
Full verifier test suite still 373/373.

### D3 — Real-data smoke (3 narratives)

Pick 3 narratives from `data/eval/sub6/sub6b_verdicts_v6_opus47_aliases.jsonl`
that contain biological claims known to be contradicted (from your
First-action checklist categorisation).

Run `verify_sub6` end-to-end on those 3 narratives **with current
code** and your patched code; diff the verdicts. Confirm:

- Real contradicted claims now flip from UNSUPPORTED → CONTRADICTED
- No SUPPORTED claim regresses

Report 3 example flips (verbatim claim text + before/after verdict +
RaMP evidence).

### D4 — Full Sub-6B verifier rerun (with v6 narrative + Opus extractor)

```bash
bash -c '
export METAGENT_LLM_PROVIDER=openai
export METAGENT_OPENAI_BASE_URL=https://api.viviai.cc/v1
export METAGENT_OPENAI_API_KEY=$(cat api_key.txt | tr -d "[:space:]")
export METAGENT_OPENAI_MODEL=claude-opus-4-7
export MINIMAX_API_KEY=$METAGENT_OPENAI_API_KEY
python scripts/eval_sub6/grade_with_verifier.py \
    --narratives results/sub6/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
    --out data/eval/sub6/sub6b_verdicts_v7_contra.jsonl \
    --track sub6b_contra
'
```

Same for Sub-6A perfect-id and Sub-6A real-id (use the v6 narrative
files: `data/eval/sub6/sub6a_narratives_perfect_id.jsonl` and
`data/eval/sub6/sub6a_narratives.jsonl`).

Use **claude-opus-4-7** to match the v6 baseline so the comparison
isolates the contra-path change. Sequential, not parallel.

Aggregate via `scripts/eval_sub6/aggregate_verifier.py` into:

- `results/sub6b_verifier_v7_contra/`
- `results/sub6a_perfect_id_verifier_v7_contra/`
- `results/sub6a_real_id_verifier_v7_contra/`

Expected runtime: ~25 min sequential.

### D5 — Comparison report

**File:** `reports/verifier/layer6c_contra_path_2026-XX-XX.md`

Required sections:

1. **Executive summary** (3 sentences)
2. **Pre-fix diagnosis** — 30-claim categorisation from First-action
   checklist (A / B / C counts)
3. **Design** — `MIN_KNOWN_PATHWAYS_FOR_CONTRA` value + tool_evidence
   schema
4. **Per-track v6 → v7 deltas** — biological_claim contra count
   change (key metric)
   ```
                         v6 contra   v7 contra   Δ
   Sub-6B biological     0           N           +N
   Sub-6A perfect bio    0           M           +M
   Sub-6A real-id bio    0           P           +P
   ```
   Plus: confirm supp / unverif counts unchanged (acceptance: ≤ 5%
   drift). If supp drops by >5%, you broke something.
5. **3 concrete CONTRADICTED examples** — verbatim claim, RaMP
   evidence, correction sentence
6. **Per-claim-type verdict roll-up** — full breakdown
   (`pathway_relationship` / `set_enrichment` / `driver_metabolite` /
   `biological_claim` / `grounded`) showing only `biological_claim`
   row changed
7. **Limitations + downstream consumer impact** —
   - Note: rewriter doesn't yet act on CONTRADICTED biological claims
   - Suggest: orchestrator can use the contra rate as a baseline
     reasoning-quality signal
8. **Provenance** — git commit, file MD5s

---

## Quality bar

- **Acceptance**:
  - Sub-6B biological_claim contra count: 0 → ≥ **20** (≥ 3.2% of 624)
  - Sub-6A perfect-id biological_claim contra: 0 → ≥ 15
  - Sub-6A real-id biological_claim contra: 0 → ≥ 12
  - These are floors. Hitting 30+ on Sub-6B is realistic.
- No regression: existing SUPPORTED count drops by < 5%; existing
  UNVERIFIABLE_V0 count drops by < 5%. Track via per-track summary
  diff.
- All 373 verifier+kegg+eval_sub6 tests still pass.
- All new claims with verdict=CONTRADICTED carry a `correction` field
  pointing at the actual top-3 pathways.

---

## Pitfalls

1. **Don't drop the disease-keyword early-return.** The current logic
   defers to UNVERIFIABLE_V0 when the claim text contains
   `disease|disorder|syndrome|cancer|...`. Keep this. Disease-pathway
   verification is **a different session's scope** (do NOT
   accidentally reach into it).

2. **The compound resolver is the v6-expanded `compound_aliases`
   table.** Use `tools.kegg.reachability.resolve_compound_to_kegg` —
   do NOT re-implement.

3. **Compound → rampId**: not all KEGG cpd:C-IDs are in RaMP. The
   v6 RaMP expansion covered 2 393 of 4 307 KEGG-graph compounds; the
   remaining 1 914 are KEGG-only. If a compound resolves to cpd:C-id
   but no rampId is found, return UNSUPPORTED (not contra), since we
   can't query RaMP analytehaspathway.

4. **"Pathway resolution" reuses Layer 6d's helpers.** Do NOT
   reimplement `_resolve_pathway` or fuzzy matching — import from
   `verifier.layers.pathway_relationship` if needed (they're public
   in that module via the `_resolve_pathway` function; if not,
   factor a shared helper into a new `verifier/layers/_pathway_resolve.py`
   instead of duplicating).

5. **The threshold matters.** `MIN_KNOWN_PATHWAYS_FOR_CONTRA = 3`
   means: only contra when RaMP has at least 3 other pathway
   memberships for the compound. If you set it to 1, lots of
   sparsely-mapped compounds will get false-positive contra. If 10,
   contra rate stays very low. Pick 3, document the choice, allow
   tuning via env var if you have time.

6. **Don't add CONTRADICTED for `pathway_membership` subtype only.**
   The contra path applies to any biological_claim where compound +
   pathway both resolve. Subtype is decorative (informational) here.

7. **Read-only RaMP**: open the connection with `mode=ro` URI to
   prevent accidental writes. RaMP is a snapshot.

8. **Threshold trade-off documented in §5 of D5 report.**
   Show what supp / unsupp / contra distribution looks like at
   thresholds 1, 3, 5, 10 (a small ablation). Pick 3 unless data
   suggests otherwise.

9. **The runner is the same `grade_with_verifier.py`** — no script
   change needed, just rerun against saved narratives. The verifier
   layer change is enough.

10. **`tasks_with_any_contradicted_driver`** in summary JSON tracks
    a different field (driver_metabolite). Keep that summary line
    intact; add a parallel `tasks_with_any_contradicted_biological`
    if useful for the report.

---

## Time budget (1 day)

- 08:00 – 09:00 First-action checklist (categorise 30 claims) +
  clarifying Q
- 09:00 – 10:30 D1 code change + helper extraction
- 10:30 – 12:00 D2 unit tests + suite green
- 12:00 – 13:00 Lunch
- 13:00 – 13:30 D3 3-narrative smoke
- 13:30 – 14:30 D4 v7 verifier reruns (Sub-6B + 6A perfect + 6A
  real-id) sequential, ~25 min wall
- 14:30 – 16:00 D5 report writing
- 16:00 – 17:00 Buffer + commit + push

If you finish in < 6 hours, **stop**. Do not also do Direction 1
(disease DB) — that's a separate session.

---

## File manifest expected at end of session

**Modified:**
- `verifier/layers/biological_sub6.py` — added `_check_compound_pathway_membership_in_ramp` + dispatcher branch

**Possibly modified (only if needed):**
- `verifier/layers/_pathway_resolve.py` (new helper if extracting `_resolve_pathway`)
- `tests/test_verifier/test_biological_sub6.py` (additive only)

**New data:**
- `data/eval/sub6/sub6b_verdicts_v7_contra.jsonl`
- `data/eval/sub6/sub6a_perfect_id_verdicts_v7_contra.jsonl`
- `data/eval/sub6/sub6a_real_id_verdicts_v7_contra.jsonl`

**New results dirs:**
- `results/sub6b_verifier_v7_contra/`
- `results/sub6a_perfect_id_verifier_v7_contra/`
- `results/sub6a_real_id_verifier_v7_contra/`

**New report:**
- `reports/verifier/layer6c_contra_path_2026-XX-XX.md`

---

## When you finish

1. Push branch `feature/layer6c-contra-path`.
2. Reply with:
   - Sub-6B biological_claim contra count (the headline)
   - Same for Sub-6A perfect / real-id
   - Confirm no SUPPORTED / UNVERIFIABLE regressions (≤ 5% drift)
   - link to comparison report
3. **Do NOT touch Direction 1 (disease DB).** It's a separate
   session that may run in parallel and may rebase off your merged
   branch.

---

*Derived from session-state as of 2026-05-05 (commit ed6896b on
feature/verifier-kegg-hierarchy).*
