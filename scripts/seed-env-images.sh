#!/usr/bin/env bash
# seed-env-images.sh — copy a local image folder (artwork, sidecars, curation
# registries) into a Railway environment's image volume over `railway ssh`.
#
# Usage:
#   scripts/seed-env-images.sh <environment-id-or-name> [source-dir]
#
# source-dir defaults to test_data/images. Files are added to the volume and
# same-named files are overwritten; nothing is deleted. Production is refused.
#
# Environment overrides:
#   RAILWAY_PROJECT   project id   (default: the ArtazZen.com project)
#   RAILWAY_SERVICE   service id   (default: the ArtazzenDotCom service)
#   REMOTE_DIR        target dir   (default: /data/images)

set -euo pipefail

PROJECT="${RAILWAY_PROJECT:-182bb54e-88dc-4026-97ed-cffc1d3c1f33}"
SERVICE="${RAILWAY_SERVICE:-91768ac6-edc1-4eb9-846f-2d32d2daeebf}"
REMOTE_DIR="${REMOTE_DIR:-/data/images}"
PRODUCTION_ID="54b8b12f-df88-47f7-aef4-3cd356770e1a"

if [[ $# -lt 1 || $# -gt 2 ]]; then
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

ENVIRONMENT="$1"
SOURCE="${2:-test_data/images}"

shopt -s nocasematch
if [[ "$ENVIRONMENT" == "$PRODUCTION_ID" || "$ENVIRONMENT" == prod* ]]; then
    echo "Refusing to seed the production environment." >&2
    exit 1
fi
shopt -u nocasematch

if [[ ! -d "$SOURCE" ]]; then
    echo "Source folder not found: $SOURCE" >&2
    exit 1
fi
if [[ ! "$REMOTE_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
    echo "REMOTE_DIR must be a plain absolute path: $REMOTE_DIR" >&2
    exit 1
fi

remote() {
    railway ssh --project="$PROJECT" --environment="$ENVIRONMENT" \
        --service="$SERVICE" -- "$@"
}

local_count=$(find "$SOURCE" -type f ! -path '*/lost+found/*' | wc -l)
echo "Sending $local_count files from $SOURCE to $REMOTE_DIR in $ENVIRONMENT"

# base64 keeps the archive intact whatever the ssh channel does to bytes.
tar czf - -C "$SOURCE" --exclude=./lost+found . | base64 | tr -d '\n' |
    remote sh -c "mkdir -p '$REMOTE_DIR' && base64 -d | tar xzf - -C '$REMOTE_DIR' --no-same-owner"

remote_count=$(remote sh -c "find '$REMOTE_DIR' -type f | wc -l" </dev/null | tr -dc '0-9')
echo "Done. $REMOTE_DIR now holds $remote_count files."
