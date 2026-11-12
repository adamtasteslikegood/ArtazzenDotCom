"""The three import sources: the gallery, a browser upload, a server path.

Each one only yields ``(filename, bytes, source_record)``; storing the copy is
:func:`upscaler.intake.import_bytes`'s job.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import quote

import httpx

from upscaler.config import GALLERY_THUMB_WIDTH, Settings
from upscaler.intake import IntakeError

_CHUNK = 1024 * 1024


def read_limited(stream: BinaryIO, limit: int, filename: str) -> bytes:
    """Read at most ``limit`` bytes; refuse anything larger without buffering it."""
    buf = bytearray()
    while chunk := stream.read(_CHUNK):
        buf += chunk
        if len(buf) > limit:
            raise IntakeError(f"{filename}: larger than the upload limit")
    return bytes(buf)


class GalleryError(RuntimeError):
    pass


class GalleryClient:
    """Reads the gallery's existing admin API with the shared credentials."""

    def __init__(
        self, settings: Settings, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.settings.gallery_url)

    def _client(self) -> httpx.Client:
        if not self.configured:
            raise GalleryError("GALLERY_URL is not set")
        return httpx.Client(
            base_url=self.settings.gallery_url,
            auth=(self.settings.admin_username, self.settings.admin_password),
            timeout=httpx.Timeout(30.0, connect=5.0),
            transport=self._transport,
        )

    def list_images(self) -> list[dict[str, Any]]:
        """Pending and approved gallery images, pending first."""
        try:
            with self._client() as client:
                resp = client.get("/admin/api/new-files")
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            raise GalleryError(f"Gallery request failed: {exc}") from None
        images: list[dict[str, Any]] = []
        for status_label, key in (("pending", "pending"), ("approved", "gallery")):
            for item in body.get(key) or []:
                name = item.get("name")
                if not name:
                    continue
                meta = item.get("metadata") or {}
                images.append(
                    {
                        "name": name,
                        "title": item.get("title") or meta.get("title") or "",
                        "status": status_label,
                    }
                )
        return images

    def fetch(self, name: str, *, thumb: bool = False) -> tuple[bytes, str]:
        """Original bytes of a gallery image (or its thumbnail)."""
        if not name or "/" in name or "\\" in name or "\x00" in name:
            raise GalleryError("Invalid gallery image name")
        params = {"w": GALLERY_THUMB_WIDTH} if thumb else None
        try:
            with (
                self._client() as client,
                client.stream(
                    "GET", f"/admin/image/{quote(name)}", params=params
                ) as resp,
            ):
                if resp.status_code == 404:
                    raise GalleryError(f"{name}: not found in the gallery")
                resp.raise_for_status()
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf += chunk
                    if len(buf) > self.settings.max_upload_bytes:
                        raise IntakeError(f"{name}: larger than the upload limit")
                content_type = resp.headers.get("content-type", "")
        except httpx.HTTPError as exc:
            raise GalleryError(f"Gallery request failed: {exc}") from None
        return bytes(buf), content_type


def select_path_files(candidate: str, import_root: Path) -> list[Path]:
    """Files under ``import_root`` matching a relative path.

    Same rules as the gallery's ``_select_import_files``: the request value
    is only matched against relative path components of an enumerated
    allowlist, never joined onto the root.
    """
    requested = candidate.strip().replace("\\", "/")
    requested_path = PurePosixPath(requested)
    if (
        not requested
        or "\x00" in requested
        or requested_path.is_absolute()
        or ".." in requested_path.parts
    ):
        raise IntakeError("Path must be relative to the configured import root")
    requested_parts = (
        () if requested_path == PurePosixPath(".") else requested_path.parts
    )
    root_path = os.path.realpath(os.fspath(import_root))
    root = Path(root_path)
    selected: list[Path] = []
    if root.is_dir():
        for discovered in root.rglob("*"):
            full = os.path.realpath(os.fspath(discovered))
            if not full.startswith(root_path + os.sep):
                continue
            safe = Path(full)
            if not safe.is_file():
                continue
            parts = safe.relative_to(root).parts
            if not requested_parts or parts[: len(requested_parts)] == requested_parts:
                selected.append(safe)
    if not selected:
        raise IntakeError("Path does not exist inside the configured import root")
    return sorted(selected)
