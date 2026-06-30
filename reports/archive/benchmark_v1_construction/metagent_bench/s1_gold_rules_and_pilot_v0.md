# S1 gold-label 规则 v0 与 pilot 候选

日期：2026-05-25  
输入：`/data/weiwentao/llm_agent_metabolomics/data/landscape/S1_fuhrer_sauer_2017/derived/`  
输出：`/data/weiwentao/llm_agent_metabolomics/data/landscape/S1_fuhrer_sauer_2017/pilot/`

## 已完成

新增脚本：`scripts/landscape/build_s1_pilot_tasks.py`

生成文件：

- `pilot/s1_pilot_review_candidates.tsv`：50 条人工审查候选。
- `pilot/s1_pilot_tasks_v0.jsonl`：20 条 pilot task JSONL，全部标记 `status = needs_manual_review`。
- `pilot/s1_pilot_summary.json`：筛选计数和拒绝原因。

## v0 筛选规则

保留条件：

- gene 在 EV3 detail 中有 `KEGG pathway by CLR`。
- pathway q-value `<= 0.05`。
- pathway 名称在 E. coli 相关代谢 allowlist v0 中。
- 至少 5 个 high-confidence differential ions：有 KEGG compound ID，`AUC >= 0.60`，`abs(Z-score) >= 3.0`。
- 任务输出为候选 gold，不是最终 gold。

屏蔽条件：

- 明显非 E. coli/非目标机制 pathway：如 `Arachidonic acid metabolism`、`alpha-Linolenic acid metabolism`、`Bacterial secretion system`、`ABC transporters`。
- 泛化过强 pathway：如 `Microbial metabolism in diverse environments`、`Biosynthesis of secondary metabolites`。
- 污染/环境降解类 pathway：如 `Caprolactam degradation`、`Toluene degradation`、`Dioxin degradation`、`Xylene degradation` 等。

排序规则：

- 优先具体基因注释，弱注释降权：`not matched`、`DUF/UPF`、`predicted/putative/conserved`、`inner membrane protein`、`prophage` 等。
- 对代谢酶/转运相关注释加权：`synthase/dehydrogenase/kinase/reductase/transferase/isomerase/exporter/transporter` 等。
- 综合 pathway q-value、差异离子数量、top weighted ion score。

## 本轮计数

| 项 | 数量 |
|---|---:|
| allowlist pathway | 46 |
| blocked pathway patterns | 24 |
| 筛选前可形成候选的基因 | 377 |
| review candidates | 50 |
| pilot task JSONL rows | 20 |

主要拒绝原因：

| 原因 | 数量 |
|---|---:|
| no allowed significant pathway | 636 |
| lt_5_high_confidence_ions | 260 |
| qvalue_gt_0.05 | 124 |
| not_in_v0_ecoli_allowlist | 103 |
| blocked Biosynthesis of secondary metabolites | 100 |
| blocked Microbial metabolism in diverse environments | 40 |
| blocked alpha-Linolenic acid | 28 |
| blocked Caprolactam degradation | 24 |
| blocked Arachidonic acid | 23 |

## 重要 caveat

这 20 条 pilot 还不能直接进入 benchmark。它们已经过滤掉最明显的 KEGG 噪声，但仍存在三类风险：

- KO gene 与候选 pathway 的机制关系可能是间接的。
- metabolite annotations 仍是 paper supplement 的 putative ion annotation。
- 一些基因虽然有具体注释，但不是经典代谢酶，机制证据可能弱。

下一步建议人工审查 `s1_pilot_review_candidates.tsv` 前 50 条，给每条打 `accept / reject / needs_literature`。通过审查后，再把 `s1_pilot_tasks_v0.jsonl` 升级为正式 `hard` task seed。

## 复跑命令

```bash
python3 scripts/landscape/extract_s1_fuhrer.py
python3 scripts/landscape/build_s1_pilot_tasks.py
```
