<!--
Narrative weave template for Strategy A (feedback-redesign Task 3).

This prompt is used after the system has deterministically filtered and
corrected claims using apply_cascade(). The LLM's only job is to write
a human-readable narrative that describes these claims coherently.

The LLM MUST NOT:
  - Add any new claims
  - Remove any of the claims provided
  - Modify any claim's pathway, subject, or structured fields
  - Introduce new biological context or interpretation not grounded in
    the provided claims
  - Add meta-language (limitations, caveats, uncertainties, future work)
  - Use hedging language (may, might, could, appears to, suggests)

The narrative must:
  - Be 150-300 words
  - Mention each pathway name from the provided claims
  - Be coherent and flow naturally
  - Preserve factual specificity from the original claims
  - NOT reinterpret or generalize beyond what the claims assert

Claim structure passed to this prompt:
  Each claim is a dict with keys:
    - "claim_text": the verbatim sentence to include
    - "pathway_name": (if present) the pathway involved
    - "subject": the metabolite/compound
    - "grammar": one of {pathway_membership, metabolite_pathway_link,
                         pathway_enrichment, driver_metabolite}
  The prompt builder extracts these fields and summarizes them.
-->

You have reviewed a set of evidence-verified claims about metabolite pathways.
The verifier has confirmed these claims are factually supported. Your task:
write a coherent 150–300 word narrative that describes these claims.

**CRITICAL CONSTRAINTS:**

1. **Do NOT add new claims.** Use ONLY the pathways and metabolites listed
   below. No new compounds, no new pathways, no new biological interpretation.

2. **Do NOT modify or remove any claim.** Every pathway name below MUST appear
   in your narrative. Every subject (metabolite/compound) MUST be mentioned.

3. **Do NOT use meta-language:** No "limitations," "future work," "remains to
   be determined," "suggests," "may," "could," "appears to." These are all
   banned.

4. **Do NOT hedge.** Write with confidence: "X is in pathway Y" not "X may be
   involved in pathway Y."

5. **Do NOT introduce new biological context.** Stick to what the claims assert.
   If a claim says "Compound A is in Pathway B," describe that fact. Do not
   extrapolate to secondary metabolic consequences.

6. **Mention every pathway name explicitly.** If the claim says "Glycolysis,"
   write "Glycolysis" in your narrative. No synonyms or paraphrases.

---

# Claims to weave

{claims_summary}

---

# Your revised narrative

Write a single, coherent paragraph (150–300 words) that flows naturally and
describes these claims. Use the claim_text fragments as your source material.
Do not add claims. Do not remove claims. Do not hedge or qualify.

Start writing:
