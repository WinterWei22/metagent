"""verifier.helpers — small helpers shared across verifier layers.

W12 C7 sprint adds:
  - fuzzy_match.py — token-Jaccard for pathway-name fuzzy matching
                     (Layer 6a Stage 2.5 + future C3 / C1+C2 sprints)

Not in this sprint:
  - namespace_xwalk.py — was planned per W12 spec §3 D4 but skipped
    after recon found data/concord/metanetx.sqlite holds only
    compound-level xref (LIPIDMAPS / HMDB / CHEBI / REACTOME / KEGG /
    METACYC / BIGG — all compound IDs), not pathway xref. A real
    pathway-namespace cross-walk needs a different data source (e.g.
    PathBank or curated pathway hierarchy). See W12 D4 commit body for
    the audit trail.
"""
