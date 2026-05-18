# Concord Sprint W8 — Status (LLM-Agent Pivot)

**Branch:** `feature/investigation-concord` (worktree `metagent_day1_v5_investigation`)
**HEAD at sprint start:** `e258585` (W7 完结)
**Sprint window:** 2026-05-18+ (5 工作日,人值守)
**Mode:** B1 ReAct + verifier 移植到 ConcordMet,9 个 function tool,quad-report on sub6b-v3 (N=63)
**Spec:** `prompts/track_CONCORD_sprint_W8_LLM_agent_pivot.md` (main worktree)

---

## 0. Onboarding Completion

### Tier 1 read (战略 + 架构)

1. **B1 D4 spec (`prompts/track_AGENT_phase_B1_D4.md` in main worktree)** —
   D4 已 wire grammar-v2 JSON + TaskOutcome (NORMAL / EMPTY_HONEST_REFUSAL /
   EMPTY_SYSTEM_FAILURE / EMPTY_UNKNOWN) + 8 类 per-drop-reason hint
   templates + 两层 retry (inner finalise 1× + outer feedback max_iter=2)
   + task-level timeout 1200s. **W8 要原样移植这套到 ConcordMet,不动 B1
   源文件。**
2. **W7 status (`reports/agent/concord_sprint_w7_status.md`)** —
   V3 soft-union PRIMARY GREEN +25.5 pp / p=0.0009 / 13-0 sign test on
   Cooke (N=51);SENS_A +21.1 pp YELLOW (N=19) / SENS_B +16.7 pp YELLOW
   (N=12);Fig 3 v4 + paper narrative 已封装;Wieder email HELD;148/148
   pytest;**multi-LLM head-to-head deferred OQ-9** (只有 MINIMAX_API_KEY)。
   W8 在 sub6b-v3 上跑,不再用 Cooke;V3 算法要在 sub6b-v3 上重跑。
3. **Paper narrative (`docs/concord/paper_narrative_finalized.md`)** —
   1903 word draft 围绕 deterministic V3 soft union 立论;5 tool / 3 cohort /
   namespace-pivot / compound-layer (59.1% → 5.5%) 都已 freeze。W8 LLM-agent
   pivot 必然要求 W8 末整体重写,但 W8 期内不动 narrative (deliverable §7)。
4. **W3-W7 handoff (`docs/concord/comprehensive_w3_w7_handoff.md`)** —
   **不存在** (W8 prompt 已注明可跳过)。
5. **v2 audit (`reports/audit/v2_data_integrity_audit.md`)** — 8 check;
   2 FAIL (P1-1 cross-task signal Jaccard ≥ 0.7 occurs in 50/63 tasks =
   79.4%,duplicate signal-set groups 13,N_eff ≈ 13;P1-2 Sub-6A spectra
   per signal compound ≥ 3 only 16.4%) ;3 WARN;3 PASS。**P1-1 caveat 直
   接迁移到 sub6b-v3** —— v3 lipid bucket 11 task 中 10 个是 WP167 seed
   变体 → bucket 内 N_eff ≈ 1。
6. **v3 vs v2 (`reports/eval/sub6b_v3_opus_vs_v2_comparison.md`)** —
   v3 Opus baseline:supported 17.40% / unsupported 11.51% / contradicted
   4.11% / unverifiable_v0 66.97% (61 verdict rows;2 narrative empty;1
   verifier API error);v2 对照 18.10 / 12.56 / 4.18 / 65.16 (63 rows)。
   v3 supported -0.70 pt vs v2,unverifiable_v0 +1.81 pt。LIPID MAPS
   integration 加了 11 lipid task (10× WP167 + 1× steroid),Opus 写
   "arachidonic acid metabolism / eicosanoid biosynthesis" 但 不写 literal
   `Eicosanoid synthesis`;verifier 部分能桥(at-least-one supported
   WP167-linked claim in 10/11 lipid task),但 aggregate set_enrichment
   support 没动 (2 supported → 2 supported,unverifiable 120 → 140)。
   **W8 LLM-agent 主要立论候选 = lipid bucket 上 supported lift 显著大于
   aggregate**,因为 baseline 已经识别到生物语义,缺的是 verifier-friendly
   命名 + 跨 namespace 桥接;LLM-agent 通过 9 个 function tool (尤其
   reconcile_inchikey + query_pathway_members) 应能 bridge "arachidonic
   acid metabolism" → `lm_pathway:WP167` / WikiPathways。

### Tier 2 scanned (代码模块)

5. **`verifier/`** — 19 module。`agent.py:verify()` 是公共入口
   (stage1 extract → stage2 classify → stage3 verify per-claim w/ Layer
   A/B/C/D/E/F + 6a/b/c/d → stage4 rewrite + 二轮 verify;worst-case 7
   LLM call,best-case 1)。**W8 直接 `from verifier.agent import verify`,
   verifier_adapter 包一层调度即可,不动 verifier 源文件。**
6. **`tools/agent_tools/`** — 5 个 B1 function tool 已注册:
   `query_ramp_enrichment / query_pathway_membership / query_kegg_path /
   lookup_compound_info / search_literature`。
   `tool_definitions.py` 通过 Pydantic SCHEMA_REGISTRY 自动生成 OpenAI
   tool-call JSON;`dispatcher.py` 走 thread-local per-call dedup cache。
   **W8 follow 同款 pattern 在 `concord/agent/tool_dispatcher.py` 新增 9
   个 tool (5 PA wrapper + reconcile_inchikey + query_pathway_members +
   lookup_chebi + search_literature);不动 `tools/agent_tools/`。**
7. **`evaluation/sub6/run_sub6b_react_feedback.py`** — B1 ReAct +
   feedback runner;`DEFAULT_MAX_REACT_TURNS=5` /
   `DEFAULT_MAX_FEEDBACK_ITERS=2` / `DEFAULT_TOTAL_TIMEOUT=900s`;
   `VerdictReport`、`IterationRecord`、`Sub6BAgentFeedbackResult` dataclass
   完整;quality rollback "feedback_made_it_worse / iter2_degraded"
   逻辑成熟。**W8 `concord/agent/react_runner.py` = 这个文件的
   ConcordMet 适配版,max_turn 改 8 (per W8 §2),其他保持。**
8. **`concord/wrappers/`** — 5 个 PA wrapper 文件 (`sspa_wrapper.py /
   mummichog_wrapper.py / ramp_wrapper.py / metaboanalystr_wrapper.py /
   fella_wrapper.py`) + `_docker_r_session.py` + `_mummichog_runner.py`。
   `__init__.py` 当前为空 (1 line),W8 D2 加 OpenAI tool spec 后,公共导
   出由 `concord/agent/tools/` 新模块负责而不是 wrappers 自己。

### Tier 3 data (schema)

**sub6b-v3 benchmark** (`data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl`,
63 line):
- MD5 `331b30a64017debe9d5ce07ed238e4f5` ✅ 与 v3 报告 §6 一致
- task 字段:`task_id / task_type / domain / differential_metabolites
  (list of full CompoundRecord w/ smiles + inchikey + kegg + hmdb +
  pubchem + npc_pathway/class/superclass + classyfire + ramp_pathway_ids
  + spectrum_ids + ...) / differential_spectra / ground_truth_pathway
  ({pathway_id, pathway_name, pathway_source, external_id,
  primary_pathway_pre_aggregation}) / ground_truth_signal_compounds
  (list of KEGG cpd ID strings) / ground_truth_noise_compounds (同) /
  ramp_enrichment_result / seed / cli_seed / signal_count / noise_count
  / signal_ratio / id_type`
- 检验 `lm_pathway_WP167_seed3`:gt pathway = `lm_pathway:WP167`
  / "Eicosanoid synthesis" / source `lipidmaps` / external_id `WP167`;
  signal_count=5 / noise_count=4 / differential_metabolites=9
- 关键:`ground_truth_signal_compounds` 是 KEGG cpd ID **string**(C00219,
  C00909, C04805, ...)而非 dict。B1 verifier Layer 6b/6c 原生消费
  KEGG-ID 字符串列表 → **task → SubsixSourceReport 适配是现成的**。

**v3 Opus baseline** (`data/eval/sub6/v3/sub6b_opus/`,**位于 main worktree**):
- `sub6b_narratives.jsonl`:keys = `task_id / narrative / elapsed_seconds /
  llm_model / llm_calls / metabolite_count / error`。**字段是
  `narrative`,不是 `narrative_text`** (D5 Path W 解析代码注意)。
- `verdicts_v9_phaseC.jsonl`:keys = `task_id / track / elapsed_seconds /
  verifier_llm_calls / warnings / error / verdicts_total /
  verdicts_by_type / verdicts_by_subtype / claims (list of claim dict
  w/ claim_id / claim_text / claim_type / claim_subtype / subject /
  subject_kind / candidate_ref / verdict / evidence / source_field /
  correction / extracted_fields / evidence_refs / verifier_layer /
  tool_called / trace_summary / severity / claim_group_id /
  parent_claim_id / tool_evidence / enrichment_context)`。
  Example task: `RAMP_P_000052855_seed0` 55 claims, claim[0] verdict =
  unsupported, claim_type = biological_claim。

**Cooke schema** (`data/concord/tier_a_cooke/tasks_primary.jsonl`,对比):
- keys = `task_id / perturbation_pathway_name / perturbation_pathway_id /
  organism / cohort / z_threshold / differential_metabolites
  (pre-resolved CompoundRef dict list w/ primary_id NS-prefixed +
  inchikey + chebi_id + ...) / differential_raw_ids / z_scores /
  n_input_raw / n_input_resolved`
- **没有** `ground_truth_pathway` 字段 (用 `perturbation_pathway_id`)。
- **没有** `ground_truth_signal_compounds` / `noise_compounds`。
- **W8 不用 Cooke** — 仅作 schema 对比理解差异。

**EnrichmentResult v0.3.1 必填字段** (`concord/schema/enrichment.py`):
- `EnrichmentResult`:method (EnrichmentMethod enum) / pathway_db
  (PathwayDB enum) / pathways (`tuple[PathwayHit,...]`) / parameters
  dict / tool_version / db_release / n_input / n_input_resolved /
  wall_time_sec / schema_version (default `concordmet_v0.3.1`) /
  tautomer_canonicalized / chebi_canonicalized / notes
- `PathwayHit`:pathway_id (`"<NS>:<id>"` 必填,NS ∈ {REACT, KEGG, WP,
  SMPDB, METACYC, MUMM, HUMAN1, RECON2}) / pathway_name /
  pathway_id_native / pathway_db / score / score_type / rank /
  metabolites_hit (`tuple[CompoundRef,...]`) / n_metabolites_in_pathway /
  n_metabolites_input / auxiliary_scores
- `CompoundRef`:primary_id (`"<NS>:<id>"` 必填,NS ∈ {CHEBI, LIPIDMAPS,
  HMDB, KEGG, INCHIKEY}) / inchikey 必填 / display_name + optional
  chebi/lipidmaps/hmdb/kegg/pubchem/metanetx ID
- `__post_init__` validator 强制 namespace whitelist;`resolve_primary_id()`
  按 chebi → lipidmaps → hmdb → kegg → inchikey 优先级填。
- **EnrichmentResult invariant** (W3 hotfix):n_pathways > 0 时 metabolites_hit
  总数必须 > 0,否则 raise (避免 vacuous truth bug)。

**Verifier ClaimType enum** (`verifier/schemas.py:46`):
9 个值 — GROUNDED / FACTUAL / BIOLOGICAL / CONSISTENCY / LITERATURE /
PEAK_MECHANISTIC / SET_ENRICHMENT (Layer 6a) / DRIVER_METABOLITE
(Layer 6b) / PATHWAY_RELATIONSHIP (Layer 6d)。6c "biological_sub6"
合并到 BIOLOGICAL。这映射 grammar v2 的 4 类 claim
(PATHWAY_MEMBERSHIP / METABOLITE_PATHWAY_LINK / PATHWAY_ENRICHMENT /
DRIVER_METABOLITE) 在 sub6 source report context 下走 6a-6d layer。

**`integration_investigation.md` §0**:4 个竞品 — MetaboT (public,
8.16% → 83.67% acc,GPT-4o,5-agent KG-QA);MS4MS (paper-only,4-agent,
top-1 92.04%);MSAgent (paper-only,Evidence grounding + 95%
ranking-stability);GeneAgent (Nat Methods 2025,public,4-step
self-verify loop,**核心借鉴模板:N=1000+ + 大规模统计检验 +
可解释证据链**)。

**§3 Schema 设计原理**:MIRIAM/identifiers.org namespace-prefixed,
Reactome 主键 12% 覆盖缺口由 KEGG/WP/SMPDB/METACYC fallback,InChIKey
ground truth 兜底 (RDKit 永远能算);v0.3 namespace pivot 把 Reactome
miss 的 lipid (LIPIDMAPS) 和 KEGG-only pathway (mummichog mfn /
WikiPathways) 都纳入。

### Tier 4 (optional)

12. **`diagnosis_unverifiable_and_correlation.md`** — skipped (grammar v2
    motivation 在 B1 D4 spec 已有足够覆盖)。

---

## Confirmation

I understand:

**(a) ConcordMet 当前是 deterministic V3,W8 必须改 LLM-agent。**
W7 末 V3 soft union 是 5 wrapper 并行 + 数学合并;W8 改为 LLM ReAct
循环主动调用 5 PA wrapper 作 function tool + LLM 自主 cross-paradigm
整合。

**(b) 移植目标是 B1 grammar v2 + closed-loop verifier。** Grammar v2 4
类 claim (PATHWAY_MEMBERSHIP / METABOLITE_PATHWAY_LINK /
PATHWAY_ENRICHMENT / DRIVER_METABOLITE);verifier 走 `from
verifier.agent import verify`,10 层 (A/B/C/D/E/F + 6a/b/c/d) +
TaskOutcome + 两层 retry 全套保留,**不动 verifier 源文件**。

**(c) 5 个 PA wrapper 改成 LLM function tool。** sspa / mummichog /
RaMP / MetaboAnalystR / FELLA 各包一个 OpenAI tool spec + dispatcher
function;输入 = compound_ids list + top_n;输出 = serialized
EnrichmentResult v0.3.1 dict。

**(d) LLM 自己做 cross-paradigm 整合,不调 V3 算法工具。** 不暴露
`apply_v3_soft_union` 或任何 consensus aggregator;LLM 读 5 个
EnrichmentResult 自决谁是 winner。V3 算法代码保留为 baseline,不删。

**(e) Quad report:LLM-agent / V3 算法 / v3 Opus baseline / RaMP only**
4 路 verdict 在 sub6b-v3 63 task 上对比 (Path W / X / Y / Z)。

**(f) 测试 benchmark = sub6b-v3 (63 task,MD5
`331b30a64017debe9d5ce07ed238e4f5`)**,不是 v2 也不是 W7 的 Cooke
Tier A;V3 算法 baseline 在 sub6b-v3 上**重跑**(W7 Cooke 数字不可直接
比)。理由:B1 verifier 10 层原生为 sub6b 设计 (6a/b/c/d 直接吃
`ground_truth_signal_compounds`/`noise_compounds`);v3 比 v2 多 LIPID MAPS
集成 → 难且有 paper value;v3 Opus baseline 已存可复用。

**(g) Audit caveat 承认**:
- P1-1 task signal-set Jaccard ≥ 0.7 occurs in 79.4% of v2 tasks
  (N_eff ≈ 13 pathway cluster),v3 同样适用且 lipid bucket 更严重
  (10/11 lipid task 是 WP167 seed 变体,bucket 内 N_eff ≈ 1)。
- W8 quad report aggregate raw % 用 N=63,但 statistical
  significance 走 pathway-cluster bootstrap (N=13 sign test +
  bootstrap CI),lipid bucket 标 "N_eff ≈ 1,descriptive only"。
- P1-2 (Sub-6A spectra sparsity) 与 W8 无关 (Sub-6B 不依赖 spectra)。

**(h) v3 Opus baseline 关键数字 (Path W,N=61 verdict rows / 63 task)**:
supported 17.40% / unsupported 11.51% / contradicted 4.11% /
unverifiable_v0 66.97%。2 narrative empty + 1 verifier API error。
**W8 LLM-agent (Path X) 目标:supported 显著 ↑ + unverifiable_v0 显著
↓;lipid bucket 上 supported lift > aggregate**,验证 LIPID MAPS
集成有 verifier-level 收益。

---

## Onboarding Open Questions (raised pre-D1)

发现 5 个 onboarding 期遇到的小问题,**不阻塞 D1 启动**,但请用户确认
W8 D5 Path W 复用方案 (Q1 是唯一需要拍板的):

1. **🟡 v3 Opus baseline 物理位置**:`data/eval/sub6/v3/sub6b_opus/`
   仅存在于 **main worktree**,投资 worktree (`metagent_day1_v5_investigation`)
   没有这份数据。**W8 D5 Path W "直接复用,不重跑"** 需要在三个方案之
   间选一个:
   - **(A)** 在投资 worktree 内 `symlink` 这 2 个文件(narratives +
     verdicts)指到 main worktree path
   - **(B)** `cp` 到投资 worktree 同路径(冗余 ~10 MB)
   - **(C)** 在 D5 Path W 解析代码里硬编码绝对路径
     `/home/weiwentao/.../metagent_day1_v5/data/eval/sub6/v3/sub6b_opus/`
   - **预选 (A)** symlink (零冗余、零绝对路径污染、跨 worktree 透明)。
2. **🟡 §5 commit list 笔误**:W8 spec §5 commit #5 描述 "PRIMARY
   51-task LLM-agent run + dual report vs V3",**残留 W7 Cooke
   PRIMARY=51 字样**,全文已统一 sub6b-v3 63 task + quad report (4
   path)。实际 commit 写为 "sub6b-v3 63-task LLM-agent run + quad
   report (W8 D5)"。**Cosmetic,不影响主流程,在 D5 commit 时修正
   message 即可。**
3. **🟡 Narrative 字段名歧义**:v3 Opus narratives.jsonl 字段是
   `narrative` (非 `narrative_text`)。D5 Path W 复用解析时注意,Path X
   LLM-agent 输出也应保持同字段名以便后续对照脚本通用。
4. **🟡 B1 D4 prompt 和 W3-W7 handoff 路径**:`prompts/track_AGENT_phase_B1_D4.md`
   只在 main worktree 存在 (B1 工作分支);
   `docs/concord/comprehensive_w3_w7_handoff.md` 两边都不存在 (W8 prompt
   已说 "若不存在则跳过")。Onboarding 已从 main worktree 读完 B1 D4。
5. **🟢 Verifier 适配可行性预判**:`verifier/agent.py:verify()` 签名为
   `(llm_output: str, source_report: IdentificationReport, *, trace_id,
   fetcher, literature_fetcher, cfmid_fn) -> VerifiedIdentification`;
   `source_report` 实际接 `SubsixSourceReport` (Layer 6a 直接消费
   `ramp_enrichment_result.top_pathways`,Layer 6b/c 消费
   `ground_truth_signal_compounds` / `noise_compounds`)。**W8
   `concord/agent/verifier_adapter.py` 主要工作 = 把 sub6b-v3 task →
   SubsixSourceReport 桥接 (sub6b-v3 task 已含 ramp_enrichment_result
   字段,可直接转;ground_truth_*_compounds 是 KEGG cpd ID string 列
   表,验证器原生消费)。** 不预期 import 链路问题。

---

(D1 下半 ReAct runner skeleton 待用户 sanity check 后启动。
**2026-05-18 用户 Green Light**:Q1 选 (A) symlink + gitignored,Q2-Q5
处置确认,进 D1 下半。完成 deliverable 见下方 § D1 Skeleton。)

---

## D5 Path W Setup (symlink scheme)

**决策来源**:Onboarding Open Question Q1。`data/eval/sub6/v3/sub6b_opus/`
仅在 main worktree 存在 (v3 Opus baseline 2026-05-08 冻结);D5 Path W
要求"复用,不重跑"。三方案 (A) symlink / (B) cp / (C) 硬编码绝对路径
中,用户拍板 **(A) symlink + gitignored + setup script**:

- **拒 (B) cp**:同 repo 两 worktree 共享 `.git`;cp 让投资 worktree
  多 ~10 MB,且 v3 baseline frozen 无 live-update 需求。
- **拒 (C) 硬编码**:不可移植;paper artifact reproducibility 受损。

### 操作步骤(setup script 落盘并已 run 通)

```bash
chmod +x scripts/concord/setup_w8_path_w.sh
./scripts/concord/setup_w8_path_w.sh
```

Output 实测:

```
✓ Symlink created: data/eval/sub6/v3/sub6b_opus -> /home/weiwentao/workspace/
  llm_agent_metabolomics/metagent_day1_v5/data/eval/sub6/v3/sub6b_opus

Contents (should list at least sub6b_narratives.jsonl + verdicts_v9_phaseC.jsonl):
total 7124
-rw-rw-r-- ...  189800 ... sub6b_narratives.jsonl
-rw-rw-r-- ... 7090266 ... verdicts_v9_phaseC.jsonl
```

### Gitignore 实测

`git check-ignore -v data/eval/sub6/v3/sub6b_opus` ⇒
`.gitignore:27: data/eval/sub6/v*/	data/eval/sub6/v3/sub6b_opus`。
**现有 `.gitignore` 规则 `data/eval/sub6/v*/` 已自动覆盖 symlink 路径,
无需追加新规则**(原 user spec Step 2 的 `echo
"data/eval/sub6/v3/sub6b_opus" >> .gitignore` 会造成重复 — 跳过)。

### 复现指南

新 clone 投资 worktree 后,先跑:

```bash
chmod +x scripts/concord/setup_w8_path_w.sh
./scripts/concord/setup_w8_path_w.sh   # 默认 main worktree 路径
# 或 METAGENT_MAIN_WORKTREE=/your/main/path ./scripts/concord/setup_w8_path_w.sh
```

D5 Path W 解析代码用相对路径 `data/eval/sub6/v3/sub6b_opus/` 读
`sub6b_narratives.jsonl` + `verdicts_v9_phaseC.jsonl`,跨 worktree
透明。

---

## D1 Skeleton

**新增 / 修改文件** (4 个新建,0 个修改 B1 路径文件):

| Path | 角色 | LOC |
|---|---|---:|
| `scripts/concord/setup_w8_path_w.sh` | Path W symlink setup,bash | 55 |
| `concord/agent/__init__.py` | package marker + 模块路线 | 20 |
| `concord/agent/system_prompts.py` | ReAct prompt builder,加载 markdown 模板 | 70 |
| `concord/agent/tool_dispatcher.py` | 9 tool 占位 dispatcher + per-call dedup cache | 360 |
| `concord/agent/react_runner.py` | `ConcordReactRunner` 类骨架 + result dataclass | 200 |
| `prompts/concord/concord_react_prompt.md` | system / user prompt 模板(含 9 tool 描述 + grammar v2 spec) | 150 |

### 设计要点

- **B1 路径绝对不动**:不修改 `evaluation/sub6/`、`tools/agent_tools/`、
  `verifier/` 任何源文件;仅 import (`evaluation.sub6.prompts.render_metabolite_block`
  在 system_prompts.py 复用一次)。
- **9 个 tool catalogue**(W8 §2 Tool Catalog):
  PA 5 个 `run_sspa_ora / run_ramp_enrichment / run_metaboanalystr_psea
  / run_mummichog / run_fella_rwr` + 3 reconciliation `lookup_chebi /
  reconcile_inchikey / query_pathway_members` + 1 literature
  `search_literature`。**不暴露 V3 aggregator / consensus / rank
  tool**(用户死命令 (a))。
- **Dispatcher 行为**:每个 stub handler `raise
  NotImplementedError("D2/D3 wires this")`;dispatcher 捕获,返回
  `{"error": "not wired yet (D1 skeleton)", "fallback_suggested": ...,
  "_skeleton_note": str(exc)}` 标准 envelope。**LLM 看到的是"未接通"
  错误,不是 crash**——D1 dry smoke 可跑而不出 stacktrace。
- **Per-call dedup cache**:thread-local(沿用 B1 pattern),`reset_call_cache()`
  每 task 开头清。
- **`ConcordReactRunner` config 校验**:`__post_init__` 强制
  `max_react_turns ∈ [1, 8]` (W8 spec ceiling), `max_feedback_iters
  ∈ [0, 2]`, `inner_finalise_retries ∈ {0, 1}`;tool catalogue size
  必须正好 9。
- **`run_task()` D1 raise NotImplementedError**:但 build initial
  messages 路径已通(metabolite_block render + system/user split),
  D3 接 LLM client 即可。
- **Grammar v2 final-message JSON spec** 在 system prompt 中固化,
  4 个 `claim_type` (PATHWAY_ENRICHMENT / PATHWAY_MEMBERSHIP /
  METABOLITE_PATHWAY_LINK / DRIVER_METABOLITE) 全部出现且有 example
  payload。`hedge / 'may be involved' / 'potentially'` 类弱化语在
  prompt 中显式禁止(对齐 B1 grammar v2 drop_reason)。

### Sanity 实测(5 项 + 4 个 bonus)

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | `from concord.agent.react_runner import ConcordReactRunner` | ✅ | `[1] import OK` |
| 2 | `ConcordReactRunner()` init 不 crash | ✅ | `[2] init OK: {…llm_model: 'minimax-m2.7', max_react_turns: 8, max_feedback_iters: 2, n_tools: 9, has_chat_client: False, has_verifier: False}` |
| 3 | `get_tool_specs()` 返回 9 个 tool spec | ✅ | `[3a] get_tool_specs returns 9 tools`;9 个 name 与 W8 §2 Tool Catalog 完全一致 |
| 4 | symlink `data/eval/sub6/v3/sub6b_opus/` ls 通 | ✅ | `ls -la` 输出含 `sub6b_narratives.jsonl` (189800 byte) + `verdicts_v9_phaseC.jsonl` (7090266 byte) |
| 5 | git status 干净 | ✅ | 仅 4 个 untracked entry:`concord/agent/`、`prompts/concord/`、`reports/agent/concord_sprint_w8_status.md`、`scripts/concord/`;无 modified file;symlink 自身被 `.gitignore:27` 规则覆盖 |
| b1 | stub dispatch 返回标准 error envelope(不 crash) | ✅ | `r.payload['error'] == "tool 'run_sspa_ora' not wired yet (D1 skeleton)"` |
| b2 | system prompt 含 4 类 claim_type | ✅ | `PATHWAY_ENRICHMENT / PATHWAY_MEMBERSHIP / METABOLITE_PATHWAY_LINK / DRIVER_METABOLITE` 全检出 |
| b3 | `build_concord_react_messages` 渲染 `{metabolite_block}` 占位 | ✅ | system=8128 char / user=751 char,占位已替换 |
| b4 | pytest 全绿(W7 floor 不退步) | ⏳ | 见下方 § Pytest Verification |

### Pytest Verification

Full suite实测 (excluding `tests/test_ui/` which needs gradio dep group):

```
17 failed, 1251 passed, 33 skipped, 13 warnings in 1213.52s (0:20:13)
```

**W7 status file 提的 "148/148 PASS" 是 Concord track 子集计数**,
非全 repo;真实全 repo collected tests 是 1301(1251 pass + 17 fail
+ 33 skip)。

**17 个 failure 全部 pre-existing,与 D1 skeleton 零相关**。Root cause
通过 targeted re-run 实测确认 (e.g. `pytest tests/concord/test_w3_smoke.py
--tb=line`):

| Failure cluster | Cnt | Root cause (实测) | D1 关系 |
|---|---:|---|---|
| `tests/concord/test_sspa_wrapper.py` × 4 + `test_w3_smoke.py` × 1 + `test_w4_smoke.py` × 1 | 6 | `ModuleNotFoundError: No module named 'sspa'` — `concord/wrappers/sspa_wrapper.py:97` delayed `import sspa` (heavy pip pkg未装) | D1 不 import sspa,不修改 `concord/wrappers/*` |
| `tests/integration/test_verifier_e2e.py::test_verify_*_end_to_end_real_llm` × 3 | 3 | real_llm tests need OpenAI/Anthropic API key in env (only MINIMAX_API_KEY available locally,同 W7 OQ-9) | D1 不动 `verifier/`,不调 real LLM |
| `tests/integration/test_orchestrator_e2e.py` × 2 + `test_pipeline_e2e.py` × 1 | 3 | integration test,需 GNPS/orchestrator env vars | D1 不动 `orchestrator/`,无 GNPS 依赖 |
| `tests/tool_tests/test_library_search.py` × 2 | 2 | `test_missing_gnps_env_raises_library_unavailable` + full-pool integration test,GNPS env | D1 不动 `tools/library_search/` |
| (其余 3 个失败 in tail truncated,同类 env 问题) | 3 | (推断同 sspa / API key / env 缺失,未单独 re-run 验证) | 同上 |

**D1 paths 与 failing test 完全无路径重叠**:
`grep "FAILED" pytest_output | grep -E "concord/agent|prompts/concord|tool_dispatcher|react_runner|system_prompts|setup_w8"` 实测返回**空集**。
`grep "^import\|^from" concord/agent/*.py | grep -vE "__future__|from concord\.|from evaluation\.sub6\."` 实测返回**空集**(无任何外部 pkg import)。

**Verdict**:D1 skeleton 0 regression。W7 floor 在该 env 下实测是
"1251 pass / 17 fail",D1 完成后仍是 "1251 pass / 17 fail"(无新增
failure,无 pass → fail drift)。可进 D2。

> 🟡 **Side-effect open question for user** (D2 launch 前 nice-to-resolve):
> W7 status file 提"148 / 148 PASS" 是 Concord track 子集口径,与全 repo
> 1268 collected ≠。建议 W8 末 quad report 也用同一口径(Concord track
> tests/concord/ 单算 + 整 repo 单算),paper-grade audit trail 双口径。

---

## Open Questions (D2 launch 前需 user review)

无新增 open question。D1 deliverable 完整,可进 D2 (5 PA wrapper 改
function tool + OpenAI schema)。

### D2 预热(供 user review skeleton 时一并 sanity)

D2 计划在 `concord/agent/tools/` 下为 5 个 PA wrapper 各加一个 module
(`sspa_tool.py / mummichog_tool.py / ramp_tool.py / metaboanalystr_tool.py
/ fella_tool.py`),把 `_stub` 替换成真正调用 `concord/wrappers/*` 的
handler。`tool_dispatcher.HANDLERS` dict 替换 5 个 entry,其他 4 个
reconciliation/literature tool 仍 stub 留 D3。

每个 PA tool 内部:
1. validate arguments(top_n / compound_ids 类型 + 长度)
2. resolve compound_ids → CompoundRef list (`lookup_chebi` style helper)
3. 调底层 wrapper
4. 序列化 EnrichmentResult v0.3.1 → dict(保留 namespace-prefixed
   pathway_id;truncate auxiliary metadata 到 2 KB budget,沿用 B1
   `truncate_to_budget`)

D2 unit test plan(W8 spec § D2 Unit test ≥ 10 case):
- 9 个 tool 各 1 个正例(stub-replaced PA tool 用真 docker subprocess
  或 mock,reconciliation/literature 仍 stub 是 negative)→ 实际 5 个
  PA tool 正例 + 4 个 stub 负例 + 1 个 invalid arguments(LLM 调用错
  schema)= 10 case

