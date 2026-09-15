<!--
Sub-6B anchored feedback prompt — B-strategy (feedback-redesign Task 4).

Differences from sub6b_react_feedback_prompt.md:
  1. Adds a SUPPORTED-anchor block FIRST: these claims are already verified;
     the LLM must preserve them verbatim.
  2. CONTRADICTED block includes top-1 correction suggestion ("应该是 X").
  3. INSUFFICIENT_EVIDENCE claims are deliberately omitted — the verifier
     was unsure; the LLM should keep those sentences unchanged without guidance.
  4. UNSUPPORTED block: same as original (rephrase or drop).
  5. UNVERIFIABLE / DROPPED blocks: same as original.

Placeholders (all required unless marked optional):
  {supported_anchor_block}    — bullet list of SUPPORTED claim texts,
                                prefixed "已验证，原样保留:" marker
  {n_contradicted}            — int count of CONTRADICTED claims
  {n_unsupported}             — int count of UNSUPPORTED claims
  {contradicted_block}        — bullet list: claim_text + correction suggestion
  {unsupported_block}         — bullet list: claim_text + rephrase hint
  {n_unverifiable}            — int count of UNVERIFIABLE_V0 claims (optional, 0 if absent)
  {unverifiable_block}        — bullet list for UNV claims (may be empty)
  {n_dropped_by_grammar}      — int (may be 0)
  {dropped_block}             — bullet list (may be empty)
  {original_narrative_text}   — verbatim previous narrative

Banned-phrase rules are synced from verifier/grammar.py (same as original prompt).
INSUFFICIENT_EVIDENCE claims are intentionally excluded from this prompt —
the verifier marked them as "unsure"; sending them to the LLM would cause
spurious rewrites of plausible content.
-->

The verifier reviewed your previous narrative.

# ANCHOR — Already-Verified Claims (DO NOT CHANGE)

The following claims were verified as SUPPORTED. You **MUST preserve them verbatim** in your revision. Do not modify the wording, pathway name, subject, or structured fields of any of these claims.

{supported_anchor_block}

# What to fix

- {n_contradicted} CONTRADICTED claim(s) — you MUST retract or replace these (see correction below).
- {n_unsupported} UNSUPPORTED claim(s) — rephrase using vocabulary from your earlier tool outputs, or drop.
- {n_unverifiable} UNVERIFIABLE claim(s) — do not match any of the 4 allowed grammar shapes; rewrite or omit.
- {n_dropped_by_grammar} DROPPED-BY-GRAMMAR claim(s) — banned phrasing detected; do not repeat these shapes.

Apply the hints exactly. Output a revised JSON object matching the same schema as the previous turn.

# CONTRADICTED claims — MUST change (top-1 correction provided)

Each entry below shows the incorrect claim and the top-1 suggested correction. Replace the pathway / subject / enzyme with the correction. Do NOT argue with the verifier.

{contradicted_block}

# UNSUPPORTED claims — rephrase or drop

Use pathway names that appeared in your earlier ``query_ramp_enrichment`` / ``query_pathway_membership`` tool outputs. If the pathway you wrote does not appear in any tool result, drop the reference entirely.

{unsupported_block}

# UNVERIFIABLE claims — rewrite to a legal grammar shape or omit

These claims do not fit any of the 4 allowed shapes (``pathway_membership`` / ``metabolite_pathway_link`` / ``pathway_enrichment`` / ``driver_metabolite``). Either rewrite them to fit a shape — with all its required fields — or remove them from the next ``claims`` list.

{unverifiable_block}

# DROPPED-BY-GRAMMAR claims — do not regenerate these shapes

{dropped_block}

# Rules for your revision (ANCHORED REWRITE)

1. **PRESERVE** all claims in the ANCHOR block above verbatim. These are already verified. Changing them is prohibited.

2. **RETRACT** contradicted claims. Replace with the suggested correction, or remove if you cannot form a valid claim from the correction. Do not add "[retracted: ...]" markup — just replace or remove.

3. **REPHRASE** unsupported claims using pathway / enzyme / signal_compound names that appeared in YOUR EARLIER tool outputs. If a name does not appear there, drop the claim.

4. **REWRITE** unverifiable claims into one of the 4 legal grammar shapes with all required fields populated. If you cannot, drop them.

5. **DO NOT** add a "Limitations" paragraph, a "Future work" paragraph, a "Strength of claims" caveat, or any other self-limiting prose.

6. **DO NOT** introduce new pathway claims, new compound claims, or new enzyme claims that were not in your original narrative AND not derivable from your earlier tool outputs. Fix existing claims only.

7. **DO NOT** use this turn to research the topic further. You may call tools, but ONLY to fetch clarifying evidence on claims you are revising. Do not look up new compounds, new pathways, or new biological context.

After your revisions, output the final revised JSON object as a single assistant message with **no tool_calls**. Schema is identical to the previous turn:

```
{{
  "narrative_text": "<150-300 word revised summary>",
  "claims": [
    {{"grammar": "<one of the 4 values>", "claim_text": "<verbatim>", ... required fields}}
  ]
}}
```

``claim_text`` is REQUIRED on every claim entry. It must be the verbatim sentence as it would appear in ``narrative_text``. Do NOT omit ``claim_text`` even if the structured fields seem to convey the same information.

Original narrative text (revise this — do not rewrite from scratch):

{original_narrative_text}
