# W11 UV claim classifier — LLM prompt (MiniMax-M2.7)

## System prompt

```
You are classifying biology research claims into one of 9 categories.

These claims were emitted by an LLM agent doing metabolic pathway analysis on
differential metabolite lists. A downstream verifier judged them as
"unverifiable" because they did not fit the 4 supported grammar shapes
(pathway_membership / metabolite_pathway_link / pathway_enrichment /
driver_metabolite). Your job is to tell us *why* each claim slipped through.

Pick exactly ONE primary category per claim from this list:

C1 cross_method_consensus
    Claim talks about multiple pathway-analysis methods (ORA / FELLA / SSPA /
    Mummichog / RaMP) reaching the same or related conclusion.
    Examples: "ORA and FELLA both rank tyrosine metabolism in the top 3",
              "Three of five paradigms converge on glycine metabolism"

C2 method_disagreement
    Claim flags a discrepancy or differential outcome between methods.
    Examples: "ORA ranks tyrosine #1 but Mummichog does not detect it",
              "Iron shows no enrichment in Mummichog analysis"

C3 signal_evidence
    Claim cites metabolite-level numeric evidence (z-score, fold change,
    abundance, p-value, number of hits) that is not itself a pathway claim.
    Examples: "Tyrosine is elevated 2.3-fold",
              "Galactose metabolism had 11 metabolite hits"

C4 uncertainty_qualifier
    Claim is hedged with confidence / strength / preliminary language.
    Examples: "High confidence in tyrosine metabolism",
              "Weak signal for arachidonate cascade",
              "Preliminary indicator suggesting..."

C5 intermediate_biology
    Claim describes biological mechanism / upstream-downstream / reaction step
    / enzyme function — NOT a pathway-membership or driver claim.
    Examples: "Serotonin is converted to melatonin via arylalkylamine N-acetyltransferase",
              "The glycine N-methyltransferase reaction uses SAM"

C6 literature_reference
    Claim invokes prior knowledge / canonical fact / well-known mechanism.
    Examples: "Tyrosine is a known precursor to dopamine",
              "As reported in the literature, methionine cycle..."

C7 namespace_form
    Claim is structurally about pathway-membership/enrichment but uses a
    non-canonical id namespace (MUMM:, LM:, bare pathway name without ID,
    wrong-prefix HMDB/KEGG/CHEBI confusion).
    Examples: "MUMM:prostaglandin_formation_from_arachidonate places thromboxane A2...",
              "Sucrose has HMDB ID C00089"  (C-prefix is KEGG, not HMDB)

C8 empty_or_noise
    Claim is degenerate: prompt fragment, repetition of earlier text,
    near-empty, lorem-ipsum-like, or completely unrelated to the task.
    Examples: ".......", "see above", "as previously stated", pasted prompt fragment

C9 other
    Claim doesn't fit any of C1-C8. Use sparingly.

Return strict JSON only — no prose, no markdown fences. Format:
[{"claim_id": "...", "primary": "C<N>"}, ...]
One entry per input claim, in the same order.
```

## User message template (per batch of 20)

```
Classify these 20 UNVERIFIABLE claims. Return JSON list with claim_id +
primary category (C1..C9).

{numbered list of {claim_id, claim_text}}
```

## Batch size

- 20 claims per call
- ~1102 / 20 = ~56 calls total
- Estimated cost @ MiniMax-M2.7 ($0.30/M prompt + $1.20/M completion):
  - prompt ~2k tokens × 56 = 112k → $0.034
  - completion ~500 tokens × 56 = 28k → $0.034
  - **total ~$0.07** (well under $3 budget)

## Quality control

- Random 50-claim manual sample (script tooled separately)
- Disagreement rate must be < 30% (per W11 spec stop condition #3)
- If LLM output is malformed JSON, skip that batch and re-run
