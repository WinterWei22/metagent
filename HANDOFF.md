# MetAgent v2 — Project Handoff

**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v3-benchmark` (renamed from `metagent-v2` in late June 2026 — see §5A)
**Last sprint:** Phase A publication-grade benchmark construction, in progress (HEAD `9a90d82`, 2026-07-08)
**Handoff written:** 2026-05-28. **Addendum §5A written 2026-07-08** covering the 122
commits between W15 (`de6cf5a`) and the current HEAD — the original §1-§14 below
still describe the W8→W15 state accurately as *history*, but §5A supersedes some of
their forward-looking conclusions (most importantly §4.3's iter-2 story — read §5A.1
before relying on §4.3 for current behavior).

This document is the single-source onboarding artifact for a new
maintainer. Read it end-to-end before opening a PR or starting a new
sprint. If you only have time for one file, read this — but read
**§5A first**, since it is the part that is not yet reflected anywhere
else outside `docs/PROJECT_MAP.md`. `CLAUDE.md` is a shorter sibling
oriented at automated agents; `HANDOFF.md` (this file) is the
human-oriented version with full decision history.

---

## §1 — What MetAgent is (one paragraph)

MetAgent reframes MS/MS-based metabolite identification from "output
one molecule with a score" to "output an auditable report". An LLM
orchestrator plans tool calls; each tool is a narrow-waist function
with a Pydantic contract; a Verifier agent closes the loop by
forward-predicting spectra from candidates, validating every factual
claim (PMIDs, database IDs, peak assignments, pathway memberships)
against external sources, and producing structured per-claim
verdicts. The output is a structured report where every statement
traces back to evidence.

The system runs in **two stages**:

- **Stage 1 — Per-spectrum identification.** Input: one MS/MS spectrum
  + ionization metadata + optional natural-language context. Output:
  `IdentificationReport` with ranked candidates, peak-level
  attribution, pathway / literature context, and a per-claim
  verification trace. Implemented as a 7-tool stack
  (`tools/spectrum_ops/`, `tools/library_search/`, `tools/molecule_gen/`,
  `tools/metabolite_info/`, `tools/pathway_context/`,
  `tools/spectrum_predict/`, `tools/literature/`) plus an LLM
  orchestrator (`orchestrator/`). **Frozen at `metagent-v2-base-b1`
  tag `ed6243b`.**

- **Stage 2 — Pathway-level narrative from enrichment results.** Input:
  a list of differentially-abundant metabolites (the output of a
  typical metabolomics pipeline). Output: pathway-grounded narrative
  + 4-shape structured claims (`pathway_membership` /
  `metabolite_pathway_link` / `pathway_enrichment` /
  `driver_metabolite`), all run through the Stage-1 Verifier with
  Sub-6-friendly layer dispatch. Implemented as a 5-paradigm
  pathway-analysis tool dispatcher (`concord/`) + ReAct runner +
  closed-loop feedback. **Active workstream — sprint cycle W8 → W15
  has been the focus of the last 6 weeks.**

The two stages share `verifier/` and `schemas/`. Stage 2 imports from
Stage 1; Stage 1 does **not** import from Stage 2.

---

## §2 — Design principles (architecture decisions and rejected alternatives)

Read `docs/ARCHITECTURE.md` first. This section adds the *why-not*
context the architecture doc skips.

### §2.1 Schemas are law

Every tool has a Pydantic input and output model. Schemas live in
`schemas/`. Tools import from `schemas/`; schemas never import from
tools. Schema changes are breaking and require an explicit decision.

**Why not free-form JSON or duck-typed dicts:** LLMs reliably emit
structured JSON but only when the schema is exhaustively documented.
Pydantic gives us both the schema-as-contract and a free Python-side
validator. We tried duck-typed dicts in an early prototype; the LLM
silently dropped fields the moment we extended the schema, and tests
could not catch the drift.

### §2.2 Tools are narrow

One tool = one user-meaningful intent. Not one DB query.
`fetch_metabolite_info(hmdb_id)` returns *everything* about one
metabolite in one call. We do not have `get_name`, `get_formula`,
`get_inchi` as separate tools — the LLM cannot reason about the
boundary between "what each query returns" and would burn tool-call
budget rediscovering it.

**Why not a single "do_chemistry(query)" mega-tool:** the LLM cannot
verify free-form text outputs; structured outputs require structured
intents.

### §2.3 Tools are independent

Tools do **not** import from other tools' packages. Composition
happens only in `orchestrator/`. Shared code goes in `schemas/` or
`common/`, never tool-to-tool.

**Why:** independent deployment + independent testing. A new
contributor working on `library_search/` should not break
`molecule_gen/`. We have hit this exactly once (B1 phase) and the
cost was a 2-day cleanup.

### §2.4 Every claim is verifiable (Verifier as first-class agent)

PMIDs must resolve in Europe PMC. KEGG/HMDB/ChEBI IDs must resolve in
their respective databases. Peak assignments must cite a predicted
fragment. The Verifier enforces this before the report reaches the
user.

**Why a separate Verifier agent and not orchestrator-internal checks:**
hallucination detection is "after-the-fact audit" with a different
cognitive task than "generate candidates". The Verifier uses a
different prompt, can use a different model, and has its own LLM-call
budget. The two roles being coupled (e.g. asking the orchestrator
LLM to self-verify) consistently rationalised away its own errors.

### §2.5 The 4-shape grammar (B1 phase, claim_grammar_v2)

Every claim must conform to one of:
- `pathway_membership`
- `metabolite_pathway_link`
- `pathway_enrichment`
- `driver_metabolite`

Anything else is marked `UNVERIFIABLE_V0` and surfaced as a
"verifier-side gap" signal. See `docs/claim_grammar_v2.md` and
`verifier/grammar.py`.

**Why so narrow:** the Verifier is built around four routable claim
types; expanding the grammar without expanding the verifier layers
just shifts hallucinations into broader buckets that look "verified".
W11 → W15 have spent significant effort measuring what falls outside
these 4 shapes; W16+ has the option to expand the grammar OR keep
narrow grammar + tighten producer-side phrasing (W15 evidence
strongly favors the latter for namespaces, the former for biology
mechanisms — see W15 close-out §7).

### §2.6 Stage 2 ConcordMet is **LLM-driven**, not deterministic

The 5 pathway-analysis paradigms (RaMP-DB ORA, Mummichog,
MetaboAnalystR PSEA, FELLA, SSPA) produce heterogeneous output; the
right combination depends on the task; hard-coded combinators do not
generalise. Therefore: an LLM ReAct runner orchestrates the 9
function-tools (`concord/agent/tool_dispatcher.py`).

**Death decree (2026-05-17):** "ConcordMet must be LLM-driven; do not
expose V3 deterministic algorithm tools." V3 is the previous
deterministic pipeline; surfacing it would shortcut the LLM's tool
selection and erase the entire investigation.

### §2.7 Verifier modification policy (2026-05-22, three tiers)

| tier | scope | gate |
|---|---|---|
| ✅ add | new layer / new helper / new regex / new enum value | no warning, normal PR |
| ⚠ modify | edit existing verifier logic (dispatcher, layer cascade) | commit body must carry `[verifier-modify-warning]` + per-modify justification + B1-test no-regression actual numbers |
| ❌ B1-core | `claim_extractor.extract_claims_from_json` / `feedback_hints.build_feedback_message` / `verifier/agent.py:_extract_classify` | banned by default; needs explicit user override |

Three guardrails (immutable):
- Tag `metagent-v2-base-b1` @ `ed6243b` cannot be moved (`git tag -f`
  forbidden)
- `data/eval/sub6/b1_d5_*/` + `data/eval/sub6/a3_rerun_*/` cannot be
  overwritten (B1 paper data)
- B1 test floor: 14 fail. Any new fail = halt + revert

### §2.8 UV optimisation sprints must start with reclassification

**Born from W12 lesson:** W12 spec assumed C7 namespace ≈ 80%
recoverable; reclassification showed only 54% (123 strict_id / 226).
W14 spec assumed C8+C9 ≈ 15% UV recoverable; reclassification showed
9.5% (14 strict_noise / 148). Both sprints would have set
unreachable targets without §0 reclassification.

**Rule (memory `feedback_uv_sprint_must_reclassify_first`):** every UV
optimisation sprint's §0 must run a strict-vs-fuzzy LLM
reclassification of the W11 surface bucket it targets, then set the
Hard Gate target as `ceiling × 0.6` (not the surface bucket size).

W15 extended this to a **3-way attribution** (producer_fault /
verifier_gap / both): even within a recoverable bucket, the lever
differs (prompt-side fix vs new verifier layer). The W15 audit is
the prerequisite for sequencing W16+ sprints.

### §2.9 Strict TDD per piece

Every code change must follow:
1. RED commit — write failing test, commit
2. GREEN commit — implement, commit (with `[verifier-modify-warning]`
   if applicable)
3. Tests must pass; Gate A (B1 verifier-core) cannot regress

W8 → W15 cumulative: **~60 commits / 0 strict-TDD slip**.

---

## §3 — Sprint timeline (W8 → W15)

Each entry is one sprint with key metric. Full close-out reports under
`reports/agent/concord_*` and `data/metagent/w15_uv_attribution/summary.md`.

| sprint | week | scope | UV % | supported % | pathway acc | iter-2 deg | wall | cost | commits |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| W8 | — | ConcordMet 5-PA wrapper + dispatcher + ReAct runner integration | — | — | — | — | — | — | many |
| W9 | — | D2 three-axis dispatcher fix + full sub6b-v3 framework verification | — | — | — | — | — | — | 16 |
| **W10 D4** | — | First Path X full 63-task run (baseline) | **52.95** | **28.62** | **54/63 = 85.7%** | 17.46% | 139.7 m | $11.17 | — |
| W10 D2.5 | — | enum-equality fix on feedback verdict filter (closed silent bug) | — | — | — | — | — | — | 2 |
| W10 P0-C | — | Regression-lock zero-LLM extract path (B1 D2 commit `2354011` invariant) | — | — | — | — | — | — | 3 |
| W10 D4.5 | — | iter-2 degradation diagnostic on N=11; H3_CONFIRMED (richer-feedback overshoot) | — | — | — | — | — | — | 2 |
| W11 | — | UV 9-cat surface classification (C1-C9), 1102 UV claim LLM-classify | — | — | — | — | — | $0.34 | 2 |
| **W12** | — | C7 namespace_form fix → `factual_sub6` layer + set_enrichment Stage 2.5 fuzzy | **51.45** | 26.61 | 54/63 | 22.22% | 109.8 m | $11.17 | 5 |
| **W13** | — | A: extended `_ID_PATTERNS` + subject normaliser; C: iter-2 diagnostic on N=14 | **47.79** | 31.91 | 54/63 | 15.87% (side-effect) | 103.7 m | $9.90 | 5 |
| **W14** | — | A: noise pattern + concord prompt banned; B: `max_feedback_iters=2→1` | **44.25** | **34.48** | **54/63** | **0.00%** (61/63 → 0/63 trigger) | **64.2 m** | **$6.83** | 6 |
| **W15** | — | UV attribution audit: 901 UV → {producer / verifier / both} | (audit) | — | — | — | (no rerun) | $0.93 | 5 |

**Cumulative W10 D4 → W14:**
- UV: **52.95 % → 44.25 %** = **−8.70 pp**
- Supported: **28.62 % → 34.48 %** = **+5.86 pp**
- Pathway accuracy: **54/63 (85.7 %)** stable across all sprints
- iter-2 trigger count: **61/63 → 0/63** (fully locked by W14.B)
- Wall: **139.7 m → 64.2 m** = **−54 %**
- Cost: **$11.17 → $6.83** = **−39 %**
- B1 verifier-core test: 407 pass / 0 fail throughout

---

## §4 — Sprint-level decision log (the chains the metrics depend on)

### §4.1 W10 D4 — first paper-grade dataset on `metagent-v2`

The merge-from-B1 + ConcordMet integration produced a working Path X
run with W12-pre baseline numbers. The decision to use this dataset as
the "before" benchmark (`data/concord/w10_d4_path_x_full/`) holds
through all subsequent sprints.

### §4.2 W10 D2.5 — silent enum-equality bug

During W10 D2 we noticed the feedback prompt iter ≥ 1 was rendering
"0 CONTRADICTED / 0 UNSUPPORTED / 0 UNVERIFIABLE / 0 DROPPED" even
when claims_v1 contained real verdicts. Root cause: on Python 3.11+
`str(Enum)` returns `"ClassName.MEMBER"` not the raw value, so the
filter `str(c.verdict).lower() == ClaimVerdict.X.value` never
matched. **Fix in `52613ac` switched all four verdict filters to
enum equality.** This was the prerequisite for everything downstream
— W11 attribution numbers, W12 / W13 / W14 sprint impact, W15 audit
ceilings all depend on the feedback loop actually surfacing
verdicts.

W11 / W12 D5 ran on the *fixed* feedback loop; the pre-fix
`feedback_made_it_worse` rates were artificially low because LLM
never saw real feedback content.

### §4.3 W10 D4.5 → W13.C → W14.B — the iter-2 story

- W10 D4.5: 11 iter-2-degraded tasks, 11/11 unsupported-dominant → H3
  confirmed at N=11.
- W12 D5: iter-2 deg rate jumped 17.7 % → 22.2 % (+4.5 pp). Could
  be H3 amplification OR W12 D4 dispatcher case side-effect.
  Hypothesis chosen for W13.C verification.
- W13.A: surprise −6.35 pp iter-2 deg as side-effect of extended ID
  patterns. Hypothesis: more grounded iter-1 claims → less surface
  area for iter-2 overshoot.
- W13.C: 14/14 unsupported-dominant on the larger N=14 W12 D5 slice.
  Σ Δ unsupported +48, Σ Δ contradicted −4, Σ Δ supported −9.
  H4 (W12 dispatcher side-effect) REFUTED. H3 CONFIRMED at N=14.
- W14.B: `DEFAULT_MAX_FEEDBACK_ITERS = 2 → 1`. iter-2 trigger 61/63
  → 0/63. Locked the side-effect at the dispatcher level.
- W14 surprise: UV drop 4.66× target. **The B cap eliminated
  iter-2's net-destructive unsupported additions** + W14.A noise
  prompt suppressed some claims upstream + LLM run variance gave
  smaller denominator. All three forces contributed to the 4.66×
  over-shoot.

### §4.4 W11 → W12 D ceiling — the "spec target was unreachable" pattern

W12 spec target: UV drop ≥ 12 pp from C7 namespace fix. W12 D5
actual: −1.50 pp. Spec gate 1 FAILED.

W12 D sub-task re-classified W11's 226 C7 claims:
- 123 strict_id (factual_sub6 amenable)
- 103 fuzzy_biology (out of scope, needs richer verifier)

Theoretical ceiling = 123 / 1102 = 11.16 pp, just below the spec
target. The −12 pp target was structurally infeasible.

**Lesson encoded in memory:** every UV sprint must reclassify
first. W14 repeated the same pattern (C8+C9 148 → 14 strict / 134
valid; ceiling 1.27 pp vs spec assumed ≈ 15 %).

### §4.5 W15 — the audit-only sprint that surprised everyone

W15 was pitched as a pure audit before W16: classify the residual
901 UV claims as producer / verifier / both. Two rubric passes:

| label | v1 (loose `both`) | v2 (DISAMBIGUATION RULE) | Δ |
|---|---:|---:|---:|
| producer_fault | 18.4 % | **27.9 %** | +9.4 pp |
| verifier_gap | 62.2 % | **52.5 %** | −9.7 pp |
| both | 19.4 % | 19.6 % | +0.2 pp |

**Finding:** v1 over-attributed soft-producer cases to verifier_gap.
v2's stricter "only `both` if BOTH conditions simultaneously true"
rule reassigned ~10 pp of mass into producer_fault.

**C7 deep-dive (user-requested):** C7 producer rate v1 43.8 % → v2
50.8 % (+7 pp). **Validates the hypothesis that W12 `factual_sub6`
did not cover the C7 residual because the residual is ReAct-side
optimisable** (wrong-prefix IDs, name-only refs, mis-namespaced
pathway IDs). W16 should fix C7 via prompt-side tightening, not
new verifier layer.

**HG-2 strict 60 % FAIL twice (v1 + v2)** with 0 hard producer ↔
verifier flips. All 8 disagreements sit on the soft `both` boundary.
Axis-level (treat `both` as match-either) = 100 % both runs. Per
user Option B step 5: accept v2 + transparent caveat.

### §4.6 The "no paper writing" death decree

User (2026-05-22): "Do not write paper narrative / Discussion /
Methods / Results / footnote / 'We demonstrate...' / 'In conclusion'
prose anywhere in commits or reports."

The data is paper-ready by W14 close-out. Multiple close-out reports
have been deliberately written as "table + caption only, no
interpretive prose". When paper writeup starts, the data + provenance
chain is in place; the writeup itself is not yet authorised.

---

## §5 — Current progress (concrete state at HEAD `de6cf5a`)

### §5.1 What is shipped and frozen

- Stage 1 7-tool stack (B1 phase, tag `metagent-v2-base-b1` @
  `ed6243b`)
- Stage 1 paper-grade datasets: B1 D5 v3 P0fix (`b1_d5_v3_p0fix/`),
  A3 same-LLM rerun (`a3_rerun_2026_05_19/`) — both **immutable**
- Stage 2 5-PA dispatcher + ReAct runner + closed-loop feedback
  (`concord/agent/`)
- Stage 2 verifier extensions: `factual_sub6` layer, extended
  `_ID_PATTERNS`, `subject_normalizer`, `fuzzy_match`,
  `noise_pattern`, `DroppedReason` enum
- W14 production config: `DEFAULT_MAX_FEEDBACK_ITERS = 1`,
  concord prompt with `## BANNED PHRASES — DO NOT WRITE` section
- W14 Path X paper-grade dataset: `w14_path_x_post_noise_cap/`
  (UV 44.25 %, supported 34.48 %, pathway 85.7 %, $6.83 / 64 min)
- W15 audit artifacts: `w15_uv_attribution/` (901 UV → v1 + v2
  attribution + 9-cat cross-tab + W16 candidate ranking)

### §5.2 Test surface

- B1 verifier-core suite: 407 pass / 0 fail (Gate A invariant W8 →
  W15)
- W12 14-case + W13 12-case + W14 11-case + W15 3-case = 40 new
  sprint-specific tests, all pass
- Full repo pytest (ignore=tests/test_ui --ignore=tests/integration):
  ~1371 pass / 14 fail (env: sspa pkg / R docker / GNPS)

### §5.3 What is "open" but not yet started

- **W16-A (recommended):** C7 producer prompt tighten. Ceiling 4.57
  pp UV reduction, ~3 d wall, prompt-only no verifier modify.
  Spec not yet written.
- **W17 candidates** (per W15 ranking):
  - C9 sub-classification audit (0.5 d prereq) → unlocks W17 sprint
  - C3 signal_evidence verifier layer (5.06 pp, 5-7 d, low ease)
- **W18+ deferred:**
  - C5 KEGG REACTION verifier (4.17 pp, 2-3 wk, requires external
    data dep)
  - C1+C2 cross-method consensus layer (2.31 pp, 1-1.5 wk)
  - C6 literature_reference verifier (2.50 pp, 2 wk, PubMed API
    cost + risk)

### §5.4 What is documented but explicitly out of scope

- Paper writeup (death decree)
- V3 deterministic algorithm tools exposed to LLM (death decree)
- B1 Stage 1 red line #4: driver-filtered correlation Δ ≥ +18 pp.
  Durable FAIL at +3.50 pp. Documented as Discussion limitation
  (tautology between ground-truth list and driver detection).
  Not a B1-claims blocker.
- The 134 W14 §0 valid_content claims (W11 mis-classification) —
  W15 v2 cross-tab has sub-classified them by attribution but not
  by W11 surface bucket; W17 candidate (C9 sub-classification)
  would refine

---

## §5A — Addendum: W16+ (W15 close `de6cf5a` → `metagent-v3-benchmark` HEAD `9a90d82`, 122 commits)

**Why this section exists.** §1–§14 of this document were written at the W15
close-out and describe the project accurately as of 2026-05-26. Between then and
now, 122 commits landed on a renamed branch (`metagent-v2` → `metagent-v3-benchmark`)
and none of it is reflected anywhere in this file or `CLAUDE.md` until this addendum.
`docs/PROJECT_MAP.md` (dated 2026-06-30) is the closest thing to an up-to-date
overview and should be read alongside this section — it has authoritative current
headline numbers this addendum mostly points at rather than re-derives.

### §5A.1 — Timeline in one table

| Phase | What happened | Outcome |
|---|---|---|
| W16 D3 | Added `signal_sub6` verifier layer + dispatcher catch-all | **Rolled back** — UV rose to 47.67% (worse than W14's 44.25%), disabled in `5933cdd` |
| W17 | Extended `SubsixSourceReport` with 4 method-keyed carrier fields (schema-only, no new consumer wired) | Landed. UV 44.92%, pathway 57/63 = 90.5% (best to date) |
| W18 | Added β `llm_judge_sub6` beta layer (LLM-as-verifier-tool on already-grounded claims) | Landed. UV 36.45% on a 59/63 "clean" subset (4 tasks excluded after a HEDGED-aggregation crash) |
| W19 | Added γ `tool_output_sub6` layer (checks RaMP/Mummichog/MetaboAnalystR claims against stored tool-output carriers) | **INCONCLUSIVE** — kept in code; small positive signal (~1pp) sits below ReAct rerun variance (~5pp); a dedicated crosswalk audit confirmed it did not break the W18 judge fall-through |
| W20 | Audited KEGG REST as a knowledge-base layer | **INCONCLUSIVE / GATE-STOPPED** — strict ceiling only 2.03pp against a ≥3pp implementation gate; **no production code was written**, audit-only |
| W21 | Piloted a `Hypothesis:` marker in the ReAct prompt to separate evidence-backed facts from biological interpretation | **INVALID EXPERIMENT** — the marker was lost between narrative text and extracted `claim_text` before the detector ever saw it; the 5-task pilot deltas are a pipeline bug artifact, not evidence either way. Full-59 was never run. |
| `cb9d745` | A single "chore" commit retroactively landing W16–W22 code, tests, and design docs that had been "running but never committed" | See §5A.6 (governance note) |
| ~W22 | `set_enrichment` rewritten to a multisource pathway pool (any paradigm hit → SUPPORTED, not just RaMP); new `ClaimVerdict.INSUFFICIENT_EVIDENCE`; new `structural_consistency` (2D) layer; v4 benchmark construction (InChIKey xref pipeline, SapBERT pathway-name matcher, MetaNetX structure index) | Landed — see §5A.3 |
| **Feedback redesign** | Full 112-task 3-arm A/B of feedback strategies; **cascade wired as the production default** (`00d47f0`) | Landed, **with a known unfixed regression** — see §5A.2, this is the single most important update in this addendum |
| `4c991b9` | Reports/docs reorganisation — introduced `docs/PROJECT_MAP.md`, `reports/reports_v2/`, `reports/reports_v3/`, archived (not deleted, all via `git mv`) superseded reports | Landed |
| benchmark v0→v1.3 | A separate benchmark-construction line: perturbation-anchored non-circular pipeline, a Miller 2015 Baylor MAPS multi-IEM task builder, and a v1.3 expansion adding lysine/carnitine + urea/propanoate replicates | Landed |
| **Phase A (current active work)** | Publication-grade 40-task benchmark: ontology-graded pathway matcher, bootstrap-CI scorecard, MPIB-Lit external baseline | **In progress** — see §5A.5 |

### §5A.2 — Architecture update: cascade supersedes the "iter cap=1, no iter-2" framing (updates §4.3)

§4.3 above ("the iter-2 story") is still an accurate *historical* record — three
independent diagnostics really did show a fresh LLM-rewrite second iteration is
net-destructive, and W14.B really did cap `max_feedback_iters` at 1. **That
finding was not overturned.** But the feedback mechanism itself was redesigned on
top of it:

- Three strategies were designed in `concord/agent/feedback_strategies.py`:
  - **A_cascade** (now the production default): deterministically processes
    iter-0 verdicts — keep SUPPORTED, replace CONTRADICTED with the multisource
    pool's top-1, drop UNSUPPORTED, drop UV — then makes exactly **one** LLM call
    to weave a narrative. The LLM cannot add, remove, or reinterpret claims.
  - **B_anchored**: LLM-anchored rewrite. **Failed catastrophically** in the full
    112-task experiment (pathway 54.05% vs a 75.00% no-feedback baseline; noise
    count 651 vs 0). Rejected.
  - **C gating**: mentioned in the design doc; no independent implementation
    evidence found in the commit history.
- Decision record: `docs/decisions/2026-06-26_feedback_workflow_a_cascade.md`.
  Cascade is wired into `ConcordReactRunner` as `feedback_strategy: str =
  "cascade"` (`00d47f0`, tagged `[concord-modify-warning]`); the legacy rewrite
  path is preserved for backward compatibility as `feedback_strategy="rewrite"`.
- This does **not** reopen the "iter-2" question W14.B closed. Cascade's
  iteration is a deterministic claim-filter plus one narrow LLM narrative call,
  not a second free-form ReAct rewrite — mechanically closer to GeneAgent's
  deterministic-cascade correction than to the thing W14.B banned.

**⚠ The production default has a known, quantified, currently-unpatched
regression.** On the v4 112-task benchmark:

| Metric | raw iter-0 | cascade final (production default) | Δ |
|---|---:|---:|---:|
| Pathway semantic accuracy | **79.46%** | 71.43% | **−8.03pp, purely negative (0 fixed / 9 broken)** |
| Claim noise (UNSUPPORTED+UV) | high | ~0 | large improvement |

Root cause, per `docs/decisions/2026-07-01_verifier_feedback_lock_pathway_to_raw.md`
(**this decision doc is currently untracked — not committed to git — but its
content is the most current design thinking on this issue and should be read**):

1. **R1** — after cascade drops UNSUPPORTED/UV claims, the pathway second-pass
   re-derives its primary prediction from the *remaining* claims, losing the
   signal that pointed at the correct pathway. 6 of the 9 broken tasks show this
   "drop-then-re-derive" pattern with zero actual counter-evidence.
2. **R2** — W15 already established that 52.5% of UV claims are `verifier_gap`
   (unverifiable ≠ wrong). Cascade treats all UV as noise to remove, which means
   it is operating on a low-precision signal.

**Proposed fix (D1), validated but not yet implemented in code**: lock the
final `pathway_prediction.primary` to the raw iter-0 prediction rather than
re-deriving it from cascade-filtered claims; cascade's claim cleanup would then
only affect the cosmetic narrative, never the pathway verdict. A zero-LLM
counterfactual replay (`scripts/metagent/validate_lock_pathway_to_raw.py`,
untracked) on the existing 112-task run shows this recovers **71.43% → 79.46%**
(+8.03pp) with no observed downside — cascade never beat raw on this metric in
any of the 9 disagreement cases. **This is the highest-priority next step for
whoever picks this project up** — see §5A.8.

### §5A.3 — Verifier layer inventory (what exists now, and its status)

| Layer | Introduced | Status |
|---|---|---|
| `factual_sub6` / extended `_ID_PATTERNS` / `subject_normalizer` / `fuzzy_match` / `noise_pattern` | W12–W14 | Production, unchanged since §1-§14 was written |
| `signal_sub6` | W16 | **Disabled** — dispatcher catch-all turned off in `5933cdd`; code remains but does not run |
| `llm_judge_sub6` | W18 | **Beta, wired into production** (final-iteration only, has a cost cap) |
| `tool_output_sub6` | W19 | **Retained, inconclusive** — small positive signal, not proven harmful or clearly beneficial |
| KEGG REST knowledge-base layer | W20 (audit) | **Never implemented** — ceiling too small, audit-only, no production code |
| `structural_consistency` (2D) | ~W22 | New, wired into `verify_sub6`'s `SET_ENRICHMENT` branch |
| `set_enrichment` | ~W22 | **Rewritten** from single-source RaMP judgement to a multisource pool (any of the 5 paradigms hitting → SUPPORTED); `998e112`, tagged `[verifier-modify-warning]` |
| `ClaimVerdict.INSUFFICIENT_EVIDENCE` | ~W22 | New verdict value, wired through metrics/severity/`react_runner` |

### §5A.4 — v3/v4 benchmark infrastructure (why several new pathway-matching components exist)

A large chunk of this window rebuilt pathway-matching infrastructure because the
old sub6b-v3 (63-task) namespace coverage was insufficient and the project needed
external-baseline comparability:

- A unified `structure_resolver` + a MetaNetX structure index + an exclusion sidecar
- A SapBERT pathway-name semantic matcher with token-overlap fallback
- An InChIKey cross-reference pipeline feeding the **v4 benchmark (342 tasks,
  292 after a P0 filter)**: `data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_metabolic.jsonl`
- Design docs: `docs/decisions/2026-06-23_v3_part2_embedding_method_upgrade.md`,
  `docs/decisions/2026-06-25_v4bench_second_pass_matcher_fix.md`,
  `docs/decisions/2026-06-25_verifier_multisource_refactor.md`

### §5A.5 — Benchmark version lineage (easy to get lost here — read this table first)

| Name | Size | Source / purpose | Status |
|---|---:|---|---|
| `sub6b_mammalian_tasks_v3.jsonl` | 63 | W8–W15's Path X main benchmark | Still the legacy comparison baseline |
| `metagent_bench_v2` (v4) | 342 → 292 after P0 filter | Built from the InChIKey xref + SapBERT pipeline; the subset actually run day-to-day is sub6 63 + hmdb_ramp filtered 49 = **112** | Current main evaluation set |
| benchmark v0→v1.3 | grows per version | A separate construction line: perturbation-anchored non-circular pipeline + Miller 2015 Baylor MAPS multi-IEM builder + lysine/carnitine, urea/propanoate replicate expansion | Landed, independent of v4 |
| `data/benchmark/impc_pilot/` (**untracked**) | small pilot | New IMPC pilot task set; not yet wired into any eval driver | Purpose not documented in commit history — confirm with the original author before relying on it |
| **Phase A publication-grade** | target N=40, 60 stretch | Prioritizes exhausting Miller data, then Sahoo/Recon logical extension, then new downloads only if needed | **In progress**, see §5A.6 |
| MPIB-Lit (Biomni) | external | Scored with the *same* official rubric matcher as MetAgent, for cross-method comparison | Wired in (`73d2e09`, single-shot iter0 = official baseline) |

### §5A.6 — Current active work: Phase A publication-grade benchmark

Spec: `docs/decisions/2026-07-07_phase_a_benchmark_publication_grade_spec.md`
(finalized, user-authorized to execute autonomously). Goal: a reproducible,
auto-scored **40-task benchmark** plus MetAgent's results on it. (Publication
narrative itself remains out of scope per the standing "no paper writing" decree
— this section tracks engineering progress only.)

Four accepted design decisions:
1. **Rubric = ontology-driven automatic grading, dual threshold.** Tiers ∈
   {exact, parent_child, adjacent, miss}; strict = exact+parent_child, lenient =
   strict+adjacent. Adjacency computed objectively from RaMP
   (`analytehaspathway`, 1.35M rows; `pathway_duplicates`; `pathway_similarity`),
   not hand-tuned. Implementation: `scripts/metagent/pathway_match_rubric.py`
   (deterministic, zero-LLM, unit-testable). **Hard gate**: must reproduce the
   human strict 13/19 and lenient 15/19 judgement on the existing 19-task set.
2. **N=40 hard target / 60 stretch**, sourcing priority A (exhaust Miller, zero
   download) → B (Sahoo/Recon logical extension) → C (download new cohorts only
   if needed).
3. **Statistics on our own model only** — bootstrap task-level CIs + 3-seed
   range + per-family breakdown; permutation tests / baseline comparisons are
   deferred to a future "Phase B".
4. Full public release (CC-BY-4.0 data / MIT code).

Progress artifacts already present in the working tree (some not yet committed):
- `scripts/metagent/pathway_match_rubric.py` — the current worktree has one
  uncommitted increment adding a "synonym pathway name" match (e.g. "Leucine,
  isoleucine and valine metabolism" and "Valine, leucine and isoleucine
  degradation" both resolve to EXACT), with matching RED/GREEN tests. Worth
  committing as-is.
- A-stats scorecard (bootstrap CI + per-family + tier distribution, `dbaa782`)
- Extended gold registry (pyrimidine/purine/FAO, `9934978`)
- `v4_bench_eval.py` gained a `--feedback-strategy` flag, default cascade (`8dea4ef`)
- MPIB-Lit official baseline = single-shot (iter0) scoring (`73d2e09`)
- A cluster of untracked zero-LLM diagnostic scripts (§5A.7), mostly aimed at the
  two open questions "where exactly is the cascade pathway regression coming
  from" and "what is the actual pathway accuracy ceiling."

### §5A.7 — Untracked artifacts a new maintainer needs to know exist

None of the following are in `git log` yet, but they are current analysis, not
scratch work — easy to miss during handoff:

| File | Purpose |
|---|---|
| `docs/decisions/2026-07-01_verifier_feedback_lock_pathway_to_raw.md` | The D1 fix proposal from §5A.2 — **the single most important uncommitted document** |
| `scripts/metagent/validate_lock_pathway_to_raw.py` | Zero-LLM counterfactual validator for D1 |
| `scripts/metagent/diagnose_pathway_ceiling.py`, `pathway_oracle_ceiling.py`, `simulate_pathway_critic.py` | Zero-LLM diagnostics decomposing the pathway gap into tool-ceiling / LLM-selection / matcher-measurement error; an oracle upper bound; a simulated-critic net-benefit estimate |
| `scripts/metagent/eval_biomni_mpib_lit.py`, `run_llm_mpib_baselines.py`, `tests/test_llm_mpib_baseline.py` | Score the external MPIB baseline with the same official rubric matcher, for cross-method comparison |
| `scripts/metagent/stage1_2_e2e_build.py`, `stage1_2_e2e_analysis.py` | Chains real (non-perfect-id) Stage 1 identification into Stage 2 for a genuine end-to-end evaluation |
| `scripts/metagent/stage2_detailed_analysis.py` | Detailed cascade-vs-legacy breakdown (pathway / claims / tools / case studies) |
| `scripts/eval_sub6/rerank_mcnemar_stats.py` | Paired McNemar test for Stage 1 rerank before/after |
| `data/benchmark/impc_pilot/` | New pilot task set; purpose undocumented in history |

### §5A.8 — Governance check: verifier modification policy (§2.7) compliance

Checked every commit touching `verifier/` between `de6cf5a` and HEAD against the
three-tier policy in §2.7 — **the full commit body**, not just the `git log
--oneline` subject line, since `[verifier-modify-warning]` is written in the
body. Result: the large majority of substantive existing-logic changes (the
`set_enrichment` rewrite, the `INSUFFICIENT_EVIDENCE` metrics rollup, the
cascade wiring in `react_runner.py`) correctly carry the warning tag with
justification and B1-regression numbers. The discipline mostly held.

Two things worth flagging, not as accusations but as things a new maintainer
should know about:

1. `cb9d745` ("chore: land W16–W22 verifier/eval code ... that had been running
   but never committed") bundles an 8-line change to
   `verifier/layers/set_enrichment.py` without its own individual RED/GREEN +
   warning-tag treatment, because it was landed retroactively as one big commit.
   The content itself looks benign (it accompanies new helpers/schema fields
   from the same window), but this "accumulate for days then land as one chore
   commit" pattern itself is a deviation from §2.9's "one RED/GREEN commit per
   piece" discipline — worth not treating as a precedent to repeat.
2. The cascade pathway regression in §5A.2 is not a missing-tag problem — it is
   a **known, quantified regression that shipped to the production default
   before being patched**. That is a more urgent issue than the tag audit
   itself.

### §5A.9 — What to do next (supersedes the outdated pointer in §11 below)

1. Read `docs/PROJECT_MAP.md` first — it is the closest thing to a structured,
   up-to-date "what exists / how to run it / where results live" reference; this
   addendum fills in what happened *after* it was last updated.
2. **Highest-priority technical debt**: implement D1 from §5A.2 (lock
   `pathway_prediction.primary` to raw iter-0 instead of re-deriving it from
   cascade-filtered claims). Expected zero LLM cost, +8pp pathway recovery,
   validation script already exists. Tag the commit `[concord-modify-warning]`.
3. **Then** continue Phase A (§5A.6): A2 (expand to 40 tasks) → A3 (3-seed rerun
   + scoring) → A4 (release package).
4. §11's "W16 starting point: C7 producer prompt tighten" below is **stale** —
   it was a W15-era candidate that has been bypassed by the subsequent 122
   commits. Do not resume it as the next step.

---

## §6 — Known issues and worked-around quirks

### §6.1 Solved (with commit reference)

| problem | resolution | commit |
|---|---|---|
| `extract_claims` made a redundant LLM call when LLM output was already grammar-v2 JSON | B1 D2 auto-detect grammar-v2 → `extract_claims_from_json` zero-LLM path | `2354011` (B1), regression-locked in W10 P0-C `9b0f899` |
| `str(Enum)` Py3.11+ change broke feedback verdict filter | Switch all 4 filters to enum equality | W10 D2.5 `52613ac` |
| Verifier `dropped_claims` did not surface through `VerifiedClaim.grammar` | Add field passthrough + stamp helper | B1 P0 fix `ed6243b` |
| iter-2 quality degradation 11.3 % → 17.7 % then 22.2 % | H3_CONFIRMED via N=14 diagnostic; W14.B caps feedback iters at 1 → 0/63 trigger | W14.B `dd8bb3e` |
| W12 spec target -12 pp unreachable (ceiling 11.16 pp) | Mandatory §0 reclassification protocol | W12 D `edb8fe4`, memory `feedback_uv_sprint_must_reclassify_first` |
| W14 §0 expected C8+C9 ≈ 15 % UV, real 9.5 % | Sprint primary value shifted from A to B (iter-2 cap); UV target recalibrated to 0.76 pp | W14 §0 `143f5e0` |
| W11 9-cat classification too coarse for sequencing decisions | W15 attribution audit adds producer / verifier / both axis | W15 `de6cf5a`, summary at `data/metagent/w15_uv_attribution/summary.md` |
| `data/concord/chebi.sqlite` + `metanetx.sqlite` are 620 MB, ETL re-run takes hours; gitignored | `setup_metagent_v2_env.sh` symlinks from sibling investigation worktree | `8c4e90b` |
| C7 namespace `factual_sub6` only covered 56.9 % of strict_id (W12) | W13.A extends `_ID_PATTERNS` (KEGG drug D-prefix, paren bare ID, PubChem 3 forms, ChEBI underscore/IRI) + subject normaliser | W13.A `e9e9fdb` |
| Initial v1 W15 classifier had 21 UNCLASSIFIED claims (batch 10 dropped) | Positional claim_id remap + retry pass with batch=5 | W15 retry script |

### §6.2 Open caveats

| caveat | status | mitigation |
|---|---|---|
| HG-2 W15 strict 20-sample agreement 60 % (not 80 %) | Accepted per user Option B + transparent note in `summary.md` | All 8 disagreements are soft `both` boundary; axis-level 100 % robust |
| `data/concord/metanetx.sqlite` has only compound xref, no pathway xref | W12 D4 namespace cross-walk skipped + documented in `verifier/helpers/__init__.py` | If pathway cross-walk needed in future: PathBank or hand-curated table required |
| W14 §0 134 valid_content claims live in C9 bucket, mixed types | Not yet sub-classified; W15 v2 cross-tab partially does it via attribution × W11 | W17 candidate: dedicated C9 sub-classifier (0.5 d) |
| Verifier hedge regex catches words like "suggests" inside biology-valid claims | Pre-existing, not introduced by W14 | W14.A noise check runs BEFORE hedge check so noise wins the drop_reason; bigger fix is future scope |
| C5 intermediate_biology (135 claims, 63 % verifier_gap) needs KEGG REACTION DB | No external data dep ingested | W19+ candidate; high engineering cost |
| Stage 1 red line #4 (driver-filtered correlation Δ ≥ 18 pp) durable FAIL +3.50 pp | Documented in `phase_b1_step_r_v3.md` + `phase_b1_step_r_per_layer.md` | Paper Discussion material; not a blocker |
| `concord/agent/` integration tests can pre-existing-fail (sspa pkg, R docker, GNPS env) | 12 fails baseline | Run setup script; tolerate the 12 fails as W13 baseline |

---

## §7 — Death decrees (must follow, all sprints)

Maintained as Claude memory at
`/home/weiwentao/.claude/projects/-home-weiwentao-workspace-llm-agent-metabolomics-metagent-day1-v5/memory/`:

1. **`feedback_language_chinese.md`** — Chinese conversation, English
   code/identifiers.
2. **`feedback_proceed_with_defaults.md`** — Full spec + "go" means
   proceed with defaults; do not ask redundant questions.
3. **`feedback_no_paper_writing_yet.md`** — No paper narrative /
   Discussion / Methods / Results / footnote / "We demonstrate..."
   prose anywhere.
4. **`feedback_concordmet_must_be_llm_driven.md`** — Stage 2 must
   stay LLM-driven; do NOT expose V3 deterministic algorithm tools.
5. **`feedback_plain_summary_at_end.md`** — Every assistant response
   ends with 2-paragraph plain-language summary (progress + next),
   1-3 sentences each. No strict-TDD / commit / sprint jargon.
6. **`feedback_uv_sprint_must_reclassify_first.md`** — Every UV
   optimisation sprint's §0 must reclassify the W11 surface bucket
   it targets BEFORE setting Hard Gate target.
7. **`feedback_verifier_modification_policy.md`** — Three-tier
   verifier modification policy (✅ add / ⚠ modify with warning / ❌
   B1-core banned).
8. **`reference_minimax_is_remote_api.md`** — MiniMax is a remote
   API. Cost is from `logs/llm_calls.jsonl` token usage. Never
   claim "$0 local".

Three guardrails:
- Tag `metagent-v2-base-b1` @ `ed6243b` cannot be moved
- B1 paper data `data/eval/sub6/b1_d5_*/` + `a3_rerun_*/` cannot be
  overwritten
- B1 test floor 14 fail. Any new fail → halt + revert

---

## §8 — Key experimental conclusions

### §8.1 Stage 1 (B1 phase)

- **Top-1 method C (hybrid extractor): 83.60 ± 7.48 %** (N=3 seeds,
  mean ± SE) on sub6b-v3 mammalian benchmark.
- **B1 hybrid extractor lift over A3 baseline: +16.93 pp** (A3 =
  66.67 ± 4.75 %, same-LLM rerun).
- **P0 fix marginal on top-1 = 0.00 pp.** Attribution shifted from
  "P0 fix" to "LLM version drift between 2026-05-15 and 2026-05-18"
  via W10 P0-isolation analysis. Documented in
  `reports/agent/phase_b1_p0_isolation.md`.
- **Per-layer breakdown (Stage C step_r_per_layer):**
  - Layer 6c (consistency): 99.9 % supported, Δ −0.07
  - Layer 6a (set_enrichment): 96.6 % supported, Δ +17.97
  - Layer 6b (driver_metabolite): 72.3 % supported, Δ +3.50
- **Red line #4 (driver-filtered correlation Δ ≥ +18 pp): durable
  FAIL at +3.50 pp on v3 N=3.** Captured as Discussion material in
  `phase_b1_step_r_v3.md`.

### §8.2 Stage 2 (W8 → W14)

- **Cumulative UV reduction: −8.70 pp** (52.95 → 44.25 %, W10 D4 →
  W14).
- **Cumulative supported lift: +5.86 pp** (28.62 → 34.48 %).
- **Pathway accuracy held at 85.7 %** across all sprints.
- **iter-2 trigger count locked at 0/63** by W14.B (was 61/63 in
  W13).
- **API cost down 39 %** ($11.17 → $6.83 per Path X run).
- **Wall down 54 %** (139.7 → 64.2 min).

### §8.3 W15 attribution audit (residual 901 UV claims)

- **52.5 % verifier_gap** (legitimate, no verifier layer covers)
- **27.9 % producer_fault** (LLM should not have written this)
- **19.6 % both**

Bucket-level attribution highlights:
- **C7 namespace: 50.8 % producer** (recoverable by prompt fix —
  the W16 recommendation)
- **C8 noise: 100 % producer** (already partially covered by W14.A)
- **C9 other: 51 % verifier, 28 % producer, 21 % both** (mixed,
  needs sub-classification)
- **C3 signal_evidence: 69 % verifier** (recoverable by new layer)
- **C5 intermediate_biology: 63 % verifier** (recoverable by KEGG
  REACTION integration)
- **C1 cross-method: 68 % verifier** (recoverable by consensus
  layer)

### §8.4 Methodology lessons (encoded in memory, must be followed)

- **Pre-sprint reclassification is mandatory.** Surface-form
  classification overestimates ceiling by 1.5–8× depending on
  bucket. Three sprints (W12 / W14 / W15) confirmed this.
- **3-way attribution (producer / verifier / both) sequences sprint
  candidates.** Producer-side fixes are cheap (prompt) but capped;
  verifier-side fixes are expensive (new layer) but uncapped.
  Sequencing matters.
- **iter-2 feedback loop is net-destructive on this benchmark.**
  Three independent diagnostics (W10 D4.5, W13.C, W14 D5 rerun)
  agree. W14.B `max_feedback_iters=1` is a hard finding.
- **DISAMBIGUATION RULE matters in classifier prompts.** Without
  it, LLM defaults to `both` for any ambiguity, inflating the
  category. W15 v1 → v2 shifted 9.7 pp of mass.

---

## §9 — How to run things

### §9.1 Environment cold-start (mandatory after fresh `git worktree add`)

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2
./scripts/concord/setup_metagent_v2_env.sh
# Symlinks chebi.sqlite + metanetx.sqlite from sibling investigation
# worktree (~620 MB total, gitignored)
```

Environment variables:
```bash
export MINIMAX_API_KEY=<your key>    # Stage 2 default
# or
export METAGENT_OPENAI_API_KEY=<key>  # OpenAI fallback (set
export METAGENT_LLM_PROVIDER=openai   # provider switch)
```

### §9.2 Stage 1 — per-spectrum identification

```bash
# Run a single spectrum through the deterministic pipeline (no LLM)
python scripts/run_full_pipeline.py --fixture glucose_pos --output md

# Run sub6a (real-id rerank evaluation)
python evaluation/sub6/run_sub6a.py \
    --benchmark data/benchmark/sub6/sub6a_*.jsonl

# Run sub6b (perfect-id narrative)
python evaluation/sub6/run_sub6b.py \
    --benchmark data/benchmark/sub6/sub6b_*.jsonl

# Run sub6b ReAct + verifier feedback loop (B1 D4)
python evaluation/sub6/run_sub6b_react_feedback.py --benchmark <path>
```

### §9.3 Stage 2 — pathway-level narrative (main workstream)

```bash
PYTHONPATH=. \
METAGENT_LLM_LOG_PATH=logs/concord/<sprint>_path_x.jsonl \
python scripts/concord/w10_d4_path_x_full.py \
    --benchmark data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --output data/concord/<sprint>_path_x/path_x_full63_results.jsonl \
    --summary data/concord/<sprint>_path_x/path_x_full63_summary.json \
    --full-dir data/concord/<sprint>_path_x/path_x_full \
    --llm-log logs/concord/<sprint>_path_x.jsonl \
    --max-react-turns 8 \
    --max-feedback-iters 1 \
    --k-concurrent 10
```

Expected wall ~ 1-1.5 h, API cost ~ $7-8 with default config.

Outputs:
- `path_x_full63_results.jsonl` — per-task signal aggregate
- `path_x_full63_summary.json` — overall aggregate
- `path_x_full/<task_id>.json` — per-task full ConcordFeedbackResult
  trace

### §9.4 W15 UV attribution (audit, no rerun)

```bash
# D1 extract
PYTHONPATH=. python scripts/metagent/w15_uv_attribution.py

# D2 classifier (v2 with DISAMBIGUATION RULE)
PYTHONPATH=. \
METAGENT_LLM_LOG_PATH=logs/concord/w15_uv_attribution.jsonl \
python scripts/metagent/w15_v2_retry.py
```

### §9.5 Tests

```bash
# Gate A — B1 verifier-core (must be 407 / 0 every sprint)
PYTHONPATH=. pytest \
    tests/test_verifier/ \
    tests/test_d4_feedback_dispatcher.py \
    tests/test_grammar_validate.py \
    tests/test_classifier_collapse.py \
    tests/test_runner_response_format.py \
    tests/test_prompt_banned_sync.py \
    -q

# Gate B — full repo (must be ~1371 / 14 at HEAD `de6cf5a`)
PYTHONPATH=. pytest -q --tb=line \
    --ignore=tests/test_ui --ignore=tests/integration

# Sprint-specific (example: W14)
pytest tests/test_grammar_noise_pattern.py \
       tests/test_concord_react_prompt_banned.py \
       tests/test_react_runner_iter_cap.py -v
```

---

## §10 — Directory map (annotated)

```
metagent_v2/
├── HANDOFF.md                 # this file
├── CLAUDE.md                  # agent-oriented sibling (shorter)
├── README.md                  # public-facing v0 description
├── docs/
│   ├── ARCHITECTURE.md        # MUST READ — design philosophy
│   ├── TOOL_CONTRACTS.md      # Stage 1 7-tool I/O
│   ├── claim_grammar_v2.md    # Stage 2 4-shape grammar
│   ├── LLM_INTEGRATION.md     # provider switch, caching
│   └── concord/               # Stage 2 W3-W7 design docs
│
├── schemas/                   # Pydantic contracts (LAW)
│   ├── report.py              # IdentificationReport (Stage 1 output)
│   ├── sub6_report.py         # SubsixSourceReport (Stage 2 input)
│   └── peak.py / spectrum.py  # Stage 1 spectrum / peak
│
├── tools/                     # Stage 1 — one subdir per tool
│   ├── spectrum_ops/          # A1 spectrum preprocess
│   ├── candidate_prefilter/   # A2
│   ├── library_search/        # B
│   ├── molecule_gen/          # C
│   ├── metabolite_info/       # D1 (HMDB/KEGG/ChEBI fetch)
│   ├── pathway_context/       # D2
│   ├── spectrum_predict/      # E (CFM-ID / SIRIUS)
│   ├── literature/            # F (PubMed / Europe PMC)
│   └── agent_tools/           # generic LLM tool adapter
│
├── orchestrator/              # Stage 1 LLM orchestration
│   ├── naive.py               # baseline orchestrator
│   ├── prompt.py / formatter.py
│   └── __main__.py            # CLI entry
│
├── verifier/                  # B1 verifier (shared by Stage 1 + 2)
│   ├── agent.py               # verify() + verify_sub6() entries
│   ├── grammar.py             # 4-shape grammar + DroppedReason enum
│   ├── claim_extractor.py     # extract_claims_from_json (B1 D2)
│   ├── claim_classifier.py    # 9-cat → 4-shape collapse
│   ├── feedback_hints.py      # B1 D4 annotate_claims
│   ├── task_outcome.py        # NORMAL / EMPTY_* enum
│   ├── layers/
│   │   ├── factual_sub6.py    # W12 D3 — Sub-6 factual layer (NEW)
│   │   ├── biological_sub6.py
│   │   ├── set_enrichment.py  # Layer 6a (W12 D4 fuzzy)
│   │   ├── driver_metabolite.py
│   │   └── pathway_relationship.py
│   ├── helpers/               # W13 / W14 add
│   │   ├── fuzzy_match.py     # W13.A token-Jaccard
│   │   ├── subject_normalizer.py  # W13.A NFKD + Greek + whitespace
│   │   └── noise_pattern.py   # W14.A noise regex
│   └── schemas.py
│
├── concord/                   # Stage 2 5-PA dispatcher + ReAct
│   ├── agent/
│   │   ├── react_runner.py    # ConcordReactRunner (W8)
│   │   ├── system_prompts.py
│   │   ├── tool_dispatcher.py # 9 function-tool routing
│   │   ├── tool_handlers.py
│   │   └── verifier_adapter.py # ConcordReactResult → SubsixSourceReport
│   ├── wrappers/              # 5 PA tool wrappers (W3-W7)
│   ├── normalize/             # wrapper output → v0.3.1 schema
│   ├── reconcile/             # cross-source ID + charge state
│   ├── analyze/               # pathway_match / consensus / gate variants
│   ├── etl/                   # ChEBI / MetaNetX / Cooke / Pathways
│   ├── lookup/                # thread-safe ChEBI lookup
│   └── schema/                # EnrichmentResult / PathwayHit
│
├── evaluation/
│   ├── sub6/                  # Stage 1 evaluation
│   └── concord/path_x.py      # Stage 2 main evaluation
│
├── prompts/
│   ├── concord/concord_react_prompt.md   # Stage 2 system prompt (W14 BANNED PHRASES section)
│   ├── agent/sub6b_react*.md             # Stage 1 narrative prompts
│   ├── track_AGENT_phase_B1_*.md         # B1 sprint specs
│   ├── track_CONCORD_*.md                # W8-W14 sprint specs
│   └── track_MetAgent_W15_*.md           # W15 sprint spec
│
├── tests/                     # B1 + W12-W15 + concord
│   ├── test_verifier/         # B1 D2-D4 unit (~320 cases)
│   ├── test_factual_sub6.py + test_factual_sub6_id_patterns_extended.py
│   ├── test_grammar_noise_pattern.py + test_concord_react_prompt_banned.py
│   ├── test_react_runner_iter_cap.py
│   ├── test_w15_uv_attribution_extractor.py
│   └── concord/               # W3-W9 unit + integration (148+ cases)
│
├── scripts/
│   ├── concord/               # W3-W14 ConcordMet drivers
│   │   ├── w10_d4_path_x_full.py        # MAIN Stage 2 evaluator
│   │   ├── w11_extract_uv_claims.py / w11_classify_uv_claims.py
│   │   ├── w12_d_reclassify_c7_strict_vs_fuzzy.py
│   │   ├── w13_c_iter2_diagnostic.py
│   │   ├── w14_c8c9_strict_vs_valid.py
│   │   └── setup_metagent_v2_env.sh     # MUST RUN after worktree add
│   ├── eval_sub6/             # Stage 1 aggregators
│   └── metagent/              # W15+ audit scripts
│       ├── w15_uv_attribution.py
│       └── w15_v2_retry.py
│
├── data/
│   ├── benchmark/sub6/        # sub6b_mammalian_tasks_v3.jsonl (63 task)
│   │   └── curated_hmdb_mammalian.jsonl  # W12 factual_sub6 fallback
│   ├── concord/
│   │   ├── chebi.sqlite / metanetx.sqlite  # gitignored, symlinked
│   │   ├── pathway_members.sqlite
│   │   ├── w10_d4_path_x_full/                 # W10 baseline
│   │   ├── w12_path_x_post_c7/                 # W12 D5
│   │   ├── w13_a_path_x_post_extended_id/      # W13.A
│   │   ├── w14_path_x_post_noise_cap/          # W14 (CURRENT)
│   │   ├── w11_uv_diagnosis/
│   │   ├── w12_uv_ceiling/
│   │   ├── w13_c_iter2_diagnostic/
│   │   ├── w14_uv_reclassify/
│   │   └── w10_d4_5_degradation_diagnostic/
│   ├── metagent/
│   │   └── w15_uv_attribution/                 # W15 audit
│   └── eval/sub6/             # B1 paper data — IMMUTABLE
│       └── b1_d5_*/, a3_rerun_*/
│
├── reports/
│   └── agent/                 # one report per sprint
│       ├── concord_sprint_w*_status.md
│       ├── concord_w*_close_out.md
│       ├── concord_w11_uv_diagnosis.md
│       └── phase_b1_*.md
│
└── logs/
    ├── llm_calls.jsonl        # global LLM call log (cost source)
    └── concord/               # per-sprint LLM logs
```

---

## §11 — Onboarding checklist (for a new maintainer)

1. **Read this file end to end.** This is the most efficient
   on-ramp.
2. **Read `docs/ARCHITECTURE.md`** for Stage 1 design philosophy.
3. **Read `docs/claim_grammar_v2.md`** for Stage 2 4-shape grammar.
4. **Run `./scripts/concord/setup_metagent_v2_env.sh`** to symlink
   sqlite. Without this, 12 concord tests fail and
   `verify_sub6()` cannot run.
5. **Run Gate A.** Confirm 407 pass / 0 fail. If not, do not
   proceed — investigate before touching code.
6. **Read the most recent close-out:**
   `reports/agent/concord_w14_close_out.md` +
   `data/metagent/w15_uv_attribution/summary.md`.
7. **Read the most recent sprint spec** for context on the active
   work pattern: `prompts/track_MetAgent_W15_uv_attribution_audit.md`.
8. **Inspect the memory dir** at
   `/home/weiwentao/.claude/projects/-home-weiwentao-workspace-llm-agent-metabolomics-metagent-day1-v5/memory/`
   to see all 8 death decrees + 3 project memories.
9. ~~**W16 starting point:** C7 producer prompt tighten~~ — **stale, superseded.**
   122 commits happened after this was written. Read **§5A** first; the real
   current starting point is §5A.9 (fix the cascade pathway regression, then
   continue Phase A).

---

## §12 — Glossary

- **B1 phase** — Stage 1 work that produced the paper-grade sub6a /
  sub6b datasets and the tag `metagent-v2-base-b1`. Frozen.
- **ConcordMet** — name of the Stage 2 5-PA dispatcher subsystem
  (historical name, lives in `concord/`). NOT the project name.
  Project name is **MetAgent**.
- **Path X** — the main Stage 2 evaluation protocol: 63 sub6b
  mammalian tasks, multi-PA dispatcher, closed-loop verifier
  feedback. Re-run each major sprint.
- **C1-C9** — W11's 9 surface-form categories of UV claims:
  C1 cross-method consensus / C2 method disagreement / C3 signal
  evidence / C4 uncertainty qualifier / C5 intermediate biology /
  C6 literature reference / C7 namespace form / C8 noise / C9 other.
- **UV** — `UNVERIFIABLE_V0`, the verdict for claims that cannot be
  judged against current verifier layers.
- **Gate A** — B1 verifier-core test suite (407 cases). Cannot
  regress.
- **Gate B** — full repo pytest. Cannot regress.
- **Hard Gate** — sprint-specific completion criteria. Failure
  triggers halt + ping user.
- **W11 9-cat reclassification** — the now-standard pre-sprint §0
  protocol: LLM-classify the residual UV in the target W11 bucket
  into strict-vs-fuzzy or producer-vs-verifier-vs-both before
  setting Hard Gate target.
- **iter-2 / iter-2 degradation** — the second iteration of the
  closed-loop feedback (iter 0 = initial, iter 1 = first
  rewrite, iter 2 = second rewrite). H3_CONFIRMED at N=11 and
  N=14: iter 2 is net-destructive on this benchmark. W14.B caps
  feedback at 1 iter.

---

## §13 — Sibling worktrees (do not confuse)

| worktree | purpose | tag |
|---|---|---|
| `metagent_day1_v5` | Original main (B1 paper data work) | `metagent-v2-base-b1` @ `ed6243b` (frozen) |
| `metagent_day1_v5_investigation` | ConcordMet spike (5-PA wrapper exploration W3-W7) | `metagent-v2-base-investigation` @ `3ffe621` (frozen) |
| `metagent_v2` (this) | Post-merge integration + Stage 2 sprints W8 → W15, then W16+/Phase A on renamed branch `metagent-v3-benchmark` (see §5A) | HEAD `9a90d82` |

All new work goes in `metagent_v2`. The other two are reference only.

---

## §14 — Reference materials

| topic | location |
|---|---|
| Stage 1 architecture | `docs/ARCHITECTURE.md` |
| Stage 1 tool I/O contracts | `docs/TOOL_CONTRACTS.md` |
| Stage 2 grammar v2 spec | `docs/claim_grammar_v2.md` |
| Most recent Stage 2 close-out | `reports/agent/concord_w14_close_out.md` |
| Most recent UV attribution audit | `data/metagent/w15_uv_attribution/summary.md` |
| W10 D4.5 iter-2 H3 analysis | `data/concord/w10_d4_5_degradation_diagnostic/summary.md` |
| W11 UV 9-cat diagnostic | `reports/agent/concord_w11_uv_diagnosis.md` |
| B1 final eval (paper-grade) | `reports/agent/phase_b1_d5_v3_p0fix.md` |
| B1 P0 isolation analysis | `reports/agent/phase_b1_p0_isolation.md` |
| Merge prep doc (B1 ↔ Concord) | `reports/agent/merge_prep_b1_into_concord.md` |
| MetAgent-v2 merge status | `reports/agent/metagent_v2_merge_status.md` |
| LLM call cost source | `logs/llm_calls.jsonl` + per-sprint logs under `logs/concord/` |
| Memory files | `/home/weiwentao/.claude/projects/.../memory/` (8 feedback + 3 project + 1 reference) |
