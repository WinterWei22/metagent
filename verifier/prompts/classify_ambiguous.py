"""Stage 2 fallback prompt — classify claims the rule-based router could
not decide.

Output format is line-delimited (``<index>: <type>``), not JSON. Rationale:
a single malformed line only marks one claim as ``error``; the rest survive.
A JSON-array format would lose every classification on a single trailing
comma. The classifier expects every claim to be classified or none at all
to be classified, so missing indices are tolerated and treated as ``error``.
"""
from __future__ import annotations


SYSTEM_PROMPT = (
    "You are a precise classifier of factual claims by verification method."
)


def build(claims: list[str]) -> str:
    """Return a user message asking the LLM to classify ``claims`` by type.

    ``claims`` is the *ambiguous* subset — claims the rule-based router did
    not decide. Each claim is shown with its index in the ambiguous list, not
    its index in the full claim set. The caller is responsible for mapping
    back.
    """
    numbered = "\n".join(f"{i}: {c}" for i, c in enumerate(claims))
    return _USER_TEMPLATE.format(numbered_claims=numbered)


_USER_TEMPLATE = """\
Classify each claim below by which verification method applies. The four
types and what each means:

- grounded_claim: a claim about a value that should appear in the structured
  pipeline output the report was generated from (e.g. a candidate's molecular
  formula, evidence score, mass-match indicator).
- factual_roundtrip_claim: a claim about an external database entity (HMDB
  ID, KEGG ID, InChIKey, the formula or name of a named compound) that can
  be verified by re-querying the metabolite-info backend.
- biological_claim: a claim about pathway membership, biological context, or
  metabolic neighbourhood that can be verified by re-querying the
  pathway-context backend.
- consistency_claim: a claim whose verification depends on comparison to
  other claims in the same report rather than to any external source.
- literature_claim: a claim that names a specific publication (PMID,
  DOI, or paraphrases an abstract). Verified by checking that the
  citation identifier resolves in PubMed / Europe PMC.

Output one line per claim in the format ``<index>: <type>`` — for example::

    0: grounded_claim
    1: biological_claim
    2: consistency_claim

Do not output anything other than these lines.

Claims:
{numbered_claims}
"""
