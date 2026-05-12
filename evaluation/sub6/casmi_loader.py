"""Phase 6.6 — CASMI 2022 / 2016 loader for OOD identification benchmark.

CASMI's evaluation differs from Sub-6A v2 in one critical way: the candidate
search space is the molecular-formula-restricted slice of PubChem (MIST-paper
convention), NOT GNPS. We therefore inject a per-spectrum
``LibrarySearchRequest.candidate_pool`` of PubChem candidates and run the
identification with ``libraries=("inhouse",)``, ``use_gnps=False``. Modified-
cosine cannot run on PubChem candidates (no reference spectrum); MS-CLIP scores
every candidate by spectrum-vs-structure embedding similarity.

CASMI 2022 layout (MIST preprocessed):
  spec_files/<spec>.ms        # SIRIUS-format peak list + metadata
  labels_true.tsv             # spec → name / formula / smiles / inchikey / ionization
  retrieval_hdf/...index.p    # formula → {offset, length} into the candidates table
  retrieval_hdf/...names.p    # int → SMILES (string) for each candidate
  retrieval_hdf/...hdf5       # 4096-bit Morgan fingerprints (not used here)

This loader produces:
  task records — one per spec — compatible with Sub-6A's
                ``differential_spectra`` shape so the existing pipeline machinery
                (spectrum normalisation, identify_spectrum) can operate on them
                with minimal adapters.
  candidate pools — list[PrefilteredCandidate] keyed by spec id; each candidate
                has source_pool="pubchem_lite", molecular_formula matching the
                spec's GT formula, exact_mass computed from formula, and
                has_reference_spectrum=False (MS-CLIP only).
"""
from __future__ import annotations

import logging
import pickle
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from schemas.common import PrefilteredCandidate

logger = logging.getLogger(__name__)


_ATOMIC_MASSES = {
    "H": 1.00782503207, "D": 2.01410177812, "C": 12.0, "N": 14.0030740048,
    "O": 15.99491461956, "F": 18.99840322, "P": 30.97376163, "S": 31.97207100,
    "Cl": 34.96885268, "Br": 78.9183371, "I": 126.904473, "Na": 22.9897692809,
    "K": 38.96370668, "Si": 27.97692653,
}
_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)")


def formula_exact_mass(formula: str) -> float:
    """Monoisotopic neutral mass of ``formula`` (e.g. 'C25H25N7O3')."""
    total = 0.0
    for el, count in _FORMULA_TOKEN.findall(formula):
        if not el:
            continue
        if el not in _ATOMIC_MASSES:
            raise KeyError(f"unknown element {el!r} in formula {formula!r}")
        n = int(count) if count else 1
        total += _ATOMIC_MASSES[el] * n
    if total <= 0:
        raise ValueError(f"non-positive mass for formula {formula!r}")
    return total


@dataclass
class CasmiSpec:
    """One CASMI spectrum + GT + raw peak list (pre-normalisation)."""

    spectrum_id: str
    dataset: str
    formula: str
    smiles: str
    inchikey: str
    inchikey_first_block: str
    adduct: str
    ion_mode: str  # "positive" | "negative"
    precursor_mz: float
    peaks: list[tuple[float, float]] = field(default_factory=list)


def _parse_ms_file(path: Path) -> dict:
    """Parse a SIRIUS-format .ms file. Returns dict with metadata + peaks.

    Format:
      >compound <id>
      >formula <C..H..>
      >parentmass <float>
      >Ionization <[M+H]+ etc>
      >InChIKey <ik>
      #smiles <smi>
      ...
      >ms2
      mz intensity
      mz intensity
      ...
    Multiple >ms2 blocks may appear (different collision energies). We pool all
    peaks across blocks; downstream identification re-normalises intensities.
    """
    meta: dict = {"peaks": []}
    in_ms2 = False
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(">"):
            head = s[1:].split(None, 1)
            key = head[0].lower()
            val = head[1] if len(head) > 1 else ""
            if key == "ms2":
                in_ms2 = True
            elif key in ("ms1", "ms1peaks", "collision"):
                in_ms2 = False
            else:
                in_ms2 = False
                meta[key] = val
            continue
        if s.startswith("#"):
            head = s[1:].split(None, 1)
            if head:
                meta["#" + head[0].lower()] = head[1] if len(head) > 1 else ""
            continue
        if in_ms2:
            parts = s.split()
            if len(parts) >= 2:
                try:
                    mz = float(parts[0]); inten = float(parts[1])
                except ValueError:
                    continue
                if inten > 0:
                    meta["peaks"].append((mz, inten))
    return meta


def _parse_mgf_file(path: Path) -> dict:
    """Parse a CASMI-2016 MGF file. Returns dict with peaks + headers.

    Format (single BEGIN IONS block per file):
      NAME=Challenge-XXX.mgf
      # Splash: ...
      SOURCE_INSTRUMENT=...
      ACTIVATION=...
      BEGIN IONS
      PEPMASS=<precursor mz>
      RTINSECONDS=<float>
      CHARGE=1+
      TITLE=...
      SCANS=1
      <mz> <intensity>
      ...
      END IONS

    All 208 CASMI 2016 cat2 MGFs have exactly one IONS block (verified).
    """
    meta: dict = {"peaks": []}
    in_ions = False
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s == "BEGIN IONS":
            in_ions = True
            continue
        if s == "END IONS":
            in_ions = False
            continue
        if "=" in s and (not in_ions or s.split("=", 1)[0].isupper()):
            key, val = s.split("=", 1)
            meta[key.lower()] = val
            continue
        if in_ions:
            parts = s.split()
            if len(parts) >= 2:
                try:
                    mz = float(parts[0]); inten = float(parts[1])
                except ValueError:
                    continue
                if inten > 0:
                    meta["peaks"].append((mz, inten))
    return meta


def _adduct_from_ion_mode(ion_mode: str) -> str:
    """CASMI 2016 cat2 GT records ION_MODE only (no explicit adduct).
    Choose the standard adduct convention used by MIST/MSAgent on this set:
      positive → [M+H]+
      negative → [M-H]-
    """
    if ion_mode.strip().upper() == "NEGATIVE":
        return "[M-H]-"
    return "[M+H]+"


def _ion_mode_from_adduct(adduct: str) -> str:
    a = (adduct or "").strip()
    if a.endswith("-") or "[M-" in a:
        return "negative"
    return "positive"


def load_casmi_2022_specs(root: Path) -> list[CasmiSpec]:
    """Load all CASMI 2022 spectra with GT.

    ``root`` should point at preprocessed/casmi2022/ (the dir containing
    spec_files, labels_true.tsv).
    """
    import pandas as pd

    df = pd.read_csv(root / "labels_true.tsv", sep="\t")
    spec_dir = root / "spec_files"
    out: list[CasmiSpec] = []
    for _, row in df.iterrows():
        sid = row["spec"]
        ms_path = spec_dir / f"{sid}.ms"
        if not ms_path.exists():
            logger.warning("CASMI 2022: missing .ms for %s", sid)
            continue
        meta = _parse_ms_file(ms_path)
        if not meta["peaks"]:
            logger.warning("CASMI 2022: %s has no MS2 peaks, skipping", sid)
            continue
        ik = str(row["inchikey"])
        ik_block = ik.split("-")[0] if ik else ""
        adduct = str(row["ionization"]) or meta.get("ionization", "[M+H]+")
        precursor = meta.get("parentmass")
        try:
            precursor_mz = float(precursor) if precursor else 0.0
        except ValueError:
            precursor_mz = 0.0
        # Fallback: compute precursor from formula + adduct mass shift
        if precursor_mz <= 0.0:
            try:
                precursor_mz = formula_exact_mass(str(row["formula"])) + 1.00728  # +H
            except Exception:
                logger.warning("CASMI 2022: %s no usable precursor", sid)
                continue
        out.append(CasmiSpec(
            spectrum_id=sid,
            dataset="casmi2022",
            formula=str(row["formula"]),
            smiles=str(row["smiles"]),
            inchikey=ik,
            inchikey_first_block=ik_block,
            adduct=adduct,
            ion_mode=_ion_mode_from_adduct(adduct),
            precursor_mz=precursor_mz,
            peaks=meta["peaks"],
        ))
    return out


# ---------------------------------------------------------------------------
# CASMI 2016 cat2 loader (Phase 6.7-C)
# ---------------------------------------------------------------------------


DEFAULT_CASMI_2016_CAT2_ROOT = Path(
    "/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2016/category2"
)


def load_casmi_2016_cat2_specs(root: Path | None = None) -> list[CasmiSpec]:
    """Load all 208 CASMI 2016 cat2 spectra with GT.

    ``root`` defaults to ``DEFAULT_CASMI_2016_CAT2_ROOT``. Expects:
      ``challenges/Challenge-XXX.mgf``     — one MGF per challenge (1 spec each)
      ``../solutions/solutions_casmi2016_cat2and3.csv`` — GT table

    Unlike CASMI 2022 (where the candidate pool is formula-restricted via
    a MIST-style retrieval_hdf), CASMI 2016 cat2 supplies a separate
    per-challenge candidate CSV (Challenge-XXX.csv) inside the
    Challenge_Candidates zip — those candidates are mass-tolerant retrieval
    over PubChem (typically 9-15 unique formulas per challenge). The
    candidate pool is therefore loaded by ``build_casmi_2016_pool(...)``
    separately, not embedded in CasmiSpec.
    """
    import csv

    root = root or DEFAULT_CASMI_2016_CAT2_ROOT
    sol_path = root.parent / "solutions" / "solutions_casmi2016_cat2and3.csv"
    if not sol_path.exists():
        raise FileNotFoundError(sol_path)
    chal_dir = root / "challenges"

    out: list[CasmiSpec] = []
    with sol_path.open() as f:
        for row in csv.DictReader(f):
            name = row["ChallengeName"]
            mgf_path = chal_dir / f"{name}.mgf"
            if not mgf_path.exists():
                logger.warning("CASMI 2016: missing MGF for %s", name)
                continue
            meta = _parse_mgf_file(mgf_path)
            if not meta["peaks"]:
                logger.warning("CASMI 2016: %s has no MS2 peaks, skipping", name)
                continue
            ik = (row.get("INCHIKEY") or "").strip()
            ik_block = ik.split("-")[0] if ik else ""
            ion_mode_raw = (row.get("ION_MODE") or "").strip()
            ion_mode = "negative" if ion_mode_raw.upper() == "NEGATIVE" else "positive"
            adduct = _adduct_from_ion_mode(ion_mode_raw)
            try:
                precursor_mz = float(row.get("PRECURSOR_MZ") or 0.0)
            except ValueError:
                precursor_mz = 0.0
            if precursor_mz <= 0.0:
                pep = meta.get("pepmass")
                if pep:
                    try:
                        precursor_mz = float(pep.split()[0])
                    except ValueError:
                        precursor_mz = 0.0
            if precursor_mz <= 0.0:
                logger.warning("CASMI 2016: %s has no usable precursor; skipping", name)
                continue
            # CASMI 2016 GT does not record molecular formula explicitly —
            # canonicalise from SMILES so downstream verifier still has it.
            smiles = (row.get("SMILES") or "").strip()
            formula = _formula_from_smiles(smiles)
            out.append(CasmiSpec(
                spectrum_id=name,
                dataset="casmi2016_cat2",
                formula=formula or "",
                smiles=smiles,
                inchikey=ik,
                inchikey_first_block=ik_block,
                adduct=adduct,
                ion_mode=ion_mode,
                precursor_mz=precursor_mz,
                peaks=meta["peaks"],
            ))
    return out


def _formula_from_smiles(smiles: str) -> str | None:
    if not smiles:
        return None
    try:
        from rdkit import Chem
        from rdkit.Chem.rdMolDescriptors import CalcMolFormula
        mol = Chem.MolFromSmiles(smiles)
        return CalcMolFormula(mol) if mol else None
    except Exception:
        return None


DEFAULT_CASMI_2016_CANDIDATES_DIR = Path(
    "/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2016/category2/candidates_extracted"
)


def build_casmi_2016_pool(
    challenge_name: str,
    precursor_mz: float | None,
    *,
    candidates_dir: Path | None = None,
    max_candidates: int | None = None,
    must_include_smiles: str | None = None,
) -> list[PrefilteredCandidate]:
    """Read Challenge-XXX.csv (extracted from the CASMI 2016 candidates zip)
    and return a PrefilteredCandidate list.

    Candidates carry mass-tolerance-retrieval-style mixed formulas; each
    candidate's `mass_error_ppm` is computed against the precursor m/z
    assuming the +H or −H adduct from ion mode (cosmetic; library_search's
    msclip path ranks by spectrum-vs-structure embedding, not by mass).
    """
    import csv

    candidates_dir = candidates_dir or DEFAULT_CASMI_2016_CANDIDATES_DIR
    csv_path = candidates_dir / f"{challenge_name}.csv"
    if not csv_path.exists():
        return []
    out: list[PrefilteredCandidate] = []
    seen_smi: set[str] = set()
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            smi = (row.get("SMILES") or "").strip()
            if not smi or smi in seen_smi:
                continue
            seen_smi.add(smi)
            formula = (row.get("MolecularFormula") or "").strip()
            try:
                mass = float(row.get("MonoisotopicMass") or 0.0)
            except ValueError:
                mass = 0.0
            if mass <= 0.0:
                try:
                    mass = formula_exact_mass(formula)
                except Exception:
                    continue
            ppm = 0.0
            if precursor_mz and precursor_mz > 0:
                # Approximate neutral mass via ±H adduct shift
                neutral = float(precursor_mz) - 1.00728
                if neutral > 0:
                    ppm = abs(mass - neutral) / neutral * 1e6
            ident = row.get("Identifier") or row.get("InChIKey") or smi
            out.append(PrefilteredCandidate(
                smiles=smi,
                name=row.get("CompoundName") or None,
                source_pool="pubchem_lite",
                source_id=f"CASMI16:{challenge_name}:{ident}",
                molecular_formula=formula or "C",
                exact_mass=float(mass),
                mass_error_ppm=float(ppm),
                has_reference_spectrum=False,
            ))
    if max_candidates is not None and len(out) > max_candidates:
        out = out[:max_candidates]
    if must_include_smiles and must_include_smiles not in seen_smi:
        # Mostly for diagnostic — track when truncation drops the GT.
        logger.debug("CASMI 2016: GT SMILES not in pool for %s", challenge_name)
    return out


def casmi_spec_to_task_dict_2016(spec: CasmiSpec) -> dict:
    """Same shape as casmi_spec_to_task_dict but with 2016-specific provenance."""
    d = casmi_spec_to_task_dict(spec)
    d["casmi_dataset"] = spec.dataset
    return d


def casmi_spec_to_task_dict(spec: CasmiSpec) -> dict:
    """Convert a CasmiSpec into the dict shape that ``identify_spectrum``
    accepts (Sub-6A's differential_spectra entry)."""
    return {
        "spectrum_id": spec.spectrum_id,
        "source_id": None,  # CASMI has no GNPS source — exclusion list is empty
        "inchikey_first_block": spec.inchikey_first_block,
        "ion_mode": spec.ion_mode,
        "adduct": spec.adduct,
        "precursor_mz": spec.precursor_mz,
        "peaks": list(spec.peaks),
        # For provenance / downstream report:
        "casmi_dataset": spec.dataset,
        "casmi_formula": spec.formula,
        "casmi_gt_smiles": spec.smiles,
        "casmi_gt_inchikey": spec.inchikey,
    }


# ---------------------------------------------------------------------------
# PubChem candidate-pool builder (CASMI 2022 retrieval_hdf format)
# ---------------------------------------------------------------------------


@dataclass
class PubChemRetrievalIndex:
    """Lightweight loader for the MIST-style retrieval pickle pair.

    Holds:
      formula → {offset, length} index into the SMILES list.
      int → SMILES dict (sequential).
    Loaded once per process; reused across spectra.
    """

    index: dict
    names: dict  # int → SMILES

    @classmethod
    def from_dir(cls, retrieval_dir: Path,
                 *,
                 prefix: str = "intpubchem_with_morgan4096_retrieval_db") -> "PubChemRetrievalIndex":
        idx_path = retrieval_dir / f"{prefix}_index.p"
        names_path = retrieval_dir / f"{prefix}_names.p"
        with idx_path.open("rb") as f:
            idx = pickle.load(f)
        with names_path.open("rb") as f:
            names = pickle.load(f)
        logger.info("PubChem retrieval loaded: %d formulas, %d names", len(idx), len(names))
        return cls(index=idx, names=names)

    def candidates_for_formula(self, formula: str) -> list[str]:
        """Return all PubChem SMILES with the given molecular formula. Empty
        list when the formula is absent from the index (the MIST corpus is
        formula-finite — only formulas seen in CASMI labels are indexed)."""
        e = self.index.get(formula)
        if not e:
            return []
        off = int(e["offset"]); ln = int(e["length"])
        return [self.names[i] for i in range(off, off + ln)]


def build_pubchem_pool(
    formula: str,
    precursor_mz: float | None,
    retrieval: PubChemRetrievalIndex,
    *,
    max_candidates: int | None = None,
    must_include_smiles: str | None = None,
) -> list[PrefilteredCandidate]:
    """Materialise a PrefilteredCandidate list for ``formula``.

    Optional ``max_candidates`` truncates the slice (selection is in pool
    order, which is the MIST corpus order — for sanity tests; the full pool
    is the default).

    ``must_include_smiles`` (typically the GT SMILES) is appended if absent
    so the GT is reachable when the slice is truncated. Use sparingly: a
    realistic OOD evaluation shouldn't surreptitiously inject the GT, but
    truncation is unavoidable for very large formula slices (~30K), so we
    document and gate this behaviour.
    """
    smiles_list = retrieval.candidates_for_formula(formula)
    if not smiles_list:
        return []
    exact_mass = formula_exact_mass(formula)
    # Neutral mass error ppm — for the no-spectrum candidates this is
    # cosmetic (msclip drives ranking), but the schema requires it.
    ppm = 0.0
    if precursor_mz is not None and precursor_mz > 0:
        # Approximate the neutral query mass using +H adduct (CASMI 2022
        # majority); precise per-adduct shift is unnecessary for the cosmetic
        # value.
        neutral = float(precursor_mz) - 1.00728
        if neutral > 0:
            ppm = abs(exact_mass - neutral) / max(neutral, 1e-6) * 1e6
    if max_candidates is not None and max_candidates > 0:
        truncated = list(smiles_list[:max_candidates])
        if must_include_smiles and must_include_smiles not in truncated:
            if must_include_smiles in smiles_list:
                truncated.append(must_include_smiles)
        smiles_list = truncated
    out: list[PrefilteredCandidate] = []
    seen_smi: set[str] = set()
    for i, smi in enumerate(smiles_list):
        if not smi or smi in seen_smi:
            continue
        seen_smi.add(smi)
        out.append(PrefilteredCandidate(
            smiles=smi,
            name=None,
            source_pool="pubchem_lite",
            source_id=f"PUBCHEM_LITE:{formula}#{i}",
            molecular_formula=formula,
            exact_mass=float(exact_mass),
            mass_error_ppm=float(ppm),
            has_reference_spectrum=False,
        ))
    return out
