#!/usr/bin/env bash
# seed-env-images.sh — fill a Railway environment's image volume with artwork,
# sidecars and curation registries over `railway ssh`.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/seed-env-images.sh [options] <environment-id-or-name> [source-dir]
  scripts/seed-env-images.sh [options] --from-bucket <environment-id-or-name>

Copies a local folder (default: test_data/images) into the environment's image
volume. Files are added and same-named files are overwritten; nothing is
deleted. Production is refused.

With --from-bucket nothing is sent from this machine: the environment copies
the seed folder from its bucket source instead (see scripts/seed_images.py),
and files that already exist there are left alone. The environment must be
running a build that has scripts/seed_images.py and the SEED_S3_* variables.

Options:
  --project ID       Railway project      (env: RAILWAY_PROJECT)
  --service ID       Railway service      (env: RAILWAY_SERVICE)
  --remote-dir DIR   target directory     (env: REMOTE_DIR, default /data/images)
  --from-bucket      seed from the bucket folder, not from a local folder
  --prefix PREFIX    bucket folder to use with --from-bucket
                     (default: the environment's SEED_S3_PREFIX, else seed/images/)
  -h, --help         show this help

An option wins over its environment variable, which wins over the default.
EOF
}

PROJECT="${RAILWAY_PROJECT:-182bb54e-88dc-4026-97ed-cffc1d3c1f33}"
SERVICE="${RAILWAY_SERVICE:-91768ac6-edc1-4eb9-846f-2d32d2daeebf}"
REMOTE_DIR="${REMOTE_DIR:-/data/images}"
PRODUCTION_ID="54b8b12f-df88-47f7-aef4-3cd356770e1a"
FROM_BUCKET=0
PREFIX=""
ARGS=()

# Prints the value of an option given as "--name value" or "--name=value".
option_value() {
    if [[ "$1" == *=* ]]; then
        printf '%s' "${1#*=}"
    elif [[ $# -ge 2 ]]; then
        printf '%s' "$2"
    else
        echo "Option ${1} needs a value." >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h | --help)
            usage
            exit 0
            ;;
        --from-bucket)
            FROM_BUCKET=1
            shift
            ;;
        --project | --project=* | --service | --service=* | \
            --remote-dir | --remote-dir=* | --prefix | --prefix=*)
            value="$(option_value "$@")"
            case "${1%%=*}" in
                --project) PROJECT="$value" ;;
                --service) SERVICE="$value" ;;
                --remote-dir) REMOTE_DIR="$value" ;;
                --prefix) PREFIX="$value" ;;
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
[[ "$FROM_BUCKET" -eq 1 ]] && max_args=1
if [[ ${#ARGS[@]} -lt 1 || ${#ARGS[@]} -gt $max_args ]]; then
    usage >&2
    exit 2
fi
if [[ -n "$PREFIX" && "$FROM_BUCKET" -eq 0 ]]; then
    echo "--prefix only applies with --from-bucket." >&2
    exit 2
fi

ENVIRONMENT="${ARGS[0]}"
SOURCE="${ARGS[1]:-test_data/images}"

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
if [[ -n "$PREFIX" && ! "$PREFIX" =~ ^[A-Za-z0-9._/-]+$ ]]; then
    echo "The prefix must be a plain folder path: $PREFIX" >&2
    exit 1
fi

remote() {
    railway ssh --project="$PROJECT" --environment="$ENVIRONMENT" \
        --service="$SERVICE" -- "$@"
}

if [[ "$FROM_BUCKET" -eq 1 ]]; then
    echo "Asking $ENVIRONMENT to seed $REMOTE_DIR from its bucket source"
    prefix_arg=""
    [[ -n "$PREFIX" ]] && prefix_arg=" --prefix '$PREFIX'"
    remote sh -c "python scripts/seed_images.py pull --dest '$REMOTE_DIR'$prefix_arg" </dev/null
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
