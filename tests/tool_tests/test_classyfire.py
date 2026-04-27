from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from tools.classyfire.cache import ClassyfireCache
from tools.classyfire.errors import ClassyfireNotFoundError, InvalidStructureError
from tools.classyfire.schemas import ClassifyStructureRequest
from tools.classyfire.tool import classify_structure

pytestmark = pytest.mark.filterwarnings("ignore:Unknown pytest.mark.requires_classyfire_api")


GLUCOSE_INCHIKEY = "WQZGKKKJIJFFOK-GASJEMHNSA-N"
CAFFEINE_INCHIKEY = "RYYVLZVUVIJVGH-UHFFFAOYSA-N"


GLUCOSE_ENTITY = {
    "smiles": "[H]C1(O)O[C@]([H])(CO)[C@@]([H])(O)[C@]([H])(O)[C@@]1([H])O",
    "inchikey": f"InChIKey={GLUCOSE_INCHIKEY}",
    "kingdom": {"name": "Organic compounds", "chemont_id": "CHEMONTID:0000000"},
    "superclass": {"name": "Organic oxygen compounds", "chemont_id": "CHEMONTID:0004603"},
    "class": {"name": "Organooxygen compounds", "chemont_id": "CHEMONTID:0000323"},
    "subclass": {
        "name": "Carbohydrates and carbohydrate conjugates",
        "chemont_id": "CHEMONTID:0000011",
    },
    "intermediate_nodes": [
        {"name": "Monosaccharides", "chemont_id": "CHEMONTID:0001540"},
    ],
    "direct_parent": {"name": "Hexoses", "chemont_id": "CHEMONTID:0001498"},
    "description": "This compound belongs to the class of organic compounds known as hexoses.",
    "ancestors": [
        "Carbohydrates and carbohydrate conjugates",
        "Hexoses",
        "Monosaccharides",
        "Organic compounds",
    ],
    "predicted_chebi_terms": ["hexose (CHEBI:18133)", "monosaccharide (CHEBI:35381)"],
}


CAFFEINE_ENTITY = {
    "smiles": "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
    "inchikey": f"InChIKey={CAFFEINE_INCHIKEY}",
    "kingdom": {"name": "Organic compounds", "chemont_id": "CHEMONTID:0000000"},
    "superclass": {
        "name": "Purines and purine derivatives",
        "chemont_id": "CHEMONTID:0000345",
    },
    "class": {"name": "Xanthines", "chemont_id": "CHEMONTID:0000504"},
    "subclass": {"name": "Methylxanthines", "chemont_id": "CHEMONTID:0000505"},
    "direct_parent": {"name": "Trimethylxanthines", "chemont_id": "CHEMONTID:0000506"},
    "description": "Caffeine is a methylxanthine.",
    "ancestors": [
        "Alkaloids and derivatives",
        "Purine alkaloids",
        "Purines and purine derivatives",
        "Xanthines",
    ],
}


LCARNITINE_ENTITY = {
    "smiles": "C[N+](C)(C)C[C@H](O)CC([O-])=O",
    "inchikey": "InChIKey=PHIQHXFUZVPYII-REOHCLBHSA-N",
    "kingdom": {"name": "Organic compounds", "chemont_id": "CHEMONTID:0000000"},
    "superclass": {
        "name": "Organic acids and derivatives",
        "chemont_id": "CHEMONTID:0000264",
    },
    "class": {"name": "Carboxylic acids and derivatives", "chemont_id": "CHEMONTID:0000265"},
    "subclass": {"name": "Amino acids, peptides, and analogues", "chemont_id": "CHEMONTID:0000013"},
    "direct_parent": {"name": "Carnitines", "chemont_id": "CHEMONTID:0002030"},
    "description": "L-carnitine is a carnitine.",
    "ancestors": ["Carnitines", "Amino acids, peptides, and analogues"],
}


class MockApiClient:
    def __init__(self, entities: dict[str, dict] | None = None, *, not_found: bool = False):
        self.entities = entities or {}
        self.not_found = not_found
        self.lookup_calls = 0
        self.batch_calls = 0

    def lookup_entity(self, inchikey: str) -> dict:
        self.lookup_calls += 1
        if self.not_found or inchikey not in self.entities:
            raise ClassyfireNotFoundError(f"not found: {inchikey}")
        return self.entities[inchikey]

    def classify_via_batch(self, inchikey: str) -> dict:
        self.batch_calls += 1
        if inchikey not in self.entities:
            raise ClassyfireNotFoundError(f"not found after batch: {inchikey}")
        return self.entities[inchikey]


@pytest.fixture
def temp_cache(tmp_path) -> ClassyfireCache:
    return ClassyfireCache(tmp_path / "classyfire_cache.sqlite")


def test_glucose_is_hexose(temp_cache):
    client = MockApiClient({GLUCOSE_INCHIKEY: GLUCOSE_ENTITY})
    resp = classify_structure(
        ClassifyStructureRequest(inchikey=GLUCOSE_INCHIKEY),
        api_client=client,
        cache=temp_cache,
    )

    assert resp.matches_claim("hexose") is True
    assert resp.matches_claim("monosaccharide") is True
    assert resp.matches_claim("amino acid") is False


def test_caffeine_is_purine_alkaloid(temp_cache):
    client = MockApiClient({CAFFEINE_INCHIKEY: CAFFEINE_ENTITY})
    resp = classify_structure(
        ClassifyStructureRequest(inchikey=CAFFEINE_INCHIKEY),
        api_client=client,
        cache=temp_cache,
    )

    assert resp.matches_claim("purine") is True
    assert resp.matches_claim("alkaloid") is True


def test_cache_hit_skips_api(temp_cache):
    client = MockApiClient({GLUCOSE_INCHIKEY: GLUCOSE_ENTITY})
    req = ClassifyStructureRequest(inchikey=GLUCOSE_INCHIKEY)

    first = classify_structure(req, api_client=client, cache=temp_cache)
    second = classify_structure(req, api_client=client, cache=temp_cache)

    assert first.source == "api"
    assert second.source == "cache"
    assert client.lookup_calls == 1


def test_not_found_raises_classyfire_not_found(temp_cache):
    client = MockApiClient(not_found=True)

    with pytest.raises(ClassyfireNotFoundError):
        classify_structure(
            ClassifyStructureRequest(inchikey="AAAAAAAAAAAAAA-BBBBBBBBBB-C"),
            api_client=client,
            cache=temp_cache,
        )

    assert client.lookup_calls == 1
    assert client.batch_calls == 1


def test_invalid_smiles_raises_before_api(temp_cache):
    client = MockApiClient({GLUCOSE_INCHIKEY: GLUCOSE_ENTITY})

    with pytest.raises(InvalidStructureError):
        classify_structure(
            ClassifyStructureRequest(smiles="not a smiles"),
            api_client=client,
            cache=temp_cache,
        )

    assert client.lookup_calls == 0


def test_matches_claim_partial_match(temp_cache):
    entity = dict(GLUCOSE_ENTITY)
    entity["direct_parent"] = {"name": "Aldohexoses", "chemont_id": "CHEMONTID:0001499"}
    client = MockApiClient({GLUCOSE_INCHIKEY: entity})

    resp = classify_structure(
        ClassifyStructureRequest(inchikey=GLUCOSE_INCHIKEY),
        api_client=client,
        cache=temp_cache,
    )

    assert resp.matches_claim("hexose") is True


def test_matches_claim_fuzzy(temp_cache):
    client = MockApiClient({GLUCOSE_INCHIKEY: GLUCOSE_ENTITY})
    resp = classify_structure(
        ClassifyStructureRequest(inchikey=GLUCOSE_INCHIKEY),
        api_client=client,
        cache=temp_cache,
    )

    assert resp.matches_claim("carbohydrate") is True


def test_explain_is_nonempty(temp_cache):
    client = MockApiClient({GLUCOSE_INCHIKEY: GLUCOSE_ENTITY})
    resp = classify_structure(
        ClassifyStructureRequest(inchikey=GLUCOSE_INCHIKEY),
        api_client=client,
        cache=temp_cache,
    )

    assert resp.explain.strip()


def test_inchikey_derived_from_smiles(temp_cache):
    client = MockApiClient({CAFFEINE_INCHIKEY: CAFFEINE_ENTITY})
    resp = classify_structure(
        ClassifyStructureRequest(smiles="Cn1cnc2c1c(=O)n(C)c(=O)n2C"),
        api_client=client,
        cache=temp_cache,
    )

    assert resp.inchikey == CAFFEINE_INCHIKEY
    assert client.lookup_calls == 1


@pytest.mark.requires_classyfire_api
def test_real_api_glucose_when_enabled(tmp_path, monkeypatch):
    if not os.environ.get("METAGENT_CLASSYFIRE_ONLINE"):
        pytest.skip("Set METAGENT_CLASSYFIRE_ONLINE=1 to hit the real ClassyFire API.")
    monkeypatch.setenv(
        "METAGENT_CLASSYFIRE_CACHE_PATH",
        str(tmp_path / "classyfire_cache.sqlite"),
    )

    resp = classify_structure(ClassifyStructureRequest(inchikey=GLUCOSE_INCHIKEY))

    assert resp.matches_claim("monosaccharide") is True
    assert any("Monosaccharide" in name for name in resp.all_classifications)
