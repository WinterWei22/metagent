"""Parse SIRIUS fragmentation-tree JSON into lookup-ready annotations."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from tools.sirius.errors import SiriusParseError
from tools.sirius.schemas import FragmentAnnotation


def parse_tree_file(
    path: str | Path,
    *,
    formula_score: float,
) -> list[FragmentAnnotation]:
    """Parse a SIRIUS tree JSON file."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SiriusParseError(f"Could not parse SIRIUS tree JSON at {path}: {e}") from e
    return parse_tree_json(data, formula_score=formula_score)


def parse_tree_json(
    data: dict[str, Any],
    *,
    formula_score: float,
) -> list[FragmentAnnotation]:
    """Parse common SIRIUS 5/6 tree JSON shapes.

    Supported shapes:
      - graph form with ``fragments``/``nodes`` and ``losses``/``edges``
      - nested form with ``root``/``children``
    """
    if not isinstance(data, dict):
        raise SiriusParseError("SIRIUS tree JSON root must be an object.")

    if isinstance(data.get("root"), dict):
        return _parse_nested_tree(data["root"], formula_score=formula_score)

    raw_nodes = _first_list(data, ("fragments", "nodes", "vertices"))
    if raw_nodes is None:
        raise SiriusParseError("SIRIUS tree JSON has no fragments/nodes list.")

    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for idx, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            raise SiriusParseError("SIRIUS tree node must be an object.")
        node_id = str(_first_present(raw_node, ("id", "nodeId", "fragmentId"), idx))
        nodes[node_id] = raw_node
        order.append(node_id)

    if not nodes:
        raise SiriusParseError("SIRIUS tree JSON contains zero nodes.")

    children: dict[str, list[tuple[str, str]]] = {node_id: [] for node_id in nodes}
    parent_of: dict[str, str] = {}
    for raw_edge in _first_list(data, ("losses", "edges")) or []:
        if not isinstance(raw_edge, dict):
            continue
        source = _first_present(
            raw_edge,
            ("source", "from", "parent", "sourceId", "sourceFragmentIdx"),
        )
        target = _first_present(
            raw_edge,
            ("target", "to", "child", "targetId", "targetFragmentIdx"),
        )
        if source is None or target is None:
            continue
        source_id = str(source)
        target_id = str(target)
        loss = _formula_from(raw_edge, default="")
        children.setdefault(source_id, []).append((target_id, loss))
        parent_of[target_id] = source_id

    root_id = next((node_id for node_id in order if node_id not in parent_of), order[0])
    loss_by_child = {
        child_id: loss for parent_id in children for child_id, loss in children[parent_id]
    }
    depths = _compute_depths(root_id, children)
    intensities = _normalised_intensities([nodes[node_id] for node_id in order])

    fragments: list[FragmentAnnotation] = []
    for node_id in order:
        node = nodes[node_id]
        fragments.append(
            FragmentAnnotation(
                mz_observed=_float_from(node, ("mz", "massToCharge", "exactMass", "mass")),
                formula=_formula_from(node),
                formula_score=formula_score,
                neutral_loss=loss_by_child.get(node_id, ""),
                neutral_loss_formula=loss_by_child.get(node_id, ""),
                intensity=intensities[node_id],
                depth=depths.get(node_id, 0),
            )
        )
    return sorted(fragments, key=lambda frag: frag.mz_observed)


def _parse_nested_tree(
    root: dict[str, Any],
    *,
    formula_score: float,
) -> list[FragmentAnnotation]:
    rows: list[tuple[dict[str, Any], int, str]] = []
    queue: deque[tuple[dict[str, Any], int, str]] = deque([(root, 0, "")])
    while queue:
        node, depth, loss = queue.popleft()
        rows.append((node, depth, loss))
        for child in _first_list(node, ("children", "childs")) or []:
            if not isinstance(child, dict):
                continue
            child_loss = _formula_from(child.get("loss", {}) if isinstance(child.get("loss"), dict) else child, default="")
            queue.append((child, depth + 1, child_loss))

    intensities = _normalised_intensities([node for node, _, _ in rows])
    fragments: list[FragmentAnnotation] = []
    for idx, (node, depth, loss) in enumerate(rows):
        node_id = str(_first_present(node, ("id", "nodeId", "fragmentId"), idx))
        fragments.append(
            FragmentAnnotation(
                mz_observed=_float_from(node, ("mz", "massToCharge", "exactMass", "mass")),
                formula=_formula_from(node),
                formula_score=formula_score,
                neutral_loss=loss,
                neutral_loss_formula=loss,
                intensity=intensities[node_id],
                depth=depth,
            )
        )
    return sorted(fragments, key=lambda frag: frag.mz_observed)


def _compute_depths(
    root_id: str,
    children: dict[str, list[tuple[str, str]]],
) -> dict[str, int]:
    depths = {root_id: 0}
    queue: deque[str] = deque([root_id])
    while queue:
        parent = queue.popleft()
        for child, _loss in children.get(parent, []):
            if child in depths:
                continue
            depths[child] = depths[parent] + 1
            queue.append(child)
    return depths


def _normalised_intensities(nodes: list[dict[str, Any]]) -> dict[str, float]:
    raw: dict[str, float] = {}
    for idx, node in enumerate(nodes):
        node_id = str(_first_present(node, ("id", "nodeId", "fragmentId"), idx))
        value = _first_present(node, ("intensity", "relativeIntensity", "relIntensity"), 0.0)
        try:
            raw[node_id] = max(float(value), 0.0)
        except (TypeError, ValueError):
            raw[node_id] = 0.0

    max_i = max(raw.values(), default=0.0)
    if max_i <= 0:
        return {node_id: 0.0 for node_id in raw}
    return {node_id: min(value / max_i, 1.0) for node_id, value in raw.items()}


def _first_list(data: dict[str, Any], keys: tuple[str, ...]) -> list[Any] | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def _first_present(
    data: dict[str, Any],
    keys: tuple[str, ...],
    default: Any = None,
) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _float_from(data: dict[str, Any], keys: tuple[str, ...]) -> float:
    value = _first_present(data, keys)
    try:
        out = float(value)
    except (TypeError, ValueError) as e:
        raise SiriusParseError(f"SIRIUS tree node missing numeric field in {keys}.") from e
    if out <= 0:
        raise SiriusParseError(f"SIRIUS tree node has non-positive m/z-like value {out}.")
    return out


def _formula_from(data: dict[str, Any], default: str | None = None) -> str:
    value = _first_present(
        data,
        (
            "formula",
            "molecularFormula",
            "molecular_formula",
            "neutralLoss",
            "lossFormula",
        ),
        default,
    )
    if value is None:
        raise SiriusParseError("SIRIUS tree node missing formula field.")
    if isinstance(value, dict):
        value = _first_present(value, ("formula", "molecularFormula", "molecular_formula"), default)
    out = str(value or "")
    if default is None and not out:
        raise SiriusParseError("SIRIUS tree node has an empty formula field.")
    return out
