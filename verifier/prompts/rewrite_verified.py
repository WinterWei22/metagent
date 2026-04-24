"""Stage 4 prompt — rewrite the report keeping only supported claims, with
corrections applied where the verifier named them.

Output is plain text — no JSON, no code fences, no markdown discipline
beyond what the original report used. The rewritten output replaces the
original in the user-facing path; the original is preserved separately in
``VerifiedIdentification.source_llm_output``.
"""
from __future__ import annotations


SYSTEM_PROMPT = (
    "You are a precise editor of metabolomics identification reports."
)


def build(
    *,
    original_output: str,
    edits: list[dict],
) -> str:
    """Return a user message asking the LLM to rewrite ``original_output``
    according to ``edits``.

    ``edits`` is a list of dicts; each describes one verified claim that
    needs editor action. Caller is responsible for filtering to actionable
    items only — supported claims should not appear here.

    Each edit dict expects::

        {
            "claim_text": str,
            "verdict": "contradicted" | "unsupported" | "unverifiable_v0",
            "correction": str | None,  # only for contradicted, when known
            "evidence": str,            # one-line for context
        }
    """
    edit_block = "\n".join(_format_edit(i, e) for i, e in enumerate(edits))
    return _USER_TEMPLATE.format(
        original=original_output,
        edits=edit_block,
    )


def _format_edit(i: int, edit: dict) -> str:
    verdict = edit["verdict"]
    text = edit["claim_text"]
    evidence = edit.get("evidence", "")
    correction = edit.get("correction")
    if verdict == "contradicted" and correction:
        return (
            f"{i}. CONTRADICTED — replace with the correct value.\n"
            f"   claim:      {text}\n"
            f"   correction: {correction}\n"
            f"   evidence:   {evidence}"
        )
    if verdict == "contradicted":
        return (
            f"{i}. CONTRADICTED — drop or rephrase to remove the wrong assertion.\n"
            f"   claim:    {text}\n"
            f"   evidence: {evidence}"
        )
    if verdict == "unsupported":
        return (
            f"{i}. UNSUPPORTED — drop this claim. The pipeline data does not "
            f"contain what the claim asserts.\n"
            f"   claim:    {text}\n"
            f"   evidence: {evidence}"
        )
    # unverifiable_v0
    return (
        f"{i}. UNVERIFIABLE — soften to a hedged statement or drop. The "
        f"verifier could not confirm or deny.\n"
        f"   claim:    {text}\n"
        f"   evidence: {evidence}"
    )


_USER_TEMPLATE = """\
Below is an identification report and a list of edits the verifier has
determined are needed. Rewrite the report applying the edits exactly as
described:

- For CONTRADICTED claims with a named correction, replace the wrong value
  with the correction.
- For CONTRADICTED claims without a correction, drop or rephrase the claim
  so the wrong assertion is not made.
- For UNSUPPORTED claims, drop the claim entirely. Do not paraphrase it.
- For UNVERIFIABLE claims, soften to a hedged statement or drop, your
  choice based on what reads naturally.

Preserve every other claim in the report verbatim. Preserve section
structure, headings, and formatting. Output only the rewritten report —
no commentary, no diff, no explanation.

Original report:
---
{original}
---

Edits:
{edits}
"""
