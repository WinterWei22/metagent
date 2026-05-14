请基于当前已经实现的 typed claim / claim table / claim_metrics，继续完成第二阶段实验闭环：candidate_ref 解析、typed fields 接入 verifier layers、auditable confidence，并跑最小实验。

目标：
验证 verifier-derived confidence 是否比 LLM self confidence 更可信，并为后续论文实验打基础。

请严格按 staged PR 思路执行，不要大重构，不要改变现有 verifier 主流程和 LLM call 数。

---

## 任务 1：实现 candidate_ref 解析

新增文件：

verifier/candidate_resolution.py

实现函数：

resolve_candidate_ref(
    claim: ExtractedClaim | ClassifiedClaim | VerifiedClaim,
    source_report: IdentificationReport,
) -> CandidateRef | None

匹配顺序：

1. candidate.candidate.name exact / normalized match
2. metabolite_info.primary_name exact / normalized match
3. metabolite_info.synonyms exact / normalized match
4. candidate.candidate.smiles match
5. metabolite_info.inchikey 或 cross_refs 中的 InChIKey match
6. database id match，例如 HMDB / KEGG / PubChem CID / ChEBI
7. rank match，例如 “top candidate”, “rank 1”, “highest-scoring candidate”
8. 如果 claim subject 不明确，不要默认返回 top-1，避免错误绑定

CandidateRef 至少填充：

- index
- path: candidates[{i}]
- name
- smiles
- inchikey
- source_id
- match_method

接入点：

- 在 verifier/agent.py 中，classification 后、进入 layer verification 前，对每个 ClassifiedClaim 调用 resolve_candidate_ref，并写入 claim.candidate_ref。
- 如果无法解析，保持 None，不要报错。

新增测试：

tests/test_verifier/test_candidate_resolution.py

覆盖：

- name 匹配
- primary_name 匹配
- synonym 匹配
- smiles 匹配
- database id 匹配
- rank/top candidate 匹配
- ambiguous subject 不 fallback top-1
- candidate.name=None 时仍能通过 metabolite_info 或 smiles 解析

---

## 任务 2：让 typed fields 真正进入 verifier layers

请优先修改这三个 layer：

- verifier/layers/grounded.py
- verifier/layers/factual.py
- verifier/layers/peak_mechanistic.py

原则：

- 不删除旧 regex 逻辑
- 优先使用 claim.extracted_fields / claim.candidate_ref
- typed field 缺失时 fallback 到旧文本解析
- verdict 行为尽量保持兼容

### grounded.py

优先消费：

- extracted_fields.formula
- extracted_fields.precursor_mz
- extracted_fields.neutral_mass
- extracted_fields.adduct
- extracted_fields.score_name
- extracted_fields.score_value
- extracted_fields.rank
- candidate_ref

要求：

- formula claim 不再只依赖文本 regex。
- score claim 能根据 score_name 匹配 evidence_score / candidate.score / predicted_spectrum_cosine。
- rank claim 能用 candidate_ref.index + report.candidates 顺序验证。
- 返回 VerifiedClaim 时透传：
  - claim_id
  - claim_subtype
  - subject
  - candidate_ref
  - extracted_fields
  - verifier_layer="grounded"
  - evidence_refs
  - trace_summary

### factual.py

优先消费：

- candidate_ref.smiles
- candidate_ref.inchikey
- extracted_fields.database_name
- extracted_fields.database_id
- extracted_fields.formula
- extracted_fields.smiles
- extracted_fields.inchikey

要求：

- chemical taxonomy claim 优先通过 candidate_ref.smiles 调用 ClassyFire。
- database ID claim 优先用 extracted_fields.database_id。
- 返回 VerifiedClaim 时透传 typed fields 和 verifier_layer="factual"。
- tool_called 对 ClassyFire 填 "classyfire"，对 metabolite info roundtrip 填 "metabolite_info"。

### peak_mechanistic.py

优先消费：

- extracted_fields.mz
- extracted_fields.neutral_loss
- extracted_fields.fragment_formula
- candidate_ref.smiles

要求：

- peak m/z 不再只依赖 claim.peak_mz。
- neutral loss 不再只依赖 claim.neutral_loss。
- 如果 candidate_ref 有 smiles，优先用于 SIRIUS 输入。
- 返回 VerifiedClaim 时透传 typed fields、candidate_ref、verifier_layer="peak_mechanistic"、tool_called="sirius"。

新增或更新测试：

- typed formula claim 被 grounded layer 正确验证
- typed score claim 被 grounded layer 正确验证
- candidate_ref rank claim 被 grounded layer 正确验证
- chemical taxonomy claim 使用 candidate_ref.smiles
- peak claim 使用 extracted_fields.mz / neutral_loss
- typed fields 缺失时旧逻辑仍通过

---

## 任务 3：实现 auditable confidence

在 verifier/metrics.py 中新增：

compute_verification_confidence(metrics: ClaimMetrics) -> float | None

第一版公式：

verification_confidence =
  0.45 * claim_precision
+ 0.25 * supported_ratio
+ 0.20 * (1 - contradiction_rate)
+ 0.10 * (1 - unverifiable_rate)

要求：

- 如果核心分母为 0，返回 None。
- 输出范围 clamp 到 [0, 1]。
- 在 ClaimMetrics schema 中新增：
  - verification_confidence: float | None
  - confidence_components: dict[str, float]

在 compute_claim_metrics() 中填充。

confidence_components 至少包括：

- claim_precision
- supported_ratio
- contradiction_rate
- unverifiable_rate

新增测试：

- 全 supported → confidence 接近 1
- 有 contradiction → confidence 降低
- 全 unverifiable → confidence 较低
- 空 claims → confidence None

---

## 任务 4：跑最小实验

新增脚本：

scripts/experiments/run_verifier_confidence_experiment.py

目标：
在已有 fixture / report / sidecar 上评估：

- LLM self confidence
- verifier-derived confidence
- claim metrics
- final correctness proxy

请自动发现以下可能输入：

1. reports/ 下已有 pipeline report json
2. /tmp/ 下最近的 report json / verifier sidecar
3. tests fixtures 中可用的 IdentificationReport
4. 如果没有真实文件，构造 2-3 个 synthetic mini reports 作为 smoke test

脚本输出一个 CSV：

reports/verifier_confidence_experiment.csv

字段至少包括：

- trace_id
- fixture_name
- top_candidate_name
- top_candidate_smiles
- llm_self_confidence
- verification_confidence
- total_claims
- supported_ratio
- claim_precision
- contradiction_rate
- unverifiable_rate
- overall_verdict
- top1_evidence_score
- top1_predicted_cosine
- n_candidates
- correctness_proxy
- notes

correctness_proxy 第一版可以这样定义：

- 如果 report 或 filename 中可识别 ground truth candidate name，并且 top candidate name 匹配 → 1
- 如果没有 ground truth，但 overall_verdict supported/contradicted 可用，则用 weak proxy：
  - no contradictions and claim_precision >= 0.8 → likely_correct
  - contradiction_rate > 0.1 → likely_problematic
  - otherwise unknown
- 不要伪造 ground truth。无法判断就填 unknown。

LLM self confidence 提取：

- 从 source_llm_output / rewritten_output 中用 regex 提取：
  - confidence: 0.8
  - confidence score = 80%
  - high / medium / low confidence 映射为 0.85 / 0.55 / 0.25
- 如果没有，填空。

脚本还要打印 summary：

- n cases
- n with llm_self_confidence
- n with verification_confidence
- Pearson/Spearman correlation，如果有 numeric correctness/tanimoto
- 按 correctness_proxy 分组的平均 verification_confidence
- contradiction_rate 最高的 top cases

注意：
- 不要强依赖 scipy；如果没有 scipy，用 numpy/pandas 或手写 Pearson。
- 如果 pandas 不可用，用 csv 标准库。
- 脚本必须能在没有真实 report 时跑通 synthetic smoke test。

---

## 任务 5：运行测试和实验

请运行：

pytest tests/test_verifier/ -q

然后运行：

python scripts/experiments/run_verifier_confidence_experiment.py

如果项目需要 conda，请根据当前 README 或现有命令选择合适环境，例如：

conda run -n metagent-llm python -m pytest tests/test_verifier/ -q
conda run -n metagent-llm python scripts/experiments/run_verifier_confidence_experiment.py

---

## 输出要求

完成后请给出：

A. 修改文件列表  
B. 每个任务的实现说明  
C. 新增 schema 字段说明  
D. 测试结果  
E. 实验 CSV 路径和前几行内容  
F. summary 结果  
G. 当前局限性和下一步建议  

特别注意：
- 不要大重构。
- 不要删除旧字段。
- 不要改变现有 LLM call 数。
- 不要让 candidate_ref 解析产生错误 top-1 fallback。
- typed fields 只能增强验证，不能让旧逻辑失效。