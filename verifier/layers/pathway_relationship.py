"""Layer 6d — verify Type ``PATHWAY_RELATIONSHIP`` claims.

A PATHWAY_RELATIONSHIP claim asserts a directional or shared-content
relationship between two pathways:

* "Pathway A is **upstream / downstream** of pathway B"
* "Pathways A and B **share intermediates**"
* "There is **cross-talk** between pathway A and pathway B"

Verification:

* **Shared compounds / cross-talk** — query RaMP-DB ``analytehaspathway``
  for the intersection of compounds in both pathways. Verdict:

  * count >= 2  → ``SUPPORTED``
  * count == 1  → ``UNSUPPORTED`` (weak — single-compound overlap is
                   common and not strong evidence of cross-talk)
  * count == 0  → ``CONTRADICTED`` (claimed relationship has no support)

* **Upstream / downstream** — RaMP-DB has no parent-child pathway table
  (no ``pathwayhaspathway`` or analogue), so direction-aware claims fall
  back to ``UNVERIFIABLE_V0`` and surface ``hierarchy_data_available=False``
  in ``enrichment_context``. Documented honestly per the Sub-6 brief
  Q5/D4: "PATHWAY_RELATIONSHIP layer documents whether RaMP has hierarchy
  data and behaves accordingly."

* **No pathway name resolved** or **DB unavailable** → ``UNVERIFIABLE_V0``.

Pathway name → RaMP ID resolution uses ``pathway.pathwayName`` (which
RaMP defines ``COLLATE NOCASE``) with substring fuzz both directions
to tolerate LLM phrasing drift ("Tyrosine catabolism" vs canonical
"Tyrosine metabolism").
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from schemas.sub6_report import SubsixSourceReport
from verifier.schemas import (
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    EnrichmentContext,
    VerifiedClaim,
)

logger = logging.getLogger(__name__)

_RAMP_ENV = "METAGENT_RAMP_PATH"
_KEGG_ENV = "METAGENT_KEGG_PATH"
_DEFAULT_KEGG_PATH = Path(__file__).resolve().parents[2] / "data" / "kegg" / "reaction_graph.sqlite"

# Phrase → relationship_type mapping. Order matters: more specific
# patterns first.
_RELATIONSHIP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcross[-\s]?talk\b", re.I), "cross_talk"),
    (re.compile(r"\bshare[ds]?\b.*\b(intermediates?|metabolites?|compounds?)\b", re.I), "shared_intermediates"),
    (re.compile(r"\bcommon\s+intermediate", re.I), "shared_intermediates"),
    (re.compile(r"\bconverge[s]?\s+on\b", re.I), "shared_intermediates"),
    (re.compile(r"\bupstream\b", re.I), "upstream"),
    (re.compile(r"\bdownstream\b", re.I), "downstream"),
    (re.compile(r"\bfeeds\s+into\b", re.I), "downstream"),
]

# Pathway name phrase regex (re-uses Layer 6a's permissive form).
_PATHWAY_PHRASE_RE = re.compile(
    r"\b("
    r"[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,5}\s+"
    r"(?:metabolism|biosynthesis|degradation|catabolism|anabolism|"
    r"synthesis|cycle|inhibition|production|pathways?)"
    r")\b",
    re.IGNORECASE,
)

_RAMP_PATHWAY_ID_RE = re.compile(r"\b(RAMP_P_\d+)\b")
_KEGG_MAP_ID_RE = re.compile(r"\b(map\d{5})\b")
_WP_ID_RE = re.compile(r"\b(WP\d+)\b")

_SUPPORTED_THRESHOLD = 2  # ≥ 2 shared compounds → SUPPORTED


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def verify_pathway_relationship(
    claim: ClassifiedClaim,
    source_report: SubsixSourceReport,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
    kegg_db_path: str | None = None,
    kegg_conn: sqlite3.Connection | None = None,
) -> VerifiedClaim:
    """Verify one PATHWAY_RELATIONSHIP claim.

    ``conn`` is dependency-injected RaMP connection; production callers
    should leave it as ``None`` and let the layer open a connection from
    ``db_path`` (or ``METAGENT_RAMP_PATH`` env var).

    ``kegg_conn`` / ``kegg_db_path`` analogous for the KEGG reaction
    graph (``data/kegg/reaction_graph.sqlite``). The KEGG graph is only
    consulted for ``upstream`` / ``downstream`` relationships, where it
    powers the directional reachability verdict introduced in
    track_verifier_kegg_hierarchy. ``cross_talk`` /
    ``shared_intermediates`` continue to use RaMP unchanged.
    """
    relationship_type = _detect_relationship(claim.claim_text)
    pathway_a_phrase, pathway_b_phrase = _extract_two_pathways(claim.claim_text)

    ctx_base = EnrichmentContext(
        pathway_a=pathway_a_phrase,
        pathway_b=pathway_b_phrase,
        relationship_type=relationship_type,  # type: ignore[arg-type]
        hierarchy_data_available=False,  # RaMP v2025-03-06 has no hierarchy
    )

    # If regex extraction missed one or both pathways, defer the decision
    # until after we have a DB connection — at that point we can do a
    # reverse-match against RaMP's pathway names to catch disease /
    # condition pathways that don't carry a metabolic-suffix word
    # ("Alkaptonuria", "Selenium micronutrient network", etc., which are
    # common as RaMP's top_pathways[1] / top_pathways[2] entries per the
    # Sub-6 evaluation guide §3 pitfall 4).

    if relationship_type in (None, "unknown"):
        return _unverifiable(
            claim,
            evidence=(
                "Layer 6d could not detect a recognised relationship "
                "keyword (upstream / downstream / cross-talk / shared)."
            ),
            ctx=ctx_base,
        )

    if relationship_type in ("upstream", "downstream"):
        # Try KEGG reaction-graph reachability before falling back to
        # the historical UNVERIFIABLE_V0 verdict. Compound-level path
        # is primary (most directional claims subject single compounds);
        # pathway-pathway path is the fallback when both endpoints are
        # pathway names.
        kegg_verdict = _try_kegg_directional(
            claim,
            relationship_type,
            ctx_base,
            ramp_conn=conn,
            ramp_db_path=db_path,
            kegg_conn=kegg_conn,
            kegg_db_path=kegg_db_path,
            pathway_a_phrase=pathway_a_phrase,
            pathway_b_phrase=pathway_b_phrase,
        )
        if kegg_verdict is not None:
            return kegg_verdict
        return _unverifiable(
            claim,
            evidence=(
                f"Claim asserts a {relationship_type} relationship; "
                "KEGG reaction-graph could not resolve subject and object "
                "to compound or pathway IDs (or KEGG DB unavailable). "
                "RaMP-DB v2025-03-06 has no pathway-hierarchy table either, "
                "so this claim is left unverified."
            ),
            ctx=ctx_base,
        )

    # shared_intermediates / cross_talk → query RaMP for shared compounds.
    db = _resolve_db_path(db_path)
    if conn is None and db is None:
        return _unverifiable(
            claim,
            evidence=(
                f"{_RAMP_ENV} not set and no db_path supplied; cannot "
                "open RaMP-DB to count shared compounds."
            ),
            ctx=ctx_base,
        )

    with _get_connection(conn=conn, path=db) as cursor:
        a_ids = _resolve_pathway(cursor, pathway_a_phrase) if pathway_a_phrase else []
        b_ids = _resolve_pathway(cursor, pathway_b_phrase) if pathway_b_phrase else []

        # Reverse-match fallback: scan RaMP pathway names against the claim
        # text for entries whose canonical name appears verbatim. Covers
        # disease / condition pathways that the suffix-based phrase regex
        # missed (e.g. "Alkaptonuria", "Statin inhibition of cholesterol
        # production"). Only fires when regex didn't find both pathways.
        excluded_names: set[str] = set()
        for got_ids, phrase in ((a_ids, pathway_a_phrase), (b_ids, pathway_b_phrase)):
            if got_ids:
                # Resolve canonical name(s) for the IDs we already matched
                # so reverse-match doesn't pick a same-named entry from a
                # different source (KEGG vs SMPDB vs HMDB aggregations
                # often duplicate names).
                cursor.execute(
                    f"SELECT pathwayName FROM pathway WHERE "
                    f"pathwayRampId IN ({','.join('?' * len(got_ids))})",
                    got_ids,
                )
                for (n,) in cursor.fetchall():
                    if n:
                        excluded_names.add(n.strip().lower())
            if phrase:
                excluded_names.add(phrase.strip().lower())

        if not a_ids or not b_ids:
            extra = _reverse_match_pathways(
                cursor, claim.claim_text,
                exclude_ids=set(a_ids) | set(b_ids),
                exclude_names=excluded_names,
            )
            for cand_phrase, cand_id in extra:
                if not a_ids:
                    pathway_a_phrase = pathway_a_phrase or cand_phrase
                    a_ids = [cand_id]
                elif not b_ids and cand_id not in a_ids:
                    pathway_b_phrase = pathway_b_phrase or cand_phrase
                    b_ids = [cand_id]
                if a_ids and b_ids:
                    break

        if not a_ids or not b_ids:
            return _unverifiable(
                claim,
                evidence=(
                    f"Pathway resolution failed after regex + reverse-match: "
                    f"{pathway_a_phrase!r} → {len(a_ids)} match(es), "
                    f"{pathway_b_phrase!r} → {len(b_ids)} match(es). "
                    "Both must resolve to ≥1 RaMP pathway id."
                ),
                ctx=ctx_base.model_copy(update={
                    "pathway_a": pathway_a_phrase,
                    "pathway_b": pathway_b_phrase,
                }),
            )

        # Update the context with whatever the reverse-match supplied.
        ctx_base = ctx_base.model_copy(update={
            "pathway_a": pathway_a_phrase,
            "pathway_b": pathway_b_phrase,
        })

        # Most specific match per pathway = first hit (caller's regex
        # already returned best by length).
        a_ramp = a_ids[0]
        b_ramp = b_ids[0]

        if a_ramp == b_ramp:
            return _unverifiable(
                claim,
                evidence=(
                    f"Both pathway phrases resolved to the same RaMP id "
                    f"({a_ramp}); cannot adjudicate a relationship between "
                    "a pathway and itself."
                ),
                ctx=ctx_base.model_copy(update={"pathway_a_id": a_ramp, "pathway_b_id": b_ramp}),
            )

        shared = _shared_compounds(cursor, a_ramp, b_ramp)

    ctx = ctx_base.model_copy(update={
        "pathway_a_id": a_ramp,
        "pathway_b_id": b_ramp,
        "shared_compound_count": len(shared),
        "shared_compounds": shared[:20],
    })

    if len(shared) >= _SUPPORTED_THRESHOLD:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=ClaimType.PATHWAY_RELATIONSHIP,
            claim_subtype=_subtype_for(relationship_type),
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.SUPPORTED,
            evidence=(
                f"RaMP analytehaspathway returns {len(shared)} compound(s) "
                f"shared between {a_ramp} ({pathway_a_phrase!r}) and "
                f"{b_ramp} ({pathway_b_phrase!r})."
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="pathway_relationship",
            tool_called="ramp_db",
            trace_summary=f"{len(shared)} shared compounds across pathways",
            enrichment_context=ctx,
        )

    if len(shared) == 1:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=ClaimType.PATHWAY_RELATIONSHIP,
            claim_subtype=_subtype_for(relationship_type),
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.UNSUPPORTED,
            evidence=(
                f"Only 1 shared compound between {a_ramp} and {b_ramp}; "
                "single-compound overlap is too weak to support a "
                "cross-talk / shared-intermediates claim "
                f"(threshold {_SUPPORTED_THRESHOLD})."
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="pathway_relationship",
            tool_called="ramp_db",
            trace_summary="1 shared compound (weak)",
            enrichment_context=ctx,
        )

    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.PATHWAY_RELATIONSHIP,
        claim_subtype=_subtype_for(relationship_type),
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.CONTRADICTED,
        evidence=(
            f"RaMP analytehaspathway returns 0 compounds shared between "
            f"{a_ramp} ({pathway_a_phrase!r}) and {b_ramp} "
            f"({pathway_b_phrase!r}); claim of "
            f"{relationship_type.replace('_', ' ')} has no support."
        ),
        extracted_fields=claim.extracted_fields,
        verifier_layer="pathway_relationship",
        tool_called="ramp_db",
        trace_summary="no shared compounds",
        enrichment_context=ctx,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_relationship(text: str) -> str | None:
    for pat, label in _RELATIONSHIP_PATTERNS:
        if pat.search(text):
            return label
    return None


_AND_SPLIT_RE = re.compile(r"\s+(?:and|or|versus|vs\.?)\s+", re.IGNORECASE)

# Reverse-anchored trim: from a phrase ending in a pathway-suffix word,
# keep only the last 1–4 word run before the suffix. Lets us strip
# leading filler like "There is significant cross-talk between" /
# "and " / "between " that the forward regex captured greedily.
_PATHWAY_TAIL_RE = re.compile(
    r"((?:[A-Za-z][A-Za-z0-9-]*\s+){0,3}"
    r"(?:metabolism|biosynthesis|degradation|catabolism|anabolism|"
    r"synthesis|cycle|inhibition|production|pathways?))\s*$",
    re.IGNORECASE,
)


def _trim_pathway_phrase(phrase: str) -> str:
    """Keep only the trailing pathway phrase (≤4 words ending in a suffix).

    Strips leading words until the first Title-Case (or all-caps) token,
    so that filler like "There is significant cross-talk between
    Tyrosine metabolism" trims to "Tyrosine metabolism". Fully lowercase
    leading words (``cross-talk``, ``and``, ``between``) are dropped.
    """
    s = phrase.strip()
    m = _PATHWAY_TAIL_RE.search(s)
    if not m:
        return s
    trimmed = m.group(1).strip()

    pathway_suffix_words = {
        "metabolism", "biosynthesis", "degradation", "catabolism",
        "anabolism", "synthesis", "cycle", "inhibition", "production",
        "pathway", "pathways",
    }
    words = trimmed.split()

    # Drop leading words that look like filler: lowercase non-suffix
    # tokens, hyphenated compound words like "cross-talk", or pure
    # function words. Preserve the trailing suffix word(s) — they're
    # what made this match a pathway phrase to begin with.
    while words and len(words) > 1:
        head = words[0]
        head_lower = head.lower()
        is_title = head[:1].isupper() and head[1:2].islower() if head else False
        is_acronym = head.isupper() and len(head) >= 2
        if is_title or is_acronym:
            break
        if head_lower in pathway_suffix_words:
            # Don't strip a suffix-word that happens to lead — could be
            # a false positive ("Cycle of life" doesn't start with a
            # pathway). But we should never reach here if the regex did
            # its job; defensive break.
            break
        words.pop(0)

    return " ".join(words)


def _extract_two_pathways(text: str) -> tuple[str | None, str | None]:
    """Return the first two pathway phrases / IDs found in ``text``.

    Phrase-style matches are split on " and "/" or " in case the regex
    greedily captured both pathways in one span (common for sentences
    like "X metabolism and Y metabolism share intermediates").
    """
    candidates: list[str] = []

    # ID-style first (RaMP / map / WP).
    for rx in (_RAMP_PATHWAY_ID_RE, _KEGG_MAP_ID_RE, _WP_ID_RE):
        for m in rx.finditer(text):
            tok = m.group(1)
            if tok not in candidates:
                candidates.append(tok)

    # Phrase-style with and/or splitting.
    for m in _PATHWAY_PHRASE_RE.finditer(text):
        full_phrase = m.group(0).strip()
        # Only split when the full phrase contains an and/or token AND
        # at least two pathway-suffix words (so "Tyrosine metabolism and
        # Phenylalanine metabolism" splits cleanly but "vitamin A and
        # B12 metabolism" does not, since there's only one suffix).
        suffix_count = len(re.findall(
            r"\b(?:metabolism|biosynthesis|degradation|catabolism|anabolism|"
            r"synthesis|cycle|inhibition|production|pathways?)\b",
            full_phrase,
            re.IGNORECASE,
        ))
        if suffix_count >= 2 and _AND_SPLIT_RE.search(full_phrase):
            subphrases = [s.strip() for s in _AND_SPLIT_RE.split(full_phrase)]
            for sub in subphrases:
                trimmed = _trim_pathway_phrase(sub)
                if trimmed and trimmed.lower() not in {c.lower() for c in candidates}:
                    candidates.append(trimmed)
        else:
            trimmed = _trim_pathway_phrase(full_phrase)
            if trimmed and trimmed.lower() not in {c.lower() for c in candidates}:
                candidates.append(trimmed)

    if len(candidates) < 2:
        return (candidates[0] if candidates else None, None)
    return (candidates[0], candidates[1])


def _resolve_db_path(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    env = os.environ.get(_RAMP_ENV)
    if env:
        p = Path(env)
        return p if p.exists() else None
    return None


@contextmanager
def _get_connection(
    *, conn: sqlite3.Connection | None, path: Path | None,
) -> Iterator[sqlite3.Cursor]:
    if conn is not None:
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
        return

    if path is None:
        raise RuntimeError("Both conn and path are None — caller bug.")

    new_conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = new_conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
    finally:
        new_conn.close()


def _resolve_pathway(cursor: sqlite3.Cursor, phrase: str) -> list[str]:
    """Return RaMP pathway ids matching ``phrase``.

    Accepts:
      * Direct RAMP_P_xxxx ID (returned as-is if present in DB)
      * KEGG ``mapXXXXX`` (looked up via ``pathway.sourceId``)
      * WikiPathways ``WPXXXX`` (same)
      * Free-text name → ``pathway.pathwayName`` substring match (NOCASE).
    """
    phrase = phrase.strip()

    if _RAMP_PATHWAY_ID_RE.fullmatch(phrase):
        cursor.execute(
            "SELECT pathwayRampId FROM pathway WHERE pathwayRampId = ?",
            (phrase,),
        )
        rows = [r[0] for r in cursor.fetchall()]
        return rows

    if _KEGG_MAP_ID_RE.fullmatch(phrase) or _WP_ID_RE.fullmatch(phrase):
        cursor.execute(
            "SELECT pathwayRampId FROM pathway WHERE sourceId = ?",
            (phrase,),
        )
        rows = [r[0] for r in cursor.fetchall()]
        return rows

    # Free-text name. pathwayName is COLLATE NOCASE.
    cursor.execute(
        "SELECT pathwayRampId, pathwayName, type FROM pathway "
        "WHERE pathwayName = ? OR pathwayName LIKE ? OR pathwayName LIKE ? "
        "ORDER BY length(pathwayName) ASC LIMIT 50",
        (phrase, f"%{phrase}%", f"{phrase}%"),
    )
    rows = cursor.fetchall()
    if not rows:
        return []
    # Prefer KEGG / WikiPathways canonical sources when multiple hits;
    # fall back to first.
    preferred_sources = {"kegg", "wikipathways", "reactome", "smpdb", "hmdb"}
    rows.sort(key=lambda r: (
        0 if (r[2] or "").lower() in preferred_sources else 1,
        len(r[1] or ""),
    ))
    return [r[0] for r in rows]


def _reverse_match_pathways(
    cursor: sqlite3.Cursor,
    text: str,
    exclude_ids: set[str],
    *,
    exclude_names: set[str] | None = None,
    min_name_length: int = 5,
    limit: int = 4,
) -> list[tuple[str, str]]:
    """Scan RaMP ``pathway`` for canonical names that appear verbatim in
    ``text``. Returns up to ``limit`` (phrase, ramp_id) pairs ordered by
    descending name length (longer = more specific).

    The query pulls a candidate set first by hitting any pathway whose
    name is contained in the claim text. SQLite's COLLATE NOCASE on
    ``pathwayName`` makes the comparison case-insensitive.

    ``exclude_ids`` skips pathway ids the regex path already matched so
    the same pathway doesn't end up as both A and B.
    """
    text_lower = text.lower()
    # We can't pass arbitrary substrings to SQL, so pull the whole
    # pathway table once (~50k rows) and scan in Python. RaMP ships
    # ~50k pathway rows; this is ~5 ms. Acceptable for a verifier hot
    # path because Layer 6d only fires after the regex misses, which is
    # the minority case.
    cursor.execute(
        "SELECT pathwayRampId, pathwayName, type, length(pathwayName) "
        "FROM pathway WHERE pathwayName IS NOT NULL "
        "ORDER BY length(pathwayName) DESC"
    )
    out: list[tuple[str, str]] = []
    seen_ids: set[str] = set(exclude_ids)
    seen_names: set[str] = set(n.strip().lower() for n in (exclude_names or set()))
    for ramp_id, name, _kind, _ln in cursor.fetchall():
        if ramp_id in seen_ids:
            continue
        if not name or len(name) < min_name_length:
            continue
        n_lower = name.lower().strip()
        if n_lower in seen_names:
            continue
        # Word-bounded substring check.
        if _word_bounded_in_text(n_lower, text_lower):
            out.append((name, ramp_id))
            seen_ids.add(ramp_id)
            seen_names.add(n_lower)
            if len(out) >= limit:
                break
    return out


def _word_bounded_in_text(needle: str, haystack: str) -> bool:
    """Word-bounded ``needle in haystack`` for already-lowercased inputs."""
    if not needle or len(needle) > len(haystack):
        return False
    idx = 0
    n = len(needle)
    while True:
        pos = haystack.find(needle, idx)
        if pos < 0:
            return False
        left_ok = pos == 0 or not haystack[pos - 1].isalnum()
        right_pos = pos + n
        right_ok = right_pos >= len(haystack) or not haystack[right_pos].isalnum()
        if left_ok and right_ok:
            return True
        idx = pos + 1


def _shared_compounds(
    cursor: sqlite3.Cursor, a: str, b: str
) -> list[str]:
    cursor.execute(
        "SELECT rampId FROM analytehaspathway WHERE pathwayRampId = ? "
        "INTERSECT "
        "SELECT rampId FROM analytehaspathway WHERE pathwayRampId = ?",
        (a, b),
    )
    return [r[0] for r in cursor.fetchall()]


def _subtype_for(relationship_type: str) -> ClaimSubtype:
    return {
        "upstream": ClaimSubtype.PATHWAY_UPSTREAM,
        "downstream": ClaimSubtype.PATHWAY_DOWNSTREAM,
        "cross_talk": ClaimSubtype.PATHWAY_CROSS_TALK,
        "shared_intermediates": ClaimSubtype.PATHWAY_SHARED_INTERMEDIATES,
    }.get(relationship_type, ClaimSubtype.UNKNOWN)


def _unverifiable(
    claim: ClassifiedClaim,
    *,
    evidence: str,
    ctx: EnrichmentContext,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.PATHWAY_RELATIONSHIP,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        extracted_fields=claim.extracted_fields,
        verifier_layer="pathway_relationship",
        trace_summary="pathway_relationship unverifiable",
        enrichment_context=ctx,
    )


# ---------------------------------------------------------------------------
# KEGG hierarchy branch (track_verifier_kegg_hierarchy)
# ---------------------------------------------------------------------------


def _resolve_kegg_db_path(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    env = os.environ.get(_KEGG_ENV)
    if env:
        p = Path(env)
        return p if p.is_file() else None
    if _DEFAULT_KEGG_PATH.is_file():
        return _DEFAULT_KEGG_PATH
    return None


def _verdict(
    claim: ClassifiedClaim,
    verdict_kind: ClaimVerdict,
    *,
    evidence: str,
    ctx: EnrichmentContext,
    correction: str | None = None,
    trace_summary: str = "pathway_relationship via kegg",
) -> VerifiedClaim:
    """Construct a VerifiedClaim with the given verdict; thin sibling
    of ``_unverifiable`` for the SUPPORTED / UNSUPPORTED / CONTRADICTED
    cases the KEGG branch can return."""
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.PATHWAY_RELATIONSHIP,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=verdict_kind,
        evidence=evidence,
        correction=correction,
        extracted_fields=claim.extracted_fields,
        verifier_layer="pathway_relationship",
        trace_summary=trace_summary,
        enrichment_context=ctx,
    )


def _try_kegg_directional(
    claim: ClassifiedClaim,
    relationship_type: str,           # "upstream" | "downstream"
    ctx_base: EnrichmentContext,
    *,
    ramp_conn: sqlite3.Connection | None,
    ramp_db_path: str | None,
    kegg_conn: sqlite3.Connection | None,
    kegg_db_path: str | None,
    pathway_a_phrase: str | None,
    pathway_b_phrase: str | None,
) -> VerifiedClaim | None:
    """Drive the KEGG-graph branch for an upstream/downstream claim.

    Returns:
      - VerifiedClaim when KEGG produced a verdict (SUPPORTED /
        UNSUPPORTED / CONTRADICTED, or its own UNVERIFIABLE_V0 with a
        clearer reason than the historical "no hierarchy table" one)
      - None when caller should fall back to the legacy unverifiable
        verdict (KEGG DB unavailable + no usable input)
    """
    # 1. Open KEGG connection (defensive; layer leaves the cursor
    #    closed if it opened one).
    own_kegg_conn = False
    if kegg_conn is None:
        path = _resolve_kegg_db_path(kegg_db_path)
        if path is None:
            logger.info(
                "Layer 6d KEGG branch: %s not set / file missing — falling back to UNVERIFIABLE_V0",
                _KEGG_ENV,
            )
            return None
        kegg_conn = sqlite3.connect(str(path))
        own_kegg_conn = True

    try:
        # Lazy import — Layer 6d previously had no kegg/* dependency and
        # we want the import error (if any) to surface here, not at
        # module-load time.
        from tools.kegg.claim_extraction import extract_compound_pair
        from tools.kegg.reachability import (
            ReachabilityResult,
            is_compound_a_upstream_of_compound_b,
            is_pathway_a_upstream_of_pathway_b,
            resolve_compound_to_kegg,
        )

        ctx = EnrichmentContext(
            pathway_a=ctx_base.pathway_a,
            pathway_b=ctx_base.pathway_b,
            relationship_type=ctx_base.relationship_type,
            hierarchy_data_available=True,  # KEGG graph IS the hierarchy
        )

        # 2. Compound-level resolution: extract subject / object phrases
        #    and try to map both to cpd:C-IDs.
        a_phrase, b_phrase = extract_compound_pair(claim.claim_text)
        cpd_a, cpd_b, src_a, src_b = None, None, None, None
        if a_phrase and b_phrase:
            cpd_a, src_a = resolve_compound_to_kegg(a_phrase, conn=kegg_conn)
            cpd_b, src_b = resolve_compound_to_kegg(b_phrase, conn=kegg_conn)

        if cpd_a and cpd_b:
            return _verdict_from_compound_reachability(
                claim,
                relationship_type,
                ctx,
                a_phrase=a_phrase or "",
                b_phrase=b_phrase or "",
                cpd_a=cpd_a,
                cpd_b=cpd_b,
                src_a=src_a or "",
                src_b=src_b or "",
                kegg_conn=kegg_conn,
                checker=is_compound_a_upstream_of_compound_b,
            )

        # 3. Pathway-pair fallback: if compound resolution failed but
        #    pathway phrases were extracted upstream, try resolving each
        #    pathway phrase to a KEGG hsa<NNNNN> ID via RaMP and run
        #    pathway-level BFS.
        kegg_a, kegg_b = _resolve_pathways_to_kegg(
            pathway_a_phrase, pathway_b_phrase,
            ramp_conn=ramp_conn, ramp_db_path=ramp_db_path,
        )
        if kegg_a and kegg_b:
            return _verdict_from_pathway_reachability(
                claim, relationship_type, ctx,
                kegg_a=kegg_a, kegg_b=kegg_b,
                a_phrase=pathway_a_phrase or "",
                b_phrase=pathway_b_phrase or "",
                kegg_conn=kegg_conn,
                checker=is_pathway_a_upstream_of_pathway_b,
            )

        # 4. Neither compound nor pathway resolution succeeded.
        notes: list[str] = []
        if not (a_phrase and b_phrase):
            notes.append("compound-pair heuristic could not isolate two endpoints")
        else:
            if not cpd_a:
                notes.append(f"subject {a_phrase!r} did not resolve to a KEGG cpd: ID")
            if not cpd_b:
                notes.append(f"object {b_phrase!r} did not resolve to a KEGG cpd: ID")
        if pathway_a_phrase or pathway_b_phrase:
            notes.append(
                "pathway-pair fallback also failed: phrases did not "
                "resolve to KEGG-source RaMP pathways"
            )
        return _verdict(
            claim,
            ClaimVerdict.UNVERIFIABLE_V0,
            evidence=(
                "KEGG reaction graph: " + "; ".join(notes)
                if notes else
                "KEGG reaction graph: no resolvable endpoints"
            ),
            ctx=ctx,
            trace_summary="pathway_relationship kegg_unresolved",
        )
    finally:
        if own_kegg_conn and kegg_conn is not None:
            kegg_conn.close()


def _verdict_from_compound_reachability(
    claim: ClassifiedClaim,
    relationship_type: str,
    ctx: EnrichmentContext,
    *,
    a_phrase: str,
    b_phrase: str,
    cpd_a: str,
    cpd_b: str,
    src_a: str,
    src_b: str,
    kegg_conn: sqlite3.Connection,
    checker,
) -> VerifiedClaim:
    """For an "X is upstream of Y" claim with both endpoints resolved
    to KEGG compound IDs, run the BFS in the direction implied by the
    relationship and translate the result into a verdict.

    Direction normalisation: "X is upstream of Y" → BFS(source=X,
    target=Y); "X is downstream of Y" → BFS(source=Y, target=X)
    (because "X downstream of Y" ⇔ "Y upstream of X").
    """
    if relationship_type == "upstream":
        source_cpd, target_cpd = cpd_a, cpd_b
        source_phrase, target_phrase = a_phrase, b_phrase
    else:  # downstream
        source_cpd, target_cpd = cpd_b, cpd_a
        source_phrase, target_phrase = b_phrase, a_phrase

    forward = checker(source_cpd, target_cpd, conn=kegg_conn, max_path_length=6)

    # Build evidence + tool_evidence regardless of verdict.
    tool_ev: dict[str, object] = {
        "kegg_compound_a": cpd_a,
        "kegg_compound_b": cpd_b,
        "kegg_subject_alias_source": src_a,
        "kegg_object_alias_source": src_b,
        "kegg_max_path_length": forward.max_path_length,
        "kegg_direction": forward.direction,
        "kegg_path": list(forward.shortest_path) if forward.shortest_path else None,
        "kegg_path_length": forward.path_length,
        "kegg_resolution": "compound",
    }
    ctx_with_ev = EnrichmentContext(
        pathway_a=ctx.pathway_a,
        pathway_b=ctx.pathway_b,
        relationship_type=ctx.relationship_type,
        hierarchy_data_available=True,
        tool_evidence=tool_ev,
    )

    if forward.is_reachable:
        # Forward path exists → claim direction matches reaction graph
        path_str = " → ".join(forward.shortest_path or [])
        evidence = (
            f"KEGG reaction graph: directional path "
            f"{source_phrase} ({source_cpd}) → {target_phrase} ({target_cpd}) "
            f"in {forward.path_length} hop(s) "
            f"[{path_str}]; direction={forward.direction}"
        )
        return _verdict(
            claim, ClaimVerdict.SUPPORTED,
            evidence=evidence, ctx=ctx_with_ev,
            trace_summary=f"pathway_relationship kegg_compound supported len={forward.path_length}",
        )

    # Forward path missing — check reverse for a CONTRADICTED verdict.
    reverse = checker(target_cpd, source_cpd, conn=kegg_conn, max_path_length=6)
    if reverse.is_reachable:
        # The path goes the OTHER way: claim was "A upstream of B" but
        # graph shows B upstream of A.
        rev_path = " → ".join(reverse.shortest_path or [])
        correction = (
            f"{target_phrase} ({target_cpd}) is upstream of "
            f"{source_phrase} ({source_cpd}) — the claim has the "
            f"directionality reversed"
        )
        evidence = (
            f"KEGG reaction graph: no path from {source_cpd} → {target_cpd} "
            f"within {forward.max_path_length} hops, but the REVERSE path "
            f"{target_cpd} → {source_cpd} exists in {reverse.path_length} "
            f"hop(s) [{rev_path}]. Claim direction is inverted."
        )
        # Refresh tool_evidence with the reverse path so audit captures both.
        tool_ev["kegg_reverse_path"] = list(reverse.shortest_path or [])
        tool_ev["kegg_reverse_path_length"] = reverse.path_length
        return _verdict(
            claim, ClaimVerdict.CONTRADICTED,
            evidence=evidence, ctx=ctx_with_ev,
            correction=correction,
            trace_summary="pathway_relationship kegg_compound direction_inverted",
        )

    # Neither direction reachable within bound → UNSUPPORTED
    evidence = (
        f"KEGG reaction graph: no directional path between "
        f"{source_cpd} and {target_cpd} within "
        f"{forward.max_path_length} hops in either direction. "
        f"The two compounds are not in a graph-reachable "
        f"upstream/downstream relationship."
    )
    return _verdict(
        claim, ClaimVerdict.UNSUPPORTED,
        evidence=evidence, ctx=ctx_with_ev,
        trace_summary="pathway_relationship kegg_compound no_path",
    )


def _verdict_from_pathway_reachability(
    claim: ClassifiedClaim,
    relationship_type: str,
    ctx: EnrichmentContext,
    *,
    kegg_a: str,
    kegg_b: str,
    a_phrase: str,
    b_phrase: str,
    kegg_conn: sqlite3.Connection,
    checker,
) -> VerifiedClaim:
    """Pathway-pair fallback. Same direction logic as the compound path."""
    if relationship_type == "upstream":
        source_pid, target_pid = kegg_a, kegg_b
        source_phrase, target_phrase = a_phrase, b_phrase
    else:
        source_pid, target_pid = kegg_b, kegg_a
        source_phrase, target_phrase = b_phrase, a_phrase

    forward = checker(source_pid, target_pid, conn=kegg_conn, max_path_length=4)

    tool_ev: dict[str, object] = {
        "kegg_pathway_a": kegg_a,
        "kegg_pathway_b": kegg_b,
        "kegg_max_path_length": forward.max_path_length,
        "kegg_direction": forward.direction,
        "kegg_path": list(forward.shortest_path) if forward.shortest_path else None,
        "kegg_path_length": forward.path_length,
        "kegg_resolution": "pathway",
    }
    ctx_with_ev = EnrichmentContext(
        pathway_a=ctx.pathway_a,
        pathway_b=ctx.pathway_b,
        relationship_type=ctx.relationship_type,
        hierarchy_data_available=True,
        tool_evidence=tool_ev,
    )

    if forward.is_reachable:
        path_str = " → ".join(forward.shortest_path or [])
        evidence = (
            f"KEGG reaction graph: pathway-level path "
            f"{source_phrase} ({source_pid}) → {target_phrase} ({target_pid}) "
            f"in {forward.path_length} hop(s) [{path_str}]; "
            f"direction={forward.direction}"
        )
        return _verdict(
            claim, ClaimVerdict.SUPPORTED,
            evidence=evidence, ctx=ctx_with_ev,
            trace_summary=f"pathway_relationship kegg_pathway supported len={forward.path_length}",
        )

    reverse = checker(target_pid, source_pid, conn=kegg_conn, max_path_length=4)
    if reverse.is_reachable:
        evidence = (
            f"KEGG reaction graph: no pathway-level path "
            f"{source_pid} → {target_pid} within "
            f"{forward.max_path_length} hops; reverse "
            f"{target_pid} → {source_pid} exists in "
            f"{reverse.path_length} hops. Claim direction is inverted."
        )
        tool_ev["kegg_reverse_path"] = list(reverse.shortest_path or [])
        tool_ev["kegg_reverse_path_length"] = reverse.path_length
        return _verdict(
            claim, ClaimVerdict.CONTRADICTED,
            evidence=evidence, ctx=ctx_with_ev,
            correction=(
                f"{target_phrase} ({target_pid}) is upstream of "
                f"{source_phrase} ({source_pid}) — claim direction is inverted"
            ),
            trace_summary="pathway_relationship kegg_pathway direction_inverted",
        )

    evidence = (
        f"KEGG reaction graph: no pathway-level path between "
        f"{source_pid} and {target_pid} within "
        f"{forward.max_path_length} hops in either direction."
    )
    return _verdict(
        claim, ClaimVerdict.UNSUPPORTED,
        evidence=evidence, ctx=ctx_with_ev,
        trace_summary="pathway_relationship kegg_pathway no_path",
    )


def _resolve_pathways_to_kegg(
    a_phrase: str | None,
    b_phrase: str | None,
    *,
    ramp_conn: sqlite3.Connection | None,
    ramp_db_path: str | None,
) -> tuple[str | None, str | None]:
    """Map two RaMP-style pathway phrases to KEGG ``hsa<NNNNN>`` IDs.

    Only KEGG-source RaMP pathways are returned (SMPDB / WikiPathways /
    Reactome stay None) — Layer 6d's KEGG branch only operates on KEGG
    pathways. Returns (None, None) when RaMP DB is unreachable so the
    caller falls back to UNVERIFIABLE_V0.
    """
    if not a_phrase or not b_phrase:
        return None, None
    db_path = _resolve_db_path(ramp_db_path)
    if ramp_conn is None and db_path is None:
        return None, None

    try:
        with _get_connection(conn=ramp_conn, path=db_path) as cursor:
            kegg_a = _phrase_to_kegg_id(cursor, a_phrase)
            kegg_b = _phrase_to_kegg_id(cursor, b_phrase)
            return kegg_a, kegg_b
    except sqlite3.Error as e:
        logger.warning("KEGG-pathway resolution via RaMP failed: %s", e)
        return None, None


def _phrase_to_kegg_id(cursor: sqlite3.Cursor, phrase: str) -> str | None:
    """Find any RaMP pathway whose name fuzzy-matches ``phrase`` AND
    whose source is 'kegg'; return its KEGG external_id normalised to
    ``hsa<NNNNN>``. Returns None when nothing KEGG-source matches.
    """
    cursor.execute(
        "SELECT pathwaySourceId FROM pathway "
        "WHERE pathwaySource = 'kegg' "
        "  AND (pathwayName LIKE ? OR ? LIKE '%' || pathwayName || '%') "
        "LIMIT 1",
        (f"%{phrase}%", phrase),
    )
    row = cursor.fetchone()
    if not row or not row[0]:
        return None
    src_id = str(row[0]).strip()
    # KEGG source IDs in RaMP appear as 'hsa00270' or 'map00270'.
    m = re.match(r"^(?:map|hsa|ko)?(\d{4,5})$", src_id, re.IGNORECASE)
    if not m:
        return None
    return f"hsa{int(m.group(1)):05d}"
