# pathway_context

Return pathway membership, immediate reaction-network neighbours, and a
co-occurrence-based plausibility score for one metabolite, optionally in
the context of other metabolites observed in the same sample. All data
comes from the local RaMP-DB SQLite dump, which integrates KEGG, Reactome,
SMPDB, and WikiPathways.

## Call it when

- A candidate has been shortlisted and you need biological context to
  judge whether it is a reasonable identification for the sample.
- The user asks "what pathways is X involved in?" or "is X plausible
  given we also saw Y and Z?".
- You are assembling the final report and need neighbour IDs to drive
  follow-up literature queries.

## Do NOT call it when

- You do not yet have a metabolite identifier — the input must resolve.
- You are looking for compound metadata (formula, mass, class, disease) —
  use `fetch_metabolite_info`.
- The organism is not human. v0 only supports `organism="hsa"`; a future
  release will switch RaMP's species-aware queries on.

## Input

| Field              | Type                 | Notes                                                                          |
| ------------------ | -------------------- | ------------------------------------------------------------------------------ |
| `metabolite_id`    | `str` (required)     | HMDB ID or KEGG compound ID. Prefixed forms (`hmdb:HMDB…`) are also accepted. |
| `organism`         | `str`                | Default `"hsa"`. v0 only tests human.                                          |
| `co_observed_ids`  | `list[str]`          | Other metabolite IDs seen in the same sample. Used for co-occurrence.         |
| `neighbour_depth`  | `int` (0–3)          | Reaction-graph BFS depth. 0 disables neighbour lookup entirely.                |
| `max_pathways`     | `int` (1–50)         | Cap on the number of pathway rows returned.                                    |

## Output

| Field                   | Type                            | Meaning                                                                   |
| ----------------------- | ------------------------------- | ------------------------------------------------------------------------- |
| `pathways`              | `list[PathwayEntry]`            | Each entry has id, name, source, hit_count, url.                          |
| `upstream_neighbours`   | `list[str]`                     | Metabolite IDs one reaction upstream of the focal compound.                |
| `downstream_neighbours` | `list[str]`                     | Metabolite IDs one reaction downstream.                                    |
| `cooccurrence_score`    | `float ∈ [0, 1]`                | Fraction of `co_observed_ids` that share ≥ 1 pathway with focal.           |
| `plausibility_summary`  | `str` (≤ 800 chars, ~120 words) | Templated natural-language paragraph naming the focal metabolite.         |
| `explain`               | `str`                           | One-line summary of the lookup.                                            |

`PathwayEntry.source` is one of `"kegg"`, `"reactome"`, `"smpdb"`,
`"wikipathways"`. Unknown RaMP pathway types are dropped silently to stay
inside the schema contract rather than silently invented.

## Failure modes

- **`RampUnavailableError`** — the SQLite file pointed to by
  `METAGENT_RAMP_PATH` is missing. Operator has to install the DB.
- **`MetaboliteNotInNetworkError`** — the identifier either does not
  resolve in RaMP's source table, or resolves but has no pathway rows
  in RaMP's curated set. These two cases are reported as one error
  because they are indistinguishable for reporting purposes.

## Determinism and trust

- **Zero LLM usage.** The `plausibility_summary` is a Python f-string
  composed from database-derived facts. The verifier can regenerate it
  from the same inputs deterministically.
- **No invented pathways, neighbours, or scores.** An empty list means
  the DB had no rows — not that the tool gave up.
- **`cooccurrence_score` is defined precisely** as `|{co_id : shares ≥ 1
  pathway with focal}| / |resolvable co_observed_ids|` after
  de-duplication. IDs the caller supplied that RaMP cannot resolve (typos,
  non-human metabolites, unknown accessions) are EXCLUDED from the
  denominator — the number dropped is surfaced in `explain`. An empty
  `co_observed_ids` list gives 0.0.

## Known limitations in v0

These are characteristics of the RaMP-DB data we cannot fix in the tool;
callers (orchestrator and verifier) must be aware of them.

- **Direction collapse for central metabolites.** RaMP's reaction graph is
  densely reversible, so for central metabolites (pyruvate, glucose,
  L-alanine, …) `upstream_neighbours` and `downstream_neighbours`
  converge to set-identical lists. Treat the two fields as an undirected
  neighbourhood in v0; do not read causality into the split.

- **Cofactor dilution.** Cofactors (H₂O, ATP, NADH, CO₂, H⁺, …) carry
  `is_cofactor=1` in RaMP's `reaction2met` but are NOT filtered. Neighbour
  lists for central metabolites are therefore dominated by cofactors rather
  than biologically specific partners.

- **Non-resolvable neighbour IDs.** Some neighbours surface with `chebi:`,
  `rhea-comp:`, or `polymer:` prefixes that `fetch_metabolite_info`
  cannot resolve. Consumers that plan to chain
  `fetch_metabolite_info(neighbour)` should pre-filter to `hmdb:` / `kegg:`
  prefixes.

- **Guidance.** In v0, orchestrator and verifier SHOULD NOT rank or
  select candidates by inspecting `upstream_neighbours` /
  `downstream_neighbours`. Use `pathways` and `cooccurrence_score`
  instead. A v1 redesign (reaction-direction filter + cofactor filter +
  HMDB/KEGG-only emit) is tracked as the P-2/3/4 follow-up in the Track
  D integration report.

## Setup

Download the latest RaMP-DB SQLite from
<https://github.com/ncats/RaMP-DB/releases> and export:

```bash
export METAGENT_RAMP_PATH=/data/ramp/ramp.sqlite
```

The dump is 1-2 GB depending on release and is never bundled with the
repository — it is entirely a runtime artefact. See
`tools/pathway_context/Dockerfile` for a reproducible container.
