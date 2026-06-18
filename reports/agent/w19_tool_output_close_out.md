# W19 Tool-output Verifier Close-out

## Status

W19 is closed as **INCONCLUSIVE**.

The tool-output verifier layer is technically valid, cheap, and produced a small positive final-iteration signal. It did not produce a measurable full-system UV reduction because the signal was below ReAct rerun variance.

## Sprint Summary

| Item | Result |
|---|---:|
| Initial KEGG strict claims | 10 / 624 |
| ReAct tool-output strict claims | 55 / 624 |
| ReAct tool-output ceiling | 2.94pp |
| D1.5 spot-check agreement | 18 / 20 = 90.0% |
| D4 Phase 1 valid tasks | 5 / 5 |
| D4 Phase 1 crashes | 0 |
| D4 Phase 1 iter-2 triggers | 0 |
| D4 Phase 1 actual MiniMax cost | $0.5135 |
| Full-59 valid tasks | 59 / 59 |
| Full-59 crashes | 0 |
| Full-59 iter-2 triggers | 0 |
| Full-59 actual MiniMax cost | $6.4428 |
| W19 D4 cumulative real-run cost | $6.9563 |
| W18 clean 59-task UV rate | 36.86% |
| W19 full-59 UV rate | 42.12% |
| UV change | UV increased by 5.26pp |
| W18 pathway bridge | 52 / 59 = 88.1% |
| W19 pathway bridge | 51 / 59 = 86.4% |
| Final-iteration W19 supported trace rows | 14 |
| Final-iteration W19 contradicted trace rows | 6 |
| Final-iteration W19 UV trace rows | 362 |

## D4.5 Regression Diagnosis

The D4.5 audit checked whether W19 tool-output UV verdicts accidentally blocked W18 LLM-judge fall-through.

Artifacts:

- `data/metagent/w19_d4_regression_audit/claim_verdict_crosswalk.csv`
- `data/metagent/w19_d4_regression_audit/dispatch_fallthrough_evidence.md`
- `data/metagent/w19_d4_regression_audit/regression_summary.json`
- `conversation/master/2026-06-12_142952_w19-d4-regression-diagnosis.md`

Diagnosis:

| Check | Result |
|---|---:|
| Same-text `SUPPORTED -> UNVERIFIABLE_V0` regressions | 0 |
| Same-text `CONTRADICTED -> UNVERIFIABLE_V0` regressions | 0 |
| W19 trace-UV rows in final crosswalk | 642 |
| W19 trace-UV rows ending as supported/contradicted | 99 |
| Dispatcher short-circuit evidence | Not found |

Conclusion: W19 did not break the W18 LLM-judge route. The full-59 regression is best explained by ReAct rerun variance and claim-set churn. W19 added about 20 final positive trace rows, roughly 1pp of possible signal, while the rerun moved the aggregate UV rate by about 5pp.

## Implementation Notes

- Added `verifier/layers/tool_output_sub6.py`.
- Added parser, lookup, trace, and crash-preservation helpers under `verifier/helpers/`.
- Routed W19 after existing verifier layers leave a claim UV, final iteration only.
- Wrote dispatcher-level trace rows via `METAGENT_TOOL_OUTPUT_TRACE_PATH`.
- No new `ClaimVerdict` value was introduced.
- `signal_sub6` remains disabled.
- W18 LLM-judge layer was not modified.
- W19 code is retained because it has small positive coverage and no evidence of dispatcher damage.

## Interpretation

The W19 pivot was reasonable because KEGG REST strict coverage was too small for W19, while ReAct tool-output strict coverage was larger and locally checkable. The implementation did what it was meant to do on a narrow slice: it checked RaMP, Mummichog, and MetaboAnalystR claims against stored carrier data at zero verifier-side LLM cost.

The close-out result is not a clean failure of the layer, but it is not a measurable success either. A 1pp layer-attributable signal cannot be trusted when the full ReAct rerun can move UV by about 5pp.

## W20 Recommendation

W20 should not proceed on a target below the rerun noise floor unless variance is controlled.

Recommended constraints:

- Use seed lock, paired comparison over the same ReAct output, or multi-run averaging.
- Treat targets under 5pp as hard to interpret without variance controls.
- If using KEGG REST, require a strict ceiling above the noise floor or combine it with a broader KB/tool plan.
- Continue preserving W19 trace JSONL and final-iteration-only dispatch patterns.

## Progress Plain Summary

W19 的代码层是能用的,也没有把 W18 的 LLM 判断截断。但它真正多救回来的 claim 太少,完整重跑时被 ReAct 自己的波动盖住了。

## Next Plain Summary

W19 收为 inconclusive,不是包装成成功,也不是删代码。W20 要先控 ReAct 重跑方差,或者选一个预期降幅明显超过 5 个百分点的知识库方向。
