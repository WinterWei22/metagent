# MetAgent 全流程 · 工具细节 · 各模块输入输出（总参考）

> 整理日期：2026-06-30 · 分支 `metagent-v3-benchmark`
> 用途：一份看懂**当前在跑的全部流程**——每个模块「做什么 / 输入 / 输出 / 关键字段」。
> 配套：方法/数据/结果见同目录 `2026-06-30_stage1_*`、`2026-06-30_stage1_2_e2e_*`、`2026-06-29_stage2_summary.md`。
> 口径标注：Stage 1 走 `verify()`；Stage 2 走 `verify_sub6()`（CLAUDE.md line 256 边界）。

---

## 0. 三流程总览

```
流程 A — Stage 1（单谱结构识别）
  MS/MS 谱 → Phase A 质量窗 → library_search → [可选 rerank] → top-1 结构 → verify()/Layer F

流程 B — Stage 2（富集通路鉴定）
  差异代谢物组 → ConcordReactRunner（9 function-tool ReAct，5-PA 富集）
              → grammar-v2 claims + narrative → verify_sub6()（4 层）
              → cascade feedback → second-pass pathway_prediction → 通路报告

流程 C — Stage 1+2 端到端（谱图集合 → 通路报告）
  sub6a 谱图 → [流程 A 识别] → 识别出的代谢物 → [桥接转 v4 schema] → [流程 B] → 通路报告 → semantic 打分
```

| | Stage 1 | Stage 2 | Stage 1+2 端到端 |
|---|---|---|---|
| 输入 | 一张 MS/MS 谱 | 一组差异代谢物 `{name,smiles,inchikey}` | 一组 MS/MS 谱 |
| 输出 | ranked 候选结构 + 峰证据 | pathway_prediction + verified claims | pathway_prediction（误差含 Stage 1 误判） |
| verifier | `verify()` + Layer F | `verify_sub6()` 4 层 | `verify_sub6()` |
| 主 driver | `run_baseline.py --sub6a` / `run_casmi.py` | `v4_bench_eval.py` | `stage1_2_e2e_build.py` + `v4_bench_eval.py` |

---

## 1. Stage 1 模块 I/O（结构识别）

### 1.1 `task_spectrum_to_schema`（`evaluation/sub6/identification.py:137`）
| | |
|---|---|
| 输入 | task 谱 dict：`{spectrum_id, precursor_mz, peaks:[[mz,intensity]], adduct, ion_mode, collision_energy}` |
| 输出 | `schemas.Spectrum`：`raw_mz[], raw_intensity[], precursor_mz, adduct, ionization_mode(pos/neg), collision_energy, mz_tolerance_ppm=5` |
| 做什么 | 峰排序 + 强度归一化（base peak→1.0）+ adduct 规范化（`[M+H]1+`→`[M+H]+`） |

### 1.2 `identify_spectrum`（`identification.py:240`）—— Stage 1 核心
| | |
|---|---|
| 输入 | `Spectrum` + library(`("gnps",)`) + `mass_tolerance_ppm=10` + `top_k=20` + `primary_retriever="modcos"` + 可选 reranker |
| 输出 | `SpectrumIdentification` |
| 关键输出字段 | `predicted_inchikey_first_block`(14字符), `predicted_name`, `predicted_smiles`, `predicted_score`, `correct_top1`, `n_candidates_returned`, `n_after_exclusion`, `ranked_candidates[]` |
| **准确率定义** | `correct_top1 = (predicted_smiles→InChIKey14) == gt_inchikey_first_block`，**2D 骨架匹配,非全 InChIKey/非 DB ID** |

### 1.3 `library_search`（`tools/library_search/`，via `docs/TOOL_CONTRACTS.md`）
| 输入 | 输出 |
|---|---|
| `Spectrum` + `mass_tolerance_ppm=10`, `top_k=20`, `libraries=[inhouse,gnps]`, `min_score=0.3` | top-20 候选 `{smiles, source_id, modcos, msclip, score, ik14}`（按 `max(modcos, msclip_rescaled)` 排） |

### 1.4 rerank head（`evaluation/sub6/rerank.py` + `llm_reranker.py`，可选）
| 模块 | 输入 | 输出 |
|---|---|---|
| SIRIUS | Spectrum | top-1 分子式 + fragmentation tree（sanity gate：分子式不符→evidence×0.5） |
| CFM-ID | 候选 SMILES | 预测 MS/MS 谱（disk-cached）→ predicted_cosine |
| weighted | 上述信号 | `evidence_score = 0.4·modcos + 0.3·pred_cosine + 0.2·mass_match + 0.1·pathway` |
| LLM reranker (Opus-4-7) | JSON evidence bundle | selected top-1 + ranked_indices（CASMI OOD 用） |

### 1.5 `run_sub6a` / `run_sub6a_batch`（`evaluation/sub6/run_sub6a.py:109/267`）
| | |
|---|---|
| 输入 | sub6a task dict（含 `differential_spectra[]`）+ `strategy="library_search"` + `skip_narrative` |
| 输出 | `Sub6AResult`：`identified_metabolites:[{name,inchikey_first_block}]`、`identifications:[asdict(SpectrumIdentification)]`、`narrative`、`llm_model`、`llm_calls` |

### 1.6 `verify()` + Layer F（`verifier/agent.py:108` + `verifier/layers/peak_mechanistic.py`）
| | |
|---|---|
| 输入 | `llm_output:str` + `source_report: IdentificationReport` |
| 输出 | `VerifiedIdentification`（verdicts_total + claims + dropped） |
| Layer F | 触发：claim 含 m/z 数值 + fragment/loss 关键词；判定：spectrum ±5ppm 内是否真有该峰 → SUPPORTED/CONTRADICTED/UNVERIFIABLE |

---

## 2. Stage 2 模块 I/O（富集通路鉴定）

### 2.1 ReAct 主入口 `ConcordReactRunner.run_task_with_feedback`（`concord/agent/react_runner.py:612`）
| | |
|---|---|
| 输入 | task dict `{task_id, differential_metabolites:[{name,smiles,inchikey(27字符)}], ground_truth(不进 prompt)}` |
| 输出 | `ConcordFeedbackResult` |
| prompt 渲染 | agent 只看到 `- <name> (SMILES: <smiles>, InChIKey: <ik>)`，KEGG/DB ID 刻意 suppress（`_strip_task_for_llm` 剥 ground_truth） |

### 2.2 9 个 function-tool（`concord/agent/tool_dispatcher.py` + `tool_handlers.py`）

**5 个富集 PA 工具**（输入 `compound_ids:list[str]`(混合 NS) + `top_n`，输出统一 `EnrichmentResult`）：
| tool | 方法 | 数据源 / 备注 |
|---|---|---|
| `run_sspa_ora` | Reactome hypergeometric ORA | sspa 包 |
| `run_ramp_enrichment` | 多 DB ORA（RaMP sqlite 本地） | Reactome+SMPDB+KEGG+WP；`KEGG:map00X→KEGG:hsa00X` 归一化 |
| `run_metaboanalystr_psea` | PSEA ORA | Docker R subprocess（~10s，KEGG/SMPDB） |
| `run_mummichog` | 人工代谢网络 activity | 可吃 `peaks:[{mz,p_value,t_score}]`；低注释友好 |
| `run_fella_rwr` | KEGG 5 层图 RWR | Docker R（~8s，间接通路，最慢） |

**4 个解析/检索工具**：
| tool | 输入 | 输出关键字段 |
|---|---|---|
| `lookup_chebi` | `id`(CHEBI/KEGG/HMDB/name/SMILES/InChIKey) + `namespace?` | `{primary_id, chebi_id, hmdb_id, kegg_compound_id, lipidmaps_id, inchikey(27字符), display_name}` |
| `reconcile_inchikey` | `refs:[{inchikey,display_name,primary_id}]` | `{n_clusters, conflict_type, n_distinct_block14, n_distinct_full, block14s}` |
| `query_pathway_members` | `pathway_id`(NS:id) | `{pathway_id, member_chebi_ids:[...]}` |
| `search_literature` | `query` + `max_results[1-20]` | `{n_results, results:[{pmid,title,abstract,year}]}` |

> ⚠ `lookup_chebi`/PA 工具的 InChIKey 解析只认**完整 27 字符**;14 字符 first-block MISS（Stage 1+2 端到端踩过的坑,见 e2e 文档 §3.3）。

### 2.3 `EnrichmentResult` / `PathwayHit` / `CompoundRef` schema（`concord/schema/enrichment.py`）

**EnrichmentResult**：`method`(enum), `pathway_db`(enum), `pathways:tuple[PathwayHit]`, `parameters`, `tool_version`, `db_release`, `n_input`, `n_input_resolved`, `wall_time_sec`, `schema_version="concordmet_v0.3.1"`。
**PathwayHit**：`pathway_id`(NS:id,NS∈{REACT,KEGG,WP,SMPDB,METACYC,MUMM,HUMAN1,RECON2}), `pathway_name`, `pathway_id_native`, `pathway_db`, `score`, `score_type`(p_value/fdr/nes/rwr_score/ease), `rank`, `metabolites_hit:tuple[CompoundRef]`, `n_metabolites_in_pathway`, `n_metabolites_input`。
**CompoundRef**：`primary_id`(NS:id), `inchikey`(27字符,必填), `display_name`, 可选 `chebi_id/lipidmaps_id/hmdb_id/kegg_compound_id/pubchem_cid/metanetx_id`。

### 2.4 `verify_sub6` + 4 层（`verifier/agent.py:549`）
| | |
|---|---|
| 输入 | `llm_output:str`(grammar-v2 JSON) + `source_report: SubsixSourceReport` + `driver_lookup` + `is_final_iteration` |
| 输出 | `VerifiedIdentification`：`claims_v1/v2:[VerifiedClaim]`, `verdicts_total:{supported,contradicted,unsupported,unverifiable_v0,insufficient_evidence}`, `dropped_claims`, `llm_calls` |

**4 层**（每 claim 按 grammar 路由）：
| 层 | 判定 | I/O |
|---|---|---|
| 6a `set_enrichment` | pathway 富集统计意义 | claim.term_id ∩ source_report.top_pathways → SUPPORTED/CONTRADICTED/UNSUPPORTED/UNVERIFIABLE_V0 |
| 6b `driver_metabolite` | driver 是否在 GT signal | claim.signal_compound_ids ⊆ ground_truth_signal_compounds |
| 6c `biological_sub6` | 代谢物-通路关系（membership / link） | (subject, pathway_name[, enzyme])→ RaMP 查 → SUPPORTED/UNSUPPORTED/UNVERIFIABLE_V0 |
| 6d `pathway_relationship` | 特化通路关系（aliased 6c） | membership/link 结构 |

**4-shape grammar**（`verifier/grammar.py`，超出即 UNVERIFIABLE_V0）：
| grammar | 必填字段 |
|---|---|
| `pathway_membership` | `subject`, `pathway_name` |
| `metabolite_pathway_link` | `subject`, `pathway_name`, `enzyme_or_reaction`(具体酶名/Rxxxxx,泛词被 drop) |
| `pathway_enrichment` | `term_id`, `term_name`, `term_type`, `metabolite_set` |
| `driver_metabolite` | `subject`, `signal_compound_ids` |

**VerifiedClaim 公共字段**：`claim_id, claim_text, claim_type, grammar, verdict`(SUPPORTED/CONTRADICTED/UNSUPPORTED/UNVERIFIABLE_V0/INSUFFICIENT_EVIDENCE), `correction`(CONTRADICTED 时 top-1 纠正), `subject, extracted_fields, evidence_snippets`。

### 2.5 cascade feedback（`concord/agent/feedback_strategies.py` + `react_runner.py:974`，生产默认）
确定性过滤 iter-0 claims（无 LLM 改 claim,只 LLM 织叙述）：
| verdict | 处置 |
|---|---|
| SUPPORTED / INSUFFICIENT_EVIDENCE | 保留（rebuild grammar-v2 dict） |
| CONTRADICTED | `pathway_name ← claim.correction`(top-1)；correction 空则删 |
| UNSUPPORTED / UNVERIFIABLE_V0 / NEEDS_HUMAN_REVIEW / ERROR | 删除 |
- 输入 `VerifiedClaim[]` + source_report → 输出 `FeedbackResult{payload:grammar-v2 JSON, corrected_claims}`。
- `weave_narrative`（1 次 LLM）只生成叙述 → re-verify（zero-LLM `extract_claims_from_json`）→ 若 quality 不改善则 rollback 到 iter-0。

### 2.6 second-pass `generate_pathway_prediction_second_pass`（`concord/agent/pathway_prediction.py:173`）
| | |
|---|---|
| 输入 | `claims:[dict]` + `narrative_text` + `chat_fn/model/provider` |
| 输出 | `PathwayPrediction` dict：`primary:PathwayPredictionEntry|None`, `alternatives:[...]`, `abstain:bool`, `abstain_reason` |
| `PathwayPredictionEntry` | `pathway_id, pathway_name`(必人读名,非 ID), `pathway_source, confidence, evidence_methods:[...], supporting_claim_indices:[int], rationale` |
| 失败 | 返回 `{primary:None, alternatives:[], abstain:True, abstain_reason:"second_pass_failed"}`（永不抛异常） |

### 2.7 ReAct 输出 dataclass（`react_runner.py`）
**ConcordReactResult**：`task_id, iterations:[ConcordIterationRecord], final_iter_idx, final_narrative_json, final_claims:[dict], final_narrative_text, pathway_prediction, final_verdict_total, n_feedback_iterations, elapsed_seconds, llm_model, n_distinct_tools_called, tools_called:[str], tool_calls_trace, enrichment_carriers, error, rollback_reason, termination_reason`。
**ConcordFeedbackResult**：`task_id, iterations:[FeedbackIterationRecord], final_iter_idx, n_feedback_iterations, rollback_reason, final_react_result:ConcordReactResult, final_verdict:VerificationOutcome`。
> `enrichment_carriers` = {ramp/mummichog/sspa/fella/metaboanalystr `_enrichment_result`} 传给 verifier 做 source。

---

## 3. Stage 1+2 桥接模块 I/O

### 3.1 `stage1_2_e2e_build.py`（`scripts/metagent/`）
| | |
|---|---|
| 输入 | `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`（38 task，含 differential_spectra + ground_truth_pathway） |
| Stage 1 | `run_sub6a_batch(skip_narrative=True, library_search, 10ppm, modcos)` → `stage1_results.jsonl` |
| 桥接 | 每 task：识别出的谱→`{name, smiles, inchikey(完整27字符,RDKit 从 smiles 重算)}` 去重 → v4 task `{task_id:"sub6_easy_"+id, input.differential_metabolites, ground_truth.perturbed_pathway}` |
| 输出 | `e2e_benchmark.jsonl`（合成 v4 benchmark）+ `build_summary.json`（id-acc + per-task） |

### 3.2 `v4_bench_eval.py` → 3.3 `full344_pathway_scorecard.py`
| 模块 | 输入 | 输出 |
|---|---|---|
| `v4_bench_eval.py` | 合成 benchmark + `--strata sub6` | `stage2_full*/path_x_full/<tid>.json`(ConcordFeedbackResult) + `status/` |
| `full344_pathway_scorecard.py` | `--out-dir` traces + `--benchmark` | semantic 打分：`PathwayNameMatcher.is_hit(primary_name,[gt_name])` → `e2e_full38*.{json,md,csv}` |

---

## 4. 端到端数据流（流程 C 一图）

```
sub6a task (differential_spectra[10])
  │  task_spectrum_to_schema → Spectrum
  ▼
identify_spectrum (library_search modcos ±10ppm, top20)
  │  → SpectrumIdentification{predicted_smiles, predicted_inchikey_first_block, correct_top1}
  ▼
_metabolites_from_identifications (去重 + RDKit 重算完整 InChIKey)
  │  → differential_metabolites:[{name, smiles, inchikey(27字符)}]
  ▼
ConcordReactRunner.run_task_with_feedback
  │  ├─ build_concord_react_messages → "- name (SMILES, InChIKey)"
  │  ├─ ReAct: 调 5-PA 富集工具 → EnrichmentResult(PathwayHit[])
  │  ├─ grammar-v2 claims + narrative
  │  ├─ verify_sub6 (4 层) → VerifiedClaim[] (verdicts_total)
  │  ├─ cascade: 保 SUPPORTED / CONTRADICTED→correction / 删 UNS+UV → 织 narrative
  │  └─ generate_pathway_prediction_second_pass → {primary, alternatives, abstain}
  ▼  ConcordFeedbackResult
full344_pathway_scorecard: is_hit(primary.pathway_name, [ground_truth_pathway.name])
  ▼
primary/top-k semantic accuracy
```

---

## 5. 数据 schema 速查

| schema | 位置 | 关键字段 |
|---|---|---|
| `Spectrum` | `schemas/spectrum.py` | raw_mz[], raw_intensity[], precursor_mz, adduct, ionization_mode, collision_energy |
| `IdentificationReport` | `schemas/report.py` | candidates:[CandidateReport(smiles,inchikey,evidence_score,...)], n_*_candidates |
| `SpectrumIdentification` | `evaluation/sub6/identification.py:95` | predicted_inchikey_first_block, predicted_smiles, predicted_name, correct_top1 |
| `Sub6AResult` | `evaluation/sub6/run_sub6a.py:59` | identified_metabolites, identifications, narrative |
| `SubsixSourceReport` | `schemas/sub6_report.py` | differential_metabolites, ground_truth_*, ramp_enrichment_result, top_pathways |
| `EnrichmentResult`/`PathwayHit`/`CompoundRef` | `concord/schema/enrichment.py` | 见 §2.3 |
| `PathwayPrediction` | `concord/agent/pathway_prediction.py` | primary, alternatives, abstain, abstain_reason |
| `VerifiedClaim`/`VerifiedIdentification` | `verifier/schemas.py` | verdict, grammar, correction, verdicts_total |

> 死命令：MiniMax/Opus 远程 API,cost 实测查 `logs/llm_calls.jsonl` / `logs/concord/*.jsonl`,禁说 "$0 local"。
