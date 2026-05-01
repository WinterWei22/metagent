"""Stage 2 — classify each claim by which layer should verify it.

Two-pass design:

1. **Rule-based pass.** Regex patterns for database IDs, pathway / disease
   keywords, and chemical-property field references decide most claims
   without an LLM call. Per the Track V brief, rules are expected to handle
   80%+ of claims.

2. **LLM fallback (single batched call).** Claims that no rule matched are
   collected and shipped in one call, using a line-delimited
   ``<index>: <type>`` format so a single malformed line only affects one
   claim instead of the whole batch.

The classifier returns ``ClassifiedClaim`` with ``classifier_source`` set
to ``"rule"`` / ``"llm"`` / ``"fallback"`` (the last is a defensive default
when neither rule nor LLM produced a classification — logged for analysis).

Note: ``CONSISTENCY`` claims are not assigned by Stage 2. Layer D performs
a global consistency sweep over the full classified-claim set and emits
``CONSISTENCY``-typed ``VerifiedClaim`` entries on top of the per-claim
verdicts from layers A/B/C. This keeps Stage 2's job to a single primary
type per claim.
"""
from __future__ import annotations

import re
from typing import Literal

from common.llm_client import chat
from verifier.claim_fields import infer_claim_subtype, normalize_claim_text, parse_claim_fields
from verifier.prompts import classify_ambiguous as prompts
from verifier.schemas import ClaimType, ClassifiedClaim, ExtractedClaim


CALLER = "verifier.stage2.classify_ambiguous"


# ---------------------------------------------------------------------------
# Rule patterns
# ---------------------------------------------------------------------------

# Pathway / metabolism / disease keywords → BIOLOGICAL
_PATHWAY_KEYWORDS = re.compile(
    r"\b("
    r"pathway|pathways|metabolism|metabolic|biosynthesis|degradation|"
    r"disease|diseases|syndrome|syndromes|disorder|disorders|"
    r"galactosemia|signal[l]?ing|cycle|"
    r"neighbour|neighbor|neighbours|neighbors|"
    r"biological\s+matrix|biological\s+context|biofluid|tissue"
    r")\b",
    re.IGNORECASE,
)

# Pathway-shaped IDs (KEGG map, SMPDB, Reactome) → BIOLOGICAL
_PATHWAY_ID_RE = re.compile(
    r"\b("
    r"map\d{5}|hsa\d{5}|R-HSA-\d+|SMP\d+|WP\d+"
    r")\b",
    re.IGNORECASE,
)

# Literature claims (PMID / DOI / pubmed) → LITERATURE
_LITERATURE_RE = re.compile(
    r"\b(?:PMID|pubmed|doi)[:\s]*\S",
    re.IGNORECASE,
)
# Bare DOI form (10.NNNN/...) without an anchor — common in LLM output
_BARE_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


# Source-report field references → GROUNDED
_GROUNDED_KEYWORDS = re.compile(
    r"\b("
    r"evidence[\s_]?score|cosine|cosine\s+similarity|"
    r"score:|B/C|"
    r"ppm|mass[\s_]?accuracy|mass[\s_]?match|exact[\s_]?mass|"
    r"neutral[\s_]?mass|precursor|"
    r"molecular[\s_]?formula|formula|"
    r"peak[\s_]?count|adduct|m/z|"
    r"smiles|chemical[\s_]?class|"
    r"hit[\s_]?count|hit[s]?\b"
    r")\b",
    re.IGNORECASE,
)

# Bare empirical-formula match (e.g. C6H12O6, C8H10N4O2) → GROUNDED
_FORMULA_RE = re.compile(
    r"\bC\d{1,3}H\d{1,3}(?:[A-Z][a-z]?\d{0,3})*\b"
)

# Compound database IDs → FACTUAL (when no pathway / grounded keyword wins)
_COMPOUND_ID_RE = re.compile(
    r"\b("
    r"HMDB\d{6,}|"
    r"CHEBI[:_-]?\d+|"
    r"CID[:_-]?\d+|"
    r"CCMSLIB\d+|"
    r"C\d{5}\b|"  # KEGG compound (C followed by exactly 5 digits)
    r"[A-Z]{14}-[A-Z]{10}-[A-Z]"  # InChIKey
    r")\b",
    re.IGNORECASE,
)

_PEAK_MZ_RE = re.compile(r"\bm/z\s*=?\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)

_PEAK_MECHANISTIC_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"neutral\s+loss\s+of",
        r"\[M[+-]H[+-][^\]]+\]",
        r"fragment(?:ation)?(?:\s+ion)?",
        r"\bpeak\s+at\b",
        r"\bloss\s+of\s+\w+",
        r"ring\s+cleavage",
        r"bond\s+scission",
        r"\barises\s+from\b",
    )
]

_NEUTRAL_LOSS_ALIASES = (
    "H2O", "H₂O", "water", "NH3", "ammonia", "CO2", "CO₂",
    "carbon dioxide", "CO", "carbon monoxide", "CH3", "methyl",
    "HCl", "hydrogen chloride", "HF", "hydrogen fluoride",
)


# ---------------------------------------------------------------------------
# Sub-6 enrichment-claim patterns (Type 6a / 6b / 6d)
# ---------------------------------------------------------------------------

# 6a — SET_ENRICHMENT: claims about a *set* of compounds being enriched in /
# pointing to / dominating a pathway. Two clusters of phrasing:
#
#   (i)  Explicit enrichment vocabulary
#         "X is/are enriched in Y" / "fold-enrichment" / "FDR < ..." /
#         "pathway analysis identified Y" / "top pathway" / "most enriched"
#   (ii) Collective subject + pathway-as-predicate (Day 3 §4 P1 fix —
#         Sub-6 baseline LLM rarely uses "enriched in" verbatim; instead
#         emits "the dominant pathway affected is X" or "the metabolites
#         suggest disruption of Y"):
#         "(the) dominant / primary / most affected (metabolic) pathway"
#         "(the) dominant theme is ..."
#         "the (differential) metabolites / data / profile / signal
#          [+ collective-subject phrases] suggests / indicates / points to /
#          reflects ... <pathway-y predicate>"
#
# pathway_membership style ("dCMP is in pyrimidine metabolism") is
# **deliberately not** caught here — that lives in BIOLOGICAL (Layer 6c
# pathway_membership subtype). Subject-grammar cut: collective set →
# SET_ENRICHMENT, single compound → BIOLOGICAL (eval guide pitfall #1).
_SET_ENRICHMENT_RE = re.compile(
    r"("
    # (i) explicit enrichment vocab
    r"\b(?:are|is|were|was)\s+(?:significantly\s+|strongly\s+)?enriched\s+in\b"
    r"|\benrichment\s+(?:was\s+detected|analysis|in|for)\b"
    r"|\bpathway\s+analysis\s+(?:identified|revealed|returned|highlighted|suggests?)\b"
    r"|\b(?:top|most\s+(?:likely|enriched))\s+pathway\b"
    r"|\b(?:show|shows|showed|exhibit|exhibits|exhibited)\s+(?:strong\s+)?enrichment\b"
    r"|\bFDR\s*[<>]?\s*0?\.\d"
    r"|\bfold[-\s]enrichment\b"
    # (ii-a) "(the) dominant / primary / main / most affected pathway"
    r"|\b(?:dominant|primary|main|principal|most\s+(?:affected|likely\s+affected)|"
    r"most\s+strongly\s+(?:implicated|affected))\s+(?:metabolic\s+)?pathway\b"
    # (ii-b) "(pathway) is the dominant pathway affected" — pathway as subject
    r"|\bis\s+the\s+(?:dominant|primary|main|principal|most\s+affected)\s+pathway\b"
    # (ii-c) "the dominant theme / signal / pattern / pathway is ..."
    r"|\b(?:the\s+)?dominant\s+theme\s+is\b"
    # (ii-d) collective-subject + pathway-y predicate. The leading anchor
    # is "(the )?<collective subject>" appearing AT START of the claim,
    # optionally followed by a short prepositional phrase
    # ("in pyrimidine metabolites" — see "coordinated changes in X
    # metabolites suggest Y"), then an
    # "implicates/suggests/indicates/points to" verb. The intervening
    # phrase is bounded to ≤ 6 tokens to avoid runaway matches.
    r"|^\s*(?:the\s+)?(?:differential\s+)?(?:metabolites?|data|profile|signal|"
    r"results?|set|combination|coordinated\s+changes?)\b"
    r"(?:\s+\w[\w-]*){0,6}\s+"
    r"(?:strongly\s+|primarily\s+|collectively\s+)?"
    r"(?:suggests?|indicates?|imply|implies|implicate[ds]?|"
    r"points?\s+to|reflects?|are\s+consistent\s+with|"
    r"(?:cluster|converge)\s+(?:in|into|on))\b"
    # (ii-e) "differential abundance in these metabolites suggests ..."
    r"|\bdifferential\s+abundance\s+in\s+these\s+(?:metabolites|compounds)\s+"
    r"(?:suggests?|indicates?)\b"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

# 6b — DRIVER_METABOLITE: "X is/are key driver(s) of Y" / "X drive(s) the
# pathway" / "X is the central metabolite". Keyword-led so we don't
# accidentally capture pathway-membership claims.
_DRIVER_RE = re.compile(
    r"\b("
    r"key\s+(?:driver|drivers|metabolite|contributor|marker)s?"
    r"|main\s+(?:driver|contributor|marker)s?"
    r"|principal\s+marker"
    r"|primarily\s+driven\s+by"
    r"|driv(?:e|es|en|ing)\s+(?:the\s+)?"
    r"(?:pathway|enrichment|signal|response)"
    r"|(?:are|is)\s+the\s+(?:central|principal|primary)\s+"
    r"(?:metabolite|driver|contributor|marker)s?"
    r"|are\s+the\s+(?:main|principal|primary)\s+contributors"
    r")\b",
    re.IGNORECASE,
)

# 6d — PATHWAY_RELATIONSHIP: directional or shared-content between two
# pathways. Most specific; runs before generic BIOLOGICAL.
_RELATIONSHIP_RE = re.compile(
    r"\b("
    r"cross[-\s]?talk"
    r"|share[ds]?\s+\w*\s*(?:intermediates?|metabolites?|compounds?)"
    r"|share\s+a\s+common\s+intermediate"
    r"|common\s+intermediate"
    r"|converge[s]?\s+on"
    r"|(?:is|are)\s+upstream\s+of"
    r"|(?:is|are)\s+downstream\s+of"
    r"|feeds?\s+into"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def classify_claims(
    claims: list[ExtractedClaim], *, trace_id: str
) -> tuple[list[ClassifiedClaim], int]:
    """Classify each claim. Returns ``(classified, llm_calls_used)``.

    ``llm_calls_used`` is 0 when every claim was decided by rules, 1 when
    the batched LLM fallback was needed.
    """
    if not claims:
        return [], 0

    decisions: list[ClaimType | None] = []
    sources: list[Literal["rule", "llm", "fallback"]] = []
    ambiguous_indices: list[int] = []

    for i, c in enumerate(claims):
        decided = _rule_classify(c.claim_text)
        decisions.append(decided)
        if decided is None:
            ambiguous_indices.append(i)
            sources.append("fallback")  # may be overwritten by LLM
        else:
            sources.append("rule")

    llm_calls = 0
    if ambiguous_indices:
        llm_decisions = _llm_classify(
            [claims[i].claim_text for i in ambiguous_indices],
            trace_id=trace_id,
        )
        llm_calls = 1
        for offset, idx in enumerate(ambiguous_indices):
            if offset < len(llm_decisions) and llm_decisions[offset] is not None:
                decisions[idx] = llm_decisions[offset]
                sources[idx] = "llm"
            # else: leave as None / "fallback" — caller will see this and
            # default-route in the layer dispatch.

    classified: list[ClassifiedClaim] = []
    for i, c in enumerate(claims):
        ct = decisions[i] if decisions[i] is not None else ClaimType.GROUNDED
        fields = c.extracted_fields
        if fields == type(fields)():
            fields = parse_claim_fields(c.claim_text)
        peak_mz = c.peak_mz if c.peak_mz is not None else fields.mz
        neutral_loss = c.neutral_loss if c.neutral_loss is not None else fields.neutral_loss
        subtype = (
            c.claim_subtype
            if c.claim_subtype.value != "unknown"
            else infer_claim_subtype(c.claim_text, fields, ct)
        )
        classified.append(
            ClassifiedClaim(
                claim_id=c.claim_id,
                claim_text=c.claim_text,
                normalized_text=c.normalized_text or normalize_claim_text(c.claim_text),
                subject=c.subject,
                claim_type=ct,
                classifier_source=sources[i],
                peak_mz=peak_mz,
                neutral_loss=neutral_loss,
                claim_subtype=subtype,
                subject_kind=c.subject_kind,
                extracted_fields=fields,
                provenance=c.provenance.model_copy(
                    update={"classifier_source": sources[i]}
                ),
            )
        )
    return classified, llm_calls


# ---------------------------------------------------------------------------
# Rule logic
# ---------------------------------------------------------------------------


def _rule_classify(claim_text: str) -> ClaimType | None:
    """Apply the precedence rules. Return None when no rule matches.

    Literature is checked FIRST — a claim like "Caffeine has PMID 12345"
    contains a compound name AND a citation, but the citation is the
    load-bearing assertion (the verifier asks "does this PMID exist?",
    not "does Caffeine exist?").

    Sub-6 enrichment patterns (PATHWAY_RELATIONSHIP, DRIVER_METABOLITE,
    SET_ENRICHMENT) are checked BEFORE generic BIOLOGICAL because
    "X metabolism shares intermediates with Y" matches both
    ``_PATHWAY_KEYWORDS`` and ``_RELATIONSHIP_RE`` — but the relationship
    is the load-bearing assertion. Order: most specific → least.
    """
    if _LITERATURE_RE.search(claim_text) or _BARE_DOI_RE.search(claim_text):
        return ClaimType.LITERATURE
    if _is_peak_mechanistic_claim(claim_text):
        return ClaimType.PEAK_MECHANISTIC
    # Sub-6 enrichment claim types — checked before BIOLOGICAL because
    # they share the pathway / metabolism vocabulary.
    if _RELATIONSHIP_RE.search(claim_text):
        return ClaimType.PATHWAY_RELATIONSHIP
    if _DRIVER_RE.search(claim_text):
        return ClaimType.DRIVER_METABOLITE
    if _SET_ENRICHMENT_RE.search(claim_text):
        return ClaimType.SET_ENRICHMENT
    if _PATHWAY_KEYWORDS.search(claim_text) or _PATHWAY_ID_RE.search(claim_text):
        return ClaimType.BIOLOGICAL
    if _GROUNDED_KEYWORDS.search(claim_text) or _FORMULA_RE.search(claim_text):
        return ClaimType.GROUNDED
    if _COMPOUND_ID_RE.search(claim_text):
        return ClaimType.FACTUAL
    return None


def _extract_peak_mz(claim_text: str) -> float | None:
    m = _PEAK_MZ_RE.search(claim_text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:  # pragma: no cover - regex should guarantee float-ish
        return None


def _is_peak_mechanistic_claim(claim_text: str) -> bool:
    if _extract_peak_mz(claim_text) is None:
        return False
    return any(p.search(claim_text) for p in _PEAK_MECHANISTIC_PATTERNS)


def _extract_neutral_loss(claim_text: str) -> str | None:
    text = claim_text.lower()
    for alias in sorted(_NEUTRAL_LOSS_ALIASES, key=len, reverse=True):
        if alias.lower() in text:
            return alias
    patterns = (
        r"neutral\s+loss\s+of\s+([A-Za-z0-9₂₃₄.+-]+(?:\s+[A-Za-z]+)?)",
        r"loss\s+of\s+([A-Za-z0-9₂₃₄.+-]+(?:\s+[A-Za-z]+)?)",
    )
    for pattern in patterns:
        m = re.search(pattern, claim_text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip(" .,:;")
    return None


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------


def _llm_classify(
    ambiguous_texts: list[str], *, trace_id: str
) -> list[ClaimType | None]:
    """Send all ambiguous claims in one batched call. Return per-claim type
    or None when the line could not be parsed.

    The line-delimited format is intentionally noise-tolerant: a single
    malformed line returns None for that index but does not invalidate the
    rest of the batch.
    """
    user_msg = prompts.build(ambiguous_texts)
    response = chat(
        messages=[
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        trace_id=trace_id,
        caller=CALLER,
    )

    decisions: list[ClaimType | None] = [None] * len(ambiguous_texts)
    for line in response.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        head, _, tail = line.partition(":")
        head, tail = head.strip(), tail.strip()
        if not head.isdigit():
            continue
        idx = int(head)
        if not (0 <= idx < len(ambiguous_texts)):
            continue
        ct = _parse_type(tail)
        if ct is not None:
            decisions[idx] = ct
    return decisions


_TYPE_LITERALS = {
    "grounded_claim": ClaimType.GROUNDED,
    "grounded": ClaimType.GROUNDED,
    "factual_roundtrip_claim": ClaimType.FACTUAL,
    "factual": ClaimType.FACTUAL,
    "biological_claim": ClaimType.BIOLOGICAL,
    "biological": ClaimType.BIOLOGICAL,
    "biological_significance": ClaimType.BIOLOGICAL,
    "consistency_claim": ClaimType.CONSISTENCY,
    "consistency": ClaimType.CONSISTENCY,
    "literature_claim": ClaimType.LITERATURE,
    "literature": ClaimType.LITERATURE,
    "peak_mechanistic_claim": ClaimType.PEAK_MECHANISTIC,
    "peak_mechanistic": ClaimType.PEAK_MECHANISTIC,
    # Sub-6 enrichment types
    "set_enrichment": ClaimType.SET_ENRICHMENT,
    "driver_metabolite": ClaimType.DRIVER_METABOLITE,
    "pathway_relationship": ClaimType.PATHWAY_RELATIONSHIP,
}


def _parse_type(token: str) -> ClaimType | None:
    return _TYPE_LITERALS.get(token.strip().lower())
