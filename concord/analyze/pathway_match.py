"""Pathway-name fuzzy matching for W6 Gate-2 evaluation.

Cooke ground-truth pathway IDs live in the ``HUMAN1:`` / ``RECON2:``
namespaces, while the five enrichment methods emit `REACT:` / `KEGG:`
/ `WP:` / `SMPDB:` / `MUMM:`. There is no canonical KEGG/Reactome
cross-walk for the Cooke perturbation labels (W6 D1.1 left this as an
explicit D4 task), so we match by pathway *name* with a tokenised-set
Jaccard against a small stop-word list.

The match is conservative on purpose: false positives in the GT match
inflate baseline hit rate and would mask any cross-paradigm lift in
Metric 1 / Metric 2.
"""
from __future__ import annotations
import re

STOPWORDS = frozenset({
    "metabolism", "pathway", "pathways", "biosynthesis", "synthesis",
    "of", "and", "the", "a", "an", "in", "to", "or", "by", "via", "from",
    "homo", "sapiens", "human", "hsa", "cell", "molecule", "molecules",
    "system", "process", "general", "other",
})


def _tokenize(name: str) -> set[str]:
    name = name.lower()
    name = re.sub(r"\([^)]*\)", " ", name)  # drop parentheticals
    tokens = re.findall(r"[a-z][a-z0-9'-]*", name)
    tokens = [t for t in tokens if len(t) >= 4 and t not in STOPWORDS]
    return set(tokens)


def pathway_name_overlap(gt_name: str, candidate_name: str,
                          threshold: float = 0.5) -> bool:
    """True if Jaccard of content tokens ≥ threshold.

    Conservative default 0.5 — requires that ≥ 50 % of the *union* of
    content words match. Tested on the Cooke pathway set: catches
    "Arachidonic acid metabolism" ↔ "Arachidonic acid metabolism" (1.0),
    rejects "Arachidonic acid metabolism" ↔ "Lipid metabolism" (0).
    """
    gt = _tokenize(gt_name)
    ca = _tokenize(candidate_name)
    if not gt or not ca:
        return False
    inter = len(gt & ca)
    union = len(gt | ca)
    if union == 0:
        return False
    return inter / union >= threshold


def best_matching_rank(gt_name: str, top_pathway_names: list[str],
                        threshold: float = 0.5) -> int | None:
    """Return 0-indexed rank of first pathway with name-overlap ≥ threshold.

    Returns None if no overlap in the top-N list.
    """
    for rank, name in enumerate(top_pathway_names):
        if pathway_name_overlap(gt_name, name, threshold=threshold):
            return rank
    return None
