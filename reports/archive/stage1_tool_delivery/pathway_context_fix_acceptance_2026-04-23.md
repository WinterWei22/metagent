# Acceptance sign-off — `pathway_context` fix

**Fix commit:** `7d8b097 fix(pathway_context): per-pathway hit_count + self-echo + score honesty`
**Fix plan:** `reports/pathway_context_fix_plan_2026-04-23.md`
**Audit report:** `reports/integration_report_de_2026-04-23.md`
**Verified by:** D-E integration audit session (`main_de`), 2026-04-23
**Status:** ✅ **PASS** — all Tier-1 findings (P-1, P-5, P-6) resolved; documentation additions (P-2/3/4, D-1) applied; no regression against prior baseline.

---

## 1. What was checked

Each Tier-1 finding from the audit has a behavioural expectation. The
acceptance run executed a targeted probe against the live HMDB / RaMP
backends to observe the expected behaviour, then re-ran all existing
tests to catch regression.

### P-1 — `hit_count` is now per-pathway

Probe (real RaMP): `pathway_context("HMDB0000122", co_observed_ids=["HMDB0000243","HMDB0000161"])` returns 10 pathways with hit_counts `[1, 1, 2, 2, 1, 1, 1, 1, 1, 1]` — distinct values `{1, 2}`. Pre-fix shape would have been `[3, 3, …, 3]`. Control: with two unresolvable co-obs, all counts collapse to `1` (focal only).

Result: **PASS**.

### P-5 — `depth ≥ 2` no longer echoes focal

Probe (real RaMP): `pathway_context("HMDB0000122", neighbour_depth=2)` and same for `HMDB0000243`. Scanned every returned ID for any sub-string match of the focal's HMDB ID or KEGG ID — zero hits in either direction.

Result: **PASS**.

### P-6 — `cooccurrence_score` denominator is resolvable-only

Probe: `pathway_context("HMDB0000122", co_observed_ids=["HMDB0000243"] + 9 fake IDs)` returns `cooccurrence_score = 1.000`. Pre-fix would have been `0.100` (1/10). The `explain` string surfaces the drop count verbatim: `"9 of 10 co-observed IDs could not be resolved against RaMP and were excluded from the score."`

Monotonicity preserved: glucose + pyruvate (shared glycolysis) → 1.000, glucose + caffeine (disjoint) → 0.000.

Result: **PASS**.

### Documentation additions

`tools/pathway_context/tool_description.md` now carries a "Known limitations in v0" section that names the three deferred neighbour-field issues (P-2 direction collapse, P-3 non-resolvable prefixes, P-4 cofactor dilution) with explicit guidance that the orchestrator/verifier should not consume the `upstream_neighbours`/`downstream_neighbours` fields for ranking in v0.

`tools/metabolite_info/tool_description.md` now carries a "Zwitterion / protonation hazard" section documenting the L-carnitine `exact_mass=162.113` cation form (D-1) and recommending RDKit-based back-computation for precursor matching.

Result: **PASS** — both sections present, correct keywords confirmed, worked example (L-carnitine / 162.11) included.

### Regression sweep

| Suite | Result | Wall time |
|---|---|---|
| `tests/tool_tests/test_pathway_context.py` | 16 pass (13 original + 3 Track D regressions) | 0.2 s |
| `tests/tool_tests/test_metabolite_info.py` | 14 pass | 0.1 s |
| `tests/integration/test_facts_d.py` | 21 pass (17 original + 4 new P-1 pins — this commit) | 3.1 s |
| `tests/integration/test_verifier_e.py` | 17 pass | 21.9 s |
| `scripts/audit_de.py` | exit 0, three tools OK | 3.7 s |
| full `tests/integration/` (A/B/C + D/E) | 53 pass, 1 skip, 1 pre-existing L-carnitine failure | 6 min |

The pre-existing failure (`test_prefilter_returns_at_least_one_candidate[lcarnitine_pos]`) is the same D-1 fixture drift documented at audit time — not caused by this fix, not fixed by this fix. Remains queued for the fixture-refresh follow-up.

---

## 2. What this session added to lock in the fix

**One commit to `tests/integration/test_facts_d.py`** — adds a new
`TestPerPathwayHitCount` class (Mock + Real variants, 4 tests total)
that pins the post-fix `hit_count` semantics at integration level. This
is the § 4 "nice-to-have" from the fix plan, turned into code.

- `TestPerPathwayHitCountMock::test_hit_count_varies_per_pathway_in_mixed_overlap`
  — mini RaMP setup designed to produce `[1, 1, 2]`. Pre-fix would have
  returned `[2, 2, 2]`.
- `TestPerPathwayHitCountMock::test_hit_count_never_counts_unresolvable`
  — two fake HMDB IDs as co-obs, expect every pathway's `hit_count == 1`.
- `TestPerPathwayHitCountReal::test_hit_count_has_variance_under_mixed_co_obs`
  — against live RaMP, `glucose + [pyruvate, alanine]` must produce at
  least two distinct hit_count values. Pre-fix always returned one.
- `TestPerPathwayHitCountReal::test_hit_count_unchanged_when_co_obs_is_empty`
  — empty co-obs list: every pathway gets exactly `hit_count=1`
  (focal only).

If someone later "simplifies" `hit_count` back to a response-level
aggregate, these four tests catch it immediately. The mock variant also
provides a minimal reproducer that does not require the RaMP dump.

---

## 3. Tier-2 status (untouched by this round of work)

Per the original fix plan and as confirmed here:

| Finding | v0 action taken | v1 owner |
|---|---|---|
| P-2 — direction collapse | Documented as known limitation | Track D — neighbour field redesign (Option C recommended) |
| P-3 — non-HMDB/non-KEGG prefixes leak | Documented | Same redesign |
| P-4 — cofactors not filtered | Documented | Same redesign |
| D-2 — fixture drift (α-glucose, L-carnitine cation) | — | Fixture refresh session, bundled with the pre-existing `test_prefilter_returns_at_least_one_candidate[lcarnitine_pos]` failure |

All four items remain tracked in `reports/pathway_context_fix_plan_2026-04-23.md` §§ 3, 5. This acceptance sign-off does not discharge them.

---

## 4. Final state at sign-off

```
7d8b097   fix(pathway_context): per-pathway hit_count + self-echo + score honesty   ← Track D fix
a8ed9c7   docs(tracks-D-E): delivery hand-off + Track D fix plan                    ← audit hand-off
63444f4   test(tracks-D-E): integration harness + smoke diagnostic
97d8bc1   audit(tracks-D-E): integration report for fact backends + verifier
```

This session appends one commit on top of `7d8b097`:

- `tests/integration/test_facts_d.py` — `TestPerPathwayHitCount{Mock,Real}` class, 4 new tests.
- `reports/pathway_context_fix_acceptance_2026-04-23.md` — this document.

No tool source, schema, doc, or existing test modified.

**Tier-1 fix accepted. Tier-2 tracked. Done for v0.**
