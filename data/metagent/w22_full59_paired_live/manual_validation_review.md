# W22 D7 Manual Validation Review

Date: 2026-06-15

Source candidate file: `data/metagent/w22_full59_paired_live/manual_validation_candidates.csv`

Validation method: opened the corresponding live dump under
`data/metagent/w22_full59_paired_live/path_x_full/{task_id}.json` and checked
the cited carrier row named by `source_field`.

## Result

- Checked: 20 candidate rows.
- Pipeline-lost-to-supported: 19 / 19 true.
- New contradicted: 0 / 1 true.
- Overall: 19 / 20 true = 95%.

## Notes

The 19 supported rows all matched the cited carrier row for pathway identity
plus rank/score. Covered carrier methods included `metaboanalystr_enrichment_result`
and `mummichog_enrichment_result`.

The only new `CONTRADICTED` row was a false positive:

- Task: `compound_only_enrich_mammalian_RAMP_P_000000398_seed1`
- Claim: `Galactose Metabolism (KEGG:hsa00052) was the top-ranked pathway in MetaboAnalystR KEGG PSEA with p = 9.533x10^-10, driven by five input metabolites.`
- Carrier: `metaboanalystr_enrichment_result.psea.pathways[0]`
- Carrier value: `score=9.533e-10`
- Verifier reason: parsed `9.533x10^-10` as `9.533`, so it incorrectly contradicted the score.

Interpretation: the live paired gain is credible for supported claims, but the
single new contradicted claim is a numeric notation parser false positive.
