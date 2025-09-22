# main.py
import os
import json
import asyncio
import shutil
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, List

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
    sidecar_data["title"] = metadata.get("title") or image_path.stem
    sidecar_data["description"] = metadata.get("description", "")
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
    data.setdefault("title", image_path.stem)
    data.setdefault("description", "")
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

def _load_metadata(image_path: Path) -> dict:
    """Load metadata for an image.

    Preference order:
    1. JSON sidecar with same stem as image.
    2. Embedded EXIF tags (ImageDescription, XPTitle, XPComment).
    """
    data: dict = {}
    json_path = image_path.with_suffix(".json")
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in {json_path}: {e}")
    else:
        try:
            with Image.open(image_path) as img:
                exif = img.getexif()
                if exif:
                    for tag_id, value in exif.items():
                        tag = ExifTags.TAGS.get(tag_id, tag_id)
                        if tag == "ImageDescription" and value:
                            data["description"] = value
                        if tag == "XPTitle" and value:
                            if isinstance(value, bytes):
                                data["title"] = value.decode("utf-16-le").rstrip("\x00")
                            else:
                                data["title"] = value
                        if tag == "XPComment" and value and "description" not in data:
                            if isinstance(value, bytes):
                                data["description"] = value.decode("utf-16-le").rstrip("\x00")
                            else:
                                data["description"] = value
        except Exception as e:
            logger.debug(f"Unable to extract EXIF from {image_path}: {e}")
    data.setdefault("title", image_path.stem)
    data.setdefault("description", "")
    data.setdefault("reviewed", False)
    data.setdefault("detected_at", time.time())
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
            else:
                data[key] = None
    # Simple coercions
    if isinstance(data.get("reviewed"), str):
        lowered = data["reviewed"].strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            data["reviewed"] = True
        elif lowered in {"false", "0", "no", "n"}:
            data["reviewed"] = False
    if isinstance(data.get("detected_at"), str):
        try:
            data["detected_at"] = float(data["detected_at"]) 
        except ValueError:
            data["detected_at"] = time.time()
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
