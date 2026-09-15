from __future__ import annotations

import json
from typing import Any


TOTAL_BUDGET_CHARS = 10_500
CARRIER_BUDGET_CHARS = 6_000
METABOLITE_BUDGET_CHARS = 3_000
AUXILIARY_BUDGET_CHARS = 1_500


def build_judge_excerpt(source_report: Any) -> str:
    payload = _as_mapping(source_report)
    sections = [
        _truncate(_build_carrier_sections(payload), CARRIER_BUDGET_CHARS),
        _truncate(_build_metabolite_section(payload), METABOLITE_BUDGET_CHARS),
        _truncate(_build_auxiliary_section(payload), AUXILIARY_BUDGET_CHARS),
    ]
    return _truncate("\n\n".join(section for section in sections if section), TOTAL_BUDGET_CHARS)


def _as_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {"value": dumped}
    if isinstance(value, dict):
        return value
    return {"value": value}


def _build_carrier_sections(payload: dict[str, Any]) -> str:
    parts = [
        _carrier_section(
            key="mummichog_enrichment_result",
            title="### Mummichog enrichment (for direct rank/FDR claims)",
            carrier=payload.get("mummichog_enrichment_result"),
            limit=10,
        ),
        _carrier_section(
            key="ramp_enrichment_result",
            title="### RaMP enrichment (for multi-DB ORA rank/FDR claims)",
            carrier=payload.get("ramp_enrichment_result"),
            limit=10,
        ),
        _nested_carrier_sections(
            key="metaboanalystr_enrichment_result",
            title_prefix="### MetaboAnalystR enrichment",
            carrier=payload.get("metaboanalystr_enrichment_result"),
            limit=5,
        ),
        _carrier_section(
            key="sspa_enrichment_result",
            title="### SSPA enrichment (for Reactome ORA claims)",
            carrier=payload.get("sspa_enrichment_result"),
            limit=10,
        ),
        _nested_carrier_sections(
            key="fella_enrichment_result",
            title_prefix="### FELLA enrichment",
            carrier=payload.get("fella_enrichment_result"),
            limit=10,
        ),
    ]
    return "\n\n".join(part for part in parts if part)


def _carrier_section(*, key: str, title: str, carrier: Any, limit: int) -> str:
    if not carrier:
        return f"{title}\n{key}: (not populated)"
    pathways = _top_pathways(carrier)
    if not pathways:
        return f"{title}\n{key}: (populated; no top_pathways found)\n{_compact_value(carrier)}"
    lines = [title, f"{key}.top_pathways:"]
    lines.extend(_format_pathway(row) for row in pathways[:limit])
    return "\n".join(lines)


def _nested_carrier_sections(*, key: str, title_prefix: str, carrier: Any, limit: int) -> str:
    if not carrier:
        return f"{title_prefix}\n{key}: (not populated)"
    if not isinstance(carrier, dict):
        return _carrier_section(key=key, title=title_prefix, carrier=carrier, limit=limit)
    populated = []
    for sub_key in ("psea", "msea", "mummichog", "rwr", "diffusion"):
        if sub_key in carrier:
            populated.append(
                _carrier_section(
                    key=f"{key}.{sub_key}",
                    title=f"{title_prefix} {sub_key} (for method-specific pathway claims)",
                    carrier=carrier.get(sub_key),
                    limit=limit,
                )
            )
    if populated:
        return "\n\n".join(populated)
    return _carrier_section(key=key, title=title_prefix, carrier=carrier, limit=limit)


def _top_pathways(carrier: Any) -> list[Any]:
    if isinstance(carrier, dict):
        for key in ("top_pathways", "pathways", "results", "rows"):
            value = carrier.get(key)
            if isinstance(value, list):
                return value
        for value in carrier.values():
            nested = _top_pathways(value)
            if nested:
                return nested
    if isinstance(carrier, list):
        return carrier
    return []


def _format_pathway(row: Any) -> str:
    if not isinstance(row, dict):
        return f"- {_compact_value(row)}"
    fields = []
    for key in (
        "rank",
        "pathway_id",
        "pathway_name",
        "name",
        "p_value",
        "pvalue",
        "fdr",
        "q_value",
        "score",
        "score_type",
        "overlap_size",
    ):
        if key in row and row.get(key) is not None:
            fields.append(f"{key}={_format_value(row.get(key))}")
    return "- " + "; ".join(fields)


def _build_metabolite_section(payload: dict[str, Any]) -> str:
    metabolites = payload.get("differential_metabolites") or []
    lines = ["### Differential metabolites (compact sample; carrier sections above are authoritative)"]
    if not isinstance(metabolites, list) or not metabolites:
        lines.append("differential_metabolites: (not populated)")
        return "\n".join(lines)
    for idx, metabolite in enumerate(metabolites):
        line = _format_metabolite(idx, metabolite)
        if len("\n".join(lines + [line])) > METABOLITE_BUDGET_CHARS - 80:
            lines.append(f"... truncated after {idx} of {len(metabolites)} metabolites")
            break
        lines.append(line)
    return "\n".join(lines)


def _format_metabolite(idx: int, metabolite: Any) -> str:
    if not isinstance(metabolite, dict):
        return f"- idx={idx}; value={_compact_value(metabolite)}"
    fields = []
    for key in ("name", "hmdb_id", "kegg_id", "compound_id", "inchikey", "log2fc", "p_value", "fdr"):
        if key in metabolite and metabolite.get(key) is not None:
            fields.append(f"{key}={_format_value(metabolite.get(key))}")
    return f"- idx={idx}; " + "; ".join(fields)


def _build_auxiliary_section(payload: dict[str, Any]) -> str:
    lines = ["### Auxiliary source metadata"]
    for key in ("task_id", "subject_name", "pathway_id", "ground_truth_pathway_id"):
        if key in payload and payload.get(key) is not None:
            lines.append(f"{key}: {_format_value(payload.get(key))}")
    curated = payload.get("curated_hmdb")
    if isinstance(curated, list):
        lines.append(f"curated_hmdb_count: {len(curated)}")
    for key in sorted(payload):
        if key.endswith("_count") and payload.get(key) is not None:
            lines.append(f"{key}: {_format_value(payload.get(key))}")
    return "\n".join(lines)


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    return _compact_value(value)


def _compact_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:500]


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    suffix = "\n... [truncated]"
    return text[: max_chars - len(suffix)] + suffix
