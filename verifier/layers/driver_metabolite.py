"""Layer 6b — verify Type ``DRIVER_METABOLITE`` claims.

A DRIVER_METABOLITE claim asserts which compounds are driving an
enrichment signal (e.g. "Tyrosine and DOPA are key drivers of this
enrichment", "C00070 and C00122 drive the pathway"). Verification
resolves every claimed driver to an InChIKey first-block and checks set
membership against ``ground_truth_signal_compounds`` /
``ground_truth_noise_compounds``.

Verdict policy:

* All claimed drivers ∈ signal set                                → ``SUPPORTED``
* Any claimed driver ∈ noise set (false-driver hallucination)     → ``CONTRADICTED``
* Some claimed drivers off-pool (neither signal nor noise)        → ``UNSUPPORTED``
* No claimed drivers extractable, or none of them resolve to an
  InChIKey                                                         → ``UNVERIFIABLE_V0``

Resolution:

The curated mammalian compound pool (`curated_hmdb_mammalian.jsonl`,
150 records) is the v0 lookup table. It carries name + KEGG ID + HMDB
ID + InChIKey for each compound, so a claimed driver can be resolved
from any of those forms. The lookup is cached at module load — load
cost is ~10 ms for 150 records, amortised across every claim verified.

The ``SubsixSourceReport.compound_lookup`` field can be pre-populated by
the benchmark runner to short-circuit module-level loading (preferred
when running many tasks back-to-back).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

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

_CURATED_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "benchmark"
    / "sub6"
    / "curated_hmdb_mammalian.jsonl"
)

# Module-level cache. Populated lazily on first call.
_LOOKUP_CACHE: dict[str, str] | None = None


# Pattern for KEGG compound IDs, HMDB IDs, and bare InChIKey first-blocks.
_KEGG_RE = re.compile(r"\b(C\d{5})\b")
_HMDB_RE = re.compile(r"\b(HMDB\d{6,})\b", re.IGNORECASE)
_INCHIKEY_BLOCK_RE = re.compile(r"\b([A-Z]{14})\b")

# Driver-name extraction is best-effort: lift quoted / capitalised tokens
# adjacent to driver keywords, then resolve. The extractor and classifier
# can populate ``extracted_fields.candidate_name`` in the future to make
# this deterministic.
_DRIVER_KEYWORDS = re.compile(
    r"\b("
    r"driv(?:e|er|ers|en|ing)|"
    r"key\s+(?:metabolite|compound|driver|contributor)s?|"
    r"main\s+(?:contributor|driver|marker)s?|"
    r"primar(?:y|ily)|"
    r"central\s+metabolite|"
    r"principal\s+marker"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def verify_driver_metabolite(
    claim: ClassifiedClaim,
    source_report: SubsixSourceReport,
    *,
    lookup: dict[str, str] | None = None,
) -> VerifiedClaim:
    """Verify one DRIVER_METABOLITE claim.

    ``lookup`` is dependency-injected for tests; production callers should
    leave it as ``None`` (or set ``source_report.compound_lookup``) and
    let the layer load the curated pool itself.
    """
    effective_lookup = (
        lookup
        if lookup is not None
        else (source_report.compound_lookup or _get_default_lookup())
    )

    claimed_names = _extract_driver_names(claim, effective_lookup)
    if not claimed_names:
        return _unverifiable(
            claim,
            evidence=(
                "Layer 6b found no driver compound names / IDs in the claim. "
                "The classifier may have misrouted a non-driver claim, or "
                "the names need a different extractor."
            ),
            ctx=EnrichmentContext(),
        )

    # Resolve claimed → InChIKey first-block.
    resolved: list[str] = []
    unresolved: list[str] = []
    for name in claimed_names:
        ik_block = _resolve_to_inchikey_block(name, effective_lookup)
        if ik_block is None:
            unresolved.append(name)
        else:
            resolved.append(ik_block)

    if not resolved:
        return _unverifiable(
            claim,
            evidence=(
                f"None of the claimed drivers {claimed_names!r} resolved "
                f"to an InChIKey via the curated pool ({_CURATED_PATH.name}). "
                "Layer 6b cannot adjudicate without a resolution anchor."
            ),
            ctx=EnrichmentContext(
                claimed_drivers=claimed_names,
                unresolved_drivers=unresolved,
            ),
        )

    # Resolve ground-truth KEGG IDs → InChIKey first-blocks.
    signal_blocks = _resolve_kegg_set(
        source_report.ground_truth_signal_compounds, effective_lookup
    )
    noise_blocks = _resolve_kegg_set(
        source_report.ground_truth_noise_compounds, effective_lookup
    )

    resolved_set = set(resolved)
    matched_signal = sorted(resolved_set & signal_blocks)
    matched_noise = sorted(resolved_set & noise_blocks)
    off_pool = sorted(resolved_set - signal_blocks - noise_blocks)

    precision = (
        len(matched_signal) / len(resolved_set) if resolved_set else None
    )
    recall = (
        len(matched_signal) / len(signal_blocks) if signal_blocks else None
    )

    ctx = EnrichmentContext(
        claimed_drivers=claimed_names,
        claimed_drivers_resolved=resolved,
        matched_signal_drivers=matched_signal,
        matched_noise_drivers=matched_noise,
        unresolved_drivers=unresolved,
        off_pool_drivers=off_pool,
        driver_precision=precision,
        driver_recall=recall,
    )

    # Verdict resolution. Order matters — CONTRADICTED outranks UNSUPPORTED.
    if matched_noise:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=ClaimType.DRIVER_METABOLITE,
            claim_subtype=ClaimSubtype.DRIVER_LIST,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.CONTRADICTED,
            evidence=(
                f"Claim cites {len(matched_noise)} compound(s) "
                f"({matched_noise}) that the task injected as noise; "
                f"these are explicitly NOT drivers of "
                f"{source_report.ground_truth_pathway.get('pathway_name')!r}."
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="driver_metabolite",
            tool_called="curated_hmdb_mammalian",
            trace_summary=f"{len(matched_noise)} noise compound(s) cited as driver",
            enrichment_context=ctx,
        )

    if off_pool:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=ClaimType.DRIVER_METABOLITE,
            claim_subtype=ClaimSubtype.DRIVER_LIST,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.UNSUPPORTED,
            evidence=(
                f"Claim cites {len(off_pool)} compound(s) ({off_pool}) "
                "outside this task's pool (neither signal nor noise). "
                "Resolved but not adjudicable as drivers; treated as "
                "unsupported rather than contradicted."
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="driver_metabolite",
            tool_called="curated_hmdb_mammalian",
            trace_summary=f"{len(off_pool)} off-pool compound(s) cited",
            enrichment_context=ctx,
        )

    if resolved_set <= signal_blocks:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=ClaimType.DRIVER_METABOLITE,
            claim_subtype=ClaimSubtype.DRIVER_LIST,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.SUPPORTED,
            evidence=(
                f"All {len(resolved_set)} claimed driver(s) are members of "
                f"ground_truth_signal_compounds. "
                f"precision={precision:.2f} recall={recall:.2f}."
                if precision is not None and recall is not None
                else f"All {len(resolved_set)} claimed driver(s) are signal."
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="driver_metabolite",
            tool_called="curated_hmdb_mammalian",
            trace_summary=(
                f"{len(matched_signal)}/{len(signal_blocks)} signal recall, "
                f"all claimed correct"
            ),
            enrichment_context=ctx,
        )

    # Defensive fallback: should not reach here given the policy above.
    return _unverifiable(
        claim,
        evidence=(
            "Driver verdict policy did not produce a definitive outcome; "
            "this is unexpected and should be investigated."
        ),
        ctx=ctx,
    )


# ---------------------------------------------------------------------------
# Lookup loading
# ---------------------------------------------------------------------------


def _get_default_lookup() -> dict[str, str]:
    """Lazy-load the curated mammalian pool into ``_LOOKUP_CACHE``.

    The lookup maps ANY of (lowercase name, KEGG ID, HMDB ID, full
    InChIKey, InChIKey first-block, PubChem CID) to the InChIKey
    first-block. This collapses the resolution surface to a single dict
    lookup at the cost of ~5x dictionary entries per compound.
    """
    global _LOOKUP_CACHE
    if _LOOKUP_CACHE is not None:
        return _LOOKUP_CACHE

    lookup: dict[str, str] = {}
    if not _CURATED_PATH.exists():
        logger.warning(
            "curated mammalian pool not found at %s; driver_metabolite "
            "layer will return UNVERIFIABLE_V0 for every claim.",
            _CURATED_PATH,
        )
        _LOOKUP_CACHE = lookup
        return lookup

    with _CURATED_PATH.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ik_block = rec.get("inchikey_first_block")
            if not ik_block:
                ik = rec.get("inchikey") or ""
                ik_block = ik.split("-")[0] if "-" in ik else ik
            if not ik_block:
                continue
            for key in (
                rec.get("name"),
                rec.get("kegg_id"),
                rec.get("hmdb_id"),
                rec.get("inchikey"),
                rec.get("inchikey_first_block"),
                str(rec.get("pubchem_cid")) if rec.get("pubchem_cid") else None,
            ):
                if key:
                    lookup[str(key).strip().lower()] = ik_block

    _LOOKUP_CACHE = lookup
    return lookup


def reset_lookup_cache() -> None:
    """Drop the in-module curated-pool cache. Tests use this to inject
    custom lookups between cases without reload friction."""
    global _LOOKUP_CACHE
    _LOOKUP_CACHE = None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _extract_driver_names(
    claim: ClassifiedClaim,
    lookup: dict[str, str] | None,
) -> list[str]:
    """Lift driver names / IDs from claim text + typed fields.

    Strategy (in priority order):
      1. ``extracted_fields.candidate_name`` — typed extractor output.
      2. Database IDs found by regex: KEGG, HMDB, InChIKey first-blocks.
      3. **Lookup-key reverse substring match** — for every lowercase
         compound name in ``lookup``, check whether it appears as a
         word-bounded substring of the claim text (also lowercased).
         This bypasses the "is the second word capitalised?" /
         "Citric acid" edge cases that doomed pure regex extraction.
      4. Title-Case + acronym fallback regex — only used when the
         lookup is empty or absent (defensive; should be rare).

    Names returned are deduplicated case-insensitively, preserving the
    order they were first observed.
    """
    names: list[str] = []
    text = claim.claim_text or ""

    # 1. Typed candidate_name win.
    typed = claim.extracted_fields.candidate_name
    if typed:
        names.append(typed.strip())

    # 2. Database IDs.
    for m in _KEGG_RE.finditer(text):
        names.append(m.group(1))
    for m in _HMDB_RE.finditer(text):
        names.append(m.group(1))
    for m in _INCHIKEY_BLOCK_RE.finditer(text):
        names.append(m.group(1))

    # 3. Lookup reverse substring match.
    if lookup:
        text_lower = text.lower()
        # Sort by descending length so "pyruvic acid" matches before "pyruv".
        sorted_keys = sorted(lookup.keys(), key=len, reverse=True)
        for key in sorted_keys:
            if not key or len(key) < 4:
                continue
            if _word_bounded_in(key, text_lower):
                names.append(key)

    # 4. Title-case / acronym regex — always run, so unresolvable
    # compound-shaped tokens still surface in ``unresolved_drivers``
    # for the verifier's audit trail. Tokens that already matched via
    # lookup pass through dedup harmlessly.
    names.extend(_extract_title_tokens(text))

    # Dedupe preserving order, lowercase-insensitive.
    seen: set[str] = set()
    unique: list[str] = []
    for n in names:
        n_norm = n.strip()
        if not n_norm:
            continue
        n_lower = n_norm.lower()
        if n_lower in seen:
            continue
        seen.add(n_lower)
        unique.append(n_norm)
    return unique


def _word_bounded_in(needle: str, haystack: str) -> bool:
    """Return True iff ``needle`` appears in ``haystack`` with word
    boundaries on both ends. Both inputs assumed lowercased."""
    if not needle or not haystack:
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


_TITLE_TOKEN_STOPWORDS = frozenset({
    # English connectives + verbs that we never want as compound candidates.
    "the", "and", "are", "is", "in", "of", "for", "to", "from", "with",
    "this", "that", "these", "those", "their", "its", "be", "been", "by",
    # Driver-keyword surface forms (lowercase) that the regex below
    # mostly avoids anyway because they're not Title Case in normal
    # narrative. Listed defensively.
    "key", "main", "primary", "primarily", "principal",
    "drive", "driver", "drivers", "driven", "driving",
    "marker", "markers", "metabolite", "metabolites", "compound",
    "compounds", "contributor", "contributors", "central", "linking",
    "pathway", "pathways", "enrichment", "signal",
})
_PATHWAY_SUFFIX_WORDS = frozenset({
    "metabolism", "biosynthesis", "degradation", "catabolism", "anabolism",
    "synthesis", "cycle", "inhibition", "production",
    "pathway", "pathways", "signaling", "signalling", "disease", "syndrome",
})


def _extract_title_tokens(text: str) -> list[str]:
    """Extract compound-name candidates from claim text.

    Two complementary patterns:
    1. **Title Case** runs of 1–3 words, e.g. "Tyrosine", "Citric acid".
    2. **All-caps acronyms** of length ≥3, e.g. "DOPA", "GABA", "NAD".

    Tokens are dropped when:
    * Pure stopword (all words in ``_TITLE_TOKEN_STOPWORDS``)
    * Followed in the claim text by a pathway-suffix word
      (so "Tyrosine metabolism" is treated as a pathway, not a driver)
    * Single-word title tokens with length < 4 (too risky)
    """
    out: list[str] = []

    title_re = re.compile(r"\b([A-Z][a-z]+(?:[- ][A-Z]?[a-z]+){0,2})\b")
    acronym_re = re.compile(r"\b([A-Z]{3,8})\b")

    seen_spans: list[tuple[int, int]] = []

    def _followed_by_pathway_suffix(end: int) -> bool:
        tail = text[end:end + 40].strip()
        if not tail:
            return False
        # Take first word after the candidate, lowercased.
        next_word = tail.split()[0].rstrip(",.;:").lower()
        return next_word in _PATHWAY_SUFFIX_WORDS

    for m in title_re.finditer(text):
        phrase = m.group(1).strip()
        # Strip trailing stopword tokens that the regex inadvertently
        # captured because a 'second word' was permitted to be lowercase
        # (e.g. "Tyrosine and" → "Tyrosine"). Compound names like
        # "Citric acid" survive because "acid" is not in stopwords.
        words = phrase.split()
        while words and words[-1].lower() in _TITLE_TOKEN_STOPWORDS:
            words.pop()
        phrase = " ".join(words)
        if not phrase:
            continue
        # Recompute end based on stripped phrase length to keep
        # _followed_by_pathway_suffix accurate.
        end_after_strip = m.start() + len(phrase)
        if _followed_by_pathway_suffix(end_after_strip):
            continue
        if all(w.lower() in _TITLE_TOKEN_STOPWORDS for w in phrase.split()):
            continue
        if " " not in phrase and "-" not in phrase and len(phrase) < 4:
            continue
        out.append(phrase)
        seen_spans.append((m.start(), end_after_strip))

    for m in acronym_re.finditer(text):
        token = m.group(1).strip()
        # Skip if this acronym is actually a 14-letter InChIKey block —
        # the InChIKey regex picks those up earlier.
        if len(token) == 14:
            continue
        # Skip if followed by a pathway-suffix word.
        if _followed_by_pathway_suffix(m.end()):
            continue
        # Skip if already covered by a Title-Case match (shouldn't happen
        # for pure all-caps tokens but defensive).
        if any(s <= m.start() < e for s, e in seen_spans):
            continue
        out.append(token)

    return out


def _resolve_to_inchikey_block(
    name: str, lookup: dict[str, str]
) -> str | None:
    """Map a single claimed name / ID to an InChIKey first-block."""
    key = name.strip().lower()
    if key in lookup:
        return lookup[key]

    # If the input itself is already a 14-letter all-caps token, accept
    # as-is so test fixtures can pass InChIKey blocks directly without
    # round-tripping through the curated pool.
    if _INCHIKEY_BLOCK_RE.fullmatch(name.strip()):
        return name.strip()

    return None


def _resolve_kegg_set(
    kegg_ids: list[str], lookup: dict[str, str]
) -> set[str]:
    """Map a list of KEGG IDs to a set of InChIKey first-blocks. Drops
    KEGG IDs that don't resolve (logged once at WARNING)."""
    out: set[str] = set()
    missed: list[str] = []
    for kid in kegg_ids:
        ik = lookup.get(kid.strip().lower())
        if ik:
            out.add(ik)
        else:
            missed.append(kid)
    if missed:
        logger.debug(
            "driver_metabolite: %d KEGG ids did not resolve via lookup: %s",
            len(missed), missed,
        )
    return out


def _unverifiable(
    claim: ClassifiedClaim,
    *,
    evidence: str,
    ctx: EnrichmentContext,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.DRIVER_METABOLITE,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        extracted_fields=claim.extracted_fields,
        verifier_layer="driver_metabolite",
        trace_summary="driver_metabolite unverifiable",
        enrichment_context=ctx,
    )
