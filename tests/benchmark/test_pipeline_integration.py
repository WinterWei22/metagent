"""End-to-end pipeline integration test.

Skips the actual GitHub download by pointing the downloader at a fixture
clone — the rest of the pipeline runs unchanged. ClassyFire is disabled
in favour of the SMARTS fallback so the test does not touch the network.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.benchmark.massbank_filter import CompoundPool


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "massbank_records"


@pytest.fixture()
def fake_clone(tmp_path: Path) -> Path:
    """Build a fake MassBank-data clone at ``tmp_path/MassBank-data``.

    Layout::

        tmp_path/MassBank-data/
        ├── .download_complete   (so the downloader skips the network)
        ├── EAWAG/
        │   ├── MSBNK-EAWAG-EC001501.txt
        │   └── MSBNK-EAWAG-EC001551.txt
        └── RIKEN/
            ├── MSBNK-RIKEN-PR010001.txt
            └── MSBNK-RIKEN-PR010014.txt
    """
    clone = tmp_path / "MassBank-data"
    eawag = clone / "EAWAG"
    riken = clone / "RIKEN"
    eawag.mkdir(parents=True)
    riken.mkdir(parents=True)
    for name in ("MSBNK-EAWAG-EC001501.txt", "MSBNK-EAWAG-EC001551.txt"):
        shutil.copy(FIXTURES / name, eawag / name)
    for name in ("MSBNK-RIKEN-PR010001.txt", "MSBNK-RIKEN-PR010014.txt"):
        shutil.copy(FIXTURES / name, riken / name)
    (clone / ".download_complete").write_text("test\t0\n")
    return clone


def test_cli_end_to_end_smoke(fake_clone: Path, tmp_path: Path) -> None:
    """Run the CLI as a subprocess against the fake clone, end-to-end."""
    out_path = tmp_path / "pool.jsonl"
    target_dir = fake_clone.parent  # downloader looks for <parent>/MassBank-data

    cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "build_compound_pool.py"),
        "--target-dir", str(target_dir),
        "--ion-modes", "positive", "negative",
        "--output", str(out_path),
        "--min-peaks", "5",  # our fixtures only have ~12 peaks
        "--classify",
        "--no-classyfire",   # SMARTS fallback only — no network
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    # Useful debug if the assertion below fires:
    if proc.returncode != 0:
        print("STDOUT:", proc.stdout, file=sys.stderr)
        print("STDERR:", proc.stderr, file=sys.stderr)
    assert proc.returncode == 0, f"CLI exited {proc.returncode}"
    assert out_path.exists(), "pool JSONL was not written"

    # Output must be loadable.
    pool = CompoundPool.load(out_path)
    assert len(pool) >= 2  # the two Eawag MS2 records survive
    accs = {r.metadata["accession"] for r in pool.records}
    assert "MSBNK-EAWAG-EC001501" in accs
    assert "MSBNK-EAWAG-EC001551" in accs
    # The two RIKEN GC-EI records are dropped (no precursor_mz, ms_level=MS).
    assert "MSBNK-RIKEN-PR010001" not in accs
    assert "MSBNK-RIKEN-PR010014" not in accs

    # Each record has the expected shape.
    for r in pool.records:
        assert r.spectrum.ionization_mode in {"positive", "negative"}
        assert r.spectrum.adduct
        assert r.spectrum.precursor_mz > 0
        assert max(r.spectrum.intensity) == pytest.approx(1.0)
        assert r.ground_truth["smiles"]
        assert r.ground_truth["inchikey"]
        assert r.ground_truth["compound_class"] is not None  # SMARTS fallback ran


def test_cli_filters_by_contributor(fake_clone: Path, tmp_path: Path) -> None:
    """`--contributors EAWAG` should skip RIKEN (and we'd expect zero RIKEN
    records anyway — they're GC-EI MS1 — but this confirms the filter knob)."""
    out_path = tmp_path / "pool_eawag.jsonl"
    cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "build_compound_pool.py"),
        "--target-dir", str(fake_clone.parent),
        "--contributors", "EAWAG",
        "--output", str(out_path),
        "--min-peaks", "5",
        "--no-classyfire",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert proc.returncode == 0, proc.stderr
    pool = CompoundPool.load(out_path)
    assert all(r.metadata["contributor"] == "EAWAG" for r in pool.records)


def test_cli_runtime_min_peaks_drops_sparse(fake_clone: Path, tmp_path: Path) -> None:
    """Bumping --min-peaks above the fixture peak counts → empty pool, exit 4."""
    out_path = tmp_path / "pool_strict.jsonl"
    cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "build_compound_pool.py"),
        "--target-dir", str(fake_clone.parent),
        "--output", str(out_path),
        "--min-peaks", "9999",  # impossible
        "--no-classyfire",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    # Exit code 4 = "0 records after filtering".
    assert proc.returncode == 4
    assert "0 records survived filtering" in proc.stderr or "After filtering: 0" in proc.stderr
    assert not out_path.exists()
