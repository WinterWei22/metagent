# classify_structure

Use `classify_structure` when verifying a factual claim about a compound's
chemical class, taxonomy, or structural category. Examples: "is a flavonoid",
"belongs to the purine class", "is a hexose sugar", or "is a monosaccharide".

Do not use this tool for pathway membership claims; use `pathway_context`
instead. Do not use it for exact name, formula, HMDB, KEGG, or PubChem ID
verification; use `fetch_metabolite_info` for those.

`ClassyfireNotFoundError` means the claim is `UNVERIFIABLE_V0`, not
contradicted. ClassyFire does not contain every novel or rare compound.

Matching is hierarchical. If the claim names a parent class of the actual
ClassyFire direct parent, `matches_claim` can still return `True`. For example,
"monosaccharide" matches a compound classified under "Hexoses" because hexoses
are monosaccharides.

The tool rate-limits live requests to one request per second and caches every
successful classification permanently by InChIKey. Do not call it in a tight
loop from verifier code.

Handoff note for the verifier session: chemical class claims should be routed
through `classify_structure(ClassifyStructureRequest(smiles=candidate.smiles))`.
Treat `matches_claim(...) == True` as `SUPPORTED`, `False` as not supported by
the current ClassyFire hierarchy, and `ClassyfireNotFoundError` as
`UNVERIFIABLE_V0`.
