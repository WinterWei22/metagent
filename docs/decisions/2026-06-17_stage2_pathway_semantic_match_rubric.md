# Stage2 Pathway Semantic Match Rubric

Date: 2026-06-17

Project: MetAgent

Purpose: define one fixed rubric for `primary_semantic_match`, `topk_semantic_match`, and manual validation of pathway-prediction outputs.

## Match

Count as semantic match when at least one condition holds:

- Exact normalized pathway name match.
- Clear synonym match, e.g. `Vitamin B2 metabolism` ↔ `Riboflavin metabolism`.
- Same primary biochemical cascade under a common pathway-family name, e.g. `Arachidonic acid metabolism` ↔ `Eicosanoid synthesis`.
- Main-component subset that is the canonical operational pathway label for the task, e.g. `Fatty acid biosynthesis` ↔ `De novo fatty acid biosynthesis`.

## Non-Match

Do not count as semantic match when:

- The prediction is a broad merged parent class that adds extra pathway families, e.g. `Urea cycle` vs `Urea cycle/amino group metabolism`.
- The prediction is only a neighboring pathway that shares metabolites but not the same biochemical cascade.
- The prediction is a generic umbrella term such as `Metabolism`.
- The prediction covers only one component of a ground-truth collection.

## Collection Ground Truth

If the ground-truth pathway name explicitly joins multiple pathway components, the prediction must cover the named components as a collection. A prediction that matches only one component is not enough.

Example: `Tricarboxylic acid cycle and glyoxylate/dicarboxylate metabolism` is not fully covered by `Citrate cycle (TCA cycle)` alone.

## Reporting

Always report ID-exact and semantic metrics separately. Human1 and Recon2.2 namespace cases must keep ID-exact in their own column and must not convert semantic rescue into ID accuracy.
