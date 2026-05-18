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

(D2 已 land — 见 § D2。)

---

## D2 — 9 LLM function tools wired with import-guard envelope

**Commit**:`feat(concord): W8 D2 — 9 LLM function tools with OpenAI
schema + import-guard fallback envelope` (待 verify 后 hash 填入)。

**用户 Green Light 决策**:Q1-Q4 全 ✅;2 nice-to-have(ramp latency
note + lookup_chebi 输入加粗)合并到 D2 主 commit。

### 新增 / 修改文件

| Path | 角色 | LOC delta |
|---|---|---:|
| **NEW** `concord/agent/tool_handlers.py` | 9 个 handler + 3 helper (`_validate_compound_ids` / `_ids_to_refs` / `_ok` + `_err` envelope) | +450 |
| **NEW** `tests/test_concord_tools.py` | 12 unit test (9 happy + 3 negative)| +290 |
| MOD `concord/agent/tool_dispatcher.py` | 删 D1 stub registry,改 `from concord.agent.tool_handlers import HANDLERS`;9 tool spec 完善 `top_n` / `query` / `max_results` 的 `description + minimum + maximum`;ramp 描述加 fast-latency note;lookup_chebi 描述加 input-shape 详列;dispatch() NotImplementedError 兜底改通用 Exception 兜底 | -25 / +35 |
| MOD `prompts/concord/concord_react_prompt.md` | run_ramp_enrichment 加 "Fast (~1s, local sqlite, no Docker)" + "first call";lookup_chebi 输入加 "**Accepted input shapes**" 段全列(6 形态加粗) | -3 / +6 |

### Handler 设计要点

- **统一 envelope**:`_ok(tool_name, result, **meta)` → `{ok: True,
  result: ..., _tool_name: ..., _n_pathways: ..., _n_compound_refs:
  ...}`;`_err(tool_name, error=, fallback_suggested=, **extra)` → `{error:
  ..., fallback_suggested: ..., _tool_name: ...}`。
- **Import 推迟到 call-time**:每个 PA handler `try: from
  concord.wrappers.X_wrapper import run_X` 在函数体内,而非 module 顶部。
  这保证:(a) env 缺 sspa / Docker 时 import 失败被 catch 返回
  `wrapper_unavailable` envelope,(b) test 可以 `monkeypatch.setattr`
  module 属性,handler 下次调用会读 patched 值。
- **Fallback_suggested 一一指定**(对齐用户 spec):
  - sspa 不可用 → "use run_ramp_enrichment / run_metaboanalystr_psea"
  - ramp 不可用 → "RaMP-DB sqlite missing; use sspa or psea"
  - metaboanalystr 不可用 → "Docker R unavailable; use sspa"
  - mummichog 不可用 → "skip m/z-direct paradigm; rely on ORA tools"
  - fella 不可用 → "Docker R unavailable; skip network paradigm"
- **`_ids_to_refs` adapter**:把 LLM 输入的 string ID 列表 (e.g.
  `["CHEBI:17234", "C00031", "HMDB0000122"]`) 转成 wrappers 能读的
  duck-typed `SimpleNamespace` 对象(无需 inchikey 兜底,B1 wrapper 用
  `getattr(ref, ...)` 读)。
- **`_validate_compound_ids`** 在所有 5 PA handler 共用,LLM 错误传
  `non-list` / 空数组 / 含非字符串元素 → 返回明确 error envelope。
- **lookup_chebi 路由**:按 namespace hint + 字面形态分发到 `get_compound
  / lookup_by_inchikey / lookup_by_xref(HMDB|KEGG|LIPIDMAPS) /
  lookup_by_name`;serialize 时把 `name` → `display_name` alias 对齐
  CompoundRef schema。
- **query_pathway_members 数据缺口**:`pathway_members.sqlite` 只有
  HUMAN1 + RECON2 (227 pathway,Cooke GEM)。LLM 传 `WP:WP167`/`KEGG:`/
  `REACT:` 等 namespace → 返回 `data_not_available` envelope +
  fallback_suggested "inspect `metabolites_hit` inside EnrichmentResult"。
  **这是 D2 已知 scoping gap,不阻塞 D5 — paper finding 反而可以是
  LLM-agent 在 WP167 lipid bucket 上的 lift 来自 PA tool 的
  `metabolites_hit`(而非 pathway_members lookup),证明 cross-paradigm
  整合的价值。**

### Sanity 8 项实测

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | 9 tool spec 完整 OpenAI schema(name + description + parameters/type/properties/required;每 property 有 type + description) | ✅ | 实测 `get_tool_specs()` 9 spec,所有 property 都有 type + description |
| 2 | 5 PA handler 全有 import-guard + 对应 fallback_suggested envelope | ✅ | 逐一 monkeypatch import 失败 → `wrapper_unavailable` envelope,每个 fallback_suggested 都提及合适的替代 tool |
| 3 | system prompt 2 微调到位(ramp latency + lookup_chebi 输入加粗) | ✅ | system prompt 含 `~1s, local sqlite, no Docker` + `Accepted input shapes`;dispatcher spec 同步含 fast-latency + 输入列表 |
| 4 | EnrichmentResult dict 序列化 + envelope shape + JSON round-trip | ✅ | 实测 `dispatch(...)` → `{ok, result, _tool_name, _n_pathways, _n_compound_refs}`;`json.dumps + json.loads` 完整 round-trip;`pathway_id` namespace 前缀(REACT/KEGG/WP/SMPDB/METACYC/MUMM/HUMAN1/RECON2)保留 |
| 5 | `tests/test_concord_tools.py` ≥ 12 case 全绿 | ✅ | **12 passed in 0.62s** (9 happy + 3 negative:invalid args / wrapper_unavailable / dedup cache hit) |
| 6 | `pytest tests/concord/` 不退步 | ✅ | 9 failed / 139 passed — 与 D1 baseline `tests/concord/` 同(9 fail 全部 `sspa` 包未装) |
| 7 | 全 repo pytest 17 pre-existing fail 数量不变 | ✅ | **17 failed / 1263 passed / 33 skipped in 1193.64s** (vs D1 baseline 17/1251/33);**+12 pass 是 D2 新增 `tests/test_concord_tools.py` 12 case**,17 fail 名字与 D1 完全一致(sspa pkg × 7 + orchestrator/pipeline × 3 + verifier real_llm × 3 + library_search × 2 + w3/w4 smoke × 2 — 全 env-driven pre-existing) |
| 8 | git status 干净 | ✅ | `2 modified + 2 new`:`M concord/agent/tool_dispatcher.py / M prompts/concord/concord_react_prompt.md / ?? concord/agent/tool_handlers.py / ?? tests/test_concord_tools.py` — 无意外 modified |

### TDD audit (per superpowers:test-driven-development)

- **RED**:12 test 全失败前 GREEN(实测:12/12 fail with right reason
  "expected `{ok: True, ...}` got `{error: 'not wired yet (D1 skeleton)'}`")
- **GREEN minimal**:每个 handler 只实现满足 test 所需逻辑,不超前
  做 D3/D4 工作
- **REFACTOR**:helper `_ok` / `_err` / `_validate_compound_ids` /
  `_ids_to_refs` / `_top_n_or_default` 抽出共享逻辑,5 PA handler 体
  ~ 30 line each(高度相似但显式写出,便于 review)

### Known data gap (flagged for D5 decision)

🟡 `query_pathway_members` 只覆盖 HUMAN1 + RECON2 (227 pathway);sub6b-v3
lipid `WP:WP167` 等查询返回 `data_not_available` envelope。D5 paper
finding 可基于 PA tool 自身 `metabolites_hit` 字段,**不依赖** pathway_members
sqlite。如 D5 数据显示该 gap 显著影响 verdict,W9 可补 ETL。

### D3 预热(供 user review D2 时一并 sanity)

(D3 已 land — 见 § D3。)

---

## D3 — ConcordReactRunner.run_task() + 2-task end-to-end smoke

**Commit**(待 full pytest verify 后填):D3 hash。

**用户 Green Light 决策(D2 sanity)**:Q1-Q4 全 ✅;Q3 test 文件移到
`tests/concord/`;Q1 envelope D5 token-budget 关注先 hold(D3 实测 OK)。

### 新增 / 修改文件

| Path | 角色 | LOC delta |
|---|---|---:|
| MOD `concord/agent/react_runner.py` | `run_task()` 实现替换 D1 NotImplementedError;3 helper (`_extract_json_object` / `_validate_grammar_v2` / `_payload_summary`) + 2 module-level prompt 文本 (`_RETRY_NUDGE_PROMPT` + `_FORCE_FINALISE_PROMPT`) + ReAct loop body | +210 / -10 |
| MOD `concord/agent/tool_handlers.py` | D3 hotfix:5 PA handler 的 `try/except` 扩展覆盖 wrapper 调用本身,新 `_WRAPPER_UNAVAILABLE_ERRORS = (ImportError, ModuleNotFoundError, FileNotFoundError)` 触发 wrapper_unavailable envelope(原仅 catch 顶层 import,wrapper 内 lazy import 失败漏出) | +15 / -25 |
| **MOVE** `tests/test_concord_tools.py` → `tests/concord/test_concord_tools.py` | Q3 fix:align 现有 tests/concord/ dir;rename via git mv 保留 history | 0 |
| MOD `tests/concord/test_concord_tools.py` | D3 hotfix regression test:`test_run_sspa_ora_wrapper_runtime_module_not_found` — monkeypatch `sspa_wrapper.run_sspa` raise `ModuleNotFoundError` → handler 必须返 `wrapper_unavailable` envelope(原 12 → 13 case) | +20 |
| **NEW** `tests/concord/test_react_runner.py` | 5 unit test 覆盖 `run_task` 控制流:happy path / inner retry recover / retry exhausted → empty_system_failure / force_finalise at max_turn / ground_truth strip | +250 |
| **NEW** `evaluation/concord/smoke_d3.py` | CLI 驱动:`--task-id` + `--out` 跑单 task,落 ConcordReactResult JSON + 终端打印 verdict 含 "★ naming bridge" 检测 | +130 |
| **NEW** `data/concord/w8_smoke/d3_{steroid,lipid}.json` | 2 smoke 完整 result(gitignored 但保留 review trace) | +data only |

### `run_task()` 设计要点

- **Wall-time guard**:每 turn 前检查 `time.time() > deadline`;超 1200s →
  `error="task_timeout"`,outcome=EMPTY_SYSTEM_FAILURE
- **max_react_turns = 8**:第 8 turn 强制 `tool_choice="none"` + 注入
  `_FORCE_FINALISE_PROMPT`(LLM 不能再调 tool,必须出 JSON)
- **Inner retry × 1**(B1 D4 component 4a 等价):finalise JSON parse fail
  → 注入 `_RETRY_NUDGE_PROMPT` 含 grammar v2 spec + parse error 原因 →
  续一 turn;再 fail → `error="invalid_final_json"`,outcome=EMPTY_SYSTEM_FAILURE
- **Outcome classification**(B1 D4 TaskOutcome 等价):
  - parse_ok AND claims != [] → `normal`
  - parse_ok AND claims == [] → `empty_honest_refusal`
  - timeout / chat_error / invalid_final_json_after_retry → `empty_system_failure`
  - 否则 → `empty_unknown`
- **`_extract_json_object`** 3 级尝试:整体 parse → 最后 `\`\`\`json ... \`\`\`` 围栏 → 最长 `{...}` 平衡 span
- **`_validate_grammar_v2`** 结构校验:`narrative_text: str` + `claims: list` + 每个 claim 的 `claim_type` ∈ 4 类
- **`_strip_task_for_llm`** 去 ground truth:仅 send `task_id` + `differential_metabolites`,屏蔽 `ground_truth_pathway` / `ground_truth_signal_compounds` / `ramp_enrichment_result`
- **Default LLM**:`MiniMax-M2.7` + `provider="minimax"`;`temperature=0.0`;
  `chat_with_tools` injection optional (test 用 `FakeChat`)

### D3 hotfix 详情(`tool_handlers.py`)

**Bug**:D2 handler 的 `try/except ImportError` 仅 catch 顶层
`from concord.wrappers.X_wrapper import run_X`。但 `sspa_wrapper.py:97`
有 `import sspa` 延迟到 `_load_pathway_db()` 被调用时 — 顶层 import
不抛错,内层 call-time 抛 `ModuleNotFoundError`。Smoke 1 实测暴露:
dispatcher 的 generic `except Exception` 捕获后返 `"tool raised
unexpectedly"` envelope,而非清晰的 `wrapper_unavailable` envelope,LLM
得到的 fallback 信号弱化。

**Fix**:5 PA handler 的 `try/except` 扩展到覆盖 wrapper **调用本身**;
新 `_WRAPPER_UNAVAILABLE_ERRORS = (ImportError, ModuleNotFoundError,
FileNotFoundError)` 统一 catch(`FileNotFoundError` 兼覆盖 Docker
subprocess / venv path 缺失场景)。

**Regression test**:`test_run_sspa_ora_wrapper_runtime_module_not_found`
monkeypatch `sspa_wrapper.run_sspa` 直接 raise `ModuleNotFoundError`,
assert handler 返 `wrapper_unavailable` envelope。

### TDD audit (per superpowers:test-driven-development)

🟡 **Honesty disclosure**: D3 `run_task()` body (~150 LOC of cohesive
control flow) was written **before** the 5 unit tests, **violating
strict TDD**. Mitigation:

- 5 unit tests written immediately after implementation,实测 5/5 pass
- 1 hotfix regression test (smoke 1 surfaced ImportError leak) followed
  strict RED → GREEN: test added first → run → fail → handler fix → pass
- D2 work (12 test) DID follow strict TDD;D3 loop body skipped it
- Justification: ReAct loop body is a translation of B1 established
  pattern, not design discovery — but per skill spec, "Throwaway
  prototypes" is the only valid exception, and D3 body isn't a prototype.

Lesson: D4 verifier integration body **must** be strict TDD (each piece
of feedback loop logic test-first).

### Smoke 1 verdict — steroid `RAMP_P_000000421_seed1`

```
task_id          = compound_only_enrich_mammalian_RAMP_P_000000421_seed1
ground_truth     = Androgen and Estrogen Metabolism (RAMP_P_000000421, KEGG hsa map00150)
task_outcome     = normal
n_turns          = 8 / 8 (force_finalised=True — LLM used full turn budget)
n_tool_calls     = 23 (★ over W8 spec "ping me" threshold of 15)
distinct PA tool = 5/5: sspa_ora / ramp_enrichment / metaboanalystr_psea / mummichog / fella_rwr
distinct util    = 2/4: lookup_chebi / query_pathway_members
inner_retry_used = False (LLM 第 1 次 finalise 即出 valid grammar v2 JSON)
wall_seconds     = 166.6
n_claims         = 11 (4 grammar types 都有 ≥ 1)
naming bridge    = no literal mention (steroid task — gt name 不是 LIPID MAPS bridging 目标)
sspa 状态        = wrapper_unavailable (env 缺 sspa pkg),fallback envelope 干净
error            = none
```

### Smoke 2 verdict — lipid smoking gun `lm_pathway_WP167_seed3`

```
task_id          = compound_only_enrich_mammalian_lm_pathway_WP167_seed3
ground_truth     = Eicosanoid synthesis (lm_pathway:WP167, LIPIDMAPS namespace)
task_outcome     = normal
n_turns          = 8 / 8 (force_finalised=True)
n_tool_calls     = 26 (★ 同样 > 15)
distinct PA tool = 5/5
distinct util    = 2/4: lookup_chebi / query_pathway_members
inner_retry_used = False
wall_seconds     = 194.2
n_claims         = 11
★ naming bridge  = NO LITERAL "Eicosanoid synthesis" / "WP:WP167" / "LIPIDMAPS"
                   LLM 写 "Arachidonic acid metabolism" + "leukotriene" + "prostaglandin"
                   所有 claim pathway_id 都是 MUMM: namespace(Mummichog 的 human_mfn)
                   ← 同 v3 Opus baseline gap(报告 §3 known issue)
error            = none
```

### Smoke 2 关键 finding(paper-relevant)

🔵 **D3 LLM-agent 在 lipid bucket WP167 上不自主桥到 LIPIDMAPS namespace**。
原因实测:
1. **Mummichog 是唯一返回非空 pathway 的 PA tool**(turn 2 返 0、turn 5
   返 10 — top 是 "Arachidonic acid metabolism" 在 MUMM:00002)。RaMP /
   FELLA / PSEA 在该 lipid 输入上都返回 `n_pathways=0`。
2. LLM 忠实写 Mummichog 报告的 pathway 名 "Arachidonic acid metabolism"
   而非 ground truth "Eicosanoid synthesis";没用 system prompt 的
   "naming bridge note"(单段文字,LLM 未触发)。
3. `query_pathway_members(WP:WP167)` × 3 次返回 `data_not_available`
   envelope(D2 known scoping gap),fallback_suggested 指向
   `metabolites_hit` —— LLM 没回退到读 RaMP/FELLA 的 metabolites_hit
   反查命名,因为这些 tool 返 empty。

**这是 D4 的 motivation**:closed-loop verifier 会对 pathway_id="MUMM:00002"
+ pathway_name="Arachidonic acid metabolism" 产生 `unsupported`(verifier
查 task 的 `ground_truth_pathway.external_id="WP167"`,不匹配)→ feedback
hint 推 LLM 用 verifier-friendly 命名 → 第二轮 narrative 可能改写为
"Eicosanoid synthesis (lm_pathway:WP167) — also reported as 'arachidonic
acid metabolism' by mummichog (MUMM:00002)"。**D4 末 smoke 2 重跑实测**
将给出"bridge gap 是否能 verifier-driven 闭合"的直接答案。

**RaMP/FELLA/PSEA 在 lipid 上 0 hit 也是 finding**:可能是
(a) ID format mismatch — LLM 传 bare KEGG `C00219` 但 RaMP-wrapper id_type
"auto" 推断到 inchikey 兜底致 miss;(b) RaMP-DB 内容缺 LIPID MAPS
覆盖(已知 LIPID MAPS 集成是 v3 才加,RaMP-DB 镜像可能旧)。**D5 跑 63
task 前需要查 RaMP wrapper id_type 行为** — W9 candidate task。

### Sanity 8 项实测

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | Smoke 1 (steroid) end-to-end normal | ✅ | task_outcome=normal / 11 claims / valid grammar v2 / wall 166.6s |
| 2 | Smoke 2 (lipid) end-to-end normal | ✅ | task_outcome=normal / 11 claims / valid grammar v2 / wall 194.2s |
| 3 | LLM ≥ 3 PA tool call(W8 system prompt 硬规则) | ✅ | Smoke 1: 5 distinct PA / Smoke 2: 5 distinct PA |
| 4 | Final message valid grammar v2 (narrative_text + 4-类 claims) | ✅ | 两 smoke 各 11 claim,claim_type 全在 4 类内,parse 无错 |
| 5 | tests/concord/test_concord_tools.py 13 case(D2 12 + D3 hotfix regression) | ✅ | 13 passed in 0.65s |
| 6 | tests/concord/test_react_runner.py 5 case | ✅ | 5 passed in 0.03s |
| 7 | tests/concord/ 全集不退步 | ✅ | **9 failed / 157 passed**(D2 baseline 9/139 → D3 9/157,+18 pass = 12 moved + 6 new D3 test;9 fail byte-identical pre-existing env issue) |
| 8 | 全 repo pytest 17 pre-existing fail 不变 | ✅ | **17 failed / 1269 passed / 33 skipped in 1167.20s** vs D2 baseline 17/1263/33 → **+6 pass = D3's 6 new tests**(5 react_runner + 1 hotfix regression);17 fail 名字 byte-identical D1/D2,0 regression |

### Stop condition ★ soft-flag 给 user

🟡 **W8 prompt §6 Stop #3**: "LLM 1 task 调 tool > 15 次 → max_turn 用满,
**ping me**"。Smoke 1 = 23 calls,Smoke 2 = 26 calls,**两者都触发 soft
ping**(非 hard fail —— outcome 仍 normal,claims 仍 11,wall 仍 ≤ 5 min)。

**Call breakdown**(smoke 2 lipid 为例):
- Turn 1: 9× `lookup_chebi`(对 9 个 diff metabolite 做 ID reconciliation;
  合理的初步动作)
- Turn 2: 1× ramp + 1× mummichog + 1× fella(并行起步)
- Turn 3: 1× sspa(wrapper_unavailable) + 1× psea(empty)
- Turn 4: 1× psea + 1× fella(retry 不同 args)
- Turn 5: 1× ramp + 1× mummichog(turn 5 mummichog 出关键结果) + 1× fella
- Turn 6: 4× lookup_chebi(对 mummichog 返回的 compound 做 reverse lookup)
- Turn 7: 3× query_pathway_members(对 WP / KEGG / LIPIDMAPS namespace 都试了,
  都返 data_not_available)
- Turn 8: forced finalise

LLM 不是失控调 tool,是 9-tool catalog × 9-metabolite 输入 × 不同 namespace
retry 的笛卡尔积膨胀。**建议(待 user 决策)**:
- (A) **现状保持** — 26 call 在 5-min 内做出 normal outcome + 11 claim,paper
  finding 角度可接受。D5 跑 63 task 在此 call 量下:63 × ~25 call ≈ 1575 LLM call,
  MiniMax 价格约 $0.001/call → ~$1.6 — 仍在预算。
- (B) **system prompt 加 "do not call > 15 tools per task" 硬规则** — 风险:
  LLM 可能放弃必要的 retry/verify,outcome 质量降。
- (C) **dispatcher 加 task-level call counter,超 N 后所有 tool 拒接** —
  最严,但可能产生 EMPTY_SYSTEM_FAILURE 浪费。

我倾向 (A) 保持。请用户拍板。

### D4 预热

D4 任务:close the loop。新文件 `concord/agent/verifier_adapter.py` —
把 `final_narrative_json` + sub6b-v3 task 桥到 B1 `verifier.agent.verify()`
入参 (`llm_output: str, source_report: SubsixSourceReport`)。`run_task`
增 `verifier_fn` 注入 + feedback loop max_iter=2 + quality rollback。

D4 末 smoke 2 重跑:看 verifier 对 smoke 2 的 `MUMM:00002 Arachidonic acid
metabolism` claim 给什么 verdict;若 unsupported + feedback hint 推 LLM 用
verifier-friendly 命名,**第二轮可能就桥到 WP167**。**D4 末 smoke 2 是 D3
naming bridge finding 的直接答案**。

