# W20 KEGG KB Audit Decision

## Decision

W20 KEGG REST is closed at audit stage as **INCONCLUSIVE / GATE-STOPPED**.

No KEGG REST verifier layer is implemented in W20.

## Audit Design

W20 applied the W19 variance lesson: do not run another full ReAct rerun unless the layer has enough expected signal. The D1 audit reviewed the W19 residual `tool_uncoverable` claims and classified them into:

- `kegg_strict`: explicit KEGG compound/pathway/reaction evidence that KEGG REST can directly check.
- `kegg_fuzzy`: KEGG-like or pathway language that needs name mapping, namespace repair, or interpretation.
- `kegg_uncoverable`: no direct KEGG REST surface.

## Results

Input: 569 W19 `tool_uncoverable` claims.

| Label | Count |
|---|---:|
| `kegg_strict` | 38 |
| `kegg_fuzzy` | 59 |
| `kegg_uncoverable` | 472 |

By type:

| claim_type | strict | fuzzy | uncoverable |
|---|---:|---:|---:|
| BIOLOGICAL | 0 | 14 | 113 |
| CONSISTENCY | 0 | 1 | 38 |
| DRIVER_METABOLITE | 0 | 1 | 34 |
| FACTUAL | 28 | 29 | 68 |
| GROUNDED | 10 | 8 | 117 |
| OTHER | 0 | 2 | 47 |
| PATHWAY_RELATIONSHIP | 0 | 3 | 39 |
| SET_ENRICHMENT | 0 | 1 | 16 |

The strict ceiling is `2.03pp` against the W18 denominator. The strict + fuzzy upper bound is `5.18pp`, but fuzzy claims require extra name mapping or interpretation and are not counted as strict implementation evidence.

D1.2 spot-check confirmed that the strict subset is real:

- 20 / 20 sampled strict rows resolved through KEGG REST `get`.

## Stop Rationale

The W20 gate requires stopping below 3pp strict ceiling. The observed strict ceiling is 2.03pp.

Multi-KB expansion was not pursued because this would shift from a narrow audit into a larger router project without evidence that the union strict ceiling clears the new verifier-side threshold. W19 and W20 both point to marginal returns on verifier-side add-ons.

## W21 Direction

W21 should move to ReAct source-side output discipline.

The updated W21 strategy is not to ban inference. It should require:

- factual claims to cite concrete evidence,
- inferential claims to be explicitly labelled as `Hypothesis:`,
- fact and inference to be separated so verifier accounting can distinguish them.

Before any pilot, W21 must decide how the verifier treats hypothesis-labelled claims. That decision must be made before changing verifier code.

## Progress Plain Summary

KEGG 这条路已经审完。严格可直接验证的空间太小,不值得现在做成新工具层。

## Next Plain Summary

W21 换方向,从 ReAct 写答案的方式下手。重点不是禁止推断,而是让模型把事实和假设分清楚。
