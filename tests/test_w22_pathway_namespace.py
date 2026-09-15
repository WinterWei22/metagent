from __future__ import annotations

from verifier.helpers.pathway_namespace import (
    canonical_pathway_id,
    pathway_ids_equivalent,
)


def test_kegg_map_and_hsa_are_equivalent() -> None:
    assert canonical_pathway_id("KEGG:map00260") == "kegg:00260"
    assert canonical_pathway_id("KEGG:hsa00260") == "kegg:00260"
    assert pathway_ids_equivalent("map00260", "hsa00260")


def test_reactome_is_not_parsed_as_kegg_hsa() -> None:
    assert canonical_pathway_id("REACT:R-HSA-211859") == "reactome:211859"
    assert not pathway_ids_equivalent("REACT:R-HSA-211859", "KEGG:hsa21185")


def test_wp_smpdb_and_mummichog_ids_normalize_exactly() -> None:
    assert canonical_pathway_id("WP:WP2525") == "wikipathways:wp2525"
    assert canonical_pathway_id("SMPDB:SMP00134") == "smpdb:smp00134"
    assert canonical_pathway_id("MUMM:tyrosine_metabolism") == "mummichog:tyrosinemetabolism"


def test_names_do_not_create_id_equivalence() -> None:
    assert canonical_pathway_id("Glycine, serine and threonine metabolism") is None
    assert not pathway_ids_equivalent(
        "Glycine, serine and threonine metabolism",
        "Glycine serine threonine metabolism",
    )

