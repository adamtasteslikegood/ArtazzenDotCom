#!/usr/bin/env python3
"""Seed an image directory from one archive behind a read-only link.

Usage:
    python scripts/seed_images.py pull [--dest DIR]
    python scripts/seed_images.py start
    python scripts/seed_images.py push SOURCE [--days N] [--dry-run]
    python scripts/seed_images.py link [--days N]

pull   Download the archive at SEED_ARCHIVE_URL and unpack it into DIR
       (default: IMAGES_DIR). Existing files are left alone, so edits made in
       the environment survive the next deploy. The only exception is an
       app-made empty collection or series registry on a volume that still
       has no artwork. Refuses to run in production.
start  What a PR environment runs to start: pull, then run the Procfile's
       web command. A failed or unconfigured pull never stops the app, and
       outside a pull-request environment (Railway names them "<name>-pr-<n>")
       nothing is pulled, so any environment can safely start this way.
push   On a trusted machine: pack a local folder (artwork, sidecars, curation
       registries) into one archive, upload it to the bucket and print a
       read-only link to it. Replaces the previous archive.
link   Print a new read-only link to the archive already in the bucket.

What an environment needs is the link, and nothing else:

    SEED_ARCHIVE_URL           https link to the archive; never a credential

The link is a presigned URL. It can read that one object until it expires
(at most 90 days) and cannot write, delete or list anything. Renew it with
`link` and update the variable.

push and link need the bucket's credentials and the boto3 package. Keep both
on the machine that runs them; do not set these on a Railway environment:

    SEED_S3_ENDPOINT           e.g. https://t3.storageapi.dev
    SEED_S3_BUCKET             the bucket's S3 name (not its display name)
    SEED_S3_ACCESS_KEY_ID
    SEED_S3_SECRET_ACCESS_KEY
    SEED_S3_REGION             default: auto
    SEED_S3_KEY                default: seed/images.tar
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger("seed_images")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KEY = "seed/images.tar"
ARCHIVE_URL_VAR = "SEED_ARCHIVE_URL"
# The longest a presigned link to a Railway bucket may live.
MAX_LINK_DAYS = 90
# Seeding runs before the app starts, so the whole download is bounded.
DOWNLOAD_DEADLINE_SECONDS = 120
PRODUCTION_ENVIRONMENT_ID = "54b8b12f-df88-47f7-aef4-3cd356770e1a"
REQUIRED_VARS = (
    "SEED_S3_ENDPOINT",
    "SEED_S3_BUCKET",
    "SEED_S3_ACCESS_KEY_ID",
    "SEED_S3_SECRET_ACCESS_KEY",
)
# How Railway names the environment it creates for a pull request.
PR_ENVIRONMENT_NAME = re.compile(r"-pr-\d+$")
# The app's lock files (app/curation.py, app/sidecars.py). A running app holds
# its locks on these very files, so they are never copied in either direction:
# a new file under the same name would be a different lock. Kept equal to the
# app's by a test, since this script does not import the app.
REGISTRY_LOCKFILE = PurePosixPath(".curation/.lock")
LOCKFILES = {
    REGISTRY_LOCKFILE,
    PurePosixPath(".curation/.sidecars.lock"),
}
# These are the only existing files an initial seed may replace. The app makes
# them on an empty volume, and their empty values would otherwise hide the
# registries from the seed.
EMPTY_REGISTRIES = {
    PurePosixPath(".curation/collections.json"): "collections",
    PurePosixPath(".curation/series.json"): "series",
}
# Never copied in either direction: the volume's own filesystem folder.
SKIPPED_TOP_LEVEL = {"lost+found"}
# Keep in sync with app.config.ALLOWED_IMAGE_EXTENSIONS without importing the
# application (which creates runtime directories at import time).
ARTWORK_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}


@dataclass(frozen=True)
class SeedSource:
    endpoint: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str
    key: str


def seed_source(environ: Mapping[str, str]) -> SeedSource | None:
    """Where push and link keep the archive, or None with no SEED_S3_* set.

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
        key=(environ.get("SEED_S3_KEY") or DEFAULT_KEY).strip().lstrip("/"),
    )


def production_reason(environ: Mapping[str, str]) -> str | None:
    """Why this environment must not be seeded, or None when it may be."""
    if environ.get("RAILWAY_ENVIRONMENT_ID", "") == PRODUCTION_ENVIRONMENT_ID:
        return "this is the production environment (by id)"
    name = environ.get("RAILWAY_ENVIRONMENT_NAME", "")
    if name.lower().startswith("prod"):
        return f"environment {name!r} is production"
    return None


def is_pr_environment(environ: Mapping[str, str]) -> bool:
    name = environ.get("RAILWAY_ENVIRONMENT_NAME", "")
    return bool(PR_ENVIRONMENT_NAME.search(name))


def make_client(source: SeedSource) -> Any:
    # Only push and link reach this, on a trusted machine: boto3 is not an
    # application dependency and environments never hold these credentials.
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise RuntimeError(
            "push and link need boto3, which the app does not install: "
            "pip install boto3"
        ) from None

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
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 2},
        ),
    )


def _relative_path(member: tarfile.TarInfo) -> PurePosixPath | None:
    """The file path an archive entry maps to under the destination, or None."""
    if member.isdir():
        return None
    if not member.isfile():
        # Links and devices have no place in a seed, whatever they point at.
        logger.warning("Skipping entry that is not a plain file: %r", member.name)
        return None
    path = PurePosixPath(member.name)
    if not path.parts or path.is_absolute() or ".." in path.parts:
        logger.warning("Skipping unsafe entry %r", member.name)
        return None
    if path.parts[0] in SKIPPED_TOP_LEVEL:
        return None
    if path in LOCKFILES:
        return None
    return path


def _sidecars_first(path: PurePosixPath) -> tuple[int, str]:
    # If a pull is cut short, an image must never be on disk without its
    # sidecar: the app would queue it for review with empty metadata.
    return (0 if path.suffix == ".json" else 1, str(path))


def holds_artwork(dest: Path) -> bool:
    """True once ``dest`` has an artwork image the application can read.

    The app creates ``.curation`` with empty registries the first time it
    starts, so a volume can be non-empty and still have nothing worth keeping.
    """
    if not dest.is_dir():
        return False
    return any(
        child.is_file()
        and not child.is_symlink()
        and child.suffix.lower() in ARTWORK_SUFFIXES
        for child in dest.iterdir()
    )


def _is_app_made_empty_registry(path: PurePosixPath, target: Path) -> bool:
    """Whether ``target`` is one of the empty registries made by the app."""
    field = EMPTY_REGISTRIES.get(path)
    if field is None or target.is_symlink() or not target.is_file():
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return (
        isinstance(data, dict)
        and set(data).issubset({"version", field})
        and data.get("version", 1) == 1
        and data.get(field) == []
    )


@contextmanager
def _registry_lock(dest: Path):
    """Use the same cross-process registry lock as ``app.curation``."""
    lockfile = dest.joinpath(*REGISTRY_LOCKFILE.parts)
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lockfile, "a")  # noqa: SIM115 - must remain open for flock
    try:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


def _publish_download(
    partial: str, target: Path, path: PurePosixPath, dest: Path
) -> bool:
    """Publish a complete file without clobbering concurrent changes."""
    if path in EMPTY_REGISTRIES:
        with _registry_lock(dest):
            if target.exists():
                if holds_artwork(dest) or not _is_app_made_empty_registry(path, target):
                    return False
                os.replace(partial, target)
                return True
            try:
                os.link(partial, target)
            except FileExistsError:
                return False
            return True

    # Hard-linking the completed temporary file publishes it atomically and,
    # unlike replace(), fails if an upload created the target in the meantime.
    try:
        os.link(partial, target)
    except FileExistsError:
        return False
    return True


def _is_artwork(path: PurePosixPath) -> bool:
    return len(path.parts) == 1 and path.suffix.lower() in ARTWORK_SUFFIXES


def pull(archive: tarfile.TarFile, dest: Path) -> tuple[int, int]:
    """Unpack the seed archive into ``dest``. Returns (copied, skipped).

    Existing files are always kept, except for the app-made empty collection
    and series registries on a volume that still has no artwork. Those are
    replaced under the same cross-process lock the app uses. A file that
    appears while the copy runs is never replaced.
    """
    paths: dict[PurePosixPath, tarfile.TarInfo] = {}
    for member in archive:
        path = _relative_path(member)
        if path is not None:
            paths[path] = member
    # An artwork image needs its sidecar, from the seed or already in place.
    # Files under .derived and .trash have none and are not artwork here.
    for path in [found for found in paths if _is_artwork(found)]:
        sidecar = path.with_suffix(".json")
        if sidecar not in paths and not (dest / sidecar.name).is_file():
            logger.warning("Skipping %s: the seed has no %s", path, sidecar)
            del paths[path]

    copied = skipped = 0
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    for path in sorted(paths, key=_sidecars_first):
        target = dest.joinpath(*path.parts)
        target_parent = target.parent.resolve()
        if not target_parent.is_relative_to(dest_root):
            logger.warning("Skipping entry outside destination: %s", path)
            continue
        target = target_parent / target.name
        if target.exists() and path not in EMPTY_REGISTRIES:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # Unpack beside the target, then rename: no half-written file is
        # ever visible under its final name.
        handle, partial = tempfile.mkstemp(dir=target.parent, prefix=".seed-")
        os.close(handle)
        try:
            _extract(archive, paths[path], partial)
            os.chmod(partial, 0o644)  # mkstemp makes it owner-only
            if _publish_download(partial, target, path, dest_root):
                copied += 1
            else:
                skipped += 1
        finally:
            if os.path.exists(partial):
                os.remove(partial)
    return copied, skipped


def _extract(archive: tarfile.TarFile, member: tarfile.TarInfo, into: str) -> None:
    source = archive.extractfile(member)
    if source is None:
        raise ValueError(f"cannot read {member.name!r} from the archive")
    with source, open(into, "wb") as out:
        shutil.copyfileobj(source, out)


def fetch_archive(
    url: str,
    into: Path,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    deadline_seconds: float = DOWNLOAD_DEADLINE_SECONDS,
) -> None:
    """Download the archive behind ``url`` to ``into``.

    The link is a secret that grants read access, so it is kept out of every
    message raised here.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"{ARCHIVE_URL_VAR} must be an https link")
    give_up_at = time.monotonic() + deadline_seconds
    try:
        with opener(url, timeout=15) as response, open(into, "wb") as out:
            while chunk := response.read(1024 * 1024):
                if time.monotonic() > give_up_at:
                    raise TimeoutError
                out.write(chunk)
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code in (400, 401, 403):
            hint = (
                ". The link may have expired: run `python scripts/seed_images.py "
                f"link` and update {ARCHIVE_URL_VAR}"
            )
        raise RuntimeError(f"the seed link answered HTTP {exc.code}{hint}") from None
    except TimeoutError:
        raise RuntimeError(
            f"the seed download did not finish in {deadline_seconds:.0f} s"
        ) from None
    except OSError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            f"the seed download failed: {str(reason).replace(url, '<link>')}"
        ) from None


def seed_files(source: Path) -> list[Path]:
    """The files of a local seed folder that belong in the archive."""
    files = []
    for file in sorted(source.rglob("*")):
        if file.is_symlink():
            logger.warning("Skipping symlink %s", file)
            continue
        if not file.is_file():
            continue
        relative = file.relative_to(source)
        if relative.parts[0] in SKIPPED_TOP_LEVEL:
            continue
        if PurePosixPath(relative.as_posix()) in LOCKFILES:
            continue
        files.append(file)
    return files


def _without_owner(member: tarfile.TarInfo) -> tarfile.TarInfo:
    # The archive is read in other environments: leave out who packed it.
    member.uid = member.gid = 0
    member.uname = member.gname = ""
    member.mode = 0o644
    return member


def build_archive(source: Path, into: Path) -> int:
    """Pack a local seed folder into one tar file. Returns the file count."""
    files = seed_files(source)
    # Not compressed: images already are, and a plain tar can be read in any
    # order, which pull needs to put sidecars before their images.
    with tarfile.open(into, "w") as archive:
        for file in files:
            archive.add(
                file,
                arcname=file.relative_to(source).as_posix(),
                recursive=False,
                filter=_without_owner,
            )
    return len(files)


def presigned_link(client: Any, bucket: str, key: str, days: int) -> str:
    """A link that can read the archive, and nothing else, for ``days`` days."""
    if not 1 <= days <= MAX_LINK_DAYS:
        raise ValueError(f"--days must be between 1 and {MAX_LINK_DAYS}")
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=days * 24 * 60 * 60,
    )


def push(client: Any, bucket: str, key: str, source: Path) -> int:
    """Upload ``source`` as the archive at ``key``. Returns the file count."""
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "seed.tar"
        count = build_archive(source, archive)
        client.upload_file(str(archive), bucket, key)
    return count


def images_dir(environ: Mapping[str, str]) -> Path:
    """Same rule as app/config.py: IMAGES_DIR, else Static/images in the repo."""
    configured = environ.get("IMAGES_DIR", "").strip()
    return Path(configured) if configured else REPO_ROOT / "Static" / "images"


def run_pull(
    environ: Mapping[str, str],
    *,
    dest: Path | None = None,
    fetch: Callable[[str, Path], None] = fetch_archive,
) -> str:
    """Pull if configured and allowed. Returns one line saying what happened.

    Raises on a broken configuration or a failed transfer; ``start`` turns
    that into a warning so the app still boots.
    """
    reason = production_reason(environ)
    if reason:
        return f"Seed skipped: {reason}."
    if environ.get("SEED_S3_SECRET_ACCESS_KEY") and environ.get(
        "RAILWAY_ENVIRONMENT_NAME"
    ):
        logger.warning(
            "SEED_S3_* credentials are set in this environment. Only push and "
            "link use them, on a trusted machine: remove them here."
        )
    url = environ.get(ARCHIVE_URL_VAR, "").strip()
    if not url:
        return f"Seed skipped: {ARCHIVE_URL_VAR} is not set."
    target = dest or images_dir(environ)
    with tempfile.TemporaryDirectory() as scratch:
        downloaded = Path(scratch) / "seed.tar"
        fetch(url, downloaded)
        with tarfile.open(downloaded, "r:*") as archive:
            copied, skipped = pull(archive, target)
    if copied == 0 and skipped == 0:
        return "Seed found nothing to copy in the archive."
    return f"Seeded {target}: {copied} files copied, {skipped} already there."


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
    if not is_pr_environment(environ):
        logger.info("Seed skipped: not a pull-request environment.")
    else:
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

    pull_parser = commands.add_parser("pull", help="seed archive -> image directory")
    pull_parser.add_argument("--dest", type=Path, help="default: IMAGES_DIR")

    commands.add_parser("start", help="pull, then run the Procfile web command")

    days_help = f"how long the link works, 1 to {MAX_LINK_DAYS} (default)"
    push_parser = commands.add_parser("push", help="local folder -> archive + link")
    push_parser.add_argument("source", type=Path)
    push_parser.add_argument("--days", type=int, default=MAX_LINK_DAYS, help=days_help)
    push_parser.add_argument("--dry-run", action="store_true")

    link_parser = commands.add_parser("link", help="new link to the stored archive")
    link_parser.add_argument("--days", type=int, default=MAX_LINK_DAYS, help=days_help)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    if args.command == "start":
        start(os.environ)
        return 0  # only reached if exec is replaced in a test

    try:
        if args.command == "pull":
            print(run_pull(os.environ, dest=args.dest))
            return 0
        if args.command == "push":
            if not args.source.is_dir():
                print(f"Source folder not found: {args.source}", file=sys.stderr)
                return 1
            if args.dry_run:
                files = seed_files(args.source)
                for file in files:
                    print(f"would pack {file.relative_to(args.source).as_posix()}")
                print(f"Would pack {len(files)} files into one archive.")
                return 0
        source = seed_source(os.environ)
        if source is None:
            print("No SEED_S3_* variables are set.", file=sys.stderr)
            return 1
        client = make_client(source)
        if args.command == "push":
            # Checked before the upload: a bad --days must not leave a new
            # archive behind with no link to it.
            presigned_link(client, source.bucket, source.key, args.days)
            count = push(client, source.bucket, source.key, args.source)
            print(f"Uploaded {count} files as {source.key!r}.", file=sys.stderr)
        else:
            client.head_object(Bucket=source.bucket, Key=source.key)
        link = presigned_link(client, source.bucket, source.key, args.days)
        expires = datetime.now(UTC) + timedelta(days=args.days)
        print(
            f"Set {ARCHIVE_URL_VAR} on the base environment to the link below "
            f"(not sealed). It works until {expires:%Y-%m-%d}.",
            file=sys.stderr,
        )
        print(link)
        return 0
    except Exception as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
