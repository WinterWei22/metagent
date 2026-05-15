"""§3 EnrichmentResult schema 草案(Investigation 阶段,**不实现 normalizer body**).

设计原则:
1. 覆盖所有 Tier-A 工具的真实输出(sspa, mummichog, FELLA, RaMP ORA)
2. score_type 显式枚举,避免后续 4-axis aggregation 时 misread
3. metabolites_hit 使用 **InChIKey full(27 字符)** 作为 internal ID,block14 单独存
4. 留 auxiliary_scores: dict 给每工具特定 metric(EASE / NES / RWR activity / ...)
5. parameters 记录调用时的 cutoff / db release,保 reproducibility
6. tautomer_canonicalized 字段从 §2.6 Q-04 落地

normalizer 只签名,**body 是 NotImplementedError**(Sprint W3 才实现)。

NOTE: 这是 **Investigation 草案**,Sprint W3 实现时可能修改字段名 / 加 schema_version。
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
# Per-pathway hit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathwayHit:
    pathway_id: str                     # canonical ID (Reactome stable ID 主键, see §5)
    pathway_id_native: str              # 工具实际输出的 ID(KEGG map00010 等)
    pathway_db: PathwayDB
    pathway_name: str
    score: float
    score_type: ScoreType
    rank: int                           # 0-based, 工具自报(若工具没排名则 by score)
    metabolites_hit: tuple[str, ...]    # full InChIKey list(27 字符,frozen for hashing)
    metabolites_hit_block14: tuple[str, ...] = ()  # block14 for cluster joins
    n_metabolites_in_pathway: int = 0   # pathway 内总数(ORA 需要)
    n_metabolites_input: int = 0        # query 输入总数(ORA 需要)

    # 工具特定附加 score(EASE / NES / RWR activity / ...)
    auxiliary_scores: dict[str, float] = field(default_factory=dict)


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
    schema_version: str = "concordmet_v0.1"
    tautomer_canonicalized: bool = False  # 见 §2.6 Q-04;输入 metabolite 是否过了 tautomer canonicalizer
    notes: str = ""                       # 任何工具/方法特殊说明


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
    fella_raw: Any,                      # rpy2 调用返回的 R list / data.frame
    *,
    method: EnrichmentMethod,            # FELLA_RWR / FELLA_DIFFUSION
    parameters: dict[str, Any],
    tool_version: str,
    db_release: str,
    n_input: int,
    n_input_resolved: int,
    wall_time_sec: float,
) -> EnrichmentResult:
    """Normalize FELLA output.

    FELLA 输出 hierarchical(KEGG pathway → module → enzyme → reaction → compound),
    我们只取 pathway-level node;module/enzyme/reaction 作为 auxiliary_scores 存。

    Known gaps:
      - FELLA 的 score 是 random-walk activity,**不是** p-value;需 ScoreType=RWR_SCORE
      - FELLA 内部用 KEGG cpd ID,需 §5 crosswalk 转 Reactome
      - FELLA 跨 5 层 graph,n_metabolites_in_pathway 含义需明确(只算 compound 层)
      - rpy2 K=10 并发 spike 失败时此 normalizer 不会被调用(见 Q-03 escalation)
    """
    raise NotImplementedError("normalize_fella_output — W3 实现")


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
    ("mummichog 反查 mz_to_inchikey 失败时 metabolites_hit 留空",  "high",  "W3 D2 设 fallback: 留 None + auxiliary_scores 备注"),
    ("Pathway ID 跨 KEGG/Reactome/WikiPathways 不统一",  "high", "见 §5 crosswalk,Reactome 主键 + KEGG fallback"),
    ("score_type=COMPOSITE 谁负责生成",                 "high",  "Sprint W6+ ConcordMet aggregator,Investigation 不实现"),
    ("auxiliary_scores 的 float-only 限制(EASE 是 float OK,但若工具输出 list of nodes?)", "low", "W3 D3 看 FELLA 实输出"),
    ("schema_version 升级策略",                         "low",  "W3 W4 任一字段变 → bump v0.1 → v0.2"),
    ("tautomer_canonicalized=False 时是否拒绝下游 reconciliation",  "medium", "W3 决定;若严格要求 canon,则 ETL 期 reject"),
]


if __name__ == "__main__":
    # Schema sanity:确保 dataclass 可实例化(空 PathwayHit + EnrichmentResult)
    hit = PathwayHit(
        pathway_id="R-HSA-71387",
        pathway_id_native="map00010",
        pathway_db=PathwayDB.REACTOME,
        pathway_name="Glycolysis",
        score=1e-5,
        score_type=ScoreType.P_VALUE,
        rank=0,
        metabolites_hit=("WQZGKKKJIJFFOK-GASJEMHNSA-N",),
        n_metabolites_in_pathway=20,
        n_metabolites_input=15,
        auxiliary_scores={"ease": 2.3, "n_hit": 8.0},
    )
    res = EnrichmentResult(
        method=EnrichmentMethod.MUMMICHOG,
        pathway_db=PathwayDB.KEGG,
        pathways=(hit,),
        parameters={"cutoff": 0.05, "permutations": 1000},
        tool_version="mummichog-3.0.0",
        db_release="kegg_2025-03",
        n_input=120,
        n_input_resolved=98,
        wall_time_sec=14.2,
        tautomer_canonicalized=False,
        notes="toy",
    )
    print(f"PathwayHit OK: {hit.pathway_id} score={hit.score} ({hit.score_type.value})")
    print(f"EnrichmentResult OK: {res.method.value} on {res.pathway_db.value} "
          f"({len(res.pathways)} hits, {res.wall_time_sec}s)")
    print(f"\nSchema gaps to revisit in W3: {len(SCHEMA_GAPS_FOR_W3)} items")
    for gap, sev, plan in SCHEMA_GAPS_FOR_W3:
        print(f"  [{sev:<6s}] {gap}")
        print(f"           plan: {plan}")
