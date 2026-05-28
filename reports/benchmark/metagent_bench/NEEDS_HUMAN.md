# NEEDS_HUMAN.md

## Gated Or Human-Decision Items

<!-- metagent-bench-gates -->

- D3 S2 IEM clinical data: Miller 2015 supplement / CRAN `CTD::Miller2015` license, de-identification, and redistribution rights require human confirmation. Not downloaded or included.
- D4 S3 ccRCC/Terunuma supplement data: license requires human confirmation before download/inclusion. Not downloaded or included.
- MetaBench overlap: confirm whether real sources overlap with MetaBench arXiv 2510.14944 use cases before final release.

## 2026-05-25 S1 Gate

- S1 conservative D1_v1 gate produced only 2 hard tasks, far below the 80-task lower bound. Human decision needed before expanding S1: either allow paper EV3 CLR pathway as gold where KO gene has no/ambiguous KEGG eco pathway, lower the differential-metabolite threshold, or accept that S1 is not a 100-200 task source under this gold rule.

## 2026-05-25 S3 ST001142 Gate

- Resolved for the narrow IDH hotspot case: DepMap 22Q2 Public Figshare article 19700056 provided `CCLE_mutations_bool_hotspot.csv` and `sample_info.csv` under CC BY 4.0; one IDH1/IDH2 hotspot task was generated.
- Still open for broad S3 expansion: full `CCLE_mutations.csv` is 258 MB and was not downloaded; any non-IDH genotype-to-metabolism tasks need separate public mechanism rules and source-level evidence.

## 2026-05-25 S6 ssPA Gate

- S6 ssPA was profiled and produces 0 tasks under the current charter because the source lacks source-level perturbed pathway ground truth. Human approval is required before treating COVID-vs-healthy enrichment output as task ground truth.

## 2026-05-25 D2 ID Mapping Gate

- RefMet/RaMP/metLinkR resources are not present in `/data/weiwentao/llm_agent_metabolomics/data/landscape`; full canonical ID unification is blocked until a resource source/API/dump is approved or provided.
- Current build has 181 S4 tasks using model-specific Human1/Recon2.2 metabolite IDs and pathway ontologies. These can remain as model-specific easy tasks, but final release needs a human decision on whether to require crosswalk to KEGG/Reactome/RaMP.
