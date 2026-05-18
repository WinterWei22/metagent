#!/usr/bin/env bash
# W8 D1: link Path W (v3 Opus baseline) from the main worktree into the
# investigation worktree, so D5 quad-report can read it from the same
# relative path the B1 path uses.
#
# Why a symlink rather than `cp`:
#   - v3 Opus baseline is frozen 2026-05-08; no live-update need.
#   - cp would duplicate ~10 MB inside the investigation worktree.
#
# Why script + .gitignore rather than hardcoded absolute paths:
#   - Reproducible: a fresh `git clone` of either branch can replay this.
#   - Path-portable: Python code reads the relative path
#     `data/eval/sub6/v3/sub6b_opus/` and gets the right files in both
#     worktrees without env-aware branching.
#
# Required env override (optional):
#   METAGENT_MAIN_WORKTREE  — main worktree absolute path. Defaults to
#                             the canonical 2026-05 layout below.
set -euo pipefail

MAIN_WORKTREE="${METAGENT_MAIN_WORKTREE:-/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5}"
TARGET="$MAIN_WORKTREE/data/eval/sub6/v3/sub6b_opus"
LINK="data/eval/sub6/v3/sub6b_opus"

if [ ! -d "$TARGET" ]; then
    echo "ERROR: main worktree v3 Opus baseline not found at $TARGET" >&2
    echo "       Set METAGENT_MAIN_WORKTREE to override, or check the main checkout." >&2
    exit 1
fi

mkdir -p "$(dirname "$LINK")"

if [ -L "$LINK" ]; then
    existing_target="$(readlink "$LINK")"
    if [ "$existing_target" = "$TARGET" ]; then
        echo "✓ Symlink already in place ($LINK -> $TARGET)"
    else
        echo "ERROR: $LINK already exists as a symlink pointing elsewhere:" >&2
        echo "       existing: $existing_target" >&2
        echo "       wanted:   $TARGET" >&2
        exit 1
    fi
elif [ -e "$LINK" ]; then
    echo "ERROR: $LINK exists and is not a symlink — refusing to overwrite." >&2
    exit 1
else
    ln -s "$TARGET" "$LINK"
    echo "✓ Symlink created: $LINK -> $TARGET"
fi

echo
echo "Contents (should list at least sub6b_narratives.jsonl + verdicts_v9_phaseC.jsonl):"
ls -la "$LINK/" | head -10
echo
echo "✓ Path W ready."
