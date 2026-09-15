# Track T1: SIRIUS integration — fragmentation tree tool

## Who you are

You are building one new tool: `sirius_annotate`. It wraps the SIRIUS CLI
(Böcker et al., Nature Methods 2019) to produce fragmentation trees,
molecular formula predictions, and peak-level fragment annotations from
a single MS/MS spectrum + precursor.

This tool is the **ground-truth engine for Type 5 (peak_mechanistic_claim)
verification** in the verifier. When the LLM says "m/z 163.06 is the
[M+H-H₂O]⁺ water-loss fragment of glucose", the verifier calls
`sirius_annotate` to check whether SIRIUS's fragmentation tree actually
places a fragment at that m/z with that formula. The verifier does not
interpret the tree — it just needs the tree as a lookup table.

This tool does NOT call an LLM. It is deterministic.

## Read before doing anything

1. `docs/ARCHITECTURE.md` — understand the tool/verifier separation
2. `docs/TOOL_CONTRACTS.md` — follow the established tool contract pattern
3. `schemas/spectrum.py` — `Spectrum` is your input type
4. `schemas/common.py` — `ToolError` base class
5. `verifier/schemas.py` — specifically `ClaimType.PEAK_MECHANISTIC` and
   `VerifiedClaim` — understand what the verifier expects from this tool
6. `tools/spectrum_predict/tool.py` — reference implementation of a
   CLI-wrapping tool (CFM-ID pattern); mirror its structure

Then report back in 5 bullets:
- How SIRIUS is installed on this machine and which version
  (run `sirius --version` to check; if absent, document the install path)
- Your proposed input/output schema (show the Pydantic models)
- Which SIRIUS sub-commands you will invoke and in what order
- How you will parse the fragmentation tree JSON output
- Your plan for the mock/real two-path test strategy

Wait for confirmation before writing code.

## Hard scope boundaries

You MAY:
- Create `tools/sirius/` with all files listed in File Layout
- Add `sirius` to the project-level notes about required external tools
- Read anything in the repo

You MAY NOT:
- Modify `verifier/` — the verifier will call your tool; you do not reach
  into verifier code
- Modify `schemas/` except to discuss proposed additions at the checkpoint
- Call an LLM inside this tool
- Modify any other existing tool

## The specific task

### What SIRIUS does (for your implementation)

SIRIUS takes an MS/MS spectrum and produces:

1. **Molecular formula prediction** — the most likely elemental composition
   of the precursor, with a confidence score
2. **Fragmentation tree** — a rooted tree where:
   - Root = precursor ion
   - Each node = a fragment ion with its m/z, formula, intensity, and
     loss formula from parent
   - Edges = neutral losses between parent and child fragment
3. **CSI:FingerID fingerprint** (optional, slower) — molecular fingerprint
   for database search

For Type 5 verification, you need items 1 and 2. Item 3 is out of scope
for this track.

### Invocation sequence

```bash
# Step 1: write spectrum to a temp .ms file (SIRIUS input format)
# Step 2: invoke SIRIUS formula sub-command
sirius -i /tmp/query.ms \
       -o /tmp/sirius_out \
       formula \
       --no-recalibrate \
       --candidates 1 \
       -p orbitrap    # instrument preset; parameterise this

# Step 3: parse /tmp/sirius_out/<compound_id>/formula_candidates.tsv
#         and /tmp/sirius_out/<compound_id>/trees/<formula>.json

# Step 4: clean up tmp files
```

The `.ms` file format is plain text:
```
>compound glucose_query
>parentmass 181.0707
>ionization [M+H]+
>collision 20
181.0707 100.0
163.0601 85.3
145.0495 42.1
...
```

### Output schema (propose in your understanding checkpoint)

The verifier needs to answer two questions from your output:

**Q1:** "Is there a fragment in the tree with m/z ≈ X (within `mz_tolerance_ppm`)?"
**Q2:** "If yes, what formula is assigned to that fragment and what is the
         neutral loss from the precursor?"

Your output type must support both lookups efficiently. A proposed starting
point (discuss and refine at the checkpoint):

```python
class FragmentAnnotation(BaseModel):
    mz_observed: float
    formula: str               # e.g. "C6H11O5"
    formula_score: float       # SIRIUS confidence [0,1]
    neutral_loss: str          # e.g. "H2O" (from parent to this node)
    neutral_loss_formula: str  # e.g. "H2O" or "C2H4O2"
    intensity: float           # relative [0,1]
    depth: int                 # depth in tree (0 = precursor)

class SiriusAnnotateRequest(BaseModel):
    spectrum: Spectrum
    instrument_preset: Literal[
        "orbitrap", "qtof", "fticr"
    ] = "orbitrap"
    timeout_seconds: int = 120

class SiriusAnnotateResponse(BaseModel):
    predicted_formula: str          # top formula prediction
    formula_score: float            # [0,1]
    fragments: list[FragmentAnnotation]
    tree_node_count: int
    sirius_version: str             # from `sirius --version`
    explain: str                    # template-rendered summary

    def lookup_fragment(
        self,
        mz: float,
        tolerance_ppm: float = 5.0
    ) -> FragmentAnnotation | None:
        """Return the closest matching fragment within tolerance, or None."""
        ...
```

The `lookup_fragment` method is the **primary interface for the verifier**.
Type 5 verification calls it like:
```python
ann = sirius_resp.lookup_fragment(mz=163.06)
if ann is None:
    verdict = UNSUPPORTED  # SIRIUS found no fragment here
elif ann.neutral_loss != claimed_neutral_loss:
    verdict = CONTRADICTED  # formula doesn't match LLM's claim
else:
    verdict = SUPPORTED
```

### Error types

```python
class SiriusNotInstalledError(ToolError): ...
class SiriusTimeoutError(ToolError): ...
class SiriusParseError(ToolError): ...      # output JSON malformed
class SiriusNoFormulaError(ToolError): ...  # no formula found (too noisy)
```

All must subclass `schemas.common.ToolError`.

## File layout

```
tools/sirius/
├── __init__.py
├── tool.py             # sirius_annotate(req) -> SiriusAnnotateResponse
├── ms_writer.py        # writes Spectrum → .ms file format
├── tree_parser.py      # parses SIRIUS JSON fragmentation tree
├── schemas.py          # SiriusAnnotateRequest, SiriusAnnotateResponse,
│                       #   FragmentAnnotation (tool-local, not in schemas/)
├── errors.py
├── tool_description.md
├── requirements.txt    # sirius is external binary; document install path
└── example.py

tests/tool_tests/test_sirius.py
```

## Test strategy

### Mock path (no SIRIUS binary needed — always runs)

Provide a `MockSiriusRunner` that reads from
`tests/fixtures/sirius_outputs/` — a directory of pre-computed SIRIUS
JSON outputs for the three canonical fixtures (glucose, caffeine,
L-carnitine). These fixture files should be real SIRIUS outputs if you can
run SIRIUS once; otherwise use hand-crafted JSON that matches the SIRIUS
output schema.

Unit tests use the mock runner:
```python
def test_glucose_has_water_loss_fragment():
    # glucose [M+H]+ = 181.07, expect [M+H-H2O]+ = 163.06
    req = SiriusAnnotateRequest(spectrum=glucose_spectrum)
    resp = sirius_annotate(req, runner=MockSiriusRunner())
    frag = resp.lookup_fragment(mz=163.06, tolerance_ppm=5.0)
    assert frag is not None
    assert frag.neutral_loss in ("H2O", "H₂O")
```

### Real path (requires SIRIUS binary — mark `@pytest.mark.requires_sirius`)

```python
@pytest.mark.requires_sirius
def test_real_glucose_formula():
    req = SiriusAnnotateRequest(spectrum=glucose_spectrum)
    resp = sirius_annotate(req)
    assert resp.predicted_formula == "C6H12O6"
    assert resp.formula_score > 0.5
```

Skip if `SIRIUS_PATH` env var is not set or binary not found.

### Test cases you MUST cover

1. **`test_ms_writer_roundtrip`**: write a Spectrum to .ms, parse back the
   mz/intensity, assert round-trip fidelity within 1e-4 Da
2. **`test_lookup_fragment_within_tolerance`**: fragment at 163.0600, query
   at 163.0603 (1.8 ppm) with tolerance 5 ppm → found
3. **`test_lookup_fragment_outside_tolerance`**: same but with 0.5 ppm
   tolerance → None
4. **`test_timeout_raises`**: inject a runner that sleeps 200s; with
   `timeout_seconds=5` → `SiriusTimeoutError`
5. **`test_tree_parser_handles_missing_neutral_loss`**: some SIRIUS outputs
   omit neutral_loss for root node; parser must handle gracefully
6. **`test_sirius_not_installed_raises`**: point `SIRIUS_PATH` at a
   nonexistent path → `SiriusNotInstalledError` before any subprocess call
7. **`test_explain_is_nonempty_template`**: call with mock runner, verify
   `explain` is a non-empty string containing fragment count

## SIRIUS installation notes

SIRIUS 5.x or 6.x is required. It is a Java application distributed as a
standalone binary. Document the following in `tools/sirius/README.md`:

```markdown
## SIRIUS Setup

Download from https://github.com/boecker-lab/sirius/releases
Set env var: METAGENT_SIRIUS_PATH=/path/to/sirius

SIRIUS requires a one-time login for CSI:FingerID features (not needed
for fragmentation trees). For this tool, no login is required — we only
use the `formula` sub-command, which is free and local.

Tested version: SIRIUS 5.8.x (also compatible with 6.x)
```

The tool must read `METAGENT_SIRIUS_PATH` from env (via `.env` / dotenv),
falling back to `sirius` on PATH, and raising `SiriusNotInstalledError`
if neither resolves.

## `tool_description.md` — written for the LLM

Must clearly state:
- **WHEN to call this tool**: when you need to verify a peak-level
  fragmentation claim, or when you need the molecular formula of the
  precursor confirmed by a dedicated fragmentation tree algorithm
- **WHEN NOT to call**: do not call for simple mass matching (use
  `candidate_prefilter` instead); do not call when spectrum has <5 peaks
  (SIRIUS will fail or produce unreliable trees)
- **What `lookup_fragment` returns**: a FragmentAnnotation or None; None
  means SIRIUS found no fragment at that m/z, NOT that the fragment is
  chemically impossible
- **Failure modes**: timeout on large molecules (>600 Da), no formula
  found for very noisy spectra, licence required for fingerprint features

## Exit criteria

- `pytest tests/tool_tests/test_sirius.py -v` — all passing with mock runner
- `python tools/sirius/example.py` — prints a SiriusAnnotateResponse
  (mock or real depending on env)
- `METAGENT_SIRIUS_PATH` pointing at real binary: all
  `@pytest.mark.requires_sirius` tests pass
- `lookup_fragment` correctly handles the water-loss case for glucose
- No modifications outside `tools/sirius/` and `tests/tool_tests/`

## First action

Run `sirius --version` and `echo $METAGENT_SIRIUS_PATH` and report the
results in your 5-bullet understanding. If SIRIUS is not installed, your
first task is to document the install path and build the full mock-first
implementation; flag to the maintainer that real-path tests will need
the binary installed separately.