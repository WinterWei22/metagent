# W19 D4 Phase 1 5-task Real Smoke Result

## What was requested

Run the approved W19 D4 5-task real Path-X smoke with the W19 tool-output verifier enabled, write LLM and tool-output traces, enforce the $3.5 Phase 1 cap, then decide whether to continue to full-59.

## What was done

- Added and committed W19 dispatcher trace wiring before the run because the helper existed but the main route did not write JSONL trace rows.
- Generated `data/metagent/w19_path_x_post_tool_output_smoke_5task/smoke_5task.jsonl` with 5 selected tasks.
- Ran true Path-X with `k-concurrent=1`, `max-feedback-iters=1`, `judge-cost-cap-usd=3.5`.
- Output: `data/metagent/w19_path_x_post_tool_output_smoke_5task/path_x_5task_results.jsonl`.
- Summary: `data/metagent/w19_path_x_post_tool_output_smoke_5task/path_x_5task_summary.json`.
- Full dumps: `data/metagent/w19_path_x_post_tool_output_smoke_5task/path_x_full/`.
- LLM log: `logs/concord/w19_path_x_post_tool_output_smoke_5task.jsonl`.
- W19 tool trace: `logs/concord/w19_path_x_post_tool_output_smoke_5task_tool_trace.jsonl`.

## Smoke metrics

- Tasks: 5 / 5 valid.
- Crashes: 0.
- Iter-2 triggers: 0.
- Wall: 42.0 min.
- LLM calls: 84.
- Prompt tokens: 1,063,225.
- Completion tokens: 162,118.
- Actual MiniMax cost from JSONL token counts: $0.5135.
- Phase 1 cap: PASS ($0.5135 <= $3.5).
- W18 same-task UV rate by runner counts: 44.93%.
- W19 same-task UV rate by runner counts: 36.96%.
- Apparent UV drop: 7.97pp.
- Final-iteration W19 tool-output trace verdicts: 34 `unverifiable_v0`, 0 `supported`, 0 `contradicted`.
- Non-final W19 tool-output trace verdicts: 1 `supported`, 4 `contradicted`, 50 `unverifiable_v0`.

## Gate decision

STOP before Phase 2.

The apparent runner-level UV drop is above the 1.5pp threshold and final-iteration W19 trace has 0 CONTRADICTED. However, final-iteration W19 trace also has 0 SUPPORTED. The observed UV drop is therefore not attributable to the new deterministic W19 layer; it is likely dominated by ReAct rerun variance and rollback/final-iteration differences.

Because the Claude instruction says any hard-gate ambiguity must stop, I did not launch full-59.

## Current status

Phase 1 completed technically, but Phase 2 is blocked on attribution ambiguity.

## Next step

User/Claude should decide whether to run full-59 anyway as a ReAct+verifier system measurement, or stop W19 as a low-direct-yield deterministic layer and move W20 toward KEGG REST / broader external KB coverage.

## Progress Plain Summary

5 个任务真实跑完了,没有崩,花费也很低。表面上 UV 降了不少,但新加的查表层在最终结果里没有直接命中,所以这个降幅不能算它的功劳。

## Next Plain Summary

我没有继续跑 59 个任务,因为继续跑会花钱但结论可能不干净。下一步需要决定:要不要把它当整体系统重跑继续测,还是承认这条确定性查表路线直接收益不够,转去更宽的知识库路线。
