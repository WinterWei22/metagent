# W19 D4 5-task Smoke Selection

Selection uses W19 offline replay hits to maximize deterministic tool-output coverage while retaining mixed pathway families.

- `compound_only_enrich_mammalian_RAMP_P_000000106_seed0`
- `compound_only_enrich_mammalian_RAMP_P_000000106_seed8`
- `compound_only_enrich_mammalian_RAMP_P_000050021_seed6`
- `compound_only_enrich_mammalian_RAMP_P_000000398_seed0`
- `compound_only_enrich_mammalian_lm_pathway_WP167_seed0`

Expected carrier coverage:
- Mummichog: all selected tasks have offline hits or carrier presence.
- MetaboAnalystR: all selected tasks have offline hits or carrier presence.
- RaMP: selected benchmark tasks are RaMP/WP pathway tasks with RaMP carrier in source data; W19 direct parser currently verifies explicit RaMP numeric claims when present.
