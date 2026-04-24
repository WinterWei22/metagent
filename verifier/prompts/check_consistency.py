"""Stage 3 Layer D prompt — detect intra-document contradictions.

The LLM is asked to surface pairs (or larger groups) of claims that
*directly contradict each other*, not claims it merely finds suspicious. The
output is a JSON list of objects ``{"claim_indices": [...], "reason": "..."}``;
empty list when nothing contradicts.

This prompt deliberately does NOT ask the LLM to compare claims to
external chemistry knowledge. That's Layer A/B's job. Layer D's only
question is "do these claims agree with each other?"
"""
from __future__ import annotations


SYSTEM_PROMPT = (
    "You are a precise detector of intra-document contradictions in chemical "
    "claims."
)


def build(claims: list[str]) -> str:
    """Return a user message asking the LLM to find contradicting claim pairs.

    Indices are 0-based and refer to the order in ``claims``.
    """
    numbered = "\n".join(f"{i}: {c}" for i, c in enumerate(claims))
    return _USER_TEMPLATE.format(numbered_claims=numbered)


_USER_TEMPLATE = """\
Below is a list of factual claims extracted from a single metabolomics
identification report. Find pairs (or larger groups) of claims that directly
contradict each other within this document.

A contradiction means two claims that cannot both be true given only what
they assert. For example:

- "D-Gulose has molecular formula C7H14O7" contradicts "D-Gulose has
  molecular formula C6H12O6" — the same subject is given two different
  formulas.
- "The evidence score is 0.771" contradicts "The evidence score is 0.770"
  for the same candidate.

Do NOT flag claims that are merely surprising, biologically unlikely, or
contradicted only by external knowledge — that is a different layer's job.
Only flag claims that contradict each other within this report.

Only return a JSON list, for example:
[
  {{"claim_indices": [3, 12], "reason": "Same subject D-Gulose given two different molecular formulas"}}
]

If no contradictions exist, return an empty list:
[]

Claims:
{numbered_claims}
"""
