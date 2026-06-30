# Track AV — Automated Verification Layers (Layer 1-3)

**Session ID:** track_AV_auto_layers
**Branch:** feature/auto-verification-layers
**Estimated work:** 2 days

## Who you are

You are implementing the automated portion of the verifier's evidence
collection. The verifier itself already exists with cascade structure
(extract → classify → verify → rewrite → re-extract). Your job is to
build three automated checkers that the `verify` stage will call to
reduce manual annotation burden.

These checkers handle Type 5 (peak-mechanistic) claims. They do NOT
replace the existing verifier — they slot into it as deterministic
sub-modules.

## Hard scope boundaries

**You MAY:**
- Create new files under `verifier/auto_layers/`
- Add tests under `tests/verifier/auto_layers/`
- Add CLI wrapper under `scripts/run_auto_verification.py`
- Read existing verifier schemas

**You MAY NOT:**
- Modify existing verifier cascade logic
- Modify any tool implementations (sirius/, cfm_id/, etc.)
- Modify schemas for IdentificationReport or VerifiedIdentification
- Add new dependencies without checking with maintainer first

## Background reading (mandatory first action)

Before writing any code, read these files and confirm understanding:

1. `verifier/schemas.py` — see VerifiedClaim, claim_type taxonomy
2. `verifier/agent.py` — see how verify stage is currently structured
3. `tools/sirius/tool.py` — see SIRIUS output format (fragmentation tree)
4. `tools/spectrum_predict/tool.py` — see CFM-ID output format
5. `reports/orchestrator_naive_v0_delivery_2026-04-23.md` §5 — see the
   8 hallucination patterns (H1-H8) we observed

Confirm in your first response:
- The 5 claim types (Type 1-5) and what each verifies
- Why Type 5 needs three sub-layers (you'll explain below)
- Which existing tools you'll call and what their outputs contain

## Three layers to implement

### Layer 1: Arithmetic consistency checker

**Purpose:** catch hallucinations where LLM cites m/z values that
don't exist in source spectrum, or makes arithmetic claims that
don't hold.

**Implementation:** `verifier/auto_layers/arithmetic_checker.py`

Functions:
- `check_mz_existence(claimed_mz: float, source_spectrum: Spectrum,
                      tolerance_ppm: float = 5.0) -> bool`
- `check_neutral_loss_arithmetic(precursor_mz: float, fragment_mz: float,
                                  claimed_loss_formula: str) -> CheckResult`
  - Uses RDKit to compute claimed loss formula's exact mass
  - Compares precursor - fragment = claimed_loss within tolerance
- `check_loss_formula_validity(loss_formula: str) -> bool`
  - Verifies the loss formula is chemically possible (no negative atoms etc.)

**Tests:** for each function, at least 3 test cases:
- Valid case (passes)
- Invalid case (fails correctly)
- Edge case (very small mass, isotope, ambiguous)

### Layer 2: Tool cross-validation

**Purpose:** verify LLM's peak-level claims against SIRIUS fragmentation
tree and CFM-ID predicted spectrum.

**Implementation:** `verifier/auto_layers/tool_cross_validator.py`

Functions:
- `verify_against_sirius(claim: PeakClaim, sirius_tree: FragmentationTree)
                         -> VerificationResult`
  - Look up claimed m/z in SIRIUS tree
  - Compare claimed neutral loss with SIRIUS-annotated edge
  - Return (matched, partial_match, no_match) with explanation
- `verify_against_cfmid(claim: PeakClaim, cfmid_spectrum: PredictedSpectrum,
                        tolerance_ppm: float = 5.0) -> VerificationResult`
  - Check if claimed peak appears in predicted spectrum
  - Score by intensity rank (high-intensity match = strong support)
- `compute_tool_consensus(sirius_result: VerificationResult,
                         cfmid_result: VerificationResult) -> ConsensusResult`
  - Three states: both agree (high confidence), one agrees (medium),
    both disagree (low / contradicted)

**Critical design note:** When SIRIUS and CFM-ID disagree, do NOT
arbitrate. Mark as "tools_disagree" — this case is escalated to
human annotation. Document this clearly in the function's docstring.

**Tests:**
- Mock SIRIUS/CFM-ID outputs (don't actually call them, use fixtures)
- Test agreement, disagreement, missing peaks, edge cases

### Layer 3: Mechanistic claim flagging

**Purpose:** identify LLM claims that involve fragmentation mechanisms
(retro-Diels-Alder, McLafferty rearrangement, alpha cleavage, etc.)
which CANNOT be auto-verified and must be flagged for human review.

**Implementation:** `verifier/auto_layers/mechanistic_flagger.py`

Functions:
- `flag_mechanistic_claims(claim_text: str) -> list[MechanismFlag]`
  - Use a curated keyword/regex list to detect mechanism mentions
  - Return list of flags with span (which part of text triggered)
  - Confidence levels: high (clear mechanism term), medium (ambiguous),
    low (might just be descriptive)

**Keyword list (starter set, you can expand):**
```python
HIGH_CONFIDENCE_MECHANISMS = [
    r'\bretro[\s-]?Diels[\s-]?Alder\b',
    r'\bMcLafferty\s+rearrangement\b',
    r'\balpha[\s-]?cleavage\b',
    r'\binductive\s+cleavage\b',
    r'\bretro[\s-]?ene\b',
    r'\bcharge[\s-]?driven\s+fragmentation\b',
    r'\bonium\s+(?:reaction|process)\b',
]

MEDIUM_CONFIDENCE_MECHANISMS = [
    r'\bring\s+opening\b',
    r'\brearrangement\b',
    r'\bhomolytic\s+cleavage\b',
    r'\bheterolytic\s+cleavage\b',
    r'\bproton\s+transfer\b',
]
```

**Tests:**
- Each keyword pattern has at least one test
- Negative test (text without mechanism doesn't trigger)
- Edge case (mechanism term used in non-mechanistic context)

## Integration point with existing verifier

After implementing the three layers, add ONE function in
`verifier/auto_layers/__init__.py`:

```python
def auto_verify_type5_claim(
    claim: VerifiedClaim,
    source_report: IdentificationReport,
    sirius_output: dict | None = None,
    cfmid_output: dict | None = None,
) -> AutoVerificationResult:
    """
    Run Layer 1-3 on a single Type 5 claim.
    
    Returns:
        - verdict: 'auto_verified' | 'auto_contradicted' | 
                   'needs_human_review'
        - confidence: float 0-1
        - evidence: structured dict explaining why
        - layer_results: outputs from all 3 layers
    """
```

This is the ONLY function the existing verifier needs to call.
Do NOT modify verifier/agent.py to call it — that wiring will be
done in a separate session.

## Required deliverables

1. **Three implementation files** under `verifier/auto_layers/`
2. **Tests for each layer** under `tests/verifier/auto_layers/`
3. **CLI script** `scripts/run_auto_verification.py` that takes a
   trace_id and runs auto verification on all Type 5 claims for that
   trace, outputting a JSON report
4. **Coverage report** — run on the existing 3 fixtures (glucose,
   caffeine, L-carnitine) and report:
   - How many Type 5 claims were extracted
   - How many were auto-verified by each layer
   - How many need human review (escalation rate)
5. **Delivery report** at `reports/track_AV_auto_layers_<date>.md`
   following the same structure as previous track delivery reports

## Quality bar

- All tests must pass
- Coverage report must show ≥ 50% auto-verification rate on real
  fixtures (if lower, document why)
- No modifications to existing verifier code
- Auto-verification must be deterministic (no LLM calls in these layers)

## Time budget

2 days. If you need more, escalate after day 1 with a concrete reason.

## First action checklist

In your first response, do all of:

1. Confirm you've read the 5 background files
2. State the 5 claim types and what each verifies
3. Explain why Type 5 specifically needs 3 sub-layers (not 1)
4. List the 4 existing tools/files you'll call and their I/O
5. Describe the integration point you'll create
6. Ask any clarifying questions

Do NOT start writing code until I confirm your understanding.