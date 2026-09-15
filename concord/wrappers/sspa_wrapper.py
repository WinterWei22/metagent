"""sspa Python wrapper(W3 D4).

Provides a single ``run_sspa()`` entry point that hides:
  - synthetic case/ctrl matrix construction (sspa requires sample-level data)
  - R-NEW-15 dtype fix (sspa pathway_df cells are int → str conversion)
  - 4 method support: ssgsea / gsva / kpca / zscore
  - 3 pathway DB support: reactome / kegg / metacyc (currently delegated to sspa.process_*)

Output is RAW (pandas DataFrame from sspa) — call ``concord.normalize.sspa_norm
.normalize_sspa_output()`` to convert to v0.3 EnrichmentResult.

Usage:
    >>> from concord.wrappers.sspa_wrapper import run_sspa
    >>> from concord.lookup.chebi import ChebiLookup
    >>> chebi = ChebiLookup()
    >>> refs = [chebi.lookup_by_xref("KEGG", "C00031"),
    ...         chebi.lookup_by_xref("HMDB", "HMDB0000234")]
    >>> raw = run_sspa(compound_refs=[r for r in refs if r],
    ...                method="ora",
    ...                pathway_db="reactome",
    ...                organism="Homo sapiens")
    >>> # raw is a pandas DataFrame of pathway-level ORA results
"""
from __future__ import annotations

import logging
import time
from typing import Any, Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SspaMethod = Literal["ora", "ssgsea", "gsva", "kpca", "zscore"]
PathwayDb = Literal["reactome", "kegg", "metacyc"]

DEFAULT_ORGANISM = "Homo sapiens"
DEFAULT_N_CASE = 5
DEFAULT_N_CTRL = 5
DEFAULT_CASE_MEAN = 5.0      # high-abundance in case samples
DEFAULT_BG_MEAN = 1.0        # baseline in all samples


# ---------------------------------------------------------------------------
# Pathway df normalization (R-NEW-15 fix)
# ---------------------------------------------------------------------------


def _normalize_pathway_df(pathway_df: pd.DataFrame) -> pd.DataFrame:
    """R-NEW-15 fix: sspa pathway_df cells are int (ChEBI numeric).

    Cast all non-Pathway_name cells to str so downstream matching against our
    ChEBI string columns works.
    """
    out = pathway_df.copy()
    for col in out.columns:
        if col == "Pathway_name":
            continue
        out[col] = out[col].apply(
            lambda v: str(int(v)) if pd.notna(v) and not isinstance(v, str) else v
        )
    return out


def _extract_pathway_universe(pathway_df: pd.DataFrame) -> set[str]:
    """All distinct compound IDs that appear in pathway_df rows.

    Used to build the universe of the synthetic case/ctrl matrix.
    """
    out: set[str] = set()
    for _pid, row in pathway_df.iterrows():
        for col, val in row.items():
            if col == "Pathway_name":
                continue
            if pd.isna(val):
                continue
            s = str(val).strip()
            if s:
                out.add(s)
    return out


# ---------------------------------------------------------------------------
# Pathway DB loader (cached)
# ---------------------------------------------------------------------------


_PATHWAY_DB_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


def _load_pathway_db(pathway_db: PathwayDb, organism: str) -> pd.DataFrame:
    """Load + cache + R-NEW-15 normalize the sspa pathway dataframe."""
    key = (pathway_db, organism)
    if key in _PATHWAY_DB_CACHE:
        return _PATHWAY_DB_CACHE[key]
    import sspa  # delayed import — heavy
    if pathway_db == "reactome":
        df = sspa.process_reactome(organism=organism)
    elif pathway_db == "kegg":
        df = sspa.process_kegg(organism=organism)
    elif pathway_db == "metacyc":
        # sspa.process_pathbank / process_gmt — MetaCyc not directly supported;
        # placeholder for W4 expansion
        raise NotImplementedError(
            "MetaCyc loading not yet wired in sspa wrapper (W4 task)"
        )
    else:
        raise ValueError(f"unsupported pathway_db: {pathway_db}")
    df = _normalize_pathway_df(df)
    _PATHWAY_DB_CACHE[key] = df
    logger.info("loaded pathway_db=%s organism=%s shape=%s", pathway_db, organism, df.shape)
    return df


# ---------------------------------------------------------------------------
# Synthetic matrix construction
# ---------------------------------------------------------------------------


def _synth_matrix(
    diff_compounds: list[str],
    pathway_universe: set[str],
    *,
    n_case: int = DEFAULT_N_CASE,
    n_ctrl: int = DEFAULT_N_CTRL,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build (mat, metadata) for sspa case/ctrl analysis.

    case rows: differential compounds at ~N(case_mean, 0.5),others ~N(bg_mean, 0.1)
    ctrl rows: all ~N(bg_mean, 0.1)
    """
    rng = np.random.default_rng(seed)
    all_compounds = sorted(pathway_universe)
    mat = pd.DataFrame(
        rng.normal(loc=DEFAULT_BG_MEAN, scale=0.1, size=(n_case + n_ctrl, len(all_compounds))),
        columns=all_compounds,
    )
    for cid in diff_compounds:
        if cid in mat.columns:
            mat.loc[: n_case - 1, cid] = rng.normal(loc=DEFAULT_CASE_MEAN, scale=0.5, size=n_case)
    metadata = pd.Series(["case"] * n_case + ["ctrl"] * n_ctrl, index=mat.index)
    return mat, metadata


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _refs_to_chebi_numeric(compound_refs: list[Any]) -> list[str]:
    """Extract ChEBI numeric str from CompoundRef-like objects.

    Accepts: CompoundRef (with primary_id "CHEBI:NNNNN"), CompoundRecord
    (with chebi_id), or raw "CHEBI:NNNNN" / "NNNNN" strings.
    """
    out = []
    for ref in compound_refs:
        if ref is None:
            continue
        if isinstance(ref, str):
            s = ref.replace("CHEBI:", "").strip()
            if s:
                out.append(s)
            continue
        # Dataclass / object with primary_id ("CHEBI:NNNNN") or chebi_id
        pid = getattr(ref, "primary_id", None)
        if pid and pid.startswith("CHEBI:"):
            out.append(pid.replace("CHEBI:", ""))
            continue
        cid = getattr(ref, "chebi_id", None)
        if cid:
            out.append(str(cid).replace("CHEBI:", ""))
    return out


def run_sspa(
    *,
    compound_refs: list[Any],
    method: SspaMethod = "ora",
    pathway_db: PathwayDb = "reactome",
    organism: str = DEFAULT_ORGANISM,
    n_case: int = DEFAULT_N_CASE,
    n_ctrl: int = DEFAULT_N_CTRL,
    seed: int = 42,
    da_cutoff: float = 0.05,
    da_testtype: str = "ttest",
) -> dict[str, Any]:
    """Run sspa enrichment.

    Returns:
        dict with keys:
            "raw":             pd.DataFrame from sspa(method-specific shape)
            "method":          str
            "pathway_db":      str
            "n_input":         int(input compound count)
            "n_input_resolved":int(input compounds that mapped to pathway_db universe)
            "wall_time_sec":   float
            "tool_version":    "sspa-1.0.4"
            "db_release":      e.g. "reactome_2024_q3"
            "parameters":      dict echo

    Raises:
        ValueError on unsupported method / db / empty input.
        NotImplementedError on metacyc (W4 task).
    """
    if not compound_refs:
        raise ValueError("compound_refs is empty")

    t0 = time.time()
    pathway_df = _load_pathway_db(pathway_db, organism)
    universe = _extract_pathway_universe(pathway_df)

    diff_chebi = _refs_to_chebi_numeric(compound_refs)
    if not diff_chebi:
        raise ValueError(
            "Could not extract any ChEBI numeric ID from compound_refs "
            f"(got {len(compound_refs)} refs)"
        )
    n_resolved = sum(1 for c in diff_chebi if c in universe)

    mat, metadata = _synth_matrix(
        diff_chebi, universe, n_case=n_case, n_ctrl=n_ctrl, seed=seed,
    )

    import sspa

    if method == "ora":
        ora = sspa.sspa_ora(mat, metadata, pathway_df,
                            DA_cutoff=da_cutoff, DA_testtype=da_testtype)
        raw = ora.over_representation_analysis()
    elif method == "ssgsea":
        # R-NEW-17 fix (W5 background F): bypass sspa.sspa_ssGSEA because it
        # passes ``mat.T`` directly to gseapy.ssgsea, but gseapy._check_data
        # calls ``set_index(keys=exprs.columns[0])`` — which treats the first
        # *column* as gene identifiers and silently replaces the compound-ID
        # index with the first sample's float values, producing
        # "no gene sets passed filtering". Workaround: reset_index() so
        # compound IDs land in column 0 where gseapy expects them.
        import gseapy
        from sspa import utils as _sspa_utils
        pathway_dict = _sspa_utils.pathwaydf_to_dict(pathway_df)
        ssgsea_res = gseapy.ssgsea(
            data=mat.T.reset_index(),
            gene_sets=pathway_dict,
            min_size=2,
            outdir=None,
            sample_norm_method="rank",
            no_plot=True,
        )
        # Mirror sspa.sspa_ssGSEA.transform output shape: pathways × samples
        # (rows = samples, cols = pathways).
        scores = ssgsea_res.res2d.pivot(index="Term", columns="Name", values="NES").T
        raw = pd.DataFrame(scores, index=mat.index).astype(float)
    elif method == "gsva":
        model = sspa.sspa_gsva(pathway_df, min_entity=2) \
            if hasattr(sspa, "sspa_gsva") else None
        if model is None:
            raise NotImplementedError("sspa_gsva not available in sspa 1.0.4")
        model.fit(mat)
        raw = model.transform(mat)
    elif method == "kpca":
        model = sspa.sspa_KPCA(pathway_df, min_entity=2)
        model.fit(mat)
        raw = model.transform(mat)
    elif method == "zscore":
        model = sspa.sspa_zscore(pathway_df, min_entity=2)
        model.fit(mat)
        raw = model.transform(mat)
    else:
        raise ValueError(f"unsupported method: {method}")

    wall = time.time() - t0
    return {
        "raw": raw,
        "method": method,
        "pathway_db": pathway_db,
        "organism": organism,
        "n_input": len(diff_chebi),
        "n_input_resolved": n_resolved,
        "wall_time_sec": wall,
        "tool_version": getattr(sspa, "__version__", "sspa-1.0.4"),
        "db_release": f"{pathway_db}_unspecified",  # W3 best-effort; W4 pin
        # ssGSEA / KPCA / GSVA / zscore normalizers need these to populate
        # metabolites_hit via pathway-membership ∩ input intersection;
        # ORA's normalizer ignores them (uses DA_Metabolites_ID column instead).
        "_pathway_df": pathway_df,
        "_input_chebi_numeric": diff_chebi,
        "parameters": {
            "da_cutoff": da_cutoff,
            "da_testtype": da_testtype,
            "n_case": n_case,
            "n_ctrl": n_ctrl,
            "seed": seed,
        },
    }
