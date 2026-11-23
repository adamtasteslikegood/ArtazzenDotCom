#!/usr/bin/env python3
"""Seed an image directory from a folder in an S3-compatible bucket.

Usage:
    python scripts/seed_images.py pull [--dest DIR] [--prefix PREFIX]
    python scripts/seed_images.py push SOURCE [--prefix PREFIX] [--dry-run]
    python scripts/seed_images.py start

pull   Copy every object under the prefix into DIR (default: IMAGES_DIR).
       Once DIR holds artwork, files that already exist are left alone, so
       edits made in the environment survive the next deploy. Until then the
       seed replaces what is there (the empty registries the app creates on
       its first start). Refuses to run in production.
push   Upload a local folder (artwork, sidecars, curation registries) to the
       prefix, replacing same-named objects. Nothing is deleted.
start  What a PR environment runs to start: pull, then run the Procfile's
       web command. A failed or unconfigured pull never stops the app.

A bucket has no mount point or file path. It is reached over HTTPS at an
endpoint, a bucket name and a key prefix, with credentials:

    SEED_S3_ENDPOINT           e.g. https://t3.storageapi.dev
    SEED_S3_BUCKET             the bucket's S3 name (not its display name)
    SEED_S3_ACCESS_KEY_ID
    SEED_S3_SECRET_ACCESS_KEY
    SEED_S3_REGION             default: auto
    SEED_S3_PREFIX             default: seed/images/

These are separate from the service's own AWS_* variables on purpose: in a
PR environment those point at that environment's own, empty bucket.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

logger = logging.getLogger("seed_images")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PREFIX = "seed/images/"
PRODUCTION_ENVIRONMENT_ID = "54b8b12f-df88-47f7-aef4-3cd356770e1a"
REQUIRED_VARS = (
    "SEED_S3_ENDPOINT",
    "SEED_S3_BUCKET",
    "SEED_S3_ACCESS_KEY_ID",
    "SEED_S3_SECRET_ACCESS_KEY",
)
# Never copied in either direction: the volume's own filesystem folder.
SKIPPED_TOP_LEVEL = {"lost+found"}


@dataclass(frozen=True)
class SeedSource:
    endpoint: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str
    prefix: str


def normalize_prefix(prefix: str) -> str:
    """A key prefix that names a folder: no leading slash, one trailing slash."""
    cleaned = prefix.strip().strip("/")
    return f"{cleaned}/" if cleaned else ""


def seed_source(environ: Mapping[str, str]) -> SeedSource | None:
    """The configured source, or None when no SEED_S3_* variable is set.

    A partial configuration is an error: it is a setup mistake, not a
    decision to skip seeding.
    """
    values = {name: environ.get(name, "").strip() for name in REQUIRED_VARS}
    if not any(values.values()):
        return None
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    return SeedSource(
        endpoint=values["SEED_S3_ENDPOINT"],
        bucket=values["SEED_S3_BUCKET"],
        access_key_id=values["SEED_S3_ACCESS_KEY_ID"],
        secret_access_key=values["SEED_S3_SECRET_ACCESS_KEY"],
        region=environ.get("SEED_S3_REGION", "").strip() or "auto",
        prefix=normalize_prefix(environ.get("SEED_S3_PREFIX") or DEFAULT_PREFIX),
    )


def production_reason(environ: Mapping[str, str]) -> str | None:
    """Why this environment must not be seeded, or None when it may be."""
    if environ.get("RAILWAY_ENVIRONMENT_ID", "") == PRODUCTION_ENVIRONMENT_ID:
        return "this is the production environment (by id)"
    name = environ.get("RAILWAY_ENVIRONMENT_NAME", "")
    if name.lower().startswith("prod"):
        return f"environment {name!r} is production"
    return None


def make_client(source: SeedSource) -> Any:
    # Imported here so the app and the tests never need boto3 at import time.
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=source.endpoint,
        aws_access_key_id=source.access_key_id,
        aws_secret_access_key=source.secret_access_key,
        region_name=source.region,
        # Same settings as services/upscaler: Railway buckets use
        # virtual-hosted-style URLs and reject unrequested CRC checksums.
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "virtual"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            # Seeding runs before the app starts; a dead endpoint must not
            # hold the deploy for long.
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 2},
        ),
    )


def _relative_path(key: str, prefix: str) -> PurePosixPath | None:
    """The file path a key maps to under the destination, or None to skip it."""
    rest = key[len(prefix) :]
    if not rest or rest.endswith("/"):
        return None  # the folder marker itself
    path = PurePosixPath(rest)
    if path.is_absolute() or ".." in path.parts:
        logger.warning("Skipping unsafe key %r", key)
        return None
    if path.parts[0] in SKIPPED_TOP_LEVEL:
        return None
    return path


def _sidecars_first(path: PurePosixPath) -> tuple[int, str]:
    # If a pull is cut short, an image must never be on disk without its
    # sidecar: the app would queue it for review with empty metadata.
    return (0 if path.suffix == ".json" else 1, str(path))


def holds_artwork(dest: Path) -> bool:
    """True once ``dest`` has anything but the app's own bookkeeping folders.

    The app creates ``.curation`` with empty registries the first time it
    starts, so a volume can be non-empty and still have nothing worth keeping.
    """
    if not dest.is_dir():
        return False
    return any(
        not child.name.startswith(".") and child.name not in SKIPPED_TOP_LEVEL
        for child in dest.iterdir()
    )


def pull(client: Any, bucket: str, prefix: str, dest: Path) -> tuple[int, int]:
    """Copy objects under ``prefix`` into ``dest``. Returns (copied, skipped).

    Existing files are kept once ``dest`` holds artwork; before that they are
    replaced, or app-made empty registries would hide the seeded collections.
    """
    paths: dict[PurePosixPath, str] = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            path = _relative_path(obj["Key"], prefix)
            if path is not None:
                paths[path] = obj["Key"]

    copied = skipped = 0
    keep_existing = holds_artwork(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(paths, key=_sidecars_first):
        target = dest.joinpath(*path.parts)
        if keep_existing and target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # Download beside the target, then rename: no half-written file is
        # ever visible under its final name.
        handle, partial = tempfile.mkstemp(dir=target.parent, prefix=".seed-")
        os.close(handle)
        try:
            client.download_file(bucket, paths[path], partial)
            os.chmod(partial, 0o644)  # mkstemp makes it owner-only
            os.replace(partial, target)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
        copied += 1
    return copied, skipped


def push(
    client: Any, bucket: str, prefix: str, source: Path, *, dry_run: bool = False
) -> int:
    """Upload every file under ``source`` to ``prefix``. Returns the count."""
    count = 0
    for file in sorted(p for p in source.rglob("*") if p.is_file()):
        relative = file.relative_to(source)
        if relative.parts[0] in SKIPPED_TOP_LEVEL:
            continue
        key = prefix + relative.as_posix()
        if dry_run:
            print(f"would upload {relative.as_posix()} -> {key}")
        else:
            client.upload_file(str(file), bucket, key)
        count += 1
    return count


def images_dir(environ: Mapping[str, str]) -> Path:
    """Same rule as app/config.py: IMAGES_DIR, else Static/images in the repo."""
    configured = environ.get("IMAGES_DIR", "").strip()
    return Path(configured) if configured else REPO_ROOT / "Static" / "images"


def run_pull(
    environ: Mapping[str, str],
    *,
    dest: Path | None = None,
    prefix: str | None = None,
    client_factory: Any = make_client,
) -> str:
    """Pull if configured and allowed. Returns one line saying what happened.

    Raises on a broken configuration or a failed transfer; ``start`` turns
    that into a warning so the app still boots.
    """
    reason = production_reason(environ)
    if reason:
        return f"Seed skipped: {reason}."
    source = seed_source(environ)
    if source is None:
        return "Seed skipped: no SEED_S3_* variables are set."
    target = dest or images_dir(environ)
    key_prefix = normalize_prefix(prefix) if prefix is not None else source.prefix
    copied, skipped = pull(client_factory(source), source.bucket, key_prefix, target)
    if copied == 0 and skipped == 0:
        return f"Seed found nothing under {key_prefix!r} in the bucket."
    return (
        f"Seeded {target} from {key_prefix!r}: {copied} files copied, "
        f"{skipped} already there."
    )


def procfile_web_command(procfile: Path | None = None) -> str:
    """The ``web:`` command of the Procfile, the one start command of record."""
    path = procfile or REPO_ROOT / "Procfile"
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, command = line.partition(":")
        if sep and name.strip() == "web" and command.strip():
            return command.strip()
    raise ValueError(f"no web command in {path}")


def start(environ: Mapping[str, str]) -> None:
    """Seed, then become the web process. Seeding can never block the start."""
    try:
        logger.info(run_pull(environ))
    except Exception as exc:
        logger.warning("Seed failed, starting without it: %s", exc)
    command = procfile_web_command()
    logger.info("Starting: %s", command)
    sys.stdout.flush()
    sys.stderr.flush()
    # The Procfile line needs a shell ($PORT, quoting); it is the repo's own
    # file, not user input.
    os.execvp("sh", ["sh", "-c", f"exec {command}"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    pull_parser = commands.add_parser("pull", help="bucket folder -> image directory")
    pull_parser.add_argument("--dest", type=Path, help="default: IMAGES_DIR")
    pull_parser.add_argument("--prefix", help=f"default: {DEFAULT_PREFIX}")

    push_parser = commands.add_parser("push", help="local folder -> bucket folder")
    push_parser.add_argument("source", type=Path)
    push_parser.add_argument("--prefix", help=f"default: {DEFAULT_PREFIX}")
    push_parser.add_argument("--dry-run", action="store_true")

    commands.add_parser("start", help="pull, then run the Procfile web command")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    if args.command == "start":
        start(os.environ)
        return 0  # only reached if exec is replaced in a test

    try:
        if args.command == "pull":
            print(run_pull(os.environ, dest=args.dest, prefix=args.prefix))
            return 0
        if not args.source.is_dir():
            print(f"Source folder not found: {args.source}", file=sys.stderr)
            return 1
        source = seed_source(os.environ)
        if source is None:
            print("No SEED_S3_* variables are set.", file=sys.stderr)
            return 1
        prefix = (
            normalize_prefix(args.prefix) if args.prefix is not None else source.prefix
        )
        client = None if args.dry_run else make_client(source)
        count = push(client, source.bucket, prefix, args.source, dry_run=args.dry_run)
        verb = "Would upload" if args.dry_run else "Uploaded"
        print(f"{verb} {count} files to {prefix!r}.")
        return 0
    except Exception as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
