"""Unit tests for RDKit Uncharger + tautomer canonicalization (W4 Background F)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.reconcile.charge_state import (
    ReconciledStructure,
    canonicalize_tautomer,
    reconcile_inchikey_layer,
    uncharge_compound,
)


def test_uncharge_neutral_compound_unchanged():
    """Estradiol (already neutral) → uncharger returns canonical form."""
    smi = "C[C@]12CC[C@H]3[C@@H](CCc4cc(O)ccc43)[C@@H]1CC[C@@H]2O"
    out = uncharge_compound(smi)
    assert out is not None
    assert "O" in out  # still has hydroxyl


def test_uncharge_anion_to_neutral():
    """Carboxylate anion (acetate) → uncharged acetic acid."""
    anion = "CC(=O)[O-]"
    neutral = uncharge_compound(anion)
    assert neutral is not None
    # No '-' charge in output SMILES
    assert "[O-]" not in neutral


def test_uncharge_invalid_returns_none():
    assert uncharge_compound("not_smiles") is None
    assert uncharge_compound("") is None


def test_canonicalize_tautomer_glucose():
    """Glucose tautomer canonicalization should return a valid canonical."""
    smi = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"
    out = canonicalize_tautomer(smi)
    assert out is not None
    # Result should be a valid SMILES (no crash)


def test_reconcile_both_layers_acetate_to_acetic():
    """Acetate → reconcile_inchikey_layer (both) → neutral acetic acid InChIKey."""
    anion = "CC(=O)[O-]"
    rec = reconcile_inchikey_layer(anion, layer="both")
    assert isinstance(rec, ReconciledStructure)
    assert rec.original_inchikey is not None
    assert rec.reconciled_inchikey is not None
    # Original InChIKey ends with -M (anion charge layer); reconciled with -N (neutral)
    assert rec.original_inchikey.endswith("-M") or rec.original_inchikey != rec.reconciled_inchikey
    # block14 should be IDENTICAL (connectivity preserved)
    orig_blk14 = rec.original_inchikey.split("-")[0]
    rec_blk14 = rec.reconciled_inchikey.split("-")[0]
    assert orig_blk14 == rec_blk14, f"block14 changed: {orig_blk14} != {rec_blk14}"


def test_reconcile_layer_charge_only():
    """charge-only layer should change only charge layer (last char)."""
    anion = "CC(=O)[O-]"
    rec = reconcile_inchikey_layer(anion, layer="charge")
    assert rec.original_inchikey is not None
    assert rec.reconciled_inchikey is not None
    # Differ at last char
    assert (rec.original_inchikey != rec.reconciled_inchikey
            or "charge" in rec.layers_changed)


def test_reconcile_invalid_returns_empty():
    rec = reconcile_inchikey_layer("not_smiles")
    assert rec.original_inchikey is None
    assert rec.reconciled_inchikey is None
    assert rec.changed is False


def test_reconcile_already_neutral_no_change():
    """Caffeine is already neutral neutral form → no charge layer change."""
    caffeine = "CN1C=NC2=C1C(=O)N(C)C(=O)N2C"
    rec = reconcile_inchikey_layer(caffeine, layer="charge")
    assert rec.original_inchikey is not None
    assert rec.reconciled_inchikey is not None
    # No charge change → layers_changed empty
    # (tautomer enumerator may still pick a different canonical form,
    # but charge-only path shouldn't trigger any layer change)
    assert "charge" not in rec.layers_changed


# ---------------------------------------------------------------------------
# Patch B2 safeguards (W4 sanity fix 2026-05-16) — added after manual Q4c found:
#   - glucose ring-open: tautomer enumerator changes block14 (wrong reconciliation)
#   - L-arginine: tautomer enumerator drops stereo info (silent stereo loss)
# Safeguards reject those artifacts; final reconciled InChIKey stays pre-tautomer.
# ---------------------------------------------------------------------------


def test_glucose_ring_open_safeguard_block14_changed():
    """Glucose open-chain Fischer SMILES: tautomer enumerator switches block14
    GZCGUPFRVQAUEE → DWJZKGYQNOQQEZ. Safeguard 1 must reject + keep block14 stable.
    """
    smi = "OC[C@H](O)[C@@H](O)[C@H](O)[C@H](O)C=O"   # open-chain glucose
    rec = reconcile_inchikey_layer(smi, layer="both")
    assert rec.original_inchikey is not None
    assert rec.reconciled_inchikey is not None
    # Original and reconciled MUST share block14
    orig_blk = rec.original_inchikey.split("-")[0]
    new_blk = rec.reconciled_inchikey.split("-")[0]
    assert orig_blk == new_blk, (
        f"block14 changed despite safeguard: {orig_blk} → {new_blk}"
    )
    # Safeguard 1 must have fired
    assert "block14_changed" in rec.safeguards_triggered, (
        f"Safeguard 1 didn't trigger for glucose ring-open; safeguards="
        f"{rec.safeguards_triggered}"
    )
    # Reconciled InChIKey must equal original (tautomer step rejected)
    assert rec.reconciled_inchikey == rec.original_inchikey
    # tautomer layer must NOT be in layers_changed (rejected)
    assert "tautomer" not in rec.layers_changed


def test_l_arginine_safeguard_stereo_dropped():
    """L-arginine (with full stereo BYPYZUCNSA): tautomer enumerator drops stereo
    to UHFFFAOYSA. Safeguard 2 must reject + preserve stereo layer.
    """
    smi = "N[C@@H](CCCNC(=N)N)C(=O)O"   # L-arginine, with stereo
    rec = reconcile_inchikey_layer(smi, layer="both")
    assert rec.original_inchikey is not None
    assert rec.reconciled_inchikey is not None
    # Original stereo block must be preserved
    orig_stereo = rec.original_inchikey.split("-")[1]
    new_stereo = rec.reconciled_inchikey.split("-")[1]
    assert orig_stereo == new_stereo, (
        f"stereo silently dropped despite safeguard: {orig_stereo} → {new_stereo}"
    )
    # The orig should be BYPYZUCNSA-prefixed (full stereo), not UHFFFAOYSA
    assert not orig_stereo.startswith("UHFFFAOYSA"), (
        "fixture broken: L-arginine input should have full stereo info"
    )
    # Safeguard 2 must have fired
    assert "stereo_dropped" in rec.safeguards_triggered, (
        f"Safeguard 2 didn't trigger; safeguards={rec.safeguards_triggered}"
    )
    # Reconciled stays at pre-tautomer state
    assert "tautomer" not in rec.layers_changed
