"""Token-Jaccard fuzzy matching for verifier layers.

W12 C7 sprint: copied verbatim from ``concord/analyze/pathway_match.py``
into verifier-namespace so verifier layers can depend on it without an
upstream concord/ import (verifier/ → concord/ would invert the
dependency graph that exists in the post-merge metagent-v2 tree, where
``concord/`` already imports verifier helpers).

Same stop-word list + tokeniser as the Concord W6 / W9 implementation
so set_enrichment + future C3 / C1+C2 sprints share one source of truth
for "what counts as a content token". The 0.5 Jaccard threshold is the
Concord W6 default (conservative — requires ≥ 50 % token overlap on
the union); set_enrichment.py is free to pick a different threshold
per call site.
"""
from __future__ import annotations

import re


# Content-word filter. Drops the same set of generic biology tokens
# concord/analyze/pathway_match.py drops, so the two implementations
# never disagree on what's a "real" token.
STOPWORDS: frozenset[str] = frozenset({
    "metabolism", "pathway", "pathways", "biosynthesis", "synthesis",
    "of", "and", "the", "a", "an", "in", "to", "or", "by", "via", "from",
    "homo", "sapiens", "human", "hsa", "cell", "molecule", "molecules",
    "system", "process", "general", "other",
})


def _tokenize(name: str) -> set[str]:
    """Lowercase, strip parentheticals, keep tokens ≥ 4 chars not in STOPWORDS."""
    name = name.lower()
    name = re.sub(r"\([^)]*\)", " ", name)  # drop parentheticals
    tokens = re.findall(r"[a-z][a-z0-9'-]*", name)
    return {t for t in tokens if len(t) >= 4 and t not in STOPWORDS}


def token_jaccard(a: str, b: str) -> float:
    """Return the Jaccard similarity of content tokens of two strings.

    Returns 0.0 if either side has no content tokens after stop-word
    stripping (e.g. names made entirely of generic words like
    "Metabolism pathway").
    """
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    union = len(ta | tb)
    if union == 0:
        return 0.0
    return len(ta & tb) / union


def pathway_name_overlap(
    gt_name: str, candidate_name: str, threshold: float = 0.5
) -> bool:
    """True if Jaccard of content tokens ≥ threshold.

    Conservative default 0.5 (Concord W6 default — see
    concord/analyze/pathway_match.py docstring for the empirical
    calibration on the Cooke perturbation labels)."""
    return token_jaccard(gt_name, candidate_name) >= threshold
