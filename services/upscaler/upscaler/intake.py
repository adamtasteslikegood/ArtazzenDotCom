"""Intake guards and the import library in ``imports/``.

Importing only stores a copy. Nothing here processes, resizes or upscales.

Bucket layout written here::

    imports/<id>-<safe-name>.<ext>   the copied bytes, unchanged
    imports/<id>.json                the record (source, size, sha256, ...)
    imports/by-sha/<sha256>.json     {"id": ...} de-duplication index
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import secrets
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from threading import Lock
from typing import Any

from PIL import Image

from upscaler.config import ALLOWED_EXTENSIONS, Settings
from upscaler.storage import Storage

IMPORT_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Uvicorn's synchronous route handlers run in a thread pool. Keep the
# de-duplication check and its writes atomic within this single-process service.
_IMPORT_LOCK = Lock()
logger = logging.getLogger(__name__)

# Pillow's detected format decides the stored extension and MIME type, so a
# JPEG renamed to .png is stored and served as a JPEG. MPO is how Pillow
# reports many camera JPEGs.
_FORMAT_EXT = {
    "JPEG": ".jpg",
    "MPO": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "TIFF": ".tiff",
}

_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
}


class IntakeError(ValueError):
    """The file was refused; the message is safe to show the user."""


@dataclass(frozen=True)
class ImageInfo:
    ext: str
    width: int
    height: int
    format: str


def safe_stem(filename: str) -> str:
    stem = PurePosixPath(filename.replace("\\", "/")).stem
    cleaned = _SAFE_CHARS_RE.sub("-", stem).strip("-.")
    return (cleaned or "image")[:80]


def check_image(data: bytes, filename: str, settings: Settings) -> ImageInfo:
    ext = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise IntakeError(f"{filename}: file type {ext or '(none)'} is not allowed")
    if not data:
        raise IntakeError(f"{filename}: file is empty")
    if len(data) > settings.max_upload_bytes:
        raise IntakeError(
            f"{filename}: larger than the {settings.max_upload_mb:g} MB limit"
        )
    try:
        with warnings.catch_warnings():
            # Pillow warns above ~89 MP; the explicit ceiling below is the
            # limit that applies. Pillow still refuses ~179 MP+ outright.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as img:
                width, height = img.size
                fmt = img.format or ""
                # Check the pixel count from the header before verify() reads
                # further into the file.
                if width * height > settings.max_megapixels * 1_000_000:
                    raise IntakeError(
                        f"{filename}: {width}×{height} exceeds the "
                        f"{settings.max_megapixels:g} MP limit"
                    )
                img.verify()
    except IntakeError:
        raise
    except Image.DecompressionBombError:
        raise IntakeError(f"{filename}: image is too large to open safely") from None
    except Exception:
        raise IntakeError(f"{filename}: not a readable image") from None
    stored_ext = _FORMAT_EXT.get(fmt)
    if stored_ext is None:
        raise IntakeError(
            f"{filename}: image format {fmt or '(unknown)'} is not allowed"
        )
    return ImageInfo(ext=stored_ext, width=width, height=height, format=fmt)


def _record_name(import_id: str) -> str:
    return f"imports/{import_id}.json"


def import_bytes(
    storage: Storage,
    data: bytes,
    filename: str,
    source: dict[str, Any],
    settings: Settings,
) -> tuple[dict[str, Any], bool]:
    """Store a copy in ``imports/``. Returns ``(record, created)``.

    ``created`` is False when identical bytes were already imported; the
    existing record is returned and nothing is written.
    """
    info = check_image(data, filename, settings)
    sha = hashlib.sha256(data).hexdigest()
    index_name = f"imports/by-sha/{sha}.json"
    with _IMPORT_LOCK:
        existing = storage.get_json(index_name)
        if existing:
            record = storage.get_json(_record_name(existing.get("id", "")))
            if record:
                return record, False

        import_id = secrets.token_hex(6)
        object_name = f"imports/{import_id}-{safe_stem(filename)}{info.ext}"
        record = {
            "id": import_id,
            "object": object_name,
            "original_name": PurePosixPath(filename.replace("\\", "/")).name,
            "bytes": len(data),
            "sha256": sha,
            "width": info.width,
            "height": info.height,
            "format": info.format,
            "source": source,
            "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        # Three separate writes; the index goes last so a lookup never finds
        # a half-written import. If a later write fails, remove the earlier
        # ones so a retry starts clean instead of leaving an orphan.
        try:
            storage.put_bytes(object_name, data, _MIME[info.ext])
            storage.put_json(_record_name(import_id), record)
            storage.put_json(index_name, {"id": import_id})
        except Exception:
            # A connection can fail after the bucket accepted a write but
            # before the client received its response. Delete every known key,
            # not only calls that returned successfully; deleting a missing S3
            # key is harmless. Remove the index first so no lookup can discover
            # a record while its cleanup is in progress.
            for name in (index_name, _record_name(import_id), object_name):
                try:
                    storage.delete(name)
                except Exception:
                    logger.exception("Could not remove partial import %s", name)
            raise
        return record, True


def list_imports(storage: Storage) -> list[dict[str, Any]]:
    records = []
    for name in storage.list_names("imports/"):
        stem = PurePosixPath(name).stem
        if (
            name.endswith(".json")
            and IMPORT_ID_RE.match(stem)
            and "/by-sha/" not in name
        ):
            record = storage.get_json(name)
            if record:
                records.append(record)
    return sorted(records, key=lambda r: r.get("imported_at", ""), reverse=True)


def get_import(storage: Storage, import_id: str) -> dict[str, Any] | None:
    if not IMPORT_ID_RE.match(import_id):
        return None
    return storage.get_json(_record_name(import_id))
