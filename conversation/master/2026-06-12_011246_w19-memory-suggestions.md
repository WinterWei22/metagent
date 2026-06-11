# W19 Memory Suggestions

Do not edit Claude memory directly. Suggested updates:

## feedback_metagent_must_be_llm_driven

Add: W19 showed that verifier-side deterministic checks over ReAct tool outputs are safe and cheap, but direct yield can be low if final ReAct narratives do not emit parser-friendly numeric tool-output claims. Treat deterministic tool-output verification as a precision layer, not a broad replacement for LLM/KB verification.

## feedback_verifier_modification_policy

Add: Any new verifier layer that writes trace artifacts must have a dispatcher-integration test proving the main Path-X route writes the trace, not only a helper-level trace writer test.

## New possible memory: feedback_d4_gate_attribution.md

Add: When a rerun shows metric improvement, separate layer-attributable improvements from ReAct rerun variance before approving expensive full reruns. If final-iteration layer trace has zero positive hits, do not credit that layer for runner-level UV drop without explicit user approval.

## New possible memory: reference_tool_output_verifier_pattern.md

Add: W19 tool-output verifier pattern: final-iteration only, post-UV only, no new ClaimVerdict, cost_usd=0 trace rows, source-compatible carrier lookup, rounded numeric tolerance, one-based/zero-based rank tolerance, and explicit STOP if direct trace hits do not explain aggregate gains.

## Progress Plain Summary

这些建议主要是防止以后把“整体重跑变好”误算成“新层真的有效”。还建议以后 trace 不能只测 helper,必须测主流程真的写出来。

## Next Plain Summary

这些只是建议,我没有改 memory 文件。之后如果要固化规则,可以由你或 Claude 主对话挑选加入。
