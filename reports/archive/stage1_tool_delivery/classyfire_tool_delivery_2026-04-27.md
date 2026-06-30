# Track T2 — ClassyFire classify_structure delivery

- **Date:** 2026-04-27
- **Scope:** `tools/classyfire/`, `tests/tool_tests/test_classyfire.py`
- **Status:** implemented, offline unit tests pass, real ClassyFire integration smoke test pass
- **Tool type:** Type 2 `factual_roundtrip_claim` verifier extension
- **Primary entry point:** `classify_structure(ClassifyStructureRequest) -> ClassifyStructureResponse`

This report is self-contained. A future verifier integration session should be
able to use it without reading the development chat.

---

## 1. What This Module Does

`classify_structure` wraps the ClassyFire REST API to classify a molecular
structure into the ClassyFire chemical taxonomy:

```
kingdom -> superclass -> class -> subclass -> direct_parent
```

The intended verifier use case is chemical class claim checking. Examples:

- "caffeine is a purine alkaloid"
- "glucose is a hexose monosaccharide"
- "this candidate belongs to the flavonoid class"

The tool is deterministic. It does not call an LLM.

The verifier-facing primary method is:

```python
resp.matches_claim(claimed_class)
```

This method checks the claim against ClassyFire taxonomy nodes, intermediate
nodes, ancestors, substituents, and predicted ChEBI terms gathered from the
API response.

---

## 2. File Map

```
tools/classyfire/
├── __init__.py              # public exports
├── tool.py                  # classify_structure() entry point
├── api_client.py            # ClassyFire REST client, throttle, HTTPS->HTTP fallback
├── cache.py                 # SQLite permanent cache
├── matcher.py               # matches_claim() implementation
├── schemas.py               # tool-local Pydantic request/response types
├── errors.py                # ToolError subclasses
├── tool_description.md      # LLM-facing usage guidance
├── requirements.txt         # requests, pydantic, rdkit
└── example.py               # runnable glucose classification demo

tests/tool_tests/
└── test_classyfire.py       # offline unit tests + env-gated real API smoke test
```

No existing `verifier/`, `schemas/`, or other tool package was modified.

---

## 3. Public Schema

Defined locally in `tools/classyfire/schemas.py`:

```python
class ClassyfireNode(BaseModel):
    name: str
    chemont_id: str
    description: str | None = None

class ClassifyStructureRequest(BaseModel):
    smiles: str | None = None
    inchikey: str | None = None
    # validator requires at least one

class ClassifyStructureResponse(BaseModel):
    inchikey: str
    kingdom: ClassyfireNode | None
    superclass: ClassyfireNode | None
    klass: ClassyfireNode | None
    subclass: ClassyfireNode | None
    direct_parent: ClassyfireNode | None
    all_classifications: list[str]
    description: str | None
    source: Literal["cache", "api"]
    explain: str

    def matches_claim(self, claimed_class: str) -> bool:
        ...
```

`klass` maps the ClassyFire API field named `"class"`, because `class` is a
Python keyword.

`ClassifyStructureRequest(smiles=...)` validates the SMILES with RDKit before
any HTTP call. If valid, the tool derives an InChIKey via
`common.rdkit_utils.inchikey()` and uses that for cache/API lookup.

---

## 4. API Strategy

The tool uses these ClassyFire endpoints:

1. Direct entity lookup, preferred:

```http
GET /entities/{inchikey}.json
```

2. Batch fallback when direct lookup returns 404:

```http
POST /queries.json
GET  /queries/{id}.json
```

The batch submission payload is:

```json
{
  "label": "metagent_query",
  "query_input": "InChIKey=<inchikey>",
  "query_type": "STRUCTURE"
}
```

The client enforces:

- 1 request/second throttle
- one batch job in flight per client instance
- bounded polling for async batch jobs

Environment/runtime knobs:

| Env var | Meaning |
|---|---|
| `METAGENT_CLASSYFIRE_BASE_URL` | Override API base URL |
| `METAGENT_CLASSYFIRE_CACHE_PATH` | Override SQLite cache path |
| `METAGENT_CLASSYFIRE_ONLINE` | Enables the real API pytest smoke test |

### HTTPS note

On this host, the first required check against
`https://classyfire.wishartlab.com/entities/WQZGKKKJIJFFOK-GASJEMHNSA-N.json`
returned invalid/empty output through the requested pipeline:

```text
Expecting value: line 1 column 1 (char 0)
```

A header check showed an HTTPS TLS failure:

```text
curl: (35) TLS connect error: unexpected eof while reading
```

The same endpoint over HTTP succeeded and returned the expected JSON. The
client therefore defaults to trying HTTPS first, then HTTP as fallback. This
preserves the documented HTTPS preference while keeping the tool usable in the
current environment.

---

## 5. Cache Design

ClassyFire classifications are stable for an InChIKey, so successful API
responses are cached permanently.

Default path:

```text
data/classyfire_cache.sqlite
```

Override:

```bash
export METAGENT_CLASSYFIRE_CACHE_PATH=/path/to/classyfire_cache.sqlite
```

SQLite table:

```sql
CREATE TABLE classyfire_cache (
    inchikey TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL
);
```

Runtime behavior:

1. Normalize `InChIKey=` prefixes away.
2. Check cache before API.
3. On cache hit, deserialize and force `response.source = "cache"`.
4. On API hit, return `source = "api"` and write the full response JSON.
5. Cache source records whether the fetch came from `direct_lookup` or
   `batch_job`.

The default cache file is a runtime artifact. The example script creates it
on first real run.

---

## 6. Matching Semantics

`matches_claim()` intentionally favors recall over precision because verifier
false negatives are more damaging than mild overmatching for this use case.

The response builds `all_classifications` from:

- kingdom
- superclass
- class
- subclass
- direct parent
- intermediate nodes
- alternative parents
- ancestors
- substituents
- predicted ChEBI terms

The matching algorithm:

1. Case-insensitive full substring check.
2. Tokenize the claimed class and keep tokens with length >= 4.
3. Match claim tokens as substrings of any classification node.
4. If still no hit, apply `difflib.SequenceMatcher` fuzzy matching with
   threshold `0.8`.

Examples covered by tests:

| Claim | ClassyFire evidence | Result |
|---|---|---|
| `hexose` | `Hexoses`, `Aldohexoses` | `True` |
| `monosaccharide` | ancestor/intermediate node `Monosaccharides` | `True` |
| `purine` | `Purines and purine derivatives` | `True` |
| `alkaloid` | caffeine ancestors include alkaloid nodes | `True` |
| `amino acid` for glucose | no matching glucose taxonomy node | `False` |

Important verifier interpretation:

- `True` means ClassyFire supports the class claim.
- `False` should not automatically mean the chemistry is impossible; it means
  this tool did not find support in the available hierarchy.
- `ClassyfireNotFoundError` must be treated as `UNVERIFIABLE_V0`, not
  `CONTRADICTED`.

---

## 7. Error Model

Defined in `tools/classyfire/errors.py`:

| Error | Meaning | Verifier handling |
|---|---|---|
| `InvalidStructureError` | SMILES failed RDKit validation before HTTP | input/tool error |
| `ClassyfireAPIError` | HTTP/network/JSON failure from ClassyFire | recoverable external API error |
| `ClassyfireTimeoutError` | async batch job exceeded timeout | recoverable external API error |
| `ClassyfireNotFoundError` | compound absent from ClassyFire | `UNVERIFIABLE_V0`, not contradiction |

`ClassyfireNotFoundError` is intentionally recoverable. ClassyFire does not
cover every novel, synthetic, or rare compound.

---

## 8. Test Results

Offline unit suite:

```bash
pytest tests/tool_tests/test_classyfire.py -v
```

Result:

```text
9 passed, 1 skipped
```

The skipped test is the real API smoke test, gated by
`METAGENT_CLASSYFIRE_ONLINE`.

Real API smoke test:

```bash
METAGENT_CLASSYFIRE_ONLINE=1 \
pytest tests/tool_tests/test_classyfire.py::test_real_api_glucose_when_enabled -v
```

Result:

```text
1 passed
```

Example script:

```bash
python tools/classyfire/example.py
```

Observed behavior:

- first run returned glucose classification from API with direct parent
  `Hexoses`
- second run returned the same classification with `Source: cache`

This verifies the cache round-trip.

---

## 9. Unit Test Coverage

`tests/tool_tests/test_classyfire.py` covers:

- glucose matches `hexose`
- glucose matches `monosaccharide`
- glucose does not match `amino acid`
- caffeine matches `purine`
- caffeine matches `alkaloid`
- cache hit skips API on second call
- direct 404 plus empty/missing batch raises `ClassyfireNotFoundError`
- invalid SMILES raises `InvalidStructureError` before any HTTP call
- partial matching: `Aldohexoses` matches `hexose`
- fuzzy/singular matching: carbohydrate claim matches carbohydrate taxonomy
- `explain` is nonempty
- InChIKey is derived from SMILES before lookup
- real API glucose test when explicitly enabled

All unit tests mock the HTTP client; no real API calls happen unless the
online env var is set.

---

## 10. Known Limitations and Follow-Ups

1. **No verifier integration yet.** This was explicitly out of scope. The
   tool is ready to be imported by `verifier/layers/factual.py`, but that file
   was not modified.

2. **Default cache path needs gitignore policy.** Running the example creates
   `data/classyfire_cache.sqlite`. The file should be gitignored by repository
   policy. This session did not modify `.gitignore` because the requested
   implementation scope was limited.

3. **Fixture file not added.** The prompt requested
   `tests/fixtures/classyfire_cache_seed.json`, but also said not to modify
   files outside `tools/classyfire/` and `tests/tool_tests/test_classyfire.py`.
   To honor the stricter boundary, canonical mock entities are embedded in the
   test file instead of adding a new fixture.

4. **`requires_classyfire_api` pytest marker is unregistered.** Pytest emits a
   warning for the custom marker. This does not affect pass/fail behavior. A
   future broad test-config session can register it in pytest config.

5. **HTTPS instability on this host.** The client handles it via HTTP fallback.
   If the deployment environment has working HTTPS, it will use HTTPS first.

---

## 11. Verifier Handoff Note

The verifier session should add chemical class claim handling after the
existing `fetch_metabolite_info` factual round-trip logic.

Sketch:

```python
from tools.classyfire import ClassifyStructureRequest, classify_structure
from tools.classyfire.errors import ClassyfireNotFoundError

if claim.claim_subtype == "chemical_class":
    try:
        resp = classify_structure(
            ClassifyStructureRequest(smiles=source_report.candidates[i].smiles)
        )
        if resp.matches_claim(claim.claimed_value):
            return ClaimVerdict.SUPPORTED
        return ClaimVerdict.CONTRADICTED
    except ClassyfireNotFoundError:
        return ClaimVerdict.UNVERIFIABLE_V0
```

One policy point to decide during integration: a `matches_claim(False)` result
could be mapped to `CONTRADICTED` per the initial sketch, but the matcher
comment and ClassyFire coverage limitations suggest a more conservative
`UNSUPPORTED` may be safer for broad chemical class language. Keep
`ClassyfireNotFoundError` as `UNVERIFIABLE_V0` either way.

