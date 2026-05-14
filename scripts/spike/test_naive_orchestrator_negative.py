"""§2.9 — naive_orchestrator on a negative-mode IdentificationReport.

Builds a partial-but-valid IdentificationReport for citric acid [M-H]-
combining real outputs already captured in earlier spike stages:

  - experimental_spectrum  : fixture, normalised in §2.1
  - candidate              : citric acid (top-1 from §2.2 prefilter, also
                             present in §2.3 library_search top-10)
  - sirius output          : (was wrong in §2.4 — captured here verbatim
                             so the LLM sees what the verifier saw)

Calls `orchestrator.naive.identify` and reports:
  - whether the LLM mentioned [M-H]- vs [M+H]+
  - whether ionization mode appears as 'negative' / 'positive'
  - whether SIRIUS' wrong-formula bias propagates into the LLM narrative
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.common import Candidate, Spectrum  # noqa: E402
from schemas.molecule import MetaboliteInfoResponse  # noqa: E402
from schemas.report import CandidateReport, IdentificationReport  # noqa: E402
from orchestrator.naive import identify  # noqa: E402

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
        score=0.85,
        source_id="MSBNK-RIKEN-PR309128",
        explain=(
            "Top GNPS [M-H]- match for citric acid; mass error 1.7 ppm; "
            "GNPS modified-cosine 0.85."
        ),
    )
    meta = MetaboliteInfoResponse(
        found=True,
        primary_name="Citric acid",
        synonyms=["2-Hydroxypropane-1,2,3-tricarboxylic acid", "E330"],
        molecular_formula="C6H8O7",
        exact_mass=192.027,
        smiles="O=C(O)CC(O)(C(=O)O)CC(=O)O",
        inchikey="KRKNYBCHXYNGOX-UHFFFAOYSA-N",
        chemical_class="Tricarboxylic acid",
        cross_refs={"hmdb": "HMDB0000094", "kegg": "C00158", "pubchem_cid": "311"},
        source="hmdb",
        explain="Resolved 'Citric acid' via hmdb metadata source.",
    )
    cand_report = CandidateReport(
        candidate=cand,
        prefilter_match=None,
        metabolite_info=meta,
        pathway=None,
        predicted_spectrum=None,
        predicted_spectrum_cosine=None,
        predicted_model_version="cfm-id-4.4.7",
        literature_records=[],
        mass_match_indicator=1.0,
        pathway_presence_indicator=1.0,
        evidence_score=0.74,
        notes=[
            "SIRIUS predicted formula C4H6N3O6 (score 0.95) — disagrees with "
            "candidate formula C6H8O7. SIRIUS appears confused on this "
            "21-peak negative-mode spectrum (CE=6V).",
        ],
    )
    return IdentificationReport(
        experimental_spectrum=spec,
        preprocess_quality_flag="good",
        neutral_mass_computed=192.0270,
        n_prefilter_candidates=20,
        n_library_candidates=5,
        n_generated_candidates=0,
        candidates=[cand_report],
        pipeline_version="spike/negative-mode-test:f96f9f5",
        tool_versions={"sirius": "6.3.4", "cfm-id": "cfm-id-4.4.7"},
        warnings=["SIRIUS top formula disagrees with candidate formula."],
    )


def analyse(text: str) -> dict:
    text_l = text.lower()
    return {
        "len_chars": len(text),
        "mentions_M_minus_H": "[m-h]-" in text_l or "m-h]" in text_l or "[m–h]-" in text_l,
        "mentions_M_plus_H": "[m+h]+" in text_l or "[m + h]+" in text_l,
        "mentions_negative_mode": "negative" in text_l,
        "mentions_positive_mode": " positive" in text_l or "positive ionization" in text_l,
        "mentions_C6H8O7": "c6h8o7" in text_l,
        "mentions_C4H6N3O6": "c4h6n3o6" in text_l,
        "mentions_citric": "citric" in text_l,
        "first_500_chars": text[:500],
    }


def main() -> None:
    print("§2.9 naive_orchestrator on a negative-mode IdentificationReport")
    print("-" * 60)

    report = build_report()
    if not os.environ.get("MINIMAX_API_KEY"):
        print("MINIMAX_API_KEY unset — cannot exercise the LLM.")
        return

    res = identify(report)
    metrics = analyse(res.llm_output)
    print(f"\ntrace_id: {res.trace_id}")
    print(f"source_report_hash: {res.source_report_hash}")
    print(f"generated_at: {res.generated_at}")
    print()
    for k, v in metrics.items():
        if k == "first_500_chars":
            print(f"  {k}:\n{'-'*40}\n{v}\n{'-'*40}")
        else:
            print(f"  {k}: {v}")
    print()
    print("=== full LLM output ===")
    print(res.llm_output)


if __name__ == "__main__":
    main()
