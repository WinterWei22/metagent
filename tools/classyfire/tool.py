"""Public entry point for ClassyFire chemical classification."""
from __future__ import annotations

from typing import Any

from common.rdkit_utils import inchikey as inchikey_from_smiles
from common.rdkit_utils import is_valid_smiles
from tools.classyfire.api_client import ClassyfireApiClient
from tools.classyfire.cache import ClassyfireCache
from tools.classyfire.errors import ClassyfireNotFoundError, InvalidStructureError
from tools.classyfire.schemas import (
    ClassifyStructureRequest,
    ClassifyStructureResponse,
    node_from_api,
)


def classify_structure(
    req: ClassifyStructureRequest,
    *,
    api_client: ClassyfireApiClient | None = None,
    cache: ClassyfireCache | None = None,
) -> ClassifyStructureResponse:
    """Classify a SMILES/InChIKey into the ClassyFire taxonomy."""
    inchikey = _resolve_inchikey(req)
    cache_obj = cache or ClassyfireCache()
    cached = cache_obj.get(inchikey)
    if cached is not None:
        return cached

    client = api_client or ClassyfireApiClient()
    cache_source = "direct_lookup"
    try:
        entity = client.lookup_entity(inchikey)
    except ClassyfireNotFoundError:
        cache_source = "batch_job"
        entity = client.classify_via_batch(inchikey)

    response = _entity_to_response(entity, source="api")
    if _bare_inchikey(response.inchikey) != inchikey:
        response.inchikey = inchikey
    cache_obj.put(inchikey, response, source=cache_source)
    return response


def _resolve_inchikey(req: ClassifyStructureRequest) -> str:
    if req.smiles is not None:
        if not is_valid_smiles(req.smiles):
            raise InvalidStructureError("SMILES failed RDKit validation.")
        derived = inchikey_from_smiles(req.smiles)
        if not derived:
            raise InvalidStructureError("RDKit could not derive an InChIKey from SMILES.")
        return _bare_inchikey(derived)
    if req.inchikey is None:
        raise InvalidStructureError("At least one of smiles or inchikey must be provided.")
    return _bare_inchikey(req.inchikey)


def _bare_inchikey(value: str) -> str:
    return value.strip().removeprefix("InChIKey=").strip()


def _entity_to_response(entity: dict[str, Any], *, source: str) -> ClassifyStructureResponse:
    nodes = {
        "kingdom": node_from_api(entity.get("kingdom")),
        "superclass": node_from_api(entity.get("superclass")),
        "klass": node_from_api(entity.get("class")),
        "subclass": node_from_api(entity.get("subclass")),
        "direct_parent": node_from_api(entity.get("direct_parent")),
    }
    all_classifications = _collect_classification_names(entity, nodes)
    inchikey = _bare_inchikey(str(entity.get("inchikey") or ""))
    direct = nodes["direct_parent"].name if nodes["direct_parent"] else None
    explain = (
        f"ClassyFire classified {inchikey} with direct parent '{direct}'."
        if direct
        else f"ClassyFire returned a classification for {inchikey}."
    )
    return ClassifyStructureResponse(
        inchikey=inchikey,
        kingdom=nodes["kingdom"],
        superclass=nodes["superclass"],
        klass=nodes["klass"],
        subclass=nodes["subclass"],
        direct_parent=nodes["direct_parent"],
        all_classifications=all_classifications,
        description=entity.get("description"),
        source=source,  # type: ignore[arg-type]
        explain=explain,
    )


def _collect_classification_names(
    entity: dict[str, Any],
    nodes: dict[str, Any],
) -> list[str]:
    names: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value and value not in names:
            names.append(value)

    for key in ("kingdom", "superclass", "klass", "subclass", "direct_parent"):
        node = nodes.get(key)
        if node is not None:
            add(node.name)

    for item in entity.get("intermediate_nodes") or []:
        if isinstance(item, dict):
            add(item.get("name"))
    for item in entity.get("alternative_parents") or []:
        if isinstance(item, dict):
            add(item.get("name"))
    for item in entity.get("ancestors") or []:
        add(item)
    for item in entity.get("substituents") or []:
        add(item)
    for item in entity.get("predicted_chebi_terms") or []:
        add(str(item).split(" (", 1)[0])

    return names
