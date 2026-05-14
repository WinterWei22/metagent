# Track: Phase B1 — Claim Grammar & Prompt Rewrite

**前置**:`MetAgent-v1-0514` 已封存(见 `track_FREEZE_MetAgent_v1_0514.md`)

## 目的

把 v1 的 UNVERIFIABLE_v0 占比(63-67%)从源头降下来,不是靠把 UNV 重命名为 OUT_OF_SCOPE,而是**让 UNV 从一开始就不被生成**。对标 GeneAgent 的 prompt 层硬约束策略。

诊断报告:
- `reports/agent/diagnosis_unverifiable_and_correlation.md`
- `reports/agent/prompt_audit_for_rewrite.md`

核心判断(来自诊断):
- UNV 70-80% 是 **prompt 层可吃掉的**,不是工具流问题
- 当前 narrative prompt 主动要求 "biological significance + upstream/downstream" → 抽象/猜测句子的产地
- extractor 自陈 "deliberately does not filter" → schema 外无 drop
- classifier 把单化合物抽象句收编为 BIOLOGICAL → 下游验不了
- feedback hint 把 UNV 列为 neutral → LLM 学到"写得越抽象越安全"

## Deliverables

### D0 — Claim Grammar 定义(动手前必做)

在 `verifier/grammar.py`(新建)里定义 v2 合法 claim schema,只允许 4 类:

```python
class ClaimGrammar(Enum):
    PATHWAY_MEMBERSHIP = "metabolite ∈ pathway"
    METABOLITE_PATHWAY_LINK = "metabolite participates in pathway via <enzyme/reaction>"
    PATHWAY_ENRICHMENT = "pathway is enriched given metabolite set {...}"
    DRIVER_METABOLITE = "metabolite drives pathway because <ground-truth evidence>"
```

每一类附:
- 正例 3 条(可被现有 layer 验证)
- 反例 3 条(当前 v1 narrative 实际产生、应被 drop)
- 该类的 verifier layer 归属(6c / 6a / 6b / E)

输出:`verifier/grammar.py` + `docs/claim_grammar_v2.md`

### D1 — Narrative Prompt 重写

**文件 1**:`evaluation/sub6/prompts.py:12-29`(single-call)
**文件 2**:`prompts/agent/sub6b_react_prompt.md`
**文件 3**:`prompts/agent/sub6b_react_feedback_prompt.md`

每份 prompt 重写要求:
1. 顶部加 **句式 schema 段**:列出 4 种合法句式,要求每个句子必须匹配其中之一
2. 加 **负面词表**:`may / might / suggest / suggesting / potentially / possibly / likely / downstream / upstream / crosstalk / signaling cascade / role in / involved in metabolic-immune ... `,一律禁用
3. 加 **端点要求**:任何 "participates in" 必须给出 enzyme 或 reaction 名;任何 "driver" 必须引用 ground-truth signal
4. 区分 **Sub-6A vs Sub-6B**:Sub-6A 有 IdReport,可写 grounded claim;Sub-6B 不能写 grounded claim(无 IdReport 锚点)
5. 输出格式从 free markdown 改 **JSON list of claims**,直接对齐 ClaimGrammar 枚举

提供 diff 形式,不直接覆盖,先 review 再 apply。

### D2 — Claim Extractor 重写

**文件**:`verifier/claim_extractor.py:169` + `verifier/prompts/extract_claims.py`

改动:
1. 删掉 "deliberately does not include 'do not hallucinate' phrasing" 那段注释和对应宽松提取行为
2. extract prompt 改成 **按 grammar 4 类抽**,每条 claim 必须标 grammar type
3. **schema 外的句子直接 drop**,在 metric 里单列 `dropped_by_grammar` 计数(不计入 supported/unverifiable 分母)
4. 如果 narrative 是 JSON 输出(D1 完成后),extractor 可以简化为 schema validation

注意:D1 落地后,如果 narrative 已经是结构化 JSON,extractor 的 LLM 步骤可以**完全去掉**,变成纯 schema validation,这是更好的目标态。

### D3 — Classifier 调整

**文件**:`verifier/claim_classifier.py` + `verifier/prompts/classify_ambiguous.py`

改动:
1. classifier 类型枚举从 9 类(GROUNDED/FACTUAL/BIOLOGICAL/...)收敛到 grammar 4 类
2. classifier prompt 里删掉 "Polyamines regulate protein synthesis 这种主动收编为 BIOLOGICAL" 的 few-shot 示例
3. 抽象单化合物句、无端点链推句直接归 `DROP`(不路由到任何 layer)

### D4 — Sub-6 Dispatch + Feedback Hint 调整

**文件 1**:`verifier/agent.py:494-518`(Sub-6 dispatch)

D1+D2+D3 之后,grammar 应该已经让 Sub-6B 不再产 GROUNDED 类 claim。Dispatch 简化:
- 4 类 grammar 各自直接路由到对应 layer
- 不再需要 "Sub-6 没 IdReport 一刀切 UNV" 的兜底
- 如果还有兜底需求,改路由到 Layer E(Europe PMC),不再用 UNVERIFIABLE_V0

**文件 2**:`verifier/feedback_hints.py:57` `_NEUTRAL_VERDICTS`

把 `UNVERIFIABLE_V0` **移出** neutral 集合。改成对 UNV claim 也发 hint,模板:

> "Claim X is unverifiable: it does not match any of the 4 allowed grammar types. Rewrite as one of {PATHWAY_MEMBERSHIP, METABOLITE_PATHWAY_LINK, PATHWAY_ENRICHMENT, DRIVER_METABOLITE},or remove."

### D5 — 评估(对照 v1)

数据集:与 A3 一致(63 task,Sub-6B,MiniMax T=0)。

**N=3 reruns**(对齐 A3 噪声测量方法,seed 0/1/2,K=10 并行)。

报告 `reports/agent/phase_b1_audit.md` 必须包含:

| 指标 | v1 (A3 D3.5) | v2 (B1 D5) | Δ |
|---|---|---|---|
| supported % | 25.23 ± 6.16 | TBD | |
| unverifiable_v0 % | 63-67 | **target < 10** | |
| contradicted % | 1.97 ± 1.03 | TBD | |
| dropped_by_grammar %(新) | N/A | TBD | |
| supported vs task-correct 相关性 | +8pp | **target +25pp** | |
| wall time per task | TBD | TBD | |

如果 unverifiable 没降到 < 10%,**不要发布 v2**,先回到诊断分析为什么 prompt 约束没生效。

### D6 — Ablation

跑 4 个 condition 比较各改动贡献:
- A:v1 baseline(MetAgent-v1-0514 tag)
- B:v1 + 仅 D1 narrative prompt 改
- C:v1 + D1+D2 extractor drop
- D:v1 + D1+D2+D3+D4 全套(= v2)

每个 condition N=1 即可(10 task subset),只是看趋势。

## 验收红线

不满足以下任一条,**不算 B1 完成**:

- [ ] unverifiable_v0 占比 < 10%
- [ ] dropped_by_grammar < 30%(若 ≥ 30% 说明 LLM 还是产生大量非法句,需进一步约束 narrative prompt)
- [ ] supported % 不下跌超过 5pp(B1 不是为了提 supported,但不能让它崩)
- [ ] supported vs task-correct 相关性提升至少 +10pp
- [ ] D6 ablation 完成,能讲清楚每一步贡献

## 非目标(明确不在 B1 范围)

- 不动 Stage 1(library_search, MS-CLIP, candidate_prefilter)
- 不加新工具
- 不换 LLM(全程 MiniMax,Opus / GPT-5.5 留 Phase A4)
- 不动 KEGG / RaMP / HMDB DB schema

## 风险与回滚

- 风险 1:JSON 输出的 narrative,LLM 可能频繁生成不合法 JSON。**对策**:加 retry + JSON repair,失败 task 单列 `narrative_invalid_json` 计数。
- 风险 2:grammar 太严,合法 claim 也被 drop。**对策**:D6 ablation 看 B condition 的 dropped 率,如果 > 50% 回去松一档。
- 回滚:任意时刻 `git checkout MetAgent-v1-0514` 回到 v1 baseline。

## 完成后产物

- `reports/agent/phase_b1_audit.md`(主报告)
- `verifier/grammar.py` + `docs/claim_grammar_v2.md`
- Diff PR(D1-D4)合并到 main
- 新 tag:`MetAgent-v2-XXXX`(由 audit 通过后决定)
