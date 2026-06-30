# MetAgent-Bench Dataset Card

## Build Status

- Build date: 2026-05-25
- Total tasks: 184
- Easy tasks: 181
- Hard tasks: 3
- Real-data tasks: 3 (1.6%)
- Synthetic tasks: 181
- Status: partial build. S1 remains the major hard-task bottleneck under current guardrails.

## Sources

- Cooke 2025 simulatedPA: 181 tasks; kind=synthetic
- Fuhrer & Sauer 2017: 2 tasks; kind=real
- CCLE ST001142 + DepMap 22Q2: 1 tasks; kind=real

## Provenance And Licenses

- S1 Fuhrer & Sauer 2017: CC BY 4.0; DOI:10.15252/msb.20167150; PMC5293155.
- S4 Cooke 2025 simulatedPA: data CC BY 4.0, code MIT; Zenodo 14980037/13753914.
- S3 ST001142 + DepMap 22Q2: CC BY 4.0; one IDH1/IDH2 hotspot task generated from public genotype labels.

## Guardrails

- No clinical S2 data included.
- No ccRCC/Terunuma supplemental data included.
- S6 ssPA was profiled but contributes 0 tasks because it lacks source-level pathway gold labels.
- No task was generated from inferred or circular ground truth.
- No scoring/rubric/model/agent implementation is included.

## Known Gaps

- S1 produced only 2 hard tasks under D1_v1; see `build/s1_build_report.md` and `NEEDS_HUMAN.md`.
- S3 currently contributes only one conservative IDH hotspot task; broad mutation expansion is intentionally not attempted.
- Dataset-level duplicate/context/ID audit is written by `scripts/landscape/audit_dataset.py` to `build/dataset_audit.md`.
- Canonical RefMet/RaMP unification is recorded as the D2 target but not yet implemented in this partial build.
