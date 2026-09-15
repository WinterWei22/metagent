# Claim Grammar v2 — Phase B1 D0 draft

**Status:** Draft. Not yet committed. Awaiting review before D1 prompt rewrite.
**Branch:** `feature/agent-phase-b1` (cut from `MetAgent-v1-0514`).
**Date:** 2026-05-14.
**Companion code:** `verifier/grammar.py`.

---

## 1. Why 4 classes — and why Sub-6A does NOT get a 5th

The v1 verifier accepts 9 `ClaimType` values (`verifier/schemas.py:46`).
Phase A3 D3 shows 63–67% of Sub-6 claims come back `UNVERIFIABLE_V0`
across the single / react / fb_nolit / +literature variants
(see `reports/agent/diagnosis_unverifiable_and_correlation.md` §2.1).
The root cause is structural, not LLM-quality:

- `verifier/agent.py:494-518` routes any non-{SET_ENRICHMENT,
  DRIVER_METABOLITE, PATHWAY_RELATIONSHIP, BIOLOGICAL, PEAK_MECHANISTIC}
  claim through `verify_sub6` and immediately returns
  `UNVERIFIABLE_V0`.
- `reports/agent/prompt_audit_for_rewrite.md` §4 confirms Sub-6A does NOT
  inject IdReport into the narrative prompt today, so a 5th
  `GROUNDED`-style class for Sub-6A has no live verifier route.

Opening a 5th class without first changing the dispatcher merely
relabels the dead path. Sub-6A grounded grammar is therefore deferred
until the dispatcher learns to consume IdReport — outside Phase B1.

**Decision:** 4 classes, shared by Sub-6A and Sub-6B.

---

## 2. The 4 classes

| Grammar | Sentence shape | Required fields | Verifier layer | v1 `ClaimType` it replaces |
|---|---|---|---|---|
| `PATHWAY_MEMBERSHIP` | `<metabolite> is a member of <pathway>` | `subject`, `pathway_name` | `biological_sub6.py` (6c) | `BIOLOGICAL / pathway_membership` |
| `METABOLITE_PATHWAY_LINK` | `<metabolite> participates in <pathway> via <enzyme/reaction>` | `subject`, `pathway_name`, `enzyme_or_reaction` | `biological_sub6.py` (6c) strict | `BIOLOGICAL` (bare) — now requires endpoint |
| `PATHWAY_ENRICHMENT` | `<term> is enriched given metabolite set {...}` | `term_id`, `term_name`, `term_type` (+ optional `fdr` / `p_value` / `metabolite_set`) | `set_enrichment.py` (6a), dispatched by `term_type` | `SET_ENRICHMENT` (was KEGG-only) |
| `DRIVER_METABOLITE` | `<metabolite> drives <pathway> based on <signal evidence>` | `subject`, `pathway_name`, `signal_compound_ids` (subset of `ground_truth_signal_compounds`) | `driver_metabolite.py` (6b) | `DRIVER_METABOLITE` |

**`term_type` on `PATHWAY_ENRICHMENT`** is the only schema field that
goes beyond a 1:1 rename of v1 concepts. RaMP enrichment can return
disease terms, Reactome pathways, and GO terms alongside KEGG pathways
(see §5 — the `17-Beta Hydroxysteroid Dehydrogenase III Deficiency`
example). v1's layer 6a only verified KEGG pathway names, which is why
real disease enrichment hits ended up as `grounded_claim / UNV`. v2
makes the taxonomy explicit at extract time so the D3 layer 6a fix can
dispatch by `term_type` without another grammar bump. Accepted values:
`"pathway" | "disease" | "reactome" | "go"`.

Categories from v1 that **no longer appear** in v2 grammar:
- `GROUNDED` (Sub-6 dispatch has no route — see §1)
- `FACTUAL` (tool-roundtrip — dropped by D2)
- `CONSISTENCY` (verifier-internal — not an LLM output)
- `LITERATURE` (Sub-6 dispatch has no route)
- `PEAK_MECHANISTIC` (Sub-6B has no spectrum; Sub-6A goes via Phase 6.3 path, outside B1 grammar)
- `PATHWAY_RELATIONSHIP` (upstream/downstream — see §3 DROP rules)

The `pathway_relationship` removal is deliberate: of 116 v1 directional
claims in `v4_a3_d3_no_lit/feedback` (63 tasks), 100% are
`UNVERIFIABLE_V0` because RaMP-DB has no pathway-hierarchy table
(see `verifier/schemas.py:93-99` docstring) — these are LLM-invented
direction labels with no ground-truth path. v2 drops them outright.

---

## 3. DROP rules — `dropped_by_grammar` metric

D2 extractor drops anything outside the 4 classes. Counted separately
from `supported / unsupported / contradicted / unverifiable_v0`. Seven
identifiable surface patterns; **all seven are also banned at the
narrative-prompt level (D1)** so D2 is a tripwire, not the primary line
of defence.

Counts come from `v4_a3_d3_no_lit/feedback/*/verdict.json` — 63 tasks,
1790 total UNV claims. The initial 6-task scan (172 UNV) referenced in
`reports/agent/diagnosis_unverifiable_and_correlation.md` §2.2 was
expanded to the full 63 during D0 sampling. Buckets marked `~` are
semantic / hand-tagged categories with no clean regex (see footnote).

| DROP subtype | Heuristic / banned tokens | Sampled v1 count (1790 UNV in 63 tasks) | Banned in `grammar.py` |
|---|---|---:|---|
| **tool roundtrip** | `\bC\d{5}\b` / `\bHMDB\d{7}\b` / `\bmap\d{5}\b` / `\b[A-Z]{14}-[A-Z]{10}-[A-Z]\b` (InChIKey) / `\bC\d+H\d+...\b` (formula) / `has KEGG\|HMDB\|...` phrasing | 318 (18%) | `BANNED_TOOL_ROUNDTRIP_PATTERNS` (regex) |
| **speculation hedge** | `may / might / suggest / potentially / possibly / likely / consistent with / appears to / seems to / could be / is thought to` | 131 (7%) | `BANNED_HEDGES` |
| **directional chain** | `upstream / downstream / two-hop / three-hop / spans N steps / precursor of / positioned at branch point / leads to / routes lead` (NOTE: `drives / driving` deliberately NOT banned — canonical verb for `DRIVER_METABOLITE`) | 116 (6%) | `BANNED_DIRECTIONAL` |
| **abstract textbook** | `canonical / cascade / arms radiating / axis / hallmark of / crosstalk / interplay / signaling cascade / branch producing / metabolic-immune` | 47 (3%) | `BANNED_ABSTRACT` |
| **ungrounded set** | `driver cluster / eicosanoid cluster / metabolite cluster` | 14 (1%) | `BANNED_ABSTRACT` |
| **meta / limitations** | `limited to / should be validated / lack of evidence / omitted / strength of claims / future work / caveat / is limited / claims regarding / does not preclude` | ~50 (3%)¹ | `BANNED_META` |
| **observation only** | single-metabolite up/down with no pathway endpoint ("X is elevated", "X accumulates", "X and Y have coordinated dysregulation") | ~30 (2%)¹ | structural (no field set besides `subject` — fails required-field check) |

¹ Approximate (`~`) where the category is semantic rather than syntactic
— individual sentences were hand-tagged during the D0 sampling pass; an
exact regex sweep would either over- or under-count and was deferred to
D2 implementation.

**Why ban Meta at the prompt and not just at the extractor.** Meta
sentences also leak into the human-facing `narrative_text` field — a
reviewer reading "the strength of claims is limited" or "claims have
been omitted for lack of positive evidence" loses trust in the result
before reading the verdict table. Source-side suppression is cheaper
than two-stage filtering.

**Observation handling (fallback chosen).** A "X is elevated, therefore
X drives pathway Y" compound sentence has a valid `DRIVER_METABOLITE`
half. Two options were considered for D2:

- **A — composite-sentence split:** extractor recognises observation +
  conclusion, drops the first, keeps the second. Implementation cost
  non-trivial (LLM step or substantial regex).
- **B — whole-sentence drop, lean on D1:** D1 narrative prompt
  explicitly tells the LLM to write driver conclusions directly,
  without observation preamble. D2 drops any sentence with no pathway
  endpoint regardless of compound structure.

**Decision: B.** Simpler, less brittle, fewer LLM calls. If B costs
>2pp on supported in D6 ablation, revisit with A. This is recorded so
future-us doesn't relitigate.

**Expected after D1 narrative-prompt rewrite:** the surface-DROP buckets
shrink (LLM stops generating them), and the residual ~70% in the
"other" bucket (unscanned by my heuristic but still UNV today)
collapses into the 4 grammar classes. Acceptance gate from the track
doc requires `dropped_by_grammar < 30%` post-D2 — anything above means
D1 prompt is not actually constraining the LLM.

---

## 4. Per-class examples — 3 positive (synthetic) + 3 negative (real `v4_a3_d3_no_lit` refs)

Real refs all from `data/eval/sub6/v4_a3_d3_no_lit/feedback/<task>/verdict.json`
unless otherwise noted. Format: `<task>#<claim_id> [<v1 claim_type>/<verdict>]`.

### 4.1 `PATHWAY_MEMBERSHIP`

**Positive (target shape — what the new prompt should produce):**
1. "L-Methionine is a member of Cysteine and methionine metabolism"
2. "Arachidonic acid is a member of Arachidonic acid metabolism (KEGG hsa00590)"
3. "Galactose is a member of Galactose metabolism"

**Negative — real v1 claims that should DROP:**
1. `compound_only_enrich_mammalian_RAMP_P_000000016_seed4 # v2:c026` `[biological_claim/unverifiable_v0]` — *"Cysteine depletion is a hallmark of compromised antioxidant defense"* → DROP: abstract textbook (`hallmark`).
2. `compound_only_enrich_mammalian_lm_pathway_WP167_seed6 # v2:c031` `[biological_claim/unverifiable_v0]` — *"HETEs are potent lipid mediators of inflammation"* → DROP: abstract textbook — single-metabolite generality with no `pathway_name`.
3. `compound_only_enrich_mammalian_lm_pathway_WP167_seed0 # v2:c018` `[biological_claim/unverifiable_v0]` (path `v4_a3_d3_with_lit/react/.../verdict.json`) — *"The six lipids are canonical intermediates of the three major enzymatic arms radiating from arachidonic acid"* → DROP: abstract textbook (`canonical / arms`).

### 4.2 `METABOLITE_PATHWAY_LINK`

**Positive:**
1. "L-Methionine participates in the methionine cycle via methionine adenosyltransferase"
2. "Arachidonic acid participates in Eicosanoid synthesis via cyclooxygenase 2 (COX-2)"
3. "Galactose-1-phosphate participates in Galactose metabolism via galactose-1-phosphate uridylyltransferase (GALT)"

**Negative — real v1:**
1. `compound_only_enrich_mammalian_RAMP_P_000000016_seed6 # v2:c018` `[biological_claim/unverifiable_v0]` — *"Glycine is a demethylated product of SAM-dependent methyltransfer"* → DROP: no `pathway_name`; mechanism description without pathway endpoint.
2. `compound_only_enrich_mammalian_lm_pathway_WP167_seed8 # v2:c021` `[biological_claim/unverifiable_v0]` — *"L-cysteine and L-cystathionine co-occurrence with eicosanoid metabolites suggests involvement of sulfur-handling biochemistry in the treatment-associated metabolic shift"* → DROP: speculation hedge (`suggests`) + collective subject + no enzyme.
3. `compound_only_enrich_mammalian_RAMP_P_000000141_seed0 # v2:c055` `[biological_claim/unverifiable_v0]` — *"Quinolinic acid is a branch-point intermediate toward NAD⁺"* → DROP: directional (`toward`) + abstract (`branch-point intermediate`).

### 4.3 `PATHWAY_ENRICHMENT`

**Positive:**
1. "Cysteine and methionine metabolism is enriched given metabolites {L-Methionine, L-Cysteine, SAM} (FDR < 0.01)"
2. "17-Beta Hydroxysteroid Dehydrogenase III Deficiency is the top-ranked enrichment (FDR = 0.0)"
3. "Arachidonic acid metabolism is enriched (hypergeometric p < 0.001) given the differential metabolite set"

**Negative — real v1:**
1. `compound_only_enrich_mammalian_RAMP_P_000050021_seed1 # v2:c030` `[biological_claim/unverifiable_v0]` — *"The treatment simultaneously perturbs Phase I and Phase II reactions"* → DROP: collective subject without a single concrete `term_id`. Correct v2 expression is **two separate `PATHWAY_ENRICHMENT` claims**, one for the Phase I term and one for Phase II (cf. §5 multi-pathway decision).
2. `compound_only_enrich_mammalian_RAMP_P_000000016_seed7 # v2:c033` `[set_enrichment/unverifiable_v0]` — *"Perturbation suggests broad disruption of one-carbon and sulfur amino-acid flux"* → DROP: speculation hedge (`suggests`).
3. `compound_only_enrich_mammalian_lm_pathway_WP167_seed2 # v2:c012` `[set_enrichment/unverifiable_v0]` — *"15-HETE is enriched in the eicosanoid cluster"* → DROP: ungrounded set name (`eicosanoid cluster` is not a RaMP pathway).

### 4.4 `DRIVER_METABOLITE`

**Positive:**
1. "L-Methionine drives Cysteine and methionine metabolism based on signal_compounds={L-Methionine, L-Cystine}"
2. "Arachidonic acid drives Arachidonic acid metabolism based on signal_compounds={Arachidonic acid, 15-HETE}"
3. "Galactose drives Galactose metabolism based on signal_compounds={Galactose, Galactitol}"

**Negative — real v1:**
1. `compound_only_enrich_mammalian_lm_pathway_WP167_seed0 # v2:c031` `[driver_metabolite/unverifiable_v0]` (path `v4_a3_d3_with_lit/react/...`) — *"Arachidonic acid is the central upstream node driving the observed elevation or depletion of its downstream eicosanoid products"* → DROP: speculation (`elevation or depletion`) + directional (`upstream / downstream`).
2. `compound_only_enrich_mammalian_lm_pathway_WP167_seed5 # v2:c030` `[biological_claim/unverifiable_v0]` — *"Eicosanoids drive vasoconstriction"* → DROP: collective subject + no pathway endpoint (`vasoconstriction` is a phenotype, not a RaMP pathway) + no `signal_evidence`.
3. `compound_only_enrich_mammalian_lm_pathway_WP167_seed9 # v2:c026` `[pathway_relationship/unverifiable_v0]` — *"The coordinated elevation is downstream of arachidonic acid pool expansion"* → DROP: directional + abstract subject + no `signal_evidence`.

---

## 5. Red-line check during sampling

Per review instruction: if a real UNV claim is *legitimate and verifiable* but not covered by the 4 classes, STOP and flag — that would mean grammar design is missing a class. **Result of the scan:** none found.

Two near-miss observations worth flagging (not gaps in grammar, but adjacent issues):

- **`compound_only_enrich_mammalian_RAMP_P_000000421_seed8 # v2:c001` `[grounded_claim/unverifiable_v0]` — "17-Beta Hydroxysteroid Dehydrogenase III Deficiency has FDR = 0.0"**: this is a legitimate `PATHWAY_ENRICHMENT` quote from the RaMP result, but v1 classified it as `grounded_claim` and routed to dead-path. Grammar v2 catches it correctly as `PATHWAY_ENRICHMENT`; the residual issue is a Stage-2 classifier bug that D3 fixes.
- **Multi-pathway co-perturbation claims** ("the treatment perturbs Phase I and Phase II reactions"): no v2 class fits cleanly because the subject is two pathways, not one. Decision: drop, since the underlying semantics is "two enrichment results in parallel" — that should be expressed as **two** `PATHWAY_ENRICHMENT` claims under v2, not one collective one.

No grammar gap.

---

## 6. Downstream impact map

| Phase B1 deliverable | What changes because of this grammar |
|---|---|
| D1 narrative prompt | Hard schema: output is a JSON list, each item has `grammar` field matching one of the 4 enum values plus the corresponding required fields. Banned-phrase list comes from `verifier/grammar.py:BANNED_*`. |
| D2 extractor | LLM step replaceable by JSON schema validation (one call → zero calls). Unmatched objects counted under `dropped_by_grammar`. |
| D3 classifier | 9-class collapse to 4-class. Existing 9-class enum stays as `LegacyClaimType` for backward-readability of historical verdicts. |
| D4 dispatcher | The "anything-else → UNVERIFIABLE_V0" fallback in `verifier/agent.py:494-518` should no longer fire if D1/D2 hold. If it does, that is a D1 prompt-leak regression, not a dispatch bug — surface as test failure. |
| D4 feedback hint | Remove `UNVERIFIABLE_V0` from `_NEUTRAL_VERDICTS`. New hint template tells the LLM: "rewrite as one of {4 classes} or omit". |

---

## 7. Decisions resolved during D0 review

1. **5th GROUNDED class for Sub-6A?** No — dispatcher has no route (§1).
2. **`PATHWAY_ENRICHMENT.term_type`?** Required field at D0 so D3 layer 6a fix doesn't need a schema bump (§2).
3. **`signal_evidence` format on `DRIVER_METABOLITE`?** Structured `signal_compound_ids: list[str]`. Free-text was rejected — JSON output costs the LLM nothing extra and gives D4 feedback hint a precise handle.
4. **Compound observation+conclusion sentences?** Whole-sentence drop, lean on D1 to suppress observation preamble (§3 Observation handling).
5. **Multi-pathway "perturbs Phase I and Phase II" claims?** Drop. The right v2 expression is two separate `PATHWAY_ENRICHMENT` claims; collective forms cost more in extraction complexity than they buy.
6. **`enzyme_or_reaction` cross-checked against KEGG enzyme table?** No — non-empty + named-in-narrative only for B1. KEGG enzyme verifier is a new tool, ruled out by the track doc.

## 8. Open questions still requiring reviewer input

None at the moment — pending review of the draft will surface any remaining gaps.
