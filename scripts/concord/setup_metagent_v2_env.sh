#!/usr/bin/env bash
# metagent-v2 merge sprint (2026-05-20): link the two large concord ETL
# sqlite artefacts from the investigation worktree into the new
# `metagent-v2` worktree, so concord-side tests that depend on them
# (chebi lookup, ramp envelope, dispatcher id negotiation, metaboanalystr
# envelope shape) can reproduce the INV-baseline PASS without running
# `python -m concord.etl.{chebi,metanetx}_etl` (each takes ~tens of
# minutes and downloads ~hundreds of MB).
#
# Why symlinks rather than `cp`:
#   - chebi.sqlite ≈ 378 MB, metanetx.sqlite ≈ 242 MB; duplicating per
#     worktree is wasteful and each ETL re-run would drift the copies.
#   - These DBs are frozen reference data; no per-worktree write need.
#
# Why script + .gitignore rather than hardcoded paths:
#   - Mirrors `setup_w8_path_w.sh` so a fresh clone has a single,
#     replayable entry point.
#   - The sqlite files are gitignored (per data/concord/.gitignore),
#     so the symlinks never accidentally land in a commit.
#
# Required env override (optional):
#   METAGENT_INV_WORKTREE  — investigation worktree absolute path.
#                            Defaults to the canonical 2026-05 layout
#                            below.
set -euo pipefail

INV_WORKTREE="${METAGENT_INV_WORKTREE:-/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5_investigation}"

SQLITES=(chebi.sqlite metanetx.sqlite)

if [ ! -d "$INV_WORKTREE/data/concord" ]; then
    echo "ERROR: investigation worktree concord data dir not found:" >&2
    echo "       $INV_WORKTREE/data/concord" >&2
    echo "       Set METAGENT_INV_WORKTREE to override, or check the layout." >&2
    exit 1
fi

mkdir -p data/concord

for name in "${SQLITES[@]}"; do
    target="$INV_WORKTREE/data/concord/$name"
    link="data/concord/$name"

    if [ ! -f "$target" ]; then
        echo "ERROR: source sqlite missing — $target" >&2
        echo "       Run \`python -m concord.etl.${name%.sqlite}_etl\` in the investigation worktree first." >&2
        exit 1
    fi

    if [ -L "$link" ]; then
        existing="$(readlink "$link")"
        if [ "$existing" = "$target" ]; then
            echo "✓ $name symlink already in place ($link -> $target)"
            continue
        else
            echo "ERROR: $link already exists as a symlink pointing elsewhere:" >&2
            echo "       existing: $existing" >&2
            echo "       wanted:   $target" >&2
            exit 1
        fi
    elif [ -e "$link" ]; then
        echo "ERROR: $link exists and is not a symlink — refusing to overwrite." >&2
        exit 1
    else
        ln -s "$target" "$link"
        echo "✓ $name symlink created ($link -> $target)"
    fi
done

echo
# ---------------------------------------------------------------------------
# V3 Part 2 (2026-06-23): unified structure index for the embedding axis.
#
# `metanetx_struct.sqlite` is OWNED by this worktree (NOT a symlink) and is
# gitignored (~344 MB). It holds MNX->SMILES (full MetaNetX chem_prop, 1.43M
# rows) + {BiGG,KEGG,HMDB,LipidMaps}->MNX bridges, so the resolver can land a
# SMILES for GEM (Human1/Recon2.2) metabolites whose ids never reach ChEBI.
# Build is idempotent: it downloads chem_prop.tsv from MetaNetX (~810 MB, a GET
# with a User-Agent header — MetaNetX rejects HEAD / blank UA) into
# data/concord/metanetx_cache/ if missing, and reuses the investigation
# worktree's chem_xref.tsv when present.
# ---------------------------------------------------------------------------
STRUCT_DB="data/concord/metanetx_struct.sqlite"
if [ -f "$STRUCT_DB" ]; then
    echo "✓ $STRUCT_DB already built"
else
    echo "Building $STRUCT_DB (downloads ~810 MB chem_prop on first run)…"
    PYTHONPATH=. python3 scripts/metagent/v3_build_structure_index.py
fi

echo
echo "✓ metagent-v2 concord env ready. Quick check:"
ls -la data/concord/*.sqlite 2>/dev/null | head -5
echo
echo "Next: PYTHONPATH=. python3 -m pytest tests/concord -q"
