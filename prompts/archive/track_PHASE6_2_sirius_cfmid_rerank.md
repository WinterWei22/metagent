# Track PHASE 6.2 — SIRIUS + CFM-ID reranking + peak-level evidence on Sub-6A real-id v2

**Session ID:** `track_PHASE6_2_sirius_cfmid_rerank`
**Branch:** `feature/sub6-sirius-cfmid-rerank`(新建 from `feature/sub6-msclip-ablation` 或 v2-integrated)
**Estimated work:** 1-2 days wall(主要是 SIRIUS / CFM-ID 推理时间)
**Predecessors:**
- `reports/eval/msclip_ablation_v2.md`(MS-CLIP ablation,67.32% baseline)
- `reports/eval/sub6_v2_comparison_2026-05-06.md`(主结果,Layer F peak_mechanistic = 0)

---

## Why this matters

Sub-6A real-id v2 当前流程**完全跳过 SIRIUS + CFM-ID**:

```python
# evaluation/sub6/identification.py 当前
spectrum → library_search (only modcos+optional msclip) → top-1
```

但 `tools/sirius/` 和 `tools/spectrum_predict/` 已经实现,且 `schemas/report.py` 的 `compute_evidence_score` 公式预留了 CFM-ID 权重 (0.3):

```
evidence_score = 0.4·library_cosine + 0.3·predicted_spectrum_cosine 
               + 0.2·mass_match + 0.1·pathway_presence
```

加上 SIRIUS rerank,本 session 干 3 件事:
1. **rerank 提升 id_acc**(从 67.32% 提到目标 75-80%)
2. **产出 peak-level evidence**(给下游 LLM narrative grounding + verifier Layer F 验证素材)
3. **跑 ablation**:gnps only / +SIRIUS / +CFM-ID / +both 4 配置

**关键定位**:本 session 只做**identification 阶段 + peak evidence 落盘**,不跑 LLM narrative 和 verifier。peak evidence 写到独立 JSONL,留给后续 session 消费。

---

## Hard scope boundaries

**You MAY:**
- 在 `evaluation/sub6/identification.py` 加 reranking 逻辑(独立函数,可 toggle)
- 调 `tools/sirius/` 和 `tools/spectrum_predict/`(已实现的 wrapper)
- 写新文件 `evaluation/sub6/peak_evidence.py`(产出 peak-level evidence)
- 写 reranker `evaluation/sub6/rerank.py`(组合 modcos + SIRIUS + CFM-ID 评分)
- 加 4 个 ablation config 命令
- 写报告 `reports/eval/sirius_cfmid_rerank_v2.md`

**You MAY NOT:**
- 修 `tools/sirius/` 或 `tools/spectrum_predict/` 的算法逻辑(只调用,不改实现)
- 修 `schemas/report.py` evidence_score 权重(用现有 0.4/0.3/0.2/0.1)
- 跑 LLM narrative(本 session `--skip-narrative`)
- 跑 verifier(留给后续 session)
- 覆盖现有 v2 / msclip_ablation 文件
- 修 prompt 模板

---

## Background reading

1. `evaluation/sub6/identification.py`(SpectrumIdentification 数据类 + identify_spectrum)
2. `tools/sirius/tool.py`(看 sirius_annotate 签名 + 输出 schema)
3. `tools/spectrum_predict/tool.py`(看 predict_spectrum 签名)
4. `tools/library_search/scoring.py`(看 modified_cosine_score / fuse_scores)
5. `schemas/report.py`(`compute_evidence_score` + `CandidateReport` schema)
6. `scripts/run_full_pipeline.py` Stage 5 (line ~700-830,看现有 enrichment 怎么调 SIRIUS+CFM-ID)
7. `verifier/layers/peak_mechanistic.py`(看 Layer F 期望什么 peak evidence schema 才能消费)
8. `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`

In your first response,确认:
- SIRIUS 单次调用平均 wall time(秒)
- CFM-ID 单次调用平均 wall time + 是否有 SMILES cache
- Layer F 期望的 peak evidence 字段结构(为产出 schema 设计)
- 459 spectra × top_k 候选,SIRIUS 总 wall time 估算
- 是否需要 GPU(CFM-ID docker shim) / SIRIUS 是否串行 only

不要写代码或跑命令,直到 confirm。

---

## Key design decisions(prompt 已替你做了,确认即可)

### D1: top_k 设为 5(不是 20)

modcos 给的 top-20 后面 15 个分数低 + 大概率错。本 session 对前 5 个跑 SIRIUS+CFM-ID,降低成本。

### D2: SIRIUS 跑 per-spectrum 一次,**不是 per-candidate**

SIRIUS 接受 (spectrum, max_candidates) 输出 top-K formulas + fragmentation trees。我们对每 spectrum 跑一次 `--candidates 5`,然后 lookup 候选化合物的 formula 跟 SIRIUS top formulas 比对。

成本:459 spectra × ~30s = ~4 hours(可并行 4-8 worker 加速到 1-2 hours)。

如果某 candidate 的 formula 不在 SIRIUS top-K formulas 里,该 candidate 的 sirius_match_score = 0。否则 = SIRIUS confidence(0-1)。

### D3: CFM-ID per-(SMILES, adduct, CE) 缓存

不同 spectra 的同一 candidate SMILES 共享 CFM-ID 预测(预测谱跟 spectrum 无关,只跟 SMILES + ion mode 有关)。

成本:459 × 5 = 2295 candidate slots。去重后预计 1500-2000 unique (SMILES, adduct) → ~1500 × 7s = ~3 hours。

CFM-ID cache 写到 `data/cache/cfmid/<smiles_hash>.json`,跑过的不重跑。

### D4: Reranking 公式(用 schemas 现有 evidence_score)

```python
predicted_cosine = cosine(experimental_peaks, cfmid_predicted_peaks, tol=10ppm)
sirius_match = 1.0 if candidate.formula in sirius_top_formulas else 0.0
mass_match = 1.0 if abs(precursor - candidate.exact_mass) < 5ppm else 0.0
pathway_presence = ... (现有逻辑,留 0 OK,因为 Sub-6A 不查 pathway_context)

evidence_score = 0.4 * modcos_normalized 
               + 0.3 * predicted_cosine
               + 0.2 * mass_match
               + 0.1 * pathway_presence

# 额外:SIRIUS sanity gate(NM-001 mitigation 复用)
if sirius_match == 0 and candidate.formula 跟 sirius_top1 差 ≥3 atoms:
    evidence_score *= 0.5  # 降权但不直接踢掉
```

注意:**不要发明新权重**,用 schemas 既有公式。SIRIUS 通过 sanity gate 介入,不直接进 evidence_score 公式(避免破坏 prior work 对比口径)。

### D5: Peak evidence 落盘 schema

`data/eval/sub6/v2_phase6_2/peak_evidence/<spectrum_id>.json`:

```json
{
  "spectrum_id": "...",
  "experimental_peaks": [[mz, intensity], ...],
  "sirius": {
    "top_formulas": [{"formula": "C7H15NO3", "score": 0.95}, ...],
    "fragmentation_tree": {  
      "<mz>": {"formula": "...", "neutral_loss": "...", "annotation": "..."}
    }
  },
  "cfmid_top1": {
    "smiles": "...",
    "predicted_peaks": [[mz, intensity, fragment_smiles], ...],
    "cosine_vs_experimental": 0.87
  },
  "candidates_evaluated": [
    {"smiles": "...", "modcos": 0.82, "predicted_cosine": 0.71, 
     "sirius_match": 1.0, "evidence_score": 0.78, "rank_after_rerank": 1},
    ...
  ]
}
```

这个文件是 paper 的核心新产物——既证明 SIRIUS/CFM-ID 真接入,又给下游 LLM/verifier 喂结构化数据。

---

## Deliverables

### D1 — Reranker 实现(0.5 day)

新文件 `evaluation/sub6/rerank.py`:

```python
def rerank_with_sirius_cfmid(
    spectrum: dict,
    modcos_candidates: list[Candidate],  # library_search top-20
    *,
    top_k_for_rerank: int = 5,
    use_sirius: bool = True,
    use_cfmid: bool = True,
    cfmid_cache_dir: Path = Path("data/cache/cfmid/"),
) -> tuple[list[Candidate], dict]:
    """
    Rerank top_k candidates by combining modcos + sirius + cfmid scores.
    
    Returns:
      reranked_candidates: list[Candidate] sorted by evidence_score desc
      peak_evidence: dict (D5 schema for落盘)
    """
```

加 unit test(mock SIRIUS + CFM-ID,断言 evidence_score 计算正确)。

### D2 — Identification 集成 + CLI(0.5 day)

`evaluation/sub6/identification.py` 加参数:
- `use_sirius: bool = False`
- `use_cfmid: bool = False`

`evaluation/sub6/run_sub6a.py` + `scripts/eval_sub6/run_baseline.py` 加 CLI:
- `--rerank-with sirius,cfmid`(逗号分隔,空 = 关)

**Default**(`--rerank-with` 不传)= 现行行为不变,跟 v2 baseline + msclip ablation Config A 一致。

### D3 — Sanity smoke(1-2 spectra,30 分钟)

跑 1 个 task(~10 spectra)用 `--rerank-with sirius,cfmid`,确认:
- SIRIUS 返回 top formulas
- CFM-ID 返回 predicted spectrum
- evidence_score 计算无 NaN
- peak_evidence JSON 格式合法

### D4 — Full ablation(主体,1 day wall)

4 个 config 在 Sub-6A real-id v2 (38 task / 459 spectra):

```bash
# Config A: gnps only (baseline 复现 67.32%)
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --out-dir data/eval/sub6/v2_phase6_2/gnps_only/ \
    --libraries gnps \
    --rerank-with "" \
    --skip-narrative \
    --mass-tolerance-ppm 10.0

# Config B: gnps + SIRIUS rerank
... --rerank-with sirius ...
out-dir: data/eval/sub6/v2_phase6_2/sirius/

# Config C: gnps + CFM-ID rerank
... --rerank-with cfmid ...
out-dir: data/eval/sub6/v2_phase6_2/cfmid/

# Config D: gnps + SIRIUS + CFM-ID (full evidence_score)
... --rerank-with sirius,cfmid ...
out-dir: data/eval/sub6/v2_phase6_2/full/
```

**所有 config 输出 peak_evidence JSON**(Config A peak_evidence 只有 modcos,没 sirius/cfmid 字段)。

预期 wall:
- Config A: ~5 min(已知)
- Config B: ~2 hours(SIRIUS 主导)
- Config C: ~3 hours(CFM-ID 主导,首次跑无缓存)
- Config D: ~4 hours(SIRIUS + CFM-ID 并行)

总 ~10 hours,可后台跑。

### D5 — Aggregator(15 分钟)

新写 `scripts/eval_sub6/aggregate_phase6_2.py`,产出:

`data/paper_figures/phase6_2_sirius_cfmid_ablation.csv`:

| Config | id_acc | id_acc_taskmean | wall_time | peak_evidence_per_spec |
|---|---:|---:|---:|---:|
| gnps_only | 67.32% | 67.37% | 5min | modcos only |
| +sirius | ? | ? | ? | + sirius tree |
| +cfmid | ? | ? | ? | + predicted peaks |
| +both | ? | ? | ? | full |

加 per-bucket breakdown(用 pathway_source 分桶,跟 msclip ablation 同口径)。

加 win/loss vs gnps_only(同 msclip ablation 模式)。

### D6 — 报告 `reports/eval/sirius_cfmid_rerank_v2.md`

#### 1. Summary
3-5 行:id_acc 数字 + peak evidence 产出 + paper 影响。

#### 2. Setup
跟 msclip_ablation_v2.md §2 同结构。

#### 3. Main result
D5 主表 + 4 个 config 比较。

#### 4. Per-bucket breakdown
按 pathway_source 5 分类。

#### 5. Win/loss analysis
gained/lost/unchanged,跟 msclip 同模式。

#### 6. Peak evidence 产出
- 多少 spectrum 有 SIRIUS top-1 formula(SIRIUS 失败率)
- 多少 spectrum 的 CFM-ID predicted_cosine > 0.5(高质量预测)
- SIRIUS top-1 formula 跟 ground-truth formula 一致率(独立指标)
- 这些数字本身就是 paper finding

#### 7. SIRIUS sanity gate 触发统计
多少 candidates 被 sanity gate 降权(NM-001 mitigation 在 v2 实战中的影响)

#### 8. Cost
- SIRIUS / CFM-ID wall time 各占多少
- CFM-ID cache hit rate
- 总 GPU/CPU 占用

#### 9. Paper finding
1-2 段:
- 跟 msclip ablation 对比(MS-CLIP 是负结果,SIRIUS+CFM-ID 是 ?)
- peak evidence 落盘的下游价值(即将解锁 Layer F)
- 跟 prior work(SIRIUS-only / SIRIUS+CSI:FingerID baseline)对比

#### 10. Limitations
- top_k=5 限制
- SIRIUS 在稀疏低 CE 谱图的失败模式(NM-001 复现?)
- CFM-ID negative-mode 准确率 known issue

#### 11. Provenance + 完整命令 + MD5

### D7 — Acceptance

```
□ 4 个 config 跑完,各 38 task / 459 spectra
□ Config A id_acc 复现 67.32% ± 0.5pt(sanity)
□ Config B/C/D id_acc 都报数(允许任一为 negative result)
□ data/eval/sub6/v2_phase6_2/<config>/peak_evidence/*.json 完整(459 个 spectrum)
□ data/paper_figures/phase6_2_sirius_cfmid_ablation.csv 主表
□ 报告 11 节完整
□ 0 LLM narrative 调用
□ 0 verifier 调用
□ 现有 v2 / msclip_ablation 文件未动
□ git diff 限制在 evaluation/sub6/{rerank,peak_evidence,identification,run_sub6a}.py 
  + scripts/eval_sub6/{run_baseline.py, aggregate_phase6_2.py} 
  + 1-2 个 unit test
```

---

## Pitfalls

1. **Config A 必须复现 67.32%**:跟 msclip_ablation Config A 同样的 sanity check。如果 D2 改 identification.py 破坏了 default 行为,escalate。

2. **SIRIUS 稀疏谱图失败模式**(NM-001 已知):citric_acid 这种 CE=6V + 21 peaks 类型 SIRIUS 会自信给错 formula。本 session 用 sanity gate 降权,不直接踢候选。如果 sanity gate 触发率 >20%,在 §7 详细分析。

3. **CFM-ID negative-mode 准确率 ~20%**(spike test 已知)。Sub-6A v2 negative spectra 占 ~40%,CFM-ID 在这部分贡献小。在 per-mode breakdown 里展示这点。

4. **CFM-ID cache key 设计**:用 (canonical_smiles, adduct, ion_mode) 三元组作 key。不要只用 SMILES(同分子不同 adduct 预测谱不同)。

5. **SIRIUS 并行 worker**:可以开 4-8 worker(SIRIUS 是 CPU-bound,内存 ~2GB/worker)。但要小心 disk I/O 竞争。

6. **不要发明新 evidence_score 权重**:prompt §D4 已固定用 schemas 现有 0.4/0.3/0.2/0.1。SIRIUS 通过 sanity gate 介入,不进 weighted sum。

7. **peak_evidence JSON schema 必须固定**(D5 描述的)。下游 session 会基于这个 schema 写 LLM prompt 和 Layer F verifier。schema 一改,下游全废。

8. **不要做 verifier integration**:Layer F 的接入是另一个 session。本 session 只产出 peak_evidence 文件。

---

## Time budget

- Confirm: 30 分钟
- D1 reranker: 4 小时(代码 + test)
- D2 CLI 集成: 2 小时
- D3 sanity smoke: 30 分钟
- D4 4 configs: ~10 hours wall(主要 SIRIUS + CFM-ID 推理,可后台跑)
- D5 aggregator: 1 小时
- D6 报告: 1 小时
- D7: 15 分钟

**Total: 1.5-2 days**(代码 + smoke 一天,跑 4 configs 后台一夜,第二天写报告)。

---

## First action checklist

第一回合:
1. 读 8 个 background 文件
2. 报告 SIRIUS 单次调用 wall time(在 1 spectrum 上 smoke)
3. 报告 CFM-ID 单次调用 wall time + cache lookup logic
4. 报告 Layer F (`verifier/layers/peak_mechanistic.py`) 期望的 peak evidence 字段名(为 D5 schema 设计参考)
5. 估算 D4 4 个 config 的总 wall(基于 1+2+3 实测)
6. 确认 SIRIUS 和 CFM-ID 是 conda env / docker 隔离,不会跟 main env 冲突
7. 任何 clarifying question

不要写代码或跑命令,直到 confirm。
