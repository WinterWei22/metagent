"""Track D (Tool 6): pathway_context.

Pathway membership, network neighbours, and a templated plausibility
summary for one metabolite against the sample context. No LLM calls —
every returned string is templated from database rows.

Public entry point: `pathway_context(req: PathwayContextRequest) -> PathwayContextResponse`.
"""
from tools.pathway_context.tool import pathway_context

__all__ = ["pathway_context"]
