#!/usr/bin/env bash
# Refresh cron-base64/combined.txt and publish a commit when it changed.
# Intended to be invoked by cron from a checked-out repository.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_DIR="${SYNC_REPO_DIR:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}"
LOCK_DIR="$REPO_DIR/.git/combined-text-sync.lock"

if ! command -v git >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
    echo "git and python3 must be installed" >&2
    exit 1
fi

if ! git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "SYNC_REPO_DIR is not a Git working tree: $REPO_DIR" >&2
    exit 1
fi

# Cron executions must never interleave a pull, commit, or push.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "sync already running; skipping"
    exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT HUP INT TERM

cd "$REPO_DIR"

# Bring the server checkout up to date before generating a new version.
git pull --ff-only

python3 cron-base64/sync_sources.py --output cron-base64/combined.txt

if git diff --quiet -- cron-base64/combined.txt; then
    echo "combined text is unchanged; nothing to push"
    exit 0
fi

git config user.name "${SYNC_GIT_NAME:-combined-text-sync}"
git config user.email "${SYNC_GIT_EMAIL:-combined-text-sync@localhost}"
git add cron-base64/combined.txt
git commit -m "chore: refresh combined text"
git push
