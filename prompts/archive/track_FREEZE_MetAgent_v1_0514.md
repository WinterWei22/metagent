# Track: Freeze MetAgent-v1-0514

## 目的

把当前代码状态(Phase A3 完成 + A4 D0 cross-LLM smoke)固化为 **MetAgent-v1-0514**,作为接下来 prompt-grammar 重写实验的对照基线。封存后我们要能:

1. 任意时刻 checkout 回这个版本复现 Sub-6A / Sub-6B 主指标
2. 在论文写作期间作为 "v1 baseline" 引用
3. 后续 prompt 重写(Phase B1)出问题时回滚

## Deliverables

### D0 — Tag + Branch
- 创建 git tag `MetAgent-v1-0514`,指向当前 `main` HEAD(commit `2bf6517` 或确认当前 HEAD)
- 创建 long-lived branch `release/v1-0514`,从同一 commit 拉出,用于后续 hotfix
- **不要 commit 当前 worktree 的 dirty 改动**,先 `git status` 确认这些是 phase A 遗留的实验性修改;如果是有价值的改动,先 commit 到 main 再打 tag

### D1 — 封存报告 `summary/freeze/MetAgent-v1-0514.md`

完整结构如下,**所有数字必须从现有 report / verdict 文件读出来,不允许编造**:

#### §1 版本全貌(One-pager)
- 当前阶段:Phase A3 完成 + A4 D0 cross-LLM smoke hooks landed
- 三大组件:Stage 1(Spec→Mol)/ Stage 2(Mol→Pathway narrative)/ Verifier cascade(10 layers)
- 默认 LLM:MiniMax-M2.7(T=0)
- Benchmark:Sub-6A 38 task / 459 spectra,Sub-6B 63 task(含 LIPID MAPS v3 的 11 个 lipid task)
- 关键能力清单:
  - ReAct loop(5 function tool + dedup cache + max_turn=5)
  - Verifier feedback loop(prevention + correction,max_iter=2,quality rollback)
  - 10 层 verifier cascade(A-F + 6a/6b/6c/6d)
  - K=10 task-level asyncio 并行,~8× speedup
  - Retry-with-backoff(5xx / Timeout / 529)

#### §2 复现方式

完整列出从 clean checkout 到主指标复现的命令,每条注明预期 wall time:

```bash
# 0. 环境
git checkout MetAgent-v1-0514
conda env create -f environment.yml  # 或 pip install -r requirements.txt
# 列出关键依赖版本:python, openai-sdk, sqlite, sirius-cli, ...

# 1. 数据资产校验
python scripts/check_assets.py        # GNPS / PubChem-Lite / HMDB / KEGG / RaMP / LIPID MAPS sqlite 路径
# 列出每个 DB 的预期 sha256 或 row count

# 2. Sub-6A 复现(459 谱)
python evaluation/sub6/run_sub6a.py --config configs/sub6a_v1.yaml
# 预期 wall time:~X 小时 @ K=10
# 输出:data/eval/sub6/sub6a_perfect_id_verdicts_v5_opus47.jsonl(或对应文件)

# 3. Sub-6B closed-loop 复现(63 task,N=3 reruns)
python evaluation/sub6/run_sub6b_react_feedback.py --config configs/sub6b_v1_minimax.yaml --seeds 0,1,2
# 预期 wall time:~Y 小时
# 输出:data/eval/sub6/v4_a3_d3_with_lit/ 等

# 4. 聚合报告
python scripts/eval_sub6/aggregate_*.py
# 输出:reports/agent/phase_a3_audit.md
```

每条命令必须真实可运行,**调研后填进去**,不要写 placeholder。

#### §3 主指标快照表

| 指标 | 数据 | 来源文件:行号 |
|---|---|---|
| Sub-6A top-1 identification | 67.32% | (待填:从 phase_a3_audit.md 或 sub6a verdict 算) |
| Sub-6B supported (closed-loop, fb_nolit, N=3) | 25.23 ± 6.16% | `reports/agent/phase_a3_audit.md` §1.1 |
| Sub-6B supported (closed-loop, +literature, N=3) | 25.70 ± 7.16% | 同上 |
| Sub-6B contradicted (fb_nolit, N=3) | 1.97 ± 1.03% | 同上 |
| Sub-6B contradicted (+lit, N=3) | 2.20 ± 1.31% | 同上 |
| Sub-6B unverifiable_v0(known issue) | 63-67% | `reports/agent/diagnosis_unverifiable_and_correlation.md` |
| Layer E literature 调用率 | ~70% | A3 D1b audit |
| Wall time(per task,K=10 parallel) | ~Z 秒 | A3 D2 wall time 章节 |

#### §4 结果路径清单

所有产物文件的绝对路径 + 说明:

- `data/eval/sub6/v4_a3_d3_react_only/` — A3 D3 react-only baseline
- `data/eval/sub6/v4_a3_d3_fb_nolit/` — closed-loop without literature
- `data/eval/sub6/v4_a3_d3_with_lit/` — closed-loop + literature
- `data/eval/sub6/v4_a3_d3p5_*/` — N=3 reruns subset(10 task × 3 seeds)
- `data/eval/sub6/sub6a_perfect_id_verdicts_v5_opus47.jsonl` — Sub-6A v5
- `reports/agent/phase_a1_smoke_audit.md`
- `reports/agent/phase_a2_feedback_audit.md`
- `reports/agent/phase_a3_audit.md`
- `reports/agent/diagnosis_unverifiable_and_correlation.md`
- `reports/agent/prompt_audit_for_rewrite.md`
- `summary/May_7/STAGE_REPORT.md` — v2 stage report
- `summary/May_7/figures/` — 9 张 Nature-style 图

每条路径 `ls -la` 确认存在 + 写 size 和 mtime,**不存在的不要写进去**。

#### §5 已知缺陷(交给 v2 的债)

明确列出 v1 的已知问题,引用诊断报告:

1. **UNVERIFIABLE_v0 占比 63-67%**(`diagnosis_unverifiable_and_correlation.md`)
   - 根因:narrative prompt 无句式约束 + extractor 不过滤 + classifier 收编抽象句 + feedback hint 对 UNV neutral
2. **supported ≠ task-correct**:claim-level supported 与 pathway 选择正确性仅 +8pp 弱相关
3. **MS-CLIP 写好但未开**
4. **literature integration 是 null result**(N=3 CI 跨 0)
5. **Sub-6A IdReport 注入与 Sub-6B 共用同一份 narrative prompt**,未分化
6. **Verifier 内部 sequential LLM call** 是 wall time 真瓶颈

#### §6 关键代码入口锚点

给后来人读代码的 5 分钟导航:

- Stage 1 流水线:`evaluation/sub6/run_sub6a.py:XX` → `pipeline/stage1.py:XX`(确认实际路径)
- Stage 2 narrative(single-call):`evaluation/sub6/prompts.py:12-29`
- Stage 2 narrative(ReAct):`prompts/agent/sub6b_react_prompt.md` + `evaluation/sub6/prompts_agent.py:60`
- Feedback runner:`evaluation/sub6/run_sub6b_react_feedback.py`
- Claim extractor:`verifier/claim_extractor.py:169` + `verifier/prompts/extract_claims.py`
- Claim classifier:`verifier/claim_classifier.py` + `verifier/prompts/classify_ambiguous.py`
- Layer 路由:`verifier/agent.py:494-518`(Sub-6 dispatch)
- Feedback hint:`verifier/feedback_hints.py:57`(_NEUTRAL_VERDICTS)
- 10 个 layer:`verifier/layers/*.py`
- LLM client:`common/llm_client.py`
- 5 个 function tool:`tools/agent_tools/`

### D2 — Worktree dirty 改动的去向决定

当前 worktree 有 10 个 modified file + 一堆 untracked。**逐项决定**:

| 文件 | 决定 | 理由 |
|---|---|---|
| `verifier/claim_extractor.py` (M) | (保留 / 丢弃 / cherry-pick 到 release) | (例如 A3 实验改动,需要回归测试) |
| `verifier/prompts/extract_claims.py` (M) | | |
| `data/eval/sub6/sub6a_*.jsonl` (??) | | (是否纳入 release artifact) |
| ... | | |

输出到 `summary/freeze/MetAgent-v1-0514_dirty_disposition.md`,每条带决定 + 操作命令。

### D3 — Smoke 回归(打 tag 前必做)
- 用 release tag 状态跑 1 个 Sub-6A task + 1 个 Sub-6B task 端到端
- 比对 verdict 字段(verdict 分布、claim 数、wall time)与 A3 audit 的预期范围
- 通过才打 tag,否则修到通过为止

## 执行约束

- 不允许编造数字。报告里每个 metric 必须 grep 出来源文件。
- 不允许在 release branch 上 commit 新逻辑,只 freeze 现状。
- 打 tag 前 `git status` 必须清洁(或者你已经决定好 dirty file 怎么处理并执行了)。
- 报告中所有命令必须真实可运行,运行不通的现在修好或者注明 "TODO: requires X"。

## 完成条件

- [ ] `git tag MetAgent-v1-0514` 存在,指向正确 commit
- [ ] `release/v1-0514` branch 存在
- [ ] `summary/freeze/MetAgent-v1-0514.md` 完成,§1-§6 全填
- [ ] `summary/freeze/MetAgent-v1-0514_dirty_disposition.md` 完成
- [ ] D3 smoke 回归通过截图/日志附在报告里
- [ ] 在 main 提一个 commit:`chore(freeze): MetAgent-v1-0514 release`,附 tag 说明
