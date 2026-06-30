# LLM 必要性审计:MetAgent 里"代谢物 → pathway"到底是谁决定的

**日期**:2026-05-14
**作者**:调研 agent(claude-opus-4-7)
**范围**:Sub-6B(compound-only enrichment)track AGENT,涵盖 v3 benchmark 63 task

## 1. TL;DR

| 问题 | 一句话答案 |
|---|---|
| Q1: pathway 怎么定的? | **核心 pathway 来自 `query_ramp_enrichment` 工具(纯 SQL + scipy hypergeometric)的返回**,LLM 只做"读 + 复述 + 在 top-K 内挑一个生物学上听起来对的"。匹配走 KEGG ID,完全 ID-based,没有 LLM 名称匹配。 |
| Q2: 不用 LLM 行不行? | **能,但取决于评分口径**。GT 本身就是 RaMP top1,所以"RaMP top1 → output"的零-LLM baseline 在 top1_strict 指标上理论上 ~100%。但项目里**没有实现这个 baseline**——这是诊断空白。 |
| Q3: LLM + Multi-Agent 必要在哪? | **弱必要 → 中等必要**。LLM 的真增量贡献是 (a) drug-pathway 噪声过滤 +(b) 把多工具结果整合成 narrative,提供 driver 解释和 upstream/downstream 因果叙事。pathway 鉴定本身 LLM 是 **可替代** 的,叙事/解释/多 claim 整合是 LLM 难替代的。 |

**总判断:对于"pathway 名鉴定"这一狭义任务,LLM 是可替代的;对于"形成可读、可逐 claim 验证的代谢叙事报告"这一任务,LLM 当前没有简单替代品。Reviewer 灵魂拷问基本成立,需要诚实承认。**

---

## 2. Pathway 确定的实际机制(Part A)

### 2.1 代码路径

入口 `evaluation/sub6/run_sub6b_react.py:run_sub6b_react` → prompt 在 `prompts/agent/sub6b_react_prompt.md`,SYSTEM 段第 1 条硬规则:

> "You MUST call `query_ramp_enrichment` at least once before producing the final narrative. Skipping enrichment and writing a narrative from training-data recall is a failure mode we are explicitly trying to fix."

工具调用通过 `tools.agent_tools.dispatch` 路由,5 个工具实现位于 `tools/agent_tools/`:

| 工具 | 输入 | 输出 | 实质 |
|---|---|---|---|
| `query_ramp_enrichment` | KEGG ID list,top_k | top_k pathway + FDR + fold-enrichment + matched compounds | **纯 SQL + scipy.stats.hypergeom**(`tools/benchmark/sub6/ramp_enrichment.py:compute_enrichment`) |
| `query_pathway_membership` | 单个 ID | 该 ID 所属 pathway 列表 + 上下游 neighbour | **纯 SQL join**(RaMP `analytehaspathway` 表) |
| `query_kegg_path` | 两个 KEGG ID | 是否可达 + 最短路径 + 方向 | **纯 BFS over KEGG reaction graph** |
| `lookup_compound_info` | 单个 ID/name/SMILES | metadata bundle | HMDB→MoNA→PubChem 查表 |
| `search_literature` | free text | PubMed hits | E-utils API |

**没有一个工具内部用到 LLM。** 全部是 deterministic 查表 / 图算法 / 统计检验。

### 2.2 ReAct trace 真实样本(task `compound_only_enrich_mammalian_lm_pathway_WP167_seed0`)

来自 `data/eval/sub6/v4_a3_d3_with_lit/react/.../narrative.json`:

- **Turn 1**:`query_ramp_enrichment(C14717, C04742, ..., C00219)` →
  返回 top-5,全是 SMPDB drug-action pathway:
  `["Leukotriene C4 Synthesis Deficiency", "Rofecoxib Action Pathway", "Salicylate-sodium Action Pathway", "Trisalicylate-choline Action Pathway", "Acetaminophen Action Pathway"]`,FDR 全是 0,fold ~735。
- **Turn 2**:对 C00219 / C00909 / C04742 各调一次 `query_pathway_membership`。返回的 pathway 列表里包含 `map00590 / SMP00075 "Arachidonic Acid Metabolism"`。
- **Turn 3**:`query_kegg_path(C00219, C04742)` → 验证 2-hop 路径,direction=forward。
- **Turn 4**:写 narrative,**top-1 pathway 选了 "Arachidonic Acid Metabolism"(KEGG map00590)**——这名字来自 turn 2 的 membership 工具结果,不是 turn 1 enrichment 的 top-5。

### 2.3 LLM 是否原样复述工具结果?

聚合 63 个 task(脚本里跑):

- **LLM 第一个 bold 的 pathway == RaMP 工具 top1 的**:8 / 63(13%)
- **LLM 第一个 pathway ~= GT(token-subset)**:39 / 63(62%,与 `pathway_accuracy_summary` 的 65% top1_strict 一致)

→ **LLM 大多数情况**不是简单复述 RaMP top1**,而是在 enrichment top-K + membership 返回的所有 pathway 集合中"挑生物学上更通用、更非 drug-action 的那个"**。例如:
- `RAMP_P_000000398_seed5`:RaMP top1 = "Galactosemia"(疾病 pathway);LLM 输出 "Galactose Metabolism";GT = "Galactose Metabolism"。**LLM 正确**。
- `RAMP_P_000025682_seed2`:RaMP top1 = "Celecoxib Action Pathway";LLM 输出 "Arachidonic Acid Metabolism";GT = "Celecoxib Action Pathway"。**LLM 反而错了——把"对的"药物 pathway 改成了"通用的"代谢 pathway**。

### 2.4 ID 还是 fuzzy 匹配?

- 输入侧:工具入参全部是 KEGG ID(`Cxxxxx`),prompt 反复强调"copy IDs, do not invent"。
- 输出 → narrative:LLM 把 pathway 名照搬进 markdown 文字。
- 评测匹配(`evaluation/sub6/metrics.py:is_pathway_hit`):**token-set subset match,大小写不敏感**(substring + content-token subset)。这就是为什么 "Galactose Metabolism" 能匹 "Galactose Metabolism"、"Arachidonic acid metabolism" 能匹 "Arachidonic Acid Metabolism"。

### 2.5 Ground truth 怎么定的

`data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl` 每个 task 字段:

```json
"ground_truth_pathway": {"pathway_id": "RAMP_P_000052855", "pathway_name": "Sulfatase and aromatase pathway", ...},
"ramp_enrichment_result": {"top_pathways": [...]}
```

GT 就是用 RaMP enrichment 在 task 构造时跑出来的 top1(经过一些 aggregation,见 `task_constructor.py`)。**这是一个自指 benchmark:用纯工具产生 GT,再让 LLM 复现 GT**。

---

## 3. Non-LLM baseline 现状(Part B)

**结论:项目里没有任何"纯工具、不调 LLM"的 pathway 预测 runner。**

证据:
- `evaluation/sub6/` 下所有 runner(`run_sub6a.py`、`run_sub6b.py`、`run_sub6b_react.py`、`run_sub6b_react_feedback.py`)均调 `common.llm_client`。"baseline" 在文档里指的是 **single-call LLM**(对比 ReAct/feedback),而不是无 LLM。
- `verifier/layers/set_enrichment.py` 是纯 RaMP 比对,但它只是**验证器**(给定 claim → SUPPORTED/CONTRADICTED),不是**生成器**——不会主动输出 pathway。
- RaMP 原生 R 包确实有 `runFisherTest()`,但项目用的是 SQLite 直查的 Python port(`tools/benchmark/sub6/ramp_enrichment.py`),没有 mummichog/MetaboAnalyst CLI 包装。
- Mummichog / GSEA / `enrichR` 等纯工具基线:**未实现**。

→ 这是一个**诊断空白**。要回答"LLM 比纯工具好多少"必须先补一个 baseline,定义如下:

```
nonllm_baseline(task) = task["ramp_enrichment_result"]["top_pathways"][0]["pathway_name"]
```

此 baseline 在当前 v3 benchmark 上 top1_strict ≈ 100%(因为 GT 字段直接来自 enrichment top1)。**这本身就是问题**——它说明现有 benchmark 评不出 LLM 的额外价值。

---

## 4. LLM 贡献分解(Part C)

| # | LLM 在 Sub-6B 里做的事 | 工具是否可替代? | 注 |
|---|---|---|---|
| 1 | 把 KEGG ID 列表丢给 enrichment | (ii) 工具能做 | 一行 SQL/Python,LLM 只是 routing |
| 2 | 在 RaMP top-K 内选 pathway,过滤掉 SMPDB 里的 "Rofecoxib/Acetaminophen Action Pathway" 类 drug-pathway | **(iii) 工具难做** | 需要"该 pathway 是 generic metabolism 还是 specific drug"的语义判断;可写规则(source==smpdb AND name contains "Action Pathway") → 部分替代 |
| 3 | 在多个候选 pathway 间挑"更通用"的(Galactose Metabolism vs Galactosemia) | **(iii) 工具难做** | 但这也会导致 false negative(case `RAMP_P_000025682_seed2` LLM 反被带偏) |
| 4 | 用 `query_pathway_membership` 把候选 driver 一一验证(逐 claim "X is in Pathway Y") | (i) 工具直接给答案 | LLM 只是把工具 boolean 翻译成英语 |
| 5 | 用 `query_kegg_path` 验证 upstream/downstream | (i) 工具直接给答案 | LLM 只是把 path list 翻译成因果句 |
| 6 | 把多个 claim 整合成 200-400 字 narrative,带 biological significance / interpretation | **(iii) 工具难做** | 这是 LLM 真正不可替代的部分,但**不是 pathway 鉴定本身,而是叙事生成** |
| 7 | 在 noise compound(CDP 等)与 signal 间做出过滤评论 | **(iii) 工具难做** | 工具能告诉你 CDP 不属于 top pathway,但"argues against primary nucleotide abnormality" 这种语义判断需要 LLM |
| 8 | 形式严谨地呼应 prompt 要求的 4 个 section | (ii) 模板生成器能做 | Jinja 模板可替代 |
| 9 | 错误恢复(工具报 error → 改用其他 ID 重试) | (ii) 简单状态机能做 | retry-loop 即可 |

**结论**:LLM 提供的"必要"价值集中在 **#2、#3、#6、#7**——也就是**语义过滤 + 叙事整合**,**不是 pathway 鉴定本身**。

定量印证(来自 `data/eval/sub6/v4_a3_pathway_accuracy/pathway_accuracy_summary.json`):

| 系统 | top1_strict | top3 acceptance | off-pathway mean |
|---|---:|---:|---:|
| d3_llm_single_no_lit(LLM 单 call,无工具) | 30.16% | 42.86% | 5.05 |
| d3_llm_single_with_lit(LLM 单 call + lit) | 26.98% | 41.27% | 4.84 |
| d3_metagent_no_lit(ReAct + 4 工具) | **65.08%** | **80.95%** | 2.56 |
| d3_metagent_with_lit(ReAct + 5 工具) | 63.49% | 84.13% | 2.30 |
| **理论 nonllm_baseline = RaMP top1** | **~100%** | 100% | 0 |

→ LLM ReAct 比 LLM 单 call **+35pp**(工具的功劳);相对零-LLM RaMP top1 还差 **-35pp**(LLM 在 enrichment top-K 内"挑错了"的损失)。

---

## 5. Supported pathway claim 溯源(Part D)

样本 `compound_only_enrich_mammalian_lm_pathway_WP167_seed0`,7 条 SUPPORTED claim:

| # | Claim 文本(截断) | pathway 名来自 | Verifier evidence 来源 | 与 LLM 关系 |
|---|---|---|---|---|
| 1 | "Arachidonic Acid Metabolism has KEGG pathway map00590" | `query_pathway_membership` 返回行 | RaMP pathway 表 ID lookup | LLM 只是复述工具行 |
| 2 | "Arachidonic acid is a pathway member of Arachidonic Acid Metabolism" | 工具返回 | RaMP `analytehaspathway` | LLM 复述 |
| 3 | "Leukotriene A4 is a pathway member of Arachidonic Acid Metabolism" | 工具返回 | RaMP `analytehaspathway` | LLM 复述 |
| 4 | "15-HETE is a pathway member of Arachidonic Acid Metabolism" | 工具返回 | RaMP `analytehaspathway` | LLM 复述 |
| 5 | "5-HETE is a pathway member of Arachidonic Acid Metabolism" | 工具返回 | RaMP `analytehaspathway` | LLM 复述 |
| 6 | "11,12,15-THETA is a pathway member of Arachidonic Acid Metabolism" | 工具返回 | RaMP `analytehaspathway` | LLM 复述 |
| 7 | "Absence of CDP from the enrichment signal argues against a primary nucleotide metabolism abnormality" | 工具未返回 CDP 在 top pathway → LLM 推断 | RaMP membership 反查 | **LLM 推断,工具仅验证** |

→ **7 / 7 supported claim 都可以追到一次 RaMP 表查询。LLM 在 claim 1-6 上贡献为零**(verifier 拿 RaMP 直接验证,LLM 写不写没差);只有 claim 7 的"argues against" 这种否定推断是 LLM 主动产生的(但 verifier 也是用 RaMP 验证它)。

更糟的是:这个 task 的 GT pathway 其实是 "**Eicosanoid synthesis (WP167)**",**没有任何一条 supported claim 直接命中 GT**——LLM 在 top1 维度被判 unsupported。

---

## 6. 给 Reviewer 的诚实答辩稿

### Q1:MetAgent 如何确定 pathway?是不是严格依据 KEGG ID lookup?

> **Pathway 鉴定的核心确实是 KEGG ID 驱动的工具调用,不是 LLM 名字匹配。** 我们的 system prompt 强制要求 LLM 第一步调用 `query_ramp_enrichment`,该工具在 RaMP-DB 上跑标准的 hypergeometric 检验(scipy.stats.hypergeom + BH FDR),返回的 pathway 来自 SQL 查询,完全 ID-based。LLM 拿到 top-K 列表后,会再调 `query_pathway_membership`(KEGG/HMDB ID lookup)和 `query_kegg_path`(reaction graph BFS)逐一验证。也就是说,**pathway 名字本身始终是从 RaMP 表里读出来的,不是 LLM 拍脑袋**。LLM 的角色是 (a) 在 enrichment top-K 内挑一个写进 narrative,(b) 把 membership 工具的 boolean 翻译成英文。

### Q2:不用 LLM,纯工具效果如何?

> **这个对比我们目前还没做完整,这是一个我们必须承认的空白。** 现有 v3 benchmark 的 ground truth pathway 就是 task 构造时 RaMP enrichment 排第一的 pathway,所以"直接输出 RaMP top1"这个零-LLM baseline 在 top1_strict 上会接近 100%——比当前 metagent 的 65% 还高 35 个百分点。也就是说,**对于"识别 top 通路"这一狭义任务,LLM 当前是性能净亏损**。LLM 在 enrichment top-K 内做了"剔除 drug-action pathway、选生物学通用 pathway"的语义筛选,这有时和 GT 吻合(Galactose Metabolism 案例),有时反而把对的 drug pathway 改错了(Celecoxib Action Pathway 案例)。下一步必须实现一个 nonllm 基线(`baseline = ramp_enrichment.top_pathways[0]`)做正式 head-to-head。

### Q3:LLM + Multi-Agent 的必要性?

> **诚实地说,在"pathway 鉴定"这个 narrow 指标上,LLM 的必要性是弱的;在"输出可读、可逐 claim 验证的代谢叙事"上,LLM 才有不可替代的价值。** 具体证据:Sub-6B 上 LLM-only(无工具)top1_strict = 30%,加了 4 个工具的 ReAct 跳到 65%——35 个百分点的提升来自工具,不是 LLM。但 LLM 提供了三件工具难做的事:(i) 在 enrichment top-K 内做 source/语义级筛选(把 SMPDB drug-action pathway 降权),(ii) 把多次工具调用结果整合成 driver claim + 因果叙事 + biological significance 段落,(iii) 处理工具未覆盖的 negative claim("CDP 不在 top pathway 因此不支持原发性核苷酸异常")。Multi-agent 的价值主要在 verifier 端(layer 6a/6b/6c)做逐 claim grounding——而 verifier 本身是用 LLM 提 claim、用纯工具验证,**不是 LLM 互相对话**。所以更准确的描述是:**LLM 是 narrative generator + claim extractor;工具是 ground truth source。Multi-agent 名字略有夸大。**

---

## 7. 如果 LLM 必要性弱,下一步该做什么实验

### 7.1 立即可做(本周)

1. **实现 nonllm baseline runner** — `evaluation/sub6/run_sub6b_nonllm.py`:输入 KEGG ID list → 调 `compute_enrichment` → 把 top1 pathway 名包成最小 narrative("The metabolites are enriched in {top1.name} (FDR={top1.fdr})") → 走同样的 metric pipeline。预期 top1_strict ≈ 100%。
2. **重新设计 benchmark GT** — 当前 GT = RaMP top1 是自指的,公平的对比要么 (a) 把 GT 换成 wet-lab paper 报告的 affected pathway(人工标注),要么 (b) 改用 leave-one-out:从一个真实生物学 pathway 里挑 N 个 metabolite 当 input,看系统能否还原(GT 是源 pathway 名)。

### 7.2 中期(2-4 周)

3. **在 narrative 维度引入 LLM-vs-template 对比** — 同一个工具结果,(a) Jinja 模板拼一段,(b) LLM 写一段。让生物学家盲评 "informativeness / biological-significance / claim density"。如果 LLM 显著胜出,这是 LLM 价值在 narrative 层的证据。
4. **测 LLM 在歧义消解上的真实价值** — 设计 task,输入既包含 GT pathway 又包含一个 drug-action 噪声 pathway 满 top-3,看 LLM 选择率是否高于随机。这是 #2/#3 的 controlled experiment。

### 7.3 长期

5. **重新框定 MetAgent 的 contribution** — 论文里少说 "LLM 鉴定 pathway",多说 "LLM 作为统一编排器把 5 个异构数据库工具的结果整合成 verifiable narrative"。把 65% top1_strict 改为辅助指标,把 supported-claim density、claim-precision、narrative-faithfulness 提到主指标。
6. **如果实验证实 LLM 在 pathway 鉴定上是性能净亏损**,则在论文里直接说"我们不主张 LLM 比 RaMP enrichment 在 pathway top1 上更准;LLM 的价值在于把多源数据库整合成 verifiable narrative"——这是 reviewer 期待的诚实陈述,反而能加分。

---

## 附:关键代码与数据路径

- 工具实现:`tools/agent_tools/{query_ramp_enrichment,query_pathway_membership,query_kegg_path,lookup_compound_info}.py`
- 底层 RaMP 引擎:`tools/benchmark/sub6/ramp_enrichment.py:compute_enrichment`
- ReAct runner:`evaluation/sub6/run_sub6b_react.py`
- Prompt:`prompts/agent/sub6b_react_prompt.md`
- Benchmark + GT:`data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl`
- Pathway 匹配 metric:`evaluation/sub6/metrics.py:compute_task_metrics`,`is_pathway_hit`
- 量化结果:`data/eval/sub6/v4_a3_pathway_accuracy/pathway_accuracy_summary.{json,md}`
- 示例 trace:`data/eval/sub6/v4_a3_d3_with_lit/react/compound_only_enrich_mammalian_lm_pathway_WP167_seed0/{narrative,verdict}.json`
- Verifier set-enrichment layer:`verifier/layers/set_enrichment.py`(纯工具 oracle)
