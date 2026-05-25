"""Subject name normalisation for `verifier.layers.factual_sub6` lookup.

W13.A — bridges surface form drift between LLM-written claim subject
strings and task `differential_metabolites` names. Examples:

  '17β-estradiol' → '17beta-estradiol'   (Greek-letter → Roman)
  'D-glucose'  vs  'D glucose'           (hyphen ↔ whitespace)
  'L-Tyrosine' vs 'l-tyrosine'           (case)

Pure helper. No I/O, no LLM call. Used by `factual_sub6._find_by_subject`
as a fallback when the case-insensitive exact-name match fails.
"""
from __future__ import annotations

import re
import unicodedata


# Greek letter → Roman name. Covers the symbols ConcordMet narratives
# typically emit when describing metabolites
# (steroid β/α positions, lipid ω numbering, polyene δ-γ-prefixes, etc.).
_GREEK_MAP: dict[str, str] = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "ο": "omicron", "π": "pi",
    "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon",
    "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    # Uppercase forms (rare but seen in some pasted text)
    "Α": "alpha", "Β": "beta", "Γ": "gamma", "Δ": "delta",
    "Ω": "omega",
}


def normalize_subject_name(name: str | None) -> str:
    """Return a normalised form of a metabolite subject name.

    Steps:
      1. NFKD decompose Unicode (drops combining accents).
      2. Replace Greek letters with their Roman names.
      3. Lowercase + strip + collapse all whitespace runs into a single '-'.
      4. Collapse any '-' run into a single '-'.

    Empty / None input returns empty string. Idempotent — calling twice
    returns the same value.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    # Drop combining marks (accents, diacritics)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    for gr, roman in _GREEK_MAP.items():
        s = s.replace(gr, roman)
    s = s.strip().lower()
    # Whitespace → '-' so "D glucose" matches "D-glucose"
    s = re.sub(r"\s+", "-", s)
    # Collapse repeated '-' into single '-'
    s = re.sub(r"-+", "-", s)
    return s
