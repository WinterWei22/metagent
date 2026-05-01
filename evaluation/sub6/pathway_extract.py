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

# Words that can follow a pathway name. The capture group accepts 1-5
# capitalised tokens then any-case final token, hyphens allowed.
# Whitespace is restricted to **horizontal** ([ \t]) so the regex never
# spans newlines — prior version used \s+ and ate "## Affected Metabolic
# Pathways\n\nThe dominant pathway" as one (multi-line) match.
_PATHWAY_RE = re.compile(
    r"\b((?:[A-Z][\w'-]+[ \t]+){0,4}[A-Za-z0-9'-]+)[ \t]+"
    r"(pathway|metabolism|biosynthesis|catabolism|degradation|"
    r"cycle|signalling|signaling|shunt)\b"
)

# Tokens that strip from a pathway-name candidate before checking whether
# any meaningful content remains. Mirrors metrics.py — kept here so the
# extractor can pre-filter mentions that contribute zero biological content
# (e.g. "Metabolism", "biosynthetic pathway"). Kept in sync manually; the
# constants in metrics.py are the source of truth.
_PATHWAY_SUFFIX_FOR_CONTENT = frozenset(
    {
        "pathway",
        "pathways",
        "metabolism",
        "catabolism",
        "anabolism",
        "biosynthesis",
        "degradation",
        "cycle",
        "signalling",
        "signaling",
        "shunt",
        "fate",
    }
)
_GENERIC_STOP_TOKENS = frozenset(
    {
        "a", "an", "and", "the", "of", "in", "for", "on", "or", "to", "by",
        # Generic adjectives often mis-captured as multi-token "heads".
        "biosynthetic", "metabolic", "metabolism", "general", "broad",
        "specific", "common", "central", "primary", "main", "key",
        "dominant", "major", "important", "critical", "relevant",
        "affected", "implicated", "active", "underlying", "candidate",
        "global", "associated", "given", "listed", "mentioned", "related",
        "various", "multiple", "several", "other", "additional", "further",
        "alternative", "unrelated", "broader", "single", "shared",
        "their", "its", "such", "including", "involving", "involved",
        "this", "these", "those", "any", "prominent", "coherent",
    }
)
_TOKEN_RE_LOCAL = re.compile(r"[A-Za-z0-9]+")


def _has_meaningful_content(text: str) -> bool:
    """True iff at least one content token survives suffix+stop stripping.

    Used to drop pathway mentions like "Metabolism" / "biosynthetic
    pathway" / "the metabolism" — they pass the regex but carry no
    biological identity.
    """
    toks = {t.lower() for t in _TOKEN_RE_LOCAL.findall(text)}
    return bool(toks - _PATHWAY_SUFFIX_FOR_CONTENT - _GENERIC_STOP_TOKENS)


# Markdown stripping. Headers (#+ leading), emphasis (**...**, *...*) and
# inline code spans are converted to plain text so the regex doesn't catch
# the markup glyphs as a "head".
_MD_HEADER_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_MD_CODE_RE = re.compile(r"`([^`\n]+)`")


def _strip_markdown(text: str) -> str:
    text = _MD_HEADER_RE.sub("", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    return text

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
# Word-boundary regex for markers — avoids 'drive' substring matching inside
# 'driver section' / 'overdrive' / etc. Build once at import time.
_DRIVER_MARKER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in _DRIVER_MARKERS) + r")\b",
    re.IGNORECASE,
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
    # Strip markdown so heading prefixes / **bold** glyphs don't get
    # captured as part of a pathway head. Length-preserving where it
    # matters (offsets shift, but we only use ordering).
    narrative_clean = _strip_markdown(narrative)
    found: list[tuple[int, PathwayMention]] = []  # (offset, mention)
    seen: set[str] = set()

    # --- generic pattern ------------------------------------------------
    for m in _PATHWAY_RE.finditer(narrative_clean):
        head, kind = m.group(1).strip(), m.group(2).strip()
        head_tokens = head.split()
        if len(head_tokens) == 1 and head_tokens[0].lower() in _HEAD_STOPLIST:
            continue
        # Multi-token head: also reject if the LAST head token is a generic
        # adjective ("Most Affected Metabolic" → last="Metabolic" → drop).
        if len(head_tokens) > 1 and head_tokens[-1].lower() in _HEAD_STOPLIST:
            continue
        text = f"{head} {kind}"
        if not _has_meaningful_content(text):
            continue
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
            # Names like "Metabolism" alone carry no content — drop.
            if not _has_meaningful_content(name):
                continue
            canon = _canonicalise(name)
            if canon in seen:
                continue
            pat = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
            m = pat.search(narrative_clean)
            if m is None:
                continue
            seen.add(canon)
            found.append((m.start(), PathwayMention(text=name, canonical=canon)))

    found.sort(key=lambda p: p[0])
    return [pm for _, pm in found]


# Markdown headers whose text suggests the section enumerates drivers.
# Matches '### 2. Key Drivers', '## Driver Compounds', '## Key Pathway
# Drivers', etc. Header level + leading numbering tolerated.
_DRIVER_SECTION_HEADER_RE = re.compile(
    r"^[ \t]*#{1,6}[ \t]+.*\bdriver", re.MULTILINE | re.IGNORECASE
)
_ANY_HEADER_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)


def _extract_driver_sections(narrative: str) -> list[str]:
    """Return the body text of every header section whose title contains
    'driver'. Section ends at the next header of any level.

    LLMs frequently structure narratives as ``### 2. Key Drivers`` followed
    by a bullet list — the sentence-marker rule misses bullets like
    ``- **Compound** is the upstream driver`` because the sentence has
    ``driver`` as a bare word, not in a multi-word marker phrase.
    """
    sections: list[str] = []
    matches = list(_DRIVER_SECTION_HEADER_RE.finditer(narrative))
    if not matches:
        return sections
    # Find all header offsets to know where to stop each section.
    header_starts = [m.start() for m in _ANY_HEADER_RE.finditer(narrative)]
    for hm in matches:
        body_start = narrative.find("\n", hm.end())
        if body_start == -1:
            body_start = hm.end()
        # Find the next header strictly after hm.start().
        next_header = next((s for s in header_starts if s > hm.start()), len(narrative))
        sections.append(narrative[body_start:next_header])
    return sections


def extract_driver_mentions(
    narrative: str,
    candidate_names: list[str],
) -> list[str]:
    """Return canonical compound names cited as drivers in the narrative.

    Two complementary rules — a name is a claimed driver if **either**
    holds:

    1. **Sentence-level marker rule** — the name appears in a sentence
       that also contains one of ``_DRIVER_MARKERS`` (``key driver``,
       ``drives``, ``responsible for`` …). Catches prose statements.
    2. **Driver-section rule** — the name appears in the body of a
       markdown section whose header contains the word ``driver``
       (e.g. ``### 2. Key Drivers`` followed by a bullet list).
       Catches the very common LLM pattern of listing drivers under a
       dedicated heading.

    Order: section-rule hits come first (mirroring the document layout),
    then sentence-rule hits. De-duplicated.
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

    seen: set[str] = set()
    out: list[str] = []

    # 1. Driver-section rule.
    for body in _extract_driver_sections(narrative):
        for m in pattern.finditer(body):
            canonical = name_lookup[m.group(1).lower()]
            if canonical in seen:
                continue
            seen.add(canonical)
            out.append(canonical)

    # 2. Sentence-marker rule.
    sentences = _SENTENCE_SPLIT.split(narrative)
    for sent in sentences:
        if not _DRIVER_MARKER_RE.search(sent):
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
