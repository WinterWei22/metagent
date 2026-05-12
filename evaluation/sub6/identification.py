"""Sub-6A spectrum identification — top-1 candidate per spectrum.

Two strategies, selectable per task:

* ``"library_search"`` — real end-to-end identification. Calls
  ``tools.library_search`` with no candidate_pool (full GNPS scan),
  filters out self-match by ``source_id`` (eval guide §3 pitfall 1),
  takes the top-1 surviving candidate. ``top_k`` is set higher than 1 so
  there is still a candidate left after exclusion pruning.

* ``"perfect_id"`` — *upper-bound* baseline. Bypasses library_search and
  treats the spectrum's GT InChIKey as the identification. The metabolite
  list fed to the LLM is the spectrum-derived InChIKey set, so the
  resulting metric isolates "LLM reasoning quality" from "identification
  accuracy." Useful when the goal is to bound how much of Sub-6A's
  end-to-end error comes from identification vs reasoning.

Identification accuracy (top-1 InChIKey first-block vs the spectrum's
ground-truth InChIKey first-block) is reported per spectrum so the Sub-6
report can decompose end-to-end errors. Under ``perfect_id`` it is
trivially 1.0 (by construction).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from schemas import LibrarySearchRequest, Spectrum

from evaluation.sub6.compound_lookup import CompoundLookup

logger = logging.getLogger(__name__)


# Phase 6.3: parse modcos/msclip out of the Candidate.explain string. The
# tools/library_search _build_candidate emits a fixed format
#   "Library match[ from <source_id>] scored X.XXX (modified cosine Y.YYY + ms-clip Z.ZZZ)."
# We rely on this contract rather than touching schemas/common.py. Parser is
# defensive — missing values return None and downstream code falls back to
# Candidate.score.
_EXPLAIN_MODCOS_RE = re.compile(r"modified\s+cosine\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_EXPLAIN_MSCLIP_RE = re.compile(r"ms[-\s]?clip\s+(\d+(?:\.\d+)?)", re.IGNORECASE)


def _candidate_score_components(cand) -> tuple[float | None, float | None]:
    """Return ``(modcos, msclip_rescaled)`` parsed from Candidate.explain.

    Either component is ``None`` when its retriever did not contribute (e.g.
    GNPS-only run has msclip=None). ``cand.score`` is always the fused max.
    """
    explain = getattr(cand, "explain", "") or ""
    modcos = None
    m = _EXPLAIN_MODCOS_RE.search(explain)
    if m:
        try:
            modcos = float(m.group(1))
        except ValueError:
            pass
    msclip = None
    m2 = _EXPLAIN_MSCLIP_RE.search(explain)
    if m2:
        try:
            msclip = float(m2.group(1))
        except ValueError:
            pass
    return modcos, msclip


PrimaryRetriever = Literal["modcos", "msclip"]


# A "library search function" — the top-level callable matching
# ``tools.library_search.library_search``. Tests inject a mock; we lazy-load
# the real one at call time so importing this module does not pull in
# matchms / ms-clip / RDKit.
LibSearchFn = Callable[[LibrarySearchRequest], object]


IdStrategy = Literal["library_search", "perfect_id"]


def _default_library_search() -> LibSearchFn:
    """Lazy-import library_search — keeps the module importable in
    environments where matchms / ms-clip are unavailable (relevant only
    when ``library_search`` strategy is used)."""
    from tools.library_search import library_search

    return library_search


@dataclass
class SpectrumIdentification:
    """One spectrum's top-1 identification result.

    ``predicted_*`` fields are None when no candidate survived after
    exclusion-filter pruning. ``correct_top1`` compares
    InChIKey first-blocks; None if predicted_inchikey is None.
    """

    spectrum_id: str
    source_id: str | None
    gt_inchikey_first_block: str | None
    predicted_inchikey_first_block: str | None
    predicted_name: str | None
    predicted_smiles: str | None
    predicted_score: float | None
    predicted_source_id: str | None
    correct_top1: bool | None
    n_candidates_returned: int
    n_after_exclusion: int
    strategy: IdStrategy = "library_search"
    error: str | None = None
    excluded_source_ids_hit: list[str] = field(default_factory=list)
    # Phase 6.2 rerank output (None when --rerank-with not set).
    rerank_applied: tuple[str, ...] = field(default_factory=tuple)
    peak_evidence: dict[str, Any] | None = None
    # Phase 6.3 LLM-as-reranker output (None unless reranker_mode="llm").
    primary_retriever: str = "modcos"
    reranker_mode: str = "weighted"
    llm_rerank_narrative: str | None = None
    llm_rerank_peak_claims: list[str] = field(default_factory=list)
    llm_rerank_confidence: str | None = None
    llm_rerank_fallback_used: bool = False
    llm_rerank_parse_error: str | None = None
    # Phase 6.7-A: LLM's preferred ordering over the rerank head (length =
    # rerank_top_k). Used to compute MRR / top-K accuracy when --dump-ranks is on.
    llm_rerank_ranked_indices: list[int] = field(default_factory=list)
    # Phase 6.7-A: top-K ranked candidates after primary retriever (before
    # rerank). Populated when --dump-ranks is on. Each entry:
    # {smiles, source_id, msclip, modcos, score, ik14}.
    ranked_candidates: list[dict[str, Any]] = field(default_factory=list)


def task_spectrum_to_schema(sp: dict) -> Spectrum:
    """Convert a Sub-6A task spectrum record into a `schemas.Spectrum`.

    Task records carry raw `peaks` (list of [mz, intensity] pairs); the
    schema requires sorted mz and intensities normalised to [0, 1] with
    base peak at 1.0. We perform that normalisation here.
    """
    peaks = sp.get("peaks") or []
    if not peaks:
        raise ValueError(f"spectrum {sp.get('spectrum_id')} has no peaks")
    pairs = sorted(((float(mz), float(intensity)) for mz, intensity in peaks), key=lambda p: p[0])
    mz_list = [p[0] for p in pairs]
    raw_int = [p[1] for p in pairs]
    base = max(raw_int)
    if base <= 0:
        raise ValueError(f"spectrum {sp.get('spectrum_id')} has non-positive base peak")
    norm = [v / base for v in raw_int]

    ion_mode = sp.get("ion_mode") or "positive"
    if ion_mode not in ("positive", "negative"):
        ion_mode = "positive"

    adduct = sp.get("adduct") or "[M+H]+"
    # Tasks emit "[M+H]1+" — schema accepts free-text but downstream tools
    # expect the standard "[M+H]+" form. Normalise common patterns.
    adduct = adduct.replace("1+", "+").replace("1-", "-")

    ce = sp.get("collision_energy")
    if ce is not None:
        try:
            ce = float(ce)
        except (TypeError, ValueError):
            ce = None

    return Spectrum(
        mz=mz_list,
        intensity=norm,
        precursor_mz=float(sp["precursor_mz"]),
        adduct=adduct,
        ionization_mode=ion_mode,
        collision_energy=ce,
    )


def identify_spectrum_perfect(
    sp: dict,
    *,
    lookup: CompoundLookup | None = None,
) -> SpectrumIdentification:
    """Perfect-identification stub: emit the spectrum's GT InChIKey as
    the prediction. Used for the *upper-bound* Sub-6A baseline.

    ``lookup`` is consulted to recover a human-readable compound name
    from the InChIKey first-block. When the InChIKey is not in the
    curated pool (rare for Sub-6A, since differential_spectra are pulled
    from compounds that are present), we fall back to a placeholder name
    so the LLM still sees the InChIKey.
    """
    spectrum_id = str(sp.get("spectrum_id", "?"))
    source_id = sp.get("source_id")
    gt_ik = sp.get("inchikey_first_block")
    if not gt_ik:
        return SpectrumIdentification(
            spectrum_id=spectrum_id,
            source_id=source_id,
            gt_inchikey_first_block=None,
            predicted_inchikey_first_block=None,
            predicted_name=None,
            predicted_smiles=None,
            predicted_score=None,
            predicted_source_id=None,
            correct_top1=None,
            n_candidates_returned=0,
            n_after_exclusion=0,
            strategy="perfect_id",
            error="perfect_id: spectrum has no inchikey_first_block",
        )

    # Recover a name from the curated pool when available; fall back to
    # a placeholder so the LLM never sees a None.
    pred_name = None
    if lookup is not None:
        pred_name = lookup.name_for(gt_ik)
    if not pred_name:
        pred_name = f"unknown ({gt_ik})"

    return SpectrumIdentification(
        spectrum_id=spectrum_id,
        source_id=source_id,
        gt_inchikey_first_block=gt_ik,
        predicted_inchikey_first_block=gt_ik,
        predicted_name=pred_name,
        predicted_smiles=None,
        predicted_score=1.0,
        predicted_source_id=source_id,
        correct_top1=True,
        n_candidates_returned=1,
        n_after_exclusion=1,
        strategy="perfect_id",
        error=None,
    )


def identify_spectrum(
    sp: dict,
    *,
    exclusion_source_ids: set[str] | frozenset[str],
    top_k: int = 20,
    min_score: float = 0.0,
    libraries: tuple[str, ...] = ("gnps",),
    library_search_fn: LibSearchFn | None = None,
    strategy: IdStrategy = "library_search",
    lookup: CompoundLookup | None = None,
    mass_tolerance_ppm: float | None = None,
    rerank_with: tuple[str, ...] = (),
    rerank_top_k: int = 5,
    cfmid_cache_dir: Path | None = None,
    primary_retriever: PrimaryRetriever = "modcos",
    reranker_mode: Literal["weighted", "llm", "none", "conditional"] = "weighted",
    conditional_fallback: Literal["weighted", "llm"] = "weighted",
    candidate_pool: list | None = None,
    use_gnps: bool | None = None,
    llm_chat_fn: Callable[..., str] | None = None,
    llm_chat_kwargs: dict[str, Any] | None = None,
) -> SpectrumIdentification:
    """Top-1 identification for one spectrum, with self-match exclusion.

    Strategies:
      ``"library_search"`` (default) — call library_search and filter
      ``"perfect_id"`` — return the spectrum's own GT InChIKey

    The library_search default uses only the ``gnps`` library and no
    in-house retriever — we want to compare query spectra against GNPS
    reference spectra, not against arbitrary SMILES. Set ``libraries``
    to add ``"inhouse"`` for ms-clip when needed.

    ``mass_tolerance_ppm`` (Phase A): when non-None, library_search's
    Path B narrows the GNPS pool to records whose precursor_mz is within
    ±tol_ppm of the query — see schemas.LibrarySearchRequest.
    ``exclusion_source_ids`` is *also* threaded into the request via
    ``LibrarySearchRequest.excluded_source_ids`` so library_search can
    drop self-matches *before* its dedup-by-SMILES step. The post-call
    exclusion sweep below is preserved as an audit (existing logic
    stays per the original Phase A scope contract).
    """
    if strategy == "perfect_id":
        return identify_spectrum_perfect(sp, lookup=lookup)

    spectrum_id = str(sp.get("spectrum_id", "?"))
    source_id = sp.get("source_id")
    gt_ik = sp.get("inchikey_first_block")

    try:
        spec = task_spectrum_to_schema(sp)
    except Exception as exc:
        return SpectrumIdentification(
            spectrum_id=spectrum_id,
            source_id=source_id,
            gt_inchikey_first_block=gt_ik,
            predicted_inchikey_first_block=None,
            predicted_name=None,
            predicted_smiles=None,
            predicted_score=None,
            predicted_source_id=None,
            correct_top1=None,
            n_candidates_returned=0,
            n_after_exclusion=0,
            error=f"spectrum_conversion: {type(exc).__name__}: {exc}",
        )

    # Phase 6.6: optional pre-filtered candidate_pool (PubChem candidates for
    # CASMI). When provided, library_search Path A scores ONLY the pool and
    # skips the GNPS scan. ``use_gnps`` (when False) drops "gnps" from
    # libraries so GNPS leakage cannot bleed into a CASMI run that also
    # injects a PubChem pool.
    libs_eff = list(libraries)
    if use_gnps is False and "gnps" in libs_eff:
        libs_eff = [l for l in libs_eff if l != "gnps"]
    req = LibrarySearchRequest(
        spectrum=spec,
        candidate_pool=candidate_pool,
        top_k=top_k,
        min_score=min_score,
        libraries=libs_eff,
        mass_tolerance_ppm=mass_tolerance_ppm,
        excluded_source_ids=sorted(exclusion_source_ids) or None,
    )
    fn = library_search_fn or _default_library_search()
    try:
        resp = fn(req)
    except Exception as exc:
        logger.warning("library_search failed for %s: %s", spectrum_id, exc)
        return SpectrumIdentification(
            spectrum_id=spectrum_id,
            source_id=source_id,
            gt_inchikey_first_block=gt_ik,
            predicted_inchikey_first_block=None,
            predicted_name=None,
            predicted_smiles=None,
            predicted_score=None,
            predicted_source_id=None,
            correct_top1=None,
            n_candidates_returned=0,
            n_after_exclusion=0,
            error=f"library_search: {type(exc).__name__}: {exc}",
        )

    cands = list(getattr(resp, "candidates", []) or [])
    excluded_hits: list[str] = []
    surviving = []
    for c in cands:
        sid = getattr(c, "source_id", None)
        if sid is not None and sid in exclusion_source_ids:
            excluded_hits.append(sid)
            continue
        surviving.append(c)

    if not surviving:
        return SpectrumIdentification(
            spectrum_id=spectrum_id,
            source_id=source_id,
            gt_inchikey_first_block=gt_ik,
            predicted_inchikey_first_block=None,
            predicted_name=None,
            predicted_smiles=None,
            predicted_score=None,
            predicted_source_id=None,
            correct_top1=None,
            n_candidates_returned=len(cands),
            n_after_exclusion=0,
            error=None,
            excluded_source_ids_hit=excluded_hits,
        )

    # Phase 6.3: optional MS-CLIP-primary post-sort. library_search internally
    # ranks by max(modcos, msclip) and returns top_k. When primary='msclip',
    # we re-sort the surviving candidates by msclip_rescaled descending so
    # downstream reranker / top-1 picker sees msclip as the dominant signal.
    # Candidates without an msclip score (e.g. msclip retriever failed or
    # candidate not in inhouse pool) drop to score 0 and tail.
    if primary_retriever == "msclip":
        def _msclip_key(c):
            _mc, ms = _candidate_score_components(c)
            return (ms or 0.0)
        surviving = sorted(surviving, key=_msclip_key, reverse=True)

    # Phase 6.7-A: snapshot the post-primary-sort top-K rank list BEFORE
    # rerank applies. Caller can use this for MRR / top-K accuracy.
    ranked_candidates_snapshot: list[dict[str, Any]] = []
    for rank, c in enumerate(surviving, start=1):
        mc, ms = _candidate_score_components(c)
        ranked_candidates_snapshot.append({
            "rank_after_primary": rank,
            "smiles": getattr(c, "smiles", None),
            "name": getattr(c, "name", None),
            "source_id": getattr(c, "source_id", None),
            "score": getattr(c, "score", None),
            "modcos": mc,
            "msclip": ms,
            "ik14": _smiles_to_inchikey_first_block(getattr(c, "smiles", "")),
        })

    # Phase 6.2: optional SIRIUS + CFM-ID rerank on top_k_for_rerank head.
    peak_evidence_dict: dict[str, Any] | None = None
    # Phase 6.5: conditional gate — when reranker_mode='conditional', evaluate
    # the msclip-confidence gate first; if it returns SKIP, no SIRIUS/CFM/LLM
    # work is done at all and the primary post-sorted top-1 is returned.
    gate_decision = None
    if reranker_mode == "conditional":
        from evaluation.sub6.conditional_rerank import should_rerank_msclip_gate
        gate_decision = should_rerank_msclip_gate(surviving)
        if not gate_decision.should_rerank:
            # Skip rerank entirely — record decision in peak_evidence_dict
            peak_evidence_dict = {
                "spectrum_id": spectrum_id,
                "conditional_skipped": True,
                "gate_reason": gate_decision.reason,
                "gate_msclip_top1": gate_decision.msclip_top1,
                "gate_msclip_gap": gate_decision.msclip_gap,
            }
            # leave surviving order untouched (msclip primary already sorted)
            rerank_with = ()  # ensure no SIRIUS/CFM run

    if rerank_with:
        from evaluation.sub6.rerank import (
            DEFAULT_CFMID_CACHE_DIR,
            rerank_with_sirius_cfmid,
        )
        use_sirius = "sirius" in rerank_with
        use_cfmid = "cfmid" in rerank_with
        try:
            surviving, pe = rerank_with_sirius_cfmid(
                spectrum_id=spectrum_id,
                experimental=spec,
                candidates=list(surviving),
                top_k_for_rerank=rerank_top_k,
                use_sirius=use_sirius,
                use_cfmid=use_cfmid,
                cfmid_cache_dir=cfmid_cache_dir or DEFAULT_CFMID_CACHE_DIR,
            )
            peak_evidence_dict = pe.to_dict()
        except Exception as exc:  # noqa: BLE001
            logger.warning("rerank failed for %s: %s", spectrum_id, exc)
            peak_evidence_dict = {"spectrum_id": spectrum_id, "error": f"{type(exc).__name__}: {exc}"}

    # Phase 6.6: ensure conditional-gate decision is recorded regardless of
    # whether rerank ran. The rerank branch above overwrites
    # peak_evidence_dict with its evidence bundle; merge the gate fields back
    # so downstream analysis can correlate trigger-rate with gap distribution.
    if reranker_mode == "conditional" and gate_decision is not None:
        if peak_evidence_dict is None:
            peak_evidence_dict = {"spectrum_id": spectrum_id}
        peak_evidence_dict.setdefault("conditional_skipped", not gate_decision.should_rerank)
        peak_evidence_dict.setdefault("gate_reason", gate_decision.reason)
        peak_evidence_dict.setdefault("gate_msclip_top1", gate_decision.msclip_top1)
        peak_evidence_dict.setdefault("gate_msclip_gap", gate_decision.msclip_gap)

    # Phase 6.3: LLM-as-reranker overrides the post-weighted top-1.
    llm_rerank_narrative: str | None = None
    llm_rerank_peak_claims: list[str] = []
    llm_rerank_confidence: str | None = None
    llm_rerank_fallback_used: bool = False
    llm_rerank_parse_error: str | None = None
    # Phase 6.7-A: ordered indices the LLM emitted (over the rerank head).
    llm_rerank_ranked_indices: list[int] = []
    if reranker_mode == "llm" and surviving and llm_chat_fn is not None:
        from evaluation.sub6.llm_reranker import (
            llm_rerank,
            render_narrative,
        )
        # Build evidence bundle from peak_evidence_dict's candidates_evaluated.
        # Each entry already has modcos / predicted_cosine / sirius_match /
        # mass_match etc. We add msclip score from explain parsing and the
        # primary-retriever info so the LLM sees the full picture.
        cands_eval = (peak_evidence_dict or {}).get("candidates_evaluated") or []
        sirius_top1_formula = (
            (peak_evidence_dict or {}).get("sirius", {}).get("top_formulas") or [{}]
        )[0].get("formula") if peak_evidence_dict else None
        cfmid_top_peaks_by_smi: dict[str, list] = {}
        if peak_evidence_dict:
            top1 = peak_evidence_dict.get("cfmid_top1") or {}
            if top1.get("smiles") and top1.get("predicted_peaks"):
                cfmid_top_peaks_by_smi[top1["smiles"]] = top1["predicted_peaks"]
        candidates_for_llm: list[dict[str, Any]] = []
        for i, c in enumerate(surviving[: rerank_top_k]):
            smi = getattr(c, "smiles", "")
            mc, ms = _candidate_score_components(c)
            primary_score = (ms if primary_retriever == "msclip" else mc) or 0.0
            ev = next((x for x in cands_eval if x.get("smiles") == smi), {}) or {}
            candidates_for_llm.append({
                "rank_after_primary": i + 1,
                "smiles": smi,
                "name": getattr(c, "name", None) or ev.get("name"),
                "formula": ev.get("formula"),
                "primary_retriever": primary_retriever,
                "primary_retriever_score": primary_score,
                "modcos": mc,
                "msclip": ms,
                "mass_match": ev.get("mass_match", 0.0),
                "sirius_top1_formula": sirius_top1_formula,
                "sirius_formula_match": bool(ev.get("sirius_match", 0.0) >= 1.0),
                "cfmid_cosine_vs_experimental": ev.get("predicted_cosine"),
                "cfmid_top_peaks": cfmid_top_peaks_by_smi.get(smi, []),
            })
        spectrum_meta = {
            "spectrum_id": spectrum_id,
            "precursor_mz": spec.precursor_mz,
            "ion_mode": spec.ionization_mode,
            "adduct": spec.adduct or "",
            "experimental_peaks": [
                [float(mz), float(intensity)]
                for mz, intensity in zip(spec.mz, spec.intensity)
            ],
        }
        try:
            res = llm_rerank(
                spectrum_meta=spectrum_meta,
                candidates_with_evidence=candidates_for_llm,
                chat_fn=llm_chat_fn,
                chat_kwargs=llm_chat_kwargs or {},
            )
            llm_rerank_narrative = render_narrative(spectrum_meta, res)
            llm_rerank_peak_claims = list(res.peak_claims)
            llm_rerank_confidence = res.confidence
            llm_rerank_fallback_used = res.fallback_used
            llm_rerank_parse_error = res.parse_error
            llm_rerank_ranked_indices = list(res.ranked_indices or [])
            # Override top-1 by LLM choice. Phase 6.7-A: also reorder the
            # rerank head (top-K) according to res.ranked_indices when
            # available so SpectrumIdentification.ranked_candidates downstream
            # reflects the LLM-preferred order.
            idx = res.selected_top1_index
            if 0 <= idx < len(surviving):
                if res.ranked_indices:
                    head_n = min(len(res.ranked_indices), len(surviving))
                    head = []
                    head_idx_set: set[int] = set()
                    for j in res.ranked_indices:
                        if 0 <= j < len(surviving) and j not in head_idx_set:
                            head.append(surviving[j])
                            head_idx_set.add(j)
                        if len(head) >= head_n:
                            break
                    tail = [c for i, c in enumerate(surviving) if i not in head_idx_set]
                    surviving = head + tail
                else:
                    chosen = surviving[idx]
                    surviving = [chosen] + [c for i, c in enumerate(surviving) if i != idx]
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm_rerank dispatch failed for %s: %s", spectrum_id, exc)
            llm_rerank_parse_error = f"dispatch error: {type(exc).__name__}: {exc}"
            llm_rerank_fallback_used = True

    top = surviving[0]
    pred_smiles = getattr(top, "smiles", None)
    pred_name = getattr(top, "name", None)
    pred_score = getattr(top, "score", None)
    pred_sid = getattr(top, "source_id", None)
    pred_ik = _smiles_to_inchikey_first_block(pred_smiles) if pred_smiles else None

    correct = None
    if pred_ik is not None and gt_ik:
        correct = pred_ik == gt_ik

    return SpectrumIdentification(
        spectrum_id=spectrum_id,
        source_id=source_id,
        gt_inchikey_first_block=gt_ik,
        predicted_inchikey_first_block=pred_ik,
        predicted_name=pred_name,
        predicted_smiles=pred_smiles,
        predicted_score=pred_score,
        predicted_source_id=pred_sid,
        correct_top1=correct,
        n_candidates_returned=len(cands),
        n_after_exclusion=len(surviving),
        error=None,
        excluded_source_ids_hit=excluded_hits,
        rerank_applied=tuple(rerank_with),
        peak_evidence=peak_evidence_dict,
        primary_retriever=primary_retriever,
        reranker_mode=reranker_mode,
        llm_rerank_narrative=llm_rerank_narrative,
        llm_rerank_peak_claims=llm_rerank_peak_claims,
        llm_rerank_confidence=llm_rerank_confidence,
        llm_rerank_fallback_used=llm_rerank_fallback_used,
        llm_rerank_parse_error=llm_rerank_parse_error,
        llm_rerank_ranked_indices=llm_rerank_ranked_indices,
        ranked_candidates=ranked_candidates_snapshot,
    )


def _smiles_to_inchikey_first_block(smiles: str) -> str | None:
    """Best-effort SMILES → InChIKey first block. RDKit-backed; returns
    None on any failure. We only need the 14-character first block since
    Sub-6 grading is at that resolution.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem.inchi import MolToInchiKey
    except ImportError:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        ik = MolToInchiKey(mol)
        if not ik or "-" not in ik:
            return None
        return ik.split("-")[0]
    except Exception:
        return None


def task_exclusion_set(task: dict) -> set[str]:
    """Build the per-task GNPS exclusion list (eval guide §3 pitfall 1).

    Every spectrum the task ships came from GNPS — without this filter,
    library_search will recommend each query as its own top-1 hit.
    """
    out: set[str] = set()
    for sp in task.get("differential_spectra") or []:
        sid = sp.get("source_id")
        if sid:
            out.add(str(sid))
    return out
