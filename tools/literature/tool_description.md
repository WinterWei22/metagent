# `literature_search`

## What it does
Searches Europe PMC (default) or PubMed for peer-reviewed literature matching a free-text query. Returns up to `max_results` `LiteratureRecord` objects, each guaranteed to have a real, numeric PMID that resolves on Europe PMC / PubMed. The tool never paraphrases, never invents — abstracts are returned verbatim from the API or as the empty string `""` when the source provides none.

## When to call it
- After you have shortlisted one or more candidate metabolites, to gather supporting literature for the final report.
- For background context on a metabolite, pathway, or disease the user mentions.
- To check whether a specific claim (e.g. "X is a biomarker for Y") has published support — phrase the query as the claim itself.

## When NOT to call it
- Do not call it to "rank" or "evaluate" candidates — it returns relevance-ordered results from the upstream API and does no scoring of its own.
- Do not call it to look up a database identifier (HMDB ID, KEGG ID). Use `fetch_metabolite_info` for that.
- Do not call it more than once for the same query in a single session — there is no caching, and identical queries return identical results.

## Inputs
- `query` (str, required) — free-text search. Boolean operators and field qualifiers (e.g. `AUTH:"Smith"`, `JOURNAL:"Nature"`) work for Europe PMC.
- `max_results` (int, default 5, max 50) — upper bound on returned records. Set to `0` if you want to no-op without hitting the network.
- `year_from` (int | None, default None) — filter to articles published in this year or later. Applied server-side.
- `sources` (list[Literal["pubmed", "europepmc"]], default `["europepmc"]`) — tried in listed order; the first source that returns a non-empty record list wins.

## Outputs
`LiteratureSearchResponse` with:
- `records: list[LiteratureRecord]` — each record has `pmid` (numeric string), `title`, `abstract` (verbatim, possibly `""`), `authors`, `year`, `journal`, optional `doi`, and `url` pointing at the article page on Europe PMC or PubMed.
- `query_used: str` — the actual query sent upstream (may include the auto-appended year filter).
- `explain: str` — a one-line factual summary of which source was used and how many records came back.

## How to interpret outputs
- An empty `records` list is a valid response — it means "no relevant literature found", not an error.
- Records are returned in the upstream API's relevance order. The verifier will spot-check the first few; trust that ordering.
- If you need more results, raise `max_results`. Do not page by issuing repeated calls — there is no pagination state in v0.

## Failure modes
- `RateLimitError` (code `RATE_LIMIT`, recoverable=True) — the upstream API returned HTTP 429. Back off and retry later, or switch to the other source.
- `LiteratureBackendError` (code `LITERATURE_BACKEND`) — the API was unreachable, returned a non-2xx, or returned malformed JSON/XML. Not retryable from the tool's side; surface to the user.

## Verifier contract
This tool is the report's primary citation trust anchor. The verifier will re-fetch a sampled PMID from Europe PMC and assert that title + abstract round-trip exactly. If a record returned here cannot be re-fetched, the report is rejected. The tool guarantees this by (a) only emitting records with `pmid` matching `^\d+$` and (b) never modifying the abstract text it received from the API.
