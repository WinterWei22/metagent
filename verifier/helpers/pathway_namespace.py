from __future__ import annotations

import re


def canonical_pathway_id(value: str | None) -> str | None:
    """Return an exact semantic pathway ID key, or None for non-ID text."""
    if not value:
        return None
    text = str(value).strip().lower()

    reactome = re.search(r"(?:react:)?r-hsa-(\d+)", text)
    if reactome:
        return f"reactome:{reactome.group(1)}"

    kegg = re.search(r"(?:kegg:)?(?:map|hsa)(\d{5})\b", text)
    if kegg:
        return f"kegg:{kegg.group(1)}"

    wp = re.search(r"(?:wp:)?(wp\d{3,5})\b", text)
    if wp:
        return f"wikipathways:{wp.group(1)}"

    smpdb = re.search(r"(?:smpdb:)?(smp\d{5,7})\b", text)
    if smpdb:
        return f"smpdb:{smpdb.group(1)}"

    mummichog = re.search(r"mumm:([a-z0-9_:-]+)\b", text)
    if mummichog:
        token = re.sub(r"[^a-z0-9]", "", mummichog.group(1))
        return f"mummichog:{token}"

    return None


def pathway_ids_equivalent(left: str | None, right: str | None) -> bool:
    left_id = canonical_pathway_id(left)
    right_id = canonical_pathway_id(right)
    return left_id is not None and left_id == right_id

