"""Track B entry point: ``library_search(req: LibrarySearchRequest) -> LibrarySearchResponse``.

Two code paths share one function:

* **Path A — candidate_pool provided.** Score only the pool. Modified cosine
  is applied to the subset of candidates that ship a GNPS reference spectrum
  (looked up via ``common.gnps_loader`` by ``source_id``); ms-clip scores the
  full pool (no reference-spectrum requirement — the maintainer confirmed the
  ``has_reference_spectrum=True`` gate in the original contract was dropped
  once ms-clip landed). Fast and focused.

* **Path B — no candidate_pool.** Fall back to scanning all GNPS v0-usable
  records. Modified cosine runs against every record; ms-clip runs against
  every record's SMILES. Slower but still bounded by the cached GNPS pool size.

Both paths feed into the same scoring pipeline (``scoring.fuse_scores``) and
return a sorted, truncated list of ``Candidate`` objects wrapped in a
``LibrarySearchResponse``.

Dependency injection: tests supply a ``MockInHouseRetriever`` via the
``retriever`` kwarg; production callers call ``library_search(req)`` and the
real ``MSClipRetriever`` is constructed on demand.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from schemas import (
    Candidate,
    LibrarySearchRequest,
    LibrarySearchResponse,
    PrefilteredCandidate,
    Spectrum,
)

from tools.library_search.errors import InHouseModelError, LibraryUnavailableError
from tools.library_search.model import (
    InHouseRetriever,
    InHouseScore,
    MSClipRetriever,
)
from tools.library_search.scoring import (
    fuse_scores,
    modified_cosine_score,
    rescale_inhouse_score,
)

logger = logging.getLogger(__name__)

GNPS_PATH_ENV = "METAGENT_GNPS_PATH"
GNPS_SPECTRA_PATH_ENV = "METAGENT_GNPS_SPECTRA_PATH"
_GNPS_CACHE: list | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def library_search(
    req: LibrarySearchRequest,
    *,
    retriever: Optional[InHouseRetriever] = None,
    gnps_records: Optional[list] = None,
) -> LibrarySearchResponse:
    """Rank candidates against reference spectra using modified cosine + ms-clip.

    Args:
        req: validated request.
        retriever: dependency-injected in-house scorer. When ``None`` and
            ``"inhouse"`` is in ``req.libraries``, a real ``MSClipRetriever``
            is constructed lazily.
        gnps_records: dependency-injected pre-loaded GNPS records. When
            ``None`` and they are needed, ``load_gnps_v0_usable`` is called on
            ``METAGENT_GNPS_PATH``.
    """
    libraries = set(req.libraries)
    use_inhouse = "inhouse" in libraries
    use_gnps = "gnps" in libraries

    # ---- gather the set of (smiles, ref_spectrum | None) pairs to score ----
    targets = _collect_scoring_targets(
        req.candidate_pool,
        want_gnps=use_gnps,
        gnps_records=gnps_records,
    )
    if not targets:
        return _empty_response(
            libraries_searched=sorted(libraries),
            reason=_explain_empty(req.candidate_pool, use_gnps),
        )

    # ---- modified cosine pass ----
    modcos_scores: dict[int, float] = {}
    if use_gnps:
        for i, tgt in enumerate(targets):
            if tgt.ref_mz is None:
                continue
            score = modified_cosine_score(
                query_mz=req.spectrum.mz,
                query_intensity=req.spectrum.intensity,
                query_precursor_mz=req.spectrum.precursor_mz,
                ref_mz=tgt.ref_mz,
                ref_intensity=tgt.ref_intensity,
                ref_precursor_mz=tgt.ref_precursor_mz,
            )
            modcos_scores[i] = score

    # ---- in-house (ms-clip) pass ----
    inhouse_scores: dict[int, float] = {}
    inhouse_failed = False
    if use_inhouse:
        if retriever is None:
            retriever = MSClipRetriever()
        unique_smiles = _dedupe_preserving_order([t.smiles for t in targets])
        try:
            raw = retriever.score_candidates(
                query_mz=req.spectrum.mz,
                query_intensity=req.spectrum.intensity,
                query_precursor_mz=req.spectrum.precursor_mz,
                adduct=req.spectrum.adduct,
                candidate_smiles=unique_smiles,
                collision_energy=req.spectrum.collision_energy,
            )
        except InHouseModelError as exc:
            logger.warning("ms-clip scoring failed, continuing with modcos only: %s", exc)
            raw = []
            inhouse_failed = True
        smi_to_rescaled = {s.smiles: rescale_inhouse_score(s.raw_global_sim) for s in raw}
        for i, tgt in enumerate(targets):
            if tgt.smiles in smi_to_rescaled:
                inhouse_scores[i] = smi_to_rescaled[tgt.smiles]

    # ---- fuse, filter, sort, truncate ----
    fused: list[tuple[float, _ScoringTarget, float | None, float | None]] = []
    for i, tgt in enumerate(targets):
        mc = modcos_scores.get(i)
        ih = inhouse_scores.get(i)
        if mc is None and ih is None:
            continue
        final = fuse_scores(mc, ih)
        if final < req.min_score:
            continue
        fused.append((final, tgt, mc, ih))

    fused.sort(key=lambda r: r[0], reverse=True)

    # Deduplicate by SMILES so the same molecule does not appear twice when
    # multiple reference spectra happen to map to it. Keep the top-scoring row.
    seen_smiles: set[str] = set()
    dedup: list[tuple[float, _ScoringTarget, float | None, float | None]] = []
    for row in fused:
        smi = row[1].smiles
        if smi in seen_smiles:
            continue
        seen_smiles.add(smi)
        dedup.append(row)

    top = dedup[: req.top_k]

    candidates = [
        _build_candidate(final=final, tgt=tgt, modcos=mc, inhouse=ih)
        for final, tgt, mc, ih in top
    ]

    return LibrarySearchResponse(
        candidates=candidates,
        libraries_searched=sorted(libraries),
        n_total_compared=len(targets),
        explain=_explain_run(
            candidates=candidates,
            n_targets=len(targets),
            libraries=sorted(libraries),
            used_pool=req.candidate_pool is not None,
            inhouse_failed=inhouse_failed,
        ),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


class _ScoringTarget:
    """One candidate to score: SMILES + optional reference spectrum.

    Plain class (not dataclass) to avoid a frozen=False vs default-value
    gotcha; the field set is small and stable enough to write explicitly.
    """

    __slots__ = (
        "smiles",
        "name",
        "source",
        "source_id",
        "ref_mz",
        "ref_intensity",
        "ref_precursor_mz",
    )

    def __init__(
        self,
        *,
        smiles: str,
        name: str | None,
        source: str,
        source_id: str | None,
        ref_mz: list[float] | None = None,
        ref_intensity: list[float] | None = None,
        ref_precursor_mz: float | None = None,
    ):
        self.smiles = smiles
        self.name = name
        self.source = source
        self.source_id = source_id
        self.ref_mz = ref_mz
        self.ref_intensity = ref_intensity
        self.ref_precursor_mz = ref_precursor_mz


def _collect_scoring_targets(
    candidate_pool: list[PrefilteredCandidate] | None,
    *,
    want_gnps: bool,
    gnps_records: list | None,
) -> list[_ScoringTarget]:
    """Materialise the flat list of candidates to score.

    Path A: iterate the pool. For entries sourced from GNPS, look up the
    reference peaks in the loaded GNPS pool by ``source_id``; for other
    sources (pubchem_lite, hmdb) leave ref fields as None (ms-clip only).

    Path B: iterate the full GNPS v0-usable pool. Every record contributes one
    target with its own peaks as the reference.
    """
    if candidate_pool is not None:
        gnps_by_id: dict[str, tuple[list[float], list[float], float]] = {}
        if want_gnps and any(c.source_pool == "gnps" for c in candidate_pool):
            records = _load_gnps_records(records=gnps_records, required=False)
            gnps_by_id = _build_gnps_id_index(records or [])

        targets: list[_ScoringTarget] = []
        for c in candidate_pool:
            ref = gnps_by_id.get(c.source_id)
            if ref is not None:
                mz, inten, prec = ref
                targets.append(
                    _ScoringTarget(
                        smiles=c.smiles,
                        name=c.name,
                        source="library",
                        source_id=c.source_id,
                        ref_mz=mz,
                        ref_intensity=inten,
                        ref_precursor_mz=prec,
                    )
                )
            else:
                targets.append(
                    _ScoringTarget(
                        smiles=c.smiles,
                        name=c.name,
                        source="library",
                        source_id=c.source_id,
                    )
                )
        return targets

    # Path B: scan the full GNPS pool.
    if not want_gnps:
        return []
    records = _load_gnps_records(records=gnps_records, required=True) or []
    targets = []
    for rec in records:
        if not rec.peaks or not rec.smiles or not rec.precursor_mz:
            continue
        mz = [float(p[0]) for p in rec.peaks]
        inten_raw = [float(p[1]) for p in rec.peaks]
        max_i = max(inten_raw) if inten_raw else 0.0
        if max_i <= 0:
            continue
        inten = [x / max_i for x in inten_raw]
        targets.append(
            _ScoringTarget(
                smiles=rec.smiles,
                name=rec.compound_name,
                source="library",
                source_id=rec.spectrum_id,
                ref_mz=mz,
                ref_intensity=inten,
                ref_precursor_mz=float(rec.precursor_mz),
            )
        )
    return targets


def _load_gnps_records(*, records: list | None, required: bool) -> list | None:
    """Return a pre-loaded records list, or lazily load the GNPS spectra dump.

    Looks up the MGF spectra path from ``METAGENT_GNPS_SPECTRA_PATH``. If that
    is unset, falls back to deriving ``.mgf`` from a ``.csv`` value of
    ``METAGENT_GNPS_PATH`` (same directory). If neither resolves, returns
    ``None`` when ``required`` is False (library_search degrades to ms-clip
    only) or raises ``LibraryUnavailableError`` when ``required`` is True.
    """
    if records is not None:
        return records
    global _GNPS_CACHE
    if _GNPS_CACHE is not None:
        return _GNPS_CACHE

    path = os.environ.get(GNPS_SPECTRA_PATH_ENV)
    if not path:
        meta_path = os.environ.get(GNPS_PATH_ENV)
        if meta_path and meta_path.endswith(".csv"):
            candidate = meta_path[:-4] + ".mgf"
            if os.path.exists(candidate):
                path = candidate
    if not path:
        if required:
            raise LibraryUnavailableError(
                f"{GNPS_SPECTRA_PATH_ENV} is not set; cannot scan GNPS for peaks. "
                "Provide a candidate_pool or set the env var."
            )
        logger.warning(
            "%s unset and cannot derive from %s; continuing without reference peaks.",
            GNPS_SPECTRA_PATH_ENV, GNPS_PATH_ENV,
        )
        return None

    try:
        from common.gnps_loader import load_v0_usable

        _GNPS_CACHE = load_v0_usable(path)
        return _GNPS_CACHE
    except Exception as exc:
        if required:
            raise LibraryUnavailableError(f"failed to load GNPS from {path}: {exc}") from exc
        logger.warning(
            "GNPS load failed (%s: %s); continuing without reference peaks.",
            type(exc).__name__, exc,
        )
        return None


def _build_gnps_id_index(records: list) -> dict[str, tuple[list[float], list[float], float]]:
    """Build a ``source_id → (mz, intensity_normalised, precursor_mz)`` lookup."""
    idx: dict[str, tuple[list[float], list[float], float]] = {}
    for rec in records:
        if not rec.peaks or rec.precursor_mz is None:
            continue
        mz = [float(p[0]) for p in rec.peaks]
        raw = [float(p[1]) for p in rec.peaks]
        m = max(raw) if raw else 0.0
        if m <= 0:
            continue
        inten = [x / m for x in raw]
        idx[rec.spectrum_id] = (mz, inten, float(rec.precursor_mz))
    return idx


def _dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _build_candidate(
    *,
    final: float,
    tgt: _ScoringTarget,
    modcos: float | None,
    inhouse: float | None,
) -> Candidate:
    parts: list[str] = []
    if modcos is not None:
        parts.append(f"modified cosine {modcos:.3f}")
    if inhouse is not None:
        parts.append(f"ms-clip {inhouse:.3f}")
    signal_str = " + ".join(parts) if parts else "no signal"
    explain = (
        f"Library match{' from ' + tgt.source_id if tgt.source_id else ''} "
        f"scored {final:.3f} ({signal_str})."
    )
    return Candidate(
        smiles=tgt.smiles,
        name=tgt.name,
        source="library",
        score=final,
        source_id=tgt.source_id,
        explain=explain,
    )


def _empty_response(*, libraries_searched: list[str], reason: str) -> LibrarySearchResponse:
    return LibrarySearchResponse(
        candidates=[],
        libraries_searched=libraries_searched,
        n_total_compared=0,
        explain=reason,
    )


def _explain_empty(candidate_pool, use_gnps: bool) -> str:
    if candidate_pool is not None and len(candidate_pool) == 0:
        return "Candidate pool was empty; no candidates to score."
    if candidate_pool is None and not use_gnps:
        return "No candidate_pool provided and 'gnps' is not in requested libraries."
    return "No scorable targets materialised from the requested libraries."


def _explain_run(
    *,
    candidates: list[Candidate],
    n_targets: int,
    libraries: list[str],
    used_pool: bool,
    inhouse_failed: bool,
) -> str:
    libs = "+".join(libraries) if libraries else "none"
    path = "prefiltered pool" if used_pool else "full GNPS pool"
    if not candidates:
        base = (
            f"Compared {n_targets} targets from {path} against libraries "
            f"[{libs}]; no candidate met min_score."
        )
    else:
        top = candidates[0]
        base = (
            f"Retrieved {len(candidates)} candidates from {path} (libraries "
            f"[{libs}], compared {n_targets}); top match "
            f"{top.source_id or top.smiles} scored {top.score:.3f}."
        )
    if inhouse_failed:
        base += " Note: ms-clip scoring failed; results use modified cosine only."
    return base


# ---------------------------------------------------------------------------
# Test utilities
# ---------------------------------------------------------------------------


def clear_gnps_cache() -> None:
    """Drop the in-module GNPS cache. Tests set up different records per case."""
    global _GNPS_CACHE
    _GNPS_CACHE = None


__all__ = ["library_search", "clear_gnps_cache"]
