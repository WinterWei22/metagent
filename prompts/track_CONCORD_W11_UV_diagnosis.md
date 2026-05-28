# ConcordMet UV Breakdown 诊断 — 0.5 day,纯 read-only analysis

**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v2`(W10 D4 数据已落盘)
**Mode:** 0.5 day,有人值守
**预算:** ~3-4h wall + ~$2-3 API(LLM 辅助分类)

---

## ⚠️ 死命令(全部延续)

- **不写 paper narrative / Discussion / Methods / Results / future work 段落 / footnote**(2026-05-17 + 2026-05-20 + 2026-05-22 死命令)
- 不改任何 production code(`concord/` / `verifier/` 全部 read-only)
- 不重跑 D4 数据
- 不动 verifier 4 个 grammar shape
- 不暴露 V3 算法 tool
- 不"$0 local"措辞(MiniMax 远程 API,cost 查 `logs/llm_calls.jsonl`)
- ConcordMet 仍 LLM-driven
- 每条 ping 结尾必含 2 段大白话总结(进展 + 问题,1-3 句各)

---

## §0 背景一句话

W10 D4 跑出 ConcordMet Path X 数据,**52% claim 被 verifier 判为 unverifiable_v0(UV)** —— 共约 1112 条 UV claim。这些 claim 不是错,只是 verifier 现有 4 个 grammar shape(`pathway_membership` / `metabolite_pathway_link` / `pathway_enrichment` / `driver_metabolite`)套不上。**本次任务是诊断这 1112 条 UV claim 到底在说什么**,给出分类分布,作为后续优化路径(扩 grammar / 收紧 prompt / 加 layer / UV 分桶)选择的依据。

---

## §1 任务范围(纯 analysis,3 步)

### Step 1:数据读取 + 抽 UV claim(~30 min)

读 `data/concord/w10_d4_path_x_full/path_x_full63_results.jsonl`(可能在 untracked 区,也可能 D5 落盘到 `data/concord/w10_d4_summary/path_x_summary.jsonl`,session 自己探数据)。

抽取所有 verdict == `unverifiable_v0` 的 claim,记录:
- `claim_text`(原文)
- `task_id`
- `iter`(0 / 1 / 2)
- `pathway_id`(如果 claim 含)
- `compound_id`(如果 claim 含)
- 其他 grammar 字段(如有)

输出 raw `data/concord/w11_uv_diagnosis/uv_claims_raw.jsonl`,每行一条 UV claim + 元数据。

### Step 2:LLM 辅助分类(~2h + $2-3 API)

用 GPT-4o 或 Claude(`api_key_*.txt` 已 ready)给 1112 条 UV claim 分类。**Prompt 由 session 设计**,要求:

- 给每条 UV claim 标 **1 个主要类别** + 可选 1 个次类别
- 类别候选清单(session 启动前我给的,可微调):
  - **C1 cross_method_consensus**:claim 提到多个 PA 方法 / 工具结果一致("3 of 5 methods agree X" / "ORA and FELLA both rank...")
  - **C2 method_disagreement**:claim 提到方法分歧("ORA says X but FELLA says Y" / "discrepancy between...")
  - **C3 signal_evidence**:claim 引用代谢物层 z-score / fold change / abundance 信号("X is significantly elevated" / "z-score = 3.2")
  - **C4 uncertainty_qualifier**:claim 含 confidence / 不确定性词("high confidence" / "weak signal" / "preliminary indicator")
  - **C5 intermediate_biology**:claim 描述中间生物学(上下游 / 步骤 / 反应链)而非 pathway-membership / driver
  - **C6 literature_reference**:claim 引用文献 / 已知机制("known to be..." / "as reported in...")
  - **C7 namespace_form**:claim 在 4 grammar shape 之内,但 pathway_id namespace 不匹配 verifier 期望(比如 MUMM: / 裸 name,这种应该 D2.5 + D3 fix 后少了,verify)
  - **C8 empty_or_noise**:LLM 走神 / 重复 / 残缺 / 拼写 / 与 task 完全无关("...." / "see above" / pasted prompt fragment)
  - **C9 other**:不属于上面 8 类的(session 提供 5-10 条样例 + 简短描述)

- LLM batch 处理(每 batch 50 条),节省 token

**Cost monitoring**:实际 cost 查 `logs/llm_calls.jsonl`,超 $5 ping me。

**Quality control**:LLM 分类完成后,**人工随机抽 50 条**(session 自己读)verify 分类是否合理,记录 disagreement rate(预期 < 20%,> 30% 必停 ping me)。

### Step 3:分布 + 抽样表(~30 min)

输出 `data/concord/w11_uv_diagnosis/uv_category_distribution.csv`:

```csv
category,count,percent,sample_claim_1,sample_claim_2,sample_claim_3
C1_cross_method_consensus,N1,P1,"...","...","..."
C2_method_disagreement,N2,P2,...
...
C9_other,N9,P9,...
TOTAL,1112,100.0,,,
```

同时输出 `reports/agent/concord_w11_uv_diagnosis.md`(**纯数据 + 短 caption,不写 paper-style 解读**):

允许内容:
- ✅ Category distribution table(N + %)
- ✅ Per-category 5-10 条 sample claim 全文(`task_id` + `iter` + claim text)
- ✅ Manual QC disagreement rate(50 条人工抽样数字)
- ✅ Methodology note:用什么 LLM 分的、prompt 截图、API cost
- ✅ Per-pathway breakdown(11 pathway × 9 类的矩阵,选做)

禁止内容:
- ❌ "Most UV claims fall in category X, suggesting..."
- ❌ "Future work should focus on..."
- ❌ "ConcordMet's broader narrative is reflected in C1+C2 dominance..."
- ❌ "This validates our hypothesis that..."
- ❌ 任何解读 / 推论 / framing 句

---

## §2 输出文件清单

```
data/concord/w11_uv_diagnosis/
├── uv_claims_raw.jsonl           # 1112 条 UV claim raw + 元数据
├── uv_classified.jsonl           # 1112 条 + LLM 分类标签
├── uv_category_distribution.csv  # 分布表
├── uv_manual_qc.csv              # 50 条人工 sample + 人工标签 vs LLM 标签
└── llm_prompt_used.md            # LLM 分类用的 prompt(可复现)

reports/agent/
└── concord_w11_uv_diagnosis.md   # 短报告(纯表 + sample 引用,无解读)
```

---

## §3 Commit 结构(2-3 atomic)

```
chore(concord): W11 UV diagnosis — extract UV claims + LLM-assisted categorization
docs(concord): W11 UV diagnosis report (category distribution + sample claims)
```

第 1 个 commit 含 raw + classified + distribution csv + manual QC + LLM prompt 文件。
第 2 个 commit 仅 report markdown。

**不 push origin**。

---

## §4 Stop Conditions

1. **D4 jsonl 找不到**(`data/concord/w10_d4_path_x_full/` 或 `data/concord/w10_d4_summary/` 都没)→ 必停 ping me,数据可能在别处
2. **UV claim 数 < 800 或 > 1500**(W10 D4 报的 ~1112,偏差太大说明数据筛选错)→ 必停
3. **LLM 分类 manual QC disagreement rate > 30%** → LLM prompt 设计差,必停重设计
4. **API cost > $5**(预算 $3,1.5× safety)→ ping me
5. **Wall > 1d**(预算 0.5d,1d 上限)→ scope 失控
6. **报告里出现任何 paper-style 解读句** → 必停回退,重写
7. **改了任 1 行 production code** → 必停回滚

---

## §5 Ping 内容 template

```
=== UV 诊断完成 ===

UV claim 总数: ?
LLM 分类(per category count + %):
  C1 cross_method_consensus:  ?  (?%)
  C2 method_disagreement:     ?  (?%)
  C3 signal_evidence:         ?  (?%)
  C4 uncertainty_qualifier:   ?  (?%)
  C5 intermediate_biology:    ?  (?%)
  C6 literature_reference:    ?  (?%)
  C7 namespace_form:          ?  (?%)
  C8 empty_or_noise:          ?  (?%)
  C9 other:                   ?  (?%)

Manual QC: 50 条抽样,LLM 与人工 disagreement = ?/50 = ?%

API cost: $?
Wall: ?h

Commits: <hash 1> + <hash 2>
Files: data/concord/w11_uv_diagnosis/* + reports/agent/concord_w11_uv_diagnosis.md

[2 段大白话总结]
```

---

## §6 一句话目标

读完 D4 已有数据,把 1112 条 UV claim 用 LLM 分类成 9 个桶,出分布 csv + sample 表,**不写任何 paper 解读句**,不改任何 code。我看分布数字后决定下一步优化路径走 A/B/C/D/E 哪条。

开干。
