# Fix plan — `pathway_context` (Track D)

**Authored by:** D-E integration audit session (`main_de`), 2026-04-23
**Target owner:** Track D maintainer
**Branch:** `integration-day1` (branch from `63444f4`)
**Source:** findings from `reports/integration_report_de_2026-04-23.md`

This document routes the audit's findings into a **single actionable PR
plan**. The audit session was not authorised to modify tool source; the
fixes below are proposed, not applied. Each entry lists the exact file
and line numbers to change, a suggested diff shape, and a
test-to-add that would catch regression.

---

## 0. Summary of scope

| Findings | Strategy |
|---|---|
| **P-1** (CRITICAL), **P-5**, **P-6** (both MAJOR) | **Fix in v0** — one focused PR, estimated half a day. |
| **P-2**, **P-3**, **P-4** (all MAJOR, neighbour-list family) | **Document as known limitations in v0; redesign in v1.** Orchestrator / verifier does not consume neighbour fields in v0. |
| **D-1** (MAJOR data quirk) | **Documentation-only** update to `fetch_metabolite_info/tool_description.md`. |

No changes to `schemas/`, `common/`, `docs/TOOL_CONTRACTS.md`, or the
pipeline e2e tests are needed for the v0 fix PR.

---

## 1. Fix in v0 (single PR)

### P-1 — per-pathway `hit_count` (CRITICAL)

**File:** `tools/pathway_context/tool.py` lines 100–120
**Issue:** `hit_count = 1 + len(cooccurring)` assigns the same number to
every `PathwayEntry` in the response, regardless of which pathway the
focal and co-observed metabolites actually belong to. Schema and contract
intend a per-pathway count ("Count of queried metabolites (focal +
co-observed) present in this pathway").

**Proposed shape.** Pre-compute per-pathway membership once with a
single extra SQL, then compute `hit_count` inside the loop against that
index.

Sketch:

```python
# After `pathway_rows` and `cooccurring` are in hand, resolve each
# co-observed ID to its rampIds (we need them keyed per-metabolite, not
# flattened).
co_obs_analytes: list[ramp_backend.Analyte] = []
for cid in co_obs_clean:
    a = ramp_backend.resolve_analyte(conn, cid)
    if a is not None:
        co_obs_analytes.append(a)

# One SQL: for every pathway in pathway_rows and every queried rampId,
# which pathways contain which metabolites?
all_queried_ramps: set[str] = set(analyte.ramp_ids)
for a in co_obs_analytes:
    all_queried_ramps.update(a.ramp_ids)

membership: dict[str, set[str]] = ramp_backend.pathway_membership(
    conn,
    pathway_ramp_ids=[row.pathway_ramp_id for row in pathway_rows],
    metabolite_ramp_ids=all_queried_ramps,
)
# membership[pathway_ramp_id] -> set of rampIds in that pathway.

# Build each PathwayEntry with its own hit_count.
for row in pathway_rows:
    present = membership.get(row.pathway_ramp_id, set())
    hit = 0
    if set(analyte.ramp_ids) & present:
        hit += 1                                                 # focal
    for a in co_obs_analytes:
        if set(a.ramp_ids) & present:
            hit += 1                                             # each co-obs, once
    pathways.append(
        PathwayEntry(
            id=row.external_id or row.pathway_ramp_id,
            name=row.name,
            source=row.source,
            hit_count=hit,
            url=row.url,
        )
    )
```

**New helper** in `ramp_backend.py`:

```python
def pathway_membership(
    conn: sqlite3.Connection,
    *,
    pathway_ramp_ids: list[str],
    metabolite_ramp_ids: set[str],
) -> dict[str, set[str]]:
    """For each pathway in `pathway_ramp_ids`, which of the queried
    metabolites are members? One bounded SQL, no fan-out."""
    if not pathway_ramp_ids or not metabolite_ramp_ids:
        return {}
    p_ph = ",".join("?" for _ in pathway_ramp_ids)
    m_ph = ",".join("?" for _ in metabolite_ramp_ids)
    cur = conn.execute(
        f"SELECT pathwayRampId, rampId FROM analytehaspathway "
        f"WHERE pathwayRampId IN ({p_ph}) AND rampId IN ({m_ph})",
        (*pathway_ramp_ids, *metabolite_ramp_ids),
    )
    out: dict[str, set[str]] = {}
    for row in cur.fetchall():
        out.setdefault(row["pathwayRampId"], set()).add(row["rampId"])
    return out
```

**Test to add** (in `tests/tool_tests/test_pathway_context.py`, mock
RaMP — track is free to modify its own test file):

```python
def test_hit_count_varies_per_pathway(ramp_db):
    """A co-observed metabolite in only SOME pathways must lift hit_count
    on only those pathways, leaving the rest at 1."""
    resp = pathway_context(PathwayContextRequest(
        metabolite_id="HMDB0000122",        # glucose
        co_observed_ids=["HMDB0000161"],    # alanine — NOT in glycolysis,
                                            # but shares alanine metabolism
                                            # transitively through pyruvate (mini fixture doesn't)
    ))
    counts = sorted({p.hit_count for p in resp.pathways})
    # Before the fix, counts == {2} for every pathway. After, ≥ 2 values.
    assert len(counts) >= 2, f"hit_count must vary per pathway; got {counts}"
```

---

### P-5 — `network_neighbours` self-echo at `depth ≥ 2` (MAJOR)

**File:** `tools/pathway_context/ramp_backend.py` lines 359–372
**Issue:** `new_up = [x for x in step_up if x not in analyte.ramp_ids]`
— `x` is an external sourceId (`hmdb:HMDB0000122`) while
`analyte.ramp_ids` is a tuple of internal rampIds (`RAMP_C_...`). The two
namespaces never intersect, so the focal's own external IDs can appear
in its own neighbour list at `depth ≥ 2`.

**Proposed shape.** Compute the focal's external IDs once (back-query
`source` table), then compare against that.

```python
def network_neighbours(conn, analyte, *, depth):
    if depth <= 0:
        return [], []

    focal_external_ids = _focal_external_ids(conn, analyte.ramp_ids)

    # ... existing body, but replace the guards:
    new_up   = [x for x in step_up   if x not in up_ids   and x not in focal_external_ids]
    new_down = [x for x in step_down if x not in down_ids and x not in focal_external_ids]


def _focal_external_ids(conn, ramp_ids: tuple[str, ...]) -> set[str]:
    """The set of sourceId strings that map to any of the focal's rampIds.
    Used as a self-exclusion set at depth ≥ 2 so the focal never appears
    in its own neighbour list."""
    if not ramp_ids:
        return set()
    placeholders = ",".join("?" for _ in ramp_ids)
    cur = conn.execute(
        f"SELECT DISTINCT sourceId FROM source WHERE rampId IN ({placeholders})",
        ramp_ids,
    )
    return {r["sourceId"] for r in cur.fetchall() if r["sourceId"]}
```

**Test to add:**

```python
def test_depth_2_does_not_echo_focal(ramp_db):
    resp = pathway_context(PathwayContextRequest(
        metabolite_id="HMDB0000122", neighbour_depth=2,
    ))
    # Neither the raw HMDB ID nor its prefixed form should appear.
    for form in ("HMDB0000122", "hmdb:HMDB0000122"):
        assert form not in resp.upstream_neighbours, form
        assert form not in resp.downstream_neighbours, form
```

---

### P-6 — `cooccurrence_score` deflation on unresolvable co-obs (MAJOR)

**File:** `tools/pathway_context/tool.py` lines 40–56
**Issue:** The score denominator counts every syntactically distinct
co_obs ID, even ones that RaMP cannot resolve. A sample with 9
unresolvable IDs and 1 real match scores 0.1 rather than 1.0. Misleading
signal for the verifier.

**Proposed shape.** Pass the resolvable subset into
`_cooccurrence_score`, compute against that, and surface the drop count
in `explain` for transparency.

```python
def _cooccurrence_score(
    co_observed_ids: list[str],
    cooccurring_ids: set[str],
    resolvable_ids: set[str],
) -> tuple[float, int, int]:
    """Return (score, n_resolvable, n_total_unique).

    Score is `|matches| / |resolvable|`, so unresolvable IDs contribute
    nothing to the denominator. Callers use `n_resolvable` and
    `n_total_unique - n_resolvable` in the explain string so the user
    knows how much input was dropped."""
    if not co_observed_ids:
        return 0.0, 0, 0
    unique = {cid.strip() for cid in co_observed_ids if cid and cid.strip()}
    if not unique:
        return 0.0, 0, 0
    resolvable = unique & resolvable_ids
    if not resolvable:
        return 0.0, 0, len(unique)
    hits = sum(1 for cid in resolvable if cid in cooccurring_ids)
    return hits / len(resolvable), len(resolvable), len(unique)
```

The caller in `tool.py` needs `resolvable_ids` computed once:

```python
resolvable_ids = {
    cid for cid in co_obs_clean
    if ramp_backend.resolve_analyte(conn, cid) is not None
}
score, n_res, n_total = _cooccurrence_score(co_obs_clean, cooccurring, resolvable_ids)
```

And the explain template adds:

```python
if n_total > n_res:
    explain += f" ({n_total - n_res} co-observed IDs could not be resolved against RaMP.)"
```

**Contract compatibility.** The schema still only exposes a single
`cooccurrence_score: float ∈ [0, 1]` field — semantics change (denominator
is now resolvable, not input), but the field signature and range do not.
Update `docs/TOOL_CONTRACTS.md § Tool 6` with one sentence clarifying the
denominator choice; no schema bump needed.

**Test to add:**

```python
def test_unresolvable_co_obs_excluded_from_denominator(ramp_db):
    # 1 real glycolysis co-member + 9 unresolvable IDs.
    fake_ids = [f"HMDB{i:07d}" for i in range(9000000, 9000009)]
    resp = pathway_context(PathwayContextRequest(
        metabolite_id="HMDB0000122",
        co_observed_ids=["HMDB0000243"] + fake_ids,
    ))
    # Before the fix: 1/10 = 0.1. After: 1/1 = 1.0.
    assert resp.cooccurrence_score == pytest.approx(1.0)
    assert "could not be resolved" in resp.explain.lower()
```

---

### PR acceptance criteria

- All existing `tests/tool_tests/test_pathway_context.py` tests pass.
- Three new tests above pass.
- Integration harness passes on both mock and real backends:
  ```
  METAGENT_HMDB_PATH=… METAGENT_RAMP_PATH=… METAGENT_CFM_URL=… \
      pytest tests/integration/test_facts_d.py tests/integration/test_verifier_e.py -v
  ```
  (The integration tests do not currently pin `hit_count` values, so they
  will not break. If the Track D session wants to add one, see § 4 below.)
- `python scripts/audit_de.py` still exits 0 and reports the three tools
  as OK.
- Full-run `pytest tests/ -v` still passes at the same baseline as
  commit `63444f4` (52 pass / 1 skip / 1 pre-existing-failure on
  `test_prefilter_returns_at_least_one_candidate[lcarnitine_pos]`, which
  is unrelated, see audit finding D-1 / recommendation #8).

---

## 2. Documentation-only changes (land in the same PR, cheap)

### P-2 / P-3 / P-4 — document v0 limitations of the neighbour fields

**File:** `tools/pathway_context/tool_description.md`

Add, near the end, a new section:

```markdown
## Known limitations in v0

- **Direction collapse for central metabolites.** RaMP's reaction graph
  is densely reversible, so for central metabolites (pyruvate, glucose,
  L-alanine, etc.) `upstream_neighbours` and `downstream_neighbours`
  converge to set-identical lists. Treat them as an undirected
  neighbourhood for v0, not as a causal substrate→product chain.

- **Cofactor dilution.** Cofactors (H₂O, ATP, NADH, CO₂, H⁺, …) flagged
  `is_cofactor=1` in RaMP's `reaction2met` are NOT filtered. Neighbour
  lists for central metabolites are therefore dominated by cofactors
  rather than biologically specific partners.

- **Non-resolvable IDs.** Some neighbour entries carry `chebi:`,
  `rhea-comp:`, or `polymer:` prefixes — `fetch_metabolite_info` cannot
  resolve those. Consumers that plan to chain fetch(neighbour) → further
  lookups should pre-filter to `hmdb:` / `kegg:` IDs only.

- **Guidance.** In v0, orchestrator and verifier SHOULD NOT rank or
  select candidates by inspecting `upstream_neighbours` /
  `downstream_neighbours`. Use `pathways` and `cooccurrence_score`
  instead. A v1 redesign (reaction-direction filter + cofactor filter +
  HMDB/KEGG-only emit, possibly unified into a single
  `reaction_neighbours` field) is tracked as the P-2/3/4 follow-up.
```

### D-1 — document the zwitterion / protonation hazard

**File:** `tools/metabolite_info/tool_description.md`

Add:

```markdown
## Zwitterion / protonation hazard (data characteristic of HMDB)

HMDB's curated entries sometimes store the **protonated cation** of
zwitterionic species rather than the neutral form. Verified example:
L-carnitine (HMDB0000062) carries `molecular_formula="C7H16NO3"` and
`exact_mass≈162.113` — the proton is already in the mass; the
InChIKey ends `-O` (the protonation layer).

Downstream impact. A verifier that computes expected [M+H]⁺ as
`exact_mass + 1.00728` will miss the actual experimental precursor by
~1 Da for species stored in cation form.

**Recommended workaround.** When matching experimental precursors,
back-compute the neutral mass from `smiles` via RDKit
(`common.rdkit_utils.molecular_formula` / `inchikey`) rather than trusting
`exact_mass` blindly. The `smiles` field always encodes structure; the
`exact_mass` field encodes whatever protonation state the source DB chose.

This is a data-quality characteristic of HMDB, not a bug in this tool —
the tool propagates every field verbatim.
```

---

## 3. Deferred to v1 (no change in this PR)

### Neighbour-field redesign (P-2 / P-3 / P-4)

Three compounding problems, one coherent fix. Options to evaluate:

**Option A — keep direction, filter harder.** Add `AND is_cofactor = 0` to
`_neighbour_external_ids`; consult `reaction.direction` to drop
bidirectional reactions from the direction-specific queries; post-filter
the emitted IDs to `hmdb:` / `kegg:` prefixes. Preserves the current
API surface. Risk: `reaction.direction` values in RaMP v3 are mostly
`"left-to-right"` even for biochemically-reversible reactions, so this
may not actually produce distinct upstream / downstream sets.

**Option B — merge into a single `reaction_neighbours: list[str]` field.**
Drop the direction split entirely, emit one deduplicated list of HMDB /
KEGG IDs excluding cofactors. Simpler API, honest about what the data
supports. **Schema bump required** — adds a new field and (probably)
deprecates two. This would be the cleanest path.

**Option C — hybrid.** Keep `upstream_neighbours` / `downstream_neighbours`
but document them as "may be identical; treat as undirected"; add a new
`metabolic_partners: list[str]` field explicitly for the filtered HMDB-
/ KEGG-only cofactor-excluded list that the verifier would consume.
No breaking schema change; two list fields with distinct semantics.

**Recommended direction.** Option C. It preserves backward-compat,
lets the verifier consume the new field immediately, and lets the
direction fields continue to exist (in case someone later finds a use
for the full unfiltered graph, e.g. for pathway topology analysis).

Open questions before anyone starts Option C:

1. Does the orchestrator / verifier actually need a directed neighbour
   graph in v0 or v1? If "no" for both, Option B is simpler.
2. Is there a downstream consumer that ranks candidates by shared
   metabolic partners? If yes, `metabolic_partners` should probably
   carry a count / weight, not just be a list.

### Fixture refresh (D-2 / related)

`tests/fixtures/hmdb_ids/expected.json` is stale relative to the real
HMDB dump (glucose now α-form; L-carnitine now cation). Two options,
both deferred to v1:

- **Refresh the fixture** to match current HMDB, and document that the
  fixture is re-authored whenever the HMDB dump is refreshed.
- **Keep the fixture stable** (e.g. use generic / neutral forms) and add
  tolerant comparators to any test that currently does strict
  fixture-vs-tool match.

A decision on this would resolve the one pre-existing failure in
`test_pipeline_e2e.py::TestRealPoolPipeline::test_prefilter_returns_at_least_one_candidate[lcarnitine_pos]`.

---

## 4. Nice-to-have: new integration assertion for P-1

After the Track D PR lands, the D-E integration session recommends
adding one assertion to `tests/integration/test_facts_d.py` that pins the
per-pathway `hit_count` semantics so the bug cannot silently return:

```python
class TestPerPathwayHitCountMock:
    def test_co_observed_member_of_some_pathways(self, mock_ramp_db):
        """A co-observed metabolite that sits in SOME pathways with focal
        but not others must lift hit_count on only those pathways."""
        resp = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000122",                     # glucose
            co_observed_ids=["HMDB0000161"],                 # alanine —
                                                             # shares 0 pathways in mini RaMP
        ))
        # Glucose's pathways in the mock: glycolysis(kegg), glycolysis(reac).
        # Alanine is in neither in the mini fixture, so all hit_count == 1.
        assert all(p.hit_count == 1 for p in resp.pathways)

        resp2 = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000243",                     # pyruvate
            co_observed_ids=["HMDB0000122", "HMDB0000161"],  # glucose (shared glycolysis),
                                                             # alanine (shared alanine pathway)
        ))
        # pyruvate has pathways: glycolysis(kegg), glycolysis(reac), alanine(kegg).
        # Glycolysis pathways: hit_count = 1 (pyruvate) + 1 (glucose) = 2.
        # Alanine pathway:    hit_count = 1 (pyruvate) + 1 (alanine) = 2.
        assert all(p.hit_count == 2 for p in resp2.pathways)
```

This would be a cross-session contract on the hit_count semantics — the
Track D fix PR changes the code, the D-E integration session (or
whoever is next) can land this assertion. Adding it before the Track D
fix lands would cause it to fail; adding it after is how you prevent
regression.

The D-E session can own this test addition as a follow-up commit once
the Track D PR lands.

---

## 5. Out of scope

- Anything under `schemas/`, `common/`, `docs/TOOL_CONTRACTS.md`. The
  fix is purely in `tools/pathway_context/` + one text addition each to
  `tools/pathway_context/tool_description.md` and
  `tools/metabolite_info/tool_description.md`.
- MoNA-supplement wiring: the MoNA dump is not installed in this
  deployment (audit finding I-3). Not relevant to these fixes.
- CFM-ID / Track E: no change in scope. This plan is Track D only.
- Fixture refresh (D-2) / pre-existing lcarnitine e2e failure: deferred,
  see § 3.

---

## 6. Suggested PR shape

Branch from `integration-day1` tip `63444f4`:

```
fix(pathway_context): per-pathway hit_count + self-echo + score honesty

  P-1: compute hit_count per-pathway via pathway_membership helper.
  P-5: fix depth-2 self-echo — compare external IDs against focal's
       external IDs, not internal rampIds.
  P-6: cooccurrence_score denominator is now resolvable co-obs count;
       surface n_dropped in explain.
  Docs: add "Known limitations in v0" to pathway_context tool
       description; add "Zwitterion hazard" to fetch_metabolite_info
       tool description.

  Addresses findings P-1 / P-5 / P-6 / D-1 from
  reports/integration_report_de_2026-04-23.md. See
  reports/pathway_context_fix_plan_2026-04-23.md for the plan.

  No schema change. All existing tests pass; three new tests pin the
  new invariants.
```

Suggested diff budget: ~120 lines added, ~30 removed, spread across:

```
tools/pathway_context/tool.py                    |  ~40 lines
tools/pathway_context/ramp_backend.py            |  ~30 lines
tools/pathway_context/tool_description.md        |  ~20 lines
tools/metabolite_info/tool_description.md        |  ~15 lines
tests/tool_tests/test_pathway_context.py         |  ~40 lines (3 new tests)
```

---

*End of plan. Questions / pushback should go back to `main_de` (D-E
integration audit session). Route the ready PR through the integration-day1
branch; no merge-to-master is expected for v0.*
