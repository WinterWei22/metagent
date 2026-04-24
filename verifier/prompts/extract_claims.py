"""Stage 1 prompt — extract atomic factual claims from an LLM report.

The model is asked to produce a JSON list of ``{claim_text, subject}``
objects. Anything that fails to parse is surfaced as
``VERIFICATION_PARSE_FAILED`` upstream — there is no retry. Per the Track V
brief, retries mask the failure modes the paper needs to record.

The extractor prompt deliberately does not include "do not hallucinate"
phrasing or instructions to drop uncertain claims. The job is *to surface
what the report says*, not to filter it. Filtering happens in the
verification layers.
"""
from __future__ import annotations


SYSTEM_PROMPT = (
    "You are a precise extractor of factual claims from metabolomics "
    "identification reports."
)


def build(llm_output: str) -> str:
    """Return the user message asking the LLM to extract atomic claims.

    The output JSON shape is locked by the example below — downstream parsing
    requires a list of objects with at least ``claim_text``. ``subject`` is
    optional but improves consistency-layer grouping when present.
    """
    return _USER_TEMPLATE.format(report=llm_output)


_USER_TEMPLATE = """\
Extract every atomic factual claim from the report below. An atomic claim is
one factual statement that can stand on its own without surrounding context.
Examples of atomic claims:

- "D-Gulose has molecular formula C7H14O7"
- "Caffeine maps to KEGG pathway map00232"
- "The mass accuracy is below 1 ppm versus the HMDB reference"

Decompose compound sentences. For example, "Linked to galactose metabolism,
galactosemia, and Fabry disease pathways" yields three claims. Numeric scores
("Score: 0.771 | Cosine: 0.423") yield two claims.

Parenthetical chemical formulas attached to a compound name (for example
"**D-Gulose (C7H14O7)**", "Caffeine (C8H10N4O2)", or "Compound X (C6H12O6)")
yield a separate molecular-formula claim. Treat the parenthetical formula
as a load-bearing factual assertion about the compound, not as decoration.
For "D-Gulose (C7H14O7)" emit "D-Gulose has molecular formula C7H14O7".

For each claim, identify the subject when one is named (a metabolite, a
pathway ID, a candidate index). Use null when no specific subject applies.

Only return a JSON list, for example:
[
  {{"claim_text": "D-Gulose has molecular formula C7H14O7", "subject": "D-Gulose"}},
  {{"claim_text": "Caffeine maps to KEGG pathway map00232", "subject": "Caffeine"}}
]

Report:
---
{report}
---
"""
