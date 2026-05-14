# MetAgent Tool Call Usage

ReAct source: `data/eval/sub6/v4_a3_d3_no_lit/react`
Feedback source: `data/eval/sub6/v4_a3_d3_with_lit/feedback`

Name-level ReAct counts come from `narrative.json.tool_calls_log`.
Name-level feedback counts come from `persist/*/turns.jsonl`, which records feedback revision turns. `result.json` also records feedback-run total tool calls by iteration, including iter0.

- ReAct standalone: 407 calls across 63 tasks.
- Feedback revision turns with tool names: 112 calls across 41/63 tasks.
- Feedback full run total from `result.json`: 510 calls; iter0 tool names are not fully persisted in `turns.jsonl`.

## MetAgent-ReAct

| tool | group | calls | tasks with call |
|---|---|---:|---:|
| query_pathway_membership | Pathway evidence | 201 | 63 |
| query_kegg_path | Pathway evidence | 139 | 63 |
| query_ramp_enrichment | Enrichment | 64 | 63 |
| lookup_compound_info | Compound lookup | 3 | 3 |

## Feedback revision

| tool | group | calls | tasks with call |
|---|---|---:|---:|
| search_literature | Literature | 75 | 37 |
| query_pathway_membership | Pathway evidence | 24 | 14 |
| query_ramp_enrichment | Enrichment | 6 | 6 |
| query_kegg_path | Pathway evidence | 5 | 5 |
| lookup_compound_info | Compound lookup | 2 | 1 |

Generated files:

- `tool_calls_raw.csv`
- `tool_calls_by_tool.csv`
- `tool_calls_by_tool_raw_names.csv`
- `tool_calls_per_task.csv`
- `feedback_tool_calls_by_iteration.csv`
- `tool_calls_react_vs_feedback_by_tool.png/.pdf`
- `feedback_tool_calls_by_iteration.png/.pdf`
