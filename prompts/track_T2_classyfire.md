# Track T2: ClassyFire integration — chemical classification tool

## Who you are

You are building one new tool: `classify_structure`. It wraps the
ClassyFire REST API (Djoumbou Feunang et al., Journal of Cheminformatics
2016) to classify a chemical structure into the ClassyFire taxonomy
(kingdom → superclass → class → subclass → direct parent).

This tool is a **Type 2 (factual_roundtrip_claim) verifier extension**.
When the LLM says "caffeine is a purine alkaloid" or "glucose is a hexose
monosaccharide", the verifier calls `classify_structure` to check whether
ClassyFire actually classifies that compound that way. Chemical class
claims are among the most common factual assertions LLMs make in
metabolite identification reports — and one of the most reliable things
to check, because ClassyFire is a deterministic rule-based system.

This tool does NOT call an LLM. It is deterministic.

## Read before doing anything

1. `docs/ARCHITECTURE.md` and `docs/TOOL_CONTRACTS.md`
2. `schemas/common.py` — `ToolError` base
3. `tools/metabolite_info/tool.py` — reference for a REST-API-backed tool
4. `common/rdkit_utils.py` — SMILES validation and InChIKey generation
5. `verifier/schemas.py` — specifically `ClaimType.FACTUAL_ROUNDTRIP`
   and how the verifier calls Type 2 verification

Then report back in 5 bullets:
- The ClassyFire API endpoints you will use and their rate limits
- Your proposed Pydantic schema for request and response
- How you handle the async nature of ClassyFire's batch endpoint
   (ClassyFire sometimes queues jobs; you need to poll)
- Your caching strategy (ClassyFire results for a given InChIKey never
  change — cache aggressively)
- Your mock/real test plan

Wait for confirmation before writing code.

## Hard scope boundaries

You MAY:
- Create `tools/classyfire/` with all files in File Layout
- Create `tests/tool_tests/test_classyfire.py`
- Create a small on-disk cache at `data/classyfire_cache.sqlite`
  (gitignored; path overridable via `METAGENT_CLASSYFIRE_CACHE_PATH`)
- Read anything

You MAY NOT:
- Modify `verifier/` — verifier calls your tool, not the other way
- Modify `schemas/` (discuss additions at checkpoint)
- Call an LLM
- Modify any other existing tool
- Hit the ClassyFire API in unit tests — mock all HTTP

## The ClassyFire API

### Endpoint 1: Submit a classification job

```
POST https://classyfire.wishartlab.com/queries.json
Content-Type: application/json

{
  "label": "metagent_query",
  "query_input": "InChIKey=WQZGKKKJIJFFOK-GASJEMHNSA-N",
  "query_type": "STRUCTURE"
}

Response:
{
  "id": 12345,
  "label": "metagent_query",
  "status": "IN_PROGRESS"  // or "DONE"
}
```

### Endpoint 2: Poll for results

```
GET https://classyfire.wishartlab.com/queries/12345.json

Response (when DONE):
{
  "entities": [
    {
      "smiles": "...",
      "inchikey": "WQZGKKKJIJFFOK-GASJEMHNSA-N",
      "kingdom": {"name": "Organic compounds", "chemont_id": "CHEMONTID:0000000"},
      "superclass": {"name": "Carbohydrates and carbohydrate conjugates", ...},
      "class": {"name": "Monosaccharides", ...},
      "subclass": {"name": "Hexoses", ...},
      "direct_parent": {"name": "Aldohexoses", ...},
      "intermediate_nodes": [...],
      "description": "...",
      "ancestors": [...]
    }
  ]
}
```

### Alternative: Direct lookup by InChIKey (faster, no job queue)

```
GET https://classyfire.wishartlab.com/entities/WQZGKKKJIJFFOK-GASJEMHNSA-N.json
```

This endpoint returns immediately if the compound is already in ClassyFire's
database (covers most known metabolites). Use this first; fall back to the
submit/poll flow only if 404.

### Rate limits

ClassyFire is a free academic service. Be a good citizen:
- Max 1 request/second for the direct lookup endpoint
- Max 1 batch job in flight at a time
- Cache every result permanently (results are stable)

## Output schema

```python
class ClassyfireNode(BaseModel):
    name: str
    chemont_id: str
    description: str | None = None

class ClassifyStructureRequest(BaseModel):
    smiles: str | None = None
    inchikey: str | None = None
    # At least one must be provided; if SMILES given, tool derives InChIKey

class ClassifyStructureResponse(BaseModel):
    inchikey: str
    kingdom: ClassyfireNode | None
    superclass: ClassyfireNode | None
    klass: ClassyfireNode | None          # "class" is a Python keyword
    subclass: ClassyfireNode | None
    direct_parent: ClassyfireNode | None
    all_classifications: list[str]        # flat list of all node names
    description: str | None              # compound-level description
    source: Literal["cache", "api"]
    explain: str

    def matches_claim(self, claimed_class: str) -> bool:
        """
        Return True if claimed_class appears anywhere in the
        classification hierarchy (case-insensitive, partial match OK).

        Examples:
          "purine alkaloid" → check all_classifications for "alkaloid"
                              AND "purine" appearing together or as a single node
          "hexose"          → check if "Hexoses" in all_classifications
          "flavonoid"       → check if any node contains "flavonoid"
        """
        ...
```

The `matches_claim` method is the **primary interface for the verifier**.
Type 2 verification calls it like:

```python
resp = classify_structure(ClassifyStructureRequest(smiles=cand.smiles))
verdict = SUPPORTED if resp.matches_claim(claimed_class) else CONTRADICTED
```

## Caching design

ClassyFire results for a given InChIKey are permanent and stable. Every
result must be cached:

```python
# SQLite cache schema
CREATE TABLE classyfire_cache (
    inchikey TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,   -- full ClassifyStructureResponse as JSON
    fetched_at TEXT NOT NULL,      -- ISO-8601 timestamp
    source TEXT NOT NULL           -- 'direct_lookup' or 'batch_job'
);
```

Cache lookup on every request before hitting the API. On cache hit,
set `response.source = "cache"`. On cache miss, fetch and store.

Cache path: `METAGENT_CLASSYFIRE_CACHE_PATH` env var, defaulting to
`data/classyfire_cache.sqlite`. Create the file on first use.

## `matches_claim` implementation guidance

Chemical class matching is non-trivial because:

1. **Naming varies**: LLM says "purine alkaloid", ClassyFire says
   "Purines and purine derivatives" at superclass and "Xanthines" at class
2. **Hierarchical containment**: if LLM says "alkaloid", any compound in
   any alkaloid subclass should match
3. **False negatives are worse than false positives** for verifier use:
   if ClassyFire says "Hexoses" and LLM says "monosaccharide", that should
   match (monosaccharide is a parent class of hexose)

Recommended strategy:
- Build a flat set of all node names from kingdom down to direct_parent
- Also include `ancestors` names if available in the API response
- Tokenize the claimed_class string and check if any token (≥4 chars)
  appears as a substring in any classification node name
- If no match via token: try fuzzy match with threshold 0.8 (use
  `difflib.SequenceMatcher`)
- If still no match: `UNSUPPORTED` (not `CONTRADICTED` — ClassyFire
  might not cover this compound)

Document the matching logic in a block comment inside `matches_claim`.
The verifier session will read this logic to understand what the verdicts mean.

## Error types

```python
class ClassyfireAPIError(ToolError):
    """HTTP error from ClassyFire API"""

class ClassyfireTimeoutError(ToolError):
    """Batch job did not complete within timeout"""

class ClassyfireNotFoundError(ToolError):
    """Compound not in ClassyFire database (novel/rare compound)"""
    # NOT a hallucination indicator — verifier should treat as UNVERIFIABLE_V0

class InvalidStructureError(ToolError):
    """SMILES failed RDKit validation before hitting the API"""
```

`ClassyfireNotFoundError` deserves special attention: if ClassyFire
doesn't know the compound, the verifier must NOT flag the LLM's class
claim as CONTRADICTED — it should be `UNVERIFIABLE_V0`. Document this
clearly in `tool_description.md`.

## File layout

```
tools/classyfire/
├── __init__.py
├── tool.py             # classify_structure(req) -> ClassifyStructureResponse
├── api_client.py       # HTTP calls to ClassyFire REST API
├── cache.py            # SQLite cache read/write
├── matcher.py          # matches_claim() logic
├── schemas.py          # tool-local Pydantic types
├── errors.py
├── tool_description.md
├── requirements.txt    # requests, pydantic, rdkit (already installed)
└── example.py

tests/tool_tests/
└── test_classyfire.py
```

## Test cases you MUST cover

All unit tests mock the HTTP layer — no real API calls.

1. **`test_glucose_is_hexose`**: mock API returns glucose classification;
   `resp.matches_claim("hexose")` → True;
   `resp.matches_claim("amino acid")` → False
2. **`test_caffeine_is_purine_alkaloid`**: mock returns caffeine classification
   (superclass = Purines, class = Xanthines);
   `resp.matches_claim("purine")` → True;
   `resp.matches_claim("alkaloid")` → True (xanthines are alkaloids)
3. **`test_cache_hit_skips_api`**: call twice with same InChIKey; assert
   HTTP client called exactly once; second response has `source="cache"`
4. **`test_not_found_raises_classyfire_not_found`**: mock 404 on direct
   lookup AND empty batch result; raises `ClassyfireNotFoundError`
5. **`test_invalid_smiles_raises_before_api`**: pass `"not a smiles"`;
   raises `InvalidStructureError` without any HTTP call
6. **`test_matches_claim_partial_match`**: mock a compound with
   `direct_parent = "Aldohexoses"`; `matches_claim("hexose")` → True
   (partial string match)
7. **`test_matches_claim_fuzzy`**: mock compound with
   `superclass = "Carbohydrates and carbohydrate conjugates"`;
   `matches_claim("carbohydrate")` → True
8. **`test_explain_is_nonempty`**: always
9. **`test_inchikey_derived_from_smiles`**: pass only SMILES; tool derives
   InChIKey via `common.rdkit_utils` before cache/API lookup
10. **`@pytest.mark.requires_classyfire_api` integration test**: real API
    call for glucose (WQZGKKKJIJFFOK-GASJEMHNSA-N); assert
    `resp.klass.name` contains "Monosaccharide"; skip if
    `METAGENT_CLASSYFIRE_ONLINE` env var not set

## Pre-populated cache fixture

Provide `tests/fixtures/classyfire_cache_seed.json` with real
ClassyFire responses for the three canonical compounds:
- Glucose (WQZGKKKJIJFFOK-GASJEMHNSA-N)
- Caffeine (RYYVLZVUVIJVGH-UHFFFAOYSA-N)
- L-Carnitine (PHIQHXFUZVPYII-REOHCLBHSA-N)

These can be fetched once by running `example.py` and copied manually.
Unit tests that need classification data load from this fixture via
`MockApiClient`, not from the live API. This makes tests deterministic
and offline-capable.

## `tool_description.md` — written for the LLM

Must state clearly:
- **WHEN to call**: when verifying a claim about a compound's chemical
  class, taxonomy, or structural category (e.g., "is a flavonoid",
  "belongs to the purine class", "is a hexose sugar")
- **WHEN NOT to call**: do not call for pathway membership (use
  `pathway_context`); do not call for exact name or formula verification
  (use `fetch_metabolite_info`)
- **`ClassyfireNotFoundError` means `UNVERIFIABLE_V0`**, not contradiction:
  many novel or rare compounds are absent from ClassyFire's database
- **Matching is hierarchical**: if the claimed class is a parent of the
  actual class, `matches_claim` returns True. "Monosaccharide" matches
  a compound classified as "Hexose" because hexose IS a monosaccharide.
- **Rate limit reminder**: do not call in a tight loop; the tool has a
  built-in 1 req/s throttle

## Verifier integration note (for the verifier session, not this session)

After this tool is delivered, the verifier session should update
`verifier/layers/factual.py` to handle chemical class claims:

```python
# In factual.py, after fetch_metabolite_info round-trip:
if claim.claim_subtype == "chemical_class":
    try:
        resp = classify_structure(ClassifyStructureRequest(
            smiles=source_report.candidates[i].smiles
        ))
        if resp.matches_claim(claim.claimed_value):
            return ClaimVerdict.SUPPORTED
        else:
            return ClaimVerdict.CONTRADICTED
    except ClassyfireNotFoundError:
        return ClaimVerdict.UNVERIFIABLE_V0
```

This integration is OUT OF SCOPE for this track. Document it as a
"handoff note" in your delivery report so the verifier session picks
it up.

## Exit criteria

- `pytest tests/tool_tests/test_classyfire.py -v` — all 9 unit tests pass
  with mocked HTTP, no real API call
- `python tools/classyfire/example.py` — prints a classification for
  glucose (from cache if populated, from API if online)
- Cache round-trip verified: run example twice, second run hits cache
- `matches_claim` correctly handles glucose/hexose/monosaccharide
  hierarchical case
- No modifications outside `tools/classyfire/` and
  `tests/tool_tests/test_classyfire.py`

## First action

Run:
```bash
curl -s "https://classyfire.wishartlab.com/entities/WQZGKKKJIJFFOK-GASJEMHNSA-N.json" \
  | python3 -m json.tool | head -60
```

Paste the output in your 5-bullet understanding. This confirms the API
is reachable from your server and shows the exact JSON shape your parser
needs to handle. If the server is unreachable (firewall), flag it and
proceed with a fully mock-based implementation.