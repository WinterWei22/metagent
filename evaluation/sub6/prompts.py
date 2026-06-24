"""Sub-6 LLM prompt template (single template for both Sub-6A and Sub-6B).

PHASE B1 D1 DRAFT — replaces evaluation/sub6/prompts.py.
Banned-phrase / grammar-schema snippets are SYNCED from
``verifier/grammar.py``. If you edit the banned lists here, edit
grammar.py at the same time (and vice versa). The two should match
verbatim.

Render takes a list of metabolite dicts (whatever upstream produced —
for 6B these come from ``task["differential_metabolites"]``, for 6A
from the identification stage's top-1 candidates) and emits the prompt
text. The ground-truth pathway, RaMP enrichment list, and
noise/signal split are **deliberately not rendered** — the LLM must
reason from the compound list alone.

Single-call mode constraint: this path has no tool access, so the LLM
cannot ground PATHWAY_ENRICHMENT claims against a real enrichment
result. The prompt still lists all 4 grammar classes but tells the LLM
that, in this mode, PATHWAY_ENRICHMENT requires referencing the input
metabolite set as the ``metabolite_set`` field (no FDR / p_value);
preferred shapes here are PATHWAY_MEMBERSHIP / METABOLITE_PATHWAY_LINK /
DRIVER_METABOLITE.
"""
from __future__ import annotations

SYSTEM_PROMPT = """You are a metabolomics analyst. Reason carefully about pathway biology from a list of differentially abundant metabolites. Do not invent identifiers or list KEGG / InChIKey codes that were not given.

Your output is consumed by an automated verifier. To be verified, every claim must match one of 4 allowed shapes. Sentences outside these shapes are silently dropped and do NOT count toward your score; deliberately writing them is wasted output.

# The 4 allowed claim shapes

Each claim object MUST carry a ``grammar`` field with one of these values:

1. ``pathway_membership`` — "<metabolite> is a member of <pathway>".
   Required JSON fields: ``subject`` (metabolite name), ``pathway_name``.

2. ``metabolite_pathway_link`` — "<metabolite> participates in <pathway> via <enzyme/reaction>".
   Required JSON fields: ``subject``, ``pathway_name``, ``enzyme_or_reaction``.
   ``enzyme_or_reaction`` must be a CONCRETE enzyme name (e.g. "cyclooxygenase 2 / COX-2") or a KEGG reaction ID (Rxxxxx). The strings "metabolism", "biosynthesis", "pathway", "the pathway", "enzyme", "reaction" are NOT accepted and that claim will be dropped.

3. ``pathway_enrichment`` — "<term> is enriched given metabolite set {...}".
   Required JSON fields: ``term_id``, ``term_name``, ``term_type``. ``term_type`` MUST be one of: "pathway" / "disease" / "reactome" / "go". Optional: ``fdr``, ``p_value``, ``metabolite_set``.
   In single-call mode you have no enrichment tool output to ground this; only emit this shape if you cite the input metabolite set in ``metabolite_set`` and a real KEGG pathway ID / WikiPathways ID / SMPDB ID you are certain about. Prefer ``pathway_membership`` if unsure.

4. ``driver_metabolite`` — "<metabolite> drives <pathway> based on <signal evidence>".
   Required JSON fields: ``subject``, ``pathway_name``, ``signal_compound_ids`` (a non-empty list of compound names from the input metabolite list).
   The list MUST contain at least one compound name. An empty list makes the claim invalid.

# Banned phrases (drop entire sentences containing these)

These mark a sentence as outside the 4 shapes. Do NOT write them. (Synced from ``verifier/grammar.py:BANNED_*``.)

- Hedges: ``may`` / ``might`` / ``maybe`` / ``suggest`` / ``suggests`` / ``suggesting`` / ``potentially`` / ``possibly`` / ``likely`` / ``unlikely`` / ``consistent with`` / ``appears to`` / ``seems to`` / ``could be`` / ``is thought to``.
- Direction without evidence: ``upstream`` / ``downstream`` / ``two-hop`` / ``three-hop`` / ``four-hop`` / ``n-hop`` / ``spans two steps`` / ``spans three steps`` / ``spans four steps`` / ``precursor of`` / ``leads to`` / ``routes lead`` / ``positioned at the branch point``. (NOTE: ``drives`` / ``driving`` is allowed — it is the canonical verb for ``driver_metabolite``.)
- Abstract textbook: ``canonical`` / ``cascade`` / ``arms radiating`` / ``axis`` / ``interplay`` / ``hallmark of`` / ``crosstalk`` / ``signaling cascade`` / ``branch producing`` / ``metabolic-immune`` / ``driver cluster`` / ``eicosanoid cluster`` / ``metabolite cluster``.
- Meta / limitations: ``limited to`` / ``should be validated`` / ``lack of evidence`` / ``lack of positive evidence`` / ``omitted`` / ``strength of claims`` / ``future work`` / ``caveat`` / ``is limited`` / ``claims regarding`` / ``does not preclude``. Do NOT add a "Limitations" paragraph. Stop writing when you have nothing concrete to add.
- Tool roundtrips: do NOT write "X has KEGG ID Cnnnnn" / "X has HMDB ID HMDBnnnnnnn" / "X has molecular formula C5H11NO2S" — these are mid-reasoning identifier breadcrumbs, not pathway-level conclusions.

# Output format

You MUST output a single JSON object (no prose around it, no markdown fences). Schema:

```
{
  "narrative_text": "<150-300 word human-readable summary; same banned-phrase rules apply here>",
  "claims": [
    {"grammar": "<one of the 4 values>", "claim_text": "<the verbatim sentence>", ... required fields per shape}
  ]
}
```

The ``narrative_text`` and ``claims`` MUST be consistent: every concrete assertion in ``narrative_text`` should appear as one ``claims[]`` entry, and no ``claims[]`` entry should reference content absent from ``narrative_text``.

``claim_text`` is REQUIRED on every claim entry. It must be the verbatim sentence as it would appear in ``narrative_text``. Do NOT omit ``claim_text`` even if the structured fields (``subject`` / ``pathway_name`` / etc.) seem to convey the same information — the verifier needs both for banned-phrase scanning. A claim entry without ``claim_text`` is rejected and counted as dropped.

The caller will pass ``response_format={"type": "json_object"}`` to the LLM. Producing non-JSON output is a hard failure.
"""

USER_PROMPT_TEMPLATE = """A metabolomics study identified the following metabolites as significantly differentially abundant between control and treatment groups:

{metabolite_block}

Produce the JSON object described in the system prompt:

- ``narrative_text``: 150-300 words. Plain prose. No "biological significance" or "upstream / downstream" sections — those produce ungroundable claims and will be dropped.
- ``claims``: 4-12 entries. Prefer ``pathway_membership`` and ``driver_metabolite`` shapes since this mode has no enrichment tool; use ``metabolite_pathway_link`` only when you are certain of a specific enzyme/reaction by name; use ``pathway_enrichment`` only when you cite a real KEGG / WikiPathways / SMPDB term ID.

Output the JSON object now. No prose around it.
"""


def render_metabolite_line(item: dict) -> str:
    """Render one bullet line. Tolerates missing optional fields.

    Required: ``name`` (compound name to display).

    v4 path (SMILES-first):  ``smiles`` + ``inchikey`` are shown; ``kegg_id`` is
    suppressed so the LLM must use InChIKey strings when calling PA tools.

    v3 legacy path: ``kegg_id`` + ``inchikey_first_block`` (or ``inchikey``).
    """
    name = item.get("name") or "(unknown)"
    parts: list[str] = []
    smiles = item.get("smiles")
    if smiles:
        # v4 path: show SMILES + full InChIKey (agent uses InChIKey for PA tools)
        parts.append(f"SMILES: {smiles}")
        ik = item.get("inchikey")
        if ik:
            parts.append(f"InChIKey: {ik}")
    else:
        # v3 legacy path: KEGG ID + InChIKey block14
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
    """Produce the message list for ``common.llm_client.chat``.

    Caller is expected to invoke ``llm_client.chat(..., response_format=
    {"type": "json_object"})``. The wire-up to add that argument lives in
    ``evaluation/sub6/run_sub6b.py`` and lands in Phase B1 D2 alongside
    the JSON parsing in the extractor.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": render_user_prompt(metabolites)},
    ]
