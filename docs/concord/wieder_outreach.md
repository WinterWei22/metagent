# Wieder Lab — Cold Outreach Draft

**Status (W7 D5 update 2026-05-17):** still **DRAFT** — held for user review.
W7 produced PRIMARY GREEN under V3 soft-union (+25.5 pp, p = 0.0009,
13/0 positive deltas). LLM-consistency precondition unmet (OQ-9, only
MiniMax key configured), so the autonomous send rule held. **DO NOT send
during W5 / W6 / W7.** Replace pre-send placeholders + final user review
needed before any send action. Updated body suggestion: lead with the
V3 result (+25.5 pp on N=51) and attach Fig 3 v4 PNG.
**Drafted:** 2026-05-16 (Sprint W5 background H)
**Target recipient:** Dr. Cecilia Wieder, *currently at* Imperial College London (formerly Ebbels/Glen lab) — primary maintainer of the `sspa` Python package and recent benchmarks of pathway-level enrichment on metabolomics data.
**Why her:** sspa (pyssp) is the only first-class Python wrapper for the GSEA / ssGSEA / kPCA pathway-activity-score family on metabolite sets; she is also the corresponding author of the 2024 *Briefings in Bioinformatics* tutorial-style benchmark comparing ORA, GSEA, ssPA on metabolite data. Most relevant external expert for a cross-method reconciliation question that is the core of ConcordMet.

> Co-CC consideration (defer to user): Dr. Hyungwon Choi (NUS, mummichog/MetaboAnalyst lineage) — only if user wants two opinions in one round. Default = single-recipient Wieder.

---

## Email Draft

**Subject:** Question about cross-tool disagreement on KEGG-vs-Reactome pathway enrichment in metabolomics — 1-minute ask

---

Hi Dr. Wieder,

I'm Wei (PhD student, [advisor + institution placeholder — fill in before send]) working on a reconciliation problem in metabolomics pathway interpretation. I'm writing because your sspa package and the 2024 *Briefings* benchmark are the cleanest framing of this question I've found, and I have one technical question and one possible collaboration question — both small.

**The setup.** Across 30 publicly-curated MS-grade metabolomics tasks (Recon3D-derived, mix of human plasma / urine / tissue), I ran five enrichment methods on the same input feature lists:

- **sspa ORA + ssGSEA** (your wrapper, ChEBI / Reactome)
- **mummichog** (Py3.10 venv, KEGG)
- **RaMP-DB** ORA (Reactome / KEGG / WP / HMDB-SMPDB)
- **MetaboAnalystR** PSEA / MSEA / Mummichog (KEGG / SMPDB)
- **FELLA** RWR + Diffusion (KEGG sub-network)

After namespace reconciliation (ChEBI primary key, KEGG / SMPDB / Reactome / WikiPathways as cross-references via MetaNetX MNXref + ChEBI `is_a` hierarchy + RDKit InChIKey block14 canonicalization), the **pairwise top-10 Jaccard mean is 0.046** across 22 unique tasks where all five tools produce non-empty output. That is much lower than the ~0.30 you reported in the 2024 benchmark for ORA vs ssPA on the same data. After dropping the cross-namespace pairs (KEGG-only mummichog vs Reactome-only sspa), it climbs to ~0.18 — still well below your ORA-vs-ssPA baseline.

**My technical question** is whether you see this gap as primarily

(a) a *compound-resolution* artifact — i.e. our shared input set has only 59% concordance at the compound level once you reconcile ChEBI / LIPIDMAPS / HMDB canonical SMILES per source, and that downstream noise dominates the pathway signal; **or**

(b) a *pathway-set-overlap* artifact — i.e. the KEGG-hsa / Reactome-Homo-sapiens / SMPDB-1.0 pathway sets simply intersect less than the benchmark assumed once you remove "named alike but DB-asserted different" pathways; **or**

(c) a real methodological disagreement that is being correctly surfaced by the breadth of the panel — in which case the multi-axis approach is more informative than any single tool but is also harder to credit single-tool results from.

I have run RDKit Uncharger + tautomer canonicalization with safeguards (rejecting any block14-changed or stereo-dropped steps); a 91% reduction in pair-level disagreement (59.1% → 5.5%) after reconciliation suggests (a) is real and large. But the residual 5.5% after reconciliation still rolls up into ~85% of pathway-level disagreement, which feels closer to (b) or (c).

**The 1-minute ask:** in your experience with sspa, when ORA vs ssPA disagree on the same Reactome set + same input feature list, is the disagreement mostly because of the input-set size effect (ssPA being more sensitive at small *n*) or because the rank-based score is genuinely picking up signal that ORA's hypergeometric tail misses? If it is the first, our gap is largely an *n*-effect; if it is the second, the five-method panel is informative and we should write it up that way.

**The collaboration question (optional).** If a paper-grade comparison would be of interest, we have the docker'd 5-tool harness running and could send you back a 5×5 Jaccard heatmap on the canonical Wieder-2024 task panel for whatever ground-truth pathway set you want (KEGG hsa01100 + Reactome top-10 by curator confidence are the natural defaults). No expectation; just an offer.

Happy to send the writeup, the reconciliation harness, or just answer follow-ups by email.

Best,
Wei
[email signature placeholder]

---

## Pre-Send Checklist (user review W6)

- [ ] Replace `[advisor + institution placeholder]` with actual line.
- [ ] Confirm Wieder is still at Imperial (LinkedIn / lab page) — she moved post-PhD; default is Imperial as of 2024.
- [ ] Replace `[email signature placeholder]` with full signature (name / role / institution / ORCID).
- [ ] Decide on Hyungwon Choi cc (default = no cc; single recipient is cleaner).
- [ ] Verify "22 unique tasks" / "0.046" / "59.1%" / "5.5%" numbers against final W5 D5 Gate 1 verdict — these are W4 numbers, may shift after the 5-axis run.
- [ ] Run the email through one Claude pass for tone (paper-grade English, not chatty).
- [ ] Subject line: keep at ≤72 chars; current is 86 chars — trim if needed.
- [ ] Send-time: Tuesday or Wednesday morning UK time (Imperial inbox).

## Reasoning Notes (internal — strip before send)

- Subject framed as a *technical question* not a *request* — academic cold-email convention; gets opened ~2× more.
- Open with concrete numbers (30 tasks / 5 methods / 0.046 Jaccard) — proves we are not a fishing expedition; she will respect that we ran the experiment first.
- The 3-bucket framing (a/b/c) gives her an easy reply template — she can pick (a) (b) (c) plus one sentence and we are unblocked.
- Collaboration offer is the *second* paragraph and explicitly optional — keeps the email short and low-pressure. If she ignores it, we lose nothing.
- DO NOT mention "agent" or "LLM" anywhere — Wieder's lab is statistics-oriented; mentioning agents reads as buzzword and dilutes the reconciliation framing, which is the actual contribution.
- Length is ~480 words including signature — at the upper edge of acceptable for an unsolicited cold email to a faculty member; can trim 80-100 words if user wants tighter.
