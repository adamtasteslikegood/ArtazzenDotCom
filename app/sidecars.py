"""Sidecar JSON storage: schema loading, path safety, metadata I/O."""

import json
import logging
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from jsonschema import ValidationError
from jsonschema import validate as js_validate
from PIL import ExifTags, Image
from starlette import status

from app import config

logger = logging.getLogger(__name__)


def _coerce_bool(value: Any) -> bool:
    """Safely coerce a bool or string to a Python bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically to reduce corruption risk across workers."""
    candidate_path = os.path.realpath(os.fspath(path))
    config_path = os.path.realpath(os.fspath(config.CONFIG_PATH))
    images_root = os.path.realpath(os.fspath(config.IMAGES_DIR))
    is_config = candidate_path == config_path
    is_image_sidecar = candidate_path.startswith(
        images_root + os.sep
    ) and candidate_path.lower().endswith(".json")
    if not (is_config or is_image_sidecar):
        raise ValueError("JSON destination is outside an approved storage root")

    safe_path = Path(candidate_path)
    tmp_path = safe_path.with_suffix(safe_path.suffix + ".tmp")
    text = json.dumps(data, indent=2, ensure_ascii=False)
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(safe_path)


def _load_schema() -> dict[str, Any]:
    try:
        return json.loads(config.SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Unable to load schema at %s: %s", config.SCHEMA_PATH, exc)
        # Minimal fallback
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "default": ""},
                "description": {"type": "string", "default": ""},
                "status": {
                    "type": "string",
                    "enum": ["pending", "approved", "hidden"],
                    "default": "pending",
                },
                "detected_at": {"type": "number", "default": 0},
            },
            "required": ["title", "description", "status", "detected_at"],
            "additionalProperties": False,
        }


def _sanitize_filename(filename: str | None) -> str:
    """Return a safe single-component filename or an empty string.

    Filenames are identifiers in this application, not paths. Rejecting path
    syntax instead of silently stripping it prevents ambiguous uploads and
    gives static analysis a clear allowlist boundary.
    """
    candidate = (filename or "").strip()
    if (
        not candidate
        or "\x00" in candidate
        or "/" in candidate
        or "\\" in candidate
        or ".." in candidate
        or candidate != os.path.basename(candidate)
    ):
        return ""
    return candidate


def _resolve_image_path(filename: str) -> Path:
    """Return a normalized image path contained beneath ``IMAGES_DIR``."""
    safe_name = _sanitize_filename(filename)
    if not safe_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )

    root_path = os.path.realpath(os.fspath(config.IMAGES_DIR))
    full_path = os.path.realpath(os.path.join(root_path, safe_name))
    if not full_path.startswith(root_path + os.sep):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )
    return Path(full_path)


def _allowed_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in config.ALLOWED_IMAGE_EXTENSIONS


def _extract_exif_metadata(image_path: Path) -> dict[str, str]:
    """Return a subset of EXIF metadata relevant to titles and descriptions."""
    data: dict[str, str] = {}
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if not exif:
                return data
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                if tag == "ImageDescription" and value:
                    if isinstance(value, bytes):
                        data["description"] = value.decode(
                            "utf-8", errors="ignore"
                        ).strip()
                    else:
                        data["description"] = str(value).strip()
                if tag == "XPTitle" and value:
                    if isinstance(value, bytes):
                        data["title"] = (
                            value.decode("utf-16-le", errors="ignore")
                            .rstrip("\x00")
                            .strip()
                        )
                    else:
                        data["title"] = str(value).strip()
                if tag == "XPComment" and value and "description" not in data:
                    if isinstance(value, bytes):
                        data["description"] = (
                            value.decode("utf-16-le", errors="ignore")
                            .rstrip("\x00")
                            .strip()
                        )
                    else:
                        data["description"] = str(value).strip()
    except Exception as exc:  # pragma: no cover - dependent on image format
        logger.debug("Unable to extract EXIF from %s: %s", image_path, exc)
    return {k: v for k, v in data.items() if v}


def _ensure_sidecar(image_path: Path, metadata: dict[str, Any]) -> None:
    """Ensure a JSON sidecar exists for the provided image with schema fields."""
    safe_image_path = _resolve_image_path(image_path.name)
    json_path = safe_image_path.with_suffix(".json")
    if json_path.exists():
        return
    schema = _load_schema()
    now = time.time()
    # Base with schema defaults
    sidecar_data: dict[str, Any] = {}
    for key, spec in schema.get("properties", {}).items():
        if "default" in spec:
            sidecar_data[key] = spec["default"]
    # Fill from detected metadata
    sidecar_data["title"] = str(metadata.get("title") or "").strip()
    sidecar_data["description"] = str(metadata.get("description") or "").strip()
    sidecar_data["ai_generated"] = bool(metadata.get("ai_generated", False))
    sidecar_ai_details = (
        metadata.get("ai_details")
        if isinstance(metadata.get("ai_details"), dict)
        else {}
    )
    sidecar_data["ai_details"] = sidecar_ai_details
    sidecar_data["status"] = metadata.get(
        "status",
        "approved" if _coerce_bool(metadata.get("reviewed", False)) else "pending",
    )
    sidecar_data["detected_at"] = float(metadata.get("detected_at", now))
    with config.sidecar_lock:
        _atomic_write_json(json_path, sidecar_data)


def _write_sidecar(image_path: Path, metadata: dict[str, Any]) -> None:
    safe_image_path = _resolve_image_path(image_path.name)
    json_path = safe_image_path.with_suffix(".json")
    with config.sidecar_lock:
        _atomic_write_json(json_path, metadata)


def _set_status_sidecar(image_path: Path, new_status: str) -> None:
    safe_image_path = _resolve_image_path(image_path.name)
    json_path = safe_image_path.with_suffix(".json")
    data: dict[str, Any] = {}
    if json_path.exists():
        with suppress(json.JSONDecodeError, OSError):
            data = json.loads(json_path.read_text(encoding="utf-8"))
    data["status"] = new_status
    data.setdefault("title", "")
    data.setdefault("description", "")
    data.setdefault("ai_generated", False)
    if not isinstance(data.get("ai_details"), dict):
        data["ai_details"] = {}
    data.setdefault("detected_at", time.time())
    _write_sidecar(image_path, data)


def _load_metadata(image_path: Path) -> dict[str, Any]:
    """Load metadata for an image, combining sidecar data and EXIF hints."""
    image_path = _resolve_image_path(image_path.name)
    data: dict[str, Any] = {}
    json_path = image_path.with_suffix(".json")
    if json_path.exists():
        try:
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Unable to load or parse sidecar JSON in %s: %s", json_path, exc
            )

    exif_data = _extract_exif_metadata(image_path)
    if not (data.get("title") or "title" in data) and exif_data.get("title"):
        data["title"] = exif_data["title"]
    if not (data.get("description") or "description" in data) and exif_data.get(
        "description"
    ):
        data["description"] = exif_data["description"]

    data.setdefault("title", "")
    data.setdefault("description", "")
    if "status" not in data and "reviewed" in data:
        data["status"] = "approved" if _coerce_bool(data["reviewed"]) else "pending"
    data.setdefault("status", "pending")
    data.setdefault("detected_at", time.time())
    data.setdefault("ai_generated", False)
    if not isinstance(data.get("ai_details"), dict):
        data["ai_details"] = {}
    return data


def _apply_schema_defaults(
    data: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    for key in required:
        spec = props.get(key, {})
        if key not in data:
            if "default" in spec:
                data[key] = spec["default"]
            elif spec.get("type") == "string":
                data[key] = ""
            elif spec.get("type") == "boolean":
                data[key] = False
            elif spec.get("type") == "number":
                data[key] = 0.0
            elif spec.get("type") == "object":
                data[key] = {}
            else:
                data[key] = None
    # Simple coercions
    if "status" in data and data["status"] not in ("pending", "approved", "hidden"):
        data["status"] = "pending"
    if isinstance(data.get("ai_generated"), str):
        lowered = data["ai_generated"].strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            data["ai_generated"] = True
        elif lowered in {"false", "0", "no", "n"}:
            data["ai_generated"] = False
    if isinstance(data.get("detected_at"), str):
        try:
            data["detected_at"] = float(data["detected_at"])
        except ValueError:
            data["detected_at"] = time.time()
    if not isinstance(data.get("ai_details"), dict):
        data["ai_details"] = {}
    ai_spec = props.get("ai_details", {})
    if isinstance(data.get("ai_details"), dict):
        for sub_key, sub_spec in ai_spec.get("properties", {}).items():
            if sub_key not in data["ai_details"] and "default" in sub_spec:
                data["ai_details"][sub_key] = sub_spec["default"]
    return data


def _validate_and_migrate_sidecars() -> None:
    """Validate all sidecars against the schema and migrate if needed."""
    schema = _load_schema()
    try:
        files = os.listdir(config.IMAGES_DIR)
    except OSError as exc:
        logger.error("Unable to list images for validation: %s", exc)
        return
    for name in files:
        image_path = config.IMAGES_DIR / name
        if not (image_path.is_file() and _allowed_image(name)):
            continue
        _ensure_sidecar(image_path, _load_metadata(image_path))
        json_path = image_path.with_suffix(".json")
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Sidecar %s invalid JSON, recreating", json_path)
            data = {}
        data = _apply_schema_defaults(data, schema)
        try:
            js_validate(instance=data, schema=schema)
        except ValidationError as exc:
            logger.warning("Sidecar %s failed schema validation: %s", json_path, exc)
            data = _apply_schema_defaults(data, schema)
        _write_sidecar(image_path, data)


def get_artwork_files(*, status_filter: str = "approved"):
    """Scan IMAGES_DIR and return metadata for images matching status_filter."""
    artwork = []
    logger.info(f"Scanning for artwork in: {config.IMAGES_DIR}")
    if config.IMAGES_DIR.exists() and config.IMAGES_DIR.is_dir():
        try:
            for filename in os.listdir(config.IMAGES_DIR):
                file_path = config.IMAGES_DIR / filename
                if file_path.is_file() and _allowed_image(filename):
                    meta = _load_metadata(file_path)
                    if status_filter and meta.get("status", "pending") != status_filter:
                        continue
                    image_url = f"{config.IMAGES_URL_PREFIX}/{filename}"
                    meta.update({"url": image_url, "name": filename})
                    artwork.append(meta)
                    logger.debug(f"Loaded metadata for {filename}")
        except OSError as e:
            logger.error(f"Error reading image directory {config.IMAGES_DIR}: {e}")
            return []
    else:
        logger.warning(
            f"Images directory not found or is not a directory: {config.IMAGES_DIR}"
        )

    logger.info(f"Found {len(artwork)} artwork files (filter={status_filter}).")
    return artwork
