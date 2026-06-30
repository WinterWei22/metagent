# Verifier Typed Claim Stage 2 Delivery Report

日期：2026-04-28

## 1. 本次交付范围

本次 PR 在已完成的 typed claim / claim table / claim metrics 第一阶段基础上，继续完成第二阶段实验闭环：

- 新增 `candidate_ref` 解析，将 claim 可靠绑定到 `IdentificationReport.candidates[i]`。
- 将 typed fields 接入 `grounded` / `factual` / `peak_mechanistic` 三个 verifier layer。
- 新增 auditable `verification_confidence`，由 claim-level metrics 计算。
- 新增最小实验脚本，生成 `reports/verifier_confidence_experiment.csv`。
- 保留现有 verifier 主流程、rewrite 流程和 LLM call 数，不改变旧 verdict 行为。

## 2. CandidateRef 解析

新增 `verifier/candidate_resolution.py`，入口：

```python
resolve_candidate_ref(claim, source_report) -> CandidateRef | None
```

解析顺序按保守优先级执行：

1. `candidate.candidate.name` exact / normalized match
2. `metabolite_info.primary_name` exact / normalized match
3. `metabolite_info.synonyms` exact / normalized match
4. `candidate.candidate.smiles` / `metabolite_info.smiles` exact match
5. `metabolite_info.inchikey` 或 `cross_refs["inchikey"]`
6. HMDB / KEGG / PubChem CID / ChEBI 等 database id
7. `rank N`、`top candidate`、`highest-scoring candidate`
8. subject 不明确时不 fallback top-1

`verifier/agent.py` 在 claim classification 后、进入 layer verification 前解析并写入 `ClassifiedClaim.candidate_ref`。

## 3. Typed Fields 接入 Verifier Layers

### grounded.py

优先消费：

- `extracted_fields.formula`
- `extracted_fields.precursor_mz`
- `extracted_fields.neutral_mass`
- `extracted_fields.adduct`
- `extracted_fields.score_name`
- `extracted_fields.score_value`
- `extracted_fields.rank`
- `candidate_ref`

新增能力：

- formula claim 不再必须依赖文本 regex 命中。
- score claim 可根据 `score_name` 映射到 `evidence_score`、`candidate.score`、`predicted_spectrum_cosine`。
- rank claim 可用 `candidate_ref.index` 与 report 排序验证。
- `VerifiedClaim` 透传 `claim_id`、`claim_subtype`、`candidate_ref`、`extracted_fields`、`verifier_layer="grounded"`、`evidence_refs`、`trace_summary`。

### factual.py

优先消费：

- `candidate_ref.smiles`
- `candidate_ref.inchikey`
- `extracted_fields.database_name`
- `extracted_fields.database_id`
- `extracted_fields.formula`
- `extracted_fields.smiles`
- `extracted_fields.inchikey`

新增能力：

- chemical taxonomy claim 优先使用 `candidate_ref.smiles` 调 ClassyFire。
- database ID claim 优先使用 typed database fields。
- ClassyFire 路径写入 `tool_called="classyfire"`。
- metabolite info roundtrip 写入 `tool_called="metabolite_info"`。

### peak_mechanistic.py

优先消费：

- `extracted_fields.mz`
- `extracted_fields.neutral_loss`
- `extracted_fields.fragment_formula`
- `candidate_ref.smiles`

新增能力：

- peak m/z 不再只依赖 `claim.peak_mz`。
- neutral loss 不再只依赖 `claim.neutral_loss`。
- 输出透传 typed fields、candidate_ref、`verifier_layer="peak_mechanistic"`、`tool_called="sirius"`。

## 4. Auditable Confidence

`ClaimMetrics` 新增：

```python
verification_confidence: float | None
confidence_components: dict[str, float]
```

计算公式：

```text
verification_confidence =
  0.45 * claim_precision
+ 0.25 * supported_ratio
+ 0.20 * (1 - contradiction_rate)
+ 0.10 * (1 - unverifiable_rate)
```

行为：

- 空 claims：`verification_confidence = None`
- 全 supported：`verification_confidence = 1.0`
- 全 unverifiable：低 confidence，而不是误判高置信
- 输出 clamp 到 `[0, 1]`

## 5. 最小实验

新增脚本：

```bash
python scripts/experiments/run_verifier_confidence_experiment.py
```

脚本自动发现：

- `reports/` 下的 verifier sidecar / report json
- `/tmp/` 下最近的 verifier sidecar / report json
- 没有真实文件时构造 synthetic smoke rows

输出 CSV：

```text
reports/verifier_confidence_experiment.csv
```

本次运行结果：

```text
n cases: 4
n with llm_self_confidence: 0
n with verification_confidence: 4
Pearson/Spearman: insufficient numeric correctness_proxy
average verification_confidence by correctness_proxy:
  unknown: 0.583956 (n=4)
```

当前发现的真实 sidecar 没有显式 LLM self-confidence，paired caffeine report 的 top candidate 缺少 name / primary_name，因此 correctness proxy 保守填 `unknown`，不伪造 ground truth。

## 6. 测试结果

运行命令：

```bash
conda run -n metagent-llm python -m pytest tests/test_verifier/ -q
conda run -n metagent-llm python scripts/experiments/run_verifier_confidence_experiment.py
```

结果：

```text
180 passed in 0.48s
CSV written to reports/verifier_confidence_experiment.csv
```

## 7. 已知局限

- `candidate_ref` 解析仍是保守规则，不做模糊 top-1 fallback，避免错误绑定。
- 短 SMILES 仅用于 exact candidate match，不作为通用化学解析器。
- 当前真实 sidecar 缺少 LLM self confidence，暂时无法直接比较 self confidence 与 verifier confidence。
- 当前 report 缺少可靠 ground-truth metadata，correctness proxy 只能保守输出 `unknown`。
- SIRIUS 在 sparse spectra 上仍可能返回 `UNVERIFIABLE_V0`，这是数据质量限制，不是 verifier crash。

## 8. 下一步建议

1. 在 orchestrator 输出中标准化 `self_confidence` 字段，避免只能从文本 regex 抽取。
2. 为 fixture/report 增加 ground-truth candidate name 或 truth table。
3. 在 UI evidence panel 中展示 `claim_tables[*].rows`，以 claim_id 为主键展示 evidence_refs、tool_called、trace_summary。
4. 为论文实验增加固定 fixture set，报告 self confidence、verification confidence、correctness 的相关性。
5. 后续再扩展 typed extraction，不在 verifier layer 内继续增加 fragile string matching。
