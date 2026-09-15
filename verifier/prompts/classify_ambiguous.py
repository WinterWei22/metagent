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
- other_claim: an abstract single-compound regulatory / mechanistic
  statement that names no specific pathway and no specific
  enzyme / reaction (e.g. "Polyamines regulate protein synthesis").
  Phase B1 D3: such sentences USED to be auto-routed to
  biological_claim, where layer C / Sub-6 biological then attempted a
  RaMP membership lookup against an unverifiable subject and emitted
  a misleading UNSUPPORTED verdict. Routing to other_claim makes the
  dispatcher emit UNVERIFIABLE_V0, which is the honest verdict.

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

    # BIOLOGICAL — names a SPECIFIC pathway by name AND attaches a
    # single-compound or single-process subject to that pathway
    "Tyrosine metabolism is dysregulated in Parkinson's disease." → biological_claim
    "Caffeine maps to KEGG pathway map00232." → biological_claim
    "dCMP is in pyrimidine metabolism." → biological_claim

    # OTHER — abstract single-compound regulation / mechanism that
    # neither names a specific pathway nor an enzyme / reaction
    "Polyamines regulate protein synthesis." → other_claim
    "Glutathione is involved in oxidative stress response." → other_claim
    "Heme synthesis compromise affects mitochondrial electron transport." → other_claim

Output one line per claim in the format ``<index>: <type>`` — for example::

    0: grounded_claim
    1: set_enrichment
    2: driver_metabolite
    3: pathway_relationship

Do not output anything other than these lines.

Claims:
{numbered_claims}
"""
