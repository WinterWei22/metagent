# W17 Evidence Parity Close-Out

## Headline

W17 alpha evidence parity foundation is complete. W18 beta can build a source-aware `signal_sub6` verifier on top of method-keyed carriers without changing `SubsixSourceReport` again.

## Sprint Summary

| Phase | Status | Key number |
|---|---|---|
| D0 onboarding | PASS | baseline full floor 14 fail |
| D1 carrier audit v1 | partial | 35% spot-check, KEGG/REACTOME confusion |
| D1.5 v2 retry | partial | 70%, design-ambiguity edge cases |
| D1.5 v3 retry | PASS | 95% spot-check (19/20), 824 full rerun clean |
| D2 RED | PASS | 12 fail / 0 pass, commit `6409508d` |
| D3 GREEN schema | PASS | commit `969f6126`, 7 schema tests pass |
| D3 GREEN adapter + runner | PASS | commit `9630bdd8`, `[concord-modify-warning]`, 12 + 1 tests pass |
| D4 Path X verify | PASS | UV 44.92%, pathway 57/63 = 90.5%, cost $6.4469 |
| D5 close-out | PASS | this report + decision doc `0f039a35` |

## Hard Gates

| Gate | Criterion | Result | Verdict |
|---|---|---|---|
| HG-1 | D1 carrier audit calibration acceptable | v3 spot-check 19/20 = 95%; 824 full rerun clean | PASS |
| HG-2 | Namespace labels excluded as carriers | no `kegg_enrichment_result`; no `reactome_enrichment_result` | PASS |
| HG-3 | D2 RED proves missing schema/passthrough | 12 failed / 0 passed at `6409508d` | PASS |
| HG-4 | D3 GREEN preserves B1 compatibility | 7 schema tests pass; 12 focused W17 tests pass | PASS |
| HG-5 | UV within +/-1pp of 44.25% | 44.92% | PASS |
| HG-6 | Pathway accuracy >=84% | 57 / 63 = 90.5% | PASS |
| HG-7 | iter-2 degradation = 0% | 0 iter-2, 0 degraded | PASS |
| HG-8 | Cost <= $15 | $6.4469 | PASS |
| HG-9 | Full repo 14-fail floor preserved | 14 failed, 1389 passed, 13 skipped, 1 xfailed | PASS |
| HG-10 | B1-core helpers untouched | `claim_extractor`, `feedback_hints`, `_extract_classify` untouched | PASS |
| HG-11 | `signal_sub6` remains disabled | dispatcher catch-all not re-enabled | PASS |
| HG-12 | Close-out artifacts created | decision doc + report + master logs | PASS |

## D4 Metrics

| Metric | W14 baseline | W16 D4 | W17 D4 | Verdict |
|---|---:|---:|---:|---|
| UV claim rate | 44.25% | 47.67% | 44.92% | PASS |
| UV count / denominator | 901 / 2036 | 880 / 1846 | 973 / 2166 | PASS |
| Supported claim rate | 34.48% | 26.38% | 31.90% | report |
| Pathway bridge accuracy | 54 / 63 = 85.7% | 51 / 63 = 81.0% | 57 / 63 = 90.5% | PASS |
| iter-2 trigger count | 0 / 63 | 0 / 63 | 0 / 63 | PASS |
| iter-2 degraded rollback | 0 / 63 | 0 / 63 | 0 / 63 | PASS |
| Cost | $6.83 | $7.0502 | $6.4469 | PASS |
| Wall | 64.2 min | 47.9 min | 48.9 min | report |

## Cost

| Phase | Cost source | Cost |
|---|---|---:|
| D1/D1.5 carrier audit | `logs/concord/w17_carrier_audit.jsonl` | $0.2873 |
| D2 RED | no LLM calls | $0.0000 |
| D3 GREEN | no LLM calls | $0.0000 |
| D4 Path X | `logs/concord/w17_path_x_post_schema_extend.jsonl` | $6.4469 |
| Total W17 measured LLM cost | actual logs | $6.7342 |

## Files Added Or Modified

Committed W17 core files:

- `schemas/sub6_report.py`
- `concord/agent/react_runner.py`
- `concord/agent/verifier_adapter.py`
- `tests/test_w17_subsix_source_report_schema_extension.py`
- `tests/test_w17_wrapper_carrier_passthrough.py`
- `tests/concord/test_react_runner.py`
- `scripts/metagent/w17_d4_path_x_metrics.py`
- `tests/test_w17_d4_path_x_metrics.py`
- `data/metagent/w17_path_x_post_schema_extend/`
- `docs/decisions/2026-06-08_w17_subsix_source_report_schema_extension.md`
- `reports/agent/w17_evidence_parity_close_out.md`

Untracked but relevant audit artifacts from D1/D1.5 remain available for review under `data/metagent/w17_carrier_audit/`, `scripts/metagent/w17_carrier_audit.py`, and `tests/test_w17_carrier_audit.py`.

## Sprint Duration

D0 started on 2026-06-08 at approximately 17:08. D5 close-out completed on 2026-06-09 at approximately 02:00. Total elapsed wall time was about 8.9 hours, including one full Path X run and two full repo regression floors.

## Final State

- `SubsixSourceReport` has nullable method-keyed carriers.
- ReAct runtime preserves successful non-RaMP enrichment payloads in `ConcordReactResult.enrichment_carriers`.
- `verify_with_b1()` passes those carriers into the adapter using a copied task dict.
- Serialized Path X traces retain `enrichment_carriers` and round-trip as JSON.
- No new verifier consumer is enabled yet.
- `signal_sub6` remains dispatcher-disabled.

## W18 Recommendation

Start W18 beta with a source-aware `signal_sub6` rebuild or an LLM-judge alternative. The source-aware rebuild should route each mention by `mention.method` to the matching carrier and default to `UNVERIFIABLE_V0` when that carrier is absent.
