# W12 C7 namespace fix — sprint status

**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v2` @ `e74af22` (post W11 UV diagnosis)
**Started:** 2026-05-22
**Stage:** onboarding(no code touched)

---

## §0 Confirmation block — sprint understanding + blocker

### What I understood from the user message

| Item | Value |
|---|---|
| Goal | C7 namespace_form fix(W11 优先级 #1) |
| Method | Layer 6a fuzzy match,reuse W9 `concord/analyze/pathway_match.py` token-Jaccard 0.5 |
| Target file | `verifier/layers/set_enrichment.py` (Layer 6a),⚠️ verifier-modify policy |
| Architecture goal | Eventually `concord/verifier_extension/` pattern per 2026-05-22 user message |
| Expected UV impact | 52% → 31-34%(−18 to −21 pp) |
| Pathway accuracy gate | not drop > 3 pp |
| Budget | 5-7 day wall + ~$10 API(Path X 重跑 1 次) |
| Policy | Tag `metagent-v2-base-b1` / B1 paper 数据 immutable;commit body 含 `[verifier-modify-warning]` + justification + B1 test 不退步证据 |

### ⚠ Blocker — sprint scope vs C7 actual content mismatch

**Recon finding (W11 data,no recompute):** C7 namespace_form 的 226 个 claim,按
`claim_type` 分布是:

| claim_type | n | % of C7 | verify_sub6 dispatch goes to | layer file |
|---|---:|---:|---|---|
| **FACTUAL** | 125 | **55.3%** | fall-through UV(line 664-685 in `verifier/agent.py`) | (no sub6 layer) |
| **GROUNDED** | 56 | **24.8%** | fall-through UV(same) | (no sub6 layer) |
| **BIOLOGICAL** | 37 | 16.4% | `verify_biological_sub6` | `verifier/layers/biological_sub6.py` |
| DRIVER_METABOLITE | 3 | 1.3% | `verify_driver_metabolite` | `verifier/layers/driver_metabolite.py` |
| **SET_ENRICHMENT** | **2** | **0.9%** | `verify_set_enrichment` | `verifier/layers/set_enrichment.py` ← **sprint target** |
| CONSISTENCY | 1 | 0.4% | fall-through UV | (no sub6 layer) |
| PATHWAY_RELATIONSHIP | 1 | 0.4% | `verify_pathway_relationship` | `verifier/layers/pathway_relationship.py` |
| OTHER | 1 | 0.4% | fall-through UV | (no sub6 layer) |
| **TOTAL** | **226** | **100%** | | |

**Implication:** changing only `verifier/layers/set_enrichment.py` (Layer 6a) affects
**2 / 226 = 0.9 % of C7**,which is **2 / 1102 = 0.18 % of total UV**. The
**−18 to −21 pp UV impact target requires reaching the 181 FACTUAL/GROUNDED**
claims (80.1 % of C7) that today fall through to the line-664 UV bucket.

C7 typical samples (random 10, `random.seed(7)`):

```
[FACTUAL]            Dehydroepiandrosterone maps to KEGG compound C01227
[BIOLOGICAL]         Pyrocatechol appears in Disulfiram action
[FACTUAL]            17β-hydroxy-5α-androstan-3-one has CHEBI ID CHEBI:16330
[FACTUAL]            L-tyrosine has KEGG ID C00082
[FACTUAL]            L-methionine corresponds to KEGG:C00073
[FACTUAL]            L-Threonine has HMDB ID C00188  ← C-prefix is KEGG, not HMDB
[FACTUAL]            Xanthine has KEGG ID C00385
[BIOLOGICAL]         Disorders of transmembrane transporters implicates cholesterol
[FACTUAL]            Pyrocatechol has KEGG ID C15571
[GROUNDED]           MUMM:prostaglandin_formation_from_arachidonate is a third mummichog hit
```

80 % of C7 are **"metabolite has external ID"** claims (metabolite-ID grounding),
not pathway-name claims. They fall through `_verify_per_claim_sub6` because Sub-6's
`SubsixSourceReport` does not carry `candidates[*].metabolite_info.cross_refs`
(which is the spectrum-centric `IdentificationReport` shape that Layer B / Layer A
require). The fall-through evidence string is:

```
Sub-6 verifier does not support claim_type 'factual': existing layer requires
IdentificationReport (spectrum-centric), but Sub-6 supplies SubsixSourceReport.
Treated as declared limitation.
```

---

## §1 — Recon notes (what's where)

### Layer 6a current behaviour (`verifier/layers/set_enrichment.py`)

- Verdict policy: top-3 → SUPPORTED, top-10 → UNSUPPORTED, beyond → CONTRADICTED,
  no phrase/ID liftable → **UNVERIFIABLE_V0** (line 168-177).
- Matching cascade:
  1. ID match (exact equal on `pathway_id` / `pathway_external_id`)
  2. Forward fuzzy (claim phrase ⊂ canonical OR canonical ⊂ claim — substring only)
  3. Reverse fuzzy (canonical name verbatim in `claim.claim_text`)
- **Does not use token-Jaccard**(substring only). Substring match misses
  "MUMM:galactose_metabolism" vs "Galactose metabolism" because `:` and `_`
  break the substring sweep.

### W9 token-Jaccard helper (`concord/analyze/pathway_match.py`)

- `pathway_name_overlap(gt, candidate, threshold=0.5)` — Jaccard of content tokens
  (post stopword strip + 4-char min).
- `best_matching_rank(gt, top_pathway_names, threshold=0.5)` — first rank with
  Jaccard ≥ 0.5.
- Stopwords drop "metabolism / pathway / synthesis / biosynthesis / etc." so
  "Galactose metabolism" tokenizes to `{galactose}`, "MUMM:galactose_metabolism"
  tokenizes to `{galactose, mumm}` (after `_` split via the regex `[a-z][a-z0-9'-]*`
  needing 4+ chars — actually "mumm" stays because it's 4 chars).

### `_verify_per_claim_sub6` dispatch (`verifier/agent.py:605-686`)

- 5 `claim_type` get layer dispatch (SET_ENRICHMENT / DRIVER_METABOLITE /
  PATHWAY_RELATIONSHIP / BIOLOGICAL / PEAK_MECHANISTIC).
- All others fall through to `UNVERIFIABLE_V0` with the fall-through evidence
  string above.

### Existing B1 tests for `set_enrichment.py`

- `tests/test_verifier/test_claim_classifier.py:75` — `test_set_enrichment_p1_rule_classify`
- `tests/test_verifier/test_claim_classifier.py:113-141` — routing precedence tests
- `tests/test_verifier/test_sub6_dispatcher_integration.py:186, 219` — sub6 dispatch
  + pure-set_enrichment narrative integration

These are the **B1 test surface** the verifier-modify policy ("不退步") gates on.

### Tags (immutable per 2026-05-22 user message)

- `metagent-v2-base-b1` → `ed6243b`
- `metagent-v2-base-investigation` → `3ffe621`

---

## §2 — Open Questions for user (blocking sprint start)

Per user death-rule "完成前不要动代码", I am stopping at onboarding and
asking for a scope decision before writing any RED test or production change.

### OQ1 — Sprint scope clarification

The sprint title says "Layer 6a fuzzy match", but Layer 6a (`set_enrichment.py`)
only sees **0.9 %** of C7 (the 2 SET_ENRICHMENT claims). The −18 to −21 pp UV
target requires reaching the **80.1 %** FACTUAL/GROUNDED metabolite-ID claims,
which currently fall through `verify_sub6` because Sub-6 has no
`IdentificationReport`-shaped candidate pool.

**Three plausible interpretations** of the user intent — please pick:

1. **A — Strict literal**: only modify `verifier/layers/set_enrichment.py`.
   Add token-Jaccard to its existing match cascade. Expected impact: ≤ 2 of
   the 2 SET_ENRICHMENT-typed UV claims flip. **−0.2 pp UV at best**.
   Sprint is a precision-improvement on a tiny C7 sub-bucket; the −18 pp
   goal is **not reachable** under this scope.

2. **B — Implied scope: add new sub6 metabolite-ID layer**:
   Add a new layer file (e.g. `verifier/layers/metabolite_id_sub6.py`)
   that handles the fall-through FACTUAL/GROUNDED claims by looking up
   metabolite IDs against RaMP DB analyte tables. `_verify_per_claim_sub6`
   gets a new branch routing FACTUAL/GROUNDED to this layer. Set_enrichment.py
   may stay untouched, or get the Jaccard upgrade as a small adjunct.
   **Reaches ~80 % of C7 (~181 claims)**. −15 to −19 pp UV target plausible.

3. **C — Strict architecture follow-up**: per 2026-05-22 user message,
   add `concord/verifier_extension/` directory + namespace_adapter.py +
   shape_router.py + wire into `ConcordReactRunner.verify_with_b1()` as a
   post-verify step. Existing `verifier/layers/*.py` untouched. Same UV
   coverage as B but routed through the extension layer instead of
   `verify_sub6`. **Matches the 2026-05-22 architecture sketch verbatim**.

### OQ2 — `B1 test 不退步` gate definition

Spec says "commit body 必须含 [verifier-modify-warning] + justification +
B1 test 不退步证据". I interpret this as:

- Run the test set in `tests/test_verifier/` + `tests/test_*.py` (B1 unit
  suite at HEAD `metagent-v2-base-b1` = `ed6243b`)
- Confirm pass/fail count identical pre- and post-change
- Quote the numbers in commit body

Is that the right interpretation, or do you want a narrower gate
(e.g. only `test_sub6_dispatcher_integration.py` + `test_claim_classifier.py`)?

### OQ3 — Path X rerun cost: $10 budget vs W10 D4 实际 $10.10

W10 D4 cost $10.10 at MiniMax-M2.7 with the same K=10/63-task/2-iter config.
$10 budget gives essentially 0 headroom. Am I OK with $10 reading as ≈ $10-12
ceiling (W10 D4 +20 %), or strict $10?

---

## §3 — Proposed next step (gated on user OQ1 decision)

Whichever of A/B/C you pick, the next sub-step is:

1. (only if B/C) define the new layer / extension's exact entry point and
   what input contract it needs (`SubsixSourceReport` only? or also
   `ramp_conn` + `driver_lookup`?)
2. Write the RED test file (≥ 6 cases covering: KEGG ID lookup hit /
   miss, CHEBI ID hit / miss, HMDB-prefix-as-KEGG corner, MUMM:
   pathway-name handling, namespace-aware fuzzy match)
3. Verify RED — confirm tests fail with the right reasons
4. Commit RED
5. Implement GREEN
6. Verify GREEN
7. B1-test-suite regression check
8. Commit GREEN with `[verifier-modify-warning]` body
9. Wire into `_verify_per_claim_sub6` or `ConcordReactRunner` (per A/B/C choice)
10. Wire-commit + integration tests
11. Path X rerun(D4 driver clone with new trace prefix)
12. Diagnostic: re-run W11 UV classifier on new data,measure C7 shift
13. Report commit

---

## §4 — Stop conditions for this sprint

Carry forward W10/W11 sprint stop conditions plus:

| # | Condition | Action |
|---|---|---|
| 1 | UV count drops > 5 pp on its own (without pathway-acc gate trigger) | proceed |
| 2 | Pathway accuracy drops > 3 pp post-rerun | **halt, ping user**, do not commit rerun data |
| 3 | B1 unit test pass count drops > 0 | **halt, ping user**, revert |
| 4 | API cost > $12 mid-run | **ping user** before continuing |
| 5 | Wall total > 7 day | scope re-evaluation |
| 6 | iter-2 degradation rate climbs (W10 D4 baseline 17.7 %) | **ping user**, may indicate new feedback regression |
| 7 | Any code change without RED commit preceding | strict-TDD slip, halt + revert |

---

## §5 — What is NOT in this sprint

(Forbidden per user death rules)

- ❌ Paper narrative / Discussion / Methods / Results / footnote text
- ❌ Modifying `verifier/grammar.py` 4-shape enum
- ❌ Modifying `B1` source other than the sanctioned `verifier/layers/set_enrichment.py`
  (and only if user picks A or B; under C, no `verifier/` change at all)
- ❌ Exposing V3 algorithmic tools through ConcordMet
- ❌ Pushing to origin
- ❌ Parallel work on a second C-category (audit trail discipline)
- ❌ "$0 local" framing — MiniMax is remote API, cost via `logs/llm_calls.jsonl`

---

## §6 — Pending decisions log (will be filled as user replies)

| # | Question | User decision | Time | Notes |
|---|---|---|---|---|
| OQ1 | A / B / C | — | — | — |
| OQ2 | B1-test-suite gate scope | — | — | — |
| OQ3 | $10 hard ceiling vs $10-12 soft | — | — | — |
