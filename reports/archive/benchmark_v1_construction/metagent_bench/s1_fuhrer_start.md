# S1 Fuhrer 2017 启动结果

日期：2026-05-25  
输入目录：`/data/weiwentao/llm_agent_metabolomics/data/landscape/S1_fuhrer_sauer_2017/`  
输出目录：`/data/weiwentao/llm_agent_metabolomics/data/landscape/S1_fuhrer_sauer_2017/derived/`

## 已完成

新增可复跑脚本：`scripts/landscape/extract_s1_fuhrer.py`

脚本只结构化已下载补充材料，不做新的离子注释：

- `Table_EV1.xlsx` -> `derived/ev1_table_ev1a.tsv`, `derived/ev1_table_ev1b.tsv`
- `Table_EV3.zip` -> `derived/ev3_gene_summary.tsv`, `derived/ev3_detail_tables.jsonl`, `derived/ev3_section_counts.tsv`
- `Table_EV4.xlsx` -> `derived/ev4_annotation_candidates.tsv`
- 初筛候选 -> `derived/s1_task_seed_candidates.tsv`

## 提取计数

| 项 | 数量 |
|---|---:|
| EV1 Table EV1A rows | 4,324 |
| EV1 Table EV1B rows | 7,534 |
| EV4 annotation candidates | 4,019 |
| EV4 negative mode candidates | 2,191 |
| EV4 positive mode candidates | 1,828 |
| EV3 gene summary rows from index | 956 |
| EV3 detail rows total | 234,123 |
| EV3 genes with CLR section | 1,273 |
| EV3 genes with Differential ions section | 1,004 |
| EV3 genes with KEGG pathway by CLR section | 847 |
| EV3 genes with Predicted metabolites from CLR section | 956 |
| Preliminary task seed candidates (`q <= 0.05`, `diff_ions_hits >= 10`) | 418 |

## 关键判断

S1 可以继续推进，但 gold label 不能直接取 `ev3_gene_summary.tsv` 的 top pathway。

原因：top pathway 是基于 CLR/ion enrichment 的候选信号，实测候选里出现 `Arachidonic acid metabolism` 这类对 E. coli benchmark 很可疑的 pathway。下一步应该用更严格的规则：优先从 `ev3_detail_tables.jsonl` 的 `Differential ions` 与 `EV4` annotation 交叉，选择 KEGG compound 明确、AUC/rank 高、且 pathway 属于 E. coli/central metabolism 的 KO。

## 下一步建议

1. 先定义 S1 gold-label 规则：是否允许多 pathway 答案；是否过滤跨物种/药物/泛 KEGG pathway；EV4 的 `rank/AUC/Z-cutoff` 阈值怎么设。
2. 生成 20 个人工审查 pilot tasks：从 `s1_task_seed_candidates.tsv` 里抽取，但人工排除明显不合理 pathway。
3. 再批量扩展到 100-200 个 hard tasks：只保留 high-confidence KO，避免把 KEGG enrichment 噪声变成答案。

## 复跑命令

```bash
python3 scripts/landscape/extract_s1_fuhrer.py
```
