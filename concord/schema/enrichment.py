"""§3 EnrichmentResult schema — v0.3(Q05-NEW-4/5 namespace pivot).

设计原则(2026-05-15 Q05-NEW-4/5 拍板后):
1. 覆盖所有 Tier-A 工具(sspa, mummichog, FELLA, RaMP ORA, MetaboAnalystR via Docker)
2. **统一 namespace-prefixed primary key 架构**(MIRIAM / identifiers.org 标准):
   - Compound:`primary_id: str` = `"<NS>:<id>"`,NS ∈ {CHEBI, LIPIDMAPS, HMDB, KEGG, INCHIKEY}
   - Pathway:`pathway_id: str` = `"<NS>:<id>"`,NS ∈ {REACT, KEGG, WP, SMPDB, METACYC}
3. **所有外部 DB ID 字段 optional**,InChIKey 作 ground truth 兜底必填
4. **primary_id resolution rule**(CompoundRef):chebi → lipidmaps → hmdb → kegg → inchikey 第一个非空填
5. metabolites_hit: `tuple[CompoundRef, ...]`(v0.2 已立)
6. score_type 显式枚举;auxiliary_scores: dict;parameters/tool_version/db_release/wall_time;
   tautomer_canonicalized + chebi_canonicalized 字段

CHANGELOG:
  v0.1 (Session 2 早期)      — InChIKey-only metabolites_hit
  v0.2 (Q-05 pivot)           — CompoundRef + 双主键 PathwayHit + kegg_id field
  v0.3 (Q05-NEW-4/5 namespace pivot, 2026-05-15)
                              — pathway_id / primary_id 改成 namespace-prefixed
                                ("REACT:R-HSA-XXX" / "CHEBI:NNNN" / "LIPIDMAPS:LMxxxx"
                                / "INCHIKEY:XXX...");消除 canonical_source 字段;
                                external ID 字段全 optional;__post_init__ validator
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EnrichmentMethod(str, Enum):
    """Method identifier — 1:1 with tool/back-end."""

    ORA_RAMP = "ora_ramp"               # RaMP-DB hypergeometric ORA(已有 tool)
    ORA_SSPA = "ora_sspa"               # sspa Hypergeometric (sspa.sspa_ora)
    SSGSEA = "ssgsea"                   # sspa.sspa_ssgsea, single-sample GSEA
    GSEA_SSPA = "gsea_sspa"             # sspa.sspa_gsea, classic preranked GSEA
    KPM_SSPA = "kpm_sspa"               # sspa.sspa_kpm, KEGG pathway model
    FELLA_RWR = "fella_rwr"             # FELLA random-walk-with-restart (R)
    FELLA_DIFFUSION = "fella_diffusion" # FELLA heat-diffusion variant
    MUMMICHOG = "mummichog"             # mummichog v3 m/z-driven enrichment
    PSEA_METABOANALYSTR = "psea_marx"   # MetaboAnalystR PerformPSEA
    MSEA_METABOANALYSTR = "msea_marx"   # MetaboAnalystR PerformMSEA


class PathwayDB(str, Enum):
    KEGG = "kegg"
    REACTOME = "reactome"
    WIKIPATHWAYS = "wikipathways"
    METACYC = "metacyc"
    HMDB = "hmdb"
    SMPDB = "smpdb"
    MERGED = "merged"                   # 跨库合并(MetaNetX 路径)


class ScoreType(str, Enum):
    """显式标 score 含义,避免后续 misread."""

    P_VALUE = "p_value"                 # raw p-value (ORA, mummichog)
    FDR = "fdr"                         # BH/Storey adjusted
    ES = "es"                           # GSEA enrichment score (signed)
    NES = "nes"                         # GSEA normalized ES
    SS_ACTIVITY = "ss_activity"         # sspa ssGSEA per-sample pathway activity
    RWR_SCORE = "rwr_score"             # FELLA RWR final score
    DIFFUSION_SCORE = "diffusion_score" # FELLA diffusion final score
    EASE = "ease"                       # mummichog EASE score
    COMPOSITE = "composite"             # ConcordMet aggregated score(Sprint W6+)


# ---------------------------------------------------------------------------
# Namespace whitelists(MIRIAM / identifiers.org 子集,v0.3 Q05-NEW-4/5 拍板)
# ---------------------------------------------------------------------------

COMPOUND_NAMESPACES = frozenset({
    "CHEBI",       # CHEBI:17234 → D-Glucose,~165k entries,100% cross-DB lingua franca
    "LIPIDMAPS",   # LIPIDMAPS:LMFA01030001,长尾 lipid 无 ChEBI 时用
    "HMDB",        # HMDB:HMDB0000122,代谢组主源
    "KEGG",        # KEGG:C00031,经典 metabolomics DB
    "INCHIKEY",    # INCHIKEY:WQZGKKKJIJFFOK-...,结构兜底,RDKit 算的出来必非空
})

PATHWAY_NAMESPACES = frozenset({
    "REACT",       # REACT:R-HSA-71387,Reactome stable ID
    "KEGG",        # KEGG:hsa00010,KEGG human pathway
    "WP",          # WP:WP167,WikiPathways
    "SMPDB",       # SMPDB:SMP0000456
    "METACYC",     # METACYC:GLYCOLYSIS
})


def _check_namespaced(value: str, whitelist: frozenset[str], field: str) -> None:
    """Validator helper for namespace-prefixed IDs."""
    if not value:
        raise ValueError(f"{field} must be non-empty namespaced ID")
    if ":" not in value:
        raise ValueError(f"{field} must be 'NS:id' form, got {value!r}")
    ns = value.split(":", 1)[0]
    if ns not in whitelist:
        raise ValueError(
            f"{field} namespace {ns!r} not in whitelist {sorted(whitelist)}"
        )


# ---------------------------------------------------------------------------
# Compound-level reference(v0.3: namespace-prefixed primary_id + soft ChEBI)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnresolvedId:
    """One external ID that ``id_resolve.resolve_ids_to_compound_refs`` could
    not turn into a v0.3 CompoundRef.

    See ``concord.reconcile.id_resolve`` for the resolution algorithm + reasons.
    """
    raw_id: str
    source_namespace: str
    reason: str   # Literal["xref_miss", "inchikey_miss", "invalid_format"]


@dataclass(frozen=True)
class CompoundRef:
    """Structured reference to one metabolite hit in a pathway.

    v0.3 (Q05-NEW-5 拍板):primary_id 永远 namespaced 形式,resolution rule:
    chebi → lipidmaps → hmdb → kegg → inchikey 第一个非空填。
    InChIKey 总能从 SMILES/InChI 算出来(RDKit),所以 primary_id 永远非空。
    """
    primary_id: str                     # "<NS>:<id>" 必填(resolved via priority)
    inchikey: str                       # 27-char full InChIKey,必填(结构 ground truth)
    display_name: str = ""              # ChEBI primary name 或 HMDB synonym

    # 跨库 secondary ID — 全 optional(None 表示该 DB 无映射)
    chebi_id: str | None = None         # 例: "CHEBI:17234"(注意:已含 NS 前缀,与 primary_id 一致)
    lipidmaps_id: str | None = None     # 例: "LIPIDMAPS:LMFA01030001"
    hmdb_id: str | None = None          # 例: "HMDB:HMDB0000122"
    kegg_compound_id: str | None = None # 例: "KEGG:C00031"
    pubchem_cid: str | None = None      # PubChem CID(无 namespace,纯数字)
    metanetx_id: str | None = None      # MNXM...

    def __post_init__(self) -> None:
        _check_namespaced(self.primary_id, COMPOUND_NAMESPACES, "primary_id")
        if not self.inchikey:
            raise ValueError("CompoundRef.inchikey 必填(结构 ground truth)")


def resolve_primary_id(
    *,
    chebi_id: str | None = None,
    lipidmaps_id: str | None = None,
    hmdb_id: str | None = None,
    kegg_compound_id: str | None = None,
    inchikey: str = "",
) -> str:
    """Resolution rule(Q05-NEW-5):按优先级第一个非空者作为 primary_id。

    输入字段可以是 namespaced("CHEBI:17234")或裸 ID("17234"),
    本函数确保返回值是 namespaced。
    InChIKey 兜底假设 W3 RDKit reconciler 已从 SMILES 算出。
    """
    def _ensure_ns(value: str, ns: str) -> str:
        return value if value.startswith(f"{ns}:") else f"{ns}:{value}"

    if chebi_id:
        return _ensure_ns(chebi_id, "CHEBI")
    if lipidmaps_id:
        return _ensure_ns(lipidmaps_id, "LIPIDMAPS")
    if hmdb_id:
        return _ensure_ns(hmdb_id, "HMDB")
    if kegg_compound_id:
        return _ensure_ns(kegg_compound_id, "KEGG")
    if inchikey:
        return f"INCHIKEY:{inchikey}"
    raise ValueError("resolve_primary_id: 所有字段空,无法构 primary_id")


# ---------------------------------------------------------------------------
# Per-pathway hit (v0.3: namespace-prefixed pathway_id)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathwayHit:
    pathway_id: str                     # "<NS>:<id>" 必填,NS ∈ PATHWAY_NAMESPACES
    pathway_name: str
    pathway_id_native: str              # 工具实际输出(KEGG map00010 / human_mfn name 等)
    pathway_db: PathwayDB               # source DB
    score: float
    score_type: ScoreType
    rank: int
    metabolites_hit: tuple[CompoundRef, ...]
    n_metabolites_in_pathway: int = 0
    n_metabolites_input: int = 0
    auxiliary_scores: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_namespaced(self.pathway_id, PATHWAY_NAMESPACES, "pathway_id")


# ---------------------------------------------------------------------------
# Method-level result
# ---------------------------------------------------------------------------


@dataclass
class EnrichmentResult:
    method: EnrichmentMethod
    pathway_db: PathwayDB                # 主源,跨库 merged 用 MERGED
    pathways: tuple[PathwayHit, ...]
    parameters: dict[str, Any]           # 调用 cutoff / db_release / fdr_method / seed / ...

    # Reconciliation traceability
    tool_version: str                    # "sspa 1.0.5" / "mummichog 3.0.0" / "FELLA 1.20.0"
    db_release: str                      # "reactome_v90", "kegg_2025-03" 等
    n_input: int                         # query 输入分子数
    n_input_resolved: int                # 成功映射到 pathway-DB 的分子数
    wall_time_sec: float                 # 实测调用 wall time(单点)

    # ConcordMet schema metadata
    schema_version: str = "concordmet_v0.3"
    tautomer_canonicalized: bool = False  # 见 §2.6 Q-04;输入 metabolite 是否过了 ChEBI is_a 上爬 / RDKit canonicalizer
    chebi_canonicalized: bool = False     # Q-05:输入 metabolite 是否已 normalize 到 ChEBI 主键
    notes: str = ""                       # 任何工具/方法特殊说明

    def __post_init__(self) -> None:
        """Validator(W3 hotfix 2026-05-16):reject n_pathways>0 with 0 hits.

        Sanity-check Check 2 暴露:空 metabolites_hit 通过 all() vacuously True
        是 second-class bug。这条 invariant 强制 producer 必须 wire metabolites_hit
        当 there are any pathways。若 pathways 真为空(input compounds 全 miss
        pathway DB universe),pathways=() 也合法,只是不能 N pathways + 0 refs 同存。
        """
        if self.pathways:
            n_refs = sum(len(p.metabolites_hit) for p in self.pathways)
            if n_refs == 0:
                raise ValueError(
                    f"EnrichmentResult has {len(self.pathways)} pathways but 0 "
                    f"compound hits across all of them — this is structurally "
                    f"vacuous; either pathways should be empty or metabolites_hit "
                    f"must be populated. "
                    f"(method={self.method.value}, db={self.pathway_db.value})"
                )


# ---------------------------------------------------------------------------
# 4 个 normalizer 签名(W3 才实现,这里只是 stub)
# ---------------------------------------------------------------------------


def normalize_sspa_output(
    sspa_raw: Any,                       # sspa 的 DataFrame / dict
    *,
    method: EnrichmentMethod,            # ORA_SSPA / SSGSEA / GSEA_SSPA / KPM_SSPA
    pathway_db: PathwayDB,
    parameters: dict[str, Any],
    tool_version: str,
    db_release: str,
    n_input: int,
    n_input_resolved: int,
    wall_time_sec: float,
    inchikey_lookup: dict[str, str],     # source_id → full InChIKey,W3 由 RDKit reconciler 提供
) -> EnrichmentResult:
    """Normalize a single sspa method output to EnrichmentResult.

    sspa 输出真实形态:`pd.DataFrame`(行=pathway,列=p_value/q_value/n_hit/...);
    ssGSEA 输出 sample × pathway matrix(此处只 normalize 全局 / 单 sample 切片)。

    Known gaps:
      - sspa 多 score 列(EASE / KSpath-specific),先全塞 auxiliary_scores,W3 再决定
        哪些升 primary
      - sspa 的 metabolite ID 用 ChEBI / KEGG,需要 inchikey_lookup 反查
    """
    raise NotImplementedError("normalize_sspa_output — W3 实现")


def normalize_mummichog_output(
    mummichog_raw: Any,                  # mummichog v3 输出(JSON / DataFrame / TSV)
    *,
    pathway_db: PathwayDB,
    parameters: dict[str, Any],
    tool_version: str,
    db_release: str,
    n_input: int,
    n_input_resolved: int,
    wall_time_sec: float,
    mz_to_inchikey: dict[float, list[str]],  # m/z → 候选 InChIKey(W3 由 metabolite_info 提供)
) -> EnrichmentResult:
    """Normalize mummichog output.

    Known gaps:
      - mummichog 输入是 (m/z, p_value, t_score) 三元组,**不是** metabolite list;
        因此 metabolites_hit 需要通过 `mz_to_inchikey` 反查 putative compound
      - mummichog 的 EASE_score 单独存 auxiliary_scores["ease"](已枚举 ScoreType.EASE)
      - mummichog 不返回 q-value(只 raw p),FDR 校正由 ConcordMet 自己做(BH)
    """
    raise NotImplementedError("normalize_mummichog_output — W3 实现")


def normalize_fella_output(
    fella_raw: Any,                      # Docker R subprocess JSON output(v0.3 Q-03 (A) 路径)
    *,
    method: EnrichmentMethod,            # FELLA_RWR / FELLA_DIFFUSION
    parameters: dict[str, Any],
    tool_version: str,
    db_release: str,
    n_input: int,
    n_input_resolved: int,
    wall_time_sec: float,
) -> EnrichmentResult:
    """Normalize FELLA output (v0.3: Docker subprocess path).

    Q-03 (A) Docker 决策 → fella_raw 是 `docker exec` 返回的 JSON(序列化 R data.frame),
    不是 rpy2 直接对象。Docker entrypoint.R 负责 R-side 序列化。

    FELLA 输出 hierarchical(KEGG pathway → module → enzyme → reaction → compound),
    只取 pathway-level node;module/enzyme/reaction 作为 auxiliary_scores 存。

    Known gaps:
      - FELLA 的 score 是 random-walk activity,**不是** p-value;ScoreType=RWR_SCORE
      - FELLA 内部用 KEGG cpd / KEGG pathway ID → pathway_id 走 KEGG: namespace
        (不强行转 Reactome,namespace pivot 后不需要)
      - FELLA 跨 5 层 graph,n_metabolites_in_pathway 只算 compound 层
      - Docker subprocess startup ~2-3s,acceptable
    """
    raise NotImplementedError("normalize_fella_output — W5 Docker 路径实现")


def normalize_ramp_output(
    ramp_raw: Any,                       # tools.benchmark.sub6.ramp_enrichment 已有 EnrichmentReport
    *,
    parameters: dict[str, Any],
    tool_version: str,
    db_release: str,
    n_input: int,
    n_input_resolved: int,
    wall_time_sec: float,
) -> EnrichmentResult:
    """Normalize existing RaMP hypergeometric ORA → ConcordMet schema.

    RaMP 的 EnrichmentReport 已经是 well-typed pydantic;normalize 主要是字段重命名 +
    InChIKey 反查(RaMP 内部用 RaMP source-ID / HMDB)。
    """
    raise NotImplementedError("normalize_ramp_output — W3 实现")


# ---------------------------------------------------------------------------
# 暂未实现的 normalizer(后续 Tier-B/C 工具)
# ---------------------------------------------------------------------------
# normalize_metaboanalystr_output()  — MetaboAnalystR PerformPSEA / PerformMSEA
# normalize_pathintegrate_output()   — Tier-B 工具,W4-W5 才考虑
# normalize_impala_output()
# normalize_piumet_output()


# ---------------------------------------------------------------------------
# 已知 schema gap(W3 实现期需 revisit)
# ---------------------------------------------------------------------------
SCHEMA_GAPS_FOR_W3 = [
    # gap, severity, resolution_plan
    ("sspa 输出多 score 列何时升 primary",            "medium", "W3 D1: 看 sspa 实测列再定"),
    ("FELLA 跨 5 层 graph 的 n_metabolites_in_pathway 定义", "low", "只取 compound 层"),
    ("mummichog 输出无 ChEBI ID(只 KEGG cpd 或 human_mfn name),需 KEGG→ChEBI 反查",  "high",  "W3 D2:走 §5 crosswalk;mummichog normalizer 走 resolve_primary_id() 拿 namespaced primary_id;ChEBI miss 时 fallback KEGG: namespace"),
    ("mummichog 反查全 miss 时 metabolites_hit 处理",  "medium", "Q05-NEW-5 解后改:resolve_primary_id() InChIKey 兜底永远非空,所以 metabolites_hit 不会丢 entry,只是 primary_id namespace 退化到 INCHIKEY:"),
    ("pathway_id 跨 KEGG/Reactome/WikiPathways 不统一",  "RESOLVED-Q05-NEW-4", "v0.3:pathway_id 改 namespace-prefixed,5 NS whitelist(REACT/KEGG/WP/SMPDB/METACYC);__post_init__ validator 强制"),
    ("score_type=COMPOSITE 谁负责生成",                 "high",  "Sprint W6+ ConcordMet aggregator,Investigation 不实现"),
    ("auxiliary_scores 的 float-only 限制(EASE 是 float OK,但若工具输出 list of nodes?)", "low", "W3 D3 看 FELLA 实输出"),
    ("schema_version 升级策略",                         "low",  "已 bump v0.1 → v0.2 → v0.3"),
    ("tautomer_canonicalized=False 时是否拒绝下游 reconciliation",  "medium", "W3 决定;Q-05 后默认要求 chebi_canonicalized=True,tautomer 是 optional"),
    ("CompoundRef chebi_id 强制必填 → unmapped lipid",   "RESOLVED-Q05-NEW-5",  "v0.3:chebi_id 改 optional;新 primary_id 字段 namespace-prefixed,resolve_primary_id() 按 chebi→lipidmaps→hmdb→kegg→inchikey 优先级填;InChIKey 兜底永远非空"),
    ("Reactome compound 12% 覆盖 → KEGG-only pathway 怎么填 pathway_id",  "RESOLVED-Q05-NEW-4",  "v0.3:pathway_id 改 namespace-prefixed;Reactome miss → KEGG:hsa00010 / WP:WP167 / SMPDB:SMP0000456 / METACYC:GLYCOLYSIS。validator 强制 NS ∈ whitelist"),
]


if __name__ == "__main__":
    # Schema sanity v0.3:namespace-prefixed primary keys + validators 工作
    glucose_ref = CompoundRef(
        primary_id=resolve_primary_id(chebi_id="CHEBI:17234", inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N"),
        inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N",
        display_name="D-glucose",
        chebi_id="CHEBI:17234",
        kegg_compound_id="KEGG:C00031",
        hmdb_id="HMDB:HMDB0000122",
        pubchem_cid="5793",
        metanetx_id="MNXM41",
    )
    # 长尾 lipid 无 ChEBI 的 case(Q05-NEW-5 关键 use case)
    unmapped_lipid = CompoundRef(
        primary_id=resolve_primary_id(lipidmaps_id="LIPIDMAPS:LMFA01030001", inchikey="ABCDE-FGHIJ-KLMNO-P"),
        inchikey="ABCDE-FGHIJ-KLMNO-P",
        display_name="palmitic acid (long-tail no ChEBI)",
        lipidmaps_id="LIPIDMAPS:LMFA01030001",
    )
    hit = PathwayHit(
        pathway_id="REACT:R-HSA-71387",           # namespace-prefixed pathway_id
        pathway_name="Glycolysis",
        pathway_id_native="map00010",             # mummichog/sspa 原 native
        pathway_db=PathwayDB.REACTOME,
        score=1e-5,
        score_type=ScoreType.P_VALUE,
        rank=0,
        metabolites_hit=(glucose_ref, unmapped_lipid),
        n_metabolites_in_pathway=20,
        n_metabolites_input=15,
        auxiliary_scores={"ease": 2.3, "n_hit": 8.0},
    )
    # 验证 Reactome miss 时用 KEGG namespace (Q05-NEW-4 关键 use case)
    kegg_only_hit = PathwayHit(
        pathway_id="KEGG:hsa00190",               # Reactome miss → KEGG namespace
        pathway_name="Oxidative phosphorylation",
        pathway_id_native="hsa00190",
        pathway_db=PathwayDB.KEGG,
        score=0.002,
        score_type=ScoreType.P_VALUE,
        rank=1,
        metabolites_hit=(glucose_ref,),
    )
    res = EnrichmentResult(
        method=EnrichmentMethod.MUMMICHOG,
        pathway_db=PathwayDB.KEGG,
        pathways=(hit,),
        parameters={"cutoff": 0.05, "permutations": 1000},
        tool_version="mummichog-2.7.0",
        db_release="kegg_2025-03",
        n_input=120,
        n_input_resolved=98,
        wall_time_sec=14.2,
        tautomer_canonicalized=False,
        chebi_canonicalized=True,
        notes="toy",
    )
    print(f"CompoundRef OK (CHEBI): primary={glucose_ref.primary_id}  name={glucose_ref.display_name}")
    print(f"CompoundRef OK (LIPIDMAPS fallback): primary={unmapped_lipid.primary_id}  name={unmapped_lipid.display_name}")
    print(f"PathwayHit OK (REACT): {hit.pathway_id} ({hit.pathway_name})  "
          f"score={hit.score} ({hit.score_type.value})  n_metabolites_hit={len(hit.metabolites_hit)}")
    print(f"PathwayHit OK (KEGG fallback): {kegg_only_hit.pathway_id} ({kegg_only_hit.pathway_name})")
    print(f"EnrichmentResult OK: {res.method.value} on {res.pathway_db.value} "
          f"({len(res.pathways)} hits, {res.wall_time_sec}s, schema={res.schema_version})")
    # Validator sanity:无 namespace 的 ID 必须 reject
    try:
        bad = PathwayHit(
            pathway_id="R-HSA-71387",  # missing "REACT:" prefix → 必须 raise
            pathway_name="x", pathway_id_native="x", pathway_db=PathwayDB.REACTOME,
            score=0.1, score_type=ScoreType.P_VALUE, rank=0,
            metabolites_hit=(glucose_ref,),
        )
        print("⚠️ Validator MISSED — unnamespaced pathway_id accepted")
    except ValueError as e:
        print(f"Validator OK (rejects unnamespaced pathway_id): {e}")
    try:
        bad = CompoundRef(primary_id="17234", inchikey="x")  # missing CHEBI: prefix
        print("⚠️ Validator MISSED — unnamespaced primary_id accepted")
    except ValueError as e:
        print(f"Validator OK (rejects unnamespaced primary_id): {e}")
    print(f"\nSchema gaps to revisit in W3: {len(SCHEMA_GAPS_FOR_W3)} items")
    for gap, sev, plan in SCHEMA_GAPS_FOR_W3:
        print(f"  [{sev:<6s}] {gap}")
        print(f"           plan: {plan}")
