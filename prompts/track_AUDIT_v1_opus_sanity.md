# Track AUDIT — v1 14-task with Opus-4-7 narrative (cross-model sanity check)

**Session ID:** `track_AUDIT_v1_opus_sanity`
**Branch:** any (推荐 `feature/sub6-v2-integrated`)
**Estimated work:** 30-45 minutes
**Predecessor:** `reports/audit/set_enrichment_regression_v1_v2.md`

---

## Why this matters

Audit 已定位 set_enrichment v1→v2 退化的主因是 **LLM swap (MiniMax-M2.7 → Opus-4-7)**,不是数据或代码。但需要一个**直接控制实验**坐实这个结论。

逻辑:用 Opus-4-7 重跑 v1 的 14 个 task。如果 v1-Opus 的 set_enrichment supported 数也只有 1-2(而不是 v1-MiniMax 的 3),就**直接证明 LLM 是主因,数据扩展是次因**。

---

## Hard scope boundaries

**You MAY:**
- 跑 v1 14 个 task 用 Opus-4-7 生成 narrative
- 跑 verifier v9-PhaseC 在新 narrative 上
- 写比较报告 `reports/audit/v1_opus_sanity_check.md`
- 用现有 Phase 3.1 引入的 `--narrative-llm opus47` CLI

**You MAY NOT:**
- 修任何代码
- 重跑 v2(没必要)
- 覆盖任何 v1/v2 现有 verdict / narrative 文件
- 修 prompt 模板

---

## Background reading

1. `reports/audit/set_enrichment_regression_v1_v2.md`(主诊断,已交付)
2. `data/benchmark/sub6/sub6a_e2e_tasks.jsonl`(v1, 14 task)
3. `results/sub6a_perfect_id_verifier_v9_phaseC/sub6a_perfect_id_v9_phaseC_verdicts.jsonl`(v1-MiniMax verdict 现成)
4. `evaluation/sub6/run_sub6a.py`(确认 `--narrative-llm` CLI 可用)

In your first response,确认:
- v1 14 task 用 Opus-4-7 跑 perfect-id narrative 的命令
- verifier v9-PhaseC 跑这批 narrative 的命令
- 输出位置:`data/eval/sub6/v1_opus_sanity/`

不要写代码或跑命令,直到 confirm。

---

## Deliverables

### D1 — 跑 Opus narrative on v1 14 task(15-20 分钟)

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a data/benchmark/sub6/sub6a_e2e_tasks.jsonl \
    --narrative-llm opus47 \
    --output data/eval/sub6/v1_opus_sanity/ \
    --mode perfect-id
```

(具体 CLI 参数以 Phase 3.1 实际实现为准,session 第一回合先确认)

### D2 — 跑 verifier v9-PhaseC

```bash
PYTHONPATH=. python scripts/eval_sub6/grade_with_verifier.py \
    --narratives data/eval/sub6/v1_opus_sanity/sub6a_narratives_perfect_id.jsonl \
    --output data/eval/sub6/v1_opus_sanity/verdicts_v9_phaseC.jsonl \
    --layer-6a-version v9-phaseC
```

预期 ~10 分钟。

### D3 — 比较报告

`reports/audit/v1_opus_sanity_check.md`,简洁 (~1 页):

#### 1. Three-way comparison

| Track | tasks | LLM | SE supported | SE unverifiable | SE total |
|---|---:|---|---:|---:|---:|
| v1 (existing, MiniMax) | 14 | MiniMax-M2.7 | 3 | 15 | 28 |
| v1-Opus (new, this audit) | 14 | claude-opus-4-7 | ? | ? | ? |
| v2 (existing, Opus) | 38 | claude-opus-4-7 | 1 | 102 | 114 |

#### 2. Conclusion(根据 D1+D2 数字写一段)

三种可能:
- **如果 v1-Opus SE supported ≤ 2**:坐实 LLM swap 是主因。数据扩展(v1→v2 task 数)对 set_enrichment 影响很小。**这是预期结果**。
- **如果 v1-Opus SE supported = 3**:LLM swap 不是全部原因,数据扩展也有贡献。需要进一步分析。
- **如果 v1-Opus SE supported > 3**:反常,可能 v9-PhaseC 在小数据集上行为不同,需深挖。

按实际数字给结论,不要预设。

#### 3. Paper implication

写 1-2 句:这个实验对 paper 的影响。

#### 4. Provenance + 文件 MD5 + wall time

### D4 — Acceptance

```
□ data/eval/sub6/v1_opus_sanity/sub6a_narratives_perfect_id.jsonl 14 行
□ data/eval/sub6/v1_opus_sanity/verdicts_v9_phaseC.jsonl 14 行
□ 比较报告完整
□ 0 行代码改动
□ v1 / v2 现有文件未动
```

---

## Pitfalls

1. **CLI 兼容性**:Phase 3.1 加的 `--narrative-llm` 在 perfect-id mode 下应该 work。如果没有,用 env var: `METAGENT_LLM_PROVIDER=openai METAGENT_OPENAI_MODEL=claude-opus-4-7 python ...` 兜底。

2. **viviai 偶尔 502**:14 task 有 1-2 个失败可重试。如果 ≥3 失败,检查 viviai 状态,再重跑失败的。

3. **verifier 必须用 v9-PhaseC**:跟 v1/v2 已有 verdict 配置一致,不能随便切别的版本。

---

## Time budget

- Confirm + setup: 5 分钟
- D1 narrative: 15-20 分钟(14 task × ~70s/task with Opus)
- D2 verifier: ~10 分钟
- D3 报告: 10 分钟
- D4: 2 分钟

**Total: ~30-45 分钟**。

---

## First action checklist

第一回合:
1. 读 4 个 background 文件
2. 确认 `evaluation/sub6/run_sub6a.py` 接受 `--narrative-llm opus47`(看代码)
3. 确认 `--mode perfect-id` 跟 `--narrative-llm` 能组合(或如何 spell)
4. 报告输出落盘路径
5. 任何 clarifying question

不要跑命令直到 confirm。
