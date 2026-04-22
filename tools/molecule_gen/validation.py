"""RDKit-backed validation and scoring helpers for molecule_generate.

All RDKit imports are lazy so importing the package does not require rdkit to
be installed (useful for Dockerfile layering and for tests that inject mocks
without touching the real pipeline).
"""
from __future__ import annotations

import math
import re
from typing import Iterable


_ELEMENT_RE = re.compile(r"([A-Z][a-z]?)(\d*)")


def parse_formula(formula: str) -> dict[str, int]:
    """Parse a Hill-style molecular formula into an element-count dict.

    Ignores isotope markers and charge suffixes; tolerates "C6H12O6" and
    "C6H12O6+". Unknown element tokens are dropped silently (the generator
    rarely emits them).
    """
    formula = re.sub(r"[+\-].*$", "", formula.strip())
    counts: dict[str, int] = {}
    for elem, n in _ELEMENT_RE.findall(formula):
        if not elem:
            continue
        counts[elem] = counts.get(elem, 0) + (int(n) if n else 1)
    return counts


def formulas_equal(a: str, b: str) -> bool:
    return parse_formula(a) == parse_formula(b)


def formula_diff(a: str, b: str) -> int:
    """Absolute element-count distance between two formulas."""
    ac, bc = parse_formula(a), parse_formula(b)
    keys = set(ac) | set(bc)
    return sum(abs(ac.get(k, 0) - bc.get(k, 0)) for k in keys)


def validate_and_canonicalize(smiles: str) -> tuple[str, str, float] | None:
    """Parse SMILES with RDKit, return (canonical_smiles, hill_formula, mw).

    Returns None if RDKit cannot parse or sanitize.
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    if not smiles:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles, sanitize=True)
    except Exception:
        return None
    if mol is None:
        return None
    try:
        canon = Chem.MolToSmiles(mol)
        form = rdMolDescriptors.CalcMolFormula(mol)
        mw = float(Descriptors.MolWt(mol))
    except Exception:
        return None
    return canon, form, mw


def normalize_logprobs(seq_log_probs: Iterable[float]) -> list[float]:
    """Map a batch of sequence log-probabilities into [0, 1] by min-max.

    A single-item batch maps to [1.0]. All-equal inputs map to all-ones (no
    differentiation possible). Designed to be numerically safe for the
    very-small and very-negative logprobs that beam search emits.
    """
    xs = [float(x) for x in seq_log_probs]
    if not xs:
        return []
    if len(xs) == 1:
        return [1.0]
    lo, hi = min(xs), max(xs)
    if not math.isfinite(lo) or not math.isfinite(hi) or hi - lo < 1e-9:
        return [1.0] * len(xs)
    return [(x - lo) / (hi - lo) for x in xs]


def combine_score(
    logprob_norm: float,
    formula_mismatch: int,
    max_mismatch: int,
    in_pool: bool,
) -> float:
    """Combine log-prob norm, formula closeness, and pool membership into [0, 1].

    Per maintainer decision:
      score = 0.5 * logprob_norm + 0.5 * (1 - mismatch / max_mismatch) + 0.1 * in_pool
      clamp to [0, 1].
    """
    if max_mismatch <= 0:
        formula_term = 1.0
    else:
        formula_term = max(0.0, 1.0 - formula_mismatch / max_mismatch)
    raw = 0.5 * logprob_norm + 0.5 * formula_term + (0.1 if in_pool else 0.0)
    return max(0.0, min(1.0, raw))
