# W19 Tool-output Verifier Decision Draft

## Decision

W19 pivoted from KEGG REST to a verifier-side tool-output layer that checks whether ReAct's own reported numeric tool outputs match stored carrier data.

## Why the pivot happened

The initial KEGG REST audit found only 10 strict claims out of 624 W18 residual claims, for a ceiling of about 0.32pp. The ReAct tool-output audit found 55 strict claims and a 2.94pp ceiling, with 90.0% spot-check agreement, so W19 prioritized the local deterministic layer and deferred KEGG REST to W20.

## Scope

- Verify direct numeric/rank/overlap claims from RaMP, Mummichog, and MetaboAnalystR carriers.
- Run only after existing verifier layers leave a claim UV.
- Run only on final iteration in the production dispatcher.
- Do not introduce a new verdict enum.
- Treat missing carriers or unparsed claims as UV, not CONTRADICTED.

## D4 Phase 1 result

The 5-task real Path-X smoke completed successfully and initially stopped before full-59 because attribution was ambiguous. The user then explicitly approved full-59 as a system rerun.

- 5 / 5 tasks valid.
- 0 crashes.
- 0 iter-2 triggers.
- MiniMax cost from JSONL token counts: $0.5135.
- W18 same-task UV rate: 44.93%.
- W19 same-task UV rate: 36.96%.
- Apparent UV drop: 7.97pp.
- Final-iteration W19 trace: 34 UV, 0 SUPPORTED, 0 CONTRADICTED.

## Interpretation

The apparent UV drop passes the numeric smoke threshold, but attribution fails: final-iteration W19 trace produced no positive direct hits. The improvement is therefore likely caused by ReAct rerun variance and changed final claim text rather than the new deterministic verifier layer.

Because the approval file required stopping on any hard-gate ambiguity, full-59 was not run.

## Full-59 result

Full-59 was subsequently run after explicit user approval.

- 59 / 59 valid tasks.
- 0 crashes.
- 0 iter-2 triggers.
- Wall time: 125.8 min.
- Actual MiniMax cost from JSONL token counts: $6.4428.
- W19 D4 cumulative real-run cost including 5-task smoke: $6.9563.
- W18 clean UV rate: 36.86%.
- W19 full-59 UV rate: 42.12%.
- UV change: -5.26pp drop, i.e. UV increased.
- W18 pathway bridge: 52 / 59 = 88.1%.
- W19 pathway bridge: 51 / 59 = 86.4%.
- Final-iteration W19 trace: 14 supported, 6 contradicted, 362 unverifiable_v0.

Decision: W19 is BELOW-TARGET. The layer is technically valid and cheap, but the full system rerun did not lower UV.

## Lessons

- Helper-level trace tests are insufficient; the dispatcher must prove it writes trace rows in real routing.
- Direct tool-output verification is high precision but low recall when final narratives do not preserve numeric tool-output claims.
- Rerun metrics must be separated from layer-attributable metrics.
- A full rerun can expose the opposite of a 5-task smoke signal; use the full result for close-out if both exist.
- Rank claims need explicit one-based/zero-based tolerance.
- Numeric p-value/FDR claims need rounding tolerance to avoid false CONTRADICTED verdicts.

## W20 checklist

- Decide whether KEGG REST should target the 569 ReAct-tool-output-uncoverable residual claims.
- Require structured evidence extraction that final narratives can actually reference.
- Keep final-iteration-only dispatch.
- Keep trace JSONL mandatory and wired through the main dispatcher.
- Separate replay/layer attribution metrics from true rerun metrics.
- Do not add a new `ClaimVerdict` unless aggregate semantics are defined first.

## Progress Plain Summary

W19 的方向从 KEGG 改成先查 ReAct 自己工具输出,这个决策当时有依据。但完整 59 个任务跑完后,UV 没降,反而升了。

## Next Plain Summary

所以 W19 应该按 below-target 收尾,不要包装成成功。W20 更应该处理这层查不到的剩余 claim,而不是继续扩大一个命中很少的查表层。
