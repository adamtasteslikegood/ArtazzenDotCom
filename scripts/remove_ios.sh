#!/usr/bin/env bash
# Remove ArtazzenMobile/ from this repo after it has been extracted to its own
# repository at ~/Projects/ArtazzenMobile.
#
# SAFETY: run this ONLY after verifying the new repo exists, has at least one
# commit, and its tree is byte-identical to ArtazzenMobile/ here. The script
# re-checks both before deleting anything. It creates a chore/extract-ios-app
# branch and pushes it; the PR to dev is opened manually afterward (direct
# pushes to dev are blocked by ruleset).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEW_REPO="${HOME}/Projects/ArtazzenMobile"

cd "$REPO_ROOT"

if [ ! -d "$NEW_REPO/.git" ]; then
    echo "ERROR: $NEW_REPO is not a git repository. Aborting." >&2
    exit 1
fi

if ! git -C "$NEW_REPO" rev-parse HEAD >/dev/null 2>&1; then
    echo "ERROR: $NEW_REPO has no commits. Aborting." >&2
    exit 1
fi

echo "Verifying trees are identical (excluding .git, .gitignore, README.md)..."
diff -r ArtazzenMobile "$NEW_REPO" --exclude=.git --exclude=.gitignore --exclude=README.md

echo "Verified. Removing ArtazzenMobile/ on branch chore/extract-ios-app..."
git checkout dev
git pull origin dev
git checkout -b chore/extract-ios-app
git rm -r ArtazzenMobile
git commit -m "chore: remove ArtazzenMobile, extracted to its own repository

The SwiftUI iOS app now lives at ~/Projects/ArtazzenMobile
(initial commit copied verbatim from this repo).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MycKsq6k2TMD2tpurmoVZP"
git push -u origin chore/extract-ios-app

echo "Done. Open a PR targeting dev:"
echo "  gh pr create --base dev --title 'chore: remove ArtazzenMobile (extracted to own repo)'"
