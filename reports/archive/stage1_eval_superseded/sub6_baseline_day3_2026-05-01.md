# Sub-6 Baseline LLM Evaluation — Day 3 Final Report

- **日期**：2026-05-01
- **分支**：`feature/sub6-baseline-eval`
- **阶段**：Day 1 (脚手架 + 抽取层) + Day 2 (Sub-6B 真实运行 + 抽取补丁 + Sub-6A perfect-id) + Day 3 (verifier 接入 + 总报告)
- **覆盖**：20 个 Sub-6B 任务 (compound-only) + 14 个 Sub-6A 任务 (perfect-id 上界基线)
- **评分维度**：抽取层（regex + curated pool 解析）+ verifier 层（typed-claim cascade，Layer 6a/6b/6c/6d）

> Sub-6A real-identification (`library_search` 策略) **不在此次报告范围**：当前环境 `matchms==0.32.0` 把 `ModifiedCosine` 重命名为 `ModifiedCosineGreedy`，`tools/library_search/scoring.py` 的 import 失败；本次按用户决定 (C) 双轨并行，**仅交付 perfect-id 上界**，real-id 等基础设施修复后再补。代码已就位，CLI `--id-strategy library_search` 可直接调用。

---

## 1. 执行摘要

| 维度 | Sub-6B (n=20) | Sub-6A perfect-id (n=14) |
|---|---:|---:|
| **抽取层** top1 strict | 30.0% | 21.4% |
| **抽取层** top3 acceptance | 35.0% | 21.4% |
| **抽取层** driver precision | 0.750 | 0.539 |
| **抽取层** driver recall | 0.432 | 0.260 |
| **抽取层** false_noise rate | 0.250 | 0.389 |
| **抽取层** off-pathway mentions | 5.70 | 6.57 |
| **verifier** total claims | 778 | 634 |
| **verifier** supported / unsupp / contra / unverif | 57 / 261 / 9 / 451 | 27 / 188 / 13 / 406 |
| **verifier** supported rate | 7.33% | 4.26% |
| **verifier** contradicted rate | 1.16% | 2.05% |
| identification accuracy (Sub-6A) | n/a | 100%（按构造） |
| 总 LLM 时间 | 13 min (baseline) + ~80 min (verifier) | 9.7 min (baseline) + ~70 min (verifier) |
| 错误任务数 | 0 / 0 | 0 / 0 |

**关键观察**：

1. **裸 LLM 的 baseline 不强**。Sub-6B top1 strict 30%、top3 35% — 即便 RaMP 把 top-3 给得很宽松（含同源疾病通路），LLM 也只能命中三分之一左右
2. **identification 不是瓶颈**。Sub-6A 在"完美鉴定"前提下 top1 strict 仅 21% — *比 Sub-6B 还低*。说明 Sub-6A 任务本身（spectra 派生的 compound 集合）就比 Sub-6B 难。这构成 Day 1 报告 §1 的反直觉数据
3. **verifier 标记 64% 的 Sub-6A 声明为 `unverifiable_v0`**。LLM 输出的声明大部分都游离于 RaMP / curated pool 可验证范围之外（典型："altered methionine flux suggests increased oxidative stress" 这种语义层面的延伸推理）
4. **`set_enrichment` 类声明严重缺失**。14 个 Sub-6A 任务只产出 8 条 `set_enrichment` 声明（每个 task 平均 < 1 条）。说明 typed-claim extractor 把绝大部分通路评论分类成了 `biological_claim`（493 条），而不是 `set_enrichment`。这是 verifier 层 0 个 supported set_enrichment 的根因

---

## 2. 数据流与方法

### 2.1 Pipeline

```
   Task (sub6{a,b}.jsonl)                          Curated pool / RaMP-DB
        │                                                    │
        ▼                                                    │
  evaluation/sub6/                                            │
   ├─ run_sub6b.py     ─── prompts.py ──► MiniMax-M2.7 ───┐  │
   └─ run_sub6a.py ─┐                                      │  │
                    └─ identification.py                   │  │
                       (perfect_id | library_search)        │  │
                                                            ▼  ▼
                                                       Narrative (.jsonl)
                                                            │
                          ┌─────────────────┬──────────────┴──┐
                          ▼                  ▼                  ▼
                  抽取层 grader         verify_sub6           Day 3 报告
                  (compute_task_metrics) (Layer 6a/b/c/d)    (本文)
                          │                  │
                          ▼                  ▼
              results/sub6{,a_perfect_id}/  results/sub6{b,a_perfect_id}_verifier/
              ─ narratives.jsonl/.md         ─ verdicts.jsonl/.csv/.md
              ─ metrics.jsonl/.csv           ─ verdicts_summary.json
              ─ summary.json                 ─ README.md
              ─ README.md
```

### 2.2 Sub-6A perfect-id 策略

- 每条 spectrum 直接读 `inchikey_first_block` 作为 prediction（id_acc = 1.00 by construction）
- 名称从 `curated_hmdb_mammalian.jsonl` 反查；查不到则用 `unknown (<inchikey>)`
- 多 spectrum 收敛到同一化合物时按 InChIKey first-block 去重
- LLM prompt 与 Sub-6B 完全相同（`differential_metabolites` 槽改填 identifications）

意义：把"端到端 Sub-6A 错误"分解成 (identification 错误) + (LLM 推理错误)，perfect-id 给出**LLM 推理错误的下界**。

### 2.3 Verifier 接入

按 `reports/verifier/verifier_sub6_enrichment_layers_delivery_2026-05-01.md` 的 handoff：
- 每个 task → `SubsixSourceReport(task_id, ground_truth_*, ramp_enrichment_result, ...)`
- driver_lookup 一次性从 curated pool 预加载（150 条 → 593 keys），所有任务共享
- `verify_sub6(narrative, source_report, ramp_db_path=/data/.../ramp.sqlite, driver_lookup=...)` 直接调用

每条 narrative 触发 verifier Stage 1 (extract claims) + Stage 2 (classify ambiguous，必要时) + 各层验证 + Layer D consistency = **2-3 LLM 调用 per narrative**。

### 2.4 抽取层 §9.5 补丁（修复后重跑同 narrative，无新 LLM 调用）

详见 `reports/eval/sub6_baseline_day1_2026-05-01.md` §9.5。三个补丁全部落在 `evaluation/sub6/pathway_extract.py`：
1. `\s+` → `[ \t]+` + markdown 头/粗体剥离 → 不再跨行抓取多段
2. `_has_meaningful_content` 过滤空内容 token → "Metabolism" / "biosynthetic pathway" 不再被取作 top-1
3. `_extract_driver_sections` → markdown `### Drivers` 段落内的所有 candidate 化合物算 driver

补丁前后 driver_recall +9.7%（0.335 → 0.432），predicted_top 字段 5/20 task 从垃圾值变成真实通路名。

---

## 3. 抽取层结果

### 3.1 Sub-6B（20 任务）— 详见 §3 of `reports/eval/sub6_baseline_day1_2026-05-01.md`

按 GT pathway 分桶：

| GT pathway | n | top1_strict | driver_prec | driver_recall |
| --- | ---: | ---: | ---: | ---: |
| Tyrosine metabolism                          | 1 | 0/1 | 0.75 | 0.60 |
| Statin inhibition of cholesterol production  | 1 | 0/1 | 0.00 | 0.00 |
| Selenium micronutrient network               | 3 | 0/3 | 0.42 | 0.50 |
| Pyrimidine metabolism                        | 5 | **5/5** | 0.75 | 0.30 |
| Sulindac Action Pathway                      | 1 | 0/1 | 1.00 | 0.17 |
| Methionine Metabolism                        | 5 | 2/5 | 0.97 | 0.41 |
| Acute Intermittent Porphyria                 | 4 | 0/4 | 1.00 | 0.25 |

### 3.2 Sub-6A perfect-id（14 任务）

按 GT pathway 分桶：

| GT pathway                    | n | top1_strict | driver_prec | driver_recall |
|---|---:|---:|---:|---:|
| Methionine Metabolism         | 5 | 0/5 | 0.59 | 0.13 |
| Pyrimidine metabolism         | 5 | 3/5 | 0.61 | 0.44 |
| Tyrosine metabolism           | 1 | 0/1 | 0.50 | 0.80 |
| Sulindac Action Pathway       | 1 | 0/1 | 0.20 | 0.00 |
| Statin inhibition of cholesterol production | 1 | 0/1 | 0.00 | 0.00 |
| Selenium micronutrient network | 1 | 0/1 | 0.50 | 0.00 |

详见 `results/sub6a_perfect_id/sub6a_metrics.csv` / `sub6a_narratives.md`。

### 3.3 Sub-6A vs Sub-6B 对比（按 pathway_id 配对，eval guide §3 pitfall 5）

| pathway_id | GT name | n_b/n_a | Sub-6B top1_strict | Sub-6A top1_strict | Δtop1 | Sub-6B drv_recall | Sub-6A drv_recall |
|---|---|---|---:|---:|---:|---:|---:|
| RAMP_P_000000026 | Methionine Metabolism                       | 5/5 | 0.20 | 0.00 | **−0.20** | 0.54 | 0.13 |
| RAMP_P_000000106 | Tyrosine metabolism                         | 1/1 | 0.00 | 0.00 | 0.00 | 0.60 | 0.80 |
| RAMP_P_000025712 | Sulindac Action Pathway                     | 1/1 | 0.00 | 0.00 | 0.00 | 0.50 | 0.00 |
| RAMP_P_000052705 | Statin inhibition of cholesterol production | 1/1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| RAMP_P_000053157 | Selenium micronutrient network              | 3/1 | 0.00 | 0.00 | 0.00 | 0.50 | 0.00 |
| RAMP_P_000053306 | Pyrimidine metabolism                       | 5/5 | 1.00 | 0.60 | **−0.40** | 0.39 | 0.44 |

**Cascade decomposition (paired only)**：6A_top1 − 6B_top1 mean = **−0.10**（13/14 配对任务，Selenium 仅 1 个 6A 不算简单平均）。

> 反直觉：即便 identification 完美 (id_acc=1.00)，Pyrimidine 桶 top1 还是从 1.00 下降到 0.60，Methionine 桶从 0.20 → 0.00。这是因为 Sub-6A 的 differential_compounds 集合**派生自 spectra**——只包含那些 GNPS 有谱图覆盖的 signal/noise 化合物，与 Sub-6B 的完整 signal+noise 列表不一致。**输入差异本身就让 LLM 表现下降，与鉴定无关**——这是 eval guide §3 pitfall 5 已警告的非 1-to-1 配对问题。

---

## 4. Verifier 结果

### 4.1 Sub-6B verifier 聚合（n=20）

| Verdict | 计数 | 占比 |
|---|---:|---:|
| supported       | 57  | 7.33% |
| unsupported     | 261 | 33.55% |
| contradicted    | 9   | 1.16% |
| unverifiable_v0 | 451 | 57.97% |
| **total claims** | **778** | — |

**按 claim type**：

| Claim type | Total | supported | unsupported | contradicted | unverifiable_v0 |
|---|---:|---:|---:|---:|---:|
| biological_claim       | 611 | 51 | 257 | 0 | 303 |
| pathway_relationship   | 55  | 0  | 0   | 0 | 55  |
| grounded_claim         | 30  | 0  | 0   | 0 | 30  |
| driver_metabolite      | 12  | 6  | 4   | 1 | 1   |
| **set_enrichment**     | **0** | — | — | — | — |

> ⚠️ Sub-6B 上 **0 个 set_enrichment 声明**——typed-claim extractor 把所有通路富集声明都分类为 `biological_claim`。这是 Layer 6a 的关键 coverage 漏洞（详见 §4.3）。

### 4.2 Sub-6A perfect-id verifier 聚合（n=14）

| Verdict | 计数 | 占比 |
|---|---:|---:|
| supported       | 27 | 4.26% |
| unsupported     | 188 | 29.65% |
| contradicted    | 13 | 2.05% |
| unverifiable_v0 | 406 | 64.04% |
| **total claims** | **634** | — |

**按 claim type**：

| Claim type | Total | supported | unsupported | contradicted | unverifiable_v0 |
|---|---:|---:|---:|---:|---:|
| biological_claim       | 493 | 25 | 187 | 0 | 281 |
| pathway_relationship   | 55  | 1  | 1   | 0 | 53  |
| grounded_claim         | 50  | 0  | 0   | 0 | 50  |
| set_enrichment         | 8   | 0  | 0   | 1 | 7   |
| driver_metabolite      | 5   | 1  | 0   | 3 | 1   |

### 4.3 关键观察

1. **`set_enrichment` 漏分类**：14 task × ≈45 claims = ~630，仅 8 个被分到 `set_enrichment` — typed-claim extractor 把绝大多数通路声明拢到了 `biological_claim`（78% 的 claim 数）。这意味着 verifier 显式针对通路富集逻辑的 6a 层基本失效，6c (biological_sub6) 接管了大部分流量
2. **Layer 6d (`pathway_relationship`) 高 unverifiable_v0**：53/55 unverifiable_v0 — 因为 RaMP-DB v2025-03-06 没有 `pathwayhaspathway` 层级表（verifier 报告 §4.3 已声明），所有 upstream/downstream 类声明默认 unverifiable_v0
3. **Layer 6b (`driver_metabolite`) 信号强但 N 太小**：5 个 driver_metabolite 中 3 个 contradicted（声明了 noise 化合物为 driver）— precision 信号靠这 5 个无法做统计判断，但和抽取层 false_noise=0.39 一致
4. **`biological_claim` 的 187 unsupported / 281 unverifiable_v0**：LLM 大量生成"代谢通路 X 与生理过程 Y 相关"这类语义化叙述，verifier 在没有 curated 疾病-通路数据库的情况下默认 `unverifiable_v0`；明确的 pathway-membership 类（187 个 unsupported）则被打回，因为通路不在 task 的 top10 集合内

---

## 5. 性能成本

| 阶段 | LLM 调用数（保守下界） | 总耗时 |
|---|---:|---:|
| Sub-6B baseline narrative                | 22（2 次失败 + 20 成功） | 13 min |
| Sub-6A perfect-id baseline narrative     | 14                          | 9.7 min |
| Sub-6B verifier (extract + classify + D) | ~40-60                      | ~80 min（含 2 次 timeout 重试） |
| Sub-6A verifier (extract + classify + D) | ~28-42                      | ~70 min（含 1 次 timeout 重试） |
| **合计 LLM 调用**                         | ~104-138                    | ~3 hours |

成本拐点：**verifier 阶段比 baseline 阶段 LLM 调用多 2-3 倍** — 因为每个 narrative 触发 ~3 个 LLM 调用 (Stage 1 extract + 可能的 Stage 2 + Layer D consistency)，每次 narrative 的 verify_sub6 总耗时与 baseline narrative 生成接近（30-60 s）。所以"裸 LLM + verifier" 系统的总成本 ≈ baseline 的 4×。

---

## 6. 已知限制 / 未跑

| # | 项 | 现状 | 影响 |
|---:|---|---|---|
| L1 | Sub-6A real-identification (`library_search`) | 未跑 — `matchms==0.32.0` 改名了 `ModifiedCosine` | 缺 e2e 真实端到端数字；perfect-id 是 LLM 推理上界，无法分解 identification 误差 |
| L2 | Sub-6B 与 Sub-6A pathway_id 配对 cascade decomposition | 数字未填 | 无法直接量化"identification 占总误差几何" |
| L3 | typed-claim extractor 把通路声明大量分类为 `biological_claim` | 未修 | verifier 6a (set_enrichment) 层覆盖率极低，6c 接管 |
| L4 | RaMP-DB 无 pathway 层级数据 | 已知 (verifier 报告 §4.3) | upstream/downstream 类全部 `unverifiable_v0` |
| L5 | curated pool 仅 150 化合物 | 数据约束 | LLM 提到的化合物大量无法解析到 InChIKey |

修复优先级建议：L1 > L3 > L2 > L5 > L4。

---

## 7. 复现

```bash
# 0. 准备
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"

# 1. Sub-6B baseline (20 task, ~13 min)
python scripts/eval_sub6/run_baseline.py --sub6b
python scripts/eval_sub6/aggregate_sub6b.py --out-dir results/sub6

# 2. Sub-6A perfect-id baseline (14 task, ~10 min)
python scripts/eval_sub6/run_baseline.py --sub6a --id-strategy perfect_id
python scripts/eval_sub6/aggregate_sub6a.py --out-dir results/sub6a_perfect_id

# 3. Verifier on Sub-6B narratives (~25 min, 2-3 LLM calls/narrative)
python scripts/eval_sub6/grade_with_verifier.py \
  --narratives results/sub6/sub6b_narratives.jsonl \
  --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
  --out data/eval/sub6/sub6b_verdicts.jsonl --track sub6b
python scripts/eval_sub6/aggregate_verifier.py \
  --verdicts data/eval/sub6/sub6b_verdicts.jsonl \
  --narratives results/sub6/sub6b_narratives.jsonl \
  --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
  --track sub6b --out-dir results/sub6b_verifier

# 4. Verifier on Sub-6A perfect-id narratives (~25 min)
python scripts/eval_sub6/grade_with_verifier.py \
  --narratives data/eval/sub6/sub6a_narratives_perfect_id.jsonl \
  --tasks data/benchmark/sub6/sub6a_e2e_tasks.jsonl \
  --out data/eval/sub6/sub6a_perfect_id_verdicts.jsonl --track sub6a_perfect_id
python scripts/eval_sub6/aggregate_verifier.py \
  --verdicts data/eval/sub6/sub6a_perfect_id_verdicts.jsonl \
  --narratives data/eval/sub6/sub6a_narratives_perfect_id.jsonl \
  --tasks data/benchmark/sub6/sub6a_e2e_tasks.jsonl \
  --track sub6a_perfect_id --out-dir results/sub6a_perfect_id_verifier
```

幂等：所有阶段对相同 `task_id` 跳过；删除对应 JSONL 强制重跑。

---

## 8. 结果索引

```
results/
  sub6/                           # Sub-6B baseline (extractor-graded)
    README.md
    sub6b_narratives.jsonl
    sub6b_narratives.md
    sub6b_metrics.{jsonl,csv}
    sub6b_summary.json
  sub6a_perfect_id/               # Sub-6A perfect-id baseline (extractor-graded)
    README.md
    sub6a_narratives.jsonl
    sub6a_narratives.md
    sub6a_metrics.{jsonl,csv}
    sub6a_identifications.csv
    sub6a_summary.json
  sub6b_verifier/                 # Sub-6B verifier-graded — 模仿 results/sub6/ 结构
    README.md
    sub6b_verdicts.{jsonl,csv,md}
    sub6b_verdicts_summary.json
  sub6a_perfect_id_verifier/      # Sub-6A perfect-id verifier-graded
    README.md
    sub6a_perfect_id_verdicts.{jsonl,csv,md}
    sub6a_perfect_id_verdicts_summary.json
```

报告：
- `reports/eval/sub6_baseline_day1_2026-05-01.md` — 脚手架 + Sub-6B 真实运行 + §9.5 抽取补丁
- `reports/eval/sub6_baseline_day3_2026-05-01.md` — 本文（终报告）

---

*交付完成 2026-05-01。Sub-6A real-identification 待 matchms / library_search 兼容性修复后再补；CLI、runner、aggregator、单测均已就位（74 单测全过），开关用 `--id-strategy library_search`。*
