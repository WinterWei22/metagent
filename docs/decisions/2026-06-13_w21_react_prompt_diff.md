# W21 ReAct Prompt Diff Draft

Status: proposed only. Do not apply to production prompt until D2 approval.

## Target

Production prompt file:

- `prompts/concord/concord_react_prompt.md`

Loader:

- `concord/agent/system_prompts.py`

## Proposed Insertion Point

Append this section after the existing `### Hard rules` block and before `### Decision rule — when to stop calling tools`.

## Proposed Section

```markdown
### Claim Discipline

Separate your final claims into two kinds. Do not blur evidence-backed facts and biological interpretation into the same sentence.

1. **Factual claims** — anything you state as a tool result must cite a concrete evidence source by tool name and identifier.
   - Good: "run_mummichog top pathway MUMM:glycine_serine_and_threonine_metabolism has p=1.27e-19."
   - Good: "query_pathway_members(WP:WP167) returned KEGG:C00219 as a member of Eicosanoid synthesis."
   - Bad: "Glycine metabolism appears relevant." If this is a tool result, cite the tool and identifier; if it is interpretation, label it as a hypothesis.

2. **Hypothesis claims** — biological interpretation, mechanism, or cross-tool synthesis that goes beyond a single tool's direct output must be explicitly labelled as hypothesis.
   - Good: "Hypothesis: the shared RaMP and mummichog signal suggests one-carbon metabolism may be central to the phenotype."
   - Good: "Hypothesis: because Mummichog and MetaboAnalystR both rank arachidonic-acid-related pathways highly, eicosanoid turnover may explain the treatment effect."
   - Bad: "Eicosanoid turnover explains the treatment effect." This states an interpretation as fact.

3. **Do not mix them** — first state the evidence-backed fact, then separately state any hypothesis.
   - Good: "Fact: run_ramp_enrichment ranked WP:WP167 Eicosanoid synthesis first. Hypothesis: this may indicate an oxidative lipid-signalling response."
   - Bad: "WP:WP167 proves an oxidative lipid-signalling response."

You are encouraged to make biological hypotheses. That is part of your value as an LLM agent. Just label them honestly so they are not mistaken for measured facts.
```

## Intended Effect

This draft does not ban biological interpretation. It separates:

- facts that claim direct support from tool output, and
- hypotheses that are useful interpretation but should not pretend to be direct measurements.

The D2.0 blocker remains: the verifier currently has no known special handling for `Hypothesis:` labels. Pilot must not run until Claude/user decides whether verifier should classify those claims into a non-UV bucket.

## D1.2 Rule Check

| Rule | Status |
|---|---|
| B1-core helpers untouched | PASS |
| W17 schema untouched | PASS |
| Claim grammar fields untouched | PASS |
| `DEFAULT_MAX_FEEDBACK_ITERS=1` untouched | PASS |
| LLM-driven principle preserved | PASS |
| Production prompt untouched in D1 | PASS |
| Verifier untouched in D1 | PASS |

## D1.3 Dry-run Plan

The dry-run loads the current production prompt through `concord.agent.system_prompts`, appends the proposed section in memory only, and confirms a mock message list can be built without editing `prompts/concord/concord_react_prompt.md`.

## 大白话进展

这份草稿不是让模型少想,而是让它把两类话分开:工具直接支持的事实,和自己做出的解释假设。

## 大白话下一步

草稿如果通过,下一步不能直接试跑。要先确认 verifier 看到 `Hypothesis:` 时该怎么算,否则模型标了也可能照样被打成无法验证。
