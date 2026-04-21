# Track F: `literature_search`

**Prerequisite:** read `prompts/_preamble.md` first.

## Your scope

You own exactly one tool: **`literature_search`**. Directory: `tools/literature/`.

This is the smallest track — a clean API wrapper around Europe PMC / PubMed. The challenge isn't complexity, it's **hallucination resistance**: every returned record must be independently verifiable. The verifier will spot-check your output, and fabricated PMIDs or synthesized abstracts will fail the whole report.

## The specific task

Given a free-text query, call Europe PMC REST (primary) or NCBI E-utilities (fallback) and return structured `LiteratureRecord` objects with verifiable PMIDs.

**Read the full contract:** `docs/TOOL_CONTRACTS.md` → "Tool 8: `literature_search`".

## What goes into which file

- `tools/literature/tool.py` — main `literature_search(req: LiteratureSearchRequest) -> LiteratureSearchResponse`
- `tools/literature/europepmc_client.py` — Europe PMC REST wrapper
- `tools/literature/pubmed_client.py` — NCBI E-utilities fallback
- `tools/literature/normalise.py` — turn API response into `LiteratureRecord`
- `tools/literature/errors.py` — `RateLimitError`
- `tools/literature/tool_description.md`
- `tools/literature/requirements.txt` — `requests`, `pydantic`
- `tools/literature/example.py`
- `tests/tool_tests/test_literature.py`

## API endpoints

**Europe PMC** (primary, no auth needed):
- Search: `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=<q>&format=json&pageSize=<n>`
- Respond with `resultList.result[]`, each having `pmid`, `title`, `abstractText`, `authorString`, `journalTitle`, `pubYear`, `doi`.

**NCBI E-utilities** (fallback, optional key via `NCBI_API_KEY`):
- Search: `esearch.fcgi?db=pubmed&term=<q>&retmode=json`
- Fetch: `efetch.fcgi?db=pubmed&id=<pmids>&rettype=abstract&retmode=xml`

## Test cases you MUST cover

1. **Common query returns results:** query `"L-carnitine fatty acid oxidation"` returns `len(records) > 0` (integration test — skip if offline).
2. **PMID format:** every `record.pmid` is a pure digit string, no `"PMID:"` prefix, no whitespace.
3. **Abstract handling:** when API returns no abstract, `record.abstract == ""` (empty string, NEVER None, NEVER invented text).
4. **`max_results=0`** returns empty list without hitting the network.
5. **Rate limit handling:** mock the HTTP client to return 429 → raises `RateLimitError`.
6. **Year filter:** `year_from=2020` filters out pre-2020 results.
7. **No LLM calls:** patch `common.llm_client.chat` to fail; tests pass.
8. **Spot-check traceability:** for a record returned in an integration test, open `https://europepmc.org/article/MED/<pmid>` and confirm the title matches. Automate this via a single `@pytest.mark.integration` test that does a live follow-up fetch and asserts title round-trip.

## Dependencies you can use

- `requests` — HTTP
- `pydantic` — schema
- (No LLM. No fancy parsing. No caching in v0.)

## Explicit non-goals

- Do NOT paraphrase abstracts. Return verbatim from the API.
- Do NOT invent PMIDs under any circumstances. If the API returns no results, return empty list. If the API returns malformed records, filter them out silently with a log warning — do not fabricate.
- Do NOT cache across runs in v0. Each call hits the API fresh.
- Do NOT call an LLM to re-rank results. Trust the API's relevance ordering.
- Do NOT scrape publisher websites. Europe PMC and PubMed only.

## Hallucination hazard reminder

This tool is the verifier's primary trust anchor for citations. The verifier will:
1. Re-fetch a sampled PMID and check that title + abstract round-trip.
2. Flag as hallucination if any record's PMID returns a 404 or mismatched content.

Your job: never let that happen. Every record returned is a real record, verbatim.

## First action — sanity check

Before coding, run this curl and confirm the response shape in your environment:
```bash
curl "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=glucose+metabolism&format=json&pageSize=3"
```
If the shape has drifted from the 2024 docs, adjust your parser accordingly and flag it to the maintainer.
