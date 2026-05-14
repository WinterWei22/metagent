# Verifier Typed Claim / Claim Table / Claim Metrics 优化方案

日期：2026-04-28  
目标：把当前 verifier 从“自然语言 claim 列表验证”升级为“typed claim + claim table + claim-level metrics”，为 peak-level verifier、auditable confidence metric 和 UI evidence panel 打基础。

## A. 当前 Schema 总结

### A.1 IdentificationReport 相关结构

当前主数据契约在 `schemas/` 下。`IdentificationReport` 是 deterministic pipeline 输出，也是 orchestrator 和 verifier 的 source of truth。

#### `Spectrum`

位置：`schemas/common.py`

字段：

- `mz: list[float]`
- `intensity: list[float]`
- `precursor_mz: float`
- `adduct: str`
- `ionization_mode: Literal["positive", "negative"]`
- `collision_energy: float | None`

约束：

- `mz` 和 `intensity` 长度一致。
- spectrum 至少一个 peak。
- intensity 已归一化到 `[0, 1]`。

可支撑 typed claim 的字段：

- `mz`
- `precursor_mz`
- `adduct`
- `collision_energy`
- peak count
- peak existence / peak coverage

缺口：

- 没有 peak_id。
- 没有 peak annotation provenance。
- 没有 per-peak tolerance / matched fragment cache。

#### `Candidate`

位置：`schemas/common.py`

字段：

- `smiles: str`
- `name: str | None`
- `source: Literal["library", "generated", "reference"]`
- `score: float`
- `source_id: str | None`
- `explain: str`

可支撑 typed claim 的字段：

- candidate name
- candidate source
- candidate score
- SMILES
- source_id

缺口：

- 没有 stable candidate id。
- 没有 rank 字段，rank 只能由 `IdentificationReport.candidates` 顺序推导。
- 没有 canonical SMILES / InChIKey 作为顶层 candidate identity。

#### `CandidateReport`

位置：`schemas/report.py`

字段：

- `candidate: Candidate`
- `prefilter_match: PrefilteredCandidate | None`
- `metabolite_info: MetaboliteInfoResponse | None`
- `pathway_context: PathwayContextResponse | None`
- `predicted_spectrum_cosine: float | None`
- `predicted_model_version: str | None`
- `mass_match_indicator: float`
- `pathway_presence_indicator: float`
- `evidence_score: float`
- `notes: list[str]`
- `literature_records: list[LiteratureRecord]`

可支撑 typed claim 的字段：

- rank：由 list index 推导。
- `candidate_ref`: 可临时用 `candidates[{i}]`。
- formula / exact mass / cross refs / InChIKey：来自 `metabolite_info`。
- pathway name / pathway id：来自 `pathway_context.pathways`。
- literature PMID / DOI：来自 `literature_records`。
- score claims：`candidate.score`、`predicted_spectrum_cosine`、`evidence_score`、`mass_match_indicator`、`pathway_presence_indicator`。

缺口：

- 没有正式 `candidate_id`。
- 没有统一 candidate identity object。
- `metabolite_info=None` 时，很多 typed claims 失去 anchor。
- `candidate.name=None` 在真实 pipeline 中出现过，会阻碍 subject 定位。

#### `IdentificationReport`

位置：`schemas/report.py`

字段：

- `experimental_spectrum: Spectrum`
- `preprocess_quality_flag: Literal["good", "sparse", "noisy", "invalid"]`
- `neutral_mass_computed: float`
- `n_prefilter_candidates: int`
- `n_library_candidates: int`
- `n_generated_candidates: int`
- `candidates: list[CandidateReport]`
- `pipeline_version: str`
- `tool_versions: dict[str, str]`
- `warnings: list[str]`

可支撑 typed claim 的字段：

- source-level spectrum claims。
- candidate-level score / rank / identity claims。
- warning / degradation claims。
- tool version / pipeline provenance claims。

缺口：

- 没有 explicit evidence id / evidence ref。
- 没有 normalized candidate refs。
- 没有 per-tool call trace。
- 没有 typed links from LLM output back to report fields。

### A.2 Verifier Claim 相关结构

当前 verifier schema 在 `verifier/schemas.py`。

#### `ClaimType`

当前类型：

- `GROUNDED = "grounded_claim"`
- `FACTUAL = "factual_roundtrip_claim"`
- `BIOLOGICAL = "biological_claim"`
- `CONSISTENCY = "consistency_claim"`
- `LITERATURE = "literature_claim"`
- `PEAK_MECHANISTIC = "peak_mechanistic_claim"`

问题：

- `ClaimType` 同时承担“验证层路由”和“claim 语义类型”两个职责。
- Type 2 内部又包含 database ID、formula/name round-trip、chemical taxonomy 等 subtype，但 schema 没有 subtype。
- Type 1 包含 formula、score、cosine、ppm、precursor/adduct 等不同字段形态，也没有 subtype。

#### `ClaimVerdict`

当前 verdict：

- `SUPPORTED`
- `CONTRADICTED`
- `UNSUPPORTED`
- `UNVERIFIABLE_V0`
- `ERROR`

这个枚举基本够用。后续 metrics 可以直接基于它计算。

#### `ExtractedClaim`

当前字段：

- `claim_text: str`
- `subject: str | None`
- `peak_mz: float | None`
- `neutral_loss: str | None`

问题：

- claim 仍以自然语言为主。
- `peak_mz` / `neutral_loss` 是局部补丁，不是通用 extracted fields。
- 没有 claim_id。
- 没有 source span / provenance。
- 没有 normalized_text。
- 没有 database_id、formula、pathway、pmid、doi、score 等结构化字段。

#### `ClassifiedClaim`

当前字段：

- `claim_text: str`
- `subject: str | None`
- `claim_type: ClaimType`
- `classifier_source: Literal["rule", "llm", "fallback"]`
- `peak_mz: float | None`
- `neutral_loss: str | None`

问题：

- 没有 `claim_subtype`。
- 没有 `candidate_ref`。
- 没有 extracted_fields。
- 没有 classification confidence。
- 没有 parser provenance。

#### `VerifiedClaim`

当前字段：

- `claim_text: str`
- `claim_type: ClaimType`
- `verdict: ClaimVerdict`
- `evidence: str`
- `source_field: str | None`
- `correction: str | None`

问题：

- evidence 是人类可读字符串，机器不可稳定聚合。
- 没有 `claim_id`，无法稳定关联 v1/v2。
- 没有 `verifier_layer`。
- 没有 `tool_called`。
- 没有 `trace_summary`。
- 没有 `candidate_ref`。
- 没有 `claim_subtype`。
- 没有 `severity`。
- 没有 parent/group 关系。

#### `VerifiedIdentification`

当前字段：

- `trace_id`
- `source_llm_output`
- `rewritten_output`
- `claims_v1: list[VerifiedClaim]`
- `claims_v2: list[VerifiedClaim]`
- `overall_verdict`
- `verification_warnings`
- `llm_call_count`
- `generated_at`

问题：

- 没有 claim table。
- 没有 metrics。
- v1/v2 claim 之间没有 stable linkage。
- consistency claims 是额外 `VerifiedClaim`，但其 cited claim indices 只在 `evidence` 字符串中，不可结构化读取。

### A.3 当前 verifier 每一步输入输出

#### Stage 1: `claim_extractor.extract_claims()`

输入：

- `llm_output: str`
- `trace_id: str`

输出：

- `list[ExtractedClaim]`

实现：

- 调 LLM，要求返回 JSON list。
- 每项目前只读取 `claim_text` 和 `subject`。
- 不解析其它字段。

#### Stage 2: `claim_classifier.classify_claims()`

输入：

- `list[ExtractedClaim]`
- `trace_id`

输出：

- `tuple[list[ClassifiedClaim], int]`

实现：

- regex rule 优先。
- ambiguous claims 批量 LLM fallback。
- 在分类时额外提取 `peak_mz` / `neutral_loss`。

#### Stage 3: `_verify_per_claim()`

输入：

- `list[ClassifiedClaim]`
- `IdentificationReport`
- optional injected fetchers

输出：

- `list[VerifiedClaim]`

实现：

- 按 `claim_type` dispatch 到 layer。
- Layer D consistency 另行批量运行，返回额外 `VerifiedClaim`。

#### Stage 4: `rewriter.rewrite()`

输入：

- `source_llm_output`
- `list[VerifiedClaim]`
- `trace_id`

输出：

- rewritten string

实现：

- 对 `CONTRADICTED`、`UNSUPPORTED`、`UNVERIFIABLE_V0` 生成 edit list。
- edit list 中只有 `claim_text`、`verdict`、`correction`、`evidence`。
- 没有 claim_id，所以 rewrite 后无法对齐旧 claim。

## B. 主要结构性问题

### B.1 Claim 当前本质上仍是自然语言文本

虽然 `ExtractedClaim` 和 `ClassifiedClaim` 已经有 `peak_mz` / `neutral_loss`，但这只是为 Type 5 做的局部扩展。绝大多数 claim 仍由 `claim_text` 承载全部语义。

后果：

- layer 反复 regex 解析同一段文本。
- UI 只能展示文本和 evidence 字符串。
- metrics 只能统计 verdict/type，无法稳定统计 subtype、field-level correctness、candidate-level support。

### B.2 Subject 到 candidate 的定位脆弱

当前主要使用 `verifier/source_lookup.py::find_candidate_by_name()`：

匹配顺序：

1. `candidate.name`
2. `metabolite_info.primary_name`
3. `metabolite_info.synonyms`
4. `candidate.name` substring

问题：

- 真实 pipeline 中出现过 `candidate.name=None`、`metabolite_info.found=False`，导致 ClassyFire 找不到 SMILES。
- 不能区分 subject 是 candidate、pathway、compound class、database id 还是 generic molecule。
- 没有 `candidate_ref` 固定住匹配结果。

### B.3 字段结构化覆盖不均匀

当前结构化字段：

- `peak_mz`
- `neutral_loss`

未结构化但需要结构化：

- formula
- neutral_mass
- precursor_mz
- adduct
- smiles
- inchikey
- database_id
- database_name
- pathway_name
- pmid
- doi
- score_name
- score_value
- rank
- candidate_name
- fragment_formula
- mz_tolerance_ppm

### B.4 Classification 同时承担 routing 和 parsing

`claim_classifier.py` 现在用 regex 判断 route，同时顺手提取 peak fields。这个职责会膨胀。

更合理的分层：

```text
claim_extractor: 抽 atomic claim
claim_normalizer/parser: 抽 typed fields
claim_classifier: 只做 claim_type + claim_subtype
layers: 消费 typed fields，必要时 fallback text parser
```

### B.5 Layer verification 依赖 fragile string matching

例子：

- Grounded layer 用 text regex 判断 formula/evidence score/cosine/ppm。
- Factual layer 重新 `_extract_ids()`。
- Literature layer 重新 `_extract_pmids()` / `_extract_dois()`。
- Biological layer 重新解析 pathway IDs / phrases。
- Peak layer 重新解析 m/z / neutral loss。

这导致：

- 同一字段在多个地方重复解析。
- parser 行为不统一。
- 新增 metric 时无法知道字段来自哪里。

### B.6 v1 / v2 没有 claim-level linkage

当前 `claims_v1` 和 `claims_v2` 是两个独立 `VerifiedClaim` 列表。

缺少：

- `claim_id`
- `parent_claim_id`
- `claim_group_id`
- rewrite action id
- old/new claim alignment

后果：

- 无法直接计算 rewrite_improvement。
- 无法判断某条 v1 contradiction 是否被删除、修改、支持或仍保留。
- UI 无法展示 before/after claim diff。

### B.7 Claim-level metrics 只能算浅层统计

当前能直接算：

- total claims
- per verdict counts
- per type counts
- supported ratio
- contradiction rate
- unverifiable rate

当前不能稳定算：

- per subtype counts
- per candidate support counts
- per tool call counts
- peak claim coverage
- rewrite improvement
- source-field coverage
- claim precision with denominator excluding unverifiable
- candidate-level confidence summary

### B.8 UI claim table 受限

当前 UI `ui/panels/verifier.py` 展示列：

- Claim
- Type
- Verdict
- Evidence
- Correction

缺少：

- subtype
- candidate_ref
- source_field as clickable / structured path
- tool_called
- trace_summary
- severity
- group / parent claim
- extracted fields

## C. 推荐 Schema 设计

设计原则：

1. 向后兼容：旧的 `claim_text` / `claims_v1` / `claims_v2` 不删除。
2. 不一开始替换 extractor LLM prompt，先用本地 parser 补 typed fields。
3. 顶层字段只放高频路由/展示/关联字段。
4. 细节字段放 `extracted_fields`，避免 schema 爆炸。
5. 所有新增字段默认 `None` 或 `default_factory`，旧测试不崩。

### C.1 新增枚举

建议在 `verifier/schemas.py` 新增：

```python
class ClaimSubtype(str, Enum):
    UNKNOWN = "unknown"

    # grounded
    FORMULA = "formula"
    PRECURSOR_MZ = "precursor_mz"
    NEUTRAL_MASS = "neutral_mass"
    ADDUCT = "adduct"
    PEAK_COUNT = "peak_count"
    EVIDENCE_SCORE = "evidence_score"
    CANDIDATE_SCORE = "candidate_score"
    PREDICTED_COSINE = "predicted_cosine"
    MASS_MATCH = "mass_match"
    RANKING = "ranking"

    # factual
    DATABASE_ID = "database_id"
    CHEMICAL_TAXONOMY = "chemical_taxonomy"
    NAME_IDENTITY = "name_identity"

    # biological
    PATHWAY_MEMBERSHIP = "pathway_membership"
    PATHWAY_NEIGHBOUR = "pathway_neighbour"
    COOCCURRENCE = "cooccurrence"
    BIOLOGICAL_CONTEXT = "biological_context"

    # literature
    LITERATURE_PMID = "literature_pmid"
    LITERATURE_DOI = "literature_doi"
    LITERATURE_FREE_TEXT = "literature_free_text"

    # peak
    PEAK_EXISTENCE = "peak_existence"
    FRAGMENT_ASSIGNMENT = "fragment_assignment"
    NEUTRAL_LOSS = "neutral_loss"
    RING_CLEAVAGE = "ring_cleavage"
```

```python
class SubjectKind(str, Enum):
    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    COMPOUND = "compound"
    PATHWAY = "pathway"
    DATABASE_ID = "database_id"
    SPECTRUM = "spectrum"
    PEAK = "peak"
    LITERATURE = "literature"
    CLASS = "class"
```

### C.2 Typed field container

建议新增：

```python
class ClaimExtractedFields(BaseModel):
    model_config = ConfigDict(extra="allow")

    mz: float | None = None
    mz_tolerance_ppm: float | None = None
    formula: str | None = None
    neutral_mass: float | None = None
    precursor_mz: float | None = None
    adduct: str | None = None
    neutral_loss: str | None = None
    fragment_formula: str | None = None
    smiles: str | None = None
    inchikey: str | None = None
    database_name: str | None = None
    database_id: str | None = None
    pathway_name: str | None = None
    pathway_id: str | None = None
    pmid: str | None = None
    doi: str | None = None
    score_name: str | None = None
    score_value: float | None = None
    rank: int | None = None
    candidate_name: str | None = None
```

为什么用 typed model 而不是 `dict[str, Any]`：

- Pydantic dump 稳定，UI 和 metrics 直接读。
- 可以保留 `extra="allow"`，让后续加字段不用 schema bump。
- typed 字段可以被测试精确断言。

### C.3 CandidateRef / EvidenceRef / Provenance

建议新增：

```python
class CandidateRef(BaseModel):
    index: int | None = None
    path: str | None = None  # e.g. candidates[0]
    name: str | None = None
    smiles: str | None = None
    inchikey: str | None = None
    source_id: str | None = None
    match_method: str | None = None  # subject_exact, synonym, fallback_top, none
```

```python
class EvidenceRef(BaseModel):
    source: str  # source_report, tool, llm_consistency, sirius, classyfire
    path: str | None = None
    value: str | float | int | bool | None = None
    summary: str | None = None
```

```python
class ClaimProvenance(BaseModel):
    pass_id: Literal["v1", "v2"] | None = None
    extractor: str | None = None
    extractor_source: Literal["llm", "rule", "manual"] | None = None
    classifier_source: Literal["rule", "llm", "fallback"] | None = None
    parser_version: str | None = None
    source_span_start: int | None = None
    source_span_end: int | None = None
```

### C.4 TypedClaim

建议先不新增独立 `TypedClaim` 进入主流程，而是把它作为 mixin 风格字段扩展到 `ExtractedClaim` / `ClassifiedClaim`。同时可以定义一个正式 model 供 helper 使用：

```python
class TypedClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_id: str
    source_text: str
    normalized_text: str | None = None
    claim_type: ClaimType | None = None
    claim_subtype: ClaimSubtype = ClaimSubtype.UNKNOWN
    subject: str | None = None
    subject_kind: SubjectKind = SubjectKind.UNKNOWN
    candidate_ref: CandidateRef | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    extracted_fields: ClaimExtractedFields = Field(default_factory=ClaimExtractedFields)
    confidence_hint: float | None = Field(None, ge=0.0, le=1.0)
    provenance: ClaimProvenance = Field(default_factory=ClaimProvenance)
```

### C.5 哪些字段放顶层，哪些放 extracted_fields

建议顶层字段：

- `claim_id`：所有表、metrics、rewrite 对齐都要用。
- `source_text` / `claim_text`：人类可读主文本。
- `normalized_text`：去大小写、unicode subscript、空白标准化后的文本。
- `claim_type`：layer 路由。
- `claim_subtype`：metric 和 UI 分组。
- `subject`：现有兼容。
- `subject_kind`：UI / candidate 解析。
- `candidate_ref`：高频展示和 per-candidate metrics。
- `evidence_refs`：审计和 UI trace。
- `confidence_hint`：extractor/classifier confidence，不等于 verifier confidence。
- `provenance`：claim 来自哪里、哪个 pass。

建议放入 `extracted_fields`：

- `mz`
- `mz_tolerance_ppm`
- `formula`
- `neutral_mass`
- `precursor_mz`
- `adduct`
- `neutral_loss`
- `fragment_formula`
- `smiles`
- `inchikey`
- `database_name`
- `database_id`
- `pathway_name`
- `pathway_id`
- `pmid`
- `doi`
- `score_name`
- `score_value`
- `rank`
- `candidate_name`

理由：

- 这些字段不是所有 claim 都有。
- 放顶层会让 schema 过宽。
- extracted_fields 可以被 layer 共享消费。

## D. Claim Table 和 Metrics 设计

### D.1 Claim table row schema

建议新增：

```python
class VerifiedClaimRow(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: ClaimType
    claim_subtype: ClaimSubtype = ClaimSubtype.UNKNOWN
    subject: str | None = None
    candidate_ref: CandidateRef | None = None
    verdict: ClaimVerdict
    evidence_summary: str
    source_field: str | None = None
    correction: str | None = None
    verifier_layer: str | None = None
    tool_called: str | None = None
    trace_summary: str | None = None
    severity: Literal["info", "minor", "major", "critical"] = "info"
    claim_group_id: str | None = None
    parent_claim_id: str | None = None
    extracted_fields: ClaimExtractedFields = Field(default_factory=ClaimExtractedFields)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
```

```python
class VerifiedClaimTable(BaseModel):
    pass_id: Literal["v1", "v2"]
    rows: list[VerifiedClaimRow]
```

### D.2 如何从当前 VerifiedIdentification 生成 claim table

短期不要求 agent 输出立刻变更。可以新增 helper：

```python
def build_claim_table(
    verified: VerifiedIdentification,
    *,
    pass_id: Literal["v1", "v2"] = "v2",
) -> VerifiedClaimTable:
    ...
```

初始版本从 `VerifiedClaim` 映射：

- `claim_id`: 如果 `VerifiedClaim.claim_id` 有值就用；否则生成 `f"{pass_id}:{i:03d}"`。
- `claim_text`: `claim.claim_text`
- `claim_type`: `claim.claim_type`
- `claim_subtype`: 如果缺失则 `UNKNOWN`
- `subject`: 如果缺失则 `None`
- `candidate_ref`: 如果缺失则 `None`
- `verdict`: `claim.verdict`
- `evidence_summary`: `claim.evidence`
- `source_field`: `claim.source_field`
- `correction`: `claim.correction`
- `verifier_layer`: 由 `claim_type` 映射，例如 `grounded`, `factual`, `biological`, `literature`, `peak_mechanistic`, `consistency`
- `tool_called`: 初期由 `claim_type/subtype/evidence` 粗映射；后续由 layer 显式填。
- `trace_summary`: 初期等于 evidence 的短摘要。
- `severity`: 由 verdict 映射。
- `claim_group_id` / `parent_claim_id`: 初期为空；consistency claims 后续填 cited ids。

是否需要修改 `agent.py` 输出结构：

- Stage 1 不需要。
- Stage 3 可先不改 dispatch。
- `VerifiedIdentification` 可以新增可选字段：
  - `claim_tables: list[VerifiedClaimTable] = []`
  - `claim_metrics: ClaimMetrics | None = None`
- 为保持兼容，先让 `_final()` 构造时填充。
- UI 继续读 `claims_v2` 不会崩；新版 UI 可以优先读 `claim_tables[-1]`。

### D.3 Claim-level metrics schema

建议新增：

```python
class ClaimMetrics(BaseModel):
    total_claims: int = 0
    supported_claims: int = 0
    contradicted_claims: int = 0
    unsupported_claims: int = 0
    unverifiable_claims: int = 0
    error_claims: int = 0
    supported_ratio: float | None = None
    contradiction_rate: float | None = None
    unverifiable_rate: float | None = None
    claim_precision: float | None = None
    rewrite_improvement: float | None = None
    per_type_verdict_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    per_subtype_verdict_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    per_candidate_support_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    peak_claim_coverage: float | None = None
    tool_call_counts: dict[str, int] = Field(default_factory=dict)
```

当前能直接算：

- `total_claims`
- `supported_claims`
- `contradicted_claims`
- `unsupported_claims`
- `unverifiable_claims`
- `error_claims`
- `supported_ratio`
- `contradiction_rate`
- `unverifiable_rate`
- `per_type_verdict_counts`

当前需要新增字段才能稳定算：

- `claim_precision`: 需要定义 denominator，建议 `supported / (supported + contradicted + unsupported)`，排除 `unverifiable_v0` 和 `error`。
- `rewrite_improvement`: 需要 v1/v2 `parent_claim_id` 或文本相似对齐。
- `per_candidate_support_counts`: 需要 `candidate_ref`。
- `peak_claim_coverage`: 需要 subtype 或 extracted_fields.mz。
- `tool_call_counts`: 需要 `tool_called` 或 layer trace。
- `per_subtype_verdict_counts`: 需要 `claim_subtype`。

## E. 最小改造路线

### Stage 1：最小 schema 扩展

目标：不改 LLM prompt，不大改 layers，先让 typed 信息有地方放。

修改 `verifier/schemas.py`：

新增：

- `ClaimSubtype`
- `SubjectKind`
- `ClaimExtractedFields`
- `CandidateRef`
- `EvidenceRef`
- `ClaimProvenance`
- `VerifiedClaimRow`
- `VerifiedClaimTable`
- `ClaimMetrics`

扩展 `ExtractedClaim`：

```python
claim_id: str | None = None
source_text: str | None = None
normalized_text: str | None = None
claim_subtype: ClaimSubtype = ClaimSubtype.UNKNOWN
subject_kind: SubjectKind = SubjectKind.UNKNOWN
extracted_fields: ClaimExtractedFields = Field(default_factory=ClaimExtractedFields)
provenance: ClaimProvenance = Field(default_factory=ClaimProvenance)
```

扩展 `ClassifiedClaim`：

```python
claim_id: str | None = None
normalized_text: str | None = None
claim_subtype: ClaimSubtype = ClaimSubtype.UNKNOWN
subject_kind: SubjectKind = SubjectKind.UNKNOWN
candidate_ref: CandidateRef | None = None
extracted_fields: ClaimExtractedFields = Field(default_factory=ClaimExtractedFields)
confidence_hint: float | None = None
provenance: ClaimProvenance = Field(default_factory=ClaimProvenance)
```

扩展 `VerifiedClaim`：

```python
claim_id: str | None = None
claim_subtype: ClaimSubtype = ClaimSubtype.UNKNOWN
subject: str | None = None
subject_kind: SubjectKind = SubjectKind.UNKNOWN
candidate_ref: CandidateRef | None = None
extracted_fields: ClaimExtractedFields = Field(default_factory=ClaimExtractedFields)
evidence_refs: list[EvidenceRef] = Field(default_factory=list)
verifier_layer: str | None = None
tool_called: str | None = None
trace_summary: str | None = None
severity: str | None = None
claim_group_id: str | None = None
parent_claim_id: str | None = None
```

扩展 `VerifiedIdentification`：

```python
claim_tables: list[VerifiedClaimTable] = Field(default_factory=list)
claim_metrics: ClaimMetrics | None = None
```

兼容策略：

- 所有新增字段都有默认值。
- 旧测试中直接构造 `ClassifiedClaim(...)` / `VerifiedClaim(...)` 不需要改。
- 旧 UI 继续读 `claims_v2`。

### Stage 2：typed extraction / normalization

新增文件：

```text
verifier/claim_fields.py
verifier/claim_ids.py
verifier/candidate_resolution.py
```

建议函数：

```python
def assign_claim_ids(
    claims: list[ExtractedClaim],
    *,
    pass_id: Literal["v1", "v2"],
) -> list[ExtractedClaim]:
    ...
```

```python
def normalize_claim_text(text: str) -> str:
    ...
```

```python
def parse_claim_fields(text: str) -> ClaimExtractedFields:
    ...
```

```python
def infer_claim_subtype(
    text: str,
    fields: ClaimExtractedFields,
    claim_type: ClaimType | None = None,
) -> ClaimSubtype:
    ...
```

```python
def resolve_candidate_ref(
    claim: ExtractedClaim | ClassifiedClaim,
    source_report: IdentificationReport,
) -> CandidateRef | None:
    ...
```

本地 parser 优先覆盖：

- formula regex，支持 unicode subscript。
- `m/z` / precursor m/z。
- neutral mass。
- adduct。
- neutral loss。
- database IDs：HMDB、KEGG、CID、ChEBI、InChIKey、CCMSLIB。
- PMID / DOI。
- score：evidence_score、candidate score、cosine。
- rank。
- pathway ID/name phrase。

LLM fallback：

- 不建议 Stage 2 立刻新增 LLM parser call。
- 如果要用 LLM，先只让 Stage 1 prompt 可选返回 extra keys；本地 Pydantic 忽略缺失。

### Stage 3：claim table + metrics

新增文件：

```text
verifier/claim_table.py
verifier/metrics.py
```

关键函数：

```python
def build_claim_table(
    claims: list[VerifiedClaim],
    *,
    pass_id: Literal["v1", "v2"],
) -> VerifiedClaimTable:
    ...
```

```python
def compute_claim_metrics(
    *,
    claims_v1: list[VerifiedClaim],
    claims_v2: list[VerifiedClaim],
) -> ClaimMetrics:
    ...
```

接入点：

- 在 `verifier/agent.py::_final()` 里构造：

```python
table_v1 = build_claim_table(claims_v1, pass_id="v1")
table_v2 = build_claim_table(claims_v2, pass_id="v2")
metrics = compute_claim_metrics(claims_v1=claims_v1, claims_v2=claims_v2)
```

- `VerifiedIdentification(...)` 附加：

```python
claim_tables=[table_v1, table_v2]
claim_metrics=metrics
```

### Stage 4：UI / report integration

UI 改造点：

- `ui/panels/verifier.py` 优先读取 `claim_tables`。
- 若没有 `claim_tables`，fallback 到旧 `claims_v2`。
- 表格列扩展为：
  - claim_id
  - claim_text
  - type
  - subtype
  - subject
  - candidate_ref
  - verdict
  - evidence_summary
  - source_field
  - correction
  - tool_called
  - severity

rewrite 改造：

- `rewriter._to_edit()` 增加 `claim_id`。
- rewrite prompt 中要求保留或引用 claim_id。
- v2 extraction 暂时无法可靠恢复 parent id，可以先通过文本相似度 helper 建 `parent_claim_id`。

trace 展示：

- 在 UI 中为每条 claim 展开：
  - extracted_fields
  - evidence_refs
  - tool_called
  - trace_summary

## F. 具体代码修改建议

### F.1 建议新增文件

#### `verifier/claim_fields.py`

职责：

- 文本归一化。
- 字段解析。
- subtype 推断。

函数草案：

```python
def normalize_claim_text(text: str) -> str: ...

def parse_claim_fields(text: str) -> ClaimExtractedFields: ...

def infer_claim_subtype(
    text: str,
    fields: ClaimExtractedFields,
    claim_type: ClaimType | None = None,
) -> ClaimSubtype: ...
```

#### `verifier/claim_ids.py`

职责：

- claim_id 生成。
- v1/v2 轻量对齐。

函数草案：

```python
def make_claim_id(pass_id: str, index: int) -> str:
    return f"{pass_id}:c{index:03d}"

def with_claim_ids(
    claims: list[ExtractedClaim],
    *,
    pass_id: Literal["v1", "v2"],
) -> list[ExtractedClaim]: ...
```

#### `verifier/candidate_resolution.py`

职责：

- 替代/包装 `source_lookup.find_candidate_by_name()`。
- 返回结构化 `CandidateRef`。

函数草案：

```python
def resolve_candidate_ref(
    *,
    subject: str | None,
    fields: ClaimExtractedFields,
    source_report: IdentificationReport,
) -> CandidateRef | None: ...
```

#### `verifier/claim_table.py`

职责：

- 从 `VerifiedClaim` 生成 UI / metrics 友好的 claim table。

函数草案：

```python
def build_claim_table(
    claims: list[VerifiedClaim],
    *,
    pass_id: Literal["v1", "v2"],
) -> VerifiedClaimTable: ...
```

#### `verifier/metrics.py`

职责：

- claim-level metrics。

函数草案：

```python
def compute_claim_metrics(
    *,
    claims_v1: list[VerifiedClaim],
    claims_v2: list[VerifiedClaim],
) -> ClaimMetrics: ...
```

### F.2 建议修改文件

#### `verifier/schemas.py`

新增 typed claim / table / metrics models。所有新增字段默认可选。

#### `verifier/claim_extractor.py`

最小修改：

- 从 LLM item 中容忍读取：
  - `claim_id`
  - `normalized_text`
  - `claim_subtype`
  - `extracted_fields`
- 如果没有，则本地填：
  - `source_text = claim_text`
  - `normalized_text = normalize_claim_text(claim_text)`
  - `extracted_fields = parse_claim_fields(claim_text)`

#### `verifier/claim_classifier.py`

修改：

- 使用 `claim.extracted_fields`，减少重复 `_extract_peak_mz()`。
- 分类后填 `claim_subtype`。
- 保留旧 `peak_mz` / `neutral_loss` 字段一段时间，来源改为 `extracted_fields.mz` / `extracted_fields.neutral_loss`。

#### `verifier/agent.py`

修改：

- `_extract_classify(text, trace_id, pass_id)` 增加 pass_id。
- Stage 1 后 assign claim_id。
- Stage 2 后可 resolve candidate_ref。
- `_final()` 构建 `claim_tables` 和 `claim_metrics`。

#### `verifier/layers/*.py`

渐进修改：

- 每个 layer 返回 `VerifiedClaim` 时传递：
  - `claim_id`
  - `claim_subtype`
  - `subject`
  - `candidate_ref`
  - `extracted_fields`
  - `verifier_layer`
  - `tool_called`
  - `evidence_refs`

不要求一次改完。第一轮可以只改 helper `_supported/_unverifiable/_contradicted`，避免散落构造点太多。

#### `verifier/rewriter.py`

修改：

- `_to_edit()` 增加 `claim_id`、`claim_type`、`claim_subtype`。
- prompt 后续可要求 rewrite 不引用 claim_id，但内部 edit list 保留 id 方便日志。

#### `ui/panels/verifier.py`

修改：

- `_select_claims()` 优先读 `claim_tables`。
- 扩表头。
- 新增 metrics summary。
- 保持旧 `claims_v2` fallback。

### F.3 迁移策略

推荐顺序：

1. 只加 schema 和 helper，不改变行为。
2. 在 extractor/classifier 中填 typed fields，但 layers 仍可读旧字段。
3. 在 layers 中逐步消费 `extracted_fields`。
4. agent 输出 `claim_tables` / `claim_metrics`。
5. UI 优先展示 claim table。
6. rewrite 加 claim_id 支持。
7. 最后再考虑让 LLM extractor 直接输出 typed JSON。

### F.4 回归测试建议

新增测试文件：

```text
tests/test_verifier/test_claim_fields.py
tests/test_verifier/test_claim_table.py
tests/test_verifier/test_metrics.py
tests/test_verifier/test_candidate_resolution.py
```

关键测试：

1. `parse_claim_fields` 能提取 formula、m/z、neutral mass、adduct、database id、PMID、DOI、score、rank。
2. unicode formula normalize：`C₆H₁₂O₆` → `C6H12O6`。
3. precursor `[M+H]+` 不触发 peak mechanistic subtype。
4. `[M+H-H2O]+` 触发 neutral loss subtype。
5. `resolve_candidate_ref` 对 candidate.name / primary_name / synonym / missing name 的行为稳定。
6. `build_claim_table` 从旧 `VerifiedClaim` 也能生成 row。
7. `compute_claim_metrics` 在 supported/contradicted/unverifiable/error 混合时结果正确。
8. agent 输出仍兼容旧字段，同时包含 `claim_tables` 和 `claim_metrics`。
9. UI render 对旧 sidecar 和新 sidecar 都能工作。
10. rewrite 后 v1/v2 claim_id 不要求完全对齐，但 claim table 不崩。

## 第一优先级建议

第一优先级不是改 LLM prompt，而是做“本地 typed normalization + claim table + metrics”的基础设施。

推荐首个 PR 范围：

1. 扩展 `verifier/schemas.py`，新增 typed claim/table/metrics schema。
2. 新增 `verifier/claim_fields.py`，把现有各 layer 的 regex 先集中一份。
3. 新增 `verifier/claim_table.py` 和 `verifier/metrics.py`。
4. `agent._final()` 输出 `claim_tables` 和 `claim_metrics`。
5. UI 暂不强制改，但保证 sidecar 中已有新结构。

这样做收益最大、风险最低：

- 不改变 verifier verdict 行为。
- 不改变现有 LLM call 数。
- 不破坏旧 sidecar / UI。
- 立即获得可计算 metrics。
- 为后续 layer 消费 typed fields 铺路。
