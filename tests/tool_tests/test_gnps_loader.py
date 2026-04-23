"""Unit tests for common.gnps_loader extension dispatch (F14).

The loader now accepts JSON and MGF dumps; CSV dumps are rejected with a
pointer at the companion MGF.
"""
from __future__ import annotations

import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.gnps_loader import iter_records


def test_iter_records_dispatches_on_extension_json(tmp_path):
    body = (
        '[{"spectrum_id": "X1", "Adduct": "[M+H]+", "Ion_Mode": "Positive", '
        '"Precursor_MZ": "123.45", "Smiles": "CCO", '
        '"peaks_json": "[[100,1],[120,0.5],[123,0.1]]"}]'
    )
    path = tmp_path / "mini.json"
    path.write_text(body)

    records = list(iter_records(path))
    assert len(records) == 1
    assert records[0].spectrum_id == "X1"
    assert len(records[0].peaks) == 3


def test_iter_records_dispatches_on_extension_mgf(tmp_path):
    body = (
        "BEGIN IONS\n"
        "SPECTRUM_ID=X1\n"
        "ADDUCT=[M+H]+\n"
        "ION_MODE=positive\n"
        "PRECURSOR_MZ=123.45\n"
        "SMILES=CCO\n"
        "100.0 1.0\n"
        "120.0 0.5\n"
        "123.0 0.1\n"
        "END IONS\n"
    )
    path = tmp_path / "mini.mgf"
    path.write_text(body)

    records = list(iter_records(path))
    assert len(records) == 1
    assert records[0].spectrum_id == "X1"
    assert len(records[0].peaks) == 3


def test_iter_records_rejects_csv_with_helpful_message(tmp_path):
    path = tmp_path / "mini.csv"
    path.write_text("spectrum_id,smiles\nX1,CCO\n")

    with pytest.raises(ValueError, match="no peak column"):
        list(iter_records(path))
