#!/usr/bin/env python3
"""Run the full deterministic identification pipeline on a single fixture spectrum.

Composes (without an LLM) the five tracks that have individually landed:

    A1 spectrum_preprocess  →  A2 candidate_prefilter
                               ↓
                               (pool shared by B and C)
                               ↓
    B  library_search   ┐
                        ├→  merge + dedupe by canonical SMILES
    C  molecule_generate┘
                               ↓  (top_k)
    D1 fetch_metabolite_info   }
    D2 pathway_context          } per-candidate enrichment (safe wrappers)
    E  predict_spectrum        }
                               ↓
    evidence_score + sort
                               ↓
    IdentificationReport (schemas.report)

Usage
-----

    python scripts/run_full_pipeline.py --fixture glucose_pos
    python scripts/run_full_pipeline.py --fixture caffeine_pos --output json
    python scripts/run_full_pipeline.py --fixture lcarnitine_pos --output md

Exit codes
----------
    0 — pipeline ran, IdentificationReport is valid
    1 — fixture missing or raw input invalid
    2 — unexpected crash (bug in composition layer or an unhandled ToolError)

The orchestrator (future work) will consume the `identify(...)` function
directly; the CLI wrapper is for maintainer spot-checks.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from schemas import (
    Candidate,
    GenerateRequest,
    GenerateResponse,
    LibrarySearchRequest,
    LibrarySearchResponse,
    LiteratureRecord,
    LiteratureSearchRequest,
    LiteratureSearchResponse,
    MetaboliteInfoRequest,
    MetaboliteInfoResponse,
    PathwayContextRequest,
    PathwayContextResponse,
    PredictSpectrumRequest,
    PredictSpectrumResponse,
    PrefilterRequest,
    PrefilterResponse,
    PrefilteredCandidate,
    PreprocessRequest,
    PreprocessResponse,
    Spectrum,
    ToolError,
)
from schemas.report import CandidateReport, IdentificationReport

from tools.candidate_prefilter import prefilter as _default_prefilter
from tools.library_search import library_search as _default_library_search
from tools.library_search.scoring import modified_cosine_score
from tools.literature import literature_search as _default_literature_search
from tools.metabolite_info import fetch_metabolite_info as _default_fetch_metabolite_info
from tools.metabolite_info.errors import IdentifierFormatError
from tools.molecule_gen import generate as _default_generate
from tools.molecule_gen.fingerprint import (
    CandidateFusionFingerprinter,
    Fingerprinter,
    FusionStrategy,
    SiriusFingerprinter,
)
from tools.pathway_context import pathway_context as _default_pathway_context
from tools.pathway_context.errors import MetaboliteNotInNetworkError, RampUnavailableError
from tools.spectrum_ops import preprocess as _default_preprocess
from tools.spectrum_predict import (
    CfmUnavailableError,
    InvalidSmilesError,
    PredictionTimeoutError,
    predict_spectrum as _default_predict_spectrum,
)

logger = logging.getLogger("metagent.pipeline")


# ---------------------------------------------------------------------------
# Fingerprint sourcing for Stage 3b (molecule_generate)
# ---------------------------------------------------------------------------


_FUSION_STRATEGIES: tuple[str, ...] = (
    "retrieved_only_60",
    "retrieved_only_80",
    "topn_60",
    "topn_80",
)
_VALID_FP_STRATEGIES: tuple[str, ...] = ("sirius",) + _FUSION_STRATEGIES


def _build_fingerprinter(
    *,
    strategy: str,
    library_candidates: list,
) -> tuple["Fingerprinter | None", str | None]:
    """Construct the Stage-3b fingerprinter for a given strategy.

    Returns ``(fingerprinter, skip_note)``. When ``skip_note`` is not None
    the caller short-circuits Stage 3b — fusion with no library candidates
    has no signal, and SIRIUS-on-empty would be the same. Surfaces the
    skip reason as a pipeline-level warning.
    """
    if strategy not in _VALID_FP_STRATEGIES:
        raise ValueError(
            f"unknown fingerprint_strategy {strategy!r}; "
            f"expected one of {_VALID_FP_STRATEGIES}"
        )

    if strategy == "sirius":
        # Legacy path. SIRIUS reads the spectrum directly; the runner does
        # not need library_candidates here.
        return SiriusFingerprinter(), None

    # Fusion strategy. Requires at least one library candidate to vote on.
    if not library_candidates:
        return None, (
            f"molecule_generate: skipped — fingerprint_strategy={strategy!r} "
            "needs at least one library_search candidate to fuse, got 0."
        )

    return (
        CandidateFusionFingerprinter(
            list(library_candidates),
            strategy=strategy,  # type: ignore[arg-type]
        ),
        None,
    )


# ---------------------------------------------------------------------------
# Canonical SMILES helpers (kept local to avoid importing from common/rdkit_utils
# on the hot path — this is deterministic composition, not a tool).
# ---------------------------------------------------------------------------


def _canonical_smiles(smiles: str) -> str | None:
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return Chem.MolToSmiles(mol)


def _inchikey_connectivity(smiles: str) -> str | None:
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    ik = Chem.MolToInchiKey(mol)
    return ik.split("-")[0] if ik else None


def _exact_mass_from_smiles(smiles: str) -> float | None:
    """Neutral monoisotopic mass from SMILES via RDKit. Used to sidestep D-1.

    HMDB stores some zwitterions (L-carnitine confirmed) as protonated cations
    whose `exact_mass` is already +1 H vs the neutral — comparing that against
    an experimental [M+H]+ precursor back-calculation would be off by 1 Da.
    Computing from SMILES gives the unambiguous neutral mass of whatever
    structure the candidate represents.
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    try:
        return float(Descriptors.ExactMolWt(mol))
    except Exception:  # pragma: no cover — rdkit is robust on parsed mols
        return None


# ---------------------------------------------------------------------------
# Merge B + C candidate lists by canonical SMILES.
# ---------------------------------------------------------------------------


def _merge_candidates(
    library_candidates: list[Candidate],
    generated_candidates: list[Candidate],
) -> list[tuple[Candidate, list[str]]]:
    """Dedupe by canonical SMILES; higher-score wins. Preserve both origins in notes.

    Returns a list of ``(survivor_candidate, origin_notes)`` tuples, sorted
    descending by the survivor's score.
    """
    best: dict[str, tuple[Candidate, list[str]]] = {}

    for cand in list(library_candidates) + list(generated_candidates):
        key = _canonical_smiles(cand.smiles)
        if key is None:
            # Skip unparseable — tool-layer tests already guard against emitting
            # these, but we are defensive at the composition boundary.
            logger.error(
                "merge: dropping unparseable SMILES %r from source=%s (id=%s)",
                cand.smiles, cand.source, cand.source_id,
            )
            continue
        origin = f"{cand.source}:{cand.source_id or '?'}"
        if key not in best:
            best[key] = (cand, [origin])
        else:
            prev_cand, prev_notes = best[key]
            notes = prev_notes + [origin]
            winner = cand if cand.score > prev_cand.score else prev_cand
            best[key] = (winner, notes)

    merged = list(best.values())
    merged.sort(key=lambda row: row[0].score, reverse=True)
    return merged


def _match_pool_entry(
    candidate: Candidate, pool: list[PrefilteredCandidate]
) -> PrefilteredCandidate | None:
    """Return the PrefilteredCandidate with the same canonical SMILES, or None."""
    key = _canonical_smiles(candidate.smiles)
    if key is None:
        return None
    for entry in pool:
        entry_key = _canonical_smiles(entry.smiles)
        if entry_key == key:
            return entry
    return None


# ---------------------------------------------------------------------------
# _safe_* enrichment wrappers.
# ---------------------------------------------------------------------------


def _identifier_for_fetch(
    candidate: Candidate, prefilter_match: PrefilteredCandidate | None
) -> tuple[str, str]:
    """Pick the best identifier + id_type for fetch_metabolite_info.

    Preference: HMDB ID from the pool (most reliable exact match) → candidate's
    source_id if it looks like an HMDB ID → InChIKey via RDKit → raw SMILES.
    """
    if prefilter_match and prefilter_match.source_id.startswith("HMDB"):
        return prefilter_match.source_id, "hmdb"
    if candidate.source_id and candidate.source_id.startswith("HMDB"):
        return candidate.source_id, "hmdb"
    ik = None
    try:
        from rdkit import Chem

        mol = Chem.MolFromSmiles(candidate.smiles)
        if mol is not None:
            ik = Chem.MolToInchiKey(mol)
    except Exception:  # pragma: no cover
        ik = None
    if ik:
        return ik, "inchikey"
    return candidate.smiles, "smiles"


def _safe_fetch_metabolite_info(
    candidate: Candidate,
    prefilter_match: PrefilteredCandidate | None,
    *,
    fetch_fn: Callable[[MetaboliteInfoRequest], MetaboliteInfoResponse],
) -> tuple[MetaboliteInfoResponse | None, str | None]:
    """Call D1 safely. On typed error or found=False return (None, note)."""
    identifier, id_type = _identifier_for_fetch(candidate, prefilter_match)
    try:
        resp = fetch_fn(MetaboliteInfoRequest(identifier=identifier, id_type=id_type))
    except IdentifierFormatError as exc:
        logger.error("fetch_metabolite_info: identifier format error on %r: %s", identifier, exc)
        return None, f"fetch_metabolite_info: {exc.code}: {exc.message}"
    except ToolError as exc:
        logger.error(
            "fetch_metabolite_info: %s on %r: %s", type(exc).__name__, identifier, exc,
        )
        return None, f"fetch_metabolite_info: {exc.code}: {exc.message}"
    except Exception as exc:  # untyped — still don't crash, but log loudly
        logger.error(
            "fetch_metabolite_info: UNEXPECTED %s on %r: %s",
            type(exc).__name__, identifier, exc,
        )
        return None, f"fetch_metabolite_info: unexpected {type(exc).__name__}: {exc}"
    if not resp.found:
        return resp, (
            f"fetch_metabolite_info: found=False for {identifier} (id_type={id_type})"
        )
    return resp, None


def _pathway_identifier(info: MetaboliteInfoResponse) -> str | None:
    """Pick the best ID to hand to pathway_context.

    RaMP resolves both `HMDB...` and `C#####` (KEGG). We prefer the HMDB ID
    because KEGG coverage in HMDB is only ~3% (see audit D-4).
    """
    hid = info.cross_refs.get("hmdb")
    if hid:
        return hid
    kid = info.cross_refs.get("kegg")
    if kid:
        return kid
    # Some HMDB rows may not populate cross_refs["hmdb"] with themselves; fall
    # back to whatever primary ID looks HMDB-shaped.
    if info.inchikey and info.source == "hmdb":
        return None  # can't pathway-query without an HMDB/KEGG ID
    return None


def _safe_pathway_context(
    info: MetaboliteInfoResponse | None,
    *,
    co_observed_ids: list[str],
    pathway_context_fn: Callable[[PathwayContextRequest], PathwayContextResponse],
) -> tuple[PathwayContextResponse | None, str | None]:
    """Call D2 safely. On orphan/unreachable return (None, note)."""
    if info is None or not info.found:
        return None, "pathway_context: skipped, no metabolite_info to identify the focal"
    ident = _pathway_identifier(info)
    if ident is None:
        return None, (
            f"pathway_context: skipped, no HMDB/KEGG cross-ref available for "
            f"{info.primary_name or info.inchikey}"
        )
    try:
        resp = pathway_context_fn(
            PathwayContextRequest(
                metabolite_id=ident, co_observed_ids=list(co_observed_ids),
            )
        )
    except MetaboliteNotInNetworkError as exc:
        return None, f"pathway_context: {exc.code} for {ident}"
    except RampUnavailableError as exc:
        return None, f"pathway_context: {exc.code}: {exc.message}"
    except ToolError as exc:
        return None, f"pathway_context: {exc.code}: {exc.message}"
    except Exception as exc:
        logger.error(
            "pathway_context: UNEXPECTED %s on %r: %s",
            type(exc).__name__, ident, exc,
        )
        return None, f"pathway_context: unexpected {type(exc).__name__}: {exc}"
    return resp, None


def _safe_predict_spectrum(
    candidate: Candidate,
    experimental_spectrum: Spectrum,
    *,
    predict_fn: Callable[[PredictSpectrumRequest], PredictSpectrumResponse],
) -> tuple[PredictSpectrumResponse | None, float | None, str | None]:
    """Call E safely. Returns (response, cosine_vs_experimental, note).

    The cosine is None iff the response is None; experimental_spectrum is
    always non-empty (A1 enforces ≥3 peaks).
    """
    try:
        resp = predict_fn(
            PredictSpectrumRequest(
                smiles=candidate.smiles,
                adduct=experimental_spectrum.adduct,
                ionization_mode=experimental_spectrum.ionization_mode,
            )
        )
    except InvalidSmilesError as exc:
        return None, None, f"predict_spectrum: {exc.code}: {exc.message}"
    except PredictionTimeoutError as exc:
        return None, None, f"predict_spectrum: {exc.code}: {exc.message}"
    except CfmUnavailableError as exc:
        return None, None, f"predict_spectrum: {exc.code}: {exc.message}"
    except ToolError as exc:
        return None, None, f"predict_spectrum: {exc.code}: {exc.message}"
    except Exception as exc:
        logger.error(
            "predict_spectrum: UNEXPECTED %s on %s: %s",
            type(exc).__name__, candidate.source_id, exc,
        )
        return None, None, f"predict_spectrum: unexpected {type(exc).__name__}: {exc}"

    # Compute modified cosine defensively — a matchms version skew or an
    # unexpected matchms internal error must not invalidate the entire
    # candidate's enrichment. We still recorded the predicted spectrum above;
    # only the similarity metric is degraded.
    try:
        cosine = modified_cosine_score(
            query_mz=experimental_spectrum.mz,
            query_intensity=experimental_spectrum.intensity,
            query_precursor_mz=experimental_spectrum.precursor_mz,
            ref_mz=resp.predicted.mz,
            ref_intensity=resp.predicted.intensity,
            ref_precursor_mz=resp.predicted.precursor_mz,
        )
    except Exception as exc:
        logger.error(
            "predict_spectrum cosine computation failed for %s: %s",
            candidate.source_id, exc,
        )
        return resp, None, f"predict_spectrum: cosine unavailable ({type(exc).__name__})"
    return resp, cosine, None


# ---------------------------------------------------------------------------
# Stage 6 — literature_search safe wrapper (per-candidate)
# ---------------------------------------------------------------------------


def _literature_query_for(candidate: Candidate) -> str | None:
    """Build the search query for a candidate. Prefer the human-readable
    name; fall back to None (caller skips Stage 6 for this candidate)
    rather than searching by raw SMILES — Europe PMC's free-text scoring
    is poor on SMILES strings and produces noise."""
    name = (candidate.name or "").strip()
    if not name:
        return None
    return f"{name} mass spectrometry metabolite"


def _safe_literature_search(
    candidate: Candidate,
    *,
    max_results: int,
    literature_search_fn: Callable[..., LiteratureSearchResponse],
) -> tuple[list[LiteratureRecord], str | None]:
    """Call F safely. Returns (records, note).

    Tool-layer errors (RateLimitError, network outages) degrade to an
    empty record list with a per-candidate note — the rest of the
    enrichment continues. This mirrors the safety pattern of D1 / D2 / E.
    """
    query = _literature_query_for(candidate)
    if query is None:
        return [], (
            "literature_search: skipped (candidate has no name; "
            "free-text query on raw SMILES is too noisy in v0)"
        )
    try:
        resp = literature_search_fn(
            LiteratureSearchRequest(
                query=query,
                max_results=max_results,
                sources=["europepmc"],
            )
        )
    except ToolError as exc:
        return [], f"literature_search: {exc.code}: {exc.message}"
    except Exception as exc:
        logger.error(
            "literature_search: UNEXPECTED %s on %s: %s",
            type(exc).__name__, candidate.source_id, exc,
        )
        return [], (
            f"literature_search: UNEXPECTED {type(exc).__name__}: {exc}"
        )
    return list(resp.records), None


# ---------------------------------------------------------------------------
# Score component helpers.
# ---------------------------------------------------------------------------


def _mass_match_indicator(
    smiles: str, neutral_mass: float, *, ppm: float = 5.0
) -> float:
    """1.0 iff SMILES-derived exact mass agrees with `neutral_mass` within `ppm`."""
    observed = _exact_mass_from_smiles(smiles)
    if observed is None or neutral_mass <= 0:
        return 0.0
    delta_ppm = abs(observed - neutral_mass) / neutral_mass * 1e6
    return 1.0 if delta_ppm <= ppm else 0.0


def _pathway_presence_indicator(pw: PathwayContextResponse | None) -> float:
    """1.0 iff we got at least one pathway back. Does NOT use hit_count or neighbours."""
    if pw is None:
        return 0.0
    return 1.0 if len(pw.pathways) > 0 else 0.0


def _smiles_zwitterion_hint(smiles: str) -> bool:
    """Return True iff the molecule has BOTH a positive and a negative
    formal-charge atom (i.e. it is a zwitterion).

    Used only to add a display-only note to the CandidateReport when an HMDB
    stored cation mass might be in play. The score logic never depends on this.
    """
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return False
    charges = [a.GetFormalCharge() for a in mol.GetAtoms()]
    return any(c > 0 for c in charges) and any(c < 0 for c in charges)


# ---------------------------------------------------------------------------
# Pipeline version + tool versions.
# ---------------------------------------------------------------------------


def _current_git_describe() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT, capture_output=True, text=True, check=False, timeout=5.0,
        )
        sha = out.stdout.strip() or "unknown"
        branch_out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=_REPO_ROOT, capture_output=True, text=True, check=False, timeout=5.0,
        )
        branch = branch_out.stdout.strip() or "unknown"
        return f"{branch}:{sha}"
    except Exception:  # pragma: no cover — defensive
        return "unknown:unknown"


def _path_signature(env_var: str) -> str | None:
    """Return '<abspath>@<mtime>' for an env-var path, or None if unset/missing."""
    val = os.environ.get(env_var, "")
    if not val:
        return None
    path = Path(val)
    if not path.exists():
        return f"{val} (missing)"
    try:
        mtime = int(path.stat().st_mtime)
    except OSError:
        mtime = 0
    return f"{val}@{mtime}"


def _collect_tool_versions(
    predict_responses: list[PredictSpectrumResponse | None],
) -> dict[str, str]:
    """Snapshot whatever version / signature strings each backend advertises."""
    versions: dict[str, str] = {}
    # CFM-ID: if any E call succeeded, pull the model_version it reported.
    for resp in predict_responses:
        if resp is not None and resp.model_version:
            versions["cfm-id"] = resp.model_version
            break
    # ms-clip + ms-bart: checkpoints don't advertise a version, fall back to
    # path+mtime when env vars are set.
    for key, env in [
        ("ms-clip", "METAGENT_MSCLIP_CKPT"),
        ("ms-bart", "METAGENT_MSBART_CKPT"),
        ("gnps_csv", "METAGENT_GNPS_PATH"),
        ("gnps_mgf", "METAGENT_GNPS_SPECTRA_PATH"),
        ("pubchem_lite", "METAGENT_PUBCHEM_LITE_PATH"),
        ("hmdb", "METAGENT_HMDB_PATH"),
        ("ramp", "METAGENT_RAMP_PATH"),
    ]:
        sig = _path_signature(env)
        if sig:
            versions[key] = sig
    return versions


# ---------------------------------------------------------------------------
# Warnings aggregation.
# ---------------------------------------------------------------------------


def _summarise_warnings(
    preprocess_resp: PreprocessResponse,
    prefilter_resp: PrefilterResponse,
    library_resp: LibrarySearchResponse,
    generate_resp: GenerateResponse,
    per_candidate_notes: list[list[str]],
) -> list[str]:
    """Fold per-tool explain strings + per-candidate notes into a report-level list."""
    out: list[str] = []
    out.append(
        f"preprocess: quality_flag={preprocess_resp.quality_flag}; "
        f"{preprocess_resp.n_peaks_in}→{preprocess_resp.n_peaks_out} peaks"
    )
    out.append(
        f"prefilter: {len(prefilter_resp.candidates)} candidates; "
        f"n_by_pool={prefilter_resp.n_by_pool}"
    )
    if len(prefilter_resp.candidates) == 0:
        out.append(
            "prefilter: empty pool — library_search has nothing to rank "
            "and molecule_generate loses its in-pool bonus"
        )
    out.append(
        f"library_search: {len(library_resp.candidates)} above min_score "
        f"from {library_resp.n_total_compared} compared"
    )
    out.append(
        f"molecule_generate: {len(generate_resp.candidates)} final "
        f"({generate_resp.n_generated_raw} raw, {generate_resp.n_valid} RDKit-valid)"
    )
    # Per-tool degradation counters.
    degraded = {"fetch_metabolite_info": 0, "pathway_context": 0, "predict_spectrum": 0}
    for notes in per_candidate_notes:
        for note in notes:
            for key in degraded:
                if note.startswith(key + ":"):
                    degraded[key] += 1
                    break
    for tool, n in degraded.items():
        if n > 0:
            out.append(f"{tool}: {n} candidate(s) ran with degraded output — see candidate notes")
    return out


# ---------------------------------------------------------------------------
# The main `identify` function.
# ---------------------------------------------------------------------------


def identify(
    raw_input: PreprocessRequest,
    *,
    top_k: int = 10,
    prefilter_pools: tuple[str, ...] = ("gnps", "pubchem_lite"),
    mass_tolerance_ppm: float = 5.0,
    predict_top_n: int = 5,
    co_observed_ids: list[str] | None = None,
    min_library_score: float = 0.3,
    n_candidates_generate: int | None = None,
    fingerprint_strategy: str = "topn_60",
    literature_top_n: int = 3,
    literature_max_results: int = 5,
    # Dependency-injected tool callables — default to the real ones. Tests
    # monkeypatch individual wrappers rather than these, so typical callers
    # leave these alone.
    preprocess_fn: Callable[[PreprocessRequest], PreprocessResponse] = _default_preprocess,
    prefilter_fn: Callable[[PrefilterRequest], PrefilterResponse] = _default_prefilter,
    library_search_fn: Callable[..., LibrarySearchResponse] = _default_library_search,
    generate_fn: Callable[..., GenerateResponse] = _default_generate,
    fetch_metabolite_info_fn: Callable[
        [MetaboliteInfoRequest], MetaboliteInfoResponse
    ] = _default_fetch_metabolite_info,
    pathway_context_fn: Callable[
        [PathwayContextRequest], PathwayContextResponse
    ] = _default_pathway_context,
    predict_spectrum_fn: Callable[
        [PredictSpectrumRequest], PredictSpectrumResponse
    ] = _default_predict_spectrum,
    literature_search_fn: Callable[
        [LiteratureSearchRequest], LiteratureSearchResponse
    ] = _default_literature_search,
) -> IdentificationReport:
    """Deterministic end-to-end identification. No LLM.

    See module docstring for the pipeline shape. `co_observed_ids` defaults to
    [] because a single-spectrum pipeline has no natural co-observed set; that
    also sidesteps P-6 (cooccurrence_score deflation on unresolvable inputs).
    """
    co_observed = list(co_observed_ids) if co_observed_ids else []
    if n_candidates_generate is None:
        n_candidates_generate = top_k

    # STAGE 1 — preprocess
    preprocess_resp = preprocess_fn(raw_input)
    spectrum = preprocess_resp.spectrum

    # STAGE 2 — prefilter
    prefilter_resp = prefilter_fn(
        PrefilterRequest(
            precursor_mz=spectrum.precursor_mz,
            adduct=spectrum.adduct,
            molecular_formula=None,
            mass_tolerance_ppm=mass_tolerance_ppm,
            pools=list(prefilter_pools),
        )
    )
    pool = list(prefilter_resp.candidates)

    # STAGE 3a — library_search (against the pool, or empty if pool is empty)
    library_resp = library_search_fn(
        LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=pool, top_k=top_k, min_score=min_library_score,
        )
    )

    # STAGE 3b — molecule_generate. Degrade gracefully when a dependency of
    # C is not available (SIRIUS missing, ms-bart checkpoint missing, etc.).
    # B's library_search still contributes on its own; the pipeline stays
    # deterministic and the failure is recorded as a report-level warning.
    #
    # Fingerprint sourcing follows ``fingerprint_strategy``:
    #
    #   * ``sirius`` — legacy default; ``SiriusFingerprinter`` runs CSI:FingerID
    #     on the spectrum. Requires SIRIUS on PATH; produces substructure-space
    #     bits that don't match MS-BART's Morgan training distribution.
    #   * ``retrieved_only_*`` / ``topn_*`` — production default. Fuses Morgan
    #     fingerprints of Stage 3a's library candidates (per
    #     ``MS-BART/preprocess/create_fused_fps.py``). When no library
    #     candidates are returned, fusion has no input, so Stage 3b is skipped
    #     with a degradation note.
    generate_degradation_note: str | None = None
    fingerprinter, fp_skip_note = _build_fingerprinter(
        strategy=fingerprint_strategy,
        library_candidates=library_resp.candidates,
    )
    if fp_skip_note is not None:
        generate_degradation_note = fp_skip_note
        generate_resp = GenerateResponse(
            candidates=[], n_generated_raw=0, n_valid=0,
            explain=fp_skip_note,
        )
    else:
        try:
            generate_resp = generate_fn(
                GenerateRequest(
                    spectrum=spectrum,
                    candidate_pool=pool,
                    n_candidates=n_candidates_generate,
                ),
                fingerprinter=fingerprinter,
            )
        except ToolError as exc:
            logger.error("molecule_generate degraded: %s: %s", type(exc).__name__, exc)
            generate_degradation_note = (
                f"molecule_generate: {type(exc).__name__}: {exc}"
            )
            generate_resp = GenerateResponse(
                candidates=[], n_generated_raw=0, n_valid=0,
                explain=f"degraded: {type(exc).__name__}: {exc}",
            )
        except FileNotFoundError as exc:
            # Most common external-binary failure mode (e.g. `sirius` not on
            # PATH; SIRIUS-strategy only).
            logger.error("molecule_generate degraded on missing binary: %s", exc)
            generate_degradation_note = f"molecule_generate: binary missing: {exc}"
            generate_resp = GenerateResponse(
                candidates=[], n_generated_raw=0, n_valid=0,
                explain=f"degraded: FileNotFoundError: {exc}",
            )

    # STAGE 4 — merge + dedupe
    merged = _merge_candidates(library_resp.candidates, generate_resp.candidates)
    merged = merged[:top_k]

    # STAGE 5 — per-candidate enrichment
    enriched: list[CandidateReport] = []
    predict_responses: list[PredictSpectrumResponse | None] = []
    per_cand_notes: list[list[str]] = []

    for rank, (candidate, origins) in enumerate(merged):
        notes: list[str] = []
        if len(set(origins)) > 1:
            # B and C both emitted this SMILES — record the merge.
            notes.append(f"merged from {'+'.join(sorted(set(o.split(':')[0] for o in origins)))}")
        pool_match = _match_pool_entry(candidate, pool)

        # D1
        info, fetch_note = _safe_fetch_metabolite_info(
            candidate, pool_match, fetch_fn=fetch_metabolite_info_fn,
        )
        if fetch_note:
            notes.append(fetch_note)

        # Zwitterion heuristic — display-only, never enters scoring.
        if _smiles_zwitterion_hint(candidate.smiles):
            notes.append(
                "zwitterion SMILES detected — HMDB may store the protonated "
                "cation form (D-1); mass_match_indicator uses the SMILES-"
                "derived neutral mass, not HMDB's exact_mass."
            )

        # D2 (requires a resolved metabolite_info with an HMDB/KEGG cross-ref)
        pw, pw_note = _safe_pathway_context(
            info, co_observed_ids=co_observed, pathway_context_fn=pathway_context_fn,
        )
        if pw_note:
            notes.append(pw_note)

        # E — only for the top `predict_top_n` (the rest get None for cosine)
        pred_resp: PredictSpectrumResponse | None = None
        pred_cosine: float | None = None
        if rank < predict_top_n:
            pred_resp, pred_cosine, pred_note = _safe_predict_spectrum(
                candidate, spectrum, predict_fn=predict_spectrum_fn,
            )
            if pred_note:
                notes.append(pred_note)
        else:
            notes.append(
                f"predict_spectrum: skipped (rank {rank} > predict_top_n={predict_top_n})"
            )

        predict_responses.append(pred_resp)

        # Score components
        mm = _mass_match_indicator(
            candidate.smiles,
            prefilter_resp.neutral_mass_computed,
            ppm=mass_tolerance_ppm,
        )
        pp = _pathway_presence_indicator(pw)
        score = CandidateReport.compute_evidence_score(
            candidate_score=candidate.score,
            predicted_spectrum_cosine=pred_cosine,
            mass_match_indicator=mm,
            pathway_presence_indicator=pp,
        )

        enriched.append(
            CandidateReport(
                candidate=candidate,
                prefilter_match=pool_match,
                metabolite_info=info,
                pathway_context=pw,
                predicted_spectrum_cosine=pred_cosine,
                predicted_model_version=(pred_resp.model_version if pred_resp else None),
                mass_match_indicator=mm,
                pathway_presence_indicator=pp,
                evidence_score=score,
                notes=notes,
            )
        )
        per_cand_notes.append(notes)

    # STAGE 6 — sort by evidence_score descending (stable: higher score wins)
    enriched.sort(key=lambda r: r.evidence_score, reverse=True)

    # STAGE 7 — literature_search per top-N (configurable; 0 disables F).
    # Runs AFTER ranking so the literature budget targets the candidates
    # the user is most likely to cite. Failures degrade per-candidate; the
    # rest of the pipeline is unaffected.
    literature_degradation_count = 0
    if literature_top_n > 0:
        for rank in range(min(literature_top_n, len(enriched))):
            cr = enriched[rank]
            recs, lit_note = _safe_literature_search(
                cr.candidate,
                max_results=literature_max_results,
                literature_search_fn=literature_search_fn,
            )
            cr.literature_records = recs
            if lit_note:
                cr.notes.append(lit_note)
                literature_degradation_count += 1

    # STAGE 8 — assemble the report
    warnings_list = _summarise_warnings(
        preprocess_resp, prefilter_resp, library_resp, generate_resp, per_cand_notes,
    )
    if generate_degradation_note is not None:
        warnings_list.append(generate_degradation_note)
    if literature_top_n == 0:
        warnings_list.append(
            "literature_search: skipped (literature_top_n=0)"
        )
    elif literature_degradation_count > 0:
        warnings_list.append(
            f"literature_search: {literature_degradation_count} candidate(s) "
            "ran with degraded output — see candidate notes"
        )
    return IdentificationReport(
        experimental_spectrum=spectrum,
        preprocess_quality_flag=preprocess_resp.quality_flag,
        neutral_mass_computed=prefilter_resp.neutral_mass_computed,
        n_prefilter_candidates=len(prefilter_resp.candidates),
        n_library_candidates=len(library_resp.candidates),
        n_generated_candidates=len(generate_resp.candidates),
        candidates=enriched,
        pipeline_version=_current_git_describe(),
        tool_versions=_collect_tool_versions(predict_responses),
        warnings=warnings_list,
    )


# ---------------------------------------------------------------------------
# CLI + fixture loader
# ---------------------------------------------------------------------------


_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "spectra"
_KNOWN_FIXTURES = ["glucose_pos", "caffeine_pos", "lcarnitine_pos"]


def _load_fixture(name: str) -> tuple[PreprocessRequest, dict[str, Any]]:
    """Load a fixture JSON and build the PreprocessRequest + metadata dict."""
    path = _FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"fixture not found: {path}")
    data = json.loads(path.read_text())
    peaks = data["peaks"]
    req = PreprocessRequest(
        raw_mz=[float(p[0]) for p in peaks],
        raw_intensity=[float(p[1]) for p in peaks],
        precursor_mz=float(data["precursor_mz"]),
        adduct=data["adduct"],
        ionization_mode=data["ionization_mode"],
        collision_energy=(
            float(data["collision_energy"]) if data.get("collision_energy") is not None else None
        ),
    )
    meta = {
        "compound_name": data["compound_name"],
        "smiles": data["smiles"],
        "inchikey": data["inchikey"],
        "hmdb_id": data["hmdb_id"],
    }
    return req, meta


def _render_json(report: IdentificationReport) -> str:
    return report.model_dump_json(indent=2)


def _render_md(report: IdentificationReport, meta: dict[str, Any]) -> str:
    """Compact markdown rendering — readable in 80 cols, not pretty."""
    lines: list[str] = []
    lines.append(f"# IdentificationReport — {meta.get('compound_name', '?')}")
    lines.append("")
    lines.append(f"- pipeline_version: `{report.pipeline_version}`")
    lines.append(f"- neutral_mass_computed: {report.neutral_mass_computed:.5f}")
    lines.append(f"- preprocess_quality_flag: {report.preprocess_quality_flag}")
    lines.append(
        f"- candidate counts: prefilter={report.n_prefilter_candidates}, "
        f"library={report.n_library_candidates}, generated={report.n_generated_candidates}, "
        f"merged_top_k={len(report.candidates)}"
    )
    lines.append("")
    lines.append("## tool_versions")
    for k, v in report.tool_versions.items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## warnings")
    for w in report.warnings:
        lines.append(f"- {w}")
    lines.append("")
    lines.append("## top candidates")
    lines.append("")
    lines.append(
        "| rank | score | cand.score | cos(E) | mass | pw | name | SMILES |"
    )
    lines.append(
        "|---:|---:|---:|---:|---:|---:|---|---|"
    )
    for i, c in enumerate(report.candidates, 1):
        cos_str = "—" if c.predicted_spectrum_cosine is None else f"{c.predicted_spectrum_cosine:.3f}"
        name = (c.metabolite_info.primary_name if c.metabolite_info and c.metabolite_info.found else c.candidate.name) or "?"
        smi = c.candidate.smiles
        if len(smi) > 40:
            smi = smi[:37] + "..."
        lines.append(
            f"| {i} | {c.evidence_score:.3f} | {c.candidate.score:.3f} | {cos_str} | "
            f"{c.mass_match_indicator:.0f} | {c.pathway_presence_indicator:.0f} | "
            f"{name} | `{smi}` |"
        )
    lines.append("")
    lines.append("## per-candidate notes")
    for i, c in enumerate(report.candidates, 1):
        if not c.notes:
            continue
        lines.append(f"### #{i} {c.candidate.smiles}")
        for n in c.notes:
            lines.append(f"- {n}")
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, choices=_KNOWN_FIXTURES)
    parser.add_argument("--output", choices=["json", "md"], default="md")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--predict-top-n", type=int, default=5)
    parser.add_argument(
        "--fp-strategy",
        choices=_VALID_FP_STRATEGIES,
        default=os.environ.get("METAGENT_FP_STRATEGY", "topn_60"),
        help=(
            "Fingerprint source for Stage 3b (molecule_generate). "
            "Default is fusion of library_search candidates; "
            "set 'sirius' for the legacy CSI:FingerID path. "
            "Override via METAGENT_FP_STRATEGY env var."
        ),
    )
    parser.add_argument(
        "--literature-top-n",
        type=int,
        default=int(os.environ.get("METAGENT_LITERATURE_TOP_N", "3")),
        help=(
            "Number of top-ranked candidates to enrich with literature_search "
            "(Stage 7). Default 3. Set 0 to skip Track F entirely. "
            "Override via METAGENT_LITERATURE_TOP_N env var."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        req, meta = _load_fixture(args.fixture)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"fixture load failed: {exc}", file=sys.stderr)
        return 1

    t0 = time.perf_counter()
    try:
        report = identify(
            req,
            top_k=args.top_k,
            predict_top_n=args.predict_top_n,
            fingerprint_strategy=args.fp_strategy,
            literature_top_n=args.literature_top_n,
        )
    except Exception as exc:
        print(f"pipeline crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2
    elapsed = time.perf_counter() - t0

    if args.output == "json":
        print(_render_json(report))
    else:
        print(_render_md(report, meta))
        print(f"\n_(wall time: {elapsed:.1f} s)_")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
