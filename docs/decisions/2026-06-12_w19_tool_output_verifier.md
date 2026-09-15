# W19 Tool-output Verifier Decision

## Decision

W19 pivoted from KEGG REST to a verifier-side layer that checks ReAct's own reported tool-output claims against stored carrier data.

Close-out decision: **INCONCLUSIVE**.

The W19 layer is retained because it is technically valid and has small positive coverage. It is not counted as a successful UV-reduction sprint because the measurable signal was below ReAct rerun variance.

## Why The Pivot Happened

The initial KEGG REST audit found only 10 strict claims out of 624 W18 residual claims, for a ceiling of about 0.32pp. The ReAct tool-output audit found 55 strict claims out of 624, for a 2.94pp ceiling and a target around 1.76pp.

The pivot was approved because tool-output checks use data already produced by ReAct and stored by W17 carriers. This matched the verifier goal: check whether ReAct's own claims are supported by ReAct's own tool evidence before introducing another external KB.

## Scope

W19 verifies direct numeric, rank, overlap, and pathway-tool claims from:

- RaMP
- Mummichog
- MetaboAnalystR

Dispatcher constraints:

- Run only after existing verifier layers leave a claim `UNVERIFIABLE_V0`.
- Run only on the final iteration.
- Do not introduce a new verdict enum.
- Treat missing carriers or unparsed claims as `UNVERIFIABLE_V0`, not `CONTRADICTED`.
- Preserve trace JSONL through the main dispatcher.

## Implementation

Implemented components:

- `verifier/helpers/tool_output_claim_parser.py`
- `verifier/helpers/tool_output_lookup.py`
- `verifier/helpers/tool_output_trace.py`
- `verifier/helpers/tool_output_crash_preservation.py`
- `verifier/layers/tool_output_sub6.py`
- Dispatcher route in `verifier/agent.py`

Test coverage:

- parser tests
- lookup tests
- layer tests
- dispatcher integration tests
- trace and cost tests
- crash-preservation tests

Important implementation fix:

- `cecd4c2c fix(verifier): W19 tool-output tolerate rounded metrics`
- This added tolerance for rounded metrics and 1-based vs 0-based rank wording.

## D4 Results

### 5-task real smoke

- Valid tasks: 5 / 5
- Crashes: 0
- Iter-2 triggers: 0
- MiniMax cost from JSONL token counts: $0.5135
- W18 same-task UV rate: 44.93%
- W19 same-task UV rate: 36.96%
- Apparent UV drop: 7.97pp
- Final-iteration W19 trace: 34 UV, 0 supported, 0 contradicted

Interpretation: the system smoke looked numerically better, but attribution failed because W19 produced no final positive direct hits in that 5-task run.

### Full-59 real rerun

- Valid tasks: 59 / 59
- Crashes: 0
- Iter-2 triggers: 0
- Wall time: 125.8 min
- Actual MiniMax cost from JSONL token counts: $6.4428
- W19 D4 cumulative real-run cost including 5-task smoke: $6.9563
- W18 clean UV rate: 36.86%
- W19 full-59 UV rate: 42.12%
- UV increased by 5.26pp
- W18 pathway bridge: 52 / 59 = 88.1%
- W19 pathway bridge: 51 / 59 = 86.4%
- Final-iteration W19 trace: 14 supported, 6 contradicted, 362 UV

## D4.5 Regression Diagnosis

W19 D4.5 checked whether W19 UV results prevented W18 LLM-judge fall-through.

Findings:

- Same-text `SUPPORTED -> UNVERIFIABLE_V0`: 0
- Same-text `CONTRADICTED -> UNVERIFIABLE_V0`: 0
- W19 trace-UV rows present in final crosswalk: 642
- W19 trace-UV rows ending as supported/contradicted: 99
- Dispatcher code path still checks W18 LLM-judge after W19 returns UV

Conclusion: no dispatcher short-circuit bug was found. The regression is best explained by ReAct rerun variance and claim-set churn. W19's final positive signal was about 20 claims over 59 tasks, roughly 1pp scale, and was not large enough to survive a roughly 5pp rerun variance band.

## Lessons

- Rerun metrics and layer-attributable metrics must be reported separately.
- A true ReAct rerun can change the claim denominator enough to swamp a narrow verifier layer.
- Tool-output verification is high precision but low recall when final narratives do not preserve direct numeric tool claims.
- Dispatcher-level trace writing must be tested, not just helper-level trace writing.
- Rank claims need explicit one-based/zero-based tolerance.
- Numeric p-value/FDR claims need rounding tolerance to avoid false contradiction.
- Future UV sprint targets below 5pp need variance controls before they can be interpreted.

## W20 Recommendation

W20 should control ReAct variance before evaluating another UV-reduction layer.

Recommended options:

- Paired comparison: run both verifier variants over the same saved ReAct outputs.
- Seed lock where possible.
- Multi-run averaging when true ReAct reruns are required.
- Report baseline rerun variance in close-out if no paired replay is available.

For KEGG REST or any external KB layer:

- Require a strict ceiling above the ReAct variance band, or combine KB sources until expected coverage is above 5pp.
- Keep final-iteration-only dispatch.
- Keep trace JSONL mandatory.
- Preserve W18 LLM-judge fall-through.
- Do not add a new `ClaimVerdict` unless aggregate semantics are defined first.

## Progress Plain Summary

W19 先不做 KEGG,改成查 ReAct 自己工具输出,这个选择当时是合理的。实现也跑通了,但完整重跑时信号太小,被 ReAct 自己的波动盖住。

## Next Plain Summary

W20 不能只看一次重跑的 UV 数字。要么先把同一批 ReAct 输出固定住再比较 verifier,要么选一个预期降幅明显超过 5 个百分点的知识库方案。
