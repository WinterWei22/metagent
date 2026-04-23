"""HMDB end-to-end smoke test for fetch_metabolite_info.

NOT part of the unit-test suite. Runs against a real HMDB SQLite pointed
to by METAGENT_HMDB_PATH and verifies that the 10 fixture HMDB IDs in
tests/fixtures/hmdb_ids/expected.json round-trip with the expected
primary_name / molecular_formula / exact_mass / InChIKey.

Usage:
    METAGENT_HMDB_PATH=/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite \\
    python tests/acceptance_hmdb_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from schemas import MetaboliteInfoRequest
from tools.metabolite_info import fetch_metabolite_info


FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "hmdb_ids" / "expected.json"


def _close_mass(a: float | None, b: float | None, tol: float = 5e-3) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) < tol


def main() -> int:
    if not os.environ.get("METAGENT_HMDB_PATH"):
        print("METAGENT_HMDB_PATH not set", file=sys.stderr)
        return 2

    entries = json.loads(FIXTURE.read_text())["entries"]
    print(f"Smoke-testing {len(entries)} HMDB fixture entries against the real DB.")
    print()

    ok = 0
    mismatches: list[str] = []
    for entry in entries:
        hmdb = entry["hmdb_id"]
        resp = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier=hmdb, id_type="hmdb")
        )
        problems: list[str] = []
        if not resp.found:
            problems.append("not found")
        else:
            if resp.molecular_formula != entry["molecular_formula"]:
                problems.append(
                    f"formula {resp.molecular_formula!r} != {entry['molecular_formula']!r}"
                )
            if not _close_mass(resp.exact_mass, entry["exact_mass"]):
                problems.append(
                    f"exact_mass {resp.exact_mass} vs expected {entry['exact_mass']}"
                )
            if resp.inchikey != entry["inchikey"]:
                problems.append(
                    f"inchikey {resp.inchikey!r} != {entry['inchikey']!r}"
                )
            if resp.cross_refs.get("kegg") != entry["kegg_id"]:
                problems.append(
                    f"kegg_id {resp.cross_refs.get('kegg')!r} != {entry['kegg_id']!r}"
                )
        status = "OK" if not problems else "MISMATCH"
        print(
            f"[{status}] {hmdb}  name={resp.primary_name!r}  "
            f"formula={resp.molecular_formula}  mass={resp.exact_mass}  "
            f"tissues={len(resp.tissue_locations)}  diseases={len(resp.disease_associations)}"
        )
        if problems:
            for p in problems:
                print(f"     - {p}")
            mismatches.append(hmdb)
        else:
            ok += 1

    print()
    print(f"result: {ok}/{len(entries)} matched fixture")

    # Spot check 1: uric acid should carry real disease annotation (e.g. gout).
    uric = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB0000289", id_type="hmdb")
    )
    print(f"spot-check uric_acid diseases: {uric.disease_associations[:5]}")

    # Spot check 2: KEGG -> HMDB round trip
    back = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="C00031", id_type="kegg")
    )
    print(
        f"spot-check KEGG C00031 -> HMDB {back.cross_refs.get('hmdb')!r} "
        f"({back.primary_name!r})"
    )

    # Spot check 3: no hallucination when the caller goes to a nonsense ID.
    none = fetch_metabolite_info(
        MetaboliteInfoRequest(identifier="HMDB9999999", id_type="hmdb")
    )
    print(
        f"spot-check HMDB9999999: found={none.found}  source={none.source}  "
        f"disease_associations={none.disease_associations}"
    )

    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
