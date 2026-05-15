"""§3 EnrichmentResult schema — Q-05 PIVOT v0.2(双主键架构).

设计原则(2026-05-15 Q-05 拍板后更新):
1. 覆盖所有 Tier-A 工具的真实输出(sspa, mummichog, FELLA, RaMP ORA)
2. **双主键架构**:
   - Compound 层:**ChEBI ID** 主键(100% 覆盖,见 §2.5)
   - Pathway 层:**Reactome stable ID**(R-HSA-XXX)主键
   - Reporting:**KEGG ID**(`hsa00XXX` / `C00XXX`)用于 paper figure/table
   - Fallback ground truth:**InChIKey**(结构哈希,做立体/互变冲突解决)
3. metabolites_hit 不再是 `list[str]`,改成 `list[CompoundRef]` 结构化引用
4. score_type 显式枚举
5. auxiliary_scores: dict 给每工具特定 metric
6. parameters 记录 cutoff / db release,保 reproducibility
7. tautomer_canonicalized 字段保留(Q-04 处置改成 ChEBI is_a hierarchy 向上爬,见 §6)

normalizer 只签名,**body 是 NotImplementedError**(Sprint W3 才实现)。

CHANGELOG:
  v0.1 (Session 2 早期) — InChIKey-only metabolites_hit
  v0.2 (Q-05 pivot) — CompoundRef 结构化;PathwayHit.pathway_id=Reactome,新增 kegg_id;
                       metabolites_hit: tuple[CompoundRef, ...]
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
# Compound-level reference(Q-05 pivot: 双主键架构,ChEBI 主)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompoundRef:
    """Structured reference to one metabolite hit in a pathway.

    Q-05 决策(2026-05-15):ChEBI 是 100% 覆盖的 lingua franca,作为 compound 主键。
    InChIKey 作为结构 ground truth fallback(用于 stereo/tautomer 冲突解决)。

    chebi_id 是必填;若工具输出没给 ChEBI(如 mummichog 给 KEGG cpd),
    normalizer 需先做 KEGG cpd → ChEBI 反查(via §5 crosswalk)再构 CompoundRef。
    """
    chebi_id: str                       # CHEBI:NNNNN(主键,100% 覆盖)
    inchikey: str = ""                  # 27-char full InChIKey(结构 ground truth)
    display_name: str = ""              # ChEBI primary name 或 HMDB synonym

    # 跨库 secondary ID(reporting / fallback;normalizer 可选填)
    kegg_compound_id: str = ""          # C00031 等
    hmdb_id: str = ""                   # HMDB0000122 等
    pubchem_cid: str = ""               # PubChem CID
    metanetx_id: str = ""               # MNXM...


# ---------------------------------------------------------------------------
# Per-pathway hit (Q-05 v0.2: Reactome 主键 + KEGG reporting fallback)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathwayHit:
    pathway_id: str                     # **Reactome stable ID 主键** (R-HSA-XXX)
    pathway_name: str                   # Reactome primary name
    kegg_id: str | None                 # KEGG mapID (hsa00XXX) — reporting / fallback
    pathway_id_native: str              # 工具实际输出的 ID(KEGG map00010 / human_mfn name / etc.)
    pathway_db: PathwayDB               # 来源 DB(reactome / kegg / wikipathways / metacyc / ...)
    score: float
    score_type: ScoreType
    rank: int                           # 0-based, 工具自报(若工具没排名则 by score)
    metabolites_hit: tuple[CompoundRef, ...]  # 结构化引用 list(Q-05 改:从 InChIKey str → CompoundRef)
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
    schema_version: str = "concordmet_v0.2"
    tautomer_canonicalized: bool = False  # 见 §2.6 Q-04;输入 metabolite 是否过了 ChEBI is_a 上爬 / RDKit canonicalizer
    chebi_canonicalized: bool = False     # Q-05:输入 metabolite 是否已 normalize 到 ChEBI 主键
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
    ("mummichog 输出无 ChEBI ID(只 KEGG cpd 或 human_mfn name),需 KEGG→ChEBI 反查",  "high",  "W3 D2:走 §5 crosswalk(ChEBI ↔ KEGG via ChEBI database_accession.tsv)"),
    ("mummichog 反查失败时 CompoundRef.chebi_id 必填规则",  "high", "W3 D2 fallback:若 KEGG→ChEBI miss,用 InChIKey 反查 ChEBI(via ChEBI structures.tsv);全 miss 则该 metabolite 不进 metabolites_hit"),
    ("pathway_id (Reactome) 跨 KEGG/Reactome/WikiPathways 不统一",  "RESOLVED-Q05", "§5 crosswalk:工具原 pathway_id → ChEBI2Reactome.txt 反查 Reactome stable ID;失败则 pathway_id=空字符串,kegg_id 作为唯一标识"),
    ("score_type=COMPOSITE 谁负责生成",                 "high",  "Sprint W6+ ConcordMet aggregator,Investigation 不实现"),
    ("auxiliary_scores 的 float-only 限制(EASE 是 float OK,但若工具输出 list of nodes?)", "low", "W3 D3 看 FELLA 实输出"),
    ("schema_version 升级策略",                         "low",  "已 bump v0.1 → v0.2(Q-05 pivot)"),
    ("tautomer_canonicalized=False 时是否拒绝下游 reconciliation",  "medium", "W3 决定;Q-05 后默认要求 chebi_canonicalized=True,tautomer 是 optional"),
    ("CompoundRef.chebi_id 强制必填 → 没 ChEBI ID 的 metabolite(如 unmapped LIPID MAPS)怎么处理",   "Q05-NEW-high",  "三选一:(a) 不进 metabolites_hit;(b) chebi_id=`UNMAPPED:LMxxxxx`;(c) 加新字段 unmapped_external_refs。W3 D2 拍。"),
    ("Reactome pathway 12% compound 覆盖 → 若 pathway 来自 KEGG/MetaCyc/WikiPathways 而无 Reactome 对应,pathway_id 怎么填",  "Q05-NEW-high",  "三选一:(a) pathway_id=空字符串,kegg_id 主显示;(b) pathway_id=`UNMAPPED:KEGG:hsa00010`;(c) 加新字段 canonical_pathway_db。W3 D1 拍。"),
]


if __name__ == "__main__":
    # Schema sanity:确保 v0.2 dataclass 可实例化(CompoundRef + PathwayHit + EnrichmentResult)
    glucose_ref = CompoundRef(
        chebi_id="CHEBI:17234",
        inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N",
        display_name="D-glucose",
        kegg_compound_id="C00031",
        hmdb_id="HMDB0000122",
        pubchem_cid="5793",
        metanetx_id="MNXM41",
    )
    hit = PathwayHit(
        pathway_id="R-HSA-71387",                 # Reactome stable ID 主键
        pathway_name="Glycolysis",
        kegg_id="hsa00010",                       # reporting fallback
        pathway_id_native="map00010",             # mummichog/sspa 实际输出
        pathway_db=PathwayDB.REACTOME,
        score=1e-5,
        score_type=ScoreType.P_VALUE,
        rank=0,
        metabolites_hit=(glucose_ref,),
        n_metabolites_in_pathway=20,
        n_metabolites_input=15,
        auxiliary_scores={"ease": 2.3, "n_hit": 8.0},
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
    print(f"CompoundRef OK: {glucose_ref.chebi_id} ({glucose_ref.display_name}, KEGG {glucose_ref.kegg_compound_id})")
    print(f"PathwayHit OK: {hit.pathway_id} ({hit.pathway_name}, KEGG {hit.kegg_id})  "
          f"score={hit.score} ({hit.score_type.value})  metabolites_hit={len(hit.metabolites_hit)}")
    print(f"EnrichmentResult OK: {res.method.value} on {res.pathway_db.value} "
          f"({len(res.pathways)} hits, {res.wall_time_sec}s, schema={res.schema_version})")
    print(f"\nSchema gaps to revisit in W3: {len(SCHEMA_GAPS_FOR_W3)} items")
    for gap, sev, plan in SCHEMA_GAPS_FOR_W3:
        print(f"  [{sev:<6s}] {gap}")
        print(f"           plan: {plan}")
