# Track V: Verifier — designed against measured hallucinations

## Who you are — and why this version of the prompt differs from earlier drafts

You are building the first hallucination-control layer in the MetAgent system. A naive LLM orchestrator (Track O1) has already shipped — it wraps the deterministic pipeline's `IdentificationReport` with a bare MiniMax call and outputs whatever the model produces. The Track O1 delivery report (`reports/orchestrator_naive_v0_delivery_2026-04-23.md`) is required reading for this session and is your **primary design input**.

An earlier draft of this prompt (`track_V_verifier.md`) was written before O1 ran. That draft assumed imagined failure modes. **You are not that version.** You are designing against measured hallucinations observed on three real fixtures. Every design choice you make must trace to a specific observation in O1's delivery §5 (the eight H1–H8 notes) or §6 (the three-tier claim taxonomy).

If a design choice in this prompt does not trace to observed data, flag it to the maintainer during the understanding checkpoint. Do not carry imagined failure modes forward.

## Read before doing anything

In this order — the first two items are non-negotiable:

1. **`reports/orchestrator_naive_v0_delivery_2026-04-23.md`** — every section. Read §4 (three verbatim LLM outputs) and §5 (8 observations) twice. Annotate which observations your verifier must catch, which it must NOT trigger on, and which are out of scope.
2. **`logs/llm_calls.jsonl`** — open the three rows with trace_ids `o1-part4-glucose_pos`, `o1-part4-caffeine_pos`, `o1-part4-lcarnitine_pos`. Read `messages[1].content` (what the pipeline fed the LLM) side-by-side with `response_cleaned` (what the LLM wrote). Your verifier's job is to cross-check one against the other.
3. `docs/ARCHITECTURE.md` — the "every factual claim is verifiable" principle
4. `docs/LLM_INTEGRATION.md` — all of it
5. `common/llm_client.py` — note the logging hook O1 added (`caller`, `trace_id`). You will use both.
6. `schemas/report.py` — `IdentificationReport` and `CandidateReport` (your ground-truth source)
7. `orchestrator/` — understand the existing module so you DO NOT accidentally depend on it. Specifically: note `NaiveIdentification` schema (you consume something compatible), but do NOT import from `orchestrator.*`.
8. `docs/TOOL_CONTRACTS.md` sections 5, 6, 7 — you will call `fetch_metabolite_info`, `pathway_context`, `predict_spectrum`

Then report back in 7 bullets:

- Map each O1 observation (H1–H8) to {verifier catches / verifier tolerates / out of scope}. This is the crux of the design — get it right.
- Your definition of "claim" (atomic, decontextualized, has a designated verification method)
- The 4 verification layers you will implement and which O1 observations each targets
- Why you are NOT using a 5-stage cascade: the naive orchestrator already produced narrative, so your cascade is 4 stages, not 5
- Your proposed module layout under `verifier/`
- LLM call budget per verification (show the math, target < 10 calls per identification)
- How your `verify(...)` entry point relates to O1's `identify(...)` — specifically that verifier is a POST-step, not a wrapper; O1 code remains untouched

Wait for maintainer confirmation before writing any code.

## Hard scope boundaries — non-negotiable

You MAY:
- Create a new top-level package `verifier/`
- Create `tests/test_verifier/` for unit tests
- Create `tests/integration/test_verifier_e2e.py` for end-to-end (gated on MINIMAX_API_KEY)
- Create verifier-local prompts under `verifier/prompts/`
- Call existing tools by importing their main functions
- Call the LLM via `common.llm_client.chat()` with your own `caller` and `trace_id`

You MAY NOT:
- **Modify any file under `orchestrator/`.** Not even a comment. The naive orchestrator's output is a scientific baseline; editing it invalidates the ablation. The O1 delivery closed with: *"Nothing in this delivery was fixed. The wrong formulas stay wrong. The prompt stays bare. That is the contract."* You inherit that contract.
- Modify any file under `tools/`, `schemas/`, `common/`, `docs/`
- Modify existing tests under `tests/test_orchestrator/`, `tests/tool_tests/`, `tests/integration/test_*_e2e.py` (pre-existing ones only — you may CREATE `test_verifier_e2e.py`)
- Import from `orchestrator.*` in verifier code. The verifier is architecturally independent; it takes `(llm_output: str, source_report: IdentificationReport, trace_id: str)` — a naive orchestrator's `NaiveIdentification` is decomposable into these three by the caller. Verifier does NOT know the orchestrator exists.
- Retry the LLM call if its output is malformed. Log and surface as `VERIFICATION_PARSE_FAILED`. Retries mask the data your paper needs to report.
- Add "safety-by-prompt" tricks to any of your LLM prompts — no "do not hallucinate", no "only return verifiable facts". You are catching hallucinations deterministically; the extractor prompt should ONLY tell the LLM what JSON shape to produce.
- Call any LLM other than what `common.llm_client` is configured with.

## The signature — memorize this

```python
def verify(
    llm_output: str,
    source_report: IdentificationReport,
    *,
    trace_id: str,
) -> VerifiedIdentification:
    ...
```

This signature is how the verifier stays decoupled from the orchestrator. A caller that has already run naive orchestrator does:

```python
result = naive.identify(report)
verified = verify(
    llm_output=result.llm_output,
    source_report=report,
    trace_id=result.trace_id + "_verified",
)
```

A future orchestrator v2 with different output shape does the same pattern. Verifier has no coupling to either.

## Claim taxonomy — based on O1 observations, not speculation

A **claim** is one atomic factual statement extracted from `llm_output`. Every claim MUST carry a `claim_type` so it can be routed to the right verification layer. The four types are defined by what tool or data source verifies them:

### Type 1: `grounded_claim`
A claim whose ground truth appears in the `source_report` itself (i.e. in what the pipeline fed the LLM). Verification is a **lookup in source_report**, not a tool call.

O1 evidence:
- **H1 (glucose_pos):** LLM wrote "D-Gulose (C₇H₁₄O₇)" in a header. Source report says C₆H₁₂O₆ in its `metabolite_info.molecular_formula`. Verifier looks up `source_report.candidates[*].metabolite_info.molecular_formula` for D-Gulose and flags mismatch → `contradicted`.
- **H2 (caffeine_pos):** LLM claimed "<1 ppm vs HMDB reference". Source report emits `mass_match_indicator` as a binary (1.0 if within 5 ppm, else 0). The scalar "<1" is NOT in the source. → `unsupported`.

Verification: extract the field name the claim targets, compare against the corresponding field in `source_report`. If field doesn't exist in `source_report`, claim is `unsupported`. If field exists and matches, `supported`. If field exists and disagrees, `contradicted`.

**This is the highest-volume layer.** H1 and H2 are both Type 1. Do not skip it.

### Type 2: `factual_roundtrip_claim`
A claim about an external database entity (HMDB ID, KEGG ID, InChIKey, molecular formula of a named compound). Verification is a **re-query via `fetch_metabolite_info`** followed by field comparison.

O1 evidence:
- **H3, H4:** LLM faithfully reported pathway names ("galactose metabolism"), KEGG IDs ("map00232"). Verifier confirms these via tool round-trip. → `supported`.
- Future expected failure (not yet observed but designed for): LLM might claim a wrong primary name, formula, or InChIKey for a known ID.

Verification: parse the ID out of the claim, call `fetch_metabolite_info(identifier)`, check the claimed field value against the tool's return. Route mismatch to `contradicted`.

### Type 3: `biological_claim`
A claim about pathway membership, co-occurrence, or other network properties. Verification is a **re-query via `pathway_context`**, then membership check.

O1 evidence:
- **H3 (glucose_pos):** "galactose metabolism, galactosemia, Fabry disease pathways" — all three appear in the source's `pathway_context` response for D-Gulose. → `supported`.

Important limitation from Track D debt: `upstream_neighbours`/`downstream_neighbours` remain unreliable per P-2/P-3/P-4/P-6 of the D/E audit. If a Type 3 claim depends on neighbours, mark as `unverifiable_v0` rather than verifying it falsely. When those fixes land, expand Layer C.

### Type 4: `consistency_claim`
A claim whose contradiction with another claim in the same output is the failure mode. Verification is **pure LLM reasoning** across the full claim set.

O1 evidence:
- **H1 again (glucose_pos):** the SAME output writes "D-Gulose (C₇H₁₄O₇)" AND "Gulose maps to galactose metabolism" (referring implicitly to the hexose C₆H₁₂O₆ form). Intra-document contradiction.
- Worth noting: H1 fires on BOTH Type 1 (grounded contradicts source) and Type 4 (claim contradicts later claim in same output). Both layers should catch it independently. Redundancy here is a feature — when one layer misses, the other catches.

### Claims the verifier must NOT flag

O1 §5 observations that are **correct behavior**, not hallucination:
- **H5: Synonym drift** ("Isocaffeine" for "1,3,9-trimethylpurine-2,6-dione") — these are arguably the same molecule under chemistry naming conventions. Verifier's Type 2 must tolerate aliases. Acceptable strategy: when IDs match (same InChIKey or same canonical SMILES via RDKit), treat claim as `supported` even if names differ.
- **H6: Honest non-identification on L-carnitine** — LLM reported the pipeline's actual (wrong) top candidate and flagged low confidence. Verifier must not force L-carnitine into the output just because it's the fixture name. The verifier verifies what was said; it does not improve identification.
- **H7: "Chemically implausible" warning on silicon candidate** — LLM's chemistry knowledge here is correct. Not a hallucination. Type 3 and Type 4 must not reject this.
- **H8: 405 words instead of 400** — length-budget nit, not a truth issue. Out of scope.

## The 4-stage cascade — shorter than GeneAgent's because input is different

GeneAgent has Stages A (generate narrative) → B (extract claims) → C (verify) → D (rewrite) → E (re-extract+re-verify). Five stages.

Your cascade has only 4 stages, because naive orchestrator already produced the narrative. Stage A doesn't exist.

```
INPUT: llm_output (string, from naive orchestrator) + source_report (pipeline output)
    │
    ├─> Stage 1: Extract atomic claims from llm_output            [LLM call #1]
    │   Produces: list[ExtractedClaim]
    │
    ├─> Stage 2: Classify each claim into {grounded, factual, biological, consistency}
    │   Produces: list[ClassifiedClaim]
    │   Implementation: deterministic (pattern match + schema) + 1 LLM call for
    │   ambiguous cases  [LLM call #2, optional]
    │
    ├─> Stage 3: Verify each claim — deterministic routing to tools / source lookups
    │   Produces: list[VerifiedClaim] with verdict in {supported, contradicted,
    │   unsupported, unverifiable_v0, error}
    │   NO LLM calls in this stage except for Type 4 consistency checks   [LLM call #3]
    │
    ├─> Stage 4: Rewrite llm_output keeping only supported claims, dropping/correcting 
    │   the rest. Then re-extract and re-verify on the rewritten output.  [LLM calls #4, #5]
    │
OUTPUT: VerifiedIdentification
```

**Why 4 stages and not 3:** Stage 4's re-extract+re-verify is GeneAgent's key innovation — rewriting introduces new claims, which are themselves subject to verification. This is the "polishing hallucination" catch. Do not omit Stage 4.

**Budget:** 5 LLM calls max per verification (extract, classify-ambiguous, consistency-check, rewrite, re-extract). At ~$0.03 per call for MiniMax-M2.7 on these prompt sizes, ~$0.15 per identification. Within target.

## Output schema

```python
class ClaimVerdict(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE_V0 = "unverifiable_v0"  # known limitation, not a judgment
    ERROR = "error"  # verification failed (tool error, etc)


class ClaimType(str, Enum):
    GROUNDED = "grounded_claim"
    FACTUAL = "factual_roundtrip_claim"
    BIOLOGICAL = "biological_claim"
    CONSISTENCY = "consistency_claim"


class VerifiedClaim(BaseModel):
    claim_text: str                      # the atomic statement
    claim_type: ClaimType
    verdict: ClaimVerdict
    evidence: str                         # what was checked and how
    source_field: str | None = None       # e.g. "candidates[0].metabolite_info.molecular_formula"
    correction: str | None = None         # for contradicted claims, the correct value per ground truth


class VerifiedIdentification(BaseModel):
    trace_id: str
    source_llm_output: str                # the ORIGINAL naive output, untouched
    rewritten_output: str                 # Stage 4 output; may equal source_llm_output if nothing changed
    claims_v1: list[VerifiedClaim]        # claims from source_llm_output after Stage 3
    claims_v2: list[VerifiedClaim]        # claims from rewritten_output after Stage 4
    overall_verdict: Literal[
        "verified",             # all claims supported
        "partially_verified",   # some unsupported or unverifiable_v0, no contradictions  
        "contradicted",         # at least one contradiction caught
        "failed",               # extraction or verification could not complete
    ]
    verification_warnings: list[str]
    llm_call_count: int                   # actual count for budget tracking
    generated_at: datetime
```

Keep `source_llm_output` verbatim. The audit trail depends on it.

## Module layout

```
verifier/
├── __init__.py
├── agent.py                 # top-level verify() entry point
├── schemas.py               # the types above
├── claim_extractor.py       # Stage 1: LLM-driven claim extraction
├── claim_classifier.py      # Stage 2: rule-based + 1 LLM fallback
├── layers/
│   ├── __init__.py
│   ├── grounded.py          # Type 1 verification via source_report lookup
│   ├── factual.py           # Type 2 verification via fetch_metabolite_info
│   ├── biological.py        # Type 3 verification via pathway_context
│   └── consistency.py       # Type 4 verification via LLM
├── rewriter.py              # Stage 4: rewrite + re-extract + re-verify
├── source_lookup.py         # helper: navigate source_report by field path
└── prompts/
    ├── extract_claims.py    # Stage 1 prompt template
    ├── classify_ambiguous.py # Stage 2 fallback prompt (small, rare)
    ├── check_consistency.py  # Stage 3 Type 4 prompt
    └── rewrite_verified.py   # Stage 4 prompt

tests/test_verifier/
├── test_claim_extractor.py
├── test_source_lookup.py
├── test_layer_grounded.py
├── test_layer_factual.py
├── test_layer_biological.py
├── test_layer_consistency.py
├── test_rewriter.py
├── test_agent_cascade.py
└── test_agent_real_o1_outputs.py    # THIS IS THE HARDEST AND MOST IMPORTANT TEST FILE

tests/integration/test_verifier_e2e.py
```

## Testing strategy — anchored on real O1 outputs

Your test suite must include a file called `test_agent_real_o1_outputs.py` that hardcodes the three O1 verbatim outputs from the delivery §4. For each:

### Glucose fixture (`o1-part4-glucose_pos`)

Required catches:
- `test_glucose_catches_H1_D_gulose_formula_contradiction`: Stage 3 Type 1 (grounded) MUST flag "D-Gulose (C₇H₁₄O₇)" as `contradicted`, with `correction="C₆H₁₂O₆"`, `source_field` pointing to the relevant `metabolite_info.molecular_formula`.
- `test_glucose_catches_H1_intra_document_inconsistency`: Stage 3 Type 4 (consistency) independently catches the same contradiction (header says C₇H₁₄O₇, body says C₆H₁₂O₆).
- `test_glucose_does_not_flag_H3_pathway_names`: "galactose metabolism", "galactosemia", "Fabry disease pathways" all MUST be `supported` via Stage 3 Type 3. If any returns `contradicted` or `unsupported`, pathway-lookup logic is broken.

### Caffeine fixture (`o1-part4-caffeine_pos`)

Required catches:
- `test_caffeine_catches_H2_ppm_hallucination`: "The mass accuracy is excellent (<1 ppm vs. HMDB reference)" MUST be flagged `unsupported` (the pipeline's `mass_match_indicator` is binary; no ppm scalar is in source).
- `test_caffeine_does_not_flag_H4_kegg_id_passthrough`: "KEGG (map00232)" MUST be `supported`.
- `test_caffeine_tolerates_H5_synonym_drift`: "Isocaffeine" claim MUST NOT be flagged `contradicted` just because the pipeline used "1,3,9-trimethylpurine-2,6-dione". Acceptable outcomes: `supported` (same InChIKey/SMILES after canonicalization) or `unverifiable_v0` (cannot resolve aliasing). NOT `contradicted`.

### L-carnitine fixture (`o1-part4-lcarnitine_pos`)

Required catches:
- `test_lcarnitine_respects_H6_honest_non_identification`: verifier MUST NOT inject L-carnitine as "the real answer". LLM correctly reported the pipeline's top candidate (2-[2-hydroxyethyl(methyl)amino]ethyl acetate). The verifier verifies what was said, not what "should have been said".
- `test_lcarnitine_does_not_flag_H7_silicon_warning`: LLM's statement that the silicon-containing candidate is "chemically implausible for most biological matrices" is correct chemistry. Do not flag.

### Overall cascade tests

- `test_cascade_llm_call_count_under_5`: hit the three fixtures with mocked LLM responses; confirm actual LLM call count ≤ 5 per fixture.
- `test_cascade_llm_call_count_under_3_when_no_ambiguity`: when Stage 2 classification is rule-based-only (no LLM fallback), total calls drop to 3.
- `test_rewriter_preserves_supported_claims`: give the rewriter an output where all claims are supported; rewritten text should preserve all key facts (InChIKey-level equivalence at minimum).
- `test_rewriter_removes_contradicted_claims`: output with H1 contradiction → rewritten version does not contain C₇H₁₄O₇.

### Mock strategy

Every unit test uses `common.llm_client.set_mock(...)` to feed deterministic responses. NEVER hit MiniMax in unit tests.

For `test_agent_real_o1_outputs.py`: the extraction of claims from real O1 outputs needs a LLM, but you can pre-compute "expected extracted claims" for each of the three outputs (hand-curate from delivery §5) and mock the extractor to return them. This tests the rest of the cascade without requiring live LLM access to reproduce identical extraction every time.

### Integration test (`tests/integration/test_verifier_e2e.py`)

- `@pytest.mark.requires_minimax_key`: skip if no key
- `test_verify_glucose_end_to_end_real_llm`: runs actual verify() on the cached glucose O1 output using real MiniMax for claim extraction. Asserts: extraction completes, overall_verdict in {"contradicted", "partially_verified"}, H1 contradiction caught.
- Run this test exactly once as acceptance; budget ~$0.05.

## Handling the O1 log join

Your `VerifiedIdentification.trace_id` SHOULD be derivable from the orchestrator's. Convention: `trace_id = orchestrator_trace_id + "_verified"`. This lets someone grep `logs/llm_calls.jsonl` for both halves.

Your verifier's LLM calls also hit `logs/llm_calls.jsonl`. Use `caller="verifier.<stage>.<function>"` — e.g. `verifier.stage1.extract_claims`, `verifier.stage4.rewrite_verified`. This lets downstream evaluation filter verifier calls separately from orchestrator calls.

## Deliverables

- `verifier/` package with everything specified in Module Layout
- `tests/test_verifier/` full suite passing on mocks
- `tests/test_verifier/test_agent_real_o1_outputs.py` — the specific real-fixture tests listed above
- `tests/integration/test_verifier_e2e.py` — gated real-LLM test
- `reports/verifier_v0_delivery_<date>.md`, ~2 pages:
  - Design summary: the 4 claim types + cascade, citing specific O1 observations
  - Verification results on the 3 O1 outputs (per-claim verdict table, verbatim from your test runs)
  - Measured LLM call count per fixture (actual, not theoretical)
  - The rewritten_output for each fixture (verbatim) — so the maintainer can compare original vs. verified
  - Known limitations: literature verification not done (Track F descoped); neighbour-based claims marked unverifiable_v0 pending P-2/3/4/6 fixes; small data set (3 fixtures, 13 distinct claims) is acknowledged seed, not statistical sample
  - Handoff notes for the next evaluation session: how to expand to 20-30 fixtures, which failure modes are over-represented in the current seed, what to watch for as the sample grows

## Exit criteria

- All 4 cascade stages implemented and unit-tested
- `pytest tests/test_verifier/ -v` — all passing with mocks
- `test_agent_real_o1_outputs.py` — all named real-data tests passing as specified
- `pytest tests/integration/test_verifier_e2e.py -v` — passes with MINIMAX_API_KEY set, skips without
- No modifications to `orchestrator/`, `tools/`, `schemas/`, `common/`, `docs/`
- `logs/llm_calls.jsonl` shows verifier-caller rows after a test run, joinable to orchestrator rows by trace_id convention
- Delivery writeup includes the actual rewritten outputs for all 3 O1 fixtures
- Measured LLM call count per verification ≤ 5

## If things go sideways

- **If the claim extractor produces wildly inconsistent claims across runs** (even with temperature=0): add a JSON-shape requirement in the prompt. Reject non-conforming outputs as `VERIFICATION_PARSE_FAILED` — do NOT retry. The failure mode is data for the paper.
- **If O1's L-carnitine output leads the verifier to "correct" it into L-carnitine**: your layer logic is wrong. You verify what was said, not what should have been said. Revisit Type 3 and Type 4 logic.
- **If synonym drift (H5) keeps being flagged as contradiction**: your Type 2 aliasing is too strict. Canonicalize via RDKit SMILES or InChIKey first, then compare. If even that fails, fallback to `unverifiable_v0` — never hard-reject on name difference alone.
- **If LLM call count exceeds 5 per verification**: profile. Common culprit is Stage 2 ambiguous-classification calling the LLM for every claim. Rule-based classification should handle 80%+ of claims; LLM fallback is rare. If LLM fallback fires for every claim, the rules are wrong.
- **If you need to modify orchestrator code to make verifier work**: you don't. Verifier takes `(llm_output, source_report, trace_id)` — three values any caller can produce. If your design requires an orchestrator change, the design is wrong.
- **If the 3-fixture seed data set feels too small to confidently design against**: you're correct, it is. The delivery writeup acknowledges this; the next evaluation session will expand. Your job is to design well against what's measurable today, not wait for perfect data.

## First action

Read the eight items under "Read before doing anything" — the first two are mandatory and everything depends on how carefully you read them. Then produce your 7-bullet understanding. 

Your first commit should be `verifier/schemas.py` (the types in this prompt). Review those with the maintainer before implementing any logic. Every other file depends on these types.