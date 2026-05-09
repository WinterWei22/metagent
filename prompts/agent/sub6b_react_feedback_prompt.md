<!--
Sub-6B feedback-turn template (phase A2 D3, track AGENT).
Loaded by evaluation/sub6/run_sub6b_react_feedback.py:build_feedback_message()
to construct a user-role message that follows an initial assistant
narrative + a verifier verdict.

Placeholders (all required):
  {n_contradicted}        — int count of CONTRADICTED claims
  {n_unsupported}         — int count of UNSUPPORTED claims
  {contradicted_block}    — formatted bullet list of contradicted claims with
                            claim_id, claim_text, evidence, feedback_hint
  {unsupported_block}     — same shape for unsupported claims
  {original_narrative}    — the agent's previous-iteration narrative verbatim

This template intentionally does NOT receive the task's ground-truth
pathway. The feedback hints already reference the LLM's own earlier
tool outputs as the source of corrected vocabulary; we never feed the
benchmark answer back into the prompt.
-->

The verifier reviewed your previous narrative and found {n_contradicted} CONTRADICTED claim(s) and {n_unsupported} UNSUPPORTED claim(s). Each one has an actionable hint from the verifier. Apply the hints exactly.

CONTRADICTED claims — you MUST retract or reverse these. Do NOT argue with the verifier evidence:

{contradicted_block}

UNSUPPORTED claims — rephrase using vocabulary that appeared in your earlier `query_ramp_enrichment` / `query_pathway_membership` tool outputs, or drop the reference:

{unsupported_block}

Rules for your revision (PHASE A2 STRICT — violations make N2 worse than N0):

1. **RETRACT** contradicted claims. Cross them out, qualify them with "[retracted: not supported by RaMP/KEGG]", or remove the sentence. Do not argue.

2. **REPHRASE** unsupported claims using pathway names that appeared in YOUR EARLIER tool outputs. If the pathway you wrote does not appear in any tool result, drop the reference entirely.

3. **ADD a brief "Limitations" paragraph** at the end noting where evidence was conflicting or absent. This is the ONLY new content you may write. Keep it under 80 words.

4. **DO NOT introduce new pathway claims, new compound claims, or new directional assertions** that were not in your original narrative. Fix existing claims only — the verifier will count any new claim as fresh and you risk regressing.

5. **DO NOT use this turn to research the topic further.** You may call tools, but ONLY for clarifying evidence on claims you are revising. Do not look up new compounds, new pathways, or new biological context.

6. **If you genuinely disagree** with a specific verifier judgement, leave that one claim in place and add `[disputed by verifier]` immediately after it. Do not expand the surrounding narrative.

After your revisions, output the final revised narrative as a single assistant message with **no tool_calls**.

Original narrative (revise this — do not rewrite from scratch):

{original_narrative}
