# Integration delivery — Tracks D (fetch_metabolite_info, pathway_context) and E (predict_spectrum)

**Session:** `main_de` (integration session for fact backends + verifier backbone)
**Date:** 2026-04-23
**Branch:** `integration-day1` (tip `63444f4` at hand-off)
**Parent document:** `reports/delivery_day1_integration_2026-04-23.md` (Tracks A1/A2/B/C delivery)
**Authoritative detail:** `reports/integration_report_de_2026-04-23.md` (full audit with all findings, reproduction steps, red-team attempts)

This file is a **self-contained hand-off** for the D / E audit session.
Read this first; drill into the audit report for the evidence behind any
finding.

---

## 1. Executive summary

**What shipped.** Three trust-anchor tools (`fetch_metabolite_info`,
`pathway_context`, `predict_spectrum`) were audited end-to-end against
the live production backends (HMDB SQLite 217,920 rows, RaMP-DB v3
SQLite 1.95 GB, CFM-ID 4.4.7 shim at `http://127.0.0.1:8088`), verified
for hallucination resistance, and wrapped in a two-flavour integration
test harness (mock + real) plus a one-command smoke diagnostic.

**Honesty verdict.** 22 red-team inputs across the three tools, **zero
hallucinations**. All typed errors subclass `ToolError`; all Pydantic
round-trips clean; all requirements.txt pinned; InChIKey ↔ SMILES
structural self-consistency holds 10/10 for the fixture set.

**Trust-anchor readiness.**

- `predict_spectrum` — ✅ **ready.** Deterministic, `model_version` pinned,
  glucose/caffeine sanity peaks land where expected, invalid SMILES
  rejected before any HTTP call (tripwire-verified).
- `fetch_metabolite_info` — ✅ **ready with documented data caveat.**
  HMDB's curation stores some zwitterions as protonated cations
  (L-carnitine shows C₇H₁₆NO₃ / 162.113 Da). The tool propagates this
  honestly; the verifier MUST back-compute exact mass from SMILES when
  matching experimental [M+H]⁺ precursors — otherwise a 1 Da miss is
  baked in.
- `pathway_context` — ⚠️ **conditional.** `pathways`, `cooccurrence_score`,
  and `plausibility_summary` are trustworthy. **Do NOT wire the
  `upstream_neighbours` / `downstream_neighbours` fields into the
  verifier in v0** — they collapse to identical sets for central
  metabolites and return 42% IDs other tools cannot resolve. One
  CRITICAL and four MAJOR bugs on this tool (see § 4 below).

**No tool source was modified** by this session. Findings are reports, not
patches; follow-up fixes are routed back to the Track D maintainer
(§ 6).

---

## 2. Commits on `integration-day1` from this session

```
63444f4   test(tracks-D-E): integration harness + smoke diagnostic
97d8bc1   audit(tracks-D-E): integration report for fact backends + verifier
```

Both sit on top of `1ab3cd5` (Track D's RaMP v3 schema adapter + neighbour
speedup), which was already on the branch.

Prior to this session, tracks D and E had landed via:

```
1ab3cd5   fix(pathway_context): adapt to RaMP v3 schema + 170x neighbour speedup
796ad3b   feat(track_D): fetch_metabolite_info + pathway_context
2885f17   day 1: predict_spectrum (Track E)
```

Those are **not** part of this delivery — they are what this session
audited.

---

## 3. Files produced or modified

### New

| Path | Purpose | Lines |
|---|---|---|
| `reports/integration_report_de_2026-04-23.md` | Full audit with severity-labeled findings, Hallucination Red Team, verifier-readiness assessment, reproduction steps | 256 |
| `tests/integration/test_facts_d.py` | 17 tests for `fetch_metabolite_info` + `pathway_context` (7 Mock classes + 7 Real classes + 3 helpers) | 454 |
| `tests/integration/test_verifier_e.py` | 17 tests for `predict_spectrum` (mock + real paths, parametrised invalid-SMILES suite) | 358 |
| `scripts/audit_de.py` | One-command smoke diagnostic; table of tool / backend / status / elapsed / output | 282 |

### Modified (additive only)

| Path | What changed |
|---|---|
| `tests/integration/conftest.py` | Added `requires_hmdb_db` / `requires_ramp_db` / `requires_cfm_id` / `requires_pubchem_online` markers; env-presence fixtures; `build_mini_hmdb_sqlite` + `build_mini_ramp_sqlite` builders; CFM mock stdout map; `_respect_integration_flag_de` autouse scoped to the new markers only (the existing A/B/C autouse is untouched) |
| `tests/integration/README.md` | Added Track D / E section: file inventory, test list, skip-marker table, `audit_de.py` usage |

### NOT modified (scope boundary honoured)

No file under `tools/metabolite_info/`, `tools/pathway_context/`,
`tools/spectrum_predict/`, `schemas/`, `common/`, `docs/`, `prompts/`,
existing `tests/tool_tests/*`, or `tests/integration/test_pipeline_e2e.py`
was touched. Diff is confined to `reports/`, `scripts/`, and the new +
two modified files under `tests/integration/`.

---

## 4. Audit findings summary (top severities only)

Full detail in `reports/integration_report_de_2026-04-23.md`.

### CRITICAL (1)

- **P-1** — `pathway_context.PathwayEntry.hit_count` is a whole-response
  aggregate (`1 + len(cooccurring)`), not a per-pathway count. Every
  pathway in a response carries the same number. Verifier ranking by
  this field would give uniform scores. Reproduction in § R-1 of the
  audit.

### MAJOR (8, across all three tools)

- **D-1** — HMDB stores zwitterions (L-carnitine confirmed) as
  protonated cations; `exact_mass` already includes the proton. Data
  quirk, not tool bug, but verifier must be aware.
- **D-2** — HMDB0000122 resolves to α-D-glucopyranose
  (`kegg=C00221`, `inchikey=…-VFUOTHLCSA-N`), not the fixture's generic
  entry. Fixture drift.
- **P-2** — `upstream_neighbours == downstream_neighbours` as sets for
  all tested central metabolites (pyruvate 204==204, glucose 143==143,
  caffeine 10==10). Root cause is RaMP's densely reversible graph; not
  fixable in SQL alone without consulting `reaction.direction` or
  returning a single reaction-adjacency field.
- **P-3** — Neighbour IDs leak `chebi:`, `rhea-comp:`, `polymer:`
  prefixes (42% of pyruvate's 204 neighbours); `fetch_metabolite_info`
  cannot resolve any of them.
- **P-4** — No cofactor filter; `is_cofactor=1` rows (H₂O, ATP, NADH,
  H⁺, CO₂) count as neighbours and dilute the biologically-informative
  signal.
- **P-5** — `network_neighbours` self-echo at `depth ≥ 2`: focal's own
  HMDB ID appears in its own neighbour lists. Guard compares external
  sourceIds against internal rampIds (different namespaces, never
  intersect).
- **P-6** — `cooccurrence_score` silently deflates when co-observed IDs
  fail RaMP resolution — 9 unresolvable + 1 real match scores 0.1
  instead of 1.0.
- **X-1** — Cross-tool chain works for glucose, but the pivot compound
  is C00221 (not C00031); any downstream consumer hard-coding generic
  KEGG IDs will miss.

### MINOR (6) and INFRASTRUCTURE (3)

See audit report § 1, § 4 for the full table. Headline items:

- Empty-string inputs to all three tools raise `pydantic.ValidationError`
  rather than the typed `InvalidSmilesError` / `IdentifierFormatError`
  / `MetaboliteNotInNetworkError` — edge-case, but the error-type
  inconsistency matters if the orchestrator pattern-matches on `.code`.
- `cfm-id-4.4.7` is running; docs and tool_description still reference
  `cfm-id-4.0.0` as the example version string.
- `METAGENT_MONA_PATH` unset and no MoNA dump on disk; the MoNA
  fallback is dead code in this deployment.
- 22 adversarial red-team inputs (`""`, whitespace, Unicode control
  chars, SQL-injection shapes, typo/truncation HMDB IDs, off-by-one
  InChIKeys, uppercase names, unclosed rings, nonsense atoms): every
  one either clean-missed with `found=False` or raised a typed error
  with no network leak. **Zero hallucinations.**

---

## 5. Verification — how to re-run at hand-off

### One-command smoke

```bash
METAGENT_HMDB_PATH=/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite \
METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
METAGENT_CFM_URL=http://127.0.0.1:8088 \
python scripts/audit_de.py
```

Expected: exit 0, three OK rows, "All three tools ran against real
backends. READY." at the bottom. With any env var unset, exit 1 and the
missing backend gets a per-tool reason.

### Test suite

```bash
# Mock path only (no env needed):
pytest tests/integration/test_facts_d.py tests/integration/test_verifier_e.py -v

# Real path (all three env vars set as above):
pytest tests/integration/test_facts_d.py tests/integration/test_verifier_e.py -v

# With --integration, env-gated tests FAIL instead of skip:
pytest tests/integration/test_facts_d.py tests/integration/test_verifier_e.py -v --integration
```

Last verified run (2026-04-23 11:20 CST):

| Suite | Count | Result | Wall time |
|---|---|---|---|
| `test_facts_d.py` | 17 | ✅ all pass (mock + real) | 2.4 s |
| `test_verifier_e.py` | 17 | ✅ all pass (mock + real) | 21.9 s |
| `test_pipeline_e2e.py` (A/B/C) | 53 | 52 pass, 1 skip, 1 pre-existing failure | 6 min |

The 1 pre-existing failure (`test_prefilter_returns_at_least_one_candidate[lcarnitine_pos]`)
is caused by the same HMDB cation-vs-neutral data drift documented in
audit finding **D-1**; it is not a regression from this session. See the
audit report § 6 recommendation #8 for the fixture refresh that would
resolve it.

---

## 6. Follow-ups routed outside this session

Listed in descending priority. None of these were applied here — the
audit scope forbade touching the tools. Each lands on the Track D /
Track E maintainer to pick up.

| # | Owner | Severity | Summary |
|---|---|---|---|
| 1 | Track D | CRITICAL | P-1: compute `hit_count` per-pathway (1 extra SQL inside the pathway loop in `tools/pathway_context/tool.py`). |
| 2 | Track D | MAJOR | P-4: filter `is_cofactor=1` rows out of `_neighbour_external_ids`; expose `include_cofactors: bool = False` on request if needed. |
| 3 | Track D | MAJOR | P-3: drop non-HMDB/KEGG IDs from neighbour lists, or change the output to `list[PathwayNeighbour]` carrying `id_type`. |
| 4 | Track D | MAJOR | P-5: fix `network_neighbours` self-echo guard — compare against external sourceIds of the focal, not internal rampIds. |
| 5 | Track D | MAJOR | P-2: document the direction-collapse behaviour, or expose `reaction_neighbours` as a single field in v1. |
| 6 | Track D | MAJOR (data) | D-1: document in `tool_description.md` that HMDB stores protonated forms for zwitterions; advise verifier to back-compute `exact_mass` from SMILES. |
| 7 | Track E | MINOR | E-2: update example `model_version` strings in `docs/TOOL_CONTRACTS.md` and `tool_description.md` to match the shipped container (`cfm-id-4.x`). |
| 8 | maintainer | MINOR | D-2: refresh `tests/fixtures/hmdb_ids/expected.json` for glucose (α-form) and L-carnitine (cation), OR document the choice to keep generic values and add tolerant comparators in the affected tests. Resolving this also fixes the pre-existing A2 e2e failure. |

---

## 7. Scope compliance

### Scope given (from session brief)

> You MAY: create files under `tests/integration/`, create `scripts/audit_de.py`, create `reports/integration_report_de_<date>.md`, read any file.
>
> You MAY NOT: modify anything under `tools/metabolite_info/`, `tools/pathway_context/`, `tools/spectrum_predict/`, `schemas/`, `common/`, `docs/`, existing `tests/tool_tests/`, or `tests/integration/test_pipeline_e2e.py`. No LLM calls. Bugs get reported, not patched.

### Actual diff (entire session, two commits combined)

```
reports/integration_report_de_2026-04-23.md       | +256   (new)
reports/delivery_integration_de_2026-04-23.md     | + new  (this file)
scripts/audit_de.py                               | +282   (new)
tests/integration/test_facts_d.py                 | +454   (new)
tests/integration/test_verifier_e.py              | +358   (new)
tests/integration/conftest.py                     | +543 additive
tests/integration/README.md                       | + 89 additive
---------------------------------------------------------------
tools/** schemas/** common/** docs/** prompts/**  |   0
tests/tool_tests/**                               |   0
tests/integration/test_pipeline_e2e.py            |   0
```

No prohibited file touched. No LLM call made by any audit, test, or
script. All findings are in `reports/`; no bug fix was applied to any
tool source.

---

## 8. Index of related documents

- `reports/integration_report_de_2026-04-23.md` — **authoritative audit**
  with all findings, evidence, reproduction steps, and red-team attempts.
- `reports/delivery_day1_integration_2026-04-23.md` — parent integration
  delivery for A1/A2/B/C (prior session).
- `tests/integration/README.md` — how to run the D / E tests and
  interpret skip markers.
- `docs/TOOL_CONTRACTS.md` § Tools 5, 6, 7 — the contracts this audit
  verified against.

---

*End of delivery. Next session should consume this document + the audit
report, decide which of the § 6 follow-ups to schedule, and route them
to the Track D / Track E maintainer before v0 verifier work begins.*
