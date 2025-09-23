# main.py
import os
import json
import asyncio
import base64
import shutil
import threading
import time
import textwrap
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette import status
from PIL import Image, ExifTags
from jsonschema import validate as js_validate, ValidationError
import httpx
import logging # Import logging

# --- Configuration ---
# Get the directory where this script is located
BASE_DIR = Path(__file__).resolve().parent
# Define directories relative to the base directory
# Use the on-disk directory name with the expected capitalization.
# Static files are served from the URL path `/static`, but the folder in
# the repository is named with a capital "S".
STATIC_DIR = BASE_DIR / "Static"
IMAGES_DIR = STATIC_DIR / "images"
TEMPLATES_DIR = BASE_DIR / "templates"
SCHEMA_PATH = BASE_DIR / "ImageSidecar.schema.json"

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".tiff",
}

POLL_INTERVAL_SECONDS = 5

OPENAI_API_KEY_ENV = "My_OpenAI_APIKey"
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
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True) # For optional CSS

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


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically to reduce corruption risk across workers."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(data, indent=2, ensure_ascii=False)
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _load_schema() -> Dict[str, Any]:
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
                "reviewed": {"type": "boolean", "default": False},
                "detected_at": {"type": "number", "default": 0},
            },
            "required": ["title", "description", "reviewed", "detected_at"],
            "additionalProperties": False,
        }


def _sanitize_filename(filename: str) -> str:
    """Return a safe filename without directory traversal."""
    return Path(filename).name


def _allowed_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_IMAGE_EXTENSIONS


def _extract_exif_metadata(image_path: Path) -> Dict[str, str]:
    """Return a subset of EXIF metadata relevant to titles and descriptions."""
    data: Dict[str, str] = {}
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if not exif:
                return data
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                if tag == "ImageDescription" and value:
                    if isinstance(value, bytes):
                        data["description"] = value.decode("utf-8", errors="ignore").strip()
                    else:
                        data["description"] = str(value).strip()
                if tag == "XPTitle" and value:
                    if isinstance(value, bytes):
                        data["title"] = value.decode("utf-16-le", errors="ignore").rstrip("\x00").strip()
                    else:
                        data["title"] = str(value).strip()
                if tag == "XPComment" and value and "description" not in data:
                    if isinstance(value, bytes):
                        data["description"] = value.decode("utf-16-le", errors="ignore").rstrip("\x00").strip()
                    else:
                        data["description"] = str(value).strip()
    except Exception as exc:  # pragma: no cover - dependent on image format
        logger.debug("Unable to extract EXIF from %s: %s", image_path, exc)
    return {k: v for k, v in data.items() if v}


def _build_openai_prompt(
    image_path: Path,
    metadata: Dict[str, Any],
    needs_title: bool,
    needs_description: bool,
) -> str:
    """Create a deterministic prompt for the OpenAI metadata request."""
    hints: List[str] = []
    if metadata.get("title"):
        hints.append(f"Existing title: {metadata['title']}")
    if metadata.get("description"):
        hints.append(f"Existing description: {metadata['description']}")
    hint_text = "\n".join(hints) if hints else "No reliable text metadata was detected."
    requested_parts: List[str] = []
    if needs_title:
        requested_parts.append("a short but descriptive title (<= 80 characters)")
    if needs_description:
        requested_parts.append("an engaging description (<= 400 characters)")
    requested = " and ".join(requested_parts)
    return textwrap.dedent(
        f"""
        You are assisting with cataloging artwork. Analyze the provided image "
        f"named '{image_path.name}'. {hint_text}
        Generate {requested}. Respond with JSON that contains the keys \
        "title" and "description" with concise English text suitable for \
        a public art gallery. Avoid mentioning that information is guessed \
        or unavailable.
        """
    ).strip()


def _prepare_image_for_openai(image_path: Path) -> Optional[str]:
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
        logger.warning("Failed to prepare %s for OpenAI metadata request: %s", image_path, exc)
        return None


def _request_openai_metadata(
    image_path: Path,
    metadata: Dict[str, Any],
    needs_title: bool,
    needs_description: bool,
) -> Dict[str, Any]:
    """Request metadata from OpenAI and return the response payload."""
    model = os.getenv(OPENAI_MODEL_ENV, OPENAI_DEFAULT_MODEL)
    prompt = _build_openai_prompt(image_path, metadata, needs_title, needs_description)
    details: Dict[str, Any] = {
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

    api_key = os.getenv(OPENAI_API_KEY_ENV)
    if not api_key:
        details["status"] = "skipped_no_api_key"
        details["error"] = (
            f"Missing OpenAI API key. Set the '{OPENAI_API_KEY_ENV}' environment variable."
        )
        return {"title": "", "description": "", "details": details}

    image_payload = _prepare_image_for_openai(image_path)
    if not image_payload:
        details["status"] = "error_image_encoding"
        details["error"] = "Unable to prepare image for OpenAI request."
        return {"title": "", "description": "", "details": details}

    request_body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You create concise, visitor-friendly metadata for artwork images. "
                    "Always respond with valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_payload, "detail": "low"}},
                ],
            },
        ],
        "max_tokens": 600,
        "temperature": 0.6,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "image_metadata",
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["title", "description"],
                    "additionalProperties": False,
                },
            },
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        timeout = httpx.Timeout(OPENAI_TIMEOUT_SECONDS)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=request_body,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        details["status"] = "error_http"
        details["error"] = str(exc)
        return {"title": "", "description": "", "details": details}

    details["response_id"] = payload.get("id", "")
    details["created"] = float(payload.get("created", details["attempted_at"]))
    details["model"] = payload.get("model", model)
    choice = next(iter(payload.get("choices", []) or []), {})
    details["finish_reason"] = choice.get("finish_reason", "")
    details["status"] = "success"
    details["raw_response"] = {
        "id": payload.get("id"),
        "usage": payload.get("usage", {}),
        "choices": [
            {
                "index": choice.get("index"),
                "finish_reason": choice.get("finish_reason"),
            }
        ],
    }

    message = choice.get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        content = "".join(text_parts)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        details["status"] = "error_parse"
        details["error"] = f"Failed to parse OpenAI response: {exc}"
        return {"title": "", "description": "", "details": details}

    title = str(parsed.get("title", "")).strip()
    description = str(parsed.get("description", "")).strip()
    return {"title": title, "description": description, "details": details}


def _populate_missing_metadata(image_path: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing metadata using OpenAI when configured."""
    title_value = (metadata.get("title") or "").strip()
    description_value = (metadata.get("description") or "").strip()
    needs_title = title_value == ""
    needs_description = description_value == ""
    if not (needs_title or needs_description):
        return metadata

    ai_details = metadata.get("ai_details")
    if not isinstance(ai_details, dict):
        ai_details = {}
    metadata["ai_details"] = ai_details

    if not os.getenv(OPENAI_API_KEY_ENV) and ai_details.get("status") == "skipped_no_api_key":
        return metadata

    result = _request_openai_metadata(image_path, metadata, needs_title, needs_description)
    details = result.get("details", {})
    metadata["ai_details"] = details

    if details.get("status") == "success":
        if needs_title and result.get("title"):
            metadata["title"] = result["title"]
        if needs_description and result.get("description"):
            metadata["description"] = result["description"]
        metadata["ai_generated"] = True
    else:
        metadata.setdefault("ai_generated", False)

    metadata.setdefault("detected_at", time.time())
    metadata.setdefault("reviewed", False)
    _write_sidecar(image_path, metadata)
    return metadata


def _ensure_sidecar(image_path: Path, metadata: Dict[str, Any]) -> None:
    """Ensure a JSON sidecar exists for the provided image with schema fields."""
    json_path = image_path.with_suffix(".json")
    if json_path.exists():
        return
    schema = _load_schema()
    now = time.time()
    # Base with schema defaults
    sidecar_data: Dict[str, Any] = {}
    for key, spec in schema.get("properties", {}).items():
        if "default" in spec:
            sidecar_data[key] = spec["default"]
    # Fill from detected metadata
    sidecar_data["title"] = str(metadata.get("title") or "").strip()
    sidecar_data["description"] = str(metadata.get("description") or "").strip()
    sidecar_data["ai_generated"] = bool(metadata.get("ai_generated", False))
    sidecar_ai_details = metadata.get("ai_details") if isinstance(metadata.get("ai_details"), dict) else {}
    sidecar_data["ai_details"] = sidecar_ai_details
    sidecar_data["reviewed"] = bool(metadata.get("reviewed", False))
    sidecar_data["detected_at"] = float(metadata.get("detected_at", now))
    with sidecar_lock:
        _atomic_write_json(json_path, sidecar_data)


def _write_sidecar(image_path: Path, metadata: Dict[str, Any]) -> None:
    json_path = image_path.with_suffix(".json")
    with sidecar_lock:
        _atomic_write_json(json_path, metadata)

def _set_review_status_sidecar(image_path: Path, reviewed: bool) -> None:
    json_path = image_path.with_suffix(".json")
    data: Dict[str, Any] = {}
    if json_path.exists():
        with suppress(json.JSONDecodeError, OSError):
            data = json.loads(json_path.read_text(encoding="utf-8"))
    data["reviewed"] = reviewed
    data.setdefault("title", "")
    data.setdefault("description", "")
    data.setdefault("ai_generated", False)
    if not isinstance(data.get("ai_details"), dict):
        data["ai_details"] = {}
    data.setdefault("detected_at", time.time())
    _write_sidecar(image_path, data)


def new_files_detected() -> List[Dict[str, Any]]:
    """Detect unreviewed image files based on their sidecar JSON."""
    pending: List[Dict[str, Any]] = []
    try:
        disk_listing = os.listdir(IMAGES_DIR)
    except OSError as exc:
        logger.error("Unable to scan images directory %s: %s", IMAGES_DIR, exc)
        disk_listing = []

    existing_files = [
        name for name in disk_listing if (IMAGES_DIR / name).is_file() and _allowed_image(name)
    ]

    for filename in existing_files:
        image_path = IMAGES_DIR / filename
        metadata = _load_metadata(image_path)
        _ensure_sidecar(image_path, metadata)
        metadata = _load_metadata(image_path)
        metadata = _populate_missing_metadata(image_path, metadata)
        if not bool(metadata.get("reviewed", False)):
            pending.append(
                {
                    "name": filename,
                    "url": f"/static/images/{filename}",
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
            pending = new_files_detected()
            app.state.pending_images = pending
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:  # pragma: no cover - clean shutdown
        logger.debug("Image directory watcher cancelled")
        raise


@app.on_event("startup")
async def startup_event() -> None:
    _validate_and_migrate_sidecars()
    app.state.pending_images = new_files_detected()
    app.state.watcher_task = asyncio.create_task(_watch_image_directory(app))


@app.on_event("shutdown")
async def shutdown_event() -> None:
    watcher = getattr(app.state, "watcher_task", None)
    if watcher:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher

def _load_metadata(image_path: Path) -> Dict[str, Any]:
    """Load metadata for an image, combining sidecar data and EXIF hints."""
    data: Dict[str, Any] = {}
    json_path = image_path.with_suffix(".json")
    if json_path.exists():
        try:
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON in %s: %s", json_path, exc)

    exif_data = _extract_exif_metadata(image_path)
    if not (data.get("title") or "title" in data) and exif_data.get("title"):
        data["title"] = exif_data["title"]
    if not (data.get("description") or "description" in data) and exif_data.get("description"):
        data["description"] = exif_data["description"]

    data.setdefault("title", "")
    data.setdefault("description", "")
    data.setdefault("reviewed", False)
    data.setdefault("detected_at", time.time())
    data.setdefault("ai_generated", False)
    if not isinstance(data.get("ai_details"), dict):
        data["ai_details"] = {}
    return data


def _apply_schema_defaults(data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
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
    if isinstance(data.get("reviewed"), str):
        lowered = data["reviewed"].strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            data["reviewed"] = True
        elif lowered in {"false", "0", "no", "n"}:
            data["reviewed"] = False
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
def get_artwork_files():
    """Scan IMAGES_DIR and return metadata for each image."""
    artwork = []
    logger.info(f"Scanning for artwork in: {IMAGES_DIR}")
    if IMAGES_DIR.exists() and IMAGES_DIR.is_dir():
        try:
            for filename in os.listdir(IMAGES_DIR):
                file_path = IMAGES_DIR / filename
                if file_path.is_file() and _allowed_image(filename):
                    meta = _load_metadata(file_path)
                    image_url = f"/static/images/{filename}"
                    meta.update({"url": image_url, "name": filename})
                    artwork.append(meta)
                    logger.debug(f"Loaded metadata for {filename}")
        except OSError as e:
            logger.error(f"Error reading image directory {IMAGES_DIR}: {e}")
            return []
    else:
        logger.warning(f"Images directory not found or is not a directory: {IMAGES_DIR}")

    logger.info(f"Found {len(artwork)} artwork files.")
    return artwork

# --- Routes ---


@app.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request) -> HTMLResponse:
    """Render the admin review dashboard."""
    pending = new_files_detected()
    request.app.state.pending_images = pending
    return templates.TemplateResponse(
        "reviewAddedFiles.html",
        {
            "request": request,
            "pending_images": pending,
            "allowed_extensions": sorted(ALLOWED_IMAGE_EXTENSIONS),
        },
    )


@app.get("/admin/review", response_class=HTMLResponse)
async def review_added_files(request: Request) -> HTMLResponse:
    pending = new_files_detected()
    request.app.state.pending_images = pending
    return templates.TemplateResponse(
        "reviewAddedFiles.html",
        {
            "request": request,
            "pending_images": pending,
            "allowed_extensions": sorted(ALLOWED_IMAGE_EXTENSIONS),
        },
    )


@app.get("/admin/api/new-files", response_class=JSONResponse)
async def api_new_files(request: Request) -> JSONResponse:
    pending = new_files_detected()
    request.app.state.pending_images = pending
    return JSONResponse({"pending": pending})


@app.post("/admin/upload")
async def upload_images(
    request: Request,
    files: List[UploadFile] = File(...),
) -> JSONResponse:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded")

    saved: List[str] = []
    skipped: List[str] = []

    for upload in files:
        filename = _sanitize_filename(upload.filename)
        if not filename:
            continue
        suffix = Path(filename).suffix.lower()
        if not _allowed_image(filename) and suffix != ".json":
            skipped.append(filename)
            continue

        destination = IMAGES_DIR / filename
        try:
            with destination.open("wb") as buffer:
                shutil.copyfileobj(upload.file, buffer)
            saved.append(filename)
            if _allowed_image(filename):
                # Ensure sidecar exists for newly uploaded images
                _ensure_sidecar(destination, _load_metadata(destination))
        except OSError as exc:
            logger.error("Failed to save %s: %s", filename, exc)
            skipped.append(filename)
        finally:
            upload.file.close()

    pending = new_files_detected()
    request.app.state.pending_images = pending
    message = "Uploaded files successfully" if saved else "No supported files uploaded"
    return JSONResponse({"saved": saved, "skipped": skipped, "message": message, "pending": pending})


@app.post("/admin/import-path")
async def import_from_path(request: Request, path: str = Form(...)) -> JSONResponse:
    source_path = Path(path).expanduser()
    if not source_path.exists():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path does not exist")

    copied: List[str] = []
    skipped: List[str] = []

    def _handle_file(file_path: Path) -> None:
        target_name = _sanitize_filename(file_path.name)
        if _allowed_image(target_name) or file_path.suffix.lower() == ".json":
            target = IMAGES_DIR / target_name
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

    if source_path.is_file():
        _handle_file(source_path)
    else:
        for file_path in source_path.rglob("*"):
            if file_path.is_file():
                _handle_file(file_path)

    pending = new_files_detected()
    request.app.state.pending_images = pending
    return JSONResponse({"copied": copied, "skipped": skipped, "pending": pending})


@app.get("/admin/review/{image_name}", response_class=HTMLResponse)
async def preview_image_metadata(request: Request, image_name: str) -> HTMLResponse:
    filename = _sanitize_filename(image_name)
    if not filename or not _allowed_image(filename):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    image_path = IMAGES_DIR / filename
    if not image_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    metadata = _load_metadata(image_path)
    _ensure_sidecar(image_path, metadata)
    metadata = _populate_missing_metadata(image_path, _load_metadata(image_path))

    return templates.TemplateResponse(
        "previewImageText.html",
        {
            "request": request,
            "image_name": filename,
            "image_url": f"/static/images/{filename}",
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
    action: str = Form("save"),
) -> RedirectResponse:
    filename = _sanitize_filename(image_name)
    if not filename or not _allowed_image(filename):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    if action == "cancel":
        return RedirectResponse(
            url=request.url_for("review_added_files"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    image_path = IMAGES_DIR / filename
    if not image_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    clean_metadata = {
        "title": title.strip() or image_path.stem,
        "description": description.strip(),
    }
    # Merge with existing sidecar and mark as reviewed
    existing = _load_metadata(image_path)
    existing.update(clean_metadata)
    existing["reviewed"] = True
    _write_sidecar(image_path, existing)

    pending = new_files_detected()
    request.app.state.pending_images = pending

    return RedirectResponse(
        url=request.url_for("review_added_files"),
        status_code=status.HTTP_303_SEE_OTHER,
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
        "request": request, # Required by Jinja2Templates
        "artwork_files": artwork_list,
        "gallery_title": "My Girlfriend's Artwork Gallery" # Customizable title
    }

    # Render the HTML template with the context data
    return templates.TemplateResponse("index.html", context)

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
