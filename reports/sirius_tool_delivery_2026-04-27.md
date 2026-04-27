# Track T1 — SIRIUS `sirius_annotate` delivery

- **Date:** 2026-04-27
- **Scope:** `tools/sirius/`, `tests/tool_tests/test_sirius.py`
- **Status:** implemented; mock tests pass; real SIRIUS 6.3.4 glucose path passes
- **Tool type:** deterministic fragmentation-tree ground-truth tool for peak-level mechanistic verification
- **Primary entry point:** `sirius_annotate(SiriusAnnotateRequest) -> SiriusAnnotateResponse`

This report is self-contained. A future verifier integration session should be
able to use it without reading the development chat.

---

## 1. What This Module Does

`sirius_annotate` wraps the SIRIUS CLI to compute:

1. top molecular formula prediction for the precursor
2. fragmentation tree nodes
3. peak-level fragment annotations, including m/z, fragment formula, intensity,
   tree depth, and neutral loss from parent

It is intended as the lookup backend for peak-level mechanistic claims such as:

> m/z 163.06 is the `[M+H-H2O]+` water-loss fragment of glucose.

The tool does not call an LLM. It is deterministic given the input spectrum,
SIRIUS version/configuration, and login/licence state.

The verifier-facing primary method is:

```python
resp.lookup_fragment(mz=163.06, tolerance_ppm=5.0)
```

It returns a `FragmentAnnotation` when SIRIUS placed a tree node within the
requested ppm window, otherwise `None`.

---

## 2. File Map

```
tools/sirius/
├── __init__.py              # public exports
├── tool.py                  # sirius_annotate(), real/mock runners, SIRIUS 6 REST reader
├── ms_writer.py             # Spectrum -> .ms writer and simple peak reader for tests
├── tree_parser.py           # SIRIUS tree JSON -> FragmentAnnotation list
├── schemas.py               # tool-local Pydantic request/response types
├── errors.py                # ToolError subclasses
├── README.md                # setup notes and tested version
├── tool_description.md      # LLM-facing usage guidance
├── requirements.txt         # python-dotenv, requests
└── example.py               # runnable glucose demo

tests/tool_tests/
└── test_sirius.py           # mock tests + real SIRIUS glucose test
```

No `verifier/` or shared `schemas/` files were modified.

---

## 3. Public Schema

Defined locally in `tools/sirius/schemas.py`:

```python
class FragmentAnnotation(BaseModel):
    mz_observed: float
    formula: str
    formula_score: float
    neutral_loss: str = ""
    neutral_loss_formula: str = ""
    intensity: float
    depth: int

class SiriusAnnotateRequest(BaseModel):
    spectrum: Spectrum
    instrument_preset: Literal["orbitrap", "qtof", "fticr"] = "orbitrap"
    timeout_seconds: int = 120

class SiriusAnnotateResponse(BaseModel):
    predicted_formula: str
    formula_score: float
    fragments: list[FragmentAnnotation]
    tree_node_count: int
    sirius_version: str
    explain: str

    def lookup_fragment(
        self,
        mz: float,
        tolerance_ppm: float = 5.0,
    ) -> FragmentAnnotation | None:
        ...
```

`lookup_fragment()` sorts fragments by `mz_observed`, checks the nearest m/z
neighbors, and returns the closest hit within the ppm window.

### Error Types

All are subclasses of `schemas.common.ToolError`:

```python
SiriusNotInstalledError
SiriusTimeoutError
SiriusParseError
SiriusNoFormulaError
```

---

## 4. Runtime and Installation

SIRIUS is installed on this machine:

```text
/home/weiwentao/tools/sirius-install/sirius-6.3.4-linux-x64/
/home/weiwentao/.local/bin/sirius
```

Version:

```text
SIRIUS 6.3.4
SIRIUS lib: 5.7.0
CSI:FingerID lib: 3.0.13
```

Project `.env` contains:

```bash
METAGENT_SIRIUS_PATH=/home/weiwentao/.local/bin/sirius
```

The SIRIUS account was logged in successfully and has an Academic License.
For future runs, the login state must remain valid in the SIRIUS workspace
under:

```text
/home/weiwentao/.sirius-6.3
```

If SIRIUS reports `Login ERROR`, rerun:

```bash
sirius login -u <email> -p
```

The password should not be placed on the command line.

---

## 5. Invocation Strategy

### 5.1 Input Writer

The tool converts `schemas.common.Spectrum` into SIRIUS `.ms` text:

```text
>compound query
>parentmass 181.070700
>ionization [M+H]+
>collision 20
61.028400 9.000000
...
163.060100 100.000000
```

Project spectra use normalized intensities `[0, 1]`; the writer scales them
to SIRIUS-style percent/base-peak values.

### 5.2 SIRIUS CLI Command

The real runner invokes:

```bash
sirius --log WARNING \
  -i /tmp/query.ms \
  -o /tmp/sirius_out \
  formula \
  --no-recalibration \
  --candidates 1 \
  -p orbitrap \
  --compound-timeout <timeout_seconds> \
  --tree-timeout <timeout_seconds>
```

For SIRIUS 5-style output, the parser supports:

```text
sirius_out/<compound>/formula_candidates.tsv
sirius_out/<compound>/trees/<formula>.json
```

### 5.3 SIRIUS 6 Output Handling

SIRIUS 6.3.4 does **not** write the old directory tree by default. It writes a
single project-space file:

```text
/tmp/sirius_out.sirius
```

The implementation detects this file and reads it through SIRIUS' local REST
API:

1. Start SIRIUS service when needed:

```bash
sirius service --headless -p <free_port> -s
```

2. If a healthy service already exists at `127.0.0.1:8765`, reuse it instead
   of starting a second service. SIRIUS permits only one service instance per
   user.

3. Open the project:

```http
PUT /api/projects/{projectId}?pathToProject=/tmp/sirius_out.sirius
```

4. Read features:

```http
GET /api/projects/{projectId}/aligned-features
```

5. Read formula candidates:

```http
GET /api/projects/{projectId}/aligned-features/{alignedFeatureId}/formulas
```

6. Read fragmentation tree:

```http
GET /api/projects/{projectId}/aligned-features/{alignedFeatureId}/formulas/{formulaId}/fragtree
```

The `/fragtree` response is parsed by `tree_parser.parse_tree_json()`.

---

## 6. Tree Parsing

`tree_parser.py` supports both:

- graph-shaped SIRIUS JSON with `fragments` and `losses`
- nested JSON with `root` and `children`

For graph-shaped output, it extracts:

```text
fragmentId/id
molecularFormula/formula
mz
intensity/relativeIntensity
loss source/target
loss molecularFormula
```

It builds parent-child edges, computes depth from the root, normalizes
intensities to `[0, 1]`, and returns fragments sorted by m/z.

Root nodes may omit neutral loss; this is handled as:

```python
neutral_loss = ""
neutral_loss_formula = ""
depth = 0
```

---

## 7. Real Glucose Result

The real-path glucose spectrum was run through installed SIRIUS 6.3.4 after
login.

Input:

```text
precursor_mz = 181.0707
adduct = [M+H]+
collision_energy = 20
peaks = 61.0284, 73.0284, 85.0284, 109.0284, 127.0390, 145.0495, 163.0601
```

Observed result from `sirius_annotate`:

```text
FORMULA C6H12O6
SCORE 0.9999982269132929
NODES 8
FRAG_MZ 163.0601
FRAG_FORMULA C6H10O5
FRAG_LOSS H2O
```

Important interpretation note:

SIRIUS' real `/fragtree` output reports neutralized fragment formulas. For the
glucose water-loss peak, SIRIUS returns:

```text
m/z 163.0601
formula C6H10O5
neutral_loss H2O
depth 1
```

The earlier handcrafted mock fixture used `C6H11O5`. The real SIRIUS value
should be treated as authoritative for real verifier checks.

Example response excerpt:

```json
{
  "predicted_formula": "C6H12O6",
  "formula_score": 0.9999982269132929,
  "tree_node_count": 8,
  "sirius_version": "6.3.4",
  "fragments": [
    {
      "mz_observed": 163.0601,
      "formula": "C6H10O5",
      "neutral_loss": "H2O",
      "neutral_loss_formula": "H2O",
      "intensity": 1.0,
      "depth": 1
    }
  ]
}
```

---

## 8. Test Coverage

Command:

```bash
pytest tests/tool_tests/test_sirius.py -v
```

Result:

```text
9 passed
```

Covered cases:

1. `test_ms_writer_roundtrip`
2. `test_lookup_fragment_within_tolerance`
3. `test_lookup_fragment_outside_tolerance`
4. `test_timeout_raises`
5. `test_tree_parser_handles_missing_neutral_loss`
6. `test_sirius_not_installed_raises`
7. `test_explain_is_nonempty_template`
8. `test_glucose_has_water_loss_fragment`
9. `test_real_glucose_formula`

The real test now runs against installed SIRIUS 6.3.4 and passes.

Example command:

```bash
python tools/sirius/example.py
```

This prints a real `SiriusAnnotateResponse` when SIRIUS is installed and
logged in. If SIRIUS is unavailable, the example falls back to `MockSiriusRunner`.

---

## 9. Mock Strategy

`MockSiriusRunner` writes deterministic SIRIUS-like output without requiring a
binary, login, REST service, or network.

Current built-in mock compounds:

- glucose
- caffeine
- L-carnitine

The mock path uses the same public `sirius_annotate()` function and parser,
but writes a small `formula_candidates.tsv` and tree JSON in the old SIRIUS 5
style. This keeps unit tests fast and independent of SIRIUS runtime state.

---

## 10. Known Issues and Operational Notes

1. **SIRIUS 6 service singleton**

   SIRIUS permits only one REST service per user. The implementation checks for
   a healthy service at:

   ```text
   http://127.0.0.1:8765
   http://localhost:8765
   ```

   and reuses it if present. Otherwise it starts a temporary service on a free
   port and shuts it down after parsing.

2. **Login persistence can expire or disappear**

   `sirius login --show` should show the logged-in account and Academic License.
   If real-path tests fail with `Login ERROR`, rerun SIRIUS login.

3. **SIRIUS web-service cleanup warnings**

   SIRIUS sometimes prints SSL handshake or timeout warnings during shutdown
   while deleting remote jobs. These did not prevent local formula/tree
   computation in the successful real tests.

4. **Pytest mark warning**

   `pytest.mark.requires_sirius` is currently unregistered, so pytest emits:

   ```text
   PytestUnknownMarkWarning: Unknown pytest.mark.requires_sirius
   ```

   The warning is harmless for this track. Registering the marker would require
   editing project-level pytest config, which was outside this track's scope.

5. **Existing repository warning**

   Test runs also show a Pydantic warning from an existing `model_version`
   field outside this tool. It is unrelated to `tools/sirius`.

---

## 11. Verifier Integration Guidance

Expected verifier usage:

```python
req = SiriusAnnotateRequest(spectrum=preprocessed_spectrum)
resp = sirius_annotate(req)

ann = resp.lookup_fragment(mz=163.06, tolerance_ppm=5.0)
if ann is None:
    verdict = ClaimVerdict.UNSUPPORTED
elif ann.neutral_loss != claimed_neutral_loss:
    verdict = ClaimVerdict.CONTRADICTED
else:
    verdict = ClaimVerdict.SUPPORTED
```

Recommended evidence string:

```text
SIRIUS 6.3.4 predicted C6H12O6; tree contains m/z 163.0601
with formula C6H10O5 and neutral loss H2O.
```

Current repo note:

`verifier/schemas.py` still defines Type 5 as `LITERATURE`, and does not yet
contain `ClaimType.PEAK_MECHANISTIC`. This tool is ready for that future layer,
but no verifier code was modified in this track.
