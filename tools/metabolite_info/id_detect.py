"""Identifier auto-detection for fetch_metabolite_info.

The LLM frequently emits the raw identifier without telling us what kind it
is. We classify in priority order HMDB → KEGG → InChIKey → SMILES → name,
because each earlier check is strict enough that it only triggers on the
exact shape of that identifier type. Name is the fallback — we do NOT try
to prove a string is a name, we only decide to treat it as one when nothing
more specific matches.

SMILES detection does NOT require RDKit at import time (rdkit is an optional
dep of this tool's PubChem/MoNA path, not the detector). We use a cheap
pattern heuristic and let the HMDB backend's canonical-SMILES lookup deal
with whether the string actually parses.
"""
from __future__ import annotations

import re
from typing import Literal

from tools.metabolite_info.errors import IdentifierFormatError

IdType = Literal["hmdb", "kegg", "inchikey", "smiles", "name"]

# HMDB IDs: legacy 5-digit (HMDB00122) through modern 7-digit (HMDB0000122).
# We normalise the legacy form on read; detection accepts both.
_HMDB_RE = re.compile(r"^HMDB\d{5,7}$", re.IGNORECASE)

# KEGG compound IDs: "C" followed by exactly 5 digits. Drugs (D#####) and
# glycans (G#####) are out of v0 scope.
_KEGG_RE = re.compile(r"^C\d{5}$")

# InChIKey: 14-10-1 uppercase letters with two hyphens. Exact form is
# defined in the InChIKey spec; we accept the standard layout only.
_INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")

# A SMILES heuristic that leans strict on purpose: we require at least one
# character that a chemical name or database ID would never contain —
# parenthesis, square bracket, =, #, /, \, or @. This misclassifies pure
# "linear" SMILES like "CCO" (ethanol) as names, which is acceptable in
# v0: the caller can still force `id_type="smiles"` explicitly, and the
# set of metabolites we care about all have rings or multiple bonds.
# We do NOT include lowercase aromatic atoms (c/n/o/s/p) here because
# names like "glucose" and "adenosine" contain those letters.
_SMILES_HINT_RE = re.compile(r"[\[\]()=#/\\@]")


def normalise_hmdb(identifier: str) -> str:
    """Left-pad legacy HMDB IDs (HMDB00122 → HMDB0000122).

    Stored IDs are always 7-digit. The caller may supply either form.
    """
    m = re.match(r"^HMDB(\d+)$", identifier, re.IGNORECASE)
    if not m:
        return identifier
    num = m.group(1)
    return "HMDB" + num.zfill(7)


def detect_id_type(identifier: str) -> IdType:
    """Classify `identifier` into one of the supported id types.

    Raises IdentifierFormatError if the string is empty or whitespace-only.
    """
    if identifier is None:
        raise IdentifierFormatError("identifier is None")
    stripped = identifier.strip()
    if not stripped:
        raise IdentifierFormatError("identifier is empty or whitespace")

    if _HMDB_RE.match(stripped):
        return "hmdb"
    if _KEGG_RE.match(stripped):
        return "kegg"
    if _INCHIKEY_RE.match(stripped):
        return "inchikey"
    if _SMILES_HINT_RE.search(stripped) and " " not in stripped:
        return "smiles"
    return "name"


def resolve_id_type(identifier: str, declared: str) -> IdType:
    """Pick the id type, honouring `declared` unless it is 'auto'.

    `declared` is the `id_type` field from the request. When the caller said
    "auto" we run `detect_id_type`; otherwise we trust them (the LLM may know
    something the pattern can't tell, e.g. a non-standard synonym).
    """
    if declared == "auto":
        return detect_id_type(identifier)
    if declared in {"hmdb", "kegg", "inchikey", "smiles", "name"}:
        # Still reject obviously-malformed input early.
        if not identifier or not identifier.strip():
            raise IdentifierFormatError("identifier is empty or whitespace")
        return declared  # type: ignore[return-value]
    # Should never happen given the Pydantic Literal on the request.
    raise IdentifierFormatError(f"unsupported id_type: {declared!r}")
