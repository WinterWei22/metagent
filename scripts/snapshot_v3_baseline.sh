#!/bin/bash
# Snapshot the v3 baseline state before Phase A1 architecture upgrade.
#
# Creates 3 layers of protection:
#   1. Git branch snapshot of dirty working tree (verifier/, tools/lipidmaps/)
#   2. Git tag at current HEAD
#   3. Tarball of data + reports + summary outputs
#
# Restore later:
#   Code:  git checkout <tag>
#          git checkout <snapshot-branch>  # if dirty WT needed
#   Data:  tar xzf ~/backups/metagent_<tag>.tar.gz
#
# Usage:
#   bash scripts/snapshot_v3_baseline.sh
#   bash scripts/snapshot_v3_baseline.sh --push   # also push to remote

set -euo pipefail

DATE=$(date +%Y-%m-%d)
TAG="v3-baseline-${DATE}"
SNAPSHOT_BRANCH="v3-state-snapshot-${DATE}"
BACKUP_DIR="${HOME}/backups"
TARBALL="${BACKUP_DIR}/metagent_${TAG}.tar.gz"
PUSH_REMOTE=false

# ---- arg parse ----
for arg in "$@"; do
    case "$arg" in
        --push) PUSH_REMOTE=true ;;
        -h|--help)
            echo "Usage: $0 [--push]"
            echo "  --push   Also push tag + snapshot branch to origin"
            exit 0 ;;
        *)
            echo "Unknown arg: $arg" >&2
            exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."  # repo root

echo "================================================================"
echo "  v3 Baseline Snapshot — ${TAG}"
echo "================================================================"

# ---- preflight ----
if ! command -v git &> /dev/null; then
    echo "ERROR: git not found" >&2; exit 1
fi
if ! command -v tar &> /dev/null; then
    echo "ERROR: tar not found" >&2; exit 1
fi

CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "DETACHED")
echo "Current branch: ${CURRENT_BRANCH}"
echo "Current commit: $(git rev-parse --short HEAD)"
echo

# Check if tag already exists
if git rev-parse "${TAG}" >/dev/null 2>&1; then
    echo "WARN: tag ${TAG} already exists. Re-running this script today is a no-op."
    echo "      Delete tag first if you really want to recreate it:"
    echo "        git tag -d ${TAG}"
    exit 1
fi

# ---- Step 1: snapshot dirty working tree to branch ----
echo "[1/4] Snapshotting dirty working tree to branch ${SNAPSHOT_BRANCH}..."

DIRTY=$(git status --porcelain | wc -l)
if [ "$DIRTY" -eq 0 ]; then
    echo "  Working tree is clean — no snapshot branch needed."
    SNAPSHOT_BRANCH=""
else
    echo "  Found ${DIRTY} dirty/untracked entries. Creating snapshot branch..."
    git checkout -b "${SNAPSHOT_BRANCH}"
    git add -A
    git commit -m "Snapshot: dirty working tree at ${TAG} (verifier v9-PhaseC actual state + LIPID MAPS WIP)" \
        --no-verify
    echo "  Created branch ${SNAPSHOT_BRANCH} at $(git rev-parse --short HEAD)"
    git checkout "${CURRENT_BRANCH}"
    echo "  Returned to ${CURRENT_BRANCH}"
fi
echo

# ---- Step 2: git tag at current HEAD ----
echo "[2/4] Creating git tag ${TAG}..."
git tag -a "${TAG}" -m "v3 baseline before Phase A1 architecture upgrade.

State:
  - LIPID MAPS integrated (lipid bucket 1 -> 11 tasks)
  - Sub-6B v3 evaluated with Opus + verifier v9-PhaseC
  - Case B confirmed: data expansion works, verifier matching gap remains
  - About to start Phase A1 (LLM tool use / agent architecture)

Restore:
  git checkout ${TAG}
  ${SNAPSHOT_BRANCH:+# For dirty working tree: git checkout ${SNAPSHOT_BRANCH}}
  tar xzf ${TARBALL}
"
echo "  Tagged at $(git rev-parse --short HEAD)"
echo

# ---- Step 3: data tarball ----
echo "[3/4] Creating data tarball ${TARBALL}..."
mkdir -p "${BACKUP_DIR}"

# Build list of paths that exist
PATHS_TO_BACKUP=()
for p in \
    data/benchmark/sub6/ \
    data/eval/sub6/v2/ \
    data/eval/sub6/v3/ \
    data/eval/sub6/v1_opus_sanity/ \
    data/processed/hmdb_candidates_npc_classified_v2.jsonl \
    data/processed/nm002_excluded_gnps_ids.json \
    data/lipidmaps/ \
    data/kegg/ \
    results/v2/ \
    results/v3/ \
    reports/ \
    summary/ \
    docs/ ; do
    if [ -e "$p" ]; then
        PATHS_TO_BACKUP+=("$p")
    fi
done

if [ ${#PATHS_TO_BACKUP[@]} -eq 0 ]; then
    echo "ERROR: no backup paths found" >&2
    exit 1
fi

tar czf "${TARBALL}" "${PATHS_TO_BACKUP[@]}"
SIZE=$(du -h "${TARBALL}" | cut -f1)
echo "  Tarball size: ${SIZE}"
echo "  Verified contents:"
tar tzf "${TARBALL}" | head -10 | sed 's/^/    /'
echo "    ... ($(tar tzf "${TARBALL}" | wc -l) total entries)"
echo

# ---- Step 4: optional push ----
if [ "$PUSH_REMOTE" = true ]; then
    echo "[4/4] Pushing to origin..."
    if git remote get-url origin >/dev/null 2>&1; then
        git push origin "${TAG}"
        if [ -n "${SNAPSHOT_BRANCH}" ]; then
            git push origin "${SNAPSHOT_BRANCH}"
        fi
        echo "  Pushed."
    else
        echo "  WARN: no 'origin' remote configured. Skipping push."
    fi
else
    echo "[4/4] Skipping remote push (use --push to enable)."
fi
echo

# ---- summary ----
echo "================================================================"
echo "  DONE."
echo "================================================================"
echo "Tag:              ${TAG}"
echo "Snapshot branch:  ${SNAPSHOT_BRANCH:-<none, working tree was clean>}"
echo "Data tarball:     ${TARBALL} (${SIZE})"
echo
echo "To restore later:"
echo "  Code:  git checkout ${TAG}"
if [ -n "${SNAPSHOT_BRANCH}" ]; then
    echo "  Dirty WT: git checkout ${SNAPSHOT_BRANCH}   # if you need uncommitted changes back"
fi
echo "  Data:  tar xzf ${TARBALL} -C /tmp/restore_test/   # test extract first"
echo
