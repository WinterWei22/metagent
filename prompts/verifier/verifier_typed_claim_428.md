请基于你刚才的 Verifier Typed Claim / Claim Table / Claim Metrics 优化方案，开始实现第一阶段的最小可落地 PR。

目标：
只做 schema 扩展 + claim field parser + claim table + metrics + agent 输出接入。
不要重构 verifier layers，不要修改 LLM prompt，不要改变现有 verifier verdict 行为。

请按以下范围实现：

1. 修改 verifier/schemas.py
新增：
- ClaimSubtype
- SubjectKind
- ClaimExtractedFields
- CandidateRef
- EvidenceRef
- ClaimProvenance
- VerifiedClaimRow
- VerifiedClaimTable
- ClaimMetrics

扩展现有：
- ExtractedClaim
- ClassifiedClaim
- VerifiedClaim
- VerifiedIdentification

要求：
- 所有新增字段必须有默认值或为 Optional
- 保持旧测试兼容
- 不删除现有字段
- peak_mz / neutral_loss 暂时保留

2. 新增 verifier/claim_fields.py
实现：
- normalize_claim_text(text: str) -> str
- parse_claim_fields(text: str) -> ClaimExtractedFields
- infer_claim_subtype(text, fields, claim_type=None) -> ClaimSubtype

第一版 parser 至少支持：
- formula，包括 unicode subscript，如 C₆H₁₂O₆
- m/z
- precursor m/z
- neutral mass
- adduct，如 [M+H]+
- neutral loss，如 H2O / NH3 / CO2
- PMID
- DOI
- HMDB / KEGG / PubChem CID / ChEBI / InChIKey
- score value
- rank

3. 新增 verifier/claim_table.py
实现：
- build_claim_table(claims: list[VerifiedClaim], pass_id: Literal["v1","v2"]) -> VerifiedClaimTable

要求：
- 即使 VerifiedClaim 没有 claim_id，也要生成稳定 fallback id：v1:c000 / v2:c000
- severity 根据 verdict 映射：
  SUPPORTED -> info
  UNVERIFIABLE_V0 -> minor
  UNSUPPORTED -> major
  CONTRADICTED -> critical
  ERROR -> major
- verifier_layer 可以先由 claim_type 映射
- evidence_summary 使用 claim.evidence

4. 新增 verifier/metrics.py
实现：
- compute_claim_metrics(claims_v1: list[VerifiedClaim], claims_v2: list[VerifiedClaim]) -> ClaimMetrics

第一版至少计算：
- total_claims
- supported_claims
- contradicted_claims
- unsupported_claims
- unverifiable_claims
- error_claims
- supported_ratio
- contradiction_rate
- unverifiable_rate
- claim_precision = supported / (supported + contradicted + unsupported)
- per_type_verdict_counts
- per_subtype_verdict_counts
- tool_call_counts

默认以 claims_v2 为主；如果 claims_v2 为空，则用 claims_v1。

5. 修改 verifier/agent.py
在最终返回 VerifiedIdentification 前：
- build table_v1
- build table_v2
- compute metrics
- 写入 VerifiedIdentification.claim_tables 和 claim_metrics

要求：
- 不改变原有 claims_v1 / claims_v2 / overall_verdict
- 不改变 rewrite 逻辑
- 不改变 LLM call 数

6. 修改 claim_extractor / claim_classifier 的最小接入
要求：
- 在 claim_extractor 生成 ExtractedClaim 时填充：
  source_text
  normalized_text
  extracted_fields
- 在 claim_classifier 生成 ClassifiedClaim 时透传：
  claim_id
  normalized_text
  extracted_fields
  claim_subtype
- peak_mz / neutral_loss 仍保持旧字段，并可由 extracted_fields 同步填充

7. 新增测试
新增或修改测试：
- tests/test_verifier/test_claim_fields.py
- tests/test_verifier/test_claim_table.py
- tests/test_verifier/test_metrics.py

测试至少覆盖：
- unicode formula normalize
- formula extraction
- m/z extraction
- precursor m/z 不被识别成 peak mechanistic neutral loss
- neutral loss extraction
- PMID / DOI extraction
- database id extraction
- score / rank extraction
- old VerifiedClaim 也能 build_claim_table
- mixed verdict metrics 正确
- agent 返回对象包含 claim_tables 和 claim_metrics

8. 最后运行：
- pytest tests/test_verifier/ -q

请输出：
A. 修改文件列表
B. 关键实现说明
C. 测试结果
D. 是否有旧测试失败，如有说明原因和建议