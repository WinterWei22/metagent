# Semantic Match Manual Validation

Sample size: 20 semantic-hit tasks.
TP: 19/20 = 95.0%.

Rubric: exact normalized match, clear synonym, or same main biochemical cascade counts; broad neighboring pathway does not count.

| task_id | GT | predicted primary | verdict | note |
|---|---|---|---|---|
| hmdb_ramp_easy_kegg_RAMP_P_000000003_rep1 | Histidine metabolism | Histidine metabolism | TP | Exact normalized histidine metabolism match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000026_rep0 | Methionine Metabolism | Methionine Metabolism | TP | Exact normalized methionine metabolism match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000026_rep1 | Methionine Metabolism | Methionine and cysteine metabolism | TP | Methionine and cysteine metabolism is the KEGG sulfur-amino-acid pathway containing methionine metabolism. |
| hmdb_ramp_easy_kegg_RAMP_P_000000038_rep1 | Ketone Body Metabolism | Ketone Body Metabolism | TP | Exact ketone body metabolism match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000116_rep0 | Arginine and proline metabolism | Arginine and Proline Metabolism | TP | Case-only normalized arginine/proline match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000158_rep0 | Alanine, aspartate and glutamate metabolism | Alanine, aspartate and glutamate metabolism | TP | Exact alanine/aspartate/glutamate pathway match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000163_rep0 | Citric Acid Cycle | Citric Acid Cycle | TP | Exact citric acid cycle match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000163_rep1 | Citric Acid Cycle | Citric Acid Cycle | TP | Exact citric acid cycle match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000173_rep0 | Glycolysis / Gluconeogenesis | Glycolysis and Gluconeogenesis | TP | Glycolysis and gluconeogenesis is the same slash-separated pathway label. |
| hmdb_ramp_easy_kegg_RAMP_P_000000173_rep1 | Glycolysis / Gluconeogenesis | Glycolysis / Gluconeogenesis | TP | Exact glycolysis/gluconeogenesis match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000301_rep0 | Butyrate Metabolism | Butyrate Metabolism | TP | Exact butyrate metabolism match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000303_rep1 | Amino Sugar Metabolism | Amino Sugar Metabolism | TP | Exact amino sugar metabolism match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000345_rep0 | Fatty acid Metabolism | Fatty acid degradation | TP | Fatty acid degradation is a main operational subpathway of the broad fatty acid metabolism GT. |
| hmdb_ramp_easy_kegg_RAMP_P_000000345_rep1 | Fatty acid Metabolism | saturated_fatty_acids_beta_oxidation | TP | Saturated fatty acid beta-oxidation is a main fatty-acid metabolism subpathway. |
| hmdb_ramp_easy_kegg_RAMP_P_000000365_rep0 | Nicotinate and nicotinamide metabolism | Nicotinate and nicotinamide metabolism | TP | Exact nicotinate/nicotinamide metabolism match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000365_rep1 | Nicotinate and nicotinamide metabolism | Nicotinate and nicotinamide metabolism | TP | Exact nicotinate/nicotinamide metabolism match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000407_rep0 | D-Arginine and D-Ornithine Metabolism | D-Arginine and D-Ornithine Metabolism | TP | Exact D-arginine/D-ornithine metabolism match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000407_rep1 | D-Arginine and D-Ornithine Metabolism | D-Arginine and D-Ornithine Metabolism | TP | Exact D-arginine/D-ornithine metabolism match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000446_rep0 | Biosynthesis of unsaturated fatty acids | Biosynthesis of unsaturated fatty acids | TP | Exact unsaturated fatty acid biosynthesis match. |
| hmdb_ramp_easy_kegg_RAMP_P_000000446_rep1 | Biosynthesis of unsaturated fatty acids | Fatty acid degradation | FP | Fatty acid degradation is neighboring but not semantically equivalent to unsaturated fatty acid biosynthesis. |
