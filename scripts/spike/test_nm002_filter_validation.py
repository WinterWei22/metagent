"""Validate NM-002 leakage filter on spike fixtures.

Reads the cached spike artifact from §2.3
(``/tmp/spike_neg_pipeline_artifacts.pkl``) and replays the same
``library_search`` top-K, *minus* every candidate whose ``source_id``
is in the NM-002 exclusion list
(``data/processed/nm002_excluded_gnps_ids.json``).

For each fixture, prints:

  - prefilter pool with/without exclusions
  - library_search top-10 with/without exclusions
  - the pre-fix top-1 (the leaked record) and the post-fix top-1
  - whether the truth (per-fixture InChIKey first-block) is still found

This is a deterministic post-hoc filter — it does NOT re-run library_search.
That is the right validation for NM-002 because library_search's score
is structure-only (ms-clip vs query spectrum); excluding leaked
references from the pool can only remove candidates, never reorder
the survivors.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

ARTIFACT = Path("/tmp/spike_neg_pipeline_artifacts.pkl")
EXCLUSION_LIST = ROOT / "data" / "processed" / "nm002_excluded_gnps_ids.json"
SPIKE_REPORT = ROOT / "reports" / "spike" / "negative_mode_spike_2026-04-28.md"


def load_exclusion_set() -> set[str]:
    raw = json.loads(EXCLUSION_LIST.read_text())
    excl = set(raw.get("excluded_ids", []))
    return excl


def _truth_inchikey_first(target: str) -> str:
    return target[:14] if target else ""


def _ik_first(smiles: str) -> str:
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return ""
        ik = Chem.MolToInchiKey(mol)
        return ik[:14] if ik else ""
    except Exception:
        return ""


def report_fixture(fname: str, payload: dict, excluded: set[str]) -> None:
    print(f"\n=== {fname} ===")
    target = payload.get("fixture_data", {}).get("inchikey", "")
    truth_first = _truth_inchikey_first(target)
    print(f"  truth InChIKey first-block: {truth_first}")

    pre_cands = payload.get("prefilter_candidates") or []
    n_pre = len(pre_cands)
    pre_excluded = sum(1 for c in pre_cands if c.get("source_id") in excluded)
    print(f"  prefilter: {n_pre} candidates, {pre_excluded} would be excluded")

    lib_cands = payload.get("library_search_top_candidates") or []
    n_lib = len(lib_cands)
    print(f"  library_search top-{n_lib} (pre-fix):")
    for i, c in enumerate(lib_cands, 1):
        sid = c.get("source_id") or ""
        flag = " ❌ leaked" if sid in excluded else ""
        match = "✅" if _ik_first(c.get("smiles") or "") == truth_first else " "
        print(f"    {i:>2}. score={c['score']:.3f} sid={sid:<22} {match} name={c['name']!r}{flag}")

    survivors = [c for c in lib_cands if c.get("source_id") not in excluded]
    print(f"\n  library_search top survivors (post-fix): {len(survivors)}")
    if not survivors:
        print("    (every leaked candidate was filtered — would need to re-run "
              "library_search on a wider pool to find a non-leaked top-1)")
    else:
        for i, c in enumerate(survivors[:5], 1):
            sid = c.get("source_id") or ""
            match = "✅" if _ik_first(c.get("smiles") or "") == truth_first else " "
            print(f"    {i:>2}. score={c['score']:.3f} sid={sid:<22} {match} name={c['name']!r}")

    pre_top = lib_cands[0] if lib_cands else None
    post_top = survivors[0] if survivors else None
    print(f"\n  TOP-1 BEFORE: sid={pre_top.get('source_id') if pre_top else '—'}, "
          f"name={pre_top.get('name') if pre_top else '—'}")
    print(f"  TOP-1 AFTER : sid={post_top.get('source_id') if post_top else '—'}, "
          f"name={post_top.get('name') if post_top else '—'}")

    pre_top_leaked = pre_top is not None and pre_top.get("source_id") in excluded
    print(f"  pre-fix top-1 is leaked: {pre_top_leaked}")
    if pre_top and post_top:
        same = pre_top.get("source_id") == post_top.get("source_id")
        print(f"  top-1 changed by filter: {not same}")


def main() -> None:
    if not ARTIFACT.exists():
        sys.exit(
            f"spike artifact missing: {ARTIFACT}. "
            "Re-run scripts/spike/test_library_search_negative.py first."
        )
    excluded = load_exclusion_set()
    print(f"NM-002 exclusion list: {EXCLUSION_LIST}")
    print(f"  excluded GNPS ids: {len(excluded):,}")

    artifact = pickle.loads(ARTIFACT.read_bytes())
    print(f"\nspike artifact fixtures: {sorted(artifact.keys())}")

    for fname in sorted(artifact.keys()):
        report_fixture(fname, artifact[fname], excluded)


if __name__ == "__main__":
    main()
