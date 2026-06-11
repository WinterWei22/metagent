# W19 Tool-output Verifier Close-out Draft

## Status

W19 is partially closed after D4 Phase 1. The sprint pivoted from KEGG REST to verifier-side checks of ReAct's own tool outputs. The implementation is in place and tested, but the 5-task real smoke did not justify automatic full-59 continuation because final-iteration W19 trace had no positive direct hits.

## Sprint summary

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
| W18 same-task UV rate | 44.93% |
| W19 same-task UV rate | 36.96% |
| Apparent UV drop | 7.97pp |
| Final-iteration W19 supported trace rows | 0 |
| Final-iteration W19 contradicted trace rows | 0 |

## Hard gates

| Gate | Result |
|---|---|
| Cost cap | PASS: $0.5135 <= $3.5 Phase 1 cap |
| Crash count | PASS: 0 crashes |
| Iter-2 | PASS: 0 iter-2 triggers |
| Trace JSONL | PASS: `logs/concord/w19_path_x_post_tool_output_smoke_5task_tool_trace.jsonl` written |
| False CONTRADICTED | PASS on final iteration: 0 final W19 CONTRADICTED |
| Attribution | STOP: final W19 trace had 0 positive hits, so aggregate UV improvement is not cleanly attributable |

## W18 vs W19 5-task comparison

| Metric | W18 same 5 tasks | W19 5-task real smoke |
|---|---:|---:|
| Supported | 42 | 64 |
| Unsupported | 28 | 50 |
| Contradicted | 6 | 2 |
| UV | 62 | 68 |
| Denominator | 138 | 184 |
| UV rate | 44.93% | 36.96% |

The runner-level denominator changed because this was a true ReAct rerun, not replay over identical claim text. That makes the apparent UV drop useful as a system smoke signal, but not as a clean W19 layer effect estimate.

## Implementation notes

- Added `verifier/layers/tool_output_sub6.py`.
- Added parser, lookup, trace, and crash-preservation helpers under `verifier/helpers/`.
- Routed W19 layer after existing verifier layers leave a claim UV, final iteration only.
- No new `ClaimVerdict` value was introduced.
- `signal_sub6` remains disabled.
- W18 LLM-judge layer was not modified.

## W20 recommendation

Do not spend a full-59 budget on W19 without an explicit decision to measure overall ReAct rerun variance plus verifier behavior. For direct UV reduction, W20 should prioritize external KB coverage over the remaining 569 tool-output-uncoverable claims, starting with KEGG REST only if it can produce structured evidence that final narratives actually reference.

## Progress Plain Summary

W19 的代码是能跑的,也很便宜,但这次真实 5 个任务没有证明它在最终答案里直接消掉 UV。表面指标变好,更像重跑时 ReAct 自己写法变了。

## Next Plain Summary

建议先不要自动大跑 59 个任务。更稳的下一步是决定要不要专门测“整体重跑收益”,否则就把 W19 收成部分成果,把 W20 转向外部知识库。
