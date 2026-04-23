"""Track E — ``predict_spectrum``.

Public entry point: ``predict_spectrum(req) -> PredictSpectrumResponse``.

Pipeline:
  1. Validate the SMILES with RDKit up front. CFM-ID's error surface on
     invalid input is ugly; it is much cheaper to reject here than to wait
     60 s for a timeout.
  2. Forbid v0-unsupported negative ionization per the project-wide scope.
  3. Call the CFM-ID shim through ``cfm_client``.
  4. Parse the shim's raw stdout into three energy blocks.
  5. For each requested collision energy, build a ``Spectrum`` (sorted,
     deduped, normalised, capped to ``top_n_peaks``).
  6. Union those three spectra into a single representative spectrum —
     taking the maximum intensity per merged m/z so dominant fragments
     from any energy survive — and renormalise.
  7. Render a templated ``explain`` string (no LLM).

CFM-ID 4.0 always emits three energy ramps labelled ``energy0/1/2``; by
convention these are the pre-trained 10 / 20 / 40 eV models. The tool
accepts the user's requested ``collision_energies`` list as *labels* for
the output dict keys; when the user gives exactly three energies we map
them positionally, otherwise we fall back to the CFM-ID defaults and note
it in ``explain``.
"""
from __future__ import annotations

from common.rdkit_utils import canonicalize_smiles, is_valid_smiles
from schemas.common import Spectrum
from schemas.spectrum import PredictSpectrumRequest, PredictSpectrumResponse
from tools.spectrum_predict import cfm_client
from tools.spectrum_predict.errors import InvalidSmilesError
from tools.spectrum_predict.parser import normalise, parse_cfm_output, sort_and_dedup

# CFM-ID 4.0's three pre-trained collision energies, in eV. The labels are
# documented on https://cfmid.wishartlab.com/ — the model has no knob for
# arbitrary energies, so we map energy0/1/2 onto these fixed values when the
# caller does not supply exactly three custom labels.
_CFM_DEFAULT_ENERGIES_EV: tuple[float, float, float] = (10.0, 20.0, 40.0)

# m/z tolerance for merging peaks across the three energy ramps into the
# union spectrum. CFM-ID's peaks are assigned exact masses from fragment
# structures, so 1e-4 Da is sufficient — anything larger risks collapsing
# distinct fragments that happen to lie close in mass.
_UNION_MZ_TOLERANCE: float = 1e-4


def _label_energies(requested: list[float]) -> tuple[list[float], bool]:
    """Return (labels_in_eV, used_defaults).

    The schema default is ``[10.0, 20.0, 40.0]``, which matches CFM-ID's
    fixed three energies. Any other length is rejected in favour of the
    defaults so downstream consumers always see a three-entry dict.
    """
    if len(requested) == 3:
        return list(requested), False
    return list(_CFM_DEFAULT_ENERGIES_EV), True


def _peaks_to_spectrum(
    peaks: list[tuple[float, float]],
    *,
    precursor_mz: float,
    adduct: str,
    ionization_mode: str,
    collision_energy: float | None,
    top_n: int,
) -> Spectrum | None:
    """Clean, normalise, cap, and wrap peaks into a Spectrum.

    Returns ``None`` for an empty peak list — callers decide whether that
    is acceptable at their level (``per_energy`` may contain an empty
    block; the union spectrum may not).
    """
    cleaned = sort_and_dedup(peaks)
    cleaned = normalise(cleaned)
    if not cleaned:
        return None
    # Keep the top-N by intensity, then re-sort by m/z for the Spectrum
    # schema (m/z must be ascending). Re-normalise in case the previous base
    # peak was removed — unlikely when the base peak is always the highest,
    # but the invariant must be preserved regardless.
    cleaned.sort(key=lambda p: p[1], reverse=True)
    cleaned = cleaned[: max(top_n, 1)]
    cleaned = normalise(cleaned)
    cleaned.sort(key=lambda p: p[0])
    return Spectrum(
        mz=[mz for mz, _ in cleaned],
        intensity=[i for _, i in cleaned],
        precursor_mz=precursor_mz,
        adduct=adduct,
        ionization_mode=ionization_mode,  # type: ignore[arg-type]
        collision_energy=collision_energy,
    )


def _union_peaks(
    per_energy_peaks: list[list[tuple[float, float]]],
    *,
    tolerance: float = _UNION_MZ_TOLERANCE,
) -> list[tuple[float, float]]:
    """Merge peaks across energies, keeping max intensity per m/z bucket.

    Each energy's peak list is assumed to already be (sorted, deduped,
    normalised to its own base peak). The union collapses m/z values that
    differ by less than ``tolerance`` (CFM-ID assigns exact fragment masses,
    so a tight tolerance is intentional) and records the maximum intensity
    seen across energies — this preserves dominant fragments from any
    single energy rather than averaging them away.
    """
    merged: list[tuple[float, float]] = []
    for peaks in per_energy_peaks:
        merged.extend(peaks)
    merged.sort(key=lambda p: p[0])

    out: list[tuple[float, float]] = []
    for mz, intensity in merged:
        if out and abs(mz - out[-1][0]) <= tolerance:
            prev_mz, prev_i = out[-1]
            if intensity > prev_i:
                out[-1] = (mz, intensity)
            else:
                out[-1] = (prev_mz, prev_i)
        else:
            out.append((mz, intensity))
    return out


def _compute_precursor_mz(smiles: str, adduct: str) -> float:
    """Estimate the precursor m/z for the output Spectrum.

    CFM-ID does not round-trip the precursor in its text output, but the
    ``Spectrum`` schema requires ``precursor_mz > 0``. Computing from the
    molecular weight plus the adduct proton mass is close enough for
    verification — the verifier agent does not rely on this field being
    correct to high precision, only non-zero and positive.
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors

    mol = Chem.MolFromSmiles(smiles)
    # is_valid_smiles has already run upstream, so mol is not None here.
    mw = float(Descriptors.ExactMolWt(mol))  # type: ignore[arg-type]
    # Minimal adduct table — enough to keep the value plausible. The full
    # mass-correction table lives in candidate_prefilter (Track A2); we
    # don't duplicate it because a wrong precursor here is not load-bearing.
    proton = 1.00728
    sodium = 22.98922
    if adduct == "[M+H]+":
        return mw + proton
    if adduct == "[M+Na]+":
        return mw + sodium
    if adduct == "[M-H]-":
        return mw - proton
    # Unknown adduct: fall back to neutral mass. The Spectrum schema only
    # requires > 0, so this is safe and auditable.
    return mw


def predict_spectrum(req: PredictSpectrumRequest) -> PredictSpectrumResponse:
    # v0 scope gate — negative mode is not tested, so refuse at the boundary
    # rather than ship an unvalidated code path. Matches spectrum_preprocess.
    if req.ionization_mode == "negative":
        raise NotImplementedError(
            "predict_spectrum v0 supports positive ionization only."
        )

    if not is_valid_smiles(req.smiles):
        raise InvalidSmilesError(
            f"RDKit could not parse SMILES={req.smiles!r}. "
            "Canonicalise before calling predict_spectrum."
        )

    # Use the canonical SMILES for the container call. Some CFM-ID builds
    # are sensitive to atom ordering; canonicalising up-front avoids
    # unexplained misses.
    canon = canonicalize_smiles(req.smiles) or req.smiles

    cfm_resp = cfm_client.predict(
        smiles=canon,
        adduct=req.adduct,
        ionization_mode=req.ionization_mode,
    )

    parsed = parse_cfm_output(cfm_resp.cfm_stdout)
    labels, used_defaults = _label_energies(req.collision_energies)
    precursor_mz = _compute_precursor_mz(canon, req.adduct)

    per_energy: dict[float, Spectrum] = {}
    normalised_blocks: list[list[tuple[float, float]]] = []
    for idx, ev in enumerate(labels):
        raw_peaks = parsed.get(idx, [])
        # Store the pre-normalised peaks so the union uses intensities
        # comparable across energies (each block is normalised to its own
        # base peak before merging).
        block = normalise(sort_and_dedup(raw_peaks))
        normalised_blocks.append(block)
        spec = _peaks_to_spectrum(
            block,
            precursor_mz=precursor_mz,
            adduct=req.adduct,
            ionization_mode=req.ionization_mode,
            collision_energy=ev,
            top_n=req.top_n_peaks,
        )
        if spec is not None:
            per_energy[float(ev)] = spec

    union_peaks = _union_peaks(normalised_blocks)
    union_spec = _peaks_to_spectrum(
        union_peaks,
        precursor_mz=precursor_mz,
        adduct=req.adduct,
        ionization_mode=req.ionization_mode,
        collision_energy=None,  # union spans multiple energies
        top_n=req.top_n_peaks,
    )
    if union_spec is None:
        # CFM-ID ran but returned no peaks at any energy. The schema
        # requires at least one peak in a Spectrum, so this is a hard
        # failure — raise rather than return a fake peak.
        raise InvalidSmilesError(
            f"CFM-ID produced zero peaks for SMILES={canon!r}. "
            "The molecule may be too large, too simple, or outside the "
            "model's training distribution."
        )

    explain_parts = [
        f"Predicted {len(union_spec.mz)} union peaks across energies "
        f"{[float(e) for e in labels]} eV using {cfm_resp.model_version}.",
        f"Top m/z {union_spec.mz[union_spec.intensity.index(1.0)]:.4f} "
        f"at normalised intensity 1.00.",
    ]
    if used_defaults and req.collision_energies != list(_CFM_DEFAULT_ENERGIES_EV):
        explain_parts.append(
            f"Requested energies {req.collision_energies} were overridden "
            f"to the CFM-ID defaults {list(_CFM_DEFAULT_ENERGIES_EV)} because "
            "CFM-ID 4.0 only exposes three pre-trained models."
        )

    return PredictSpectrumResponse(
        predicted=union_spec,
        per_energy=per_energy,
        model_version=cfm_resp.model_version,
        explain=" ".join(explain_parts),
    )
