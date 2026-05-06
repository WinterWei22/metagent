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
from dataclasses import dataclass, field
from typing import Callable, Literal

from schemas import LibrarySearchRequest, Spectrum

from evaluation.sub6.compound_lookup import CompoundLookup

logger = logging.getLogger(__name__)


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

    req = LibrarySearchRequest(
        spectrum=spec,
        candidate_pool=None,
        top_k=top_k,
        min_score=min_score,
        libraries=list(libraries),
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
