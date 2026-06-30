# MetAgent W17 — Evidence Parity (SubsixSourceReport schema extension)

**Sprint type**: ⚠ Schema-extend(`[schema-extend-warning]` discipline)+ ✅ Add helper/consumer code
**Duration**: 3-5 day(D0 onboarding / D1 dual-audit / D2 RED + schema design / D3 GREEN / D4 Path X smoke verify / D5 close-out)
**Date launched**: 2026-06-08
**Working tree**: `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2/`
**Branch**: `metagent-v2`
**Model name**: **MetAgent**(不是 ConcordMet)
**Predecessor**: W16 回滚 commit `5933cdd4`(signal_sub6 dispatcher disabled,layer/helper/unit tests 保留)

---

## §0 Onboarding(在任何代码动作前必读)

### A. 战略上下文 — 为什么有 W17

W16 D4 失败教训(诊断报告 `reports/agent/w16_signal_sub6_d4_diagnostic.md`):

- signal_sub6 layer 设计时假设 verifier 能查 multi-paradigm 数值证据
- **实际 `SubsixSourceReport` 只有 `ramp_enrichment_result` 一个 numeric carrier**
- ReAct narrative 引用 5 种 paradigm(RaMP / Mummichog / MetaboAnalystR / SSPA / FELLA + 可能 Reactome),verifier 拿 RaMP 单一 carrier 对所有,**17/18 verdict 误判 CONTRADICTED**
- UV 44.25% → 47.67%(+3.42pp),pathway 86% → 81%

**用户 2026-06-08 拍板路线**:α 不写 verifier 层,**先把数据通道建好**——`SubsixSourceReport` schema 扩 method-keyed carriers,让 verifier 能看到 ReAct 实际调用的所有 paradigm 的结构化输出。

α 是 W18 β LLM-judge 和 W19 γ KB 工具的 **foundation**——没有这一步,β 和 γ 都不能合理工作。

### B. W17 不做什么(铭刻于心)

| Non-goal | 理由 |
|---|---|
| ❌ 不写新 verifier 层 | W17 是 plumbing,β 是 verifier 升级,分两步 |
| ❌ 不改 signal_sub6 / factual_sub6 / set_enrichment 已有 layer 逻辑 | 保持纯 schema 扩展,不动 ⚠ Modify 区 |
| ❌ 不重启用 signal_sub6 dispatcher catch-all | 留给 W18 β rebuild |
| ❌ 不动 ReAct prompt | producer 端 W14 已稳定 |
| ❌ 不写 paper narrative | 死命令 |
| ❌ 不顺手做 W18 β / W19 γ | scope discipline |

### C. 死命令(全部 active)

1. **中文交流**,代码英文 — `feedback_language_chinese`
2. **MetAgent LLM-driven**,KB 工具明确可暴露 — `feedback_metagent_must_be_llm_driven`(2026-06-08 边界澄清版)
3. **MiniMax remote API**,成本必从 `logs/concord/*.jsonl` 读 — `reference_minimax_is_remote_api`
4. **每条回复结尾 2 段大白话总结** — `feedback_plain_summary_at_end`,禁 strict-TDD/sprint/commit 术语
5. **Verifier 修改三档准则 + 新增 schema 扩展子条** — `feedback_verifier_modification_policy`
   - ✅ Add helper / consumer / 新 carrier 字段 → 自由
   - ⚠ **Schema 扩字段(本 sprint 主要操作)** → commit body 必含 `[schema-extend-warning]` + ping me + B1 paper 数据 load 验证
   - ❌ 改 SubsixSourceReport 现有字段类型 / 删字段 / 改语义 → 默认禁
   - ❌ 改 B1-core helper(`claim_extractor` / `feedback_hints` / `_extract_classify`)→ 默认禁
6. **3 护栏**:tag `metagent-v2-base-b1 @ ed6243b` immutable / B1 paper 数据 immutable / B1 test 14-fail floor 不退步
7. **Multi-paradigm verification 必做 data carrier audit** — `feedback_multi_paradigm_data_carrier_audit`(W16 D4 教训)
   - **本 sprint D1 第一步就是这个 audit,审计输出是 D2 RED 的前置依赖**
8. **不写 paper narrative** — `feedback_no_paper_writing_yet`
9. **重要 design 决策存档** — `feedback_design_decisions_archive`,W17 D5 必须写 `docs/decisions/2026-06-08_w17_subsix_source_report_schema_extension.md`
10. **跨 session 通信** — `reference_conversation_channel`,每个 task-ending reply 必写 master log
11. **Strict TDD per-piece**:每个 piece 先 RED commit 后 GREEN commit,0 slip

### D. 必读 memory 文件(D0 第一步)

```
feedback_language_chinese.md
feedback_proceed_with_defaults.md
feedback_metagent_must_be_llm_driven.md     # 重读最新版,V3 vs KB 边界澄清
reference_minimax_is_remote_api.md
feedback_plain_summary_at_end.md
feedback_verifier_modification_policy.md    # 重读最新版,schema 扩展子条
feedback_no_paper_writing_yet.md
feedback_uv_sprint_must_reclassify_first.md
feedback_multi_paradigm_data_carrier_audit.md  # 新立(W16 教训)
feedback_design_decisions_archive.md
project_metagent_v2_merge.md
reference_conversation_channel.md
```

### E. 必读项目工件(D0 第一步)

```
reports/agent/w16_signal_sub6_d4_diagnostic.md                            # W16 失败诊断
docs/decisions/2026-05-26_uv_root_cause_attribution_framework.md          # W15 attribution
data/metagent/w15_uv_attribution/summary.md                               # 数据
data/metagent/w15_uv_attribution/attribution_v2.csv                       # 重分类
verifier/agent.py                                                         # dispatcher 当前状态
verifier/helpers/enrichment_lookup.py                                     # 当前只读 ramp 的实证
verifier/layers/signal_sub6.py                                            # 暂禁的 layer(保留)
verifier/layers/factual_sub6.py                                           # W12 layer(本 sprint 不动)
verifier/layers/set_enrichment.py                                         # W12 Stage 2/3 layer
# SubsixSourceReport schema 定义文件需要 D0 grep 定位
# 提示:grep -r "class SubsixSourceReport\|SubsixSourceReport(" .
concord/agent/react_runner.py                                             # 上游产出 carrier 的源头
prompts/track_CONCORD_W12_C7_namespace_fix.md                             # factual_sub6 同款 schema-related pattern
```

---

## §1 Goals & Non-Goals

### Goals

| ID | Goal |
|---|---|
| G1 | D1 完成 **dual data carrier audit**:claim 端引用的 paradigm 全集 vs SubsixSourceReport 当前实际承载的 carrier 全集,cross-tab 输出 |
| G2 | D2 设计 `SubsixSourceReport` schema 扩展方案(新增 method-keyed carrier 字段),写 RED 测试 |
| G3 | D3 实现 schema 扩展(新增字段为 Optional/nullable,B1 老数据 load 默认 None 不破)+ 上游 wrapper 把数据传入 SubsixSourceReport(若上游已有结构化输出) |
| G4 | D4 跑 Path X full-63 smoke verify:UV / pathway / cost 不退步(α 不期望 UV 降幅;只验不破) |
| G5 | D5 写 decision doc `docs/decisions/2026-06-08_w17_subsix_source_report_schema_extension.md` + memory 更新 |

### Non-Goals

- ❌ 不写新 verifier 层(W18 β 范畴)
- ❌ 不接 KEGG REST / PubMed / Reactome API(W19 γ 范畴)
- ❌ 不重启用 signal_sub6 dispatcher
- ❌ 不动 factual_sub6 / set_enrichment / signal_sub6 内部逻辑
- ❌ 不期望 UV 降幅(α 是 plumbing,降幅留给 β)
- ❌ 不动 ReAct prompt
- ❌ 不顺手做其他 sprint 的事

---

## §2 Architecture(D1 audit 后细化)

### 当前(W16 回滚后)

```python
# verifier/grammar.py or similar(D0 grep 定位)
class SubsixSourceReport:
    differential_metabolites: list[...]
    curated_hmdb: list[...]
    ramp_enrichment_result: dict | None    # 唯一 numeric carrier
    # ... 其他字段
```

verifier/helpers/enrichment_lookup.py 当前:
```python
def lookup_signal_evidence(mention, source_report):
    top_pathways = (source_report.ramp_enrichment_result or {}).get("top_pathways")
    # ↑ 只查 RaMP,忽略 mention.method
```

### W17 α 目标(待 D1 audit 校准)

```python
class SubsixSourceReport:
    # 现有字段(全部保留,字段类型/语义不变)
    differential_metabolites: list[...]
    curated_hmdb: list[...]
    ramp_enrichment_result: dict | None
    
    # NEW:method-keyed carriers(D1 audit 列出实际需要的)
    mummichog_enrichment_result: dict | None = None     # 候选
    sspa_enrichment_result: dict | None = None          # 候选
    fella_enrichment_result: dict | None = None         # 候选
    metaboanalystr_enrichment_result: dict | None = None  # 候选
    reactome_enrichment_result: dict | None = None      # 候选
    # 也可能需要 statistical-method-keyed:
    ora_result: dict | None = None
    gsea_result: dict | None = None
    msea_result: dict | None = None
    qea_result: dict | None = None
    topology_result: dict | None = None
    
    # 选哪些 / 字段命名 / 是否需要嵌套 → D1 audit 输出决定
```

**关键设计原则**:
- 所有新字段 **Optional + default None**,B1 老数据反序列化不破
- 所有新字段 **仅 add,不改老字段**
- 新增字段添加到 schema **末尾**(避免 positional 序列化的潜在问题)
- 上游 wrapper(`concord/agent/react_runner.py` 或 PA tool 调用层)若已有结构化输出,**直接传入**;若只有 narrative 字符串,**留 None,W17 不强行解析**

---

## §3 Daily Breakdown

### D0(~0.3d)— Onboarding

1. 读 §0.D 全部 memory 文件
2. 读 §0.E 全部项目工件
3. 回报当前 git status + branch + HEAD(应 `metagent-v2 @ 5933cdd4` 或 更新)
4. 跑 `pytest tests/` 记录 baseline fail count(应 ≤ 14)
5. **grep 定位 SubsixSourceReport schema 定义文件**,把绝对路径记录在 master log
6. **grep 定位 5 PA tool wrapper 实现位置**(`run_ora` / `run_gsea` / `run_msea` / `run_qea` / `run_topology` + `mummichog` / `sspa` / `fella` / `ramp` / `metaboanalystr` adapter),记录路径
7. Ping user 报 D0 6 项

### D1(~0.5-1d)— **Dual Data Carrier Audit**(死命令 `feedback_multi_paradigm_data_carrier_audit`)

**这是 W17 最关键的一步,不允许跳过。**

#### D1.1 Claim 端 paradigm 引用全集

1. Pull W15 v2 attribution CSV(`data/metagent/w15_uv_attribution/attribution_v2.csv`)中 verifier_gap + both 标签的 claim
2. 加上 W16 D4 results jsonl(`data/metagent/w16_path_x_post_signal_sub6/path_x_full63_results.jsonl`)里所有 UV claim 的 narrative excerpt
3. 用 MiniMax 抽 paradigm 标签(prompt:"列出 claim 文本中引用的 paradigm 名称,如 RaMP / Mummichog / SSPA / FELLA / MetaboAnalystR / Reactome / KEGG / 其他,无引用则 NONE")
4. 输出 `data/metagent/w17_carrier_audit/claim_paradigm_inventory.csv`(claim_id, claim_text_excerpt, paradigms_cited list, method_prefix if any)
5. 统计:每个 paradigm 的 claim 引用计数 + 占比
6. 写 `data/metagent/w17_carrier_audit/claim_paradigm_summary.md`

成本预估:~$1-2 MiniMax,死命令要求从 jsonl 读实际值。

#### D1.2 Carrier 端 SubsixSourceReport 实际承载全集

1. 读 SubsixSourceReport schema 定义,列出现有字段
2. **实测**:对 W16 D4 trace dump 中的 SubsixSourceReport 实例,统计每个字段非空 / 包含 `top_pathways` 等 numeric 子结构的实例占比
3. 对每个 paradigm wrapper(D0 step 6 定位),检查 wrapper 函数返回结构,是否产出结构化 dict 可入 SubsixSourceReport
4. 输出 `data/metagent/w17_carrier_audit/carrier_actual_inventory.csv`(paradigm, wrapper_function, returns_structured_dict, schema_field_if_exists)
5. 写 `data/metagent/w17_carrier_audit/carrier_actual_summary.md`

#### D1.3 Cross-tab + MISSING_CARRIER flag

1. Cross-tab:每个 D1.1 列出的 paradigm × D1.2 列出的 carrier
2. 标记 MISSING_CARRIER:claim 引用了 但 SubsixSourceReport 没承载的 paradigm
3. 输出 `data/metagent/w17_carrier_audit/carrier_audit_crosstab.md`:
   - Table A: paradigm × claim count × carrier exists
   - Table B: MISSING_CARRIER list with rationale(是 wrapper 不产 / 还是 wrapper 产但没传 / 还是 schema 缺字段)
   - Table C: W17 α 应该新增的 schema 字段清单 + 优先级
4. **如果某 paradigm 的 wrapper 根本不产结构化输出(只产 narrative string)→ 该 paradigm 留 None,W17 不为其加字段**
5. Ping user 报 audit 结果,**等 user OK schema 字段清单才进 D2**

### D2(~0.5-0.8d)— Schema Design + RED

#### D2.1 Schema design doc(预备稿)

写 `docs/decisions/2026-06-08_w17_subsix_source_report_schema_extension.md`(draft 版,D5 finalize)。包括:
- Context: W16 D4 教训 + 用户 6-08 路线决策
- Options considered(为什么是 schema 扩展而不是新 envelope 类)
- Decision: 新增字段清单(D1 audit 输出)
- Backward compatibility: Optional + default None
- Consequences: 哪些下游 consumer 需要更新(若有)

#### D2.2 RED tests

文件:`tests/test_w17_subsix_source_report_schema_extension.py`(新)

Cases(≥6):
1. SubsixSourceReport() 默认构造 → 所有新增字段为 None
2. SubsixSourceReport(mummichog_enrichment_result={...}) → 字段可读
3. 反序列化 B1 老 paper 数据(`data/eval/sub6/b1_d5_*/.../some_task.json`)→ load 成功 + 新字段为 None
4. 序列化含新字段的实例 → 包含字段名
5. 类型 hint 正确(`dict | None`)
6. 老 consumer 代码读 ramp_enrichment_result 不受影响

文件:`tests/test_w17_wrapper_carrier_passthrough.py`(新)— 若 D1.2 发现 wrapper 已产出结构化结果但未传入

Cases(≥3,数量取决于 D1 audit 结果):
- ora wrapper 输出 → 进 source_report.ora_result
- mummichog wrapper 输出 → 进 source_report.mummichog_enrichment_result
- ...

Commit: `test(verifier): W17 D2 RED — SubsixSourceReport schema extension`

跑 RED 确认全 fail。

### D3(~1-1.5d)— GREEN

按 D2 写的 RED 测试逐个绿:

1. 扩 SubsixSourceReport schema(add fields at end)
2. 更新 schema serializer / deserializer 如有
3. 更新 wrapper 把结构化输出传入 SubsixSourceReport(D1 audit 列出的)
4. 每个 piece 独立 commit,每个 commit body 必含 `[schema-extend-warning]` block:
   ```
   [schema-extend-warning]
   This commit extends SubsixSourceReport schema per feedback_verifier_modification_policy
   2026-06-08 sub-rule. Only adds new Optional[dict] fields with default None.
   B1 paper data load verified (see verification section).
   ```
5. 每个 commit 后跑:
   - `pytest tests/test_w17_*.py -q` → GREEN
   - `pytest tests/` 全 repo → ≤ 14 fail
   - `pytest tests/test_factual_sub6* tests/test_set_enrichment* tests/test_signal_extractor* tests/test_enrichment_lookup* tests/test_signal_sub6.py -q` → 0 退步
6. **B1 paper 数据 load 验证**:
   - 写一次性脚本 `scripts/metagent/w17_b1_paper_data_load_verify.py`
   - Load `data/eval/sub6/b1_d5_*/.../some_task.json`(若存在)
   - 确认 SubsixSourceReport 反序列化成功,新字段为 None,老字段一致
   - 输出 `data/metagent/w17_carrier_audit/b1_paper_data_load_verify.md`
   - Commit `[schema-extend-warning]` 必须 link 到这份 verify 报告

### D4(~0.5d)— Path X smoke verify

**目的**:验证 schema 扩展不破现有 verifier / ReAct pipeline。**不期望 UV 降幅**——α 是 plumbing。

1. 跑 Path X full-63(MiniMax,K=10 docker concurrent),输出到 `data/metagent/w17_path_x_post_schema_extend/`
2. 计算指标:
   | 指标 | 期望 | W14 / W16 baseline |
   |---|---|---|
   | UV rate | 基本不变 ±1pp(W14 44.25% 附近) | W14 44.25% |
   | Pathway accuracy | 不退步(≥84%) | W14 86% |
   | iter-2 deg | = 0 | W14/W16 0 |
   | Cost | ≤ $15 | W14 $6.83 |
3. 如有任一退步 → STOP,写 master log ping user 决断
4. 输出 `data/metagent/w17_path_x_post_schema_extend/summary.md`

### D5(~0.3d)— Close-out

1. Finalize `docs/decisions/2026-06-08_w17_subsix_source_report_schema_extension.md`(包括 D4 实测数字)
2. Memory 更新:
   - 若 D1 audit 揭示新教训 → append 到 `feedback_multi_paradigm_data_carrier_audit.md`
   - 若 schema 扩展过程发现 ⚠ 子条还需细化 → append 到 `feedback_verifier_modification_policy.md`
3. 把 W18 β 启动的 prerequisite checklist 写进 decision doc(W18 prompt 写 signal_sub6 rebuild 时要 reference 哪些新字段)
4. Sprint close-out ping(2 段大白话总结 + 实际数字)

---

## §4 Hard Gates(全部 PASS 才能 close-out)

| Gate | Target | Verify |
|---|---|---|
| **HG-1** | D1 carrier audit 输出完整,Tables A/B/C 全存在 | `data/metagent/w17_carrier_audit/` |
| **HG-2** | LLM-vs-human 20-sample agreement ≥80%(D1.1 paradigm 抽签校准) | spot-check 报告 |
| **HG-3** | SubsixSourceReport 新增字段全 Optional + default None | schema diff |
| **HG-4** | B1 paper 数据 load 验证通过 | `b1_paper_data_load_verify.md` |
| **HG-5** | D4 Path X UV 不退步(±1pp 容差) | `summary.md` |
| **HG-6** | D4 pathway accuracy ≥84% | 同上 |
| **HG-7** | D4 iter-2 deg = 0 | 同上 |
| **HG-8** | D4 cost ≤ $15(actual,from jsonl) | `logs/concord/*.jsonl` |
| **HG-9** | B1 test 14-fail floor 不退步(每个 commit 后跑) | `pytest tests/` |
| **HG-10** | factual_sub6 / set_enrichment / signal_sub6 unit / dispatcher preservation tests 全 GREEN | focused pytest |
| **HG-11** | Schema 改字段类型 / 删字段 / 改语义 commit 数 = 0 | `git diff` audit |
| **HG-12** | B1-core helper(claim_extractor / feedback_hints / _extract_classify)未碰 | `git diff --name-only` audit |

---

## §5 Risks & Stop Conditions

| Risk | Stop trigger | User decision |
|---|---|---|
| D1 audit 发现 wrappers 根本不产结构化输出 | 大部分 paradigm 是 narrative-only | YES — stop ping option {A: 缩 scope 只扩 wrapper 已产的 paradigm / B: pivot 到 W17 改 wrapper 让它产结构化 / C: 放弃 α 直接做 β LLM-judge} |
| D2 schema 设计发现 SubsixSourceReport 是 protobuf/复杂序列化 | schema 扩展机械复杂度 > 预期 | YES — stop ping 设计选项 |
| D3 实测 B1 paper 数据 load 破 | HG-4 fail | YES — STOP,撤回 commit |
| D4 UV 退步 > 1pp | HG-5 fail | YES — schema 扩展意外影响 verifier 行为,深挖原因 |
| D4 pathway < 84% | HG-6 fail | YES — STOP,撤回 |
| D4 cost > $20 mid-run | budget 失控 | YES — STOP abort |
| 任何 commit 触动 `_extract_classify` / `claim_extractor` / `feedback_hints` | HG-12 fail,❌ 档触发 | YES — STOP immediately ping |
| 任何 commit 改 SubsixSourceReport 老字段类型 / 删字段 / 改语义 | ❌ 档触发 | YES — STOP immediately ping |

---

## §6 Banned phrases

- 不写 paper narrative:"Our results show...", "We demonstrate...", "In conclusion,...", footnote prose
- 不说 "$0 local"(MiniMax 是远程 API)
- 大白话总结不用 strict-TDD / commit / sprint / RED / GREEN / Hard Gate 术语
- 不 push 任何 commit 到 remote
- 不 force tag / 不删 tag

---

## §7 输出工件清单(D5 末必须存在)

```
# D1 audit
data/metagent/w17_carrier_audit/
  ├─ claim_paradigm_inventory.csv
  ├─ claim_paradigm_summary.md
  ├─ carrier_actual_inventory.csv
  ├─ carrier_actual_summary.md
  ├─ carrier_audit_crosstab.md
  └─ b1_paper_data_load_verify.md

# D2 RED
tests/test_w17_subsix_source_report_schema_extension.py
tests/test_w17_wrapper_carrier_passthrough.py        # 若 D1 显示有需要

# D3 GREEN
<SubsixSourceReport schema file>                     # ⚠ schema-extend-warning commit
<wrapper passthrough files>                          # ✅ Add commits
scripts/metagent/w17_b1_paper_data_load_verify.py

# D4 verify
data/metagent/w17_path_x_post_schema_extend/
  ├─ path_x_full63_results.jsonl
  └─ summary.md

# D5 close-out
docs/decisions/2026-06-08_w17_subsix_source_report_schema_extension.md
```

---

## §8 Memory updates expected at D5

- `feedback_multi_paradigm_data_carrier_audit.md` — append D1 实测 lesson(若有)
- `feedback_verifier_modification_policy.md` — 若 schema 扩展过程发现 ⚠ 子条需细化(比如序列化 / B1 load 步骤标准化)→ append
- 新 memory 候选:若 D1 揭示 paradigm wrapper 设计教训 → 写 `reference_paradigm_wrapper_structured_output.md`

---

## §9 First action upon receiving this prompt

1. 中文 ack,**结尾 2 段大白话总结**
2. 执行 §3 D0 全部 7 步
3. Ping user with D0 报告
4. **不进 D1 直到 user OK D0 报告**
5. D1 carrier audit 写完 ping user **报 audit 结果 + schema 字段清单**,等 user OK 才进 D2

---

## §10 决断红线(立即停 ping)

- Memory 文件读不到 / 不存在 → STOP
- W15 v2 attribution CSV / W16 Path X jsonl 不存在 → STOP
- 当前 branch ≠ `metagent-v2` 或 worktree ≠ `metagent_v2` → STOP
- HEAD ≠ `5933cdd4` 或更新(回滚 commit)→ STOP
- pytest baseline > 14 fail → STOP
- D0 grep 找不到 SubsixSourceReport 定义 → STOP ping(可能 schema 在不同模块,需要确认)
- 死命令冲突 → STOP

**Ready. Go.**
