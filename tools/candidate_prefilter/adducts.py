"""Adduct-to-neutral-mass conversion for candidate_prefilter.

A small hard-coded table of common electrospray adducts. For each adduct we
record how the observed m/z relates to the neutral exact mass M:

    m/z = (multiplier * M + mass_shift) / charge

    =>  M = (m/z * charge - mass_shift) / multiplier

`multiplier` handles dimers/trimers; `charge` is the absolute value of the
ion's charge; `mass_shift` is a signed mass difference in Daltons (positive =
atoms gained, negative = atoms lost).

Mass constants follow NIST / Fiehn-Lab conventions. Reference table:
    https://fiehnlab.ucdavis.edu/staff/kind/metabolomics/ms-adduct-calculator/

Electron mass is accounted for: the mass of the H+ proton (1.007276) differs
from the neutral H atom (1.007825) by one electron rest mass. We use proton
mass for charged adducts (positive-ion additions, negative-ion subtractions).
"""
from __future__ import annotations

from dataclasses import dataclass

from tools.candidate_prefilter.errors import InvalidAdductError


# Atomic / particle constants (monoisotopic, Daltons).
_PROTON = 1.007276
_ELECTRON = 0.000549
_H = 1.007825
_NA = 22.989770
_K = 38.963708
_N = 14.003074
_C = 12.000000
_O = 15.994915


# Derived ion masses (charged species, electron mass accounted for).
_NA_ION = _NA - _ELECTRON          # 22.989221
_K_ION = _K - _ELECTRON            # 38.963159
_NH4_ION = _N + 4 * _H - _ELECTRON # 18.033823
_FORMATE = _H + _C + 2 * _O        # 45.002740 (HCOO, neutral)
_ACETATE = 2 * _C + 3 * _H + 2 * _O  # 59.018390 (CH3COO, neutral)


@dataclass(frozen=True)
class AdductRule:
    """How to back-calculate neutral M from observed m/z for one adduct.

    M = (m/z * charge - mass_shift) / multiplier
    """

    multiplier: int       # how many copies of M are in the ion (1 = monomer, 2 = dimer)
    mass_shift: float     # signed Da added to (multiplier * M) to get ion mass
    charge: int           # absolute charge of the ion (positive integer)
    polarity: str         # "positive" | "negative" — informational only

    def neutral_mass(self, mz: float) -> float:
        return (mz * self.charge - self.mass_shift) / self.multiplier


# Bracket-normalised keys only — callers must pass a normalised adduct string
# (e.g. "[M+H]+", not "M+H"). common.gnps_loader._normalise_adduct already
# normalises library entries to this form.
_ADDUCT_TABLE: dict[str, AdductRule] = {
    # --- positive mode, required six ---
    "[M+H]+":     AdductRule(multiplier=1, mass_shift=+_PROTON,           charge=1, polarity="positive"),
    "[M+Na]+":    AdductRule(multiplier=1, mass_shift=+_NA_ION,           charge=1, polarity="positive"),
    "[M+K]+":     AdductRule(multiplier=1, mass_shift=+_K_ION,            charge=1, polarity="positive"),
    "[M+NH4]+":   AdductRule(multiplier=1, mass_shift=+_NH4_ION,          charge=1, polarity="positive"),
    # --- negative mode, required ---
    "[M-H]-":     AdductRule(multiplier=1, mass_shift=-_PROTON,           charge=1, polarity="negative"),
    "[M+FA-H]-":  AdductRule(multiplier=1, mass_shift=+_FORMATE - _PROTON, charge=1, polarity="negative"),
    # --- common extras (cheap to include; not exhaustive) ---
    "[M+H-H2O]+": AdductRule(multiplier=1, mass_shift=+_PROTON - (2 * _H + _O), charge=1, polarity="positive"),
    "[M+2H]2+":   AdductRule(multiplier=1, mass_shift=+2 * _PROTON,       charge=2, polarity="positive"),
    "[2M+H]+":    AdductRule(multiplier=2, mass_shift=+_PROTON,           charge=1, polarity="positive"),
    "[2M+Na]+":   AdductRule(multiplier=2, mass_shift=+_NA_ION,           charge=1, polarity="positive"),
    "[M+Cl]-":    AdductRule(multiplier=1, mass_shift=+34.969402,         charge=1, polarity="negative"),  # Cl- ion
    "[M+AcO-H]-": AdductRule(multiplier=1, mass_shift=+_ACETATE - _PROTON, charge=1, polarity="negative"),
    "[2M-H]-":    AdductRule(multiplier=2, mass_shift=-_PROTON,           charge=1, polarity="negative"),
}


def supported_adducts() -> list[str]:
    """Return the list of bracket-normalised adduct strings this tool accepts."""
    return sorted(_ADDUCT_TABLE.keys())


def neutral_mass_from_precursor(precursor_mz: float, adduct: str) -> float:
    """Back-calculate the neutral exact mass M from an observed precursor m/z.

    Raises:
        InvalidAdductError: if `adduct` is not in the supported table.
    """
    if adduct not in _ADDUCT_TABLE:
        raise InvalidAdductError(
            f"Unsupported adduct {adduct!r}. Supported adducts: "
            f"{', '.join(supported_adducts())}."
        )
    rule = _ADDUCT_TABLE[adduct]
    return rule.neutral_mass(precursor_mz)
