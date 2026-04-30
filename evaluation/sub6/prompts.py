"""Sub-6 LLM prompt template (single template for both Sub-6A and Sub-6B).

Render takes a list of metabolite dicts (whatever upstream produced — for
6B these come from ``task["differential_metabolites"]``, for 6A from the
identification stage's top-1 candidates) and emits the prompt text. The
ground-truth pathway, RaMP enrichment list, and noise/signal split are
**deliberately not rendered** — the LLM must reason from the compound
list alone.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a metabolomics analyst. Reason carefully about pathway "
    "biology from a list of differentially abundant metabolites. Do not "
    "invent identifiers or list KEGG/InChIKey codes that were not given."
)

USER_PROMPT_TEMPLATE = """A metabolomics study identified the following metabolites as significantly differentially abundant between control and treatment groups:

{metabolite_block}

Please analyze:
1. Which metabolic pathway(s) are most likely affected?
2. Which of the listed metabolites are key drivers in those pathways?
3. What is the biological significance of these pathway changes?
4. Are there upstream/downstream pathway relationships worth noting?

Provide reasoning in 200-400 words.
"""


def render_metabolite_line(item: dict) -> str:
    """Render one bullet line. Tolerates missing optional fields.

    Required: ``name`` (compound name to display).
    Optional: ``kegg_id``, ``inchikey_first_block`` (or ``inchikey``).
    """
    name = item.get("name") or "(unknown)"
    parts: list[str] = []
    kegg = item.get("kegg_id")
    if kegg:
        parts.append(f"KEGG: {kegg}")
    ik = item.get("inchikey_first_block") or item.get("inchikey")
    if ik:
        parts.append(f"InChIKey: {ik}")
    suffix = f" ({', '.join(parts)})" if parts else ""
    return f"  - {name}{suffix}"


def render_metabolite_block(items: list[dict]) -> str:
    """Render the bullet block. Caller pre-shuffles; we preserve order."""
    if not items:
        return "  (no metabolites available)"
    return "\n".join(render_metabolite_line(it) for it in items)


def render_user_prompt(metabolites: list[dict]) -> str:
    return USER_PROMPT_TEMPLATE.format(
        metabolite_block=render_metabolite_block(metabolites)
    )


def build_messages(metabolites: list[dict]) -> list[dict]:
    """Produce the message list for ``common.llm_client.chat``."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": render_user_prompt(metabolites)},
    ]
