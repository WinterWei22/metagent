"""§2.8 — verifier peak_mechanistic on a negative-mode claim.

Brief's "Layer 2 (tool_cross_validator)" maps to
`verifier/layers/peak_mechanistic.py` in this codebase. We construct a
minimal IdentificationReport for citric acid [M-H]- and ask the layer to
verify a fragment claim against SIRIUS (which we already know works
on negative mode from §2.4).

We test two claims:
  1. m/z 87.0086 with neutral loss "C2H2O5"  — SIRIUS in §2.4 predicted
     this exact loss for citric acid, so the verdict should match
     (CONTRADICTED if SIRIUS' wrong-formula bias triggers, otherwise OK).
  2. m/z 111.0085 with neutral loss "H2O"  — neither matches the
     SIRIUS-predicted "CH4O4", so we expect CONTRADICTED.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.common import Candidate, Spectrum  # noqa: E402
from schemas.report import CandidateReport, IdentificationReport  # noqa: E402
from verifier.schemas import (  # noqa: E402
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClassifiedClaim,
    SubjectKind,
)
from verifier.layers.peak_mechanistic import verify_peak_mechanistic  # noqa: E402

FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "spectra" / "negative_mode" / "citric_acid_neg.json"
)


def build_report() -> IdentificationReport:
    fx = json.loads(FIXTURE_PATH.read_text())
    raw_max = max(p[1] for p in fx["peaks"])
    spec = Spectrum(
        mz=[p[0] for p in fx["peaks"]],
        intensity=[p[1] / raw_max for p in fx["peaks"]],
        precursor_mz=fx["precursor_mz"],
        adduct=fx["adduct"],
        ionization_mode=fx["ionization_mode"],
        collision_energy=fx.get("collision_energy"),
    )
    cand = Candidate(
        smiles="O=C(O)CC(O)(C(=O)O)CC(=O)O",
        name="Citric acid",
        source="library",
        score=0.9,
        source_id="MSBNK-RIKEN-PR309128",
        explain="Synthetic top-1 stub for spike test.",
    )
    cand_report = CandidateReport(
        candidate=cand,
        prefilter_match=None,
        metabolite_info=None,
        pathway=None,
        predicted_spectrum=None,
        predicted_spectrum_cosine=None,
        predicted_model_version=None,
        literature_records=[],
        mass_match_indicator=1.0,
        pathway_presence_indicator=0.0,
        evidence_score=0.36,  # 0.4 * 0.9 + 0 + 0 + 0
        notes=[],
    )
    return IdentificationReport(
        experimental_spectrum=spec,
        preprocess_quality_flag="good",
        neutral_mass_computed=192.0270,
        n_prefilter_candidates=1,
        n_library_candidates=1,
        n_generated_candidates=0,
        candidates=[cand_report],
        pipeline_version="spike/negative-mode-test",
        tool_versions={},
        warnings=[],
    )


def make_claim(mz: float, neutral_loss: str | None) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_id=f"C-{mz}",
        claim_text=(
            f"The fragment at m/z {mz:.4f} corresponds to a neutral loss "
            f"of {neutral_loss}." if neutral_loss
            else f"The fragment at m/z {mz:.4f} is observed."
        ),
        normalized_text=None,
        subject="Citric acid",
        claim_type=ClaimType.PEAK_MECHANISTIC,
        classifier_source="rule",
        peak_mz=mz,
        neutral_loss=neutral_loss,
        claim_subtype=ClaimSubtype.UNKNOWN,
        subject_kind=SubjectKind.UNKNOWN,
        candidate_ref=None,
        extracted_fields=ClaimExtractedFields(mz=mz, neutral_loss=neutral_loss),
    )


def main() -> None:
    print("§2.8 verifier peak_mechanistic on negative-mode claim")
    print("-" * 60)
    report = build_report()

    cases = [
        (87.0086, "C2H2O5"),
        (111.0085, "H2O"),
        (191.0190, None),  # precursor itself, no neutral loss
        (200.0000, "CO2"),  # phantom peak, expect CONTRADICTED via "peak missing"
    ]

    for mz, nl in cases:
        claim = make_claim(mz, nl)
        try:
            verdict = verify_peak_mechanistic(claim, report)
            print(f"\nclaim: {claim.claim_text}")
            print(f"  verdict: {verdict.verdict.value}")
            print(f"  evidence: {verdict.evidence}")
            print(f"  trace: {verdict.trace_summary}")
            print(f"  tool_called: {verdict.tool_called}")
            if verdict.correction:
                print(f"  correction: {verdict.correction}")
        except Exception as e:
            print(f"\nclaim: {claim.claim_text}")
            print(f"  CRASHED: {type(e).__name__}: {str(e)[:300]}")


if __name__ == "__main__":
    main()
