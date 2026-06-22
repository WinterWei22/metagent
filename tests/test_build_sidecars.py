from __future__ import annotations

from scripts.metagent import build_relevant_pathway_sets as brs
from scripts.metagent import build_gold_drivers as bgd


def test_stratum_of():
    assert brs.stratum_of("s4_cooke_2025_human1_group1") == "human1"
    assert brs.stratum_of("s4_cooke_2025_recon2_2_subsystem27") == "recon2"
    assert brs.stratum_of("hmdb_ramp_easy_kegg_RAMP_P_1_rep0") == "hmdb_ramp"
    assert brs.stratum_of("sub6_easy_compound_only_enrich_mammalian_RAMP_P_1_seed0") == "sub6"


def test_gold_drivers_na_for_modelorg():
    assert bgd.stratum_of("s4_cooke_2025_human1_group1") == "human1"
    # human1/recon2 must map to null gold
    assert bgd.is_na_stratum("human1") is True
    assert bgd.is_na_stratum("recon2") is True
    assert bgd.is_na_stratum("sub6") is False
    assert bgd.is_na_stratum("hmdb_ramp") is False
