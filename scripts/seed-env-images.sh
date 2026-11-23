#!/usr/bin/env bash
# seed-env-images.sh — fill a Railway environment's image volume with artwork,
# sidecars and curation registries over `railway ssh`.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/seed-env-images.sh [options] <environment-id-or-name> [source-dir]
  scripts/seed-env-images.sh [options] --from-archive <environment-id-or-name>

Copies a local folder (default: test_data/images) into the environment's image
volume. Files are added and same-named files are overwritten; nothing is
deleted. Production is refused.

With --from-archive nothing is sent from this machine: the environment
downloads its seed archive again (see scripts/seed_images.py), and once the
volume holds artwork, files that already exist there are left alone. The
environment must be running a build that has scripts/seed_images.py and the
SEED_ARCHIVE_URL variable.

Options:
  --project ID       Railway project      (env: RAILWAY_PROJECT)
  --service ID       Railway service      (env: RAILWAY_SERVICE)
  --remote-dir DIR   target directory     (env: REMOTE_DIR, default /data/images)
  --from-archive     seed from the environment's seed archive, not from a
                     local folder
  -h, --help         show this help

An option wins over its environment variable, which wins over the default.
EOF
}

PROJECT="${RAILWAY_PROJECT:-182bb54e-88dc-4026-97ed-cffc1d3c1f33}"
SERVICE="${RAILWAY_SERVICE:-91768ac6-edc1-4eb9-846f-2d32d2daeebf}"
REMOTE_DIR="${REMOTE_DIR:-/data/images}"
PRODUCTION_ID="54b8b12f-df88-47f7-aef4-3cd356770e1a"
FROM_ARCHIVE=0
ARGS=()

# Prints the value of an option given as "--name value" or "--name=value".
# An empty value, or one that is itself an option, is a mistake: railway would
# fall back to whatever project or service it considers the default.
option_value() {
    local value
    if [[ "$1" == *=* ]]; then
        value="${1#*=}"
    elif [[ $# -ge 2 ]]; then
        value="$2"
    else
        value=""
    fi
    if [[ -z "$value" || "$value" == -* ]]; then
        echo "Option ${1%%=*} needs a value." >&2
        exit 2
    fi
    printf '%s' "$value"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h | --help)
            usage
            exit 0
            ;;
        --from-archive)
            FROM_ARCHIVE=1
            shift
            ;;
        --project | --project=* | --service | --service=* | \
            --remote-dir | --remote-dir=*)
            value="$(option_value "$@")"
            case "${1%%=*}" in
                --project) PROJECT="$value" ;;
                --service) SERVICE="$value" ;;
                --remote-dir) REMOTE_DIR="$value" ;;
            esac
            if [[ "$1" == *=* ]]; then shift; else shift 2; fi
            ;;
        --)
            shift
            ARGS+=("$@")
            break
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

max_args=2
[[ "$FROM_ARCHIVE" -eq 1 ]] && max_args=1
if [[ ${#ARGS[@]} -lt 1 || ${#ARGS[@]} -gt $max_args ]]; then
    usage >&2
    exit 2
fi

ENVIRONMENT="${ARGS[0]}"
SOURCE="${ARGS[1]:-test_data/images}"

# With an empty name railway picks an environment itself, which may be
# production, and a padded name would slip past the check below.
if [[ ! "$ENVIRONMENT" =~ ^[A-Za-z0-9]([A-Za-z0-9\ ._-]*[A-Za-z0-9])?$ ]]; then
    echo "Not an environment name or id: '$ENVIRONMENT'" >&2
    exit 2
fi

shopt -s nocasematch
if [[ "$ENVIRONMENT" == "$PRODUCTION_ID" || "$ENVIRONMENT" == prod* ]]; then
    echo "Refusing to seed the production environment." >&2
    exit 1
fi
shopt -u nocasematch

if [[ ! "$REMOTE_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
    echo "REMOTE_DIR must be a plain absolute path: $REMOTE_DIR" >&2
    exit 1
fi

remote() {
    railway ssh --project="$PROJECT" --environment="$ENVIRONMENT" \
        --service="$SERVICE" -- "$@"
}

if [[ "$FROM_ARCHIVE" -eq 1 ]]; then
    echo "Asking $ENVIRONMENT to seed $REMOTE_DIR from its seed archive"
    remote sh -c "python scripts/seed_images.py pull --dest '$REMOTE_DIR'" </dev/null
    exit 0
fi

if [[ ! -d "$SOURCE" ]]; then
    echo "Source folder not found: $SOURCE" >&2
    exit 1
fi

local_count=$(find "$SOURCE" -type f ! -path '*/lost+found/*' | wc -l)
echo "Sending $local_count files from $SOURCE to $REMOTE_DIR in $ENVIRONMENT"

# base64 keeps the archive intact whatever the ssh channel does to bytes.
tar czf - -C "$SOURCE" --exclude=./lost+found . | base64 | tr -d '\n' |
    remote sh -c "mkdir -p '$REMOTE_DIR' && base64 -d | tar xzf - -C '$REMOTE_DIR' --no-same-owner"

remote_count=$(remote sh -c "find '$REMOTE_DIR' -type f | wc -l" </dev/null | tr -dc '0-9')
echo "Done. $REMOTE_DIR now holds $remote_count files."
