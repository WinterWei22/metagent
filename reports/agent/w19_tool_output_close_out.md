# W19 Tool-output Verifier Close-out Draft

## Status

W19 is closed as BELOW-TARGET after a user-approved full-59 real Path-X rerun. The sprint pivoted from KEGG REST to verifier-side checks of ReAct's own tool outputs. The implementation is in place and tested, but full-59 did not reduce UV; UV increased relative to W18 clean.

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
| Full-59 valid tasks | 59 / 59 |
| Full-59 crashes | 0 |
| Full-59 iter-2 triggers | 0 |
| Full-59 actual MiniMax cost | $6.4428 |
| W19 D4 cumulative real-run cost | $6.9563 |
| W18 clean 59-task UV rate | 36.86% |
| W19 full-59 UV rate | 42.12% |
| UV change | -5.26pp drop (UV increased) |
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

After user approval, full-59 was run anyway as a system measurement:

| Gate | Full-59 result |
|---|---|
| Cost cap | PASS: $6.4428 full-59, $6.9563 cumulative real-run cost |
| Crash count | PASS: 0 crashes |
| Iter-2 | PASS: 0 iter-2 triggers |
| Pathway bridge | PASS: 51 / 59 = 86.4% |
| UV target | FAIL: W18 36.86% → W19 42.12% |
| W19 trace | 14 final supported, 6 final contradicted, 362 final UV |

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

## W18 vs W19 full-59 comparison

| Metric | W18 clean 59 | W19 full-59 |
|---|---:|---:|
| Supported | 698 | 706 |
| Unsupported | 426 | 413 |
| Contradicted | 44 | 45 |
| UV | 682 | 847 |
| Denominator | 1850 | 2011 |
| UV rate | 36.86% | 42.12% |
| Pathway bridge | 52 / 59 | 51 / 59 |

## Implementation notes

- Added `verifier/layers/tool_output_sub6.py`.
- Added parser, lookup, trace, and crash-preservation helpers under `verifier/helpers/`.
- Routed W19 layer after existing verifier layers leave a claim UV, final iteration only.
- No new `ClaimVerdict` value was introduced.
- `signal_sub6` remains disabled.
- W18 LLM-judge layer was not modified.

## W20 recommendation

W19 should be closed below target. For direct UV reduction, W20 should prioritize external KB coverage over the remaining 569 tool-output-uncoverable claims, starting with KEGG REST only if it can produce structured evidence that final narratives actually reference.

## Progress Plain Summary

W19 的代码是能跑的,也很便宜,但完整 59 个任务没有降 UV。最终数字比 W18 更差,所以这条路线不能算成功。

## Next Plain Summary

建议把 W19 按 below-target 收尾。下一步应转向外部知识库,因为只查 ReAct 自己输出的覆盖面不够。
