"""Benchmark-protocol filtering, compound classification, and pool I/O.

Apply Section 2.2 of ``docs/decisions/2026-04-28_benchmark_protocol_v2.md``
to a stream of :class:`tools.benchmark.massbank_normalizer.NormalizedRecord`
objects, classify each surviving compound into one of the six benchmark
classes from Section 2.4, and bundle the result into a queryable
:class:`CompoundPool`.

Class assignment uses two paths, in priority order:

1. **ClassyFire**, via the existing ``tools.classyfire`` tool (with its
   own SQLite cache). We map the ClassyFire taxonomy strings to one of
   the six benchmark labels.
2. **SMARTS fallback** for environments where ClassyFire is offline. The
   patterns are intentionally conservative: they recognise the obvious
   cases (carboxylic acid, alpha-amino acid, glycerophospholipid, etc.)
   and return ``"other"`` rather than guessing.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from rdkit import Chem
from rdkit.Chem import AllChem  # noqa: F401  # imported for side effects

from schemas.common import Spectrum, ToolError
from tools.benchmark.massbank_normalizer import NormalizedRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CompoundPoolIOError(ToolError):
    """Failure while saving / loading a :class:`CompoundPool`."""

    code = "COMPOUND_POOL_IO_ERROR"
    recoverable = False


# ---------------------------------------------------------------------------
# FilterCriteria
# ---------------------------------------------------------------------------


CompoundClass = Literal[
    "amino_acid", "nucleoside", "organic_acid", "flavonoid",
    "lipid", "alkaloid", "other",
]
"""Exhaustive label set used by :func:`classify_compound`. Matches
benchmark protocol Section 2.4."""

ION_MODES: tuple[str, ...] = ("positive", "negative")


@dataclass
class FilterCriteria:
    """Filtering knobs.

    Defaults match Stage 1 of the benchmark protocol (§2.2). Override any
    field for sub-pool experiments.
    """

    ion_mode: list[str] | None = None
    """``["positive"]``, ``["negative"]``, or both. ``None`` keeps all."""

    instrument_types: list[str] | None = None
    """Substring whitelist over the raw ``AC$INSTRUMENT_TYPE`` value
    (case-insensitive). E.g. ``["Q-TOF", "Orbitrap", "QFT", "FT-ICR"]``.
    ``None`` keeps all."""

    ms_level: list[str] | None = None
    """E.g. ``["MS2"]``. ``None`` keeps all."""

    min_peaks: int = 15
    """Inclusive lower bound on peak count after normalisation."""

    precursor_mz_range: tuple[float, float] | None = (100.0, 800.0)
    """Inclusive (lo, hi) range. ``None`` disables the check."""

    require_inchikey: bool = True
    require_smiles: bool = True
    require_formula: bool = True

    contributors: list[str] | None = None
    """Whitelist over ``metadata['contributor']`` (case-insensitive).
    ``None`` keeps all."""

    identification_levels: list[str] | None = None
    """Reserved for future use — MassBank doesn't expose a uniform
    identification-level field. Kept for API forward-compat."""


# ---------------------------------------------------------------------------
# Streaming filter
# ---------------------------------------------------------------------------


def filter_records(
    records: Iterable[NormalizedRecord],
    criteria: FilterCriteria,
) -> list[NormalizedRecord]:
    """Apply ``criteria`` to a stream of records.

    The input is consumed lazily — pass an iterator to keep memory bounded
    at parse + normalise time. The output is materialised into a list (the
    benchmark sizes ~10⁴ records, fits comfortably).
    """
    kept: list[NormalizedRecord] = []
    n_in = 0
    drop_reasons: dict[str, int] = {}

    mode_set = {m.lower() for m in criteria.ion_mode} if criteria.ion_mode else None
    inst_substrings = (
        [s.lower() for s in criteria.instrument_types]
        if criteria.instrument_types
        else None
    )
    contrib_set = (
        {c.lower() for c in criteria.contributors}
        if criteria.contributors
        else None
    )
    level_set = {x.upper() for x in criteria.ms_level} if criteria.ms_level else None

    for rec in records:
        n_in += 1
        spectrum = rec.spectrum
        gt = rec.ground_truth
        meta = rec.metadata

        if mode_set and spectrum.ionization_mode not in mode_set:
            drop_reasons["ion_mode"] = drop_reasons.get("ion_mode", 0) + 1
            continue
        if criteria.precursor_mz_range is not None:
            lo, hi = criteria.precursor_mz_range
            if not (lo <= spectrum.precursor_mz <= hi):
                drop_reasons["precursor_mz"] = drop_reasons.get("precursor_mz", 0) + 1
                continue
        if len(spectrum.mz) < criteria.min_peaks:
            drop_reasons["min_peaks"] = drop_reasons.get("min_peaks", 0) + 1
            continue
        if criteria.require_smiles and not gt.get("smiles"):
            drop_reasons["smiles"] = drop_reasons.get("smiles", 0) + 1
            continue
        if criteria.require_inchikey and not gt.get("inchikey"):
            drop_reasons["inchikey"] = drop_reasons.get("inchikey", 0) + 1
            continue
        if criteria.require_formula and not gt.get("molecular_formula"):
            drop_reasons["formula"] = drop_reasons.get("formula", 0) + 1
            continue
        if level_set:
            ms_level = (meta.get("ms_level") or "").upper()
            if ms_level not in level_set:
                drop_reasons["ms_level"] = drop_reasons.get("ms_level", 0) + 1
                continue
        if inst_substrings:
            inst = (meta.get("instrument_type") or "").lower()
            if not any(s in inst for s in inst_substrings):
                drop_reasons["instrument_type"] = drop_reasons.get("instrument_type", 0) + 1
                continue
        if contrib_set:
            contrib = (meta.get("contributor") or "").lower()
            if contrib not in contrib_set:
                drop_reasons["contributor"] = drop_reasons.get("contributor", 0) + 1
                continue
        kept.append(rec)

    if drop_reasons:
        logger.info(
            "filter_records: kept %d/%d (drops: %s)",
            len(kept), n_in,
            ", ".join(f"{k}={v}" for k, v in sorted(drop_reasons.items())),
        )
    else:
        logger.info("filter_records: kept %d/%d (no drops)", len(kept), n_in)
    return kept


# ---------------------------------------------------------------------------
# Compound classification
# ---------------------------------------------------------------------------


# ClassyFire taxonomy strings → our 6-label vocabulary. Ordered: first match wins.
_CF_KEYWORD_MAP: list[tuple[str, CompoundClass]] = [
    # Lipids first — many lipids have carboxylic acids inside, but the lipid
    # super-class trumps.
    ("glycerophospholipid", "lipid"),
    ("glycerolipid", "lipid"),
    ("phosphatidyl", "lipid"),
    ("lysophosphatidyl", "lipid"),
    ("lyso", "lipid"),
    ("sphingolipid", "lipid"),
    ("ceramide", "lipid"),
    ("fatty acid ester", "lipid"),
    ("acylcarnitine", "lipid"),
    ("acyl-coa", "lipid"),
    ("fatty acyl", "lipid"),
    # Flavonoids
    ("flavonoid", "flavonoid"),
    ("flavone", "flavonoid"),
    ("flavanone", "flavonoid"),
    ("flavonol", "flavonoid"),
    ("flavan-3-ol", "flavonoid"),
    ("isoflavone", "flavonoid"),
    ("anthocyanid", "flavonoid"),
    # Nucleosides / nucleotides
    ("nucleoside", "nucleoside"),
    ("nucleotide", "nucleoside"),
    ("purine ribonucleotide", "nucleoside"),
    ("pyrimidine ribonucleotide", "nucleoside"),
    # Amino acids and peptides
    ("amino acid", "amino_acid"),
    ("alpha amino acid", "amino_acid"),
    ("α-amino acid", "amino_acid"),
    ("dipeptide", "amino_acid"),
    ("tripeptide", "amino_acid"),
    # Alkaloids
    ("alkaloid", "alkaloid"),
    # Organic acids — checked LAST so flavonoid carboxylic acids etc. don't grab
    ("carboxylic acid", "organic_acid"),
    ("organic acid", "organic_acid"),
    ("dicarboxylic acid", "organic_acid"),
    ("tricarboxylic acid", "organic_acid"),
    ("hydroxy acid", "organic_acid"),
]


def _classify_from_classyfire(smiles: str, inchikey: str | None) -> str | None:
    """Try ClassyFire (with its own cache). Returns class label or ``None``."""
    try:
        from tools.classyfire.schemas import ClassifyStructureRequest
        from tools.classyfire.tool import classify_structure
    except ImportError:
        return None
    try:
        req = ClassifyStructureRequest(smiles=smiles, inchikey=inchikey)
        resp = classify_structure(req)
    except Exception as e:
        logger.debug("ClassyFire failed for %s: %s", inchikey or smiles, e)
        return None

    classifications = " ; ".join(resp.all_classifications).lower()
    for keyword, label in _CF_KEYWORD_MAP:
        if keyword in classifications:
            return label
    # We hit ClassyFire but it doesn't fall in the 6 buckets.
    return "other"


# SMARTS fallback patterns. Compiled once.
_SMARTS_PATTERNS = {
    # Alpha-amino acid: NH2/NH on C alpha to a carboxylic acid
    "amino_acid": Chem.MolFromSmarts("[NX3;H2,H1;!$(NC=O)][CX4][CX3](=O)[OX2H,OX1H0-]"),
    # Carboxylic acid (free, not amide)
    "organic_acid": Chem.MolFromSmarts("[CX3](=O)[OX2H1]"),
    # Flavone-ish C6-C3-C6 with a 2-aryl-1-benzopyran-4-one core.
    "flavonoid": Chem.MolFromSmarts("O=c1cc(-[c]2ccccc2)oc2ccccc12"),
    # Glycerophospholipid: glycerol-3-phosphate backbone
    "lipid_gpl": Chem.MolFromSmarts("OCC(O)COP(=O)(O)O"),
    # Long-chain (>=12 C in a chain) ester / acid → lipid heuristic
    "lipid_chain": Chem.MolFromSmarts("CCCCCCCCCCCCC"),  # 13 C chain
    # Purine ring
    "purine": Chem.MolFromSmarts("c1nc2[nH]cnc2cn1"),
    # Pyrimidine ring (uracil / cytosine / thymine cores)
    "pyrimidine": Chem.MolFromSmarts("c1cnc(=O)nc1"),
    # Furanose / pyranose ring with multiple OHs (sugar-ish)
    "sugar_ring": Chem.MolFromSmarts("[OX2H]C[CH]1O[CH][CH][CH]1[OX2H]"),
}


def _classify_from_smarts(smiles: str) -> CompoundClass:
    """SMARTS-only classifier, used when ClassyFire is unavailable."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return "other"

    # Lipid checks first (long chain + GPL backbone, OR very long chain alone)
    if _SMARTS_PATTERNS["lipid_gpl"] and mol.HasSubstructMatch(_SMARTS_PATTERNS["lipid_gpl"]):
        return "lipid"
    if _SMARTS_PATTERNS["lipid_chain"] and mol.HasSubstructMatch(_SMARTS_PATTERNS["lipid_chain"]):
        # Need it to also have an acyl/ester linker to count as lipid
        if mol.HasSubstructMatch(Chem.MolFromSmarts("C(=O)O")):
            return "lipid"

    # Nucleoside: purine or pyrimidine ring + sugar ring
    has_base = (
        (_SMARTS_PATTERNS["purine"] and mol.HasSubstructMatch(_SMARTS_PATTERNS["purine"]))
        or (_SMARTS_PATTERNS["pyrimidine"] and mol.HasSubstructMatch(_SMARTS_PATTERNS["pyrimidine"]))
    )
    has_sugar = bool(
        _SMARTS_PATTERNS["sugar_ring"] and mol.HasSubstructMatch(_SMARTS_PATTERNS["sugar_ring"])
    )
    if has_base and has_sugar:
        return "nucleoside"

    # Flavonoid (chromone core with 2-aryl)
    if _SMARTS_PATTERNS["flavonoid"] and mol.HasSubstructMatch(_SMARTS_PATTERNS["flavonoid"]):
        return "flavonoid"

    # Amino acid (alpha-amino acid pattern)
    if _SMARTS_PATTERNS["amino_acid"] and mol.HasSubstructMatch(_SMARTS_PATTERNS["amino_acid"]):
        return "amino_acid"

    # Organic acid
    if _SMARTS_PATTERNS["organic_acid"] and mol.HasSubstructMatch(_SMARTS_PATTERNS["organic_acid"]):
        return "organic_acid"

    return "other"


def classify_compound(
    smiles: str,
    inchikey: str | None = None,
    *,
    use_classyfire: bool = True,
) -> str | None:
    """Assign a compound to one of the six benchmark classes (or ``"other"``).

    Priority:

    1. ClassyFire taxonomy (cached via ``tools.classyfire``). The
       taxonomy strings are mapped via :data:`_CF_KEYWORD_MAP`.
    2. SMARTS fallback when ClassyFire is unreachable or the smiles cannot
       resolve to an InChIKey.

    Returns ``None`` only when the input SMILES is itself unparseable;
    otherwise returns one of the seven labels (six classes + ``"other"``).
    """
    if not smiles:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    if use_classyfire:
        label = _classify_from_classyfire(smiles, inchikey)
        if label is not None:
            return label
        logger.debug("ClassyFire returned no class; falling back to SMARTS")

    return _classify_from_smarts(smiles)


# ---------------------------------------------------------------------------
# CompoundPool
# ---------------------------------------------------------------------------


@dataclass
class CompoundPool:
    """A queryable collection of normalized + classified records.

    Each record's ``ground_truth`` carries a ``compound_class`` field after
    :func:`build_compound_pool` runs — but :class:`CompoundPool` does not
    require it. If the field is missing (e.g. classification disabled),
    :meth:`by_class` simply returns nothing for the missing class.
    """

    records: list[NormalizedRecord] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.records)

    def by_class(self, class_name: str) -> list[NormalizedRecord]:
        """All records whose ``ground_truth['compound_class']`` matches."""
        return [
            r for r in self.records
            if r.ground_truth.get("compound_class") == class_name
        ]

    def by_mode(self, mode: str) -> list[NormalizedRecord]:
        return [r for r in self.records if r.spectrum.ionization_mode == mode]

    def stats(self) -> dict[str, Any]:
        """Cross-tab counts for quick inspection.

        Returns::

            {
              "total": N,
              "by_mode":   {"positive": X, "negative": Y},
              "by_class":  {"amino_acid": A, ..., "other": Z, "<unknown>": K},
              "by_instrument": {"LC-ESI-Q-TOF": ..., ...},
              "by_contributor": {"RIKEN": ..., "EAWAG": ...},
              "by_mode_class": {"positive|amino_acid": ..., ...},
            }

        The mode/class cross-tab keys are stringified ``"mode|class"`` so the
        result round-trips through JSON.
        """
        out: dict[str, Any] = {
            "total": len(self.records),
            "by_mode": {},
            "by_class": {},
            "by_instrument": {},
            "by_contributor": {},
            "by_mode_class": {},
        }
        for r in self.records:
            mode = r.spectrum.ionization_mode
            klass = r.ground_truth.get("compound_class") or "<unknown>"
            inst = r.metadata.get("instrument_type") or "<unknown>"
            contrib = r.metadata.get("contributor") or "<unknown>"
            out["by_mode"][mode] = out["by_mode"].get(mode, 0) + 1
            out["by_class"][klass] = out["by_class"].get(klass, 0) + 1
            out["by_instrument"][inst] = out["by_instrument"].get(inst, 0) + 1
            out["by_contributor"][contrib] = out["by_contributor"].get(contrib, 0) + 1
            key = f"{mode}|{klass}"
            out["by_mode_class"][key] = out["by_mode_class"].get(key, 0) + 1
        return out

    # -- I/O ---------------------------------------------------------------

    def save(self, path: Path | str) -> None:
        """Serialise the pool to JSON-Lines.

        One record per line:

        .. code-block:: json

            {
              "spectrum": {...Pydantic-dumped Spectrum...},
              "ground_truth": {...},
              "metadata": {...},
              "normalization_warnings": [...]
            }

        The schema is documented at ``data/processed/SCHEMA.md`` (created
        by :mod:`scripts.build_compound_pool`).
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with p.open("w", encoding="utf-8") as f:
                for rec in self.records:
                    f.write(json.dumps(_record_to_jsonable(rec), ensure_ascii=False))
                    f.write("\n")
        except OSError as e:
            raise CompoundPoolIOError(f"failed to write {p}: {e}") from e

    @classmethod
    def load(cls, path: Path | str) -> "CompoundPool":
        p = Path(path)
        try:
            with p.open("r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as e:
            raise CompoundPoolIOError(f"failed to read {p}: {e}") from e
        records: list[NormalizedRecord] = []
        for i, line in enumerate(lines, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                blob = json.loads(s)
                records.append(_record_from_jsonable(blob))
            except Exception as e:
                raise CompoundPoolIOError(
                    f"{p}:{i} failed to parse: {e}"
                ) from e
        return cls(records=records)


def _record_to_jsonable(rec: NormalizedRecord) -> dict[str, Any]:
    spec = rec.spectrum.model_dump()
    return {
        "spectrum": spec,
        "ground_truth": rec.ground_truth,
        "metadata": rec.metadata,
        "normalization_warnings": list(rec.normalization_warnings),
    }


def _record_from_jsonable(blob: dict[str, Any]) -> NormalizedRecord:
    spec = Spectrum.model_validate(blob["spectrum"])
    return NormalizedRecord(
        spectrum=spec,
        ground_truth=dict(blob.get("ground_truth", {})),
        metadata=dict(blob.get("metadata", {})),
        normalization_warnings=list(blob.get("normalization_warnings", [])),
    )


# ---------------------------------------------------------------------------
# build_compound_pool
# ---------------------------------------------------------------------------


def build_compound_pool(
    records: Iterable[NormalizedRecord],
    classify: bool = True,
    use_classyfire: bool = True,
) -> CompoundPool:
    """Materialise a list of records into a :class:`CompoundPool`.

    If ``classify`` is True, each record's ``ground_truth['compound_class']``
    is populated. Set ``use_classyfire=False`` to skip the network and use
    only the SMARTS fallback (useful for offline tests / CI).

    Records that fail classification entirely (unparseable SMILES) end up
    with ``compound_class=None`` so :meth:`CompoundPool.stats` reports them
    under ``"<unknown>"``.
    """
    materialised: list[NormalizedRecord] = list(records)
    if classify:
        n_classified = 0
        n_failed = 0
        for rec in materialised:
            smiles = rec.ground_truth.get("smiles")
            inchikey = rec.ground_truth.get("inchikey")
            label = classify_compound(smiles, inchikey, use_classyfire=use_classyfire)
            rec.ground_truth["compound_class"] = label
            if label is None:
                n_failed += 1
                rec.normalization_warnings.append("compound_class: classification failed")
            else:
                n_classified += 1
        logger.info(
            "build_compound_pool: classified %d, failed %d (out of %d)",
            n_classified, n_failed, len(materialised),
        )
    return CompoundPool(records=materialised)


# ---------------------------------------------------------------------------
# Convenience: stream-friendly filter+pool
# ---------------------------------------------------------------------------


def filter_and_pool(
    records: Iterable[NormalizedRecord],
    criteria: FilterCriteria,
    classify: bool = True,
    use_classyfire: bool = True,
) -> CompoundPool:
    """Compose :func:`filter_records` and :func:`build_compound_pool`."""
    filtered = filter_records(records, criteria)
    return build_compound_pool(filtered, classify=classify, use_classyfire=use_classyfire)
