"""Acceptance tests against the three verbatim O1 naive-orchestrator outputs.

The raw strings below are copy-pasted from
``reports/orchestrator_naive_v0_delivery_2026-04-23.md`` §4, which itself
was copy-pasted from ``logs/llm_calls.jsonl`` ``response_cleaned``. They
are the *real data* Track V is designed against.

Strategy: the Stage 1 extractor needs an LLM, and we don't want each test
run to be sensitive to extraction randomness. So we hand-curate the
expected ``ExtractedClaim`` list for each output (sourced from delivery
§5 + direct inspection of the JSONL ``messages[1].content``), mock the
extractor to return them, and run the rest of the cascade for real
(layers A/B/C + D + rewriter) against each ``IdentificationReport``
fixture in ``conftest.py``.

The per-fixture assertions map 1:1 to the acceptance criteria in
``prompts/track_V_verifier.md`` (H1-H7 catches and tolerations).
"""
from __future__ import annotations

import json

from common import llm_client
from verifier.agent import verify
from verifier.schemas import ClaimType, ClaimVerdict


# ---------------------------------------------------------------------------
# Verbatim O1 outputs — DO NOT EDIT (these are the raw data)
# ---------------------------------------------------------------------------

O1_GLUCOSE = """\
## Identification Report

**Precursor:** [M+H]+ at m/z 181.0707 (neutral mass 180.0634 Da)
**Molecular Formula:** C₆H₁₂O₆ (hexose monosaccharide)

---

### Most Likely Candidate: D-Gulose (evidence_score: 0.771)

D-Gulose ranks highest by a narrow margin (0.771 vs 0.761). It is a C-3 epimer of glucose and appears in galactose-related metabolic pathways. The predicted spectral match (cosine 0.423) is the best among candidates, and its B/C score (0.860) is the highest in the list.

---

### Top Candidates

**1. D-Gulose (C₇H₁₄O₇)**
Score: 0.771 | Cosine: 0.423
Linked to galactose metabolism, galactosemia, and Fabry disease pathways. The pathway enrichment provides biological context supporting this identification.

**2. Glucose (C₆H₁₂O₆)**
Score: 0.761 | Cosine: 0.423
Identical predicted spectral similarity and formula. Glucose is a central metabolic hub, making it statistically probable in biological samples.

### Pathway Context
Gulose maps to galactose metabolism and galactosemia pathways (SMPDB/KEGG). Glucose connects to a broader range of metabolic contexts.
"""

O1_CAFFEINE = """\
## Metabolite Identification Report

### Summary
The experimental spectrum (m/z 195.0877 [M+H]+, neutral mass 194.0804 Da) matches molecular formula **C8H10N4O2**. The top five candidates are structural isomers within the imidazopyrimidine/purine-dione chemical class. **Caffeine** is the most likely identification based on the available evidence.

---

### 1. Caffeine (evidence_score: 0.785) — **Most Likely**

Caffeine ranks highest primarily due to its exceptional library candidate score (B/C = 0.975) and robust cross-referencing across HMDB, KEGG, and ChEBI. The mass accuracy is excellent (<1 ppm vs. HMDB reference). Critically, Caffeine is the only candidate with meaningful pathway context: it maps to caffeine metabolism pathways in SMPDB, KEGG (map00232), and Reactome.

### 2. Isocaffeine (evidence_score: 0.651)

A structural isomer of caffeine with identical molecular formula. It shows the highest predicted-spectrum cosine (0.439) among candidates, but lacks pathway associations and database cross-references.
"""

O1_LCARNITINE = """\
## Identification Report

### Most Likely Candidate
**2-[2-hydroxyethyl(methyl)amino]ethyl acetate** (CID:218057, C₇H₁₅NO₃) is the top candidate with an evidence score of 0.529. It demonstrates the highest predicted-spectrum cosine similarity (0.112) among the candidates and maintains a favorable candidate score (B/C: 0.737).

### Top 3 Candidates

1. **2-[2-hydroxyethyl(methyl)amino]ethyl acetate** — Contains a tertiary amine, an ester, and a hydroxyl group.

2. **3-[2-(dimethylamino)ethoxy]propanoic acid** (evidence_score: 0.499) — Also C₇H₁₅NO₃ with a zwitterionic potential.

3. **[dimethyl-(trimethylsilylamino)silyl]methane** (evidence_score: 0.499) — Contains silicon. This is an atypical organosilane unlikely to arise in biological samples.

### Limitations and Caveats
- **Silicon-containing candidate**: Candidate #2 is chemically implausible for most biological matrices.
"""


# ---------------------------------------------------------------------------
# Hand-curated expected extractions — the "source of truth" for what
# Stage 1 should surface. These track the delivery §5 observations and
# add supporting claims needed for downstream verification.
# ---------------------------------------------------------------------------


_GLUCOSE_V1_CLAIMS = [
    {"claim_text": "Spectrum molecular formula is C6H12O6",
     "subject": None},
    # H1 — the contradicted claim
    {"claim_text": "D-Gulose has molecular formula C7H14O7",
     "subject": "D-Gulose"},
    {"claim_text": "D-Gulose evidence_score is 0.771",
     "subject": "D-Gulose"},
    {"claim_text": "D-Gulose predicted-spectrum cosine is 0.423",
     "subject": "D-Gulose"},
    {"claim_text": "D-Gulose B/C score is 0.860",
     "subject": "D-Gulose"},
    # H3 — three pathway-names that the verifier must NOT flag
    {"claim_text": "D-Gulose appears in galactose metabolism",
     "subject": "D-Gulose"},
    {"claim_text": "D-Gulose appears in galactosemia",
     "subject": "D-Gulose"},
    {"claim_text": "D-Gulose appears in Fabry disease pathway",
     "subject": "D-Gulose"},
    {"claim_text": "Glucose has molecular formula C6H12O6",
     "subject": "Glucose"},
    {"claim_text": "Glucose evidence_score is 0.761",
     "subject": "Glucose"},
]

_GLUCOSE_V2_CLAIMS = [
    # After rewrite, D-Gulose formula is corrected to C6H12O6
    {"claim_text": "Spectrum molecular formula is C6H12O6", "subject": None},
    {"claim_text": "D-Gulose has molecular formula C6H12O6", "subject": "D-Gulose"},
    {"claim_text": "D-Gulose evidence_score is 0.771", "subject": "D-Gulose"},
    {"claim_text": "D-Gulose predicted-spectrum cosine is 0.423", "subject": "D-Gulose"},
    {"claim_text": "D-Gulose B/C score is 0.860", "subject": "D-Gulose"},
    {"claim_text": "D-Gulose appears in galactose metabolism", "subject": "D-Gulose"},
    {"claim_text": "D-Gulose appears in galactosemia", "subject": "D-Gulose"},
    {"claim_text": "D-Gulose appears in Fabry disease pathway", "subject": "D-Gulose"},
    {"claim_text": "Glucose has molecular formula C6H12O6", "subject": "Glucose"},
    {"claim_text": "Glucose evidence_score is 0.761", "subject": "Glucose"},
]

_CAFFEINE_V1_CLAIMS = [
    {"claim_text": "Spectrum molecular formula is C8H10N4O2", "subject": None},
    {"claim_text": "Caffeine evidence_score is 0.785", "subject": "Caffeine"},
    {"claim_text": "Caffeine has B/C score 0.975", "subject": "Caffeine"},
    # H2 — the ppm-scalar hallucination
    {"claim_text": "The mass accuracy is below 1 ppm vs HMDB reference",
     "subject": None},
    # H4 — KEGG pathway ID that the verifier must NOT flag
    {"claim_text": "Caffeine maps to KEGG pathway map00232",
     "subject": "Caffeine"},
    {"claim_text": "Caffeine appears in caffeine metabolism pathway",
     "subject": "Caffeine"},
    # H5 — synonym / isomer naming — pipeline already emits Isocaffeine
    {"claim_text": "Isocaffeine is a structural isomer of caffeine",
     "subject": "Isocaffeine"},
    {"claim_text": "Isocaffeine evidence_score is 0.651",
     "subject": "Isocaffeine"},
    {"claim_text": "Isocaffeine predicted-spectrum cosine is 0.439",
     "subject": "Isocaffeine"},
]

_LCARNITINE_V1_CLAIMS = [
    # H6 — verifier verifies what was said, not what should have been said.
    # The LLM honestly reported the pipeline's top candidate.
    {"claim_text": "2-[2-hydroxyethyl(methyl)amino]ethyl acetate has CID:218057",
     "subject": "2-[2-hydroxyethyl(methyl)amino]ethyl acetate"},
    {"claim_text": "2-[2-hydroxyethyl(methyl)amino]ethyl acetate has molecular formula C7H15NO3",
     "subject": "2-[2-hydroxyethyl(methyl)amino]ethyl acetate"},
    {"claim_text": "2-[2-hydroxyethyl(methyl)amino]ethyl acetate evidence_score is 0.529",
     "subject": "2-[2-hydroxyethyl(methyl)amino]ethyl acetate"},
    {"claim_text": "Predicted-spectrum cosine is 0.112",
     "subject": "2-[2-hydroxyethyl(methyl)amino]ethyl acetate"},
    {"claim_text": "3-[2-(dimethylamino)ethoxy]propanoic acid evidence_score is 0.499",
     "subject": "3-[2-(dimethylamino)ethoxy]propanoic acid"},
    # H7 — chemistry-knowledge claim must not be flagged CONTRADICTED
    {"claim_text": "The silicon-containing candidate is chemically "
                   "implausible for most biological matrices",
     "subject": "[dimethyl-(trimethylsilylamino)silyl]methane"},
]


# ---------------------------------------------------------------------------
# Helpers to build canonical mock sequences
# ---------------------------------------------------------------------------


def _no_rewrite_mock_sequence(v1_claims):
    """Return the minimal mock sequence for a cascade that finds nothing
    actionable in v1 and short-circuits Stage 4."""
    return [
        json.dumps(v1_claims),   # Stage 1 v1
        "[]",                    # Stage 3 Layer D v1 — no contradictions
    ]


def _rewrite_cycle_mock_sequence(
    v1_claims, v2_claims, rewritten_text, *, consistency_v1=None,
):
    """Full mock sequence for a cascade that does one rewrite cycle."""
    return [
        json.dumps(v1_claims),              # Stage 1 v1
        consistency_v1 or "[]",             # Stage 3 Layer D v1
        rewritten_text,                     # Stage 4 rewrite
        json.dumps(v2_claims),              # Stage 1 v2
        "[]",                               # Stage 3 Layer D v2
    ]


# ---------------------------------------------------------------------------
# Glucose fixture — H1 and H3
# ---------------------------------------------------------------------------


def test_glucose_catches_H1_D_gulose_formula_contradiction(glucose_report):
    """Layer A must flag 'D-Gulose (C7H14O7)' as CONTRADICTED with
    correction = 'C6H12O6'."""
    rewritten = (
        O1_GLUCOSE.replace("C₇H₁₄O₇", "C6H12O6")
    )
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _GLUCOSE_V1_CLAIMS, _GLUCOSE_V2_CLAIMS, rewritten,
    ))
    result = verify(O1_GLUCOSE, glucose_report,
                    trace_id="o1-part4-glucose_pos_verified")

    h1 = next(c for c in result.claims_v1
              if "D-Gulose" in c.claim_text and "C7H14O7" in c.claim_text)
    assert h1.verdict == ClaimVerdict.CONTRADICTED
    assert h1.correction == "C6H12O6"
    assert h1.source_field == (
        "candidates[0].metabolite_info.molecular_formula"
    )


def test_glucose_catches_H1_intra_document_inconsistency(glucose_report):
    """Layer D must also surface the H1 contradiction as an intra-document
    mismatch between claim [0] (spectrum C6H12O6) and claim [1] (D-Gulose
    C7H14O7). This is the redundant catch per the Track V brief."""
    rewritten = (
        O1_GLUCOSE.replace("C₇H₁₄O₇", "C6H12O6")
    )
    # Mock: Layer D flags indices [0, 1] as contradicting
    consistency_v1 = json.dumps([{
        "claim_indices": [0, 1],
        "reason": ("Header asserts spectrum molecular formula is C6H12O6 but "
                   "D-Gulose is given C7H14O7, which is incompatible."),
    }])
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _GLUCOSE_V1_CLAIMS, _GLUCOSE_V2_CLAIMS, rewritten,
        consistency_v1=consistency_v1,
    ))
    result = verify(O1_GLUCOSE, glucose_report, trace_id="t-glucose-layerD")

    consistency_claims = [c for c in result.claims_v1
                          if c.claim_type == ClaimType.CONSISTENCY]
    assert len(consistency_claims) == 1
    assert consistency_claims[0].verdict == ClaimVerdict.CONTRADICTED


def test_glucose_does_not_flag_H3_pathway_names(glucose_report):
    """galactose metabolism, galactosemia, Fabry disease — all must
    verify as SUPPORTED via Layer C."""
    rewritten = (
        O1_GLUCOSE.replace("C₇H₁₄O₇", "C6H12O6")
    )
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _GLUCOSE_V1_CLAIMS, _GLUCOSE_V2_CLAIMS, rewritten,
    ))
    result = verify(O1_GLUCOSE, glucose_report, trace_id="t-glucose-H3")

    pathway_claims = [c for c in result.claims_v1
                      if c.claim_type == ClaimType.BIOLOGICAL]
    assert len(pathway_claims) == 3
    for c in pathway_claims:
        assert c.verdict == ClaimVerdict.SUPPORTED, (
            f"Expected SUPPORTED for {c.claim_text!r}; got {c.verdict}"
        )


# ---------------------------------------------------------------------------
# Caffeine fixture — H2, H4, H5
# ---------------------------------------------------------------------------


def test_caffeine_catches_H2_ppm_hallucination(caffeine_report):
    """'The mass accuracy is below 1 ppm vs HMDB reference' MUST be
    UNSUPPORTED — pipeline emits only binary mass_match_indicator, no
    scalar ppm."""
    # Stage 4 will fire because H2 is UNSUPPORTED. The rewritten text
    # drops the ppm claim; v2 extracts the surviving claims.
    rewritten_caffeine = (
        O1_CAFFEINE.replace("The mass accuracy is excellent (<1 ppm vs. HMDB reference). ", "")
    )
    v2_claims = [c for c in _CAFFEINE_V1_CLAIMS if "ppm" not in c["claim_text"]]
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _CAFFEINE_V1_CLAIMS, v2_claims, rewritten_caffeine,
    ))
    result = verify(O1_CAFFEINE, caffeine_report,
                    trace_id="o1-part4-caffeine_pos_verified")

    h2 = next(c for c in result.claims_v1 if "ppm" in c.claim_text)
    assert h2.verdict == ClaimVerdict.UNSUPPORTED


def test_caffeine_does_not_flag_H4_kegg_id_passthrough(caffeine_report):
    """'KEGG (map00232)' is in source_report — must be SUPPORTED."""
    rewritten_caffeine = (
        O1_CAFFEINE.replace("The mass accuracy is excellent (<1 ppm vs. HMDB reference). ", "")
    )
    v2_claims = [c for c in _CAFFEINE_V1_CLAIMS if "ppm" not in c["claim_text"]]
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _CAFFEINE_V1_CLAIMS, v2_claims, rewritten_caffeine,
    ))
    result = verify(O1_CAFFEINE, caffeine_report, trace_id="t-caffeine-H4")

    h4 = next(c for c in result.claims_v1 if "map00232" in c.claim_text)
    assert h4.verdict == ClaimVerdict.SUPPORTED


def test_caffeine_tolerates_H5_synonym_drift(caffeine_report):
    """Per direct inspection of the glucose_pos JSONL, the pipeline
    already emits 'Isocaffeine' as the candidate-#2 name. No drift.
    Verifier must NOT return CONTRADICTED for this claim on this seed.
    Acceptable verdicts: SUPPORTED (direct source name match) or
    UNVERIFIABLE_V0; NEVER CONTRADICTED."""
    rewritten_caffeine = (
        O1_CAFFEINE.replace("The mass accuracy is excellent (<1 ppm vs. HMDB reference). ", "")
    )
    v2_claims = [c for c in _CAFFEINE_V1_CLAIMS if "ppm" not in c["claim_text"]]
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _CAFFEINE_V1_CLAIMS, v2_claims, rewritten_caffeine,
    ))
    result = verify(O1_CAFFEINE, caffeine_report, trace_id="t-caffeine-H5")

    h5_claims = [c for c in result.claims_v1
                 if "isocaffeine" in c.claim_text.lower()]
    assert len(h5_claims) >= 1
    for c in h5_claims:
        assert c.verdict != ClaimVerdict.CONTRADICTED, (
            f"H5 tolerance violated: {c.claim_text!r} -> {c.verdict}"
        )


# ---------------------------------------------------------------------------
# L-carnitine fixture — H6 and H7
# ---------------------------------------------------------------------------


def test_lcarnitine_respects_H6_honest_non_identification(lcarnitine_report):
    """Verifier must NOT invent L-carnitine into the output. Every claim
    in v1/v2 must be about entities the LLM actually named — the
    real pipeline top-1 (zwitter ester), the dimethylamino ester, or the
    silicon candidate."""
    # The L-carnitine output has one UNVERIFIABLE_V0 claim (H7), so
    # Stage 4 will fire. v2 drops or softens the silicon chemistry note.
    v2_claims = [c for c in _LCARNITINE_V1_CLAIMS
                 if "silicon" not in c["claim_text"].lower()]
    rewritten_lc = O1_LCARNITINE  # simplest: mock returns same text sans silicon
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _LCARNITINE_V1_CLAIMS, v2_claims, rewritten_lc,
    ))
    result = verify(O1_LCARNITINE, lcarnitine_report,
                    trace_id="o1-part4-lcarnitine_pos_verified")

    # The verifier must not have manufactured an L-carnitine claim.
    for c in result.claims_v1 + result.claims_v2:
        assert "l-carnitine" not in c.claim_text.lower(), (
            f"Verifier injected an L-carnitine claim: {c.claim_text}"
        )


def test_lcarnitine_does_not_flag_H7_silicon_warning(lcarnitine_report):
    """'Candidate is chemically implausible for most biological matrices'
    is correct chemistry, not a hallucination. Verifier must NOT return
    CONTRADICTED. Acceptable verdicts: UNSUPPORTED or UNVERIFIABLE_V0."""
    v2_claims = [c for c in _LCARNITINE_V1_CLAIMS
                 if "silicon" not in c["claim_text"].lower()]
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _LCARNITINE_V1_CLAIMS, v2_claims, O1_LCARNITINE,
    ))
    result = verify(O1_LCARNITINE, lcarnitine_report, trace_id="t-lcarn-H7")

    h7 = next(c for c in result.claims_v1
              if "chemically implausible" in c.claim_text)
    assert h7.verdict != ClaimVerdict.CONTRADICTED


# ---------------------------------------------------------------------------
# Cascade-wide budget and invariants
# ---------------------------------------------------------------------------


def test_cascade_llm_call_count_within_budget_glucose(glucose_report):
    rewritten = O1_GLUCOSE.replace("C₇H₁₄O₇", "C6H12O6")
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _GLUCOSE_V1_CLAIMS, _GLUCOSE_V2_CLAIMS, rewritten,
    ))
    result = verify(O1_GLUCOSE, glucose_report, trace_id="t-budget-glucose")
    assert result.llm_call_count <= 7


def test_cascade_skips_rewrite_when_all_v1_supported(caffeine_report):
    """A minimal fixture with only SUPPORTED v1 claims must skip Stage 4
    entirely. Budget drops to 2 (extract + consistency)."""
    # Caffeine-only claims, nothing hallucinated
    clean_v1 = [
        {"claim_text": "Caffeine maps to KEGG pathway map00232",
         "subject": "Caffeine"},
        {"claim_text": "Caffeine evidence_score is 0.785",
         "subject": "Caffeine"},
    ]
    llm_client.set_mock(_no_rewrite_mock_sequence(clean_v1))
    result = verify(
        "Caffeine maps to map00232. evidence_score 0.785.",
        caffeine_report,
        trace_id="t-noretry",
    )
    assert result.overall_verdict == "verified"
    assert result.rewritten_output == result.source_llm_output
    assert result.llm_call_count == 2


def test_rewriter_preserves_supported_and_removes_contradicted(glucose_report):
    """Rewriter MUST drop / replace C7H14O7 and keep pathway claims."""
    rewritten_body = (
        "## Identification Report\n"
        "**1. D-Gulose (C6H12O6)**\n"
        "Score: 0.771 | Cosine: 0.423\n"
        "Linked to galactose metabolism, galactosemia, Fabry disease pathways."
    )
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _GLUCOSE_V1_CLAIMS, _GLUCOSE_V2_CLAIMS, rewritten_body,
    ))
    result = verify(O1_GLUCOSE, glucose_report, trace_id="t-rewriter")

    assert "C7H14O7" not in result.rewritten_output
    assert "galactose metabolism" in result.rewritten_output.lower()
    # source verbatim preservation
    assert "C₇H₁₄O₇" in result.source_llm_output


def test_source_llm_output_never_mutated(glucose_report):
    rewritten = O1_GLUCOSE.replace("C₇H₁₄O₇", "C6H12O6")
    llm_client.set_mock(_rewrite_cycle_mock_sequence(
        _GLUCOSE_V1_CLAIMS, _GLUCOSE_V2_CLAIMS, rewritten,
    ))
    result = verify(O1_GLUCOSE, glucose_report, trace_id="t-verbatim")
    assert result.source_llm_output == O1_GLUCOSE
