"""End-to-end integration tests for the Track V verifier.

Makes REAL MiniMax calls. Gated on ``MINIMAX_API_KEY`` — skipped when the
key is not set. Each test runs ``verify()`` once on a cached O1 output
(glucose, caffeine, lcarnitine) against a synthetic
``IdentificationReport`` that mirrors the real pipeline's output for
that fixture. Per-test budget: ≤ 7 LLM calls (Stage 2 LLM-fallback can
fire in both v1 and v2 passes), costing approximately US$0.05 at
current MiniMax-M2.7 rates. Total budget for all three: ~US$0.15 and
~10–20 min wall-clock depending on backend latency.

Each test pins its raw-LLM log to a stable, fixture-named path under
``/tmp`` so a failed run can be inspected after pytest cleanup.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_SKIP_REASON = (
    "verifier end-to-end test requires both MINIMAX_API_KEY and the "
    "openai==0.28 package (the 'metagent-llm' conda env). Skipped when "
    "either is absent."
)


def _integration_unavailable() -> bool:
    if not os.environ.get("MINIMAX_API_KEY"):
        return True
    try:
        import openai  # noqa: F401 — import-availability probe only
    except ImportError:
        return True
    return False


# ---------------------------------------------------------------------------
# Glucose fixture — reproduces the O1 delivery's source report shape
# without depending on the full pipeline.
# ---------------------------------------------------------------------------


def _glucose_source_report():
    from schemas.common import Candidate, PathwayEntry, Spectrum
    from schemas.molecule import MetaboliteInfoResponse
    from schemas.pathway import PathwayContextResponse
    from schemas.report import CandidateReport, IdentificationReport

    spectrum = Spectrum(
        mz=[181.0707], intensity=[1.0],
        precursor_mz=181.0707, adduct="[M+H]+",
        ionization_mode="positive", collision_energy=20.0,
    )
    gulose_pathways = PathwayContextResponse(
        pathways=[
            PathwayEntry(id="SMP00525", name="Fabry disease",
                         source="smpdb", hit_count=1, url="X"),
            PathwayEntry(id="SMP00043", name="Galactose Metabolism",
                         source="smpdb", hit_count=1, url="X"),
            PathwayEntry(id="map00052", name="Galactose Metabolism",
                         source="kegg", hit_count=1, url="X"),
            PathwayEntry(id="SMP00182", name="Galactosemia",
                         source="smpdb", hit_count=1, url="X"),
        ],
        upstream_neighbours=[], downstream_neighbours=[],
        cooccurrence_score=0.0, plausibility_summary="X", explain="X",
    )
    gulose = CandidateReport(
        candidate=Candidate(
            smiles="OCC1OC(O)C(O)C(O)C1O", name="D-Gulose",
            source="library", score=0.860,
            source_id="MSBNK-MPI_for_Chemical_Ecology-CE000691",
            explain="library hit",
        ),
        prefilter_match=None,
        metabolite_info=MetaboliteInfoResponse(
            found=True, primary_name="D-Gulose",
            synonyms=["Gulose", "D-(+)-Gulose"],
            molecular_formula="C6H12O6", exact_mass=180.063388116,
            smiles="OCC1OC(O)C(O)C(O)C1O",
            inchikey="WQZGKKKJIJFFOK-VFUOTHLCSA-N",
            chemical_class="Organooxygen compounds",
            cross_refs={"hmdb": "HMDB0250761", "kegg": "C00738",
                        "pubchem_cid": "206"},
            source="hmdb", explain="hit",
        ),
        pathway_context=gulose_pathways,
        predicted_spectrum_cosine=0.423,
        predicted_model_version="cfm-id-4.4.7",
        mass_match_indicator=1.0, pathway_presence_indicator=1.0,
        evidence_score=0.771, notes=[],
    )
    glucose = CandidateReport(
        candidate=Candidate(
            smiles="C([C@@H]1[C@H]([C@@H]([C@H](C(O1)O)O)O)O)O",
            name="Glucose", source="library", score=0.835,
            source_id="CID:5793", explain="library hit",
        ),
        prefilter_match=None,
        metabolite_info=MetaboliteInfoResponse(
            found=True, primary_name="Glucose",
            synonyms=[], molecular_formula="C6H12O6",
            exact_mass=180.063388116,
            smiles="C([C@@H]1[C@H]([C@@H]([C@H](C(O1)O)O)O)O)O",
            inchikey=None,
            chemical_class="Organooxygen compounds",
            cross_refs={"hmdb": "HMDB0304632", "kegg": "C00031",
                        "chebi": "4167", "pubchem_cid": "5793"},
            source="hmdb", explain="hit",
        ),
        pathway_context=None,
        predicted_spectrum_cosine=0.423,
        predicted_model_version="cfm-id-4.4.7",
        mass_match_indicator=1.0, pathway_presence_indicator=0.0,
        evidence_score=0.761, notes=[],
    )
    return IdentificationReport(
        experimental_spectrum=spectrum,
        preprocess_quality_flag="sparse",
        neutral_mass_computed=180.063424,
        n_prefilter_candidates=206,
        n_library_candidates=10,
        n_generated_candidates=0,
        candidates=[gulose, glucose],
        pipeline_version="integration-day1:2bc192d",
        tool_versions={"cfm-id": "cfm-id-4.4.7"},
        warnings=[],
    )


# ---------------------------------------------------------------------------
# The verbatim glucose O1 output — copy of the response_cleaned field for
# trace_id=o1-part4-glucose_pos in logs/llm_calls.jsonl.
# ---------------------------------------------------------------------------


_O1_GLUCOSE_OUTPUT = """\
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


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_integration_unavailable(), reason=_SKIP_REASON)
def test_verify_glucose_end_to_end_real_llm(tmp_path):
    """Run the full verifier cascade against the glucose O1 output using
    live MiniMax. Asserts the minimum-viable guarantees:

    * Cascade completes (returns a ``VerifiedIdentification``).
    * Overall verdict is not "verified" on the first pass — the H1
      contradiction means either "contradicted" (rewriter could not
      eliminate it) or "partially_verified" (some UNSUPPORTED /
      UNVERIFIABLE_V0 survived) or "verified" (Stage 4 cleaned up).
    * ``llm_call_count`` is within the documented ceiling of 6.
    * ``source_llm_output`` is preserved verbatim.
    * At least one v1 claim is flagged CONTRADICTED (H1).
    """
    from common import llm_client
    from verifier.agent import verify
    from verifier.schemas import ClaimVerdict

    # Pin to a stable, inspectable location so a failed run can be
    # debugged after the fact. tmp_path is fine for unit tests but a
    # live-LLM failure is too expensive to lose to fixture cleanup.
    log_path = Path("/tmp/verifier_e2e_glucose_lastrun.jsonl")
    if log_path.exists():
        log_path.unlink()
    llm_client.set_log_path(log_path)

    result = verify(
        _O1_GLUCOSE_OUTPUT,
        _glucose_source_report(),
        trace_id="o1-part4-glucose_pos_verified_it",
    )

    # 1. Cascade completed.
    assert result is not None
    assert result.trace_id == "o1-part4-glucose_pos_verified_it"

    # 2. Verbatim source preservation.
    assert result.source_llm_output == _O1_GLUCOSE_OUTPUT

    # 3. Budget ceiling.
    assert result.llm_call_count <= 7, (
        f"Budget exceeded: {result.llm_call_count} LLM calls"
    )

    # Diagnostic dump — kept always-on because each run costs $0.05 and
    # silent failures leave no breadcrumb after pytest cleans up.
    print(f"\nllm_call_count = {result.llm_call_count}")
    print(f"overall_verdict = {result.overall_verdict}")
    print(f"warnings = {result.verification_warnings}")
    print(f"len(claims_v1) = {len(result.claims_v1)}")
    for c in result.claims_v1:
        print(f"  v1  {c.verdict.value:18s}  {c.claim_text[:90]}")
    print(f"len(claims_v2) = {len(result.claims_v2)}")
    print(f"raw response log: {log_path}")

    # 4. Overall verdict should not be "failed" (the cascade ran).
    assert result.overall_verdict != "failed", (
        f"Cascade failed: warnings = {result.verification_warnings}"
    )

    # 5. At least one CONTRADICTED v1 claim (H1 or consistency sweep).
    # NOTE: this assertion is the whole point of the integration test.
    # If it fails, the live LLM cascade did not catch H1. Inspect
    # /tmp/verifier_e2e_glucose_lastrun.jsonl to understand why — most
    # likely culprit is non-deterministic Stage 1 truncation (extractor
    # returned a fraction of the expected claim list).
    v1_contradicted = [
        c for c in result.claims_v1
        if c.verdict == ClaimVerdict.CONTRADICTED
    ]
    assert len(v1_contradicted) >= 1, (
        f"Expected at least one CONTRADICTED claim catching H1; "
        f"got claims_v1 = {[(c.verdict.value, c.claim_text) for c in result.claims_v1]}"
    )


# ---------------------------------------------------------------------------
# Caffeine fixture — H2 (ppm scalar), H4 (KEGG passthrough), H5 (Isocaffeine)
# ---------------------------------------------------------------------------


def _caffeine_source_report():
    from schemas.common import Candidate, PathwayEntry, Spectrum
    from schemas.molecule import MetaboliteInfoResponse
    from schemas.pathway import PathwayContextResponse
    from schemas.report import CandidateReport, IdentificationReport

    spectrum = Spectrum(
        mz=[195.0877], intensity=[1.0],
        precursor_mz=195.0877, adduct="[M+H]+",
        ionization_mode="positive", collision_energy=25.0,
    )
    caffeine = CandidateReport(
        candidate=Candidate(
            smiles="Cn1c(=O)c2c(ncn2C)n(C)c1=O", name="Caffeine",
            source="library", score=0.975,
            source_id="CCMSLIB00005884028", explain="library hit",
        ),
        prefilter_match=None,
        metabolite_info=MetaboliteInfoResponse(
            found=True, primary_name="Caffeine",
            synonyms=["1,3,7-trimethylxanthine",
                      "1,3,7-Trimethyl-1H-purine-2,6(3H,7H)-dione"],
            molecular_formula="C8H10N4O2", exact_mass=194.080375584,
            smiles="Cn1c(=O)c2c(ncn2C)n(C)c1=O",
            inchikey="RYYVLZVUVIJVGH-UHFFFAOYSA-N",
            chemical_class="Imidazopyrimidines",
            cross_refs={"hmdb": "HMDB0001847", "kegg": "C07481",
                        "chebi": "27732", "pubchem_cid": "2519"},
            source="hmdb", explain="hit",
        ),
        pathway_context=PathwayContextResponse(
            pathways=[
                PathwayEntry(id="SMP00028", name="Caffeine Metabolism",
                             source="smpdb", hit_count=1, url="X"),
                PathwayEntry(id="map00232", name="Caffeine Metabolism",
                             source="kegg", hit_count=1, url="X"),
            ],
            upstream_neighbours=[], downstream_neighbours=[],
            cooccurrence_score=0.0, plausibility_summary="X", explain="X",
        ),
        predicted_spectrum_cosine=0.316,
        predicted_model_version="cfm-id-4.4.7",
        mass_match_indicator=1.0, pathway_presence_indicator=1.0,
        evidence_score=0.785, notes=[],
    )
    isocaffeine = CandidateReport(
        candidate=Candidate(
            smiles="CN1C=NC2=C1N(C(=O)N(C2=O)C)C", name="Isocaffeine",
            source="library", score=0.797,
            source_id="CID:1326", explain="library hit",
        ),
        prefilter_match=None, metabolite_info=None, pathway_context=None,
        predicted_spectrum_cosine=0.439,
        predicted_model_version="cfm-id-4.4.7",
        mass_match_indicator=1.0, pathway_presence_indicator=0.0,
        evidence_score=0.651, notes=[],
    )
    isomer3 = CandidateReport(
        candidate=Candidate(
            smiles="CC1=NC2=C(N1)C(=O)N(C(=O)N2C)C",
            name="1,3,8-trimethyl-7H-purine-2,6-dione",
            source="library", score=0.790,
            source_id="CID:95030", explain="library hit",
        ),
        prefilter_match=None, metabolite_info=None, pathway_context=None,
        predicted_spectrum_cosine=0.338,
        predicted_model_version="cfm-id-4.4.7",
        mass_match_indicator=1.0, pathway_presence_indicator=0.0,
        evidence_score=0.617, notes=[],
    )
    return IdentificationReport(
        experimental_spectrum=spectrum,
        preprocess_quality_flag="sparse",
        neutral_mass_computed=194.0804,
        n_prefilter_candidates=512,
        n_library_candidates=10,
        n_generated_candidates=0,
        candidates=[caffeine, isocaffeine, isomer3],
        pipeline_version="integration-day1:2bc192d",
        tool_versions={"cfm-id": "cfm-id-4.4.7"},
        warnings=[],
    )


_O1_CAFFEINE_OUTPUT = """\
## Metabolite Identification Report

### Summary
The experimental spectrum (m/z 195.0877 [M+H]+, neutral mass 194.0804 Da) matches molecular formula **C8H10N4O2**. The top five candidates are structural isomers within the imidazopyrimidine/purine-dione chemical class. **Caffeine** is the most likely identification based on the available evidence.

---

### 1. Caffeine (evidence_score: 0.785) — **Most Likely**

Caffeine ranks highest primarily due to its exceptional library candidate score (B/C = 0.975) and robust cross-referencing across HMDB, KEGG, and ChEBI. The mass accuracy is excellent (<1 ppm vs. HMDB reference). Critically, Caffeine is the only candidate with meaningful pathway context: it maps to caffeine metabolism pathways in SMPDB, KEGG (map00232), and Reactome.

### 2. Isocaffeine (evidence_score: 0.651)

A structural isomer of caffeine with identical molecular formula. It shows the highest predicted-spectrum cosine (0.439) among candidates, but lacks pathway associations and database cross-references.
"""


@pytest.mark.skipif(_integration_unavailable(), reason=_SKIP_REASON)
def test_verify_caffeine_end_to_end_real_llm(tmp_path):
    """Live cascade against caffeine_pos. Asserts H2 catch (ppm scalar),
    H4 tolerance (KEGG passthrough), and H5 tolerance (Isocaffeine name
    appears verbatim in source — must NOT be CONTRADICTED)."""
    from common import llm_client
    from verifier.agent import verify
    from verifier.schemas import ClaimVerdict

    log_path = Path("/tmp/verifier_e2e_caffeine_lastrun.jsonl")
    if log_path.exists():
        log_path.unlink()
    llm_client.set_log_path(log_path)

    result = verify(
        _O1_CAFFEINE_OUTPUT,
        _caffeine_source_report(),
        trace_id="o1-part4-caffeine_pos_verified_it",
    )

    assert result is not None
    assert result.source_llm_output == _O1_CAFFEINE_OUTPUT
    assert result.llm_call_count <= 7, (
        f"Budget exceeded: {result.llm_call_count} LLM calls"
    )

    print(f"\nllm_call_count = {result.llm_call_count}")
    print(f"overall_verdict = {result.overall_verdict}")
    print(f"warnings = {result.verification_warnings}")
    print(f"len(claims_v1) = {len(result.claims_v1)}")
    for c in result.claims_v1:
        print(f"  v1  {c.verdict.value:18s}  {c.claim_text[:90]}")
    print(f"raw response log: {log_path}")

    assert result.overall_verdict != "failed"

    # H2 — any v1 claim mentioning "ppm" should be UNSUPPORTED. The
    # pipeline's mass_match_indicator is binary; a scalar ppm assertion
    # is not in source_report.
    ppm_claims = [c for c in result.claims_v1 if "ppm" in c.claim_text.lower()]
    assert len(ppm_claims) >= 1, (
        f"Expected the live extractor to surface the '<1 ppm' claim. "
        f"Inspect {log_path} if missing — likely a Stage 1 truncation."
    )
    h2_caught = any(c.verdict == ClaimVerdict.UNSUPPORTED for c in ppm_claims)
    assert h2_caught, (
        f"H2 NOT caught — at least one ppm claim should be UNSUPPORTED. "
        f"Got: {[(c.verdict.value, c.claim_text) for c in ppm_claims]}"
    )

    # H4 — any v1 claim referencing 'map00232' should be SUPPORTED via
    # Layer C. (May not appear if the LLM dropped the parenthetical, but
    # if it appears it must be SUPPORTED.)
    kegg_claims = [c for c in result.claims_v1 if "map00232" in c.claim_text]
    if kegg_claims:
        h4_supported = any(
            c.verdict == ClaimVerdict.SUPPORTED for c in kegg_claims
        )
        assert h4_supported, (
            f"H4 violated — map00232 claim should be SUPPORTED. "
            f"Got: {[(c.verdict.value, c.claim_text) for c in kegg_claims]}"
        )

    # H5 — Isocaffeine appears verbatim in source.cross_refs is empty
    # for that candidate (degraded info), but Layer A should resolve
    # the formula claim against `candidates[1].candidate.name = 'Isocaffeine'`.
    # No Isocaffeine-related claim should be CONTRADICTED merely on the
    # basis of its name.
    iso_claims = [
        c for c in result.claims_v1
        if "isocaffeine" in c.claim_text.lower()
    ]
    for c in iso_claims:
        assert c.verdict != ClaimVerdict.CONTRADICTED, (
            f"H5 violated — Isocaffeine claim CONTRADICTED on this seed. "
            f"Got: {(c.verdict.value, c.claim_text)}"
        )


# ---------------------------------------------------------------------------
# L-carnitine fixture — H6 (honest non-identification), H7 (silicon warning)
# ---------------------------------------------------------------------------


def _lcarnitine_source_report():
    from schemas.common import Candidate, Spectrum
    from schemas.report import CandidateReport, IdentificationReport

    spectrum = Spectrum(
        mz=[162.1125], intensity=[1.0],
        precursor_mz=162.1125, adduct="[M+H]+",
        ionization_mode="positive", collision_energy=20.0,
    )
    top = CandidateReport(
        candidate=Candidate(
            smiles="CC(=O)OCCN(C)CCO",
            name="2-[2-hydroxyethyl(methyl)amino]ethyl acetate",
            source="library", score=0.737,
            source_id="CID:218057", explain="library hit",
        ),
        prefilter_match=None, metabolite_info=None, pathway_context=None,
        predicted_spectrum_cosine=0.112,
        predicted_model_version="cfm-id-4.4.7",
        mass_match_indicator=1.0, pathway_presence_indicator=0.0,
        evidence_score=0.529, notes=[],
    )
    silicon = CandidateReport(
        candidate=Candidate(
            smiles="C[Si](C)(C)N[Si](C)(C)C",
            name="[dimethyl-(trimethylsilylamino)silyl]methane",
            source="library", score=0.748,
            source_id="CID:13838", explain="library hit",
        ),
        prefilter_match=None, metabolite_info=None, pathway_context=None,
        predicted_spectrum_cosine=0.0,
        predicted_model_version="cfm-id-4.4.7",
        mass_match_indicator=1.0, pathway_presence_indicator=0.0,
        evidence_score=0.499, notes=[],
    )
    third = CandidateReport(
        candidate=Candidate(
            smiles="CN(C)CCOCCC(=O)O",
            name="3-[2-(dimethylamino)ethoxy]propanoic acid",
            source="library", score=0.722,
            source_id="CID:20553414", explain="library hit",
        ),
        prefilter_match=None, metabolite_info=None, pathway_context=None,
        predicted_spectrum_cosine=0.035,
        predicted_model_version="cfm-id-4.4.7",
        mass_match_indicator=1.0, pathway_presence_indicator=0.0,
        evidence_score=0.499, notes=[],
    )
    return IdentificationReport(
        experimental_spectrum=spectrum,
        preprocess_quality_flag="sparse",
        neutral_mass_computed=161.10522,
        n_prefilter_candidates=56,
        n_library_candidates=10,
        n_generated_candidates=0,
        candidates=[top, silicon, third],
        pipeline_version="integration-day1:2bc192d",
        tool_versions={"cfm-id": "cfm-id-4.4.7"},
        warnings=[],
    )


_O1_LCARNITINE_OUTPUT = """\
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


@pytest.mark.skipif(_integration_unavailable(), reason=_SKIP_REASON)
def test_verify_lcarnitine_end_to_end_real_llm(tmp_path):
    """Live cascade against lcarnitine_pos. Asserts H6 (verifier does
    not inject the literal 'L-carnitine' that the pipeline did not
    return) and H7 (chemistry-knowledge silicon-implausibility claim is
    NOT CONTRADICTED — it's correct chemistry, not a hallucination)."""
    from common import llm_client
    from verifier.agent import verify
    from verifier.schemas import ClaimVerdict

    log_path = Path("/tmp/verifier_e2e_lcarnitine_lastrun.jsonl")
    if log_path.exists():
        log_path.unlink()
    llm_client.set_log_path(log_path)

    result = verify(
        _O1_LCARNITINE_OUTPUT,
        _lcarnitine_source_report(),
        trace_id="o1-part4-lcarnitine_pos_verified_it",
    )

    assert result is not None
    assert result.source_llm_output == _O1_LCARNITINE_OUTPUT
    assert result.llm_call_count <= 7, (
        f"Budget exceeded: {result.llm_call_count} LLM calls"
    )

    print(f"\nllm_call_count = {result.llm_call_count}")
    print(f"overall_verdict = {result.overall_verdict}")
    print(f"warnings = {result.verification_warnings}")
    print(f"len(claims_v1) = {len(result.claims_v1)}")
    for c in result.claims_v1:
        print(f"  v1  {c.verdict.value:18s}  {c.claim_text[:90]}")
    print(f"len(claims_v2) = {len(result.claims_v2)}")
    for c in result.claims_v2:
        print(f"  v2  {c.verdict.value:18s}  {c.claim_text[:90]}")
    print(f"raw response log: {log_path}")

    assert result.overall_verdict != "failed"

    # H6 — verifier verifies what was said, not what should have been
    # said. The literal string "L-carnitine" / "L-Carnitine" should NOT
    # appear as a verifier-emitted claim — the LLM never said it.
    for c in result.claims_v1 + result.claims_v2:
        assert "l-carnitine" not in c.claim_text.lower(), (
            f"H6 violated — verifier injected an L-carnitine claim that "
            f"the LLM did not write: {c.claim_text!r}"
        )
    # The rewritten output also must not introduce "L-carnitine" out of
    # nowhere. (The model COULD legitimately mention it as e.g. "the
    # zwitterion of L-carnitine" if hedging — but the stronger claim of
    # "the answer is L-carnitine" is what we forbid; for v0 we use the
    # broader literal-string check.)
    assert "l-carnitine" not in result.rewritten_output.lower(), (
        f"H6 violated — rewriter introduced 'L-carnitine' to the output: "
        f"{result.rewritten_output!r}"
    )

    # H7 — any claim about the silicon candidate's chemical implausibility
    # must NOT be CONTRADICTED. UNSUPPORTED / UNVERIFIABLE_V0 are fine
    # (verifier has no path to confirm a chemistry-knowledge assertion).
    silicon_claims = [
        c for c in result.claims_v1
        if "implausible" in c.claim_text.lower()
        or "silicon" in c.claim_text.lower()
    ]
    for c in silicon_claims:
        assert c.verdict != ClaimVerdict.CONTRADICTED, (
            f"H7 violated — silicon-implausibility claim should not be "
            f"CONTRADICTED. Got: {(c.verdict.value, c.claim_text)}"
        )

    # 6. The log file was written and matches the call count.
    assert log_path.exists()
    n_lines = sum(1 for _ in log_path.open())
    assert n_lines == result.llm_call_count, (
        f"Log line count {n_lines} != llm_call_count {result.llm_call_count}"
    )
