"""Heuristic compound-pair extraction from upstream/downstream claim text.

Pulled out of scripts/kegg/extract_required_pathways.py so Layer 6d can
use the same extraction logic at verification time. Both the script
(audit / pre-population pass) and the layer (runtime) call this single
function — no duplicated regex.

The heuristic is deliberately tight: it looks for a well-known
relationship keyword and isolates the (subject, object) text on either
side, trimming common subordinate-clause tails. It does NOT resolve
the endpoints to KEGG IDs — that's ``resolve_compound_to_kegg``'s job.

When the heuristic can't isolate two endpoints, returns (None, None);
the caller decides whether to fall back to pathway-pair extraction or
return UNVERIFIABLE_V0.
"""
from __future__ import annotations

import re

# Keywords ordered most → least specific so "is upstream of" beats
# bare "upstream of" when both could match. The bare prepositional
# forms cover natural-language paraphrases the typed forms miss.
_RELATIONSHIP_KEYWORDS: tuple[str, ...] = (
    "is upstream of",
    "are upstream of",
    "is downstream of",
    "are downstream of",
    "feeds into",
    "feed into",
    "feeding into",
    "fed into",
    "downstream product of",
    "upstream product of",
    "feeds the",
    "feeds back",
    "downstream of",
    "upstream of",
)

_TRIM_TAIL_RE = re.compile(
    r"\s+(?:in|via|within|through|of\s+the)\s+",
    flags=re.IGNORECASE,
)


def extract_compound_pair(claim_text: str) -> tuple[str | None, str | None]:
    """Return ``(subject_phrase, object_phrase)`` or ``(None, None)``.

    Subject is the text to the LEFT of the relationship keyword; object
    is the text to the RIGHT, trimmed at the first comma / period or
    "in <pathway>" prepositional clause so the object isn't the rest
    of the sentence. Both sides are stripped of surrounding punctuation
    and whitespace; no further normalisation here (resolution is the
    caller's responsibility).
    """
    txt = re.sub(r"\s+", " ", claim_text.strip())
    txt_lc = txt.lower()
    for kw in _RELATIONSHIP_KEYWORDS:
        idx = txt_lc.find(kw)
        if idx == -1:
            continue
        left = txt[:idx].strip(" ,.;:")
        right = txt[idx + len(kw):].strip(" ,.;:")
        right = _TRIM_TAIL_RE.split(right, maxsplit=1)[0]
        right = re.split(r"[,.;]", right, maxsplit=1)[0].strip()
        if left and right:
            return left.strip(), right.strip()
    return None, None
