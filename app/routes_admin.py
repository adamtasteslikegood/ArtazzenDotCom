"""Admin dashboard, review, upload, import, config, and curation routes."""

import copy
import json
import logging
import os
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette import status

from app import ai_metadata, config, sidecars, watcher
from app.security import _verify_admin
from app.watcher import get_pending_files

logger = logging.getLogger(__name__)

router = APIRouter()


def _select_import_files(candidate: str) -> list[Path]:
    """Select import files from an allowlist enumerated beneath ``IMPORT_ROOT``.

    The request value is used only to match relative path components; it is
    never used to construct or access a filesystem path.
    """
    requested = candidate.strip().replace("\\", "/")
    requested_path = PurePosixPath(requested)
    if (
        not requested
        or "\x00" in requested
        or requested_path.is_absolute()
        or ".." in requested_path.parts
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Import path must be relative to the configured import root",
        )

    requested_parts = (
        () if requested_path == PurePosixPath(".") else requested_path.parts
    )
    root_path = os.path.realpath(os.fspath(config.IMPORT_ROOT))
    root = Path(root_path)
    selected: list[Path] = []
    for discovered_path in root.rglob("*"):
        full_path = os.path.realpath(os.fspath(discovered_path))
        if not full_path.startswith(root_path + os.sep):
            continue
        safe_path = Path(full_path)
        if not safe_path.is_file():
            continue
        relative_parts = safe_path.relative_to(root).parts
        if (
            not requested_parts
            or relative_parts == requested_parts
            or relative_parts[: len(requested_parts)] == requested_parts
        ):
            selected.append(safe_path)

    if not selected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Import path does not exist inside the configured import root",
        )
    return sorted(selected)


@router.get("/admin", response_class=HTMLResponse)
async def admin_home(
    request: Request,
    pending_images: list[dict[str, Any]] = Depends(get_pending_files),
    _: None = Depends(_verify_admin),
) -> HTMLResponse:
    """Render the admin review dashboard."""
    gallery_images = sidecars.get_artwork_files(status_filter="approved")
    return config.templates.TemplateResponse(
        request,
        "reviewAddedFiles.html",
        {
            "pending_images": pending_images,
            "gallery_images": gallery_images,
            "allowed_extensions": sorted(config.ALLOWED_IMAGE_EXTENSIONS),
        },
    )


@router.get("/admin/review", response_class=HTMLResponse)
async def review_added_files(
    request: Request,
    pending_images: list[dict[str, Any]] = Depends(get_pending_files),
    _: None = Depends(_verify_admin),
) -> HTMLResponse:
    """Render the admin review dashboard. Alias for /admin."""
    gallery_images = sidecars.get_artwork_files(status_filter="approved")
    return config.templates.TemplateResponse(
        request,
        "reviewAddedFiles.html",
        {
            "pending_images": pending_images,
            "gallery_images": gallery_images,
            "allowed_extensions": sorted(config.ALLOWED_IMAGE_EXTENSIONS),
        },
    )


@router.get("/admin/api/new-files", response_class=JSONResponse)
async def api_new_files(
    pending: list[dict[str, Any]] = Depends(get_pending_files),
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    """Return pending and gallery files as JSON."""
    gallery = sidecars.get_artwork_files(status_filter="approved")
    return JSONResponse({"pending": pending, "gallery": gallery})


@router.get("/admin/api/collections", response_class=JSONResponse)
async def list_collections(_: None = Depends(_verify_admin)) -> JSONResponse:
    """Return distinct collection values from all sidecars."""
    collections: set[str] = set()
    try:
        for name in os.listdir(config.IMAGES_DIR):
            if not name.lower().endswith(".json"):
                continue
            json_path = config.IMAGES_DIR / name
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                val = str(data.get("collection") or "").strip()
                if val:
                    collections.add(val)
            except (json.JSONDecodeError, OSError):
                continue
    except OSError:
        pass
    return JSONResponse({"collections": sorted(collections)})


@router.get("/admin/config", response_class=JSONResponse)
async def get_admin_config(_: None = Depends(_verify_admin)) -> JSONResponse:
    cfg = config._get_ai_config()
    return JSONResponse(
        {
            "ai": cfg,
            "allowed_extensions": sorted(config.ALLOWED_IMAGE_EXTENSIONS),
        }
    )


@router.post("/admin/config", response_class=JSONResponse)
async def update_admin_config(
    request: Request,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    ai = body.get("ai", body) if isinstance(body, dict) else {}
    cfg = config._get_ai_config()
    if isinstance(ai, dict):
        if "enabled" in ai:
            cfg["enabled"] = config._coerce_bool(ai["enabled"])
        if "model" in ai and isinstance(ai["model"], str) and ai["model"].strip():
            cfg["model"] = ai["model"].strip()
        if "temperature" in ai:
            try:
                t = float(ai["temperature"])
                cfg["temperature"] = max(0.0, min(2.0, t))
            except (TypeError, ValueError):
                pass
        if "max_output_tokens" in ai:
            try:
                tok = int(ai["max_output_tokens"])
                cfg["max_output_tokens"] = max(16, min(4000, tok))
            except (TypeError, ValueError):
                pass
    config.runtime_ai_config = cfg
    config._save_ai_config(cfg)
    return JSONResponse({"ai": cfg, "message": "Configuration updated and saved"})


@router.post("/admin/config/reset", response_class=JSONResponse)
async def reset_admin_config(
    request: Request,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    cfg = config._default_ai_config_from_env()
    config.runtime_ai_config = cfg
    config._save_ai_config(cfg)
    return JSONResponse({"ai": cfg, "message": "Configuration reset to defaults"})


@router.post("/admin/ai/regenerate", response_class=JSONResponse)
async def regenerate_ai_metadata(
    request: Request,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    images = body.get("images") or []
    force = config._coerce_bool(body.get("force", False))
    preview = config._coerce_bool(body.get("preview", False))
    fields: list[str] | None
    if "fields" not in body or body.get("fields") is None:
        fields = None
    elif not isinstance(body.get("fields"), list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fields must be a JSON array. Supported values: title, description, caption, tags",
        )
    else:
        fields = list(
            dict.fromkeys(
                f
                for f in body["fields"]
                if f in ("title", "description", "caption", "tags")
            )
        )
        if not fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No supported fields provided. Use: title, description, caption, tags",
            )

    if not isinstance(images, list) or not images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No images provided"
        )

    updated = []
    errors = []
    for name in images:
        fname = sidecars._sanitize_filename(str(name))
        if not fname or not sidecars._allowed_image(fname):
            errors.append({"name": name, "error": "Unsupported or invalid filename"})
            continue
        path = sidecars._resolve_image_path(fname)
        if not path.exists():
            errors.append({"name": name, "error": "File not found"})
            continue
        try:
            # Work on a candidate copy so a failed AI call can never blank or
            # otherwise corrupt the stored sidecar.
            candidate = copy.deepcopy(sidecars._load_metadata(path))
            if force:
                blank_fields = fields or ["title", "description", "caption", "tags"]
                for f in blank_fields:
                    if f == "tags":
                        candidate["tags"] = []
                    else:
                        candidate[f] = ""
            candidate = ai_metadata._populate_missing_metadata(
                path, candidate, only_fields=fields, persist=False
            )
            ai_status = (candidate.get("ai_details") or {}).get("status")
            if force and ai_status != "success":
                errors.append(
                    {
                        "name": fname,
                        "error": "AI generation failed"
                        + (f" ({ai_status})" if ai_status else "")
                        + "; sidecar left unchanged",
                    }
                )
                continue
            if preview:
                updated.append({"name": fname, "metadata": candidate, "preview": True})
            else:
                sidecars._write_sidecar(path, candidate)
                updated.append({"name": fname, "metadata": candidate})
        except Exception:
            logger.exception("Failed to regenerate metadata for %s", fname)
            errors.append({"name": fname, "error": "Metadata regeneration failed"})

    pending = await watcher.refresh_pending_files(request)
    return JSONResponse({"updated": updated, "errors": errors, "pending": pending})


@router.post("/admin/upload")
async def upload_images(
    request: Request,
    files: list[UploadFile] = File(...),
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded"
        )

    saved: list[str] = []
    skipped: list[str] = []

    for upload in files:
        filename = sidecars._sanitize_filename(upload.filename)
        if not filename:
            continue
        suffix = Path(filename).suffix.lower()
        if not sidecars._allowed_image(filename) and suffix != ".json":
            skipped.append(filename)
            continue

        destination = sidecars._resolve_image_path(filename)
        try:
            # Fast pre-check using Content-Length / spooled size when available
            upload_size = getattr(upload, "size", None)
            if upload_size is not None and upload_size > config.MAX_UPLOAD_SIZE_BYTES:
                logger.warning(
                    "Upload rejected: %s exceeds size limit (%d MB)",
                    filename,
                    config.MAX_UPLOAD_SIZE_BYTES // config.BYTES_PER_MB,
                )
                skipped.append(filename)
                continue
            # Stream to disk in chunks to avoid holding entire files in memory
            bytes_written = 0
            exceeded = False
            with destination.open("wb") as buffer:
                while True:
                    chunk = await upload.read(config.UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > config.MAX_UPLOAD_SIZE_BYTES:
                        exceeded = True
                        break
                    buffer.write(chunk)
            if exceeded:
                destination.unlink(missing_ok=True)
                logger.warning(
                    "Upload rejected: %s exceeds size limit (%d MB)",
                    filename,
                    config.MAX_UPLOAD_SIZE_BYTES // config.BYTES_PER_MB,
                )
                skipped.append(filename)
                continue
            saved.append(filename)
            if sidecars._allowed_image(filename):
                # Ensure sidecar exists for newly uploaded images
                sidecars._ensure_sidecar(
                    destination, sidecars._load_metadata(destination)
                )
        except OSError as exc:
            logger.error("Failed to save %s: %s", filename, exc)
            skipped.append(filename)
        finally:
            upload.file.close()

    message = "Uploaded files successfully" if saved else "No supported files uploaded"
    pending = await watcher.refresh_pending_files(request)
    return JSONResponse(
        {"saved": saved, "skipped": skipped, "message": message, "pending": pending}
    )


@router.post("/admin/import-path")
async def import_from_path(
    request: Request,
    path: str = Form(...),
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    source_files = _select_import_files(path)

    copied: list[str] = []
    skipped: list[str] = []

    for file_path in source_files:
        target_name = sidecars._sanitize_filename(file_path.name)
        if target_name and (
            sidecars._allowed_image(target_name) or file_path.suffix.lower() == ".json"
        ):
            target = sidecars._resolve_image_path(target_name)
            try:
                shutil.copy2(file_path, target)
                copied.append(target_name)
                if sidecars._allowed_image(target_name):
                    sidecars._ensure_sidecar(target, sidecars._load_metadata(target))
            except OSError as exc:
                logger.error("Failed to copy %s: %s", file_path, exc)
                skipped.append(target_name)
        else:
            skipped.append(target_name)

    pending = await watcher.refresh_pending_files(request)
    return JSONResponse({"copied": copied, "skipped": skipped, "pending": pending})


@router.get("/admin/review/{image_name}", response_class=HTMLResponse)
async def preview_image_metadata(
    request: Request,
    image_name: str,
    _: None = Depends(_verify_admin),
) -> HTMLResponse:
    filename = sidecars._sanitize_filename(image_name)
    if not filename or not sidecars._allowed_image(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )

    image_path = sidecars._resolve_image_path(filename)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )

    metadata = sidecars._load_metadata(image_path)
    sidecars._ensure_sidecar(image_path, metadata)
    metadata = ai_metadata._populate_missing_metadata(
        image_path, sidecars._load_metadata(image_path)
    )

    return config.templates.TemplateResponse(
        request,
        "previewImageText.html",
        {
            "image_name": filename,
            "image_url": f"{config.IMAGES_URL_PREFIX}/{filename}",
            "metadata": metadata,
            "review_url": request.url_for("review_added_files"),
        },
    )


@router.post("/admin/metadata/{image_name}")
async def update_image_metadata(
    request: Request,
    image_name: str,
    title: str = Form(""),
    description: str = Form(""),
    caption: str = Form(""),
    tags: str = Form(""),
    artist: str = Form(""),
    copyright_info: str = Form("", alias="copyright"),
    collection: str = Form(""),
    ai_fields: str = Form(""),
    ai_generated: str = Form(""),
    action: str = Form("save"),
    _pending_refresh: list[dict[str, Any]] = Depends(get_pending_files),
    _: None = Depends(_verify_admin),
) -> RedirectResponse:
    filename = sidecars._sanitize_filename(image_name)
    if not filename or not sidecars._allowed_image(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )

    if action == "cancel":
        return RedirectResponse(
            url=request.url_for("review_added_files"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    image_path = sidecars._resolve_image_path(filename)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    clean_metadata = {
        "title": title.strip() or image_path.stem,
        "description": description.strip(),
        "caption": caption.strip(),
        "tags": tag_list,
        "artist": artist.strip(),
        "copyright": copyright_info.strip(),
        "collection": collection.strip(),
    }
    existing = sidecars._load_metadata(image_path)
    prior_ai = set(existing.get("ai_fields", []))
    changed = {
        f
        for f in ("title", "description", "caption", "tags")
        if f in clean_metadata and clean_metadata[f] != existing.get(f)
    }
    # Fields regenerated via preview arrive as a hidden form field; union
    # them so provenance survives the preview-then-save flow.
    incoming_ai = {
        f.strip()
        for f in ai_fields.split(",")
        if f.strip() in ("title", "description", "caption", "tags")
    }
    existing["ai_fields"] = sorted((prior_ai - changed) | incoming_ai)
    if incoming_ai or sidecars._coerce_bool(ai_generated):
        existing["ai_generated"] = True
    existing.update(clean_metadata)
    existing["status"] = "approved"
    sidecars._write_sidecar(image_path, existing)

    return RedirectResponse(
        url=request.url_for("review_added_files"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/unapprove/{image_name}", response_class=JSONResponse)
async def unapprove_image(
    image_name: str,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    """Move an approved image back to pending status."""
    image_path = sidecars._resolve_image_path(image_name)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )
    sidecars._set_status_sidecar(image_path, "pending")
    return JSONResponse({"status": "ok", "image": image_name, "new_status": "pending"})


@router.post("/admin/delete/{image_name}", response_class=JSONResponse)
async def soft_delete_image(
    image_name: str,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    """Soft-delete an image by moving it and its sidecar to .trash/."""
    image_path = sidecars._resolve_image_path(image_name)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )
    trash_dir = config.IMAGES_DIR / ".trash"
    trash_dir.mkdir(exist_ok=True)
    sidecar_path = image_path.with_suffix(".json")
    trash_name = image_path.name
    if (trash_dir / trash_name).exists():
        stem, suffix = image_path.stem, image_path.suffix
        trash_name = f"{stem}_{int(time.time())}{suffix}"
    shutil.move(str(image_path), str(trash_dir / trash_name))
    if sidecar_path.exists():
        trash_sidecar = Path(trash_name).with_suffix(".json").name
        shutil.move(str(sidecar_path), str(trash_dir / trash_sidecar))
    logger.info("Soft-deleted %s to .trash/", image_name)
    return JSONResponse({"status": "ok", "image": image_name, "action": "deleted"})
