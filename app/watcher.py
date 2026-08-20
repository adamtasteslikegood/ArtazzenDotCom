"""Background detection of new image files awaiting review."""

import asyncio
import logging
import os
import threading
from typing import Any

from fastapi import FastAPI, Request

from app import ai_metadata, config, sidecars

logger = logging.getLogger(__name__)

# Serializes scans across the watcher task and request-triggered refreshes.
# Overlapping scans could both see the same pending image with missing
# fields and each fire an OpenAI request for it (duplicate work and spend).
_scan_lock = threading.Lock()


def new_files_detected() -> list[dict[str, Any]]:
    """Detect pending image files based on their sidecar JSON status.

    Filesystem scanning and the OpenAI metadata calls inside are
    synchronous/blocking — call this off the event loop (see
    :func:`get_pending_files` and :func:`_watch_image_directory`).
    """
    with _scan_lock:
        return _scan_pending_files()


def _scan_pending_files() -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    try:
        disk_listing = os.listdir(config.IMAGES_DIR)
    except OSError as exc:
        logger.error("Unable to scan images directory %s: %s", config.IMAGES_DIR, exc)
        disk_listing = []

    existing_files = [
        name
        for name in disk_listing
        if (config.IMAGES_DIR / name).is_file() and sidecars._allowed_image(name)
    ]

    for filename in existing_files:
        # One bad entry (unreadable file, rejected name) must not take down
        # the whole background scan.
        try:
            image_path = config.IMAGES_DIR / filename
            metadata = sidecars._load_metadata(image_path)
            sidecars._ensure_sidecar(image_path, metadata)
            metadata = sidecars._load_metadata(image_path)
            metadata = ai_metadata._populate_missing_metadata(image_path, metadata)
        except FileNotFoundError:
            raise  # handled by the watcher loop's retry
        except Exception as exc:
            logger.warning("Skipping %s during watcher scan: %s", filename, exc)
            continue
        if metadata.get("status", "pending") == "pending":
            pending.append(
                {
                    "name": filename,
                    "url": f"{config.IMAGES_URL_PREFIX}/{filename}",
                    "metadata": metadata,
                    "detected_at": metadata.get("detected_at"),
                    "sidecar_exists": image_path.with_suffix(".json").exists(),
                }
            )

    logger.debug("Pending review files: %s", [item["name"] for item in pending])
    return pending


async def _watch_image_directory(app: FastAPI) -> None:
    """Background task that polls for new files."""
    try:
        while True:
            try:
                # The scan blocks (filesystem + synchronous OpenAI calls);
                # run it in a worker thread so requests keep being served.
                pending = await asyncio.to_thread(new_files_detected)
                app.state.pending_images = pending
            except FileNotFoundError:
                logger.debug(
                    "File disappeared during watcher scan, will retry next cycle"
                )
            await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:  # pragma: no cover - clean shutdown
        logger.debug("Image directory watcher cancelled")
        raise


async def get_pending_files(request: Request) -> list[dict[str, Any]]:
    """
    FastAPI dependency to get the list of pending files.
    This runs before routes that depend on it.
    """
    return await refresh_pending_files(request)


async def refresh_pending_files(request: Request) -> list[dict[str, Any]]:
    """Re-scan pending images and keep the application cache in sync.

    The scan is offloaded to a worker thread — running it inline blocked
    the event loop for the full scan (plus any OpenAI calls), stalling
    every in-flight request. The app-state assignment happens back on the
    event loop so no request state crosses threads.
    """
    pending = await asyncio.to_thread(new_files_detected)
    request.app.state.pending_images = pending
    return pending


def _refresh_pending_files(request: Request) -> list[dict[str, Any]]:
    """Synchronous variant, retained for compatibility (main shim export).

    App code calls :func:`refresh_pending_files` instead; this blocks the
    caller for the full scan.
    """
    pending = new_files_detected()
    request.app.state.pending_images = pending
    return pending
