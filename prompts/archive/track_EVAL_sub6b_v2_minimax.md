# Track EVAL — Sub-6B v2 with MiniMax-M2.7 narrative (3-way symmetry)

**Session ID:** `track_EVAL_sub6b_v2_minimax`
**Branch:** `feature/sub6-v2-integrated`(从 Phase 3.2 继续)
**Estimated work:** 3-4 hours wall(LLM 调用为主)
**Predecessors:**
- `reports/eval/sub6_v2_integrated_v9_phaseC_4tracks.md`(已完成 Sub-6B Opus + GPT-5.5)
- `reports/audit/v1_opus_sanity_check.md`(F4 finding 数据)

---

## Why this matters

audit 揭示了 **verifier literal-style bias**:supported rate 受 LLM 写法影响远大于受生物学正确性影响。当前 Sub-6B v2 已有 Opus + GPT-5.5 narrative,**缺 MiniMax**。补 MiniMax 后形成完整 3-way 对比:

```
LLM        | supported pct (期望) | 写作风格
-----------|---------------------|----------
MiniMax    | 高 (~28%)           | literal canonical names
GPT-5.5    | 中 (28.89%)         | mixed
Opus-4-7   | 低 (18.10%)         | mechanistic / functional terms
```

3-way 完整矩阵让 paper 能展示"verifier 不是 LLM-agnostic"这个 finding,而不是只 2-way 对比。

---

## Hard scope boundaries

**You MAY:**
- 用 `--narrative-llm minimax` 跑 Sub-6B v2 63 task
- 跑 verifier v9-PhaseC 在新 narrative 上
- 写 update 报告 `reports/eval/sub6b_v2_3way_full_comparison.md`
- 用现有 aggregator 出 summary.json

**You MAY NOT:**
- 修任何代码(verifier、orchestrator、prompt 模板)
- 重跑 Opus / GPT-5.5(它们已有数据)
- 覆盖现有 v1/v2 verdict 文件
- 跑 Sub-6A(本 session 只补 Sub-6B 那一缺口)

---

## Background reading

1. `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl`(63 task,确认存在)
2. `data/eval/sub6/v2/sub6b_opus/verdicts_v9_phaseC.jsonl`(已有 Opus)
3. `data/eval/sub6/v2/sub6b_gpt55/verdicts_v9_phaseC.jsonl`(已有 GPT-5.5)
4. `evaluation/sub6/run_sub6b.py`(--narrative-llm 应该已支持)
5. `scripts/eval_sub6/run_baseline.py`(CLI 入口)
6. `reports/eval/sub6_v2_integrated_v9_phaseC_4tracks.md`(主结果格式参考)

In your first response,确认:
- `--narrative-llm minimax` 当前 Phase 3.1 实现是否 work(看 commit 历史)
- 现有 Opus / GPT-5.5 跑的命令(从 logs/v2/ 找)
- MiniMax 默认 model 名是 `MiniMax-M2.7` 还是别的

不要跑命令直到 confirm。

---

## Deliverables

### D1 — 跑 MiniMax narrative(2.5-3 小时)

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
    --narrative-llm minimax \
    --output data/eval/sub6/v2/sub6b_minimax/ \
    > logs/v2/sub6b_minimax.log 2>&1
```

输出:
- `data/eval/sub6/v2/sub6b_minimax/sub6b_narratives.jsonl`(63 行)
- log 落 `logs/v2/sub6b_minimax.log`

预期 wall: 63 × ~150s = 2.5 小时(MiniMax 比 Opus 慢)。如果偶发失败可重试。

### D2 — 跑 verifier v9-PhaseC

```bash
# 使用 working tree 的 verifier(即 v9-PhaseC)
PYTHONPATH=. python scripts/eval_sub6/grade_with_verifier.py \
    --narratives data/eval/sub6/v2/sub6b_minimax/sub6b_narratives.jsonl \
    --output data/eval/sub6/v2/sub6b_minimax/verdicts_v9_phaseC.jsonl
```

预期 wall: ~1 小时。

### D3 — Aggregator 出 summary

跑现有 aggregator(跟 Opus / GPT-5.5 同一个),得:
- `results/v2/sub6b_minimax/sub6b_v2_minimax_verdicts.csv`
- `results/v2/sub6b_minimax/sub6b_v2_minimax_verdicts_summary.json`

### D4 — 3-way 完整对比报告

`reports/eval/sub6b_v2_3way_full_comparison.md`,简洁(1-2 页):

#### 1. Three-way verdict distribution(主表)

| | MiniMax | GPT-5.5 | Opus-4-7 |
|---|---:|---:|---:|
| narrative wall | ? min | 24.8 min | 19.7 min |
| s/task | ? | 23.6s | 18.8s |
| narrative 平均长度 | ? chars | 2601 | 2766 |
| total claims | ? | 2956 | 3281 |
| supported pct | ? | 28.89% | 18.10% |
| unsupported pct | ? | 17.42% | 12.56% |
| contradicted pct | ? | 3.89% | 4.18% |
| unverifiable_v0 pct | ? | 49.80% | 65.16% |
| SE 任务级 supported | ?/63 | 5/63 | 2/63 |
| Driver-contra 任务 | ?/63 | 16/63 | 17/63 |

#### 2. SE 类 verdict 分布(F4 finding 验证)

| | MiniMax | GPT-5.5 | Opus-4-7 |
|---|---:|---:|---:|
| SE total | ? | ? | ? |
| SE supported | ? | ? | ? |
| SE supported pct | ? | ? | ? |
| SE unverifiable pct | ? | ? | ? |

预期:MiniMax SE supported pct 显著高于 Opus(literal-style hypothesis 验证)。

#### 3. Contradicted 跨 LLM 一致性(关键!)

```
MiniMax contra: ?  (?% of total)
GPT-5.5 contra: ?  (?% of total)
Opus contra:    ?  (?% of total)
```

如果 3 个 LLM 的 contradicted **比例接近**(都在 3-5%),说明**底层"乱说"
水平相当**,差异主要在写作风格 → 强证据支撑 paper 的 literal-style bias finding。

如果差异显著(MiniMax contra 突然 >10%),需进一步分析。

#### 4. Sample claim 对比(同 task 跨 3 LLM)

挑 3 个 task,贴 3 个 LLM 在同一 task 的 SE claim 句子,展示风格差异:

```
Task: ...
MiniMax: "..."  → SUPPORTED
GPT-5.5: "..."  → ?
Opus:    "..."  → UNVERIFIABLE
```

#### 5. Paper finding 更新建议

写 1 段:这个 3-way 对比对 paper framing 的具体影响。

#### 6. Provenance + MD5 + git commit

### D5 — Acceptance

```
□ data/eval/sub6/v2/sub6b_minimax/sub6b_narratives.jsonl 63 行
□ data/eval/sub6/v2/sub6b_minimax/verdicts_v9_phaseC.jsonl 63 行
□ results/v2/sub6b_minimax/*_summary.json 存在
□ 报告 §1 主表 3 LLM 列填全
□ 报告 §3 contradicted 比例对比
□ 0 行代码改动
□ 现有 Opus / GPT-5.5 文件未动
```

---

## Pitfalls

1. **MiniMax 偶发 timeout**:加 retry。如果 ≥5 task 失败,记录后跑另一轮 fill-in。

2. **--narrative-llm minimax 路由确认**:这是 default,不切 env 即可。如果 Phase 3.1 实现把 minimax 当成"不切 provider"处理,直接跑就行。

3. **不要触动 prompt 模板**:跨 LLM 公平对比的根基。

4. **MiniMax wall ~2.5h 比 Opus 长**:nohup / tmux 后台跑,别让 SSH 断开打断。

5. **不要在 logs/ 之外的位置写 log**(已有 v2 目录约定)。

---

## Time budget

- Confirm: 5 分钟
- D1 narrative: ~2.5 小时(后台跑,session 等待时可写 D4 草稿)
- D2 verifier: ~1 小时
- D3 aggregator: 5 分钟
- D4 报告: 30 分钟
- D5: 5 分钟

**Total: ~4 小时 wall**(其中 3.5 小时是 LLM 调用,你不用守着)

---

## First action checklist

第一回合:
1. 读 6 个 background 文件
2. 确认 `--narrative-llm minimax` 现状(代码 / commit 历史)
3. 报告 MiniMax default model 名(`MiniMax-M2.7` ?)
4. 报告 Opus / GPT-5.5 当时跑的具体命令(从 logs/v2/sub6b_opus.log 找)
5. 估算 D1 + D2 wall time
6. 任何 clarifying question

不要跑命令直到 confirm。
