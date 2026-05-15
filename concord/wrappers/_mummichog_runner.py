"""Mummichog runner — executes INSIDE the Py3.10 venv via subprocess (W4 D1).

NEVER import this from main concord code — the OUTER wrapper
``concord.wrappers.mummichog_wrapper.run_mummichog`` spawns a subprocess that
invokes this file with the Py3.10 venv's Python interpreter.

Reads JSON request from stdin, writes JSON response to stdout. No concord
imports — pure stdlib + mummichog only — so it works in the isolated venv
without needing the repo on PYTHONPATH.

JSON in:
    {
      "peaks": [{"mz": float, "p_value": float, "t_score": float|null,
                 "retention_time": float|null, "feature_id": str|null}, ...],
      "mode": "positive" | "negative",
      "ref_db": "mfn" | "hmdb" | "kegg",   # mummichog 2.7.0 only ships mfn out of the box
      "permutations": int,                  # default 100
      "instrument_ppm": int,                # default 10
      "force_primary_ion": bool             # default true
    }

JSON out:
    {
      "pathways": [{"pathway_id": str, "pathway_name": str,
                    "overlap_size": int, "pathway_size": int,
                    "p_value": float, "hits_kegg_ids": [str, ...]}, ...],
      "empirical_compounds": [{"eid": str, "mass_features": [str, ...],
                               "compound_ids": [str, ...]}, ...],
      "stats": {"n_features_in": int, "n_significant": int,
                "n_pathways_tested": int, "wall_time_sec": float},
      "errors": [str, ...]
    }

Mummichog CLI quirks observed in Session 4:
  - Input TSV columns must be exactly:  m/z, retention_time, p-value, t-score, custom_id
  - Output written under <timestamp>.<tag>/{tables, figures, js, result.html}
  - `mummichog.main` ignores --help; only the implicit positional flags work
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path


def _read_request() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("empty stdin")
    return json.loads(raw)


def _write_response(resp: dict) -> None:
    sys.stdout.write(json.dumps(resp, default=str))
    sys.stdout.flush()


def _build_input_tsv(peaks: list[dict], tmpdir: Path) -> Path:
    """Write the 5-column TSV mummichog expects."""
    path = tmpdir / "input.tsv"
    with path.open("w") as f:
        f.write("m/z\tretention_time\tp-value\tt-score\tcustom_id\n")
        for i, p in enumerate(peaks):
            mz = float(p["mz"])
            rt = float(p.get("retention_time") or 0.0)
            pv = float(p["p_value"])
            t = float(p.get("t_score") or 0.0)
            cid = str(p.get("feature_id") or f"feature_{i}")
            f.write(f"{mz:.4f}\t{rt:.1f}\t{pv:.6g}\t{t:.2f}\t{cid}\n")
    return path


def _find_pathway_tsv(outdir: Path) -> Path | None:
    # Mummichog writes to <timestamp>.<tag>/tables/mcg_pathwayanalysis_<tag>.tsv
    candidates = list(outdir.rglob("mcg_pathwayanalysis_*.tsv"))
    return candidates[0] if candidates else None


def _find_emp_tsv(outdir: Path) -> Path | None:
    candidates = list(outdir.rglob("ListOfEmpiricalCompounds.tsv"))
    return candidates[0] if candidates else None


def _parse_pathway_tsv(path: Path, emp_compounds: dict[str, list[str]]) -> list[dict]:
    """Parse mummichog pathway analysis TSV.

    Columns (verified mummichog 2.7.0):
        pathway, overlap_size, pathway_size, p-value,
        overlap_EmpiricalCompounds (id), overlap_features (id),
        overlap_features (name)
    Map EmpCompound IDs (`E123`) → underlying KEGG cpd IDs via emp_compounds dict.
    """
    out = []
    with path.open() as f:
        header = f.readline().rstrip("\n").split("\t")
        i_path = header.index("pathway")
        i_ov = header.index("overlap_size")
        i_sz = header.index("pathway_size")
        i_p = header.index("p-value")
        i_ec = header.index("overlap_EmpiricalCompounds (id)") \
            if "overlap_EmpiricalCompounds (id)" in header else -1
        i_feat = header.index("overlap_features (id)") \
            if "overlap_features (id)" in header else -1
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 4:
                continue
            eids = []
            if i_ec >= 0 and i_ec < len(cols):
                eids = [t.strip() for t in cols[i_ec].split(",") if t.strip()]
            # Collect all KEGG cpd ids from referenced EmpCompounds + from
            # overlap_features column (cpds embedded as 'C00031' etc.)
            kegg_ids: set[str] = set()
            for eid in eids:
                for c in emp_compounds.get(eid, []):
                    if c.startswith("C") and re.match(r"C\d{5,6}$", c):
                        kegg_ids.add(c)
            if i_feat >= 0 and i_feat < len(cols):
                # overlap_features field is like "C00031/C00221,C00208/..."
                # extract any token matching KEGG cpd pattern
                for tok in re.findall(r"\bC\d{5,6}\b", cols[i_feat]):
                    kegg_ids.add(tok)
            out.append({
                "pathway_id": cols[i_path],   # name only (mummichog uses human_mfn names)
                "pathway_name": cols[i_path],
                "overlap_size": int(cols[i_ov]) if cols[i_ov] else 0,
                "pathway_size": int(cols[i_sz]) if cols[i_sz] else 0,
                "p_value": float(cols[i_p]) if cols[i_p] else 1.0,
                "hits_kegg_ids": sorted(kegg_ids),
            })
    return out


def _parse_emp_tsv(path: Path) -> tuple[list[dict], dict[str, list[str]]]:
    """Parse ListOfEmpiricalCompounds.tsv.

    Columns: EID, massfeature_rows, str_row_ion, compounds, compound_names
    Returns (list_of_records, EID → [KEGG cpd ids] dict).
    """
    records = []
    by_eid: dict[str, list[str]] = {}
    with path.open() as f:
        header = f.readline().rstrip("\n").split("\t")
        i_eid = header.index("EID") if "EID" in header else 0
        i_mf = header.index("massfeature_rows") if "massfeature_rows" in header else 1
        i_cp = header.index("compounds") if "compounds" in header else 3
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) <= i_cp:
                continue
            eid = cols[i_eid]
            mf = [t for t in (cols[i_mf] if i_mf < len(cols) else "").split(";") if t]
            # Compound list is "/"-separated within ";" groups e.g. "C00031;C00221,..."
            cp_raw = cols[i_cp]
            cps = re.findall(r"\bC\d{5,6}\b", cp_raw)
            by_eid[eid] = cps
            records.append({
                "eid": eid,
                "mass_features": mf[:10],   # cap
                "compound_ids": cps[:10],   # cap
            })
    return records, by_eid


def run(req: dict) -> dict:
    """Main runner — coordinate mummichog subprocess + parse outputs."""
    t0 = time.time()
    peaks = req.get("peaks", [])
    if not peaks:
        return {
            "pathways": [], "empirical_compounds": [],
            "stats": {"n_features_in": 0, "n_significant": 0,
                      "n_pathways_tested": 0, "wall_time_sec": time.time() - t0},
            "errors": ["empty peaks list"],
        }
    mode = req.get("mode", "positive")
    permutations = int(req.get("permutations", 100))
    instrument_ppm = int(req.get("instrument_ppm", 10))
    force_primary = req.get("force_primary_ion", True)

    with tempfile.TemporaryDirectory(prefix="mcg_runner_") as tmp:
        tmpdir = Path(tmp)
        infile = _build_input_tsv(peaks, tmpdir)
        outdir = tmpdir / "out"; outdir.mkdir()
        cmd = [
            sys.executable, "-m", "mummichog.main",
            "-f", str(infile), "-o", "mcg_w4", "-m", mode,
            "-p", str(permutations), "-u", str(instrument_ppm),
            "-z", str(force_primary), "-k", str(outdir),
        ]
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return {"pathways": [], "empirical_compounds": [],
                    "stats": {"wall_time_sec": time.time() - t0},
                    "errors": ["mummichog subprocess timeout (120s)"]}

        errors: list[str] = []
        if r.returncode != 0:
            errors.append(f"mummichog exit {r.returncode}: {r.stderr[:300]}")
        path_tsv = _find_pathway_tsv(outdir)
        emp_tsv = _find_emp_tsv(outdir)
        emp_records: list[dict] = []
        by_eid: dict[str, list[str]] = {}
        if emp_tsv:
            emp_records, by_eid = _parse_emp_tsv(emp_tsv)
        pathways: list[dict] = []
        if path_tsv:
            pathways = _parse_pathway_tsv(path_tsv, by_eid)

        n_sig = 0
        for line in r.stdout.splitlines():
            m = re.search(r"Using (\d+) features.*as significant list", line)
            if m:
                n_sig = int(m.group(1)); break

        return {
            "pathways": pathways,
            "empirical_compounds": emp_records[:200],  # cap output size
            "stats": {
                "n_features_in": len(peaks),
                "n_significant": n_sig,
                "n_pathways_tested": len(pathways),
                "wall_time_sec": time.time() - t0,
                "exit_code": r.returncode,
            },
            "errors": errors,
        }


def main() -> int:
    try:
        req = _read_request()
    except Exception as e:
        _write_response({"errors": [f"request parse: {e}"], "pathways": [],
                         "empirical_compounds": [], "stats": {}})
        return 2
    try:
        resp = run(req)
    except Exception as e:
        _write_response({"errors": [f"runner exception: {e}",
                                    traceback.format_exc()[:500]],
                         "pathways": [], "empirical_compounds": [], "stats": {}})
        return 3
    _write_response(resp)
    errors = resp.get("errors") or []
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
