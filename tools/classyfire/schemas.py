"""Pydantic schemas for the ClassyFire tool."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tools.classyfire.matcher import matches_claim as _matches_claim


class ClassyfireNode(BaseModel):
    name: str
    chemont_id: str
    description: str | None = None


class ClassifyStructureRequest(BaseModel):
    smiles: str | None = None
    inchikey: str | None = None

    @model_validator(mode="after")
    def _at_least_one_identifier(self) -> "ClassifyStructureRequest":
        if not self.smiles and not self.inchikey:
            raise ValueError("At least one of smiles or inchikey must be provided.")
        return self


class ClassifyStructureResponse(BaseModel):
    model_config = ConfigDict(validate_assignment=True, populate_by_name=True)

    inchikey: str
    kingdom: ClassyfireNode | None = None
    superclass: ClassyfireNode | None = None
    klass: ClassyfireNode | None = Field(None, alias="class")
    subclass: ClassyfireNode | None = None
    direct_parent: ClassyfireNode | None = None
    all_classifications: list[str]
    description: str | None = None
    source: Literal["cache", "api"]
    explain: str

    def matches_claim(self, claimed_class: str) -> bool:
        """
        ClassyFire names are hierarchical and often more specific than an LLM
        claim. This matcher therefore checks every available taxonomy node,
        intermediate node, ancestor, substituent, and predicted term gathered
        into all_classifications. It first allows case-insensitive substring
        matches, then token matches for claim tokens of at least four
        characters, then fuzzy token matches with SequenceMatcher >= 0.8.
        This intentionally favors recall over precision for verifier use:
        a positive match supports the claim, while a miss should be treated as
        unsupported/unverifiable rather than as proof that the claim is false.
        """
        return _matches_claim(claimed_class, self.all_classifications)


def node_from_api(value: Any) -> ClassyfireNode | None:
    if not isinstance(value, dict) or not value.get("name"):
        return None
    return ClassyfireNode(
        name=str(value["name"]),
        chemont_id=str(value.get("chemont_id") or ""),
        description=value.get("description"),
    )
