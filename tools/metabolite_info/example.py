"""Minimal runnable demo of fetch_metabolite_info.

Run from the repo root:

    METAGENT_HMDB_PATH=/path/to/hmdb.sqlite \\
    python -m tools.metabolite_info.example

If METAGENT_HMDB_PATH is unset the script reports `found=False` rather
than crashing, so you can sanity-check the identifier auto-detection
without a built HMDB DB on disk.
"""
from schemas import MetaboliteInfoRequest
from schemas.common import ToolError
from tools.metabolite_info import fetch_metabolite_info
from tools.metabolite_info.id_detect import detect_id_type


if __name__ == "__main__":
    identifier = "HMDB0000122"

    # Step 1 — id detection always works; no external data needed.
    print(f"detected id_type for {identifier!r}: {detect_id_type(identifier)}")

    # Step 2 — actual DB lookup; reports found=False if no backend is set up.
    try:
        resp = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier=identifier, id_type="auto")
        )
    except ToolError as e:
        print(f"fetch_metabolite_info failed ({e.code}): {e.message}")
    else:
        print(
            f"found={resp.found}  name={resp.primary_name!r}  "
            f"formula={resp.molecular_formula}  source={resp.source}"
        )
        print(f"cross_refs={resp.cross_refs}")
        print(resp.explain)
