# Track C: `molecule_generate`

**Prerequisite:** read `prompts/_preamble.md` first.

## Your scope

You own exactly one tool: **`molecule_generate`**. Directory: `tools/molecule_gen/`.

This tool produces de novo candidate structures (SMILES) from a spectrum when library_search either fails or produces low-confidence matches. It wraps an in-house generative model.

## CRITICAL FIRST ACTION — ask the maintainer

Your tool wraps an in-house generation model. Before you write any code, you MUST ask the maintainer:

1. **Where is the in-house generation model code?** (path or git URL)
2. **What's the entry point?** (module path, class name, function signature for single-inference)
3. **What does the model take as input?** (spectrum? formula? both? any embedding?)
4. **What does it output?** (SMILES list? SMILES + logit? tokens?)
5. **How does it handle the formula constraint?** (hard? soft? ignored?)
6. **What's the typical n_candidates range it's been tuned for?**
7. **Is there a recommended decoding strategy?** (beam search, temperature sampling, etc.)

Do NOT guess. Do NOT start coding. Wait for these answers.

If the maintainer says "not ready," implement a mock that returns 5 plausible SMILES for testing purposes (e.g. hard-coded return of common metabolites) and mark real-model tests with `@pytest.mark.requires_inhouse_model`.

## The specific task (once you have model info)

1. Load the in-house generation model (lazy — don't load at import).
2. Run inference with the spectrum (and optional formula) as input.
3. For each generated SMILES:
   - Validate with RDKit (drop invalid).
   - Compute canonical SMILES.
   - Check molecular weight against `max_molecular_weight`.
   - If `molecular_formula` was provided as a constraint, verify the SMILES matches; drop if not.
4. Rank by model's native confidence (logit, beam score, whatever the model exposes). Normalize to `[0, 1]`.
5. If `candidate_pool` was provided, the generator is ENCOURAGED but not required to bias toward structures matching the pool's masses/formulas. Strategy is implementation-defined — document it.
6. Return `GenerateResponse`.

**Read the full contract:** `docs/TOOL_CONTRACTS.md` → "Tool 4: `molecule_generate`".

## What goes into which file

- `tools/molecule_gen/tool.py` — main `generate(req: GenerateRequest) -> GenerateResponse`
- `tools/molecule_gen/model.py` — wrapper around the in-house generation model
- `tools/molecule_gen/validation.py` — RDKit validation, formula matching, MW filter
- `tools/molecule_gen/errors.py` — `ModelLoadError`, `NoValidCandidatesError`
- `tools/molecule_gen/tool_description.md`
- `tools/molecule_gen/requirements.txt` — `rdkit`, `torch` (or whatever the model uses)
- `tools/molecule_gen/example.py`
- `tests/tool_tests/test_molecule_gen.py`

## Test cases you MUST cover

1. **All returned SMILES parse in RDKit:** `Chem.MolFromSmiles(s)` returns non-None for every candidate.
2. **source="generated"** on every output.
3. **Score in [0, 1]** for every output.
4. **Formula constraint respected:** when `molecular_formula="C8H10N4O2"` is provided, at least 90% of outputs have that formula (RDKit Hill form).
5. **MW constraint respected:** `max_molecular_weight=200` excludes heavier outputs.
6. **`n_candidates=0`** returns `candidates=[]` without error.
7. **Invalid SMILES are filtered before response** — if model emits `"not a molecule"`, it doesn't appear in the output.
8. **No crash on empty spectrum input:** 3-peak input still produces at least zero outputs (no exception).

## Testing without the in-house model

Mock the model:
```python
class Generator(Protocol):
    def sample(self, spectrum, n: int, formula: str | None) -> list[tuple[str, float]]:
        """Return list of (smiles, confidence) pairs."""
```
In tests, inject a mock returning hand-picked SMILES. Real model goes through the same interface.

## Dependencies you can use

- `rdkit` — validation, canonicalization, formula computation
- `torch` — model runtime (if applicable)
- `pydantic` — schema
- `common.rdkit_utils` — if you find you're reusing helpers from there

## Explicit non-goals

- Do NOT train the model here. Ship inference only. Training lives elsewhere.
- Do NOT call an LLM. This is a generative-chemistry model, not an LLM.
- Do NOT return invalid SMILES. Every output is RDKit-valid, period.
- Do NOT implement library search as a fallback. If generation fails, raise `NoValidCandidatesError`.
