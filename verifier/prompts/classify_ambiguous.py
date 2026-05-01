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
Classify each claim below by which verification method applies. The
types and what each means:

- grounded_claim: a claim about a value that should appear in the structured
  pipeline output the report was generated from (e.g. a candidate's molecular
  formula, evidence score, mass-match indicator).
- factual_roundtrip_claim: a claim about an external database entity (HMDB
  ID, KEGG ID, InChIKey, the formula or name of a named compound) that can
  be verified by re-querying the metabolite-info backend.
- biological_claim: a claim about pathway membership, biological context, or
  metabolic neighbourhood that can be verified by re-querying the
  pathway-context backend (also covers "biological significance" /
  disease-relevance phrasing for Sub-6 enrichment narratives).
- consistency_claim: a claim whose verification depends on comparison to
  other claims in the same report rather than to any external source.
- literature_claim: a claim that names a specific publication (PMID,
  DOI, or paraphrases an abstract). Verified by checking that the
  citation identifier resolves in PubMed / Europe PMC.
- peak_mechanistic_claim: a claim about a specific MS/MS fragment ion or
  neutral loss at a given m/z (verified against SIRIUS / CFM-ID).
- set_enrichment: a claim that a *set* of compounds (the input differential
  metabolites, "the metabolites", "the data", "coordinated changes") is
  enriched in / points to / dominated by a pathway. Subject is the
  collective compound set, OR a pathway is named as "dominant / primary /
  most affected pathway". The Sub-6 baseline LLM rarely uses the word
  "enriched" verbatim — watch for synonyms ("dominant", "most affected",
  "implicated", "points to", "suggest disruption of"). KEY DISTINCTION
  from biological_claim: SET_ENRICHMENT subject is a COLLECTIVE
  (metabolites/data/set), or the predicate qualifies a pathway as the
  top-ranked one. BIOLOGICAL subject is a single compound or a single
  process.
- driver_metabolite: a claim that one or more named compounds DRIVE an
  enrichment signal (e.g. "Tyrosine and DOPA are key drivers").
- pathway_relationship: a claim about a relationship between TWO pathways
  (upstream / downstream / cross-talk / shared intermediates).

Examples (Sub-6 enrichment narratives):

    # SET_ENRICHMENT — collective subject OR pathway-as-top-1 predicate
    "These metabolites are enriched in Tyrosine metabolism." → set_enrichment
    "Pathway analysis identified Statin inhibition as the top hit." → set_enrichment
    "The dominant pathway affected is glycerolipid metabolism." → set_enrichment
    "Pyrimidine metabolism is the dominant pathway affected." → set_enrichment
    "Methionine metabolism is the most affected pathway." → set_enrichment
    "The metabolites strongly suggest perturbation of pyrimidine metabolism." → set_enrichment
    "Differential metabolites point to disruption of several interconnected pathways." → set_enrichment
    "Coordinated changes in pyrimidine metabolites suggest altered nucleotide demand." → set_enrichment

    # DRIVER_METABOLITE — single or few compounds DRIVE the enrichment
    "Tyrosine and DOPA are key drivers of this enrichment." → driver_metabolite
    "The enrichment is primarily driven by C00070 and C00122." → driver_metabolite

    # PATHWAY_RELATIONSHIP — between two pathways
    "Tyrosine metabolism is upstream of dopamine synthesis." → pathway_relationship
    "Both pathways share several intermediates including DOPA." → pathway_relationship

    # BIOLOGICAL — single compound role / single-process / pathway membership
    "Tyrosine metabolism is dysregulated in Parkinson's disease." → biological_claim
    "Caffeine maps to KEGG pathway map00232." → biological_claim
    "Glutathione is involved in oxidative stress response." → biological_claim
    "dCMP is in pyrimidine metabolism." → biological_claim
    "Polyamines regulate protein synthesis." → biological_claim
    "Heme synthesis compromise affects mitochondrial electron transport." → biological_claim

Output one line per claim in the format ``<index>: <type>`` — for example::

    0: grounded_claim
    1: set_enrichment
    2: driver_metabolite
    3: pathway_relationship

Do not output anything other than these lines.

Claims:
{numbered_claims}
"""
