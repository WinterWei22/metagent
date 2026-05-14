"""Validate Layer F cross-validation against the NM-001 cascade.

Re-runs the four §2.8 spike claims with the new cross-validation logic,
using a SIRIUS *mock* that replays the wrong-formula behaviour observed
during the original spike (so the test is reproducible regardless of
whether the live SIRIUS CLI is currently logged in). CFM-ID is called
through the real Docker shim if reachable; otherwise it falls back to
``NO_DATA`` and the consensus collapses to single-tool rules.

Outputs a side-by-side table:

   claim          | pre-fix verdict (from spike §2.8)
                  | post-fix verdict (with cross-validation)
                  | consensus label (machine-readable)

The four claims are taken verbatim from
``reports/spike/negative_mode_spike_2026-04-28.md`` §2.8.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.common import Candidate, Spectrum  # noqa: E402
from schemas.report import CandidateReport, IdentificationReport  # noqa: E402
from verifier.layers.peak_mechanistic import (  # noqa: E402
    verify_peak_mechanistic,
    reset_cfmid_cache,
)
from verifier.schemas import (  # noqa: E402
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClassifiedClaim,
    SubjectKind,
)


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
        pathway_context=None,
        predicted_spectrum_cosine=None,
        predicted_model_version=None,
        mass_match_indicator=1.0,
        pathway_presence_indicator=0.0,
        evidence_score=0.36,
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
        pipeline_version="spike/nm001-fix-validation",
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


def _spike_sirius_mock(req):
    """Replay the SIRIUS behaviour observed in spike §2.4 for citric acid.

    SIRIUS predicted ``C4H6N3O6`` with score 0.952 and a tree of 11
    fragments. The relevant fragments at the four claim m/z values:
      - 87.0086  → annotated as CHN3 ('HN3' loss, per spike §2.8)
      - 111.0085 → annotated as CH4O4 loss (per spike §2.8)
      - 191.0190 → precursor itself; SIRIUS' tree confirms presence
      - 200.0000 → not in spectrum (early-return CONTRADICTED, never reaches SIRIUS)
    """
    fragments = [
        # m/z, fragment formula, neutral_loss formula, depth
        (191.0190, "C4H6N3O6", "", 0),
        (111.0085, "C3H2N3O2", "CH4O4", 1),
        (87.0086, "C3H3N2O", "HN3", 1),
    ]
    frag_objs = []
    for mz_val, formula, nl, depth in fragments:
        frag_objs.append(SimpleNamespace(
            mz_observed=mz_val,
            formula=formula,
            formula_score=0.9,
            neutral_loss=nl,
            neutral_loss_formula=nl,
            intensity=0.5,
            depth=depth,
        ))

    def lookup_fragment(mz, tolerance_ppm=5.0):
        for f in frag_objs:
            ppm = abs(f.mz_observed - mz) / mz * 1e6
            if ppm <= tolerance_ppm:
                return f
        return None

    return SimpleNamespace(
        predicted_formula="C4H6N3O6",  # NM-001: wrong formula
        formula_score=0.952,
        fragments=frag_objs,
        tree_node_count=11,
        sirius_version="6.3.4 (mock-spike)",
        explain="spike-replay",
        lookup_fragment=lookup_fragment,
    )


# Pre-fix verdicts as documented in spike report §2.8.
_PREFIX_VERDICTS = {
    87.0086: "CONTRADICTED (SIRIUS says loss is HN3)",
    111.0085: "CONTRADICTED (SIRIUS says loss is CH4O4)",
    191.0190: "SUPPORTED (SIRIUS confirms — but with formula C4H6N3O6)",
    200.0000: "CONTRADICTED (peak absent from spectrum)",
}


def main() -> None:
    print("Layer F NM-001 validation — citric_acid_neg.json")
    print("=" * 78)
    print("SIRIUS: replayed spike-§2.4 mock (predicted_formula=C4H6N3O6)")
    print("CFM-ID: live Docker shim if reachable, else NO_DATA")
    print("-" * 78)
    reset_cfmid_cache()
    report = build_report()

    cases = [
        (87.0086, "C2H2O5"),
        (111.0085, "H2O"),
        (191.0190, None),  # precursor itself
        (200.0000, "CO2"),  # phantom peak
    ]

    for mz, nl in cases:
        claim = make_claim(mz, nl)
        result = verify_peak_mechanistic(
            claim, report, sirius_fn=_spike_sirius_mock,
        )
        print(f"\n  m/z {mz:>9.4f} (NL={nl or '—'})")
        print(f"    pre-fix:  {_PREFIX_VERDICTS[mz]}")
        print(f"    post-fix: {result.verdict.value}")
        if result.tool_evidence:
            print(f"    consensus: {result.tool_evidence.get('consensus')}")
            print(f"    rationale: {result.tool_evidence.get('rationale')}")
            sirius_ev = result.tool_evidence.get("sirius", {})
            cfmid_ev = result.tool_evidence.get("cfmid", {})
            print(f"    sirius:   result={sirius_ev.get('result')} "
                  f"sanity_passed={sirius_ev.get('sanity_check_passed')} "
                  f"predicted_formula={sirius_ev.get('predicted_formula')!r}")
            print(f"    cfmid:    result={cfmid_ev.get('result')} "
                  f"matched_mz={cfmid_ev.get('matched_mz')} "
                  f"peaks={cfmid_ev.get('predicted_peak_count')}")
        if result.correction:
            print(f"    correction: {result.correction}")
    print()


if __name__ == "__main__":
    main()
