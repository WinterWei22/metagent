"""Pathway-name and driver-compound extraction from LLM narratives.

Strategy is deliberately regex-first:

* ``extract_pathway_mentions`` — captures ``<X> (pathway|metabolism|cycle|
  biosynthesis|catabolism|degradation|signalling)`` plus a small list of
  canonical names appearing in the eval guide top_pathways. Uppercases
  preserved as-given for downstream substring matching.
* ``extract_driver_mentions`` — for each compound name in the curated
  pool, scan the narrative for any mention; mark as a *claimed driver*
  only when the mention sits in the same sentence as a driver marker
  ("key driver", "primary driver", "drives", "responsible for", etc.).

Both functions return de-duplicated lists. Order is the order of first
appearance in the narrative, which matters for "top-1" pathway scoring.

A second-stage LLM-based extractor was considered (eval guide deliverable
4 mentions one as backup); intentionally **not** added in the baseline so
the pipeline does not double-charge LLM calls. If recall on these regexes
is below 90% on the dry run, swap to the LLM extractor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Words that can follow a pathway name. The capture group ((?:[A-Z][\w-]*\s+)
# {0,4}[A-Z][\w-]*) accepts 1-5 capitalised tokens, hyphens allowed.
_PATHWAY_RE = re.compile(
    r"\b((?:[A-Z][\w'-]+\s+){0,4}[A-Za-z0-9'-]+)\s+"
    r"(pathway|metabolism|biosynthesis|catabolism|degradation|"
    r"cycle|signalling|signaling|shunt)\b"
)

# Heads that look like pathway names but are really evaluative adjectives
# / determiners / generic nouns. The 'urea cycle' / 'tca cycle' style names
# are real pathways with lowercase heads, so we cannot drop all lowercase
# heads — instead we drop a small explicit stop-list.
_HEAD_STOPLIST = frozenset(
    {
        "the",
        "this",
        "these",
        "those",
        "an",
        "a",
        "any",
        "dominant",
        "major",
        "main",
        "key",
        "primary",
        "central",
        "important",
        "critical",
        "relevant",
        "affected",
        "implicated",
        "active",
        "metabolic",
        "biological",
        "underlying",
        "common",
        "candidate",
        "global",
        "specific",
        "general",
        "associated",
        "given",
        "listed",
        "mentioned",
        "related",
        "various",
        "multiple",
        "several",
        "other",
        "additional",
        "further",
        "alternative",
        "unrelated",
        "broader",
        "broad",
        "single",
        "shared",
        "their",
        "its",
        "such",
        "including",
        "involving",
        "involved",
    }
)

_DRIVER_MARKERS = (
    "key driver",
    "key drivers",
    "primary driver",
    "primary drivers",
    "main driver",
    "main drivers",
    "drives",
    "drive",
    "driving",
    "responsible for",
    "central to",
    "central role",
    "central player",
    "are drivers",
    "is a driver",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NORM_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class PathwayMention:
    text: str  # what the regex captured ("Tyrosine metabolism")
    canonical: str  # lowercase + collapsed-whitespace form, for matching


def _canonicalise(s: str) -> str:
    return _NORM_SPACES.sub(" ", s.lower()).strip()


def extract_pathway_mentions(
    narrative: str,
    known_pathway_names: list[str] | None = None,
) -> list[PathwayMention]:
    """Return pathway names mentioned in the narrative (first-occurrence order).

    Two extractors run, then results are merged and sorted by character
    offset so the *first* mention reflects what the LLM led with:

    1. **Generic pattern** — ``<Capitalised tokens> (pathway|metabolism|
       biosynthesis|catabolism|cycle|...)``. Heads in ``_HEAD_STOPLIST``
       are rejected to avoid "dominant pathway" / "the metabolism" noise.
    2. **Known-name pattern** — direct substring match against any of
       ``known_pathway_names`` (typically the task's ``top_pathways[*]
       .pathway_name``). Catches single-token disease pathways like
       ``Alkaptonuria`` that the generic pattern cannot.
    """
    found: list[tuple[int, PathwayMention]] = []  # (offset, mention)
    seen: set[str] = set()

    # --- generic pattern ------------------------------------------------
    for m in _PATHWAY_RE.finditer(narrative):
        head, kind = m.group(1).strip(), m.group(2).strip()
        head_tokens = head.split()
        if len(head_tokens) == 1 and head_tokens[0].lower() in _HEAD_STOPLIST:
            continue
        text = f"{head} {kind}"
        canon = _canonicalise(text)
        if canon in seen:
            continue
        seen.add(canon)
        found.append((m.start(), PathwayMention(text=text, canonical=canon)))

    # --- known-name pattern ---------------------------------------------
    if known_pathway_names:
        # Sort longest-first so 'Tyrosine metabolism' wins over 'Tyrosine'.
        for name in sorted(set(known_pathway_names), key=len, reverse=True):
            if not name:
                continue
            canon = _canonicalise(name)
            if canon in seen:
                continue
            pat = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
            m = pat.search(narrative)
            if m is None:
                continue
            seen.add(canon)
            found.append((m.start(), PathwayMention(text=name, canonical=canon)))

    found.sort(key=lambda p: p[0])
    return [pm for _, pm in found]


def extract_driver_mentions(
    narrative: str,
    candidate_names: list[str],
) -> list[str]:
    """Return canonical compound names cited as drivers in the narrative.

    A name is a "claimed driver" when it appears in the same sentence as
    one of the driver markers above. We use sentence-level co-occurrence
    rather than fixed-window scanning because driver-statements typically
    reference 2-4 compounds in a single clause.
    """
    if not candidate_names:
        return []

    # Pre-build name regex (escape, lowercase, word-boundary). Names are
    # matched case-insensitively; we still report the original casing.
    name_lookup: dict[str, str] = {n.lower(): n for n in candidate_names}
    # Sort by length desc so 'L-Tyrosine' wins over 'Tyrosine' on overlap.
    sorted_keys = sorted(name_lookup.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in sorted_keys) + r")\b",
        re.IGNORECASE,
    )

    sentences = _SENTENCE_SPLIT.split(narrative)
    seen: set[str] = set()
    out: list[str] = []
    for sent in sentences:
        sent_low = sent.lower()
        if not any(marker in sent_low for marker in _DRIVER_MARKERS):
            continue
        for m in pattern.finditer(sent):
            canonical = name_lookup[m.group(1).lower()]
            if canonical in seen:
                continue
            seen.add(canonical)
            out.append(canonical)
    return out


def extract_compound_mentions(
    narrative: str,
    candidate_names: list[str],
) -> list[str]:
    """All compound mentions, regardless of driver-marker context.

    Used for diagnostics / sanity checks (e.g. "did the LLM mention any
    of the input compounds at all?"). Not a metric input.
    """
    if not candidate_names:
        return []
    name_lookup: dict[str, str] = {n.lower(): n for n in candidate_names}
    sorted_keys = sorted(name_lookup.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in sorted_keys) + r")\b",
        re.IGNORECASE,
    )
    seen: set[str] = set()
    out: list[str] = []
    for m in pattern.finditer(narrative):
        canonical = name_lookup[m.group(1).lower()]
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out
