"""Example usage for classify_structure."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.classyfire import ClassifyStructureRequest, classify_structure  # noqa: E402


def main() -> None:
    req = ClassifyStructureRequest(inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N")
    resp = classify_structure(req)
    print(f"InChIKey: {resp.inchikey}")
    print(f"Direct parent: {resp.direct_parent.name if resp.direct_parent else 'unknown'}")
    print(f"Classifications: {', '.join(resp.all_classifications[:8])}")
    print(f"Source: {resp.source}")
    print(resp.explain)


if __name__ == "__main__":
    main()
