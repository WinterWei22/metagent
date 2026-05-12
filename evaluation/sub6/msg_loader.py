"""Phase 6.7-D — MassSpecGym (MSG) loader for OOD identification benchmark.

MSG evaluation mirrors the CASMI 2022 protocol (candidate-pool injection +
MS-CLIP scoring) but differs in four ways:

1. Spectrum files are per-ID JSON dicts (`pred_<ID>.json`) with keys
   ``raw_spec`` ([[mz, intensity], ...]) and ``prec_mz``.
2. Candidate JSON is keyed by **GT SMILES** (not molecular formula or spec ID).
   Two pools:
     ``formula`` — same molecular formula as GT (PubChem isomers, up to 256)
     ``mass``    — mass-window PubChem compounds (up to 256, almost disjoint
                   from the formula pool at the per-compound level)
3. Test split is provided via ``splits/split_msg.tsv``.
4. Collision energy is embedded in ``labels.tsv``.collision_energies and
   should be passed to MS-CLIP (checkpoint was trained with embed_ce=True).

The loader produces:
  ``MsgSpec`` — one per selected test spectrum
  ``build_msg_pool`` — candidate list from the pre-built JSON
  ``msg_spec_to_task_dict`` — adapter to the identify_spectrum dict shape
"""
from __future__ import annotations

import csv
import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from schemas.common import PrefilteredCandidate
from evaluation.sub6.casmi_loader import formula_exact_mass

logger = logging.getLogger(__name__)

MSG_SPEC_DIR = Path(
    "/data/weiwentao/ms-pred/results/dag_msg_train"
    "/split_msg_rnd1/preds_train_20_inten_corrected"
)
MSG_DATA_DIR = Path("/home/weiwentao/workspace/ms-pred/data/spec_datasets/msg")

DEFAULT_MSG_LABELS = MSG_DATA_DIR / "labels.tsv"
DEFAULT_MSG_SPLIT = MSG_DATA_DIR / "splits/split_msg.tsv"
DEFAULT_FORMULA_CANDS = MSG_DATA_DIR / "retrieval/MassSpecGym_retrieval_candidates_formula.json"
DEFAULT_MASS_CANDS = MSG_DATA_DIR / "retrieval/MassSpecGym_retrieval_candidates_mass.json"


@dataclass
class MsgSpec:
    """One MSG test spectrum + GT metadata."""

    spectrum_id: str           # e.g. "MassSpecGymID0337069"
    formula: str
    smiles: str                # GT canonical SMILES (candidate pool lookup key)
    inchikey: str              # full InChIKey
    inchikey_first_block: str  # first 14 chars
    adduct: str                # e.g. "[M+H]+"
    ion_mode: str              # "positive" | "negative"
    precursor_mz: float
    collision_energy: float | None  # eV from labels.tsv; None when not parseable
    peaks: list[tuple[float, float]] = field(default_factory=list)


def _ion_mode(adduct: str) -> str:
    a = (adduct or "").strip()
    if a.endswith("-") or "[M-" in a:
        return "negative"
    return "positive"


def _parse_ce(raw: str) -> float | None:
    """Parse collision_energies column → float eV.

    MSG stores a single float per row (one spectrum per row).
    Fallback to None on parse failure.
    """
    if not raw or raw.strip() in ("", "nan", "None"):
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def load_msg_test_specs(
    labels_tsv: Path = DEFAULT_MSG_LABELS,
    split_tsv: Path = DEFAULT_MSG_SPLIT,
    spec_dir: Path = MSG_SPEC_DIR,
    *,
    n_sample: int = 500,
    seed: int = 42,
) -> list[MsgSpec]:
    """Load a random sample of MSG test-split spectra.

    Steps:
    1. Read ``split_tsv`` to collect test spec IDs.
    2. Randomly sample ``n_sample`` (seed-stable) from those IDs.
    3. Join sampled IDs with ``labels_tsv`` for GT metadata.
    4. Read each spectrum's JSON from ``spec_dir`` for peak list.

    Returns ``list[MsgSpec]`` in sampled order (deterministic for the same
    seed). Spectra whose JSON is missing or empty are skipped with a warning.
    """
    # Step 1: collect test IDs
    test_ids: list[str] = []
    with split_tsv.open() as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["split"] == "test":
                test_ids.append(row["name"])
    logger.info("MSG: %d total test spectra", len(test_ids))

    # Step 2: sample
    rng = random.Random(seed)
    sampled: list[str]
    if n_sample is not None and len(test_ids) > n_sample:
        sampled = rng.sample(test_ids, n_sample)
    else:
        sampled = list(test_ids)
    sampled_set = set(sampled)
    logger.info("MSG: sampled %d spectra (seed=%d)", len(sampled), seed)

    # Step 3: build GT metadata map from labels.tsv
    meta_map: dict[str, dict] = {}
    with labels_tsv.open() as f:
        for row in csv.DictReader(f, delimiter="\t"):
            sid = row["spec"]
            if sid in sampled_set:
                meta_map[sid] = row

    # Step 4: load spectrum peaks + assemble MsgSpec
    out: list[MsgSpec] = []
    for sid in sampled:
        meta = meta_map.get(sid)
        if meta is None:
            logger.warning("MSG: %s not found in labels.tsv", sid)
            continue
        spec_path = spec_dir / f"pred_{sid}.json"
        if not spec_path.exists():
            logger.warning("MSG: spectrum file missing: %s", spec_path)
            continue
        try:
            with spec_path.open() as f:
                spec_json = json.load(f)
        except Exception as exc:
            logger.warning("MSG: failed to read %s: %s", spec_path, exc)
            continue
        raw_spec = spec_json.get("raw_spec") or []
        if not raw_spec:
            logger.warning("MSG: %s has empty raw_spec", sid)
            continue
        peaks = [(float(mz), float(inten)) for mz, inten in raw_spec if inten > 0]
        if not peaks:
            logger.warning("MSG: %s has no positive-intensity peaks", sid)
            continue
        ik = meta.get("inchikey", "")
        ik_block = ik.split("-")[0] if ik else ""
        adduct = meta.get("ionization", "[M+H]+")
        ce = _parse_ce(meta.get("collision_energies", ""))
        try:
            prec = float(spec_json.get("prec_mz") or meta.get("precursor") or 0.0)
        except ValueError:
            prec = 0.0
        out.append(MsgSpec(
            spectrum_id=sid,
            formula=meta.get("formula", ""),
            smiles=meta.get("smiles", ""),
            inchikey=ik,
            inchikey_first_block=ik_block,
            adduct=adduct,
            ion_mode=_ion_mode(adduct),
            precursor_mz=prec,
            collision_energy=ce,
            peaks=peaks,
        ))
    logger.info("MSG: loaded %d spectra (of %d sampled)", len(out), len(sampled))
    return out


def load_candidates_json(candidates_json: Path) -> dict[str, list[str]]:
    """Load a MSG candidates JSON (keyed by GT SMILES → list[SMILES])."""
    logger.info("loading MSG candidates from %s", candidates_json)
    with candidates_json.open() as f:
        data = json.load(f)
    logger.info("loaded %d compound entries", len(data))
    return data


def build_msg_pool(
    gt_smiles: str,
    candidates: dict[str, list[str]],
    precursor_mz: float | None = None,
    *,
    gt_formula: str = "",
    max_candidates: int | None = None,
    pool_type: Literal["formula", "mass"] = "formula",
) -> list[PrefilteredCandidate]:
    """Build a PrefilteredCandidate list for one MSG spectrum.

    ``candidates`` is the pre-loaded JSON dict (GT SMILES → list[SMILES]).
    The pool is identified by ``gt_smiles`` (exact key lookup).

    ``gt_formula`` is used to compute ``exact_mass`` (required > 0 by schema).
    For formula-restricted pools all candidates share the same formula, so
    the GT exact_mass is a correct value. For mass-window pools the formula
    may vary slightly but the value is cosmetic (MS-CLIP drives ranking).
    Falls back to ``precursor_mz − 1.007`` when formula parsing fails.
    """
    smi_list = candidates.get(gt_smiles)
    if not smi_list:
        logger.debug("MSG: no candidates for GT SMILES %.40s... (pool=%s)",
                     gt_smiles, pool_type)
        return []
    if max_candidates is not None and len(smi_list) > max_candidates:
        smi_list = smi_list[:max_candidates]

    # Compute a shared exact_mass for the pool (cosmetic for MS-CLIP path).
    exact_mass = 0.0
    if gt_formula:
        try:
            exact_mass = formula_exact_mass(gt_formula)
        except Exception:
            pass
    if exact_mass <= 0.0 and precursor_mz and precursor_mz > 1.0:
        exact_mass = max(precursor_mz - 1.00728, 1.0)  # approx neutral mass

    out: list[PrefilteredCandidate] = []
    seen: set[str] = set()
    for i, smi in enumerate(smi_list):
        if not smi or smi in seen:
            continue
        seen.add(smi)
        out.append(PrefilteredCandidate(
            smiles=smi,
            name=None,
            source_pool="pubchem_lite",
            source_id=f"MSG:{pool_type}:{i}",
            molecular_formula=gt_formula or "",
            exact_mass=float(exact_mass),
            mass_error_ppm=0.0,
            has_reference_spectrum=False,
        ))
    return out


def msg_spec_to_task_dict(spec: MsgSpec) -> dict:
    """Convert MsgSpec to the dict shape that ``identify_spectrum`` accepts.

    Includes ``collision_energy`` so MS-CLIP receives the real CE value
    (checkpoint was trained with embed_ce=True, so this improves accuracy).
    """
    return {
        "spectrum_id": spec.spectrum_id,
        "source_id": None,  # no GNPS source — exclusion list is empty
        "inchikey_first_block": spec.inchikey_first_block,
        "ion_mode": spec.ion_mode,
        "adduct": spec.adduct,
        "precursor_mz": spec.precursor_mz,
        "collision_energy": spec.collision_energy,
        "peaks": list(spec.peaks),
        # Provenance fields for the output JSONL:
        "msg_formula": spec.formula,
        "msg_gt_smiles": spec.smiles,
        "msg_gt_inchikey": spec.inchikey,
    }
