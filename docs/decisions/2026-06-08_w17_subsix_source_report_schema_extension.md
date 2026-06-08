# W17 SubsixSourceReport Schema Extension

## Context

W16 D4 showed that `signal_sub6` compared method-labeled numeric claims against the single `ramp_enrichment_result` carrier. W17 alpha extends the data channel before any verifier layer is rebuilt.

The W17 decision is intentionally additive:

- Add nullable method-keyed carriers to `SubsixSourceReport`.
- Preserve existing `ramp_enrichment_result` behavior.
- Do not re-enable `signal_sub6`.
- Do not add a new verifier layer in W17 alpha.

## D1 Audit Findings

### D1.5/D1.6 Rubric Tightening

The v1 audit mixed tool-output carriers with database namespaces. D1.5 removed `KEGG` and `REACTOME` from the paradigm label set because `SubsixSourceReport` schema fields carry tool outputs, not pathway identifier namespaces.

D1.6 added explicit edge-case resolutions for generic MetaboAnalystR output, `MUMM:` signatures, Mummichog m/z-direct method labels, and RaMP database-vs-tool wording.

### Carrier Audit Crosstab

| paradigm | claim count | carrier exists before W17 | populated at runtime before W17 | missing carrier |
|---|---:|---|---|---|
| MUMMICHOG | 156 | no | no | yes |
| RAMP | 63 | yes | yes | no |
| METABOANALYSTR_PSEA | 49 | no | no | yes |
| METABOANALYSTR_MUMMICHOG | 1 | no | no | yes |

| paradigm | claim count | reason | recommended field |
|---|---:|---|---|
| MUMMICHOG | 156 | schema field missing | `mummichog_enrichment_result` |
| METABOANALYSTR_PSEA | 49 | schema field missing | `metaboanalystr_enrichment_result` |
| METABOANALYSTR_MUMMICHOG | 1 | schema field missing | `metaboanalystr_enrichment_result` |

### Approved Schema Fields

| new field name | type | source paradigms | nesting decision | priority | claim count |
|---|---|---|---|---|---:|
| `mummichog_enrichment_result` | `dict[str, Any] | None = None` | MUMMICHOG | single carrier | P1 | 156 |
| `metaboanalystr_enrichment_result` | `dict[str, Any] | None = None` | METABOANALYSTR_MUMMICHOG; METABOANALYSTR_PSEA | nested variants | P2 | 50 |
| `sspa_enrichment_result` | `dict[str, Any] | None = None` | SSPA | single carrier | P3 | 0 |
| `fella_enrichment_result` | `dict[str, Any] | None = None` | FELLA_DIFFUSION; FELLA_RWR | nested variants | P4 | 0 |

Explicitly not added:

- `kegg_enrichment_result`: KEGG is a database namespace, not a tool-output carrier.
- `reactome_enrichment_result`: Reactome is a database namespace, not a tool-output carrier.

## D3 Implementation Notes

### Schema Commit

Commit `969f6126` added four nullable carrier fields to `schemas/sub6_report.py`:

- `mummichog_enrichment_result`
- `metaboanalystr_enrichment_result`
- `sspa_enrichment_result`
- `fella_enrichment_result`

The commit body includes `[schema-extend-warning]`. Existing fields were not renamed, deleted, or retyped.

### Sub-case C Continuation

D3 initially stopped because Sub-case C was triggered: canonical `sub6b_task` rows did not preserve non-RaMP outputs. The only persisted task-level enrichment field was `ramp_enrichment_result`, and `tool_calls_trace` retained only `_payload_summary` rather than full normalized tool payloads.

The user authorized continuation with `go on`. The session then applied the minimum runner-bookkeeping expansion:

- `ConcordReactResult.enrichment_carriers` field.
- `ConcordReactRunner.run_task()` stores successful method-keyed payload `result` bodies.
- `ConcordReactRunner.verify_with_b1()` merges carriers into a copied task dict before `sub6b_task_to_subsix_source_report(...)`.
- `verifier_adapter.sub6b_task_to_subsix_source_report(...)` passes optional carrier fields through when present.

Tool handlers were untouched. B1-core helpers were untouched. Verifier layers were untouched.

### Warning Tag Convention

Commit `9630bdd8` introduced `[concord-modify-warning]` for `concord/agent/*.py` modifications. This tag is parallel to `[verifier-modify-warning]` and `[schema-extend-warning]` and should be added to standing workflow memory after review.

## Architectural Correction

The original W17 prompt sketched passthrough at handler level. D2 Step 0 grep showed the true `SubsixSourceReport` assembly boundary:

- `concord/agent/verifier_adapter.py:111` (`sub6b_task_to_subsix_source_report`)
- `concord/agent/react_runner.py:721` (`verify_with_b1` calls the adapter)

D3 corrected the design to adapter-focused implementation plus minimal runner carrier persistence. This avoids changing tool handlers and keeps carrier plumbing at the ConcordReactResult-to-verifier boundary.

## Wired vs Unwired Carriers

| Carrier | W17 schema-ready | W17 runtime-wired | Current source |
|---|---|---|---|
| `mummichog_enrichment_result` | yes | yes | `run_mummichog` |
| `metaboanalystr_enrichment_result["psea"]` | yes | yes | `run_metaboanalystr_psea` |
| `sspa_enrichment_result` | yes | yes | `run_sspa_ora` |
| `fella_enrichment_result["rwr"]` | yes | yes | `run_fella_rwr` |
| `metaboanalystr_enrichment_result["msea"]` | yes | no | wrapper exists, no LLM-exposed handler |
| `metaboanalystr_enrichment_result["mummichog"]` | yes | no | wrapper exists, no LLM-exposed handler |
| `fella_enrichment_result["diffusion"]` | yes | no | wrapper exists, no LLM-exposed handler |

Future handler additions should wire to existing sub-keys without further schema change.

## D4 Path X Verify

Command:

`PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/w17_path_x_post_schema_extend.jsonl python scripts/concord/w10_d4_path_x_full.py --benchmark data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl --output data/metagent/w17_path_x_post_schema_extend/path_x_full63_results.jsonl --summary data/metagent/w17_path_x_post_schema_extend/path_x_full63_summary.json --full-dir data/metagent/w17_path_x_post_schema_extend/path_x_full --llm-log logs/concord/w17_path_x_post_schema_extend.jsonl --max-react-turns 8 --max-feedback-iters 1 --k-concurrent 10`

Artifact commit: `385d7967`.

| Metric | W14 baseline | W16 D4 | W17 D4 | Target | Verdict |
|---|---:|---:|---:|---:|---|
| UV claim rate | 44.25% | 47.67% | 44.92% | 43.25-45.25% | PASS |
| UV count / denominator | 901 / 2036 | 880 / 1846 | 973 / 2166 | within +/-1pp | PASS |
| Supported claim rate | 34.48% | 26.38% | 31.90% | report | PASS |
| Pathway bridge accuracy | 54 / 63 = 85.7% | 51 / 63 = 81.0% | 57 / 63 = 90.5% | >=84% | PASS |
| iter-2 trigger count | 0 / 63 | 0 / 63 | 0 / 63 | 0 / 63 | PASS |
| iter-2 degraded rollback | 0 / 63 | 0 / 63 | 0 / 63 | 0 / 63 | PASS |
| Cost | $6.83 | $7.0502 | $6.4469 | <= $15 | PASS |
| Wall | 64.2 min | 47.9 min | 48.9 min | report | PASS |

Serialization round-trip check passed on `data/metagent/w17_path_x_post_schema_extend/path_x_full/compound_only_enrich_mammalian_RAMP_P_000000421_seed5.json`:

- `enrichment_carriers` present: true.
- JSON round-trip preserved a dict.
- Carrier keys: `metaboanalystr_enrichment_result`, `mummichog_enrichment_result`.

## Hard Gates

| Gate | Criterion | Result | Verdict |
|---|---|---|---|
| HG-1 | D1 carrier audit reaches acceptable calibration | v3 spot-check 19/20 = 95%; 824 full rerun clean | PASS |
| HG-2 | Approved schema fields exclude namespace-only carriers | no `kegg_enrichment_result`; no `reactome_enrichment_result` | PASS |
| HG-3 | D2 RED proves schema + passthrough absent before GREEN | 12 failed / 0 passed at commit `6409508d` | PASS |
| HG-4 | D3 GREEN preserves B1 compatibility | schema tests 7 passed; adapter tests 12 passed after GREEN | PASS |
| HG-5 | UV within +/-1pp of 44.25% | 44.92% | PASS |
| HG-6 | Pathway accuracy >=84% | 57 / 63 = 90.5% | PASS |
| HG-7 | iter-2 degradation = 0% | 0 iter-2, 0 degraded | PASS |
| HG-8 | Cost <= $15 | $6.4469 | PASS |
| HG-9 | Full repo 14-fail floor preserved | 14 failed, 1389 passed, 13 skipped, 1 xfailed | PASS |
| HG-10 | No B1-core helper modification | untouched | PASS |
| HG-11 | `signal_sub6` remains disabled | dispatcher catch-all not re-enabled | PASS |
| HG-12 | D5 close-out artifacts created | decision doc + close-out report + master logs | PASS pending report commit |

## W18 Beta Prerequisite Checklist

Schema fields now available for routing:

- `mummichog_enrichment_result`
- `metaboanalystr_enrichment_result["psea"]`
- `sspa_enrichment_result`
- `fella_enrichment_result["rwr"]`

W18 beta `signal_sub6` dispatcher rebuild design:

- Route by `mention.method` to matching carrier.
- Default to `UNVERIFIABLE_V0` when method has no carrier.
- Do not fuzzy-fallback to RaMP when a claim cites a different method.
- Pin source compatibility: `mention.method == "mummichog"` must look up in `mummichog_enrichment_result`, not any other carrier.
- Keep Reactome / KEGG namespace claims separate: they have no direct carrier and need W19 gamma KB tools or LLM-judge support.

## Memory Update Suggestions

Do not edit memory files directly in W17. Claude should apply these after review:

- Suggest `feedback_verifier_modification_policy.md`: add `[concord-modify-warning]` tag for `concord/agent/*.py` modifications as parallel to `[verifier-modify-warning]` and `[schema-extend-warning]`.
- Suggest `feedback_multi_paradigm_data_carrier_audit.md`: append D1.5 v3 lesson that rubric edge-case rules took three iterations and namespace-vs-tool boundary is the dominant ambiguity.

## Status

W17 alpha evidence parity foundation is complete. The carrier data path is now available for W18 beta source-aware signal verifier design, but no new verifier consumer has been enabled yet.
