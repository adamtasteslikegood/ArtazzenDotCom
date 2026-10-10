"""Public image URLs, cache headers, WebP derivatives, and CDN purge."""

import hashlib
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

import anyio
import httpx
from fastapi import HTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from starlette import status
from starlette.types import Scope

from app import config, sidecars

logger = logging.getLogger(__name__)

DERIVED_DIRNAME = ".derived"
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
CACHE_UNVERSIONED = "public, max-age=3600"
NO_STORE = {"Cache-Control": "no-store"}

_TOKEN_RE = re.compile(r"^v[0-9a-f]{10}$")
# Sources whose derivatives failed to build, keyed by path with the file
# signature that failed, so a corrupt image is not reopened on every scan.
_failed_derivatives: dict[str, tuple[int, int]] = {}
_derivative_lock = threading.Lock()


# --- URLs -----------------------------------------------------------------


def version_token(path: Path) -> str:
    """Token that changes whenever the file's bytes do ('' if unreadable).

    The change time is included because an import (`shutil.copy2`) keeps the
    source's modified time, so a same-size replacement would otherwise keep
    its year-long immutable URL.
    """
    try:
        stat = path.stat()
    except OSError:
        return ""
    digest = hashlib.sha1(
        f"{stat.st_mtime_ns}-{stat.st_ctime_ns}-{stat.st_size}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    return f"v{digest[:10]}"


def cache_tag(filename: str) -> str:
    """Cloudflare cache tag shared by an image and its derivatives."""
    digest = hashlib.sha1(filename.encode(), usedforsecurity=False).hexdigest()
    return f"img-{digest[:16]}"


def _within(root: Path, relative: str) -> Path | None:
    """Resolve `relative` beneath `root`, or None when it would escape it."""
    root_path = os.path.realpath(os.fspath(root))
    full_path = os.path.realpath(os.path.join(root_path, relative))
    if not full_path.startswith(root_path + os.sep):
        return None
    return Path(full_path)


def derivative_path(filename: str, width: int) -> Path:
    path = _within(config.IMAGES_DIR / DERIVED_DIRNAME, f"{filename}.{width}.webp")
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return path


def _versioned(prefix: str, path: Path, relative: str) -> str:
    token = version_token(path)
    encoded = quote(relative)
    return f"{prefix}/{token}/{encoded}" if token else f"{prefix}/{encoded}"


def public_url(filename: str) -> str:
    """Versioned public URL of an original image."""
    return _versioned(
        config.IMAGES_URL_PREFIX, sidecars._resolve_image_path(filename), filename
    )


def _derivative_is_fresh(source: Path, derived: Path) -> bool:
    try:
        return derived.stat().st_mtime_ns >= source.stat().st_mtime_ns
    except OSError:
        return False


def derivative_url(filename: str, width: int) -> str:
    """Versioned URL of a derivative; the original's URL when none exists."""
    derived = derivative_path(filename, width)
    if _derivative_is_fresh(sidecars._resolve_image_path(filename), derived):
        return _versioned(
            config.IMAGES_URL_PREFIX, derived, f"{DERIVED_DIRNAME}/{derived.name}"
        )
    return public_url(filename)


def add_urls(meta: dict[str, Any], filename: str) -> dict[str, Any]:
    """Attach public URLs: original (`url`), grid thumb, and detail display."""
    meta.update(
        {
            "name": filename,
            "url": public_url(filename),
            "thumb_url": derivative_url(filename, config.THUMB_WIDTH),
            "display_url": derivative_url(filename, config.DISPLAY_WIDTH),
        }
    )
    return meta


def list_artworks(*, status_filter: str = "approved") -> list[dict[str, Any]]:
    """`sidecars.get_artwork_files` with public URLs attached."""
    return [
        add_urls(meta, meta["name"])
        for meta in sidecars.get_artwork_files(status_filter=status_filter)
    ]


def admin_url(filename: str, width: int | None = None) -> str:
    """Authenticated preview URL; works for any status."""
    url = f"/admin/image/{quote(filename)}"
    return f"{url}?w={width}" if width else url


def admin_preview_path(filename: str, width: int | None) -> Path:
    """File the admin preview route should send for the requested width."""
    source = sidecars._resolve_image_path(filename)
    if width in (config.THUMB_WIDTH, config.DISPLAY_WIDTH):
        derived = derivative_path(filename, width)
        if _derivative_is_fresh(source, derived):
            return derived
    return source


def static_url(path: str) -> str:
    """Versioned URL of a file under Static/ (for templates)."""
    return _versioned("/static", config.STATIC_DIR / path, path)


# --- Serving --------------------------------------------------------------


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, headers=NO_STORE)


def _split_token(path: str) -> tuple[str, str]:
    """Split a leading version segment off a mount-relative path."""
    head, _, rest = path.replace(os.sep, "/").partition("/")
    if rest and _TOKEN_RE.match(head):
        return head, rest
    return "", path.replace(os.sep, "/")


def _is_approved(filename: str) -> bool:
    try:
        source = sidecars._resolve_image_path(filename)
    except HTTPException:
        return False
    if not source.is_file():
        return False
    return sidecars._load_metadata(source).get("status", "pending") == "approved"


def _source_filename(relative: str) -> str | None:
    """Image filename a public path refers to, or None if it is not servable."""
    parts = relative.split("/")
    if len(parts) == 1:
        name = parts[0]
    elif len(parts) == 2 and parts[0] == DERIVED_DIRNAME:
        name = ""
        for width in (config.THUMB_WIDTH, config.DISPLAY_WIDTH):
            suffix = f".{width}.webp"
            if parts[1].endswith(suffix):
                name = parts[1][: -len(suffix)]
        if not name:
            return None
    else:
        return None
    if name.startswith(".") or not sidecars._allowed_image(name):
        return None
    return name


class _VersionedFiles(StaticFiles):
    """StaticFiles that understands `/v<token>/` segments and sets caching."""

    url_prefix = ""

    def _root(self) -> Path:
        return Path(str(self.directory))

    def _allowed(self, relative: str) -> str | None:
        """Return a cache tag ('' for none) or None when the path is blocked."""
        raise NotImplementedError

    async def get_response(self, path: str, scope: Scope) -> Response:
        token, relative = _split_token(path)
        tag = await anyio.to_thread.run_sync(self._allowed, relative)
        if tag is None:
            raise _not_found()
        full_path = _within(self._root(), relative)
        if full_path is None:
            raise _not_found()
        current = await anyio.to_thread.run_sync(version_token, full_path)
        if token and token != current:
            if not current:
                raise _not_found()
            # A stale or invented token must not create a new cacheable URL.
            return RedirectResponse(
                f"{self.url_prefix}/{current}/{quote(relative)}",
                status_code=status.HTTP_308_PERMANENT_REDIRECT,
                headers={"Cache-Control": CACHE_UNVERSIONED},
            )
        try:
            response = await super().get_response(relative, scope)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                raise _not_found() from exc
            raise
        if response.status_code in (status.HTTP_200_OK, status.HTTP_304_NOT_MODIFIED):
            response.headers["Cache-Control"] = self._cache_control(bool(token))
            if tag:
                response.headers["Cache-Tag"] = tag
        return response

    def _cache_control(self, versioned: bool) -> str:
        return CACHE_IMMUTABLE if versioned else CACHE_UNVERSIONED


class PublicImageFiles(_VersionedFiles):
    """Serves approved originals and their derivatives; everything else 404."""

    def __init__(self) -> None:
        self.url_prefix = config.IMAGES_URL_PREFIX
        super().__init__(directory=config.IMAGES_DIR, check_dir=False)

    def _root(self) -> Path:
        return config.IMAGES_DIR

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        # Resolved against config.IMAGES_DIR on every request (not the
        # directory captured at mount time); `_allowed` has already limited
        # `path` to an image filename or one of its derivatives.
        full_path = _within(config.IMAGES_DIR, path)
        if full_path is None:
            return "", None
        try:
            return str(full_path), os.stat(full_path)
        except OSError:
            return "", None

    def _allowed(self, relative: str) -> str | None:
        name = _source_filename(relative)
        if name is None or not _is_approved(name):
            return None
        return cache_tag(name)

    def _cache_control(self, versioned: bool) -> str:
        if not versioned:
            return CACHE_UNVERSIONED
        if purge_configured():
            return CACHE_IMMUTABLE
        # Without purge credentials an unapproved image could not be pulled
        # from the edge, so shared caches are capped at a day.
        return f"{CACHE_IMMUTABLE}, s-maxage=86400"


class VersionedStaticFiles(_VersionedFiles):
    """Serves Static/ assets; the images subtree is never served from here."""

    url_prefix = "/static"

    def __init__(self) -> None:
        super().__init__(directory=config.STATIC_DIR)

    def _allowed(self, relative: str) -> str | None:
        if relative == "images" or relative.startswith("images/"):
            return None
        return ""


# --- Derivatives ----------------------------------------------------------


def _signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


def _save_webp(image: Image.Image, target: Path) -> None:
    tmp = target.with_name(f".{target.name}.tmp")
    image.save(tmp, format="WEBP", quality=config.WEBP_QUALITY, method=4)
    os.replace(tmp, target)


def ensure_derivatives(image_path: Path, *, force: bool = False) -> bool:
    """Build missing or stale WebP derivatives; return True if any work ran.

    The thumbnail is always written (never upscaled), so its presence marks
    the source as processed. The display size is written only when the source
    is wider than it. Animated images get no derivatives.
    """
    # One build at a time: an upload and the watcher's backfill can reach the
    # same image together, and a decoded photo is tens of megabytes.
    with _derivative_lock:
        return _ensure_derivatives(image_path, force)


def _ensure_derivatives(image_path: Path, force: bool) -> bool:
    filename = image_path.name
    thumb = derivative_path(filename, config.THUMB_WIDTH)
    key = str(image_path)
    if not force:
        if _derivative_is_fresh(image_path, thumb):
            return False
        if _failed_derivatives.get(key) == _signature(image_path):
            return False
    try:
        thumb.parent.mkdir(exist_ok=True)
        with Image.open(image_path) as opened:
            # MPO (multi-picture JPEG from phone cameras) reports several
            # frames but is a still image; its first frame is the photo.
            if opened.format != "MPO" and getattr(opened, "is_animated", False):
                raise ValueError("animated image")
            # Lets the JPEG decoder downscale while decoding large sources.
            opened.draft("RGB", (config.DISPLAY_WIDTH, config.DISPLAY_WIDTH))
            image = ImageOps.exif_transpose(opened)
            if image.mode not in ("RGB", "RGBA"):
                alpha = "A" in image.getbands() or "transparency" in image.info
                image = image.convert("RGBA" if alpha else "RGB")
            display = derivative_path(filename, config.DISPLAY_WIDTH)
            if image.width > config.DISPLAY_WIDTH:
                image.thumbnail((config.DISPLAY_WIDTH, image.height * 2))
                _save_webp(image, display)
            else:
                display.unlink(missing_ok=True)
            if image.width > config.THUMB_WIDTH:
                image.thumbnail((config.THUMB_WIDTH, image.height * 2))
            _save_webp(image, thumb)
    except Exception as exc:
        logger.warning("No derivatives for %s: %s", filename, exc)
        _failed_derivatives[key] = _signature(image_path)
        remove_derivatives(filename)
        return True
    _failed_derivatives.pop(key, None)
    return True


def remove_derivatives(filename: str) -> None:
    for width in (config.THUMB_WIDTH, config.DISPLAY_WIDTH):
        try:
            derivative_path(filename, width).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove derivative of %s: %s", filename, exc)


# --- CDN purge ------------------------------------------------------------


def purge_configured() -> bool:
    return bool(config.CLOUDFLARE_API_TOKEN and config.CLOUDFLARE_ZONE_ID)


def purge_public(filename: str) -> None:
    """Drop an image and its derivatives from the Cloudflare edge cache.

    Called after an image stops being public. Never raises: the admin action
    that triggered it has already succeeded.
    """
    if not purge_configured():
        logger.info("CDN purge skipped for %s: Cloudflare is not configured", filename)
        return
    try:
        response = httpx.post(
            "https://api.cloudflare.com/client/v4/zones/"
            f"{config.CLOUDFLARE_ZONE_ID}/purge_cache",
            headers={"Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}"},
            json={"tags": [cache_tag(filename)]},
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("CDN purge failed for %s: %s", filename, exc)
