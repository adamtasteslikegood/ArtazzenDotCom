"""Background detection of new image files awaiting review."""

import asyncio
import logging
import os
from typing import Any

from fastapi import FastAPI, Request

from app import ai_metadata, config, sidecars

logger = logging.getLogger(__name__)


def new_files_detected() -> list[dict[str, Any]]:
    """Detect pending image files based on their sidecar JSON status."""
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
        image_path = config.IMAGES_DIR / filename
        metadata = sidecars._load_metadata(image_path)
        sidecars._ensure_sidecar(image_path, metadata)
        metadata = sidecars._load_metadata(image_path)
        metadata = ai_metadata._populate_missing_metadata(image_path, metadata)
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
                pending = new_files_detected()
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
    return _refresh_pending_files(request)


def _refresh_pending_files(request: Request) -> list[dict[str, Any]]:
    """Re-scan pending images and keep the application cache in sync."""
    pending = new_files_detected()
    request.app.state.pending_images = pending
    return pending
