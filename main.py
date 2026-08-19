# main.py
import asyncio
import base64
import json
import logging  # Import logging
import os
import secrets
import shutil
import textwrap
import threading
import time
from contextlib import asynccontextmanager, suppress
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jsonschema import ValidationError
from jsonschema import validate as js_validate
from PIL import ExifTags, Image
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware

# --- Configuration ---
# Get the directory where this script is located
BASE_DIR = Path(__file__).resolve().parent
# Define directories relative to the base directory
# Use the on-disk directory name with the expected capitalization.
# Static files are served from the URL path `/static`, but the folder in
# the repository is named with a capital "S".
STATIC_DIR = BASE_DIR / "Static"
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", STATIC_DIR / "images"))
_USING_VOLUME = IMAGES_DIR != STATIC_DIR / "images"
IMAGES_URL_PREFIX = "/images" if _USING_VOLUME else "/static/images"
IMPORT_ROOT = Path(os.getenv("IMPORT_ROOT", BASE_DIR / "imports"))
GALLERY_TITLE = os.getenv("GALLERY_TITLE", "Artazzen Gallery")
TEMPLATES_DIR = BASE_DIR / "templates"
SCHEMA_PATH = BASE_DIR / "ImageSidecar.schema.json"
CONFIG_PATH = BASE_DIR / "ai_config.json"

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
}

POLL_INTERVAL_SECONDS = 5

ADMIN_USERNAME_ENV = "ADMIN_USERNAME"
ADMIN_PASSWORD_ENV = "ADMIN_PASSWORD"

BYTES_PER_MB = 1024 * 1024
try:
    MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * BYTES_PER_MB
except ValueError:
    MAX_UPLOAD_SIZE_BYTES = 50 * BYTES_PER_MB
UPLOAD_CHUNK_SIZE = 64 * 1024  # 64 KB streaming chunks

OPENAI_API_KEY_ENV_PRIMARY = "MY_OPENAI_API_KEY"
OPENAI_API_KEY_ENV_LEGACY = "My_OpenAI_APIKey"
OPENAI_MODEL_ENV = "OPENAI_IMAGE_METADATA_MODEL"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
try:
    OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
except ValueError:
    OPENAI_TIMEOUT_SECONDS = 30.0

# Create necessary directories if they don't exist
# parents=True creates any necessary parent directories
# exist_ok=True prevents an error if the directory already exists
STATIC_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
IMPORT_ROOT.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True)  # For optional CSS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FastAPI App Setup ---
app = FastAPI(title="Artwork Gallery")

# Mount the Static directory on the '/static' URL path. This makes files
# under 'Static/' accessible via URLs starting with '/static'. For example,
# '/static/images/my_art.jpg' will serve the file 'Static/images/my_art.jpg'.
# The 'name="static"' allows generating URLs using url_for('static', path=...) in templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Set up Jinja2 templating. This allows using HTML files from the 'templates'
# directory to render responses.
templates = Jinja2Templates(directory=TEMPLATES_DIR)

sidecar_lock = threading.Lock()
config_lock = threading.Lock()


def _get_ai_config() -> dict[str, Any]:
    """Return runtime AI config from app.state with env fallbacks."""
    cfg = getattr(app.state, "ai_config", {})
    enabled = bool(cfg.get("enabled", True))
    model = str(cfg.get("model", os.getenv(OPENAI_MODEL_ENV, OPENAI_DEFAULT_MODEL)))
    try:
        temperature = float(cfg.get("temperature", 0.6))
    except (TypeError, ValueError):
        temperature = 0.6
    try:
        max_output_tokens = int(cfg.get("max_output_tokens", 600))
    except (TypeError, ValueError):
        max_output_tokens = 600
    return {
        "enabled": enabled,
        "model": model,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }


def _parse_bool_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    candidate = value.strip().lower()
    if candidate in {"1", "true", "yes", "y", "on"}:
        return True
    if candidate in {"0", "false", "no", "n", "off"}:
        return False
    try:
        return bool(int(candidate))
    except ValueError:
        return default


def _coerce_bool(value: Any) -> bool:
    """Safely coerce a bool or string to a Python bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _parse_float_env(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_int_env(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _default_ai_config_from_env() -> dict[str, Any]:
    return {
        "enabled": _parse_bool_env(os.getenv("AI_METADATA_ENABLED"), True),
        "model": os.getenv(OPENAI_MODEL_ENV, OPENAI_DEFAULT_MODEL),
        "temperature": _parse_float_env(
            os.getenv("OPENAI_IMAGE_METADATA_TEMPERATURE"), 0.6
        ),
        "max_output_tokens": _parse_int_env(
            os.getenv("OPENAI_IMAGE_METADATA_MAX_TOKENS"), 600
        ),
    }


def _sanitize_ai_config(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(_default_ai_config_from_env())
    if isinstance(cfg, dict):
        if "enabled" in cfg:
            out["enabled"] = bool(cfg.get("enabled"))
        if isinstance(cfg.get("model"), str) and cfg.get("model").strip():
            out["model"] = cfg["model"].strip()
        try:
            t = float(cfg.get("temperature", out["temperature"]))
            out["temperature"] = max(0.0, min(2.0, t))
        except (TypeError, ValueError):
            pass
        try:
            tok = int(cfg.get("max_output_tokens", out["max_output_tokens"]))
            out["max_output_tokens"] = max(16, min(4000, tok))
        except (TypeError, ValueError):
            pass
    return out


def _load_ai_config() -> dict[str, Any]:
    base = _default_ai_config_from_env()
    if CONFIG_PATH.exists():
        with suppress(json.JSONDecodeError, OSError):
            persisted = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return _sanitize_ai_config({**base, **(persisted or {})})
    return base


def _save_ai_config(cfg: dict[str, Any]) -> None:
    with config_lock:
        _atomic_write_json(CONFIG_PATH, _sanitize_ai_config(cfg))


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically to reduce corruption risk across workers."""
    candidate_path = os.path.realpath(os.fspath(path))
    config_path = os.path.realpath(os.fspath(CONFIG_PATH))
    images_root = os.path.realpath(os.fspath(IMAGES_DIR))
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
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Unable to load schema at %s: %s", SCHEMA_PATH, exc)
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

    root_path = os.path.realpath(os.fspath(IMAGES_DIR))
    full_path = os.path.realpath(os.path.join(root_path, safe_name))
    if not full_path.startswith(root_path + os.sep):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )
    return Path(full_path)


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
    root_path = os.path.realpath(os.fspath(IMPORT_ROOT))
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


def _allowed_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_IMAGE_EXTENSIONS


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


def _build_openai_prompt(
    image_path: Path,
    metadata: dict[str, Any],
    needed_fields: list[str],
) -> str:
    """Create a deterministic prompt for the OpenAI metadata request."""
    hints: list[str] = []
    for key in ("title", "description", "caption", "artist"):
        if metadata.get(key):
            hints.append(f"Existing {key}: {metadata[key]}")
    if metadata.get("tags"):
        hints.append(f"Existing tags: {', '.join(metadata['tags'])}")
    hint_text = "\n".join(hints) if hints else "No reliable text metadata was detected."

    field_descriptions: dict[str, str] = {
        "title": "a short but descriptive title (<= 80 characters)",
        "description": "an engaging description (<= 400 characters)",
        "caption": "a concise gallery caption (<= 160 characters)",
        "tags": "3-8 descriptive tags for categorization",
    }
    requested_parts = [
        field_descriptions[f] for f in needed_fields if f in field_descriptions
    ]
    requested = " and ".join(requested_parts)

    field_keys = ", ".join(f'"{f}"' for f in needed_fields)
    return textwrap.dedent(f"""
        You are assisting with cataloging artwork. Analyze the provided image
        named '{image_path.name}'. {hint_text}
        Generate {requested}. Respond with JSON containing the keys {field_keys}
        with concise English text suitable for a public art gallery. For tags,
        return an array of lowercase strings. Avoid mentioning that information
        is guessed or unavailable.
        """).strip()


def _prepare_image_for_openai(image_path: Path) -> str | None:
    """Return a data URL encoded version of the image for OpenAI vision models."""
    try:
        with Image.open(image_path) as img:
            if img.mode not in {"RGB", "L"}:
                img = img.convert("RGB")
            max_edge = 1024
            img.thumbnail((max_edge, max_edge))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as exc:  # pragma: no cover - dependent on Pillow support
        logger.warning(
            "Failed to prepare %s for OpenAI metadata request: %s", image_path, exc
        )
        return None


def _get_openai_api_key() -> str | None:
    """Return OpenAI API key from env or optional local module.

    Checks env vars `MY_OPENAI_API_KEY` then legacy `My_OpenAI_APIKey`.
    Falls back to optional my_OpenAI_APIkey.py module if present.
    """
    api_key = os.getenv(OPENAI_API_KEY_ENV_PRIMARY) or os.getenv(
        OPENAI_API_KEY_ENV_LEGACY
    )
    if api_key:
        return api_key
    with suppress(Exception):
        # Lazy import to avoid hard dependency
        import my_OpenAI_APIkey as local_key  # type: ignore

        v = getattr(local_key, "MY_OPENAI_API_KEY", None)
        if v:
            return str(v)
    return None


def _request_openai_metadata(
    image_path: Path,
    metadata: dict[str, Any],
    needed_fields: list[str],
) -> dict[str, Any]:
    """Request metadata from OpenAI and return the response payload."""
    ai_cfg = _get_ai_config()
    model = ai_cfg["model"]
    prompt = _build_openai_prompt(image_path, metadata, needed_fields)
    details: dict[str, Any] = {
        "provider": "openai",
        "model": model,
        "prompt": prompt,
        "response_id": "",
        "finish_reason": "",
        "created": 0.0,
        "attempted_at": time.time(),
        "status": "",
        "error": "",
        "raw_response": {},
    }

    api_key = _get_openai_api_key()
    if not api_key:
        details["status"] = "skipped_no_api_key"
        details["error"] = (
            "Missing OpenAI API key. Set env 'MY_OPENAI_API_KEY' "
            "(or legacy 'My_OpenAI_APIKey'), or provide my_OpenAI_APIkey.py."
        )
        return {"title": "", "description": "", "details": details}

    image_payload = _prepare_image_for_openai(image_path)
    if not image_payload:
        details["status"] = "error_image_encoding"
        details["error"] = "Unable to prepare image for OpenAI request."
        return {"title": "", "description": "", "details": details}

    request_body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You create concise, visitor-friendly metadata for artwork images. "
                            "Always respond with valid JSON only."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_payload},
                ],
            },
        ],
        "max_output_tokens": ai_cfg["max_output_tokens"],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "image_metadata",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        f: (
                            {"type": "array", "items": {"type": "string"}}
                            if f == "tags"
                            else {"type": "string"}
                        )
                        for f in needed_fields
                    },
                    "required": sorted(needed_fields),
                    "additionalProperties": False,
                },
            }
        },
    }
    # Some models (e.g., gpt-5-mini) do not accept 'temperature'
    if not str(model).startswith("gpt-5"):
        request_body["temperature"] = ai_cfg["temperature"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        timeout = httpx.Timeout(OPENAI_TIMEOUT_SECONDS)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=request_body,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.warning("OpenAI metadata request failed: %s", exc)
        details["status"] = "error_http"
        details["error"] = "OpenAI metadata request failed."
        details["error_body"] = ""
        return {"title": "", "description": "", "details": details}

    details["response_id"] = payload.get("id", "")
    details["created"] = float(payload.get("created", details["attempted_at"]))
    details["model"] = payload.get("model", model)
    details["status"] = "success"

    # Extract JSON from Responses API output; support output_json and output_text
    parsed = None
    content_text = ""
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            parts = (item or {}).get("content", []) or []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype in {"output_json", "json"} and isinstance(
                    part.get("json"), dict
                ):
                    parsed = part.get("json")
                    break
                if ptype in {"output_text", "text"}:
                    text_val = part.get("text", "")
                    if isinstance(text_val, str):
                        content_text += text_val
            if parsed is not None:
                break
    # Fallback for older chat-style payloads
    if parsed is None and not content_text:
        choice: dict[str, Any] = next(iter(payload.get("choices", []) or []), {})
        details["finish_reason"] = choice.get("finish_reason", "")
        message = choice.get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [
                part.get("text", "") for part in content if isinstance(part, dict)
            ]
            content_text = "".join(text_parts)
        elif isinstance(content, str):
            content_text = content

    if parsed is None:
        try:
            parsed = json.loads(content_text) if content_text else None
        except json.JSONDecodeError as exc:
            logger.warning("Unable to parse OpenAI metadata response: %s", exc)
            details["status"] = "error_parse"
            details["error"] = "OpenAI metadata response could not be parsed."
            # attach brief output excerpt and types for debugging
            try:
                details["raw_response"] = {
                    "id": payload.get("id"),
                    "usage": payload.get("usage", {}),
                    "output_types": [
                        [
                            (p or {}).get("type")
                            for p in ((it or {}).get("content") or [])
                        ]
                        for it in (output or [])
                    ],
                    "text_excerpt": content_text[:200],
                }
            except Exception:
                details["raw_response"] = {
                    "id": payload.get("id"),
                    "usage": payload.get("usage", {}),
                }
            return {"title": "", "description": "", "details": details}

    # Keep raw id/usage only to avoid bloating sidecar
    details["raw_response"] = {
        "id": payload.get("id"),
        "usage": payload.get("usage", {}),
    }

    result: dict[str, Any] = {"details": details}
    for field in needed_fields:
        val = parsed.get(field)
        if field == "tags" and isinstance(val, list):
            result[field] = [str(t).strip() for t in val if str(t).strip()]
        elif val is not None:
            result[field] = str(val).strip()
        else:
            result[field] = "" if field != "tags" else []
    return result


def _populate_missing_metadata(
    image_path: Path,
    metadata: dict[str, Any],
    only_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Fill missing metadata using OpenAI when configured.

    If only_fields is provided, only regenerate those specific fields.
    Otherwise, regenerate any empty AI-eligible field.
    """
    ai_eligible = ["title", "description", "caption", "tags"]

    if only_fields is not None:
        needed_fields = [f for f in only_fields if f in ai_eligible]
    else:
        needed_fields = []
        for field in ai_eligible:
            val = metadata.get(field)
            if field == "tags":
                if not val:
                    needed_fields.append(field)
            elif not (val or "").strip():
                needed_fields.append(field)

    if not needed_fields:
        return metadata
    if not _get_ai_config().get("enabled", True):
        return metadata

    ai_details = metadata.get("ai_details")
    if not isinstance(ai_details, dict):
        ai_details = {}
    metadata["ai_details"] = ai_details

    if not _get_openai_api_key() and ai_details.get("status") == "skipped_no_api_key":
        return metadata

    result = _request_openai_metadata(image_path, metadata, needed_fields)
    details = result.get("details", {})
    metadata["ai_details"] = details

    if details.get("status") == "success":
        existing_ai_fields = set(metadata.get("ai_fields", []))
        for field in needed_fields:
            val = result.get(field)
            if field == "tags" and isinstance(val, list) and val:
                metadata["tags"] = val
                existing_ai_fields.add("tags")
            elif isinstance(val, str) and val:
                metadata[field] = val
                existing_ai_fields.add(field)
        metadata["ai_fields"] = sorted(existing_ai_fields)
        metadata["ai_generated"] = True
    else:
        metadata.setdefault("ai_generated", False)

    metadata.setdefault("detected_at", time.time())
    metadata.setdefault("status", "pending")
    _write_sidecar(image_path, metadata)
    return metadata


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
    with sidecar_lock:
        _atomic_write_json(json_path, sidecar_data)


def _write_sidecar(image_path: Path, metadata: dict[str, Any]) -> None:
    safe_image_path = _resolve_image_path(image_path.name)
    json_path = safe_image_path.with_suffix(".json")
    with sidecar_lock:
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


def new_files_detected() -> list[dict[str, Any]]:
    """Detect pending image files based on their sidecar JSON status."""
    pending: list[dict[str, Any]] = []
    try:
        disk_listing = os.listdir(IMAGES_DIR)
    except OSError as exc:
        logger.error("Unable to scan images directory %s: %s", IMAGES_DIR, exc)
        disk_listing = []

    existing_files = [
        name
        for name in disk_listing
        if (IMAGES_DIR / name).is_file() and _allowed_image(name)
    ]

    for filename in existing_files:
        image_path = IMAGES_DIR / filename
        metadata = _load_metadata(image_path)
        _ensure_sidecar(image_path, metadata)
        metadata = _load_metadata(image_path)
        metadata = _populate_missing_metadata(image_path, metadata)
        if metadata.get("status", "pending") == "pending":
            pending.append(
                {
                    "name": filename,
                    "url": f"{IMAGES_URL_PREFIX}/{filename}",
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
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:  # pragma: no cover - clean shutdown
        logger.debug("Image directory watcher cancelled")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.ai_config = _load_ai_config()
    _validate_and_migrate_sidecars()
    app.state.pending_images = new_files_detected()
    app.state.watcher_task = asyncio.create_task(_watch_image_directory(app))
    yield
    # Shutdown
    watcher = getattr(app.state, "watcher_task", None)
    if watcher:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


app = FastAPI(title="Artwork Gallery", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if _USING_VOLUME:
    app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

# --- Security ---

_http_basic = HTTPBasic(auto_error=False)


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security-relevant HTTP response headers to every reply."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        return response


app.add_middleware(_SecurityHeadersMiddleware)


def _verify_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_http_basic),
) -> None:
    """FastAPI dependency that enforces HTTP Basic Auth on admin routes.

    Credentials are read from env vars ``ADMIN_USERNAME`` (default: ``admin``)
    and ``ADMIN_PASSWORD`` (required; admin access is disabled when unset).

    With ``auto_error=False`` on the :class:`HTTPBasic` scheme, this function
    receives ``None`` when the browser sends no credentials, allowing it to
    return a 503 when the password is not configured or a 401 prompting for
    credentials.
    """
    expected_password = os.getenv(ADMIN_PASSWORD_ENV, "")
    if not expected_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Admin interface is not configured. "
                f"Set the {ADMIN_PASSWORD_ENV} environment variable."
            ),
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Artwork Admin"'},
        )
    expected_username = os.getenv(ADMIN_USERNAME_ENV, "admin")
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        expected_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Artwork Admin"'},
        )
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin") or request.headers.get("referer", "")
        host = request.headers.get("host", "")
        if origin and host and host not in origin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-origin request rejected",
            )


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
        files = os.listdir(IMAGES_DIR)
    except OSError as exc:
        logger.error("Unable to list images for validation: %s", exc)
        return
    for name in files:
        image_path = IMAGES_DIR / name
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


# --- Helper Function ---
def get_artwork_files(*, status_filter: str = "approved"):
    """Scan IMAGES_DIR and return metadata for images matching status_filter."""
    artwork = []
    logger.info(f"Scanning for artwork in: {IMAGES_DIR}")
    if IMAGES_DIR.exists() and IMAGES_DIR.is_dir():
        try:
            for filename in os.listdir(IMAGES_DIR):
                file_path = IMAGES_DIR / filename
                if file_path.is_file() and _allowed_image(filename):
                    meta = _load_metadata(file_path)
                    if status_filter and meta.get("status", "pending") != status_filter:
                        continue
                    image_url = f"{IMAGES_URL_PREFIX}/{filename}"
                    meta.update({"url": image_url, "name": filename})
                    artwork.append(meta)
                    logger.debug(f"Loaded metadata for {filename}")
        except OSError as e:
            logger.error(f"Error reading image directory {IMAGES_DIR}: {e}")
            return []
    else:
        logger.warning(
            f"Images directory not found or is not a directory: {IMAGES_DIR}"
        )

    logger.info(f"Found {len(artwork)} artwork files (filter={status_filter}).")
    return artwork


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


# --- Routes ---


@app.get("/admin", response_class=HTMLResponse)
async def admin_home(
    request: Request,
    pending_images: list[dict[str, Any]] = Depends(get_pending_files),
    _: None = Depends(_verify_admin),
) -> HTMLResponse:
    """Render the admin review dashboard."""
    gallery_images = get_artwork_files(status_filter="approved")
    return templates.TemplateResponse(
        request,
        "reviewAddedFiles.html",
        {
            "pending_images": pending_images,
            "gallery_images": gallery_images,
            "allowed_extensions": sorted(ALLOWED_IMAGE_EXTENSIONS),
        },
    )


@app.get("/admin/review", response_class=HTMLResponse)
async def review_added_files(
    request: Request,
    pending_images: list[dict[str, Any]] = Depends(get_pending_files),
    _: None = Depends(_verify_admin),
) -> HTMLResponse:
    """Render the admin review dashboard. Alias for /admin."""
    gallery_images = get_artwork_files(status_filter="approved")
    return templates.TemplateResponse(
        request,
        "reviewAddedFiles.html",
        {
            "pending_images": pending_images,
            "gallery_images": gallery_images,
            "allowed_extensions": sorted(ALLOWED_IMAGE_EXTENSIONS),
        },
    )


@app.get("/admin/api/new-files", response_class=JSONResponse)
async def api_new_files(
    pending: list[dict[str, Any]] = Depends(get_pending_files),
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    """Return pending and gallery files as JSON."""
    gallery = get_artwork_files(status_filter="approved")
    return JSONResponse({"pending": pending, "gallery": gallery})


@app.get("/admin/api/collections", response_class=JSONResponse)
async def list_collections(_: None = Depends(_verify_admin)) -> JSONResponse:
    """Return distinct collection values from all sidecars."""
    collections: set[str] = set()
    try:
        for name in os.listdir(IMAGES_DIR):
            if not name.lower().endswith(".json"):
                continue
            json_path = IMAGES_DIR / name
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


@app.get("/admin/config", response_class=JSONResponse)
async def get_admin_config(_: None = Depends(_verify_admin)) -> JSONResponse:
    cfg = _get_ai_config()
    return JSONResponse(
        {
            "ai": cfg,
            "allowed_extensions": sorted(ALLOWED_IMAGE_EXTENSIONS),
        }
    )


@app.post("/admin/config", response_class=JSONResponse)
async def update_admin_config(
    request: Request,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    ai = body.get("ai", body) if isinstance(body, dict) else {}
    cfg = _get_ai_config()
    if isinstance(ai, dict):
        if "enabled" in ai:
            cfg["enabled"] = bool(ai["enabled"])
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
    request.app.state.ai_config = cfg
    _save_ai_config(cfg)
    return JSONResponse({"ai": cfg, "message": "Configuration updated and saved"})


@app.post("/admin/config/reset", response_class=JSONResponse)
async def reset_admin_config(
    request: Request,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    cfg = _default_ai_config_from_env()
    request.app.state.ai_config = cfg
    _save_ai_config(cfg)
    return JSONResponse({"ai": cfg, "message": "Configuration reset to defaults"})


@app.post("/admin/ai/regenerate", response_class=JSONResponse)
async def regenerate_ai_metadata(
    request: Request,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    images = body.get("images") or []
    force = bool(body.get("force", False))
    fields: list[str] | None = body.get("fields")
    if isinstance(fields, list):
        fields = [f for f in fields if f in ("title", "description", "caption", "tags")]
        if not fields:
            fields = None
    else:
        fields = None

    if not isinstance(images, list) or not images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No images provided"
        )

    updated = []
    errors = []
    for name in images:
        fname = _sanitize_filename(str(name))
        if not fname or not _allowed_image(fname):
            errors.append({"name": name, "error": "Unsupported or invalid filename"})
            continue
        path = _resolve_image_path(fname)
        if not path.exists():
            errors.append({"name": name, "error": "File not found"})
            continue
        try:
            meta = _load_metadata(path)
            if force:
                blank_fields = fields or ["title", "description", "caption", "tags"]
                for f in blank_fields:
                    if f == "tags":
                        meta["tags"] = []
                    else:
                        meta[f] = ""
            meta = _populate_missing_metadata(path, meta, only_fields=fields)
            _write_sidecar(path, meta)
            updated.append({"name": fname, "metadata": meta})
        except Exception:
            logger.exception("Failed to regenerate metadata for %s", fname)
            errors.append({"name": fname, "error": "Metadata regeneration failed"})

    pending = _refresh_pending_files(request)
    return JSONResponse({"updated": updated, "errors": errors, "pending": pending})


@app.post("/admin/upload")
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
        filename = _sanitize_filename(upload.filename)
        if not filename:
            continue
        suffix = Path(filename).suffix.lower()
        if not _allowed_image(filename) and suffix != ".json":
            skipped.append(filename)
            continue

        destination = _resolve_image_path(filename)
        try:
            # Fast pre-check using Content-Length / spooled size when available
            upload_size = getattr(upload, "size", None)
            if upload_size is not None and upload_size > MAX_UPLOAD_SIZE_BYTES:
                logger.warning(
                    "Upload rejected: %s exceeds size limit (%d MB)",
                    filename,
                    MAX_UPLOAD_SIZE_BYTES // BYTES_PER_MB,
                )
                skipped.append(filename)
                continue
            # Stream to disk in chunks to avoid holding entire files in memory
            bytes_written = 0
            exceeded = False
            with destination.open("wb") as buffer:
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > MAX_UPLOAD_SIZE_BYTES:
                        exceeded = True
                        break
                    buffer.write(chunk)
            if exceeded:
                destination.unlink(missing_ok=True)
                logger.warning(
                    "Upload rejected: %s exceeds size limit (%d MB)",
                    filename,
                    MAX_UPLOAD_SIZE_BYTES // BYTES_PER_MB,
                )
                skipped.append(filename)
                continue
            saved.append(filename)
            if _allowed_image(filename):
                # Ensure sidecar exists for newly uploaded images
                _ensure_sidecar(destination, _load_metadata(destination))
        except OSError as exc:
            logger.error("Failed to save %s: %s", filename, exc)
            skipped.append(filename)
        finally:
            upload.file.close()

    message = "Uploaded files successfully" if saved else "No supported files uploaded"
    pending = _refresh_pending_files(request)
    return JSONResponse(
        {"saved": saved, "skipped": skipped, "message": message, "pending": pending}
    )


@app.post("/admin/import-path")
async def import_from_path(
    request: Request,
    path: str = Form(...),
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    source_files = _select_import_files(path)

    copied: list[str] = []
    skipped: list[str] = []

    for file_path in source_files:
        target_name = _sanitize_filename(file_path.name)
        if target_name and (
            _allowed_image(target_name) or file_path.suffix.lower() == ".json"
        ):
            target = _resolve_image_path(target_name)
            try:
                shutil.copy2(file_path, target)
                copied.append(target_name)
                if _allowed_image(target_name):
                    _ensure_sidecar(target, _load_metadata(target))
            except OSError as exc:
                logger.error("Failed to copy %s: %s", file_path, exc)
                skipped.append(target_name)
        else:
            skipped.append(target_name)

    pending = _refresh_pending_files(request)
    return JSONResponse({"copied": copied, "skipped": skipped, "pending": pending})


@app.get("/admin/review/{image_name}", response_class=HTMLResponse)
async def preview_image_metadata(
    request: Request,
    image_name: str,
    _: None = Depends(_verify_admin),
) -> HTMLResponse:
    filename = _sanitize_filename(image_name)
    if not filename or not _allowed_image(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )

    image_path = _resolve_image_path(filename)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )

    metadata = _load_metadata(image_path)
    _ensure_sidecar(image_path, metadata)
    metadata = _populate_missing_metadata(image_path, _load_metadata(image_path))

    return templates.TemplateResponse(
        request,
        "previewImageText.html",
        {
            "image_name": filename,
            "image_url": f"{IMAGES_URL_PREFIX}/{filename}",
            "metadata": metadata,
            "review_url": request.url_for("review_added_files"),
        },
    )


@app.post("/admin/metadata/{image_name}")
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
    action: str = Form("save"),
    pending_dependency: list[dict[str, Any]] = Depends(get_pending_files),
    _: None = Depends(_verify_admin),
) -> RedirectResponse:
    filename = _sanitize_filename(image_name)
    if not filename or not _allowed_image(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )

    if action == "cancel":
        return RedirectResponse(
            url=request.url_for("review_added_files"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    image_path = _resolve_image_path(filename)
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
    existing = _load_metadata(image_path)
    existing.update(clean_metadata)
    existing["status"] = "approved"
    _write_sidecar(image_path, existing)

    return RedirectResponse(
        url=request.url_for("review_added_files"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/unapprove/{image_name}", response_class=JSONResponse)
async def unapprove_image(
    image_name: str,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    """Move an approved image back to pending status."""
    image_path = _resolve_image_path(image_name)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )
    _set_status_sidecar(image_path, "pending")
    return JSONResponse({"status": "ok", "image": image_name, "new_status": "pending"})


@app.post("/admin/delete/{image_name}", response_class=JSONResponse)
async def soft_delete_image(
    image_name: str,
    _: None = Depends(_verify_admin),
) -> JSONResponse:
    """Soft-delete an image by moving it and its sidecar to .trash/."""
    image_path = _resolve_image_path(image_name)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )
    trash_dir = IMAGES_DIR / ".trash"
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


@app.get("/artwork/{image_filename}", response_class=HTMLResponse)
async def artwork_detail(request: Request, image_filename: str):
    """
    Displays the details of a single piece of artwork.
    """
    filename = _sanitize_filename(image_filename)
    if not filename or not _allowed_image(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artwork not found"
        )

    image_path = _resolve_image_path(filename)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artwork not found"
        )

    metadata = _load_metadata(image_path)
    image_url = f"{IMAGES_URL_PREFIX}/{filename}"

    artwork_data = {
        "title": metadata.get("title", "Artwork"),
        "description": metadata.get("description", ""),
        "caption": metadata.get("caption", ""),
        "tags": metadata.get("tags", []),
        "artist": metadata.get("artist", ""),
        "copyright": metadata.get("copyright", ""),
        "collection": metadata.get("collection", ""),
        "image_url": image_url,
    }

    gallery = get_artwork_files(status_filter="approved")
    filenames = [item["name"] for item in gallery]
    prev_artwork = None
    next_artwork = None
    if filename in filenames:
        idx = filenames.index(filename)
        if idx > 0:
            prev_artwork = filenames[idx - 1]
        if idx < len(filenames) - 1:
            next_artwork = filenames[idx + 1]

    return templates.TemplateResponse(
        request,
        "artwork_detail.html",
        {
            "artwork": artwork_data,
            "prev_artwork": prev_artwork,
            "next_artwork": next_artwork,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    Handles requests to the root URL ('/').
    It gets the list of artwork files and renders the index.html template.
    """
    logger.info("Request received for root path ('/')")
    artwork_list = get_artwork_files()

    # Data to pass to the HTML template
    context = {
        "request": request,  # Required by Jinja2Templates
        "artwork_files": artwork_list,
        "gallery_title": GALLERY_TITLE,
    }

    # Render the HTML template with the context data
    return templates.TemplateResponse(request, "index.html", context)


# --- Running the App ---
# To run this app:
# 1. Save this code as 'main.py'.
# 2. Make sure you have the 'Static/images' and 'templates' directories set up.
# 3. Put artwork images in 'Static/images'.
# 4. Create 'templates/index.html' (code provided separately).
# 5. Create `Static/css/styles.css` (code provided separately).
# 6. Create a virtual environment: python -m venv .venv
# 7. Activate it: source .venv/bin/activate (or .\venv\Scripts\activate on Windows)
# 8. Install necessary libraries: pip install "fastapi[all]"
# 9. Freeze requirements: pip freeze > requirements.txt
# 10. Run from your terminal in the directory containing 'main.py':
#     uvicorn main:app --reload
#     (The --reload flag automatically restarts the server when code changes)
