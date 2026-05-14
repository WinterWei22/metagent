# Verifier wiring session: integrate SIRIUS (T1) and ClassyFire (T2)

## Who you are

You are updating the verifier(/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/reports/ui_v1_verifier_delivery_2026-04-24.md) to use two newly delivered tools:
- `tools/sirius/` (Track T1) — fragmentation tree annotation(/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/reports/sirius_tool_delivery_2026-04-27.md)
- `tools/classyfire/` (Track T2) — chemical class classification(/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/reports/classyfire_tool_delivery_2026-04-27.md)

Both tools are complete and tested. Your job is to wire them into the
existing verifier claim-verification layers. The verifier's cascade
structure (4 stages), schemas, and existing tests do NOT change.

This is a surgical wiring task. Estimated code changes: ~150 lines across
3 files. If you find yourself writing more than 300 lines, stop and check
with the maintainer.

## Read before doing anything

1. `verifier/schemas.py` — especially `ClaimType` enum and `VerifiedClaim`
2. `verifier/layers/factual.py` — Type 2 verification (you extend this)
3. `verifier/agent.py` — understand the cascade; confirm you won't change it
4. `tools/sirius/schemas.py` and `tools/sirius/tool.py` — the interface
   you consume for Type 5
5. `tools/classyfire/schemas.py` and `tools/classyfire/tool.py` — the
   interface you consume for Type 2 extension
6. `tools/classyfire/tool_description.md` — specifically the
   `ClassyfireNotFoundError → UNVERIFIABLE_V0` rule
7. `reports/orchestrator_naive_v0_delivery_2026-04-23.md` §5 — the 8
   observed hallucination types; H1/H2 are Type 1, H3/H4 are Type 2,
   Type 5 (peak-level) was NOT observed in the 3-fixture naive run
   because the fixtures had too few peaks

Then state back in 5 bullets:
- Which files you will create (should be exactly 2 new files)
- Which files you will modify (should be exactly 3 existing files)
- How Type 5 lookup works end-to-end (claim → SIRIUS call → verdict)
- How Type 2 ClassyFire extension works (when does it trigger vs the
  existing fetch_metabolite_info path?)
- Your test plan for the new code paths

Wait for confirmation before writing any code.

## Hard scope boundaries

You MAY:
- Create `verifier/layers/peak_mechanistic.py` (new)
- Create `tests/test_verifier/test_layer_peak_mechanistic.py` (new)
- Modify `verifier/layers/factual.py` (add ClassyFire branch)
- Modify `verifier/claim_classifier.py` (add Type 5 classification rules)
- Modify `tests/test_verifier/test_layer_factual.py` (add ClassyFire tests)

You MAY NOT:
- Modify `verifier/schemas.py` — if you need a new field, discuss first
- Modify `verifier/agent.py` or `verifier/claim_extractor.py`
- Modify `verifier/rewriter.py`
- Modify anything under `tools/sirius/` or `tools/classyfire/`
- Modify `schemas/`, `common/`, `docs/`
- Change any existing passing test

## Part 1: Type 5 — peak_mechanistic_claim verification

### What Type 5 claims look like

From LLM outputs, Type 5 claims sound like:
- "The peak at m/z 163.06 corresponds to [M+H-H₂O]⁺, a water-loss fragment"
- "m/z 138.07 is the imidazole ring fragment of caffeine"
- "The base peak at m/z 184.07 arises from loss of trimethylamine (59 Da)"
- "Fragment at 175.07 corresponds to lactone ring cleavage"

These claims have THREE extractable components:
1. **mz_value**: the m/z being claimed (float)
2. **fragment_description**: what the LLM says it is (string)
3. **neutral_loss**: the claimed neutral loss, if stated (string or None)

The claim extractor (Stage 1) already runs before verification; it must
tag these as `ClaimType.PEAK_MECHANISTIC` and populate a
`peak_mz` field on `ExtractedClaim`. Check whether `ExtractedClaim` in
`verifier/schemas.py` already has this field; if not, propose adding it
at the understanding checkpoint.

### Verification logic in `peak_mechanistic.py`

```python
def verify_peak_mechanistic(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
) -> VerifiedClaim:
    """
    Three-step verification for peak-level mechanistic claims.
    Uses SIRIUS fragmentation tree as ground truth.
    """

    # Step 1: Does the claimed peak exist in the experimental spectrum?
    mz = claim.peak_mz
    spectrum = source_report.experimental_spectrum
    peak_exists = any(
        abs(obs_mz - mz) / mz * 1e6 <= 5.0
        for obs_mz in spectrum.mz
    )
    if not peak_exists:
        return VerifiedClaim(
            claim_text=claim.claim_text,
            claim_type=ClaimType.PEAK_MECHANISTIC,
            verdict=ClaimVerdict.CONTRADICTED,
            evidence=f"Peak at m/z {mz:.4f} not found in experimental "
                     f"spectrum (5 ppm tolerance). Spectrum has "
                     f"{len(spectrum.mz)} peaks.",
        )

    # Step 2: Does SIRIUS place a fragment there?
    top_candidate = _get_top_candidate(source_report)
    if top_candidate is None:
        return VerifiedClaim(..., verdict=ClaimVerdict.UNVERIFIABLE_V0,
                             evidence="No candidate with SMILES available")

    try:
        sirius_resp = sirius_annotate(SiriusAnnotateRequest(
            spectrum=source_report.experimental_spectrum
        ))
    except SiriusNotInstalledError:
        return VerifiedClaim(..., verdict=ClaimVerdict.UNVERIFIABLE_V0,
                             evidence="SIRIUS not available in this environment")
    except SiriusNoFormulaError:
        return VerifiedClaim(..., verdict=ClaimVerdict.UNVERIFIABLE_V0,
                             evidence="SIRIUS could not assign a formula "
                                      "(spectrum too noisy or too few peaks)")

    annotation = sirius_resp.lookup_fragment(mz=mz, tolerance_ppm=5.0)

    if annotation is None:
        return VerifiedClaim(
            ...,
            verdict=ClaimVerdict.UNSUPPORTED,
            evidence=f"SIRIUS fragmentation tree has no fragment at "
                     f"m/z {mz:.4f} ± 5 ppm. Tree has "
                     f"{sirius_resp.tree_node_count} nodes.",
        )

    # Step 3: Does the claimed neutral loss match SIRIUS?
    if claim.neutral_loss is not None:
        nl_match = _neutral_loss_matches(
            claimed=claim.neutral_loss,
            sirius_nl=annotation.neutral_loss_formula,
        )
        if not nl_match:
            return VerifiedClaim(
                ...,
                verdict=ClaimVerdict.CONTRADICTED,
                evidence=f"SIRIUS assigns neutral loss "
                         f"'{annotation.neutral_loss_formula}' at this m/z, "
                         f"but LLM claimed '{claim.neutral_loss}'.",
                correction=annotation.neutral_loss_formula,
            )

    return VerifiedClaim(
        ...,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=f"SIRIUS confirms fragment at m/z {mz:.4f} "
                 f"(formula {annotation.formula}, "
                 f"neutral loss {annotation.neutral_loss_formula}).",
        source_field="experimental_spectrum + sirius_fragmentation_tree",
    )
```

Implement `_neutral_loss_matches` with tolerance for naming variants:
"H2O" == "H₂O" == "water" == "18.01" (within 0.02 Da mass tolerance).
Use a small lookup table for common neutral losses rather than parsing
arbitrary chemistry.

### Common neutral losses lookup table

Put this in `peak_mechanistic.py` as a module-level constant:

```python
COMMON_NEUTRAL_LOSSES = {
    # formula: (mass_da, common_names)
    "H2O":   (18.0106, ["h2o", "water", "h₂o"]),
    "NH3":   (17.0265, ["nh3", "ammonia"]),
    "CO":    (27.9949, ["co", "carbon monoxide"]),
    "CO2":   (43.9898, ["co2", "carbon dioxide", "co₂"]),
    "CH2O2": (46.0055, ["formic acid", "hcooh"]),
    "C2H4O": (44.0262, ["acetaldehyde"]),
    "C2H2O": (42.0106, ["ketene"]),
    "HPO3":  (79.9663, ["metaphosphoric acid", "hpo3"]),
    "H3PO4": (97.9769, ["phosphoric acid"]),
    "CH3":   (15.0235, ["methyl", "ch3"]),
    "C2H4":  (28.0313, ["ethylene", "c2h4"]),
    "HF":    (20.0062, ["hf", "hydrogen fluoride"]),
    "HCl":   (35.9767, ["hcl", "hydrogen chloride"]),
    "SO3":   (79.9568, ["so3", "sulfur trioxide"]),
    "C5H8O4": (132.0423, ["glutaric acid"]),
    # add more as needed from MSAgent case studies
}
```

## Part 2: Type 2 extension — ClassyFire chemical class claims

### When to use ClassyFire vs fetch_metabolite_info

The existing Type 2 verifier in `factual.py` handles claims like:
- "HMDB0000122 is glucose" → `fetch_metabolite_info`
- "L-carnitine has formula C7H16NO3" → `fetch_metabolite_info`

ClassyFire handles a **different sub-type** of factual claim:
- "caffeine is a purine alkaloid" → ClassyFire
- "glucose is a hexose monosaccharide" → ClassyFire
- "L-carnitine belongs to the amino acid class" → ClassyFire

These are **chemical taxonomy claims**, not database ID claims.

Add a `claim_subtype` field to `ClassifiedClaim` (or use the existing
`claim_text` pattern-matching approach — discuss at checkpoint) to
distinguish taxonomy claims from ID/formula claims.

### ClassyFire verification logic in `factual.py`

Add a new branch after the existing `fetch_metabolite_info` block:

```python
elif is_chemical_class_claim(claim):
    # Get SMILES from source_report candidates
    smiles = _get_smiles_for_claim(claim, source_report)
    if smiles is None:
        return VerifiedClaim(..., verdict=ClaimVerdict.UNVERIFIABLE_V0,
                             evidence="No SMILES available for ClassyFire lookup")
    try:
        resp = classify_structure(ClassifyStructureRequest(smiles=smiles))
        claimed_class = _extract_class_from_claim(claim.claim_text)
        if resp.matches_claim(claimed_class):
            return VerifiedClaim(..., verdict=ClaimVerdict.SUPPORTED,
                                 evidence=f"ClassyFire confirms: "
                                          f"{resp.direct_parent.name if resp.direct_parent else 'classified'} "
                                          f"(source: {resp.source})")
        else:
            return VerifiedClaim(
                ...,
                verdict=ClaimVerdict.CONTRADICTED,
                evidence=f"ClassyFire classifies this compound as "
                         f"'{resp.direct_parent.name if resp.direct_parent else 'unknown'}', "
                         f"not '{claimed_class}'.",
                correction=resp.direct_parent.name if resp.direct_parent else None,
            )
    except ClassyfireNotFoundError:
        return VerifiedClaim(..., verdict=ClaimVerdict.UNVERIFIABLE_V0,
                             evidence="Compound not in ClassyFire database "
                                      "(novel or rare compound)")
```

### `is_chemical_class_claim` heuristic

A claim is a chemical class claim if its text contains phrases like:
- "is a [X] compound/class/type"
- "belongs to [X]"
- "classified as [X]"
- "[compound] is [X]" where X matches known chemical taxonomy vocabulary
  (alkaloid, flavonoid, terpene, lipid, amino acid, monosaccharide,
  nucleoside, steroid, polyketide, etc.)

Maintain a short vocabulary list in `factual.py`. If not confident it's
a class claim, default to the existing `fetch_metabolite_info` path.

## Part 3: Claim classifier update

In `verifier/claim_classifier.py`, add Type 5 classification rules.
Type 5 is the easiest to pattern-match because peak-level claims almost
always contain:
- A numeric m/z value (regex: `m/z\s+[\d.]+`)
- Fragment terminology: "fragment", "loss", "ion", "peak at"

Add to the rule-based classifier:

```python
PEAK_MECHANISTIC_PATTERNS = [
    r"m/z\s+[\d.]+",           # "peak at m/z 163.06"
    r"neutral loss of",         # "neutral loss of H2O"
    r"\[M[+-]H[^\]]*\]",       # "[M+H-H2O]+"
    r"fragment(?:ation)?\s+at", # "fragmentation at m/z"
    r"loss of \w+",             # "loss of water"
    r"ring cleavage",
    r"bond scission",
]
```

If ≥1 pattern matches AND a float m/z is extractable → Type 5.

## Tests

### `test_layer_peak_mechanistic.py`

All tests use MockSiriusRunner from `tests/fixtures/sirius_outputs/`.

1. **`test_peak_exists_in_spectrum_supported`**: glucose spectrum, SIRIUS
   confirms fragment at 163.06 → SUPPORTED
2. **`test_peak_not_in_spectrum_contradicted`**: claim says m/z 999.99 →
   CONTRADICTED (peak not in spectrum, checked before SIRIUS call)
3. **`test_sirius_no_fragment_at_mz_unsupported`**: peak exists in
   spectrum but not in SIRIUS tree → UNSUPPORTED
4. **`test_neutral_loss_mismatch_contradicted`**: SIRIUS says H2O loss,
   LLM claims NH3 loss → CONTRADICTED with correction
5. **`test_neutral_loss_alias_match`**: LLM says "water loss", SIRIUS
   says "H2O" → SUPPORTED (alias match)
6. **`test_sirius_not_installed_unverifiable`**: mock `SiriusNotInstalledError`
   → UNVERIFIABLE_V0 (not a crash)
7. **`test_too_few_peaks_unverifiable`**: spectrum with 3 peaks → SIRIUS
   raises `SiriusNoFormulaError` → UNVERIFIABLE_V0

### `test_layer_factual.py` additions

8. **`test_caffeine_is_purine_supported`**: mock ClassyFire returns
   caffeine as Xanthine (under Purines); `claim = "caffeine is a purine"`
   → SUPPORTED
9. **`test_glucose_is_amino_acid_contradicted`**: mock ClassyFire returns
   glucose as Hexose; `claim = "glucose is an amino acid"` → CONTRADICTED
10. **`test_classyfire_not_found_unverifiable`**: mock raises
    `ClassyfireNotFoundError` → UNVERIFIABLE_V0

## Deliverables

- `verifier/layers/peak_mechanistic.py`
- `tests/test_verifier/test_layer_peak_mechanistic.py`
- Modified `verifier/layers/factual.py` (ClassyFire branch)
- Modified `verifier/claim_classifier.py` (Type 5 patterns)
- Modified `tests/test_verifier/test_layer_factual.py` (3 new tests)
- `reports/verifier_t1t2_wiring_<date>.md` (~1 page):
  - What was wired and how
  - Test counts before/after
  - Known limitations (sparse spectra → Type 5 mostly UNVERIFIABLE_V0;
    ClassyFire not found for novel compounds)
  - One concrete example: what happens to the caffeine O1 output now
    that ClassyFire is wired in

## Exit criteria

- `pytest tests/test_verifier/ -v` — all tests pass including new ones
- `pytest` whole repo — nothing broken
- No modifications outside the 5 files listed in Deliverables
- The delivery report shows at least one Type 5 claim going through the
  full verification path (even if result is UNVERIFIABLE_V0 due to
  sparse fixture)

## First action

Read the 7 items above, then answer these specific questions in your
5-bullet understanding:

1. Does `verifier/schemas.py` currently have a `peak_mz` field on
   `ExtractedClaim`? If not, what is the minimal addition needed?
2. Does `verifier/claim_classifier.py` currently have a
   `ClaimType.PEAK_MECHANISTIC` branch? If not, where exactly does it go?
3. After this wiring, how many total LLM calls does one verification
   consume on average? (Budget check: must stay ≤ 5)
4. Confirm: `SiriusNotInstalledError` and `ClassyfireNotFoundError` both
   → `UNVERIFIABLE_V0`, NOT a pipeline crash
5. What is the expected Type 5 verdict distribution on the current 3
   sparse fixtures (glucose/caffeine/L-carnitine)? Should be mostly
   UNVERIFIABLE_V0 because those fixtures have 5-7 peaks, insufficient
   for SIRIUS to build meaningful trees. Is this correct?