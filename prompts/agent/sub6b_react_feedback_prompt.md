<!--
Sub-6B feedback-turn template — PHASE B1 D1 DRAFT.
Loaded by evaluation/sub6/run_sub6b_react_feedback.py:build_feedback_message()
to construct a user-role message that follows an initial assistant
narrative + a verifier verdict.

Placeholders (all required):
  {n_contradicted}        — int count of CONTRADICTED claims
  {n_unsupported}         — int count of UNSUPPORTED claims
  {n_unverifiable}        — int count of UNVERIFIABLE_V0 claims (NEW in B1 D1;
                            wire-up in D4 once feedback_hints.py drops UNV
                            from _NEUTRAL_VERDICTS)
  {n_dropped_by_grammar}  — int count of DROPPED-BY-GRAMMAR claims (NEW in
                            B1 D1; wire-up depends on D2 extractor)
  {contradicted_block}    — formatted bullet list of contradicted claims
                            (claim_id, claim_text, evidence, feedback_hint)
  {unsupported_block}     — same shape for unsupported claims
  {unverifiable_block}    — same shape for UNV claims, with the hint
                            "rewrite as one of the 4 grammar shapes or omit"
                            (NEW in B1 D1; wire-up in D4)
  {dropped_block}         — same shape for grammar-dropped claims (NEW)
  {original_narrative_text} — the agent's previous-iteration narrative
                            verbatim. Field renamed from {original_narrative}
                            because the input is now the JSON object's
                            narrative_text field, not free markdown.

Banned-phrase / grammar-schema snippets are SYNCED from
``verifier/grammar.py``. If the prompt's lists drift from grammar.py,
the verifier and the LLM will disagree about what is allowed and the
feedback hint will appear arbitrary.

This template intentionally does NOT receive the task's ground-truth
pathway. The feedback hints already reference the LLM's own earlier
tool outputs as the source of corrected vocabulary; we never feed the
benchmark answer back into the prompt.
-->

The verifier reviewed your previous narrative.

- {n_contradicted} CONTRADICTED claim(s) — you MUST retract or reverse these.
- {n_unsupported} UNSUPPORTED claim(s) — rephrase using vocabulary from your earlier tool outputs, or drop.
- {n_unverifiable} UNVERIFIABLE claim(s) — these do not match any of the 4 allowed grammar shapes; rewrite or omit.
- {n_dropped_by_grammar} DROPPED-BY-GRAMMAR claim(s) — these were silently discarded from your previous output because they violated the schema; do not produce sentences of the same shape again.

Apply the hints exactly. Output a revised JSON object matching the same schema as the previous turn.

# CONTRADICTED claims — retract or reverse

Do NOT argue with the verifier evidence.

{contradicted_block}

# UNSUPPORTED claims — rephrase or drop

Use pathway names that appeared in your earlier ``query_ramp_enrichment`` / ``query_pathway_membership`` tool outputs. If the pathway you wrote does not appear in any tool result, drop the reference entirely.

{unsupported_block}

# UNVERIFIABLE claims — rewrite to a legal grammar shape or omit

These claims do not fit any of the 4 allowed shapes (``pathway_membership`` / ``metabolite_pathway_link`` / ``pathway_enrichment`` / ``driver_metabolite``). Either rewrite them to fit a shape — with all its required fields — or remove them from the next ``claims`` list.

{unverifiable_block}

# DROPPED-BY-GRAMMAR claims — do not regenerate these shapes

These sentences were stripped from your previous output because they contained banned phrasing (hedges / direction-without-evidence / abstract textbook language / meta-limitations / tool-roundtrips) or because their required fields were missing or generic. Do NOT produce sentences of the same shape again.

{dropped_block}

# Rules for your revision (PHASE B1 STRICT)

1. **RETRACT** contradicted claims. Remove the sentence from ``narrative_text`` and remove the matching ``claims[]`` entry. Do not argue. (No "[retracted: ...]" markup — just remove.)

2. **REPHRASE** unsupported claims using pathway / enzyme / signal_compound names that appeared in YOUR EARLIER tool outputs. If a name does not appear there, drop the claim.

3. **REWRITE** unverifiable claims into one of the 4 legal grammar shapes with all required fields populated. If you cannot, drop them.

4. **DO NOT** add a "Limitations" paragraph, a "Future work" paragraph, a "Strength of claims" caveat, or any other self-limiting prose. Meta-language is banned at the grammar layer; sentences containing it will be silently dropped.

5. **DO NOT** introduce new pathway claims, new compound claims, or new enzyme claims that were not in your original narrative AND not derivable from your earlier tool outputs. Fix existing claims only — the verifier will count any new claim as fresh and you risk regressing.

6. **DO NOT** use this turn to research the topic further. You may call tools, but ONLY to fetch clarifying evidence on claims you are revising (e.g. a second ``query_pathway_membership`` for a specific driver). Do not look up new compounds, new pathways, or new biological context.

7. **If you genuinely disagree** with a specific verifier judgement, leave that one ``claims[]`` entry in place AND add a new claim with ``grammar`` field set to the same shape and ``claim_text`` prefixed by ``[disputed by verifier]``. Limit this to ≤1 disputed claim per revision; abusing it makes N2 worse than N0.

After your revisions, output the final revised JSON object as a single assistant message with **no tool_calls**. Schema is identical to the previous turn:

```
{{
  "narrative_text": "<150-300 word revised summary>",
  "claims": [
    {{"grammar": "<one of the 4 values>", "claim_text": "<verbatim>", ... required fields}}
  ]
}}
```

``claim_text`` is REQUIRED on every claim entry. It must be the verbatim sentence as it would appear in ``narrative_text``. Do NOT omit ``claim_text`` even if the structured fields (``subject`` / ``pathway_name`` / etc.) seem to convey the same information — the verifier needs both for banned-phrase scanning. A claim entry without ``claim_text`` is rejected and counted as dropped.

Original narrative text (revise this — do not rewrite from scratch):

{original_narrative_text}
