# Session 2026-06-25 — Second-Pass Prompt Fix + Semantic Matcher Fix

## 背景

接上一个 session，问题是：v4 filtered benchmark（342 tasks）基线分数偏低：
- sub6: 61.90% primary semantic
- hmdb_ramp: 43.43% primary semantic
- human1: 12.07%，recon22: 14.06%

当时已经完成 InChIKey xref pipeline，能把 name/SMILES/InChIKey 解析到 KEGG/HMDB ID。
这个 session 找到了两个根因并分别修复，同时确认 human1/recon22 不做。

---

## 根因分析

### 根因 1：second-pass prompt 锚定 claims[] 排名，不看 narrative

`concord/agent/pathway_prediction.py` 里的 `generate_pathway_prediction_second_pass()` 是
在主 ReAct narrative 生成后独立运行的一次 LLM call，负责输出 `pathway_prediction` JSON。

旧 prompt：「从 claims[] 的证据里选最可能的 primary pathway」
→ LLM 按 claims 里的 p-value 排名选，与 narrative 的结论脱节
→ MetaboAnalystR 返回裸 ID（hsa00020），LLM 把它直接放进 `pathway_name` 字段

修复：`SECOND_PASS_SYSTEM_PROMPT` 加两条规则：
1. **SELECTION RULE**：先读 narrative_text，找 narrative 明确指出的主要通路，再从 claims[] 里查对应的 pathway_id 和 pathway_name 字符串。claims[] 的排名不能覆盖 narrative 的结论。
2. **FORMATTING RULE**：pathway_name 必须是人类可读名字，绝不能是裸数据库 ID（hsa00020 / KEGG:map00020 / REACT:R-HSA-xxx），这些 ID 只能放 pathway_id 字段。

commit: `937df54` `fix(second-pass): narrative-first selection + bare-ID formatting rule`

### 根因 2：semantic matcher 串行 fallback，且无 stemming

`concord/lookup/pathway_name_matcher.py` 原逻辑：
- embedding 得分 < 0.80 → 直接返回 False，不跑 token overlap
- "fatty acid" ≠ "fatty acids"（复数），token overlap 匹配失败

问题：「更具体的子通路」应该算正确答案。
例如："Saturated fatty acids beta-oxidation" 是 "Fatty acid Metabolism" 的子通路，
逻辑上预测对了，但 embedding cosine ≈ 0.72，旧 matcher 判 False。

修复（commit `22aa9bc`）：
1. **并行 OR 逻辑**：token overlap 和 embedding 同时跑，任一 hit → 结果为 True
2. **Stemming**：`_stem()` 剥离 -s / -es / -ing 后缀，"acids"→"acid"，"oxidations"→"oxidation"
3. `is_hit()` 简化为 `any(self.match(q, c).hit for c in candidates)`

---

## 修改的文件

| 文件 | 改动 | commit |
|---|---|---|
| `concord/agent/pathway_prediction.py` | `SECOND_PASS_SYSTEM_PROMPT` 加 SELECTION RULE + FORMATTING RULE | 937df54 |
| `concord/lookup/pathway_name_matcher.py` | 并行 OR + stemming + is_hit 简化 | 22aa9bc |
| `scripts/metagent/v4_bench_eval.py` | skip-done 逻辑 + `--strata` 多值参数 | 未提交（working tree） |

### v4_bench_eval.py 具体改动（未 commit，下个 session 需确认是否提交）

1. `_run_one` 函数开头加 skip-done：若 `status_dir/{tid}.json` 已存在，直接返回，不重跑
2. `--strata` 参数（`nargs="+"`, choices 同 `--stratum`）：支持同时跑多个 stratum，如 `--strata sub6 hmdb_ramp`

---

## 已知科学结论：human1 / recon22 不做

**根因**：GEM（基因组尺度代谢网络）的机制模拟产生的是「被扰动通路的下游因果后果」，
而不是「该通路的成员代谢物」。

例：扰动 Pentose Phosphate Pathway → FBA 计算后差异代谢物全是 GTP/ADP/FAD/NAD+（核苷酸池）
→ 这些代谢物不是 KEGG PPP 成员，ORA/Mummichog 正确报 "Purine metabolism"，但 GT 是 PPP
→ 任何 membership-based 富集范式原理上都会系统失败

此外 62/102 human1 通路（"Acyl-CoA hydrolysis" 等）在任何外部数据库不存在。

**处置**：human1/recon22 从 headline 指标移出，单列并标注 "beyond enrichment paradigm scope"，
作为 Discussion limitation。不开额外工程工作。

---

## 当前 benchmark 跑步状态

进行中的 run（截至 session 结束时）：

- **out-dir**: `data/metagent/v4_bench_eval_sub6hmdb_secondpass_20260624/`
- **benchmark**: `data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_filtered.jsonl`
- **strata**: sub6 + hmdb_ramp（共 162 tasks，跳过 human1/recon22）
- **LLM log**: `logs/concord/v4_bench_sub6hmdb_secondpass_20260624.jsonl`
- **进度**：sub6=63/63 ✅，hmdb_ramp=72/99（被 kill，待续跑）
- **k=10, max-react-turns=8, max-feedback-iters=1**

### 续跑命令

```bash
PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/v4_bench_sub6hmdb_secondpass_20260624.jsonl \
python3 scripts/metagent/v4_bench_eval.py \
    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_filtered.jsonl \
    --strata sub6 hmdb_ramp \
    --out data/metagent/v4_bench_eval_sub6hmdb_secondpass_20260624 \
    --k 10 \
    --max-react-turns 8 \
    --max-feedback-iters 1
```

skip-done 逻辑会自动跳过已完成的 135 个，只跑剩余 27 个 hmdb_ramp。

### 跑完后评分命令

```bash
PYTHONPATH=. python3 scripts/metagent/full344_pathway_scorecard.py \
    --out-dir data/metagent/v4_bench_eval_sub6hmdb_secondpass_20260624 \
    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_filtered.jsonl \
    --relevant-sidecar data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json \
    --gold-sidecar data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json \
    --ramp /data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
    --report reports/reports_v3/2026-06-25_v4bench_secondpass_final.md
```

---

## 已知数字（partial，135/162 完成时）

| stratum | tasks | 原始 baseline | matcher-only（同数据重评） | 本次（新 prompt + 新 matcher） |
|---|---:|---:|---:|---:|
| sub6 primary semantic | 63 | 61.90% | 63.49% | **65.08%** |
| sub6 top-k semantic | 63 | 80.95% | 80.95% | **85.71%** |
| hmdb_ramp primary semantic | 18* | 43.43% | 47.47% | **83.33%*** |

\* hmdb_ramp 只有前 18 个（样本小，偏乐观）。全量 99 个跑完才算数。

sub6 提升温和（+3pp primary）：因为 sub6 narrative 原本就比较一致，second-pass 收益有限。
hmdb_ramp 前 18 个大幅跳升（43% → 83%）：这才是 second-pass prompt fix 的主要价值，
hmdb_ramp 任务的 narrative 和 claims[] 排名冲突更多，新 SELECTION RULE 效果明显。

---

## 下一步（下个 session 直接接手）

1. **续跑** hmdb_ramp 剩余 27 个（用上面续跑命令，会自动 skip done）
2. **跑全量 scorecard**（用上面评分命令）
3. **确认** hmdb_ramp 是否稳在 75-85% 区间
4. **可选**：提交 `v4_bench_eval.py` 的 skip-done + `--strata` 改动
5. **可选**：如果 hmdb_ramp 全量结果低于预期，做 failure case 诊断

---

## 本 session 未动的部分

- verifier UV 指标（W14 baseline 44.25%）：本 session 没碰，UV 系列工作在 `metagent-v2` branch
- human1/recon22 GEM crosswalk：明确决定不做
- driver recall（当前 23%）：已知问题，不是本 session 目标
- `v4_bench_eval.py` 的改动没 commit，下个 session 可以 `git diff` 确认后决定是否提交
