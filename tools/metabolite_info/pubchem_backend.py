"""PubChem PUG-REST fallback for fetch_metabolite_info.

Used ONLY when the local HMDB DB returns no hit and the caller has granted
network access (see METAGENT_ALLOW_PUBCHEM env var, default off). Keeping
this fallback network-gated has three benefits:

1. Unit tests never accidentally hit the internet — the env var is unset.
2. Air-gapped deployments don't silently leak queries to pubchem.ncbi.nlm.nih.gov.
3. The trust-anchor contract ("every field traces to a real DB row") is
   preserved even when the underlying DB is PubChem: the CID is returned
   verbatim and the caller can independently verify it.

Returned fields are a strict subset of what HMDB would have provided:
formula, exact mass, smiles, inchikey, primary name, synonyms, pubchem CID.
PubChem does not carry tissue/disease annotation, so those stay empty.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PUBCHEM_ALLOW_ENV_VAR = "METAGENT_ALLOW_PUBCHEM"
PUBCHEM_TIMEOUT_S = 10.0
_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


@dataclass
class PubChemHit:
    """Parsed PubChem CID record with the fields we surface.

    Missing fields are None/[] — PubChem not answering is not evidence of
    absence, only of silence.
    """

    pubchem_cid: str
    primary_name: str | None
    synonyms: list[str]
    molecular_formula: str | None
    exact_mass: float | None
    smiles: str | None
    inchikey: str | None


def pubchem_allowed() -> bool:
    """True iff the operator has opted in by setting METAGENT_ALLOW_PUBCHEM=1.

    Any truthy string ('1', 'true', 'yes', 'on') counts. Absence is 'off'.
    """
    val = os.environ.get(PUBCHEM_ALLOW_ENV_VAR, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _get_json(url: str) -> dict | None:
    """GET `url` and parse JSON. Returns None on any network/parse error.

    Imports `requests` lazily so that the mere import of this module does
    not pull in the network stack for users who never call the fallback.
    """
    try:
        import requests  # type: ignore
    except ImportError:
        logger.warning("requests not installed — cannot reach PubChem.")
        return None
    try:
        r = requests.get(url, timeout=PUBCHEM_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - network errors are many-shaped
        logger.info("PubChem GET failed: %s", e)
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _cid_from_inchikey(inchikey: str) -> str | None:
    data = _get_json(f"{_PUBCHEM_BASE}/compound/inchikey/{inchikey}/cids/JSON")
    if not data:
        return None
    cids = (data.get("IdentifierList") or {}).get("CID") or []
    return str(cids[0]) if cids else None


def _cid_from_name(name: str) -> str | None:
    import urllib.parse

    encoded = urllib.parse.quote(name)
    data = _get_json(f"{_PUBCHEM_BASE}/compound/name/{encoded}/cids/JSON")
    if not data:
        return None
    cids = (data.get("IdentifierList") or {}).get("CID") or []
    return str(cids[0]) if cids else None


def _cid_from_smiles(smiles: str) -> str | None:
    import urllib.parse

    encoded = urllib.parse.quote(smiles, safe="")
    data = _get_json(f"{_PUBCHEM_BASE}/compound/smiles/{encoded}/cids/JSON")
    if not data:
        return None
    cids = (data.get("IdentifierList") or {}).get("CID") or []
    return str(cids[0]) if cids else None


def _properties_for_cid(cid: str) -> dict | None:
    url = (
        f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/"
        "MolecularFormula,ExactMass,CanonicalSMILES,InChIKey,IUPACName/JSON"
    )
    data = _get_json(url)
    if not data:
        return None
    props = ((data.get("PropertyTable") or {}).get("Properties") or [])
    return props[0] if props else None


def _synonyms_for_cid(cid: str, limit: int = 5) -> list[str]:
    data = _get_json(f"{_PUBCHEM_BASE}/compound/cid/{cid}/synonyms/JSON")
    if not data:
        return []
    syn_lists = ((data.get("InformationList") or {}).get("Information") or [])
    if not syn_lists:
        return []
    syns = syn_lists[0].get("Synonym") or []
    return [str(s) for s in syns[:limit]]


def _build_hit(cid: str) -> PubChemHit | None:
    """Assemble a PubChemHit from the two property/synonym calls."""
    props = _properties_for_cid(cid)
    if not props:
        return None
    try:
        exact_mass = float(props.get("ExactMass")) if props.get("ExactMass") is not None else None
    except (TypeError, ValueError):
        exact_mass = None
    synonyms = _synonyms_for_cid(cid)
    primary = synonyms[0] if synonyms else props.get("IUPACName")
    return PubChemHit(
        pubchem_cid=str(cid),
        primary_name=primary,
        synonyms=synonyms,
        molecular_formula=props.get("MolecularFormula"),
        exact_mass=exact_mass,
        smiles=props.get("CanonicalSMILES"),
        inchikey=props.get("InChIKey"),
    )


def lookup(identifier: str, id_type: str) -> PubChemHit | None:
    """Resolve `identifier` of the given kind against PubChem.

    Returns None when the gate (METAGENT_ALLOW_PUBCHEM) is off, when any
    intermediate call fails, or when PubChem itself reports no match.
    Never raises on network errors — the outer tool decides whether an
    absent result is a miss (`found=False`) or an error.
    """
    if not pubchem_allowed():
        return None

    if id_type == "inchikey":
        cid = _cid_from_inchikey(identifier.strip())
    elif id_type == "smiles":
        cid = _cid_from_smiles(identifier.strip())
    elif id_type == "name":
        cid = _cid_from_name(identifier.strip())
    else:
        # HMDB / KEGG lookups don't go through PubChem here — those must be
        # satisfied by the local HMDB DB.
        return None

    if not cid:
        return None
    return _build_hit(cid)
