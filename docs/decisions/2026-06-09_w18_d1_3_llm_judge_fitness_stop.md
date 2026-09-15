# W18 D1.3 LLM-Judge Fitness Stop Decision

## Decision

Do not proceed to D2 implementation yet.

## Reason

D1.3 review found that the D1.2 judge-fitness audit is directionally useful but not reliable enough to authorize a verifier layer. The clean D1.2 rerun produced a large apparent target, but the 20-row independent spot-check agreement is only 15 / 20 = 75.0%, below the 80% gate.

## Corrected D1.2 Inputs

- D1.2 had a join-key bug: `claim_id` repeats across tasks, so joining W15 attribution to W17 carrier audit by `claim_id` polluted carrier metadata.
- The fix joins by `(claim_id, task_id_tail)` and preserves W17 `audit_id` when present.
- D1.2 also had an incomplete-batch issue: MiniMax sometimes returned fewer items than requested, and the script silently merged missing rows.
- The fix validates batch completeness and reruns incomplete cached batches.
- Batch size was reduced to 10 to avoid 8000-token JSON truncation.

## Clean D1.2 Result

- Command: `PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/w18_dual_audit_v3.jsonl python scripts/metagent/w18_dual_audit.py --llm-log logs/concord/w18_dual_audit_v3.jsonl`.
- Total UV claims classified: 901.
- `judge_strict`: 296 = 32.9%.
- `judge_uncoverable`: 605 = 67.1%.
- Strict ceiling: 14.76 pp of W17 UV.
- Target drop: 8.85 pp.
- Target UV rate: 36.07%.
- Actual MiniMax cost for v3 log: $0.2762 from `logs/concord/w18_dual_audit_v3.jsonl`.

## D1.3 Spot-Check Review

- Reviewed file: `data/metagent/w18_dual_audit/claim_judge_fitness_spot_check_reviewed.csv`.
- Agreement: 15 / 20 = 75.0%.
- Gate: >=80% required.
- Result: fail.

## Failure Pattern

The model over-labels `judge_strict` for claims that require external knowledge or unwired carriers:

- Molecular formula or compound identity claims that need chemistry lookup.
- Reactome hit claims without a Reactome carrier.
- Biological contribution phrases such as eicosanoid signal contribution.
- Ambiguous placement/status claims without a defined carrier field.

It also under-labels at least one Mummichog rank claim as uncoverable despite direct carrier-checkability.

## Implication

W18 beta should not implement `llm_judge_sub6` from this rubric. The likely next useful step is a narrower D1.4 rubric repair before any D2 RED:

- Require a concrete evidence pointer category for `judge_strict`.
- Ban `judge_strict` for KEGG/CHEBI/Reactome/EC/formula/reaction claims unless the relevant lookup output is already present in the source report.
- Treat generic `NONE` paradigm claims as uncoverable unless they reference source inputs or explicit all-carrier absence.
- Re-run a 20-row agreement check before implementation.
