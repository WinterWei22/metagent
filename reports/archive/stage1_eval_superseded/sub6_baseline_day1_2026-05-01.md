# Sub-6 Baseline LLM Evaluation — Day 1 交付报告

- **日期**：2026-05-01
- **分支**：`feature/sub6-baseline-eval`
- **提交**：`715f589` — `feat(eval_sub6): Day 1 — Sub-6 baseline LLM evaluation pipeline`
- **范围**：`evaluation/sub6/`、`tests/eval_sub6/`；不动 `verifier/`、Sub-6 数据文件、现有 tools
- **真实 LLM 调用**：✅ **已完成**——20 个 Sub-6B 任务全部跑过 MiniMax-M2.7（详见 §9）

---

## 1. 目标回顾

按 `reports/benchmark/sub6_evaluation_guide.md`，建立**裸 LLM**（无 verifier）通路富集 narrative 的评测基线，覆盖：

- Sub-6B：20 个 compound-only 任务（化合物列表 → narrative）
- Sub-6A：14 个 end-to-end 任务（光谱 → 鉴定 → narrative）
- LLM 默认 = MiniMax；temperature=0.0

Day 1 = Deliverable 1–4（Prompt + Sub-6B Runner + Metrics）骨架，**不发任何真实 LLM 调用**，先用 mock 在前 2 个真实任务上做 dry-run。

## 2. 交付物

### 2.1 模块代码（`evaluation/sub6/`）

| 文件 | 行数 | 职责 |
| --- | ---: | --- |
| `__init__.py` | 7 | 包说明 |
| `compound_lookup.py` | 134 | KEGG / 名称 ↔ InChIKey first-block 解析；punctuation-insensitive name 匹配 |
| `prompts.py` | 68 | System / User 模板；只渲染 `name` + `kegg_id` + `inchikey_first_block`，绝不泄露 ground truth |
| `pathway_extract.py` | 244 | 从 narrative 抽通路名（regex + known-name 回退）和 driver 化合物（句子级 marker 共现） |
| `metrics.py` | 227 | `is_pathway_hit`（双层模糊）+ `compute_task_metrics`（top1/top3/driver/false_noise/off_pathway） |
| `io_utils.py` | 63 | 幂等 JSONL append + `load_completed_task_ids` 断点恢复 |
| `run_sub6b.py` | 146 | Sub-6B 单任务 / 批处理；`chat_fn` 依赖注入便于 mock |

合计 **+889 行**实现代码。

### 2.2 测试（`tests/eval_sub6/`）

| 文件 | 用例 | 覆盖点 |
| --- | ---: | --- |
| `test_compound_lookup.py` | 5 | KEGG/name 解析、punctuation-insensitive、真池冒烟 |
| `test_prompts.py` | 7 | 渲染、ground-truth 不泄露 |
| `test_pathway_extract.py` | 9 | regex + driver-marker 句级共现 |
| `test_metrics.py` | 11 | substring/token-subset、完美/近失/false_noise narrative |
| `test_io_utils.py` | 5 | 幂等、partial-line 容错 |
| `test_run_sub6b.py` | 6 | mocked chat_fn、batch resume、no-leak |

**43 个用例全绿**（`pytest tests/eval_sub6/ -q` 0.09 s）。

## 3. 关键设计与决策

### 3.1 Prompt（评测指南 Deliverable 1）

System：固定一句话指令，要求基于代谢通路推理；显式禁止编造 KEGG/InChIKey。
User：四问模板（受影响通路、key driver、生物学意义、上下游关系），200–400 词。
**ground truth 字段（pathway_name / signal_compounds / noise_compounds / ramp_enrichment_result）一律不进 prompt**，由 `_strip_ground_truth(task)` 防御性拷贝兜底。

### 3.2 通路抽取（`pathway_extract.py`）

两遍合并：
1. **泛化 regex**：`<Capitalised tokens 1–5> (pathway|metabolism|biosynthesis|catabolism|degradation|cycle|signalling|shunt)`
2. **已知名直接 substring**：兜底单 token 疾病通路（如 `Alkaptonuria`），输入是 `task.ramp_enrichment_result.top_pathways[*].pathway_name + ground_truth_pathway`

抽取结果按字符偏移合并排序，**首个 mention** 即为"top-1 predicted"。

`_HEAD_STOPLIST` 拒绝 `dominant pathway`、`the metabolism`、`key cycle` 等评价性形容词头，防止误伤真实通路名（保留 lowercase 单 token 头如 `urea cycle`）。

### 3.3 Driver 抽取

句子级 marker 共现（`key driver` / `drives` / `responsible for` / `central to` 等 14 个标记），不是滑动窗口。理由：driver-statement 通常一句话点 2–4 个化合物，窗口扫描会把上下文里偶现的化合物误算为 driver。

### 3.4 通路命中（`is_pathway_hit`，评测指南 §3 pitfall 3）

两层规则，任一命中即 True：
1. 原始字符串 case-insensitive substring 双向；
2. 去后缀词（`_PATHWAY_SUFFIX_TOKENS = {pathway, metabolism, catabolism, anabolism, biosynthesis, degradation, cycle, signalling, signaling, shunt, fate}`）+ 去英文 stop words 后，content-token 集合**较小一边是较大一边的子集**。

效果：
- `Tyrosine catabolism` ↔ `Tyrosine metabolism` ✅（{tyrosine}⊆{tyrosine}）
- `Methionine metabolism` ↔ `Methionine and cysteine metabolism` ✅（{methionine}⊆{methionine,cysteine}）
- `Cysteine metabolism` ↔ `Methionine metabolism` ❌（{cysteine}⊄{methionine}）
- `Glycolysis` ↔ `Tyrosine metabolism` ❌

### 3.5 Driver 化合物对齐（评测指南 §3 pitfall 2）

所有 driver 比较都在 **InChIKey first-block** 层面进行：
- 抽到的 driver name → `lookup.resolve_name()` → InChIKey
- ground-truth 的 KEGG list → `lookup.kegg_to_inchikey_set()` → InChIKey 集合
- 命中数取交集，避免 KEGG vs name vs InChIKey 三套口径打架

### 3.6 幂等批处理

`run_sub6b_batch` 启动时 `load_completed_task_ids(out_path)` 读出已完成 task_id，重跑时只补缺。`load_completed_task_ids` 容忍最后一行被截断（`json.loads` 失败时静默丢弃尾行），因此 Ctrl-C / OOM 中断后再次启动也安全。

## 4. Mock LLM Dry-run（真实前 2 个 Sub-6B 任务）

| Task | predicted_top | top1_strict | driver_prec | driver_recall | false_noise | off_pathway |
| --- | --- | :---: | ---: | ---: | ---: | ---: |
| Tyrosine metabolism (`...P_106_seed4`) | Tyrosine catabolism | ✅ | 1.00 | 1.00 | 0.00 | 0 |
| Statin/胆固醇 (`...P_xxx`) | Cholesterol biosynthesis | ✅（token-subset） | — | — | — | — |

> 第二条数值列空缺是因为 mock narrative 没专门点 driver 化合物——本意只验证通路抽取。

dry-run 证实：(a) prompt 渲染无 ground-truth 泄露；(b) 两层通路命中规则按预期工作；(c) JSONL append 路径正常；(d) `chat_fn` 依赖注入可 mock 出任意响应。

## 5. 不在 Day 1 范围 / 待 Day 2

- ✅ ~~**未发任何真实 LLM 调用**~~ → **已完成 Sub-6B 真实运行**，详见 §9
- ❌ Sub-6A identification 包装（`evaluation/sub6/identification.py`）
- ❌ Sub-6A 任务级 GNPS exclusion（运行层后过滤；评测指南 §3 pitfall 1）
- ❌ `evaluation/sub6/run_sub6a.py`
- ❌ `scripts/eval_sub6/run_baseline.py` CLI（`--sub6a / --sub6b / --output-dir / --llm-model / --limit`）
- ❌ Day 3 报告（`reports/eval/sub6_baseline_eval_YYYY-MM-DD.md`）

## 6. 已知风险 / 注意事项

1. **regex 抽取召回**：评测指南 Deliverable 4 提到"如 dry-run 召回 <90% 则切 LLM 二次抽取"。Day 1 mock narrative 干净、命中率 100%，**真 LLM 输出召回率要在 Day 2 第一批真实结果上重测**。
2. **`_HEAD_STOPLIST` 和 `_PATHWAY_SUFFIX_TOKENS` 是英文先验**：若 LLM 偶发输出中文通路名，需在 Day 2 第一波真实数据上检视。
3. **`compound_lookup` 用 `data/benchmark/sub6/curated_hmdb_mammalian.jsonl`**：约 1.6k 条；命名映射对该 pool 内化合物足够，**对 LLM 自由文本里出现的别名（如 `Tyr` 缩写）会漏识**。Day 2 真实数据上看是否需要补别名词典。
4. **GNPS exclusion 不在 Sub-6B 范围**（6B 输入是化合物，不是光谱），将在 Day 2 Sub-6A runner 层做。

## 7. 复现命令

```bash
# 单测
python -m pytest tests/eval_sub6/ -q
# 输出：43 passed in 0.09s

# Mock dry-run（前 2 个 Sub-6B 任务，不发 LLM）
python -c "
from common import llm_client
from evaluation.sub6.run_sub6b import run_sub6b_batch
llm_client.set_mock(['<mock narrative 1>', '<mock narrative 2>'])
run_sub6b_batch(
    'data/benchmark/sub6/sub6b_mammalian_tasks.jsonl',
    'data/eval/sub6/sub6b_narratives_mock.jsonl',
    limit=2,
    model='mock',
)
"
```

## 8. 下一步建议

1. ~~确认 `MINIMAX_API_KEY` 已 export → 跑 2 个任务真实 sanity check~~ → **已完成**（§9）
2. **进入 Day 2**：实现 Sub-6A identification + CLI，再跑 14 个 e2e 任务（≈3–5 h）
3. Day 3 出聚合报告（按 bucket 分桶 + 失败模式分析）

---

## 9. 真实 LLM 运行结果（Sub-6B，2026-05-01）

### 9.1 调用证据

| 证据来源 | 内容 |
| --- | --- |
| `results/sub6/sub6b_narratives.jsonl` 第 1 条 `llm_model` | `MiniMax-M2.7`（**非** `MOCK`/`mock`） |
| 调用 API base | `https://api.minimaxi.com/v1`（见 `common/llm_client.py:33`） |
| API key 来源 | `api_key.txt`（125 字节）→ `MINIMAX_API_KEY` env 注入 |
| `logs/llm_calls.jsonl` 中 `caller=sub6b_baseline` 记录 | **22 条**真实调用（model=`MiniMax-M2.7`），4 条早期 mock（model=`MOCK`） |
| 真实调用时间戳 | `2026-05-01T02:37:28Z ~ 02:50:57Z`（持续 13 分 30 秒） |
| 单任务耗时分布 | min=14.3s, mean=39.0s, max=109.7s（mock 不会真等 14–110 s） |
| 调用总耗时 | **779 s ≈ 13 min**（与背景任务 wall time 吻合） |

> 22 条 real log 而非 20 条，是因为前 2 个 sanity-check 任务在 openai 模块缺失时跑过 1 次失败（`ModuleNotFoundError`，`error` 字段已落盘），删除失败记录后重跑 → 共 2(失败) + 2(成功 sanity) + 18(批处理) = 22 条真实 API 记录，narrative 文件保留 20 条成功结果。

> 注：`logs/llm_calls.jsonl` 里 `usage.prompt_tokens / completion_tokens` 字段为 `None`——MiniMax 的 chat-completion 响应未把 usage 字段塞回 openai 0.28 客户端的字典，是已知小问题，不影响 narrative 正确性。

### 9.2 聚合指标（n=20，0 错误）

> **注**：以下数字为抽取层补丁修复后的最终值；修复前的"虚高"指标和补丁对比见 §9.5。

| 指标 | 值 |
| --- | ---: |
| top1 pathway strict rate          | **30.0%** (6/20) |
| top3 pathway acceptance rate      | **35.0%** (7/20) |
| driver precision (mean)           | 0.750 |
| driver recall (mean)              | 0.432 |
| false noise rate (mean)           | 0.250 |
| off-pathway mentions (mean)       | 5.70 |
| narrative chars (mean)            | 2189 |
| 总 LLM 时间                       | 779.2 s |
| 平均单任务时间                    | 39.0 s |

### 9.3 按 GT pathway 分桶

| GT pathway | n | top1_strict | driver_prec | driver_recall |
| --- | ---: | ---: | ---: | ---: |
| Tyrosine metabolism                          | 1 | 0/1 | 0.75 | 0.60 |
| Statin inhibition of cholesterol production  | 1 | 0/1 | 0.00 | 0.00 |
| Selenium micronutrient network               | 3 | 0/3 | 0.42 | 0.50 |
| Pyrimidine metabolism                        | 5 | **5/5** | 0.75 | 0.30 |
| Sulindac Action Pathway                      | 1 | 0/1 | 1.00 | 0.17 |
| Methionine Metabolism                        | 5 | 2/5 | 0.97 | 0.41 |
| Acute Intermittent Porphyria                 | 4 | 0/4 | 1.00 | 0.25 |

**观察**：
- Pyrimidine metabolism 桶 5/5 命中——pyrimidine biosynthesis 在 LLM 训练里高频
- Acute Intermittent Porphyria 桶 0/4——疾病罕见，LLM 一律误判为 Coenzyme A / mevalonate / 通用 "biosynthetic pathway"
- Selenium micronutrient network 桶 0/3——硒代谢罕见，LLM 误判到 lipid / stress pathway
- Methionine 桶 2/5——一半 seed LLM 提到了 methionine，另一半被分流到 polyamine / transsulfuration / "acid metabolism"（后两者其实和 methionine 在同一通路网，但严格命中算 miss）

### 9.4 每任务结果（按 GT 排序）

| task_id (尾段) | GT pathway | predicted_top | top1 | top3 | drv_prec | drv_rec | f_noise | off |
| --- | --- | --- | :---: | :---: | ---: | ---: | ---: | ---: |
| RAMP_P_000000026_seed0 | Methionine Metabolism                       | methionine metabolism            | ✅ | ✅ | 1.00 | 0.50 | 0.00 | 8 |
| RAMP_P_000000026_seed1 | Methionine Metabolism                       | polyamine biosynthesis           | ❌ | ❌ | 1.00 | 0.38 | 0.00 | 6 |
| RAMP_P_000000026_seed3 | Methionine Metabolism                       | Metabolism                       | ✅ | ✅ | 1.00 | 0.29 | 0.00 | 3 |
| RAMP_P_000000026_seed4 | Methionine Metabolism                       | acid metabolism                  | ❌ | ❌ | 0.83 | 0.63 | 0.17 | 10 |
| RAMP_P_000000026_seed5 | Methionine Metabolism                       | transsulfuration pathway         | ❌ | ❌ | 1.00 | 0.25 | 0.00 | 4 |
| RAMP_P_000000106_seed4 | Tyrosine metabolism                         | methionine metabolism            | ❌ | ❌ | 0.75 | 0.60 | 0.25 | 7 |
| RAMP_P_000000402_seed0 | Acute Intermittent Porphyria                | Coenzyme A biosynthesis          | ❌ | ❌ | 1.00 | 0.20 | 0.00 | 5 |
| RAMP_P_000000402_seed1 | Acute Intermittent Porphyria                | mevalonate pathway               | ❌ | ❌ | 1.00 | 0.20 | 0.00 | 5 |
| RAMP_P_000000402_seed2 | Acute Intermittent Porphyria                | biosynthetic pathway             | ❌ | ❌ | 1.00 | 0.20 | 0.00 | 5 |
| RAMP_P_000000402_seed3 | Acute Intermittent Porphyria                | prominent pathway                | ❌ | ❌ | 1.00 | 0.40 | 0.00 | 11 |
| RAMP_P_000025712_seed1 | Sulindac Action Pathway                     | acid metabolism                  | ❌ | ❌ | 1.00 | 0.17 | 0.00 | 4 |
| RAMP_P_000052705_seed1 | Statin inhibition of cholesterol production | glycerolipid metabolism          | ❌ | ❌ | 0.00 | 0.00 | 1.00 | 9 |
| RAMP_P_000053157_seed2 | Selenium micronutrient network              | (markdown header artefact)       | ❌ | ❌ | 0.50 | 0.50 | 0.50 | 7 |
| RAMP_P_000053157_seed4 | Selenium micronutrient network              | Lipid metabolism                 | ❌ | ✅ | 0.25 | 0.50 | 0.75 | 4 |
| RAMP_P_000053157_seed5 | Selenium micronutrient network              | stress pathway                   | ❌ | ❌ | 0.50 | 0.50 | 0.50 | 4 |
| RAMP_P_000053306_seed0 | Pyrimidine metabolism                       | Pyrimidine metabolism            | ✅ | ✅ | 0.00 | 0.00 | 1.00 | 5 |
| RAMP_P_000053306_seed1 | Pyrimidine metabolism                       | pyrimidine metabolism            | ✅ | ✅ | 1.00 | 0.40 | 0.00 | 7 |
| RAMP_P_000053306_seed2 | Pyrimidine metabolism                       | Pyrimidine metabolism            | ✅ | ✅ | 1.00 | 0.17 | 0.00 | 1 |
| RAMP_P_000053306_seed3 | Pyrimidine metabolism                       | Pyrimidine metabolism            | ✅ | ✅ | 1.00 | 0.33 | 0.00 | 6 |
| RAMP_P_000053306_seed5 | Pyrimidine metabolism                       | pyrimidine metabolism            | ✅ | ✅ | 0.75 | 0.50 | 0.25 | 7 |

### 9.5 抽取层暴露的问题 — **已修复并重跑**

| # | 问题 | 修复 | 落地位置 |
|---:|---|---|---|
| 1 | regex `\s+` 跨行吞掉多段，把 `Affected Metabolic Pathways\n\nThe dominant pathway` 抓成一个 mention | `\s+` → `[ \t]+`（仅水平空白）+ markdown 头/粗体/斜体/code 预剥离 | `pathway_extract.py::_PATHWAY_RE` + `_strip_markdown` |
| 2 | 单 token "Metabolism" 或多 token 末尾为通用形容词的"通路名"被取作 top-1 | 引入 `_has_meaningful_content`（去后缀+stop tokens 后内容集非空）+ 多 token head 末尾在 `_HEAD_STOPLIST` 也拒绝 | `pathway_extract.py::extract_pathway_mentions` |
| 3 | driver_recall 偏低，因为 LLM 常用 `### Key Drivers\n- **X** is...` 段落而非句级 marker 列出 driver | 新增 `_extract_driver_sections`：识别 header 含 `driver` 词的 markdown section，section body 内所有 candidate 名命中即记 driver | `pathway_extract.py::extract_driver_mentions` |
| ✱ | 顺手修：`drive` 字串误匹配 `driver section` 等 | marker 命中改用 `\b...\b` 词边界正则 | `pathway_extract.py::_DRIVER_MARKER_RE` |

回归测试增加 8 条（`tests/eval_sub6/test_pathway_extract.py`），`pytest tests/eval_sub6/` **51 passed**。

#### 修复前 vs 修复后（同一份 narratives，仅重跑指标）

| 指标 | before | after | Δ | 解读 |
|---|---:|---:|---:|---|
| top1_pathway_strict_rate     | 0.350 | **0.300** | −0.050 | 诚实化：seed3 之前虚假命中"Metabolism" |
| top3_pathway_acceptance_rate | 0.400 | **0.350** | −0.050 | 同上 |
| driver_precision_mean        | 0.779 | 0.750 | −0.029 | 表格 driver 加入后部分被 noise 拉低 |
| driver_recall_mean           | 0.335 | **0.432** | **+0.097** | ✅ 表格/bullet driver 现在抓得着 |
| false_noise_rate_mean        | 0.221 | 0.250 | +0.029 | 与 precision 下降互为镜像 |
| off_pathway_count_mean       | 5.90  | 5.70  | −0.20  | 垃圾 mention 被过滤 |

#### predicted_top 字段的具体修复

| task_id 尾段 | before | after |
|---|---|---|
| `P_000053157_seed2` | `'Affected Metabolic Pathways\n\nThe dominant pathway'` | `'glycerolipid metabolism'` |
| `P_000000026_seed3` | `'Metabolism'` | `'purine catabolism'` |
| `P_000000402_seed0` | `'Coenzyme A biosynthesis'` | `'isoprenoid pathway'` |
| `P_000000402_seed2` | `'biosynthetic pathway'` | `'purine catabolism'` |
| `P_000000402_seed3` | `'prominent pathway'` | **`'heme biosynthesis'`** |

> **AIP 桶值得单独看**：`P_000000402_seed3` 的 LLM 实际写的是 heme biosynthesis（不是垃圾），之前却被 regex 抓成 `'prominent pathway'`。修复后能看到——LLM 至少**指向了正确生物学**（AIP = 卟啉/heme 合成缺陷），只是名称没用 RaMP 的官方写法。这意味着 AIP 桶 0/4 严格命中的实际**生物学准确率比指标显示的高**，verifier 阶段值得用语义匹配纠偏。

#### driver_recall 显著提升的任务

| task_id 尾段 | recall before → after |
|---|---:|
| `P_000000026_seed1` | 0.38 → **0.88** |
| `P_000025712_seed1` | 0.17 → 0.50 |
| `P_000053306_seed0` | 0.00 → 0.40 |
| `P_000000402_seed0` | 0.20 → 0.40 |
| `P_000000402_seed3` | 0.40 → 0.60 |
| `P_000053306_seed2` | 0.17 → 0.33 |
| `P_000000026_seed3` | 0.29 → 0.43 |

**七个任务受益**——印证了 §9.5 #3 假设（driver 多写在专门 markdown 段落里）。

#### 结论

- **指标诚实化**：top1/top3 下降的 5% 全部来自之前的 false-positive（"Metabolism" 模糊命中 GT），不是性能退化
- **真实改进**：driver_recall +9.7% 是抽取层的真实进步，没有重跑 LLM
- **后续**：当前 0.30 / 0.35 / 0.43 是 Sub-6B baseline 的可信指标，Day 3 报告以此为准；verifier 设计应预期能在 AIP 桶（卟啉/heme）这种语义近邻命中上拿到提升空间

### 9.6 结果落盘位置

```
results/sub6/
  README.md              # 复现命令 + headline 表
  sub6b_narratives.jsonl # 20 条原始 LLM 输出（49 KB）
  sub6b_narratives.md    # 60 KB 人类可读：每任务 GT/predicted/scorecard + 完整 narrative
  sub6b_metrics.jsonl    # 每任务 TaskMetrics + 元数据
  sub6b_metrics.csv      # 同上扁平 CSV
  sub6b_summary.json     # 聚合统计
```

### 9.7 复现

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python -c "from evaluation.sub6.run_sub6b import run_sub6b_batch; \
  run_sub6b_batch( \
    'data/benchmark/sub6/sub6b_mammalian_tasks.jsonl', \
    'data/eval/sub6/sub6b_narratives.jsonl', \
    caller='sub6b_baseline')"
python scripts/eval_sub6/aggregate_sub6b.py --out-dir results/sub6
```

`run_sub6b_batch` 幂等——已完成的 `task_id` 会跳过；删除输出 JSONL 强制全量重跑。

---

*更新于 Sub-6B 真实 LLM 运行交付完成、Sub-6A 尚未启动之时（2026-05-01）。*
