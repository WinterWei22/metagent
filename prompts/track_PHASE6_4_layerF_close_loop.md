# Track PHASE 6.4 — Close the Layer F loop on Config C narratives

**Session ID:** `track_PHASE6_4_layerF_close_loop`
**Branch:** `feature/sub6-llm-reranker`(Phase 6.3 已 wire 完,本 session 只差最后一步)
**Estimated work:** 1-2 hours wall(无 LLM 成本)
**Predecessor:** `reports/eval/llm_reranker_v2.md` §6(诊断已完成,根因明确)

---

## Why this matters

Phase 6.3 已经把 Layer F 路径**完全 wire 通**:
- LLM-as-reranker 输出 881 peak_claims(`data/eval/sub6/v2_phase6_3/C_msclip_llm/sub6a_narratives.jsonl`)
- `verifier/agent.py` Sub-6 dispatcher 加了 PEAK_MECHANISTIC 路由分支
- `schemas/sub6_report.py` 加了 `experimental_spectrum` adapter

**但 D7 verifier 用 Opus-4-7 extractor 跑出来 0 个 peak_mechanistic claim**——因为 Opus extractor 把复合句子(含 m/z + mechanism)拆成 atomic claim,各自只有 m/z 或 mechanism 单边,Layer F regex 不触发。

**关键证据**:同一 narrative 用 **rule-based fallback extractor** 跑(D7 v1 因 viviai 余额耗尽触发)→ **129 个 peak_mechanistic claim**(报告 §6.2)。

本 session 干 1 件事:**让 verifier 用 rule-based extractor 重跑 Config C narratives**,同时 dispatcher patch 已就位 → Layer F 应该出 ~100+ verdict。**无 LLM 调用成本**。

---

## Hard scope boundaries

**You MAY:**
- 改 verifier 调用方式让其用 rule-based extractor(可能是改 `claim_extractor.py` 的某个 fallback 开关,或 `grade_with_verifier.py` 加 CLI flag)
- 在 Config C 现有 narratives 上重跑 verifier(narratives 文件不重新 LLM 生成)
- 写报告 `reports/eval/layerf_loop_closed.md`

**You MAY NOT:**
- 重跑 LLM-as-reranker(narratives 已 freeze)
- 重跑 SIRIUS / CFM-ID
- 修 verifier layer 算法(Layer F 已 ready)
- 修 dispatcher patch(Phase 6.3 加的 5 行已正确)
- 跑 Sub-6B / Sub-6A perfect

**Optional 但 nice-to-have**(如果 1 小时内能完成):
- 修 Opus extractor prompt(`verifier/prompts/extract_claims.py`)让它不拆 mechanistic 复合句。如果能,跟 rule-based 跑结果对比

---

## Background reading

1. `reports/eval/llm_reranker_v2.md` §6.2(诊断细节)
2. `verifier/claim_extractor.py`(看 LLM extractor vs rule-based fallback 怎么切)
3. `verifier/prompts/extract_claims.py`(Opus extractor prompt,可能是 atomic 拆解的根因)
4. `verifier/claim_classifier.py:107-119`(Layer F 触发的 regex contract)
5. `verifier/layers/peak_mechanistic.py`(Layer F 算法)
6. `data/eval/sub6/v2_phase6_3/C_msclip_llm/sub6a_narratives.jsonl`(881 peak_claims 来源)
7. `logs/v2_phase6_3/C_verifier.log`(D7 v1 rule-based 跑出来 129 claim 的现场,可作 sanity benchmark)

In your first response,确认:
- rule-based extractor 在 codebase 怎么触发(是 fallback 还是有 explicit flag)
- D7 v1 log 里 129 claim 的具体路径(能直接读出来对比)
- 估算重跑 verifier wall(无 LLM 应该 < 30 min)

不要写代码或跑命令,直到 confirm。

---

## Deliverables

### D1 — 复现 rule-based 路径(30 min)

读 `claim_extractor.py`,定位 LLM vs rule-based 切换逻辑。

3 种可能:
- A: 已有 env var / CLI flag(如 `METAGENT_VERIFIER_EXTRACTOR=rule`)→ 直接设置即可
- B: rule-based 是 catch-all fallback(LLM 失败才走)→ 加一个 force flag
- C: rule-based 不直接可用 → 抽出来作独立 path

报告哪种情况,采取最小动作。

### D2 — 重跑 verifier on Config C narratives(15-30 min wall)

```bash
PYTHONPATH=. <env-var-or-cli-flag-for-rule-based> \
    python scripts/eval_sub6/grade_with_verifier.py \
    --narratives data/eval/sub6/v2_phase6_3/C_msclip_llm/sub6a_narratives.jsonl \
    --output data/eval/sub6/v2_phase6_3/C_msclip_llm/verdicts_v9_phaseC_rulebased.jsonl
```

不覆盖现有 `verdicts_v9_phaseC.jsonl`(D7 Opus extractor 结果)。

预期:
- total claims ≈ 1958(D7 v1 数字)
- peak_mechanistic_claim ≈ 100-150
- Layer F dispatched > 0
- Layer F SUPPORTED + CONTRADICTED + UNVERIFIABLE_v0 三类都非零

### D3 — Aggregate Layer F 数字

新增 CSV `data/paper_figures/phase6_4_layerf_activation.csv`:

```csv
extractor,total_claims,peak_mech_claims,layer_f_dispatched,layer_f_supported,layer_f_contradicted,layer_f_unsupported,layer_f_unverif
opus47 (D7 v3),1484,0,0,0,0,0,0
rule-based (Phase 6.4),?,?,?,?,?,?,?
```

跟 D7 Opus extractor 对比成 paper finding:**LLM extractor 当前对 mechanistic 复合句不友好,rule-based 反而更适合**。

### D4 — 5 个 Layer F case study(关键!paper 用)

从 verdicts_v9_phaseC_rulebased.jsonl 挑 5 个有代表性的 peak_mechanistic verdict:
- 2 个 SUPPORTED(both SIRIUS + CFM-ID 一致)
- 1 个 CONTRADICTED(LLM 编了 m/z 或 mechanism 不对)
- 1 个 UNVERIFIABLE_v0(tools_disagree)
- 1 个 NEEDS_HUMAN_REVIEW(escalate)

每个 case 完整展示:
- LLM-as-reranker 写的原句(从 narrative 找)
- Layer F 的 evidence(SIRIUS top formula / CFM-ID predicted peak / consensus)
- Verdict + reasoning

这是 paper Figure 的核心数据,**比 §5.1 的数字表更有 storytelling 价值**。

### D5 — 报告 `reports/eval/layerf_loop_closed.md`

简短(2-3 页):

#### 1. Summary
2-3 行:rule-based extractor 让 Layer F 出 verdict ≈ N 个。三层成功:wired (Phase 6.3) + extracted + verified。

#### 2. Setup
跟 Phase 6.3 同 narrative + verifier 配置,只换 extractor。

#### 3. Layer F numerical state(主表)
D7 Opus extractor vs rule-based extractor 对比。

#### 4. Verdict 分布
4 类 verdict 数字 + per-类比率。SUPPORTED 占比是 paper 关键数字。

#### 5. Case study(D4 5 个)

#### 6. Limitations
- Opus extractor 的 atomic decomposition 是已知问题,留 future work
- 当前 Layer F 用 `experimental_spectrum=differential_spectra[0]` 可能 routing 不准(per-claim spectrum 未实现)
- 5 个 case study 是抽样,不是穷举

#### 7. Provenance
git commit / 输入文件 MD5 / 输出 MD5 / wall

### D6 — Acceptance

```
□ verdicts_v9_phaseC_rulebased.jsonl 存在
□ peak_mechanistic_claim count > 50(关键)
□ Layer F dispatched > 50
□ Layer F 至少有 SUPPORTED ≥ 1 + CONTRADICTED ≥ 1(否则 verifier 实质没工作)
□ 5 个 case study 完整
□ 现有 D7 Opus extractor verdicts 文件未动
□ git diff 限制在 1-2 个文件(extractor toggle + 报告)
```

如果 peak_mechanistic_claim < 30,escalate(说明 dispatcher 或 extractor 路径还有问题)。

---

## Pitfalls

1. **rule-based extractor 可能 schema 跟 Opus extractor 不一致**:验证 verdict JSONL 字段,跟 Opus 输出字段一致(supported / unsupported / contradicted / unverifiable_v0)。

2. **rule-based 抽得多 ≠ 抽得对**:129 个 peak_mechanistic claim 中可能有 false positive(rule-based 触发了不该触发的句子)。Layer F 应该把这些标 CONTRADICTED 或 UNSUPPORTED。如果**全 SUPPORTED**,可疑——可能 Layer F 在 routing 错误的 spectrum(per-claim routing 没实现的副作用)。

3. **不要触动 dispatcher patch**:Phase 6.3 加的 5 行已正确。如果 D2 verifier 仍不出 verdict,debug 在 extractor 不在 dispatcher。

4. **不要跑 LLM**:本 session 是无 LLM 成本的,任何 LLM 调用都是错。

5. **`experimental_spectrum=differential_spectra[0]` 局限性**:5 个 case study 里如果发现 false UNVERIFIABLE 是因为 routing 错(claim 提的 m/z 在 spectrum 5 里,但 Layer F 查 spectrum 0 的 peaks),在 §6 limitation 写明。

---

## Time budget

- Confirm: 15 min
- D1: 30 min
- D2: 30 min wall
- D3: 10 min
- D4: 30 min(挑 case + 写 case study)
- D5: 30 min
- D6: 5 min

**Total: ~2 hours**(无 LLM 成本,~$0)。

---

## First action checklist

第一回合:
1. 读 7 个 background 文件
2. 报告 rule-based extractor 触发方式(env var / CLI flag / fallback condition)
3. 报告 D7 v1 log 里 129 peak_mechanistic claim 出现的具体上下文(行号 / verifier output 路径)
4. 估算 D2 wall(rule-based 是不是真的 < 30 min)
5. 任何 clarifying question

不要写代码或跑命令,直到 confirm。
