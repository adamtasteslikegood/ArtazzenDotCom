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
import re
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
import tempfile
# Optional: used to coordinate a single background watcher across gunicorn workers
try:  # pragma: no cover - platform dependent
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - e.g., Windows
    fcntl = None  # type: ignore

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
CONFIG_PATH = BASE_DIR / "ai_config.json"
ADV_CONFIG_PATH = BASE_DIR / "advanced_config.json"
WATCHER_LOCK_PATH = BASE_DIR / ".watcher.lock"
MIGRATION_LOCK_PATH = BASE_DIR / ".migration.lock"

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

OPENAI_API_KEY_ENV_PRIMARY = "MY_OPENAI_API_KEY"
OPENAI_API_KEY_ENV_LEGACY = "My_OpenAI_APIKey"
OPENAI_MODEL_ENV = "OPENAI_IMAGE_METADATA_MODEL"
OPENAI_DEFAULT_MODEL = "gpt-5"
OPENAI_MODEL_CHOICES = [
    "auto",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4o-audio-preview",
    "gpt-5-mini",
    "gpt-5",
]
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

def _configure_logging() -> logging.Logger:
    """Configure console + rotating file logging with env-driven levels.

    Env vars:
    - APP_LOG_LEVEL: console log level (default INFO)
    - APP_FILE_LOG: enable file logging to logs/app.log (default 1/true)
    - APP_FILE_LOG_LEVEL: file log level (default INFO)
    """
    logger = logging.getLogger()
    if getattr(logger, "_app_logging_configured", False):
        return logging.getLogger(__name__)

    level_name = os.getenv("APP_LOG_LEVEL", "INFO").upper()
    file_level_name = os.getenv("APP_FILE_LOG_LEVEL", level_name).upper()
    try:
        level = getattr(logging, level_name)
    except AttributeError:
        level = logging.INFO
    try:
        file_level = getattr(logging, file_level_name)
    except AttributeError:
        file_level = level

    logger.setLevel(min(level, file_level))

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (always on)
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # Optional rotating file handler
    file_log_enabled = os.getenv("APP_FILE_LOG", "1").lower() in {"1", "true", "yes"}
    if file_log_enabled:
        logs_dir = BASE_DIR / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        try:
            from logging.handlers import RotatingFileHandler

            fh = RotatingFileHandler(str(logs_dir / "app.log"), maxBytes=5 * 1024 * 1024, backupCount=3)
        except Exception:
            fh = logging.FileHandler(str(logs_dir / "app.log"))
        fh.setLevel(file_level)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    setattr(logger, "_app_logging_configured", True)
    return logging.getLogger(__name__)


logger = _configure_logging()

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


def _get_ai_config() -> Dict[str, Any]:
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
        "startup_enrichment_enabled": bool(cfg.get("startup_enrichment_enabled", True)),
        "startup_sidecar_enabled": bool(cfg.get("startup_sidecar_enabled", True)),
        "max_workers_create_sidecars": int(cfg.get("max_workers_create_sidecars", 2)),
    }


def _parse_bool_env(value: Optional[str], default: bool) -> bool:
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


def _parse_float_env(value: Optional[str], default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_int_env(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _default_ai_config_from_env() -> Dict[str, Any]:
    return {
        "enabled": _parse_bool_env(os.getenv("AI_METADATA_ENABLED"), True),
        "model": os.getenv(OPENAI_MODEL_ENV, OPENAI_DEFAULT_MODEL),
        "temperature": _parse_float_env(os.getenv("OPENAI_IMAGE_METADATA_TEMPERATURE"), 0.6),
        "max_output_tokens": _parse_int_env(os.getenv("OPENAI_IMAGE_METADATA_MAX_TOKENS"), 600),
        "startup_enrichment_enabled": _parse_bool_env(os.getenv("AI_METADATA_AT_STARTUP_ENABLED"), True),
        "startup_sidecar_enabled": _parse_bool_env(os.getenv("AI_SIDECAR_AT_STARTUP_ENABLED"), True),
        "max_workers_create_sidecars": max(1, _parse_int_env(os.getenv("AI_SIDECAR_MAX_WORKERS"), 2)),
    }


def _sanitize_ai_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
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
        if "startup_enrichment_enabled" in cfg:
            out["startup_enrichment_enabled"] = bool(cfg.get("startup_enrichment_enabled"))
        if "startup_sidecar_enabled" in cfg:
            out["startup_sidecar_enabled"] = bool(cfg.get("startup_sidecar_enabled"))
        if "max_workers_create_sidecars" in cfg:
            try:
                slots = int(cfg.get("max_workers_create_sidecars", out.get("max_workers_create_sidecars", 2)))
                out["max_workers_create_sidecars"] = max(1, min(64, slots))
            except (TypeError, ValueError):
                pass
    return out


def _load_ai_config() -> Dict[str, Any]:
    base = _default_ai_config_from_env()
    if CONFIG_PATH.exists():
        with suppress(json.JSONDecodeError, OSError):
            persisted = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return _sanitize_ai_config({**base, **(persisted or {})})
    return base


def _save_ai_config(cfg: Dict[str, Any]) -> None:
    with config_lock:
        _atomic_write_json(CONFIG_PATH, _sanitize_ai_config(cfg))


# --- Advanced config (logging, debug dumps, timeouts) ---

def _default_advanced_config_from_env() -> Dict[str, Any]:
    lvl = os.getenv("APP_LOG_LEVEL", "INFO").upper()
    file_lvl = os.getenv("APP_FILE_LOG_LEVEL", lvl).upper()
    return {
        "log_level": lvl,
        "file_log": _parse_bool_env(os.getenv("APP_FILE_LOG"), True),
        "file_log_level": file_lvl,
        "ai_metadata_debug_dump": _parse_bool_env(os.getenv("AI_METADATA_DEBUG_DUMP"), False),
        "openai_timeout_seconds": _parse_float_env(os.getenv("OPENAI_TIMEOUT_SECONDS"), 30.0),
    }


def _sanitize_advanced_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    base = _default_advanced_config_from_env()
    out = dict(base)
    if not isinstance(cfg, dict):
        return out
    lvl = str(cfg.get("log_level", out["log_level"])) .upper()
    out["log_level"] = lvl if lvl in allowed else out["log_level"]
    out["file_log"] = bool(cfg.get("file_log", out["file_log"]))
    flvl = str(cfg.get("file_log_level", out["file_log_level"])) .upper()
    out["file_log_level"] = flvl if flvl in allowed else out["file_log_level"]
    out["ai_metadata_debug_dump"] = bool(cfg.get("ai_metadata_debug_dump", out["ai_metadata_debug_dump"]))
    try:
        out["openai_timeout_seconds"] = max(5.0, float(cfg.get("openai_timeout_seconds", out["openai_timeout_seconds"])) )
    except (TypeError, ValueError):
        pass
    return out


def _load_advanced_config() -> Dict[str, Any]:
    base = _default_advanced_config_from_env()
    if ADV_CONFIG_PATH.exists():
        with suppress(json.JSONDecodeError, OSError):
            persisted = json.loads(ADV_CONFIG_PATH.read_text(encoding="utf-8"))
            return _sanitize_advanced_config({**base, **(persisted or {})})
    return base


def _save_advanced_config(cfg: Dict[str, Any]) -> None:
    with config_lock:
        _atomic_write_json(ADV_CONFIG_PATH, _sanitize_advanced_config(cfg))


def _apply_logging_config(cfg: Dict[str, Any]) -> None:
    root = logging.getLogger()
    # Ensure a stream handler exists
    stream = None
    fileh = None
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            stream = h
        if isinstance(h, logging.FileHandler):
            fileh = h
    if stream is None:
        stream = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
        stream.setFormatter(fmt)
        root.addHandler(stream)
    # Levels
    level = getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO)
    file_level = getattr(logging, str(cfg.get("file_log_level", "INFO")).upper(), logging.INFO)
    stream.setLevel(level)
    # File logging toggle
    enable_file = bool(cfg.get("file_log", True))
    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    if enable_file and fileh is None:
        try:
            from logging.handlers import RotatingFileHandler
            fileh = RotatingFileHandler(str(logs_dir / "app.log"), maxBytes=5*1024*1024, backupCount=3)
        except Exception:
            fileh = logging.FileHandler(str(logs_dir / "app.log"))
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
        fileh.setFormatter(fmt)
        root.addHandler(fileh)
    if fileh is not None:
        if enable_file:
            fileh.setLevel(file_level)
        else:
            # remove file handler
            try:
                root.removeHandler(fileh)
            except Exception:
                pass


def _is_debug_dump_enabled() -> bool:
    # env override still works
    env = os.getenv("AI_METADATA_DEBUG_DUMP", "").strip().lower()
    if env in {"1", "true", "yes"}:
        return True
    adv = getattr(app.state, "advanced_config", None)
    if isinstance(adv, dict):
        return bool(adv.get("ai_metadata_debug_dump", False))
    return False


def _get_openai_timeout_seconds() -> float:
    adv = getattr(app.state, "advanced_config", None)
    if isinstance(adv, dict):
        try:
            return float(adv.get("openai_timeout_seconds", 30.0))
        except (TypeError, ValueError):
            return 30.0
    try:
        return float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
    except ValueError:
        return 30.0


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically with a unique temp file to avoid cross-process races."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    fd = None
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except FileNotFoundError:
        # Retry once by recreating a temp file
        path.parent.mkdir(parents=True, exist_ok=True)
        fd2, tmp_name2 = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        with os.fdopen(fd2, "w", encoding="utf-8") as f2:
            f2.write(text)
            f2.flush()
            os.fsync(f2.fileno())
        os.replace(tmp_name2, path)
    finally:
        if fd is not None:
            with suppress(Exception):
                os.close(fd)
        if tmp_name and os.path.exists(tmp_name):
            with suppress(Exception):
                os.remove(tmp_name)


def _acquire_process_lock(path: Path) -> Optional[int]:
    """Attempt to acquire a cross-process exclusive lock. Returns fd if held."""
    if fcntl is None:  # pragma: no cover - platform dependent
        logger.warning("fcntl not available; cannot ensure single watcher across workers")
        return None
    fd: Optional[int] = None
    try:
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:  # lock held by another process
        if fd is not None:
            with suppress(Exception):
                os.close(fd)
        return None
    except Exception as exc:
        logger.warning("Failed to acquire watcher lock %s: %s", path, exc)
        if fd is not None:
            with suppress(Exception):
                os.close(fd)
        return None


def _release_process_lock(fd: Optional[int]) -> None:
    if fd is None:
        return
    try:
        if fcntl is not None:  # pragma: no cover - platform dependent
            with suppress(Exception):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        with suppress(Exception):
            os.close(fd)


def _acquire_sidecar_slot(max_slots: int) -> Optional[int]:
    """Acquire one of N sidecar creation slots across processes.

    Returns an OS file descriptor if a slot is held, else None.
    """
    if fcntl is None:  # pragma: no cover
        # Without fcntl we cannot coordinate across processes; treat as unlimited
        return None
    max_slots = max(1, int(max_slots or 1))
    for i in range(max_slots):
        path = BASE_DIR / f".sidecar.slot.{i}"
        fd: Optional[int] = None
        try:
            fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if fd is not None:
                with suppress(Exception):
                    os.close(fd)
            continue
        except Exception:
            if fd is not None:
                with suppress(Exception):
                    os.close(fd)
            continue
    return None


def _release_sidecar_slot(fd: Optional[int]) -> None:
    _release_process_lock(fd)


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
    needs_caption: bool,
    needs_author: bool,
    needs_tags: bool,
) -> str:
    """Create a deterministic prompt for the OpenAI metadata request."""
    hints: List[str] = []
    if metadata.get("title"):
        hints.append(f"Existing title: {metadata['title']}")
    if metadata.get("description"):
        hints.append(f"Existing description: {metadata['description']}")
    if metadata.get("caption"):
        hints.append(f"Existing caption: {metadata['caption']}")
    if metadata.get("author"):
        hints.append(f"Existing author: {metadata['author']}")
    tags = metadata.get("tags") or []
    if tags:
        hints.append("Existing tags: " + ", ".join(str(tag) for tag in tags if tag))
    hint_text = "\n".join(hints) if hints else "No reliable text metadata was detected."
    requested_parts: List[str] = []
    if needs_title:
        requested_parts.append("a short but descriptive title (<= 80 characters)")
    if needs_description:
        requested_parts.append("an engaging description (<= 400 characters)")
    if needs_caption:
        requested_parts.append("a vivid caption sentence (<= 160 characters)")
    if needs_author:
        requested_parts.append("an author credit (use 'Unknown Artist' if unclear)")
    if needs_tags:
        requested_parts.append("a list of 3 to 7 short descriptive tags")
    requested = " and ".join(requested_parts)
    return textwrap.dedent(
        f"""
        You are assisting with cataloging artwork. Analyze the provided image
        named '{image_path.name}'. {hint_text}
        Generate {requested}. Respond with JSON that contains the keys "title", "description",
        "caption", "author", and "tags". Keep all text concise, professional, and visitor-friendly
        for a public art gallery. Provide tags as an array of lowercase strings without hashtags.
        Avoid mentioning that information is guessed or unavailable.
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


def _get_openai_api_key() -> Optional[str]:
    """Return OpenAI API key from env or optional local module.

    Checks env vars `MY_OPENAI_API_KEY` then legacy `My_OpenAI_APIKey`.
    Falls back to optional my_OpenAI_APIkey.py module if present.
    """
    api_key = os.getenv(OPENAI_API_KEY_ENV_PRIMARY) or os.getenv(OPENAI_API_KEY_ENV_LEGACY)
    if api_key:
        return api_key
    with suppress(Exception):
        # Lazy import to avoid hard dependency
        import my_OpenAI_APIkey as local_key  # type: ignore

        v = getattr(local_key, "MY_OPENAI_API_KEY", None)
        if v:
            return str(v)
    return None


def _resolve_model_choice(model: str) -> str:
    """Resolve configured model name, honoring the 'auto' option."""
    candidate = (model or "").strip()
    if not candidate or candidate.lower() == "auto":
        env_model = os.getenv(OPENAI_MODEL_ENV, "").strip()
        if env_model:
            chosen = env_model
        else:
            chosen = OPENAI_DEFAULT_MODEL
    else:
        chosen = candidate

    # Warn on unknown models but allow for forward compatibility
    if chosen not in OPENAI_MODEL_CHOICES:
        logger.warning("Using non-listed model '%s' (proceeding for compatibility)", chosen)
    return chosen


def _request_openai_metadata(
    image_path: Path,
    metadata: Dict[str, Any],
    needs_title: bool,
    needs_description: bool,
    needs_caption: bool,
    needs_author: bool,
    needs_tags: bool,
) -> Dict[str, Any]:
    """Request metadata from OpenAI and return the response payload."""
    ai_cfg = _get_ai_config()
    configured_model = ai_cfg["model"]
    model = _resolve_model_choice(configured_model)
    prompt = _build_openai_prompt(
        image_path,
        metadata,
        needs_title,
        needs_description,
        needs_caption,
        needs_author,
        needs_tags,
    )
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
        # Ask for JSON Schema output to increase structured responses
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "image_metadata",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "caption": {"type": "string"},
                        "author": {"type": "string"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 12,
                        },
                    },
                    "required": ["title", "description", "caption", "author", "tags"],
                    "additionalProperties": False,
                },
            },
        },
    }
    # Some models (e.g., gpt-5 variants) do not accept 'temperature'
    if not str(model).startswith("gpt-5"):
        request_body["temperature"] = ai_cfg["temperature"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        timeout = httpx.Timeout(_get_openai_timeout_seconds())
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=request_body,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        details["status"] = "error_http"
        details["error"] = str(exc)
        # Attach response body when available for diagnostics
        try:
            details["error_body"] = response.text
        except Exception:
            pass
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
                if ptype in {"output_json", "json"} and isinstance(part.get("json"), dict):
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
        choice = next(iter(payload.get("choices", []) or []), {})
        details["finish_reason"] = choice.get("finish_reason", "")
        message = choice.get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            content_text = "".join(text_parts)
        elif isinstance(content, str):
            content_text = content

    # Helper: strip markdown code fences and try to extract a JSON object
    def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        # Remove common code fences like ```json ... ``` or ``` ... ```
        cleaned = re.sub(r"```+\s*json\s*|```+", "", text, flags=re.IGNORECASE)
        # First, try a straight parse
        with suppress(json.JSONDecodeError):
            return json.loads(cleaned)
        # If that fails, try to find a balanced {...} region and parse it
        start = cleaned.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:i+1]
                    with suppress(json.JSONDecodeError):
                        return json.loads(candidate)
        return None

    # Helper: dump diagnostic file when parsing fails or when debug is enabled
    def _dump_openai_debug(reason: str, text_excerpt: str = "") -> None:
        try:
            debug_enabled = _is_debug_dump_enabled()
            if reason != "success" or debug_enabled:
                logs_dir = BASE_DIR / "logs" / "ai"
                logs_dir.mkdir(parents=True, exist_ok=True)
                safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", image_path.name)
                ts = time.strftime("%Y%m%d-%H%M%S")
                out_path = logs_dir / f"openai_{ts}_{safe_name}_{reason}.json"
                doc = {
                    "reason": reason,
                    "image": image_path.name,
                    "model": details.get("model"),
                    "payload_id": payload.get("id"),
                    "usage": payload.get("usage", {}),
                    "output_types": [
                        [(p or {}).get("type") for p in ((it or {}).get("content") or [])]
                        for it in (output or [])
                    ] if isinstance(output, list) else [],
                    "content_text": content_text,
                    "text_excerpt": text_excerpt or content_text[:500],
                }
                with open(out_path, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, indent=2, ensure_ascii=False)
        except Exception as dump_exc:
            logger.debug("Failed to write OpenAI debug dump: %s", dump_exc)

    if parsed is None:
        # Try strict parse, then lenient extraction
        try:
            parsed = json.loads(content_text) if content_text else None
        except json.JSONDecodeError:
            parsed = _extract_json_object(content_text)
        if parsed is None:
            details["status"] = "error_parse"
            details["error"] = "Failed to parse OpenAI response: no valid JSON object found"
            try:
                details["raw_response"] = {
                    "id": payload.get("id"),
                    "usage": payload.get("usage", {}),
                    "output_types": [
                        [(p or {}).get("type") for p in ((it or {}).get("content") or [])]
                        for it in (output or [])
                    ],
                    "text_excerpt": content_text[:200],
                }
            except Exception:
                details["raw_response"] = {"id": payload.get("id"), "usage": payload.get("usage", {})}
            _dump_openai_debug("error_parse", text_excerpt=content_text[:500])
            return {"title": "", "description": "", "details": details}

    # If still no structured JSON, bail gracefully instead of crashing
    if not isinstance(parsed, dict):
        details["status"] = "error_parse"
        details["error"] = "OpenAI response did not include JSON content."
        try:
            details["raw_response"] = {"id": payload.get("id"), "usage": payload.get("usage", {})}
        except Exception:
            pass
        _dump_openai_debug("no_json")
        return {"title": "", "description": "", "details": details}

    # Keep raw id/usage only to avoid bloating sidecar
    details["raw_response"] = {"id": payload.get("id"), "usage": payload.get("usage", {})}

    # Optionally dump successful responses for diagnostics when AI_METADATA_DEBUG_DUMP is enabled
    try:
        debug_enabled = os.getenv("AI_METADATA_DEBUG_DUMP", "0").lower() in {"1", "true", "yes"}
        if debug_enabled:
            _dump_openai_debug("success")
    except Exception:
        pass

    title = str(parsed.get("title", "")).strip()
    description = str(parsed.get("description", "")).strip()
    caption = str(parsed.get("caption", "")).strip()
    author = str(parsed.get("author", "")).strip()
    tags_value = parsed.get("tags", [])
    if isinstance(tags_value, str):
        tags = [tag.strip() for tag in tags_value.split(",") if tag.strip()]
    elif isinstance(tags_value, list):
        tags = [str(tag).strip() for tag in tags_value if str(tag).strip()]
    else:
        tags = []
    return {
        "title": title,
        "description": description,
        "caption": caption,
        "author": author,
        "tags": tags,
        "details": details,
    }


def _populate_missing_metadata(image_path: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing metadata using OpenAI when configured."""
    title_value = (metadata.get("title") or "").strip()
    description_value = (metadata.get("description") or "").strip()
    caption_value = (metadata.get("caption") or "").strip()
    author_value = (metadata.get("author") or "").strip()
    tags_value = metadata.get("tags")
    if isinstance(tags_value, str):
        tags_value = [tag.strip() for tag in tags_value.split(",") if tag.strip()]
    if not isinstance(tags_value, list):
        tags_value = []
    metadata["tags"] = tags_value
    needs_title = title_value == ""
    needs_description = description_value == ""
    needs_caption = caption_value == ""
    needs_author = author_value == ""
    needs_tags = len(tags_value) == 0
    metadata.setdefault("caption", caption_value)
    metadata.setdefault("author", author_value)
    metadata.setdefault("copyright", metadata.get("copyright", ""))
    if not (needs_title or needs_description or needs_caption or needs_author or needs_tags):
        logger.debug("AI enrichment not needed for %s (metadata complete)", image_path.name)
        return metadata
    # Respect runtime toggle
    if not _get_ai_config().get("enabled", True):
        logger.info("AI enrichment disabled; skipping for %s", image_path.name)
        return metadata

    ai_details = metadata.get("ai_details")
    if not isinstance(ai_details, dict):
        ai_details = {}
    metadata["ai_details"] = ai_details

    if not _get_openai_api_key() and ai_details.get("status") == "skipped_no_api_key":
        return metadata

    # Log start of enrichment
    requested = [
        key for key, need in (
            ("title", needs_title),
            ("description", needs_description),
            ("caption", needs_caption),
            ("author", needs_author),
            ("tags", needs_tags),
        ) if need
    ]
    logger.info(
        "AI enrichment starting for %s (fields: %s)",
        image_path.name,
        ", ".join(requested) or "none",
    )

    result = _request_openai_metadata(
        image_path,
        metadata,
        needs_title,
        needs_description,
        needs_caption,
        needs_author,
        needs_tags,
    )
    details = result.get("details", {})
    metadata["ai_details"] = details

    if details.get("status") == "success":
        if needs_title and result.get("title"):
            metadata["title"] = result["title"]
        if needs_description and result.get("description"):
            metadata["description"] = result["description"]
        if needs_caption and result.get("caption"):
            metadata["caption"] = result["caption"]
        if needs_author and result.get("author"):
            metadata["author"] = result["author"]
        if needs_tags and result.get("tags"):
            metadata["tags"] = result["tags"]
        metadata["ai_generated"] = True
        updated_fields = [
            k for k in [
                "title" if needs_title and result.get("title") else None,
                "description" if needs_description and result.get("description") else None,
                "caption" if needs_caption and result.get("caption") else None,
                "author" if needs_author and result.get("author") else None,
                "tags" if needs_tags and result.get("tags") else None,
            ] if k
        ]
        logger.info(
            "AI enrichment succeeded for %s (updated: %s)",
            image_path.name,
            ", ".join(updated_fields) or "none",
        )
    else:
        metadata.setdefault("ai_generated", False)
        status_text = details.get("status") or "unknown"
        error_text = details.get("error") or ""
        if status_text.startswith("skipped"):
            logger.info("AI enrichment skipped for %s: %s", image_path.name, status_text)
        else:
            logger.warning(
                "AI enrichment failed for %s: %s %s",
                image_path.name,
                status_text,
                f"- {error_text}" if error_text else "",
            )

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
    sidecar_data["caption"] = str(metadata.get("caption") or "").strip()
    sidecar_data["author"] = str(metadata.get("author") or "").strip()
    sidecar_data["copyright"] = str(metadata.get("copyright") or "").strip()
    tags_value = metadata.get("tags")
    if isinstance(tags_value, str):
        tags_value = [tag.strip() for tag in tags_value.split(",") if tag.strip()]
    if not isinstance(tags_value, list):
        tags_value = []
    else:
        tags_value = [str(tag).strip() for tag in tags_value if str(tag).strip()]
    sidecar_data["tags"] = tags_value
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


def new_files_detected(
    allow_ai_enrichment: bool = True,
    allow_sidecar_creation: bool = True,
) -> List[Dict[str, Any]]:
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

    skipped_sidecar = 0
    skipped_ai = 0
    for filename in existing_files:
        image_path = IMAGES_DIR / filename
        metadata = _load_metadata(image_path)
        if allow_sidecar_creation:
            _ensure_sidecar(image_path, metadata)
            metadata = _load_metadata(image_path)
        else:
            skipped_sidecar += 1
        if allow_ai_enrichment:
            metadata = _populate_missing_metadata(image_path, metadata)
        else:
            skipped_ai += 1
        if not bool(metadata.get("reviewed", False)):
            item = dict(metadata)
            item.update(
                {
                    "name": filename,
                    "url": f"/static/images/{filename}",
                    "detected_at": metadata.get("detected_at"),
                    "sidecar_exists": image_path.with_suffix(".json").exists(),
                }
            )
            pending.append(item)

    if not allow_sidecar_creation and skipped_sidecar:
        logger.info("Startup sidecar creation disabled; skipped for %d images", skipped_sidecar)
    if not allow_ai_enrichment and skipped_ai:
        logger.info("Startup AI enrichment disabled; skipped for %d images", skipped_ai)
    logger.debug("Pending review files: %s", [item["name"] for item in pending])
    return pending


def _gather_admin_dashboard_data() -> Dict[str, List[Dict[str, Any]]]:
    """Return dictionaries of pending and reviewed images for the admin UI."""
    pending = new_files_detected()
    pending_lookup = {item["name"]: item for item in pending}
    reviewed: List[Dict[str, Any]] = []
    all_items: List[Dict[str, Any]] = []
    for artwork in get_artwork_files():
        normalized = dict(artwork)
        name = normalized.get("name")
        if name in pending_lookup:
            # Ensure pending entries include the latest data we know about
            pending_item = pending_lookup[name]
            pending_item.update({k: normalized.get(k, pending_item.get(k)) for k in normalized.keys()})
        else:
            reviewed.append(normalized)
        all_items.append(normalized)
    pending_list = list(pending_lookup.values())
    # Ensure consistent ordering (newest first) for admin convenience
    pending_list.sort(key=lambda item: item.get("detected_at") or 0, reverse=True)
    reviewed.sort(key=lambda item: item.get("detected_at") or 0, reverse=True)
    return {"pending": pending_list, "reviewed": reviewed, "all": pending_list + reviewed}


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
    # Initialize advanced + AI config from persisted files with env fallbacks
    app.state.advanced_config = _load_advanced_config()
    _apply_logging_config(app.state.advanced_config)
    # Initialize runtime AI config from persisted file with env fallbacks
    app.state.ai_config = _load_ai_config()
    # Run schema validation/migration and startup enrichment in a single process when possible
    mig_fd = _acquire_process_lock(MIGRATION_LOCK_PATH)
    startup_ai = bool(app.state.ai_config.get("startup_enrichment_enabled", True))
    startup_sidecar = bool(app.state.ai_config.get("startup_sidecar_enabled", True))
    sidecar_slots = int(app.state.ai_config.get("max_workers_create_sidecars", 2) or 2)
    if mig_fd is not None:
        try:
            _validate_and_migrate_sidecars()
            if not startup_ai:
                logger.info("Startup AI enrichment disabled by config; scanning without enrichment")
            if not startup_sidecar:
                logger.info("Startup sidecar creation disabled by config; scanning without sidecars")
            # Only the process holding the lock performs startup enrichment
            # Attempt to acquire a sidecar creation slot for this scan
            slot_fd = _acquire_sidecar_slot(sidecar_slots) if startup_sidecar else None
            try:
                app.state.pending_images = new_files_detected(
                    allow_ai_enrichment=startup_ai,
                    allow_sidecar_creation=startup_sidecar and (slot_fd is not None or fcntl is None),
                )
            finally:
                _release_sidecar_slot(slot_fd)
        finally:
            _release_process_lock(mig_fd)
    else:
        logger.info(
            "Another process holds migration/enrichment lock; scanning without startup enrichment here",
        )
        if not startup_sidecar:
            logger.info("Startup sidecar creation disabled by config; scanning without sidecars")
        slot_fd = _acquire_sidecar_slot(sidecar_slots) if startup_sidecar else None
        try:
            app.state.pending_images = new_files_detected(
                allow_ai_enrichment=False,
                allow_sidecar_creation=startup_sidecar and (slot_fd is not None or fcntl is None),
            )
        finally:
            _release_sidecar_slot(slot_fd)
    app.state.watcher_task = None
    app.state.watcher_lock_fd = None
    if os.getenv("DISABLE_WATCHER", "").strip().lower() not in {"1", "true", "yes", "y"}:
        lock_fd = _acquire_process_lock(WATCHER_LOCK_PATH)
        if lock_fd is not None:
            app.state.watcher_lock_fd = lock_fd
            app.state.watcher_task = asyncio.create_task(_watch_image_directory(app))
            logger.info("Started image watcher in this process (lock acquired)")
        else:
            logger.info("Another process holds the watcher lock; skipping watcher here")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    watcher = getattr(app.state, "watcher_task", None)
    if watcher:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
    _release_process_lock(getattr(app.state, "watcher_lock_fd", None))

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
    data.setdefault("caption", "")
    data.setdefault("author", "")
    data.setdefault("copyright", "")
    data.setdefault("reviewed", False)
    data.setdefault("detected_at", time.time())
    data.setdefault("ai_generated", False)
    if not isinstance(data.get("ai_details"), dict):
        data["ai_details"] = {}
    tags = data.get("tags")
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    if not isinstance(tags, list):
        tags = []
    else:
        tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    data["tags"] = tags
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
    tags_value = data.get("tags")
    if isinstance(tags_value, str):
        tags_value = [tag.strip() for tag in tags_value.split(",") if tag.strip()]
    if not isinstance(tags_value, list):
        tags_value = []
    else:
        tags_value = [str(tag).strip() for tag in tags_value if str(tag).strip()]
    data["tags"] = tags_value
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
    dashboard = _gather_admin_dashboard_data()
    pending = dashboard["pending"]
    request.app.state.pending_images = pending
        return templates.TemplateResponse(
            "reviewAddedFiles.html",
            {
                "request": request,
                "pending_images": pending,
                "reviewed_images": dashboard["reviewed"],
                "admin_data": dashboard,
                "model_options": OPENAI_MODEL_CHOICES,
                "allowed_extensions": sorted(ALLOWED_IMAGE_EXTENSIONS),
            },
        )


@app.get("/admin/review", response_class=HTMLResponse)
async def review_added_files(request: Request) -> HTMLResponse:
    dashboard = _gather_admin_dashboard_data()
    pending = dashboard["pending"]
    request.app.state.pending_images = pending
        return templates.TemplateResponse(
            "reviewAddedFiles.html",
            {
                "request": request,
                "pending_images": pending,
                "reviewed_images": dashboard["reviewed"],
                "admin_data": dashboard,
                "model_options": OPENAI_MODEL_CHOICES,
                "allowed_extensions": sorted(ALLOWED_IMAGE_EXTENSIONS),
            },
        )


@app.get("/admin/advanced", response_class=HTMLResponse)
async def advanced_settings(request: Request) -> HTMLResponse:
    adv = getattr(app.state, "advanced_config", _load_advanced_config())
    return templates.TemplateResponse(
        "advancedSettings.html",
        {
            "request": request,
            "advanced": adv,
        },
    )


@app.post("/admin/advanced", response_class=JSONResponse)
async def update_advanced_settings(request: Request) -> JSONResponse:
    data: Dict[str, Any] = {}
    try:
        data = await request.json()
    except Exception:
        # Fallback to form data
        form = await request.form()
        data = {k: form.get(k) for k in form.keys()}
    cfg = _sanitize_advanced_config(data or {})
    request.app.state.advanced_config = cfg
    _save_advanced_config(cfg)
    _apply_logging_config(cfg)
    return JSONResponse({"advanced": cfg, "message": "Advanced settings updated"})


@app.post("/admin/advanced/reset", response_class=JSONResponse)
async def reset_advanced_settings(request: Request) -> JSONResponse:
    cfg = _default_advanced_config_from_env()
    request.app.state.advanced_config = cfg
    _save_advanced_config(cfg)
    _apply_logging_config(cfg)
    return JSONResponse({"advanced": cfg, "message": "Advanced settings reset to defaults"})


@app.get("/admin/api/new-files", response_class=JSONResponse)
async def api_new_files(request: Request) -> JSONResponse:
    dashboard = _gather_admin_dashboard_data()
    request.app.state.pending_images = dashboard["pending"]
    return JSONResponse({"pending": dashboard["pending"], "reviewed": dashboard["reviewed"]})


@app.get("/admin/api/gallery", response_class=JSONResponse)
async def api_gallery_data() -> JSONResponse:
    dashboard = _gather_admin_dashboard_data()
    return JSONResponse(dashboard)


@app.get("/admin/config", response_class=JSONResponse)
async def get_admin_config() -> JSONResponse:
    cfg = _get_ai_config()
    return JSONResponse({
        "ai": cfg,
        "allowed_extensions": sorted(ALLOWED_IMAGE_EXTENSIONS),
    })


@app.post("/admin/config", response_class=JSONResponse)
async def update_admin_config(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    ai = body.get("ai", body) if isinstance(body, dict) else {}
    cfg = _get_ai_config()
    if isinstance(ai, dict):
        if "enabled" in ai:
            cfg["enabled"] = bool(ai["enabled"])
        if "startup_enrichment_enabled" in ai:
            cfg["startup_enrichment_enabled"] = bool(ai["startup_enrichment_enabled"])
        if "startup_sidecar_enabled" in ai:
            cfg["startup_sidecar_enabled"] = bool(ai["startup_sidecar_enabled"])
        if "max_workers_create_sidecars" in ai:
            try:
                cfg["max_workers_create_sidecars"] = max(1, min(64, int(ai["max_workers_create_sidecars"])) )
            except (TypeError, ValueError):
                pass
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
        if "startup_enrichment_enabled" in ai:
            cfg["startup_enrichment_enabled"] = bool(ai["startup_enrichment_enabled"])
    request.app.state.ai_config = cfg
    _save_ai_config(cfg)
    return JSONResponse({"ai": cfg, "message": "Configuration updated and saved"})


@app.post("/admin/config/reset", response_class=JSONResponse)
async def reset_admin_config(request: Request) -> JSONResponse:
    cfg = _default_ai_config_from_env()
    request.app.state.ai_config = cfg
    _save_ai_config(cfg)
    return JSONResponse({"ai": cfg, "message": "Configuration reset to defaults"})


@app.post("/admin/ai/regenerate", response_class=JSONResponse)
async def regenerate_ai_metadata(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    images = body.get("images") or []
    force = bool(body.get("force", False))
    if not isinstance(images, list) or not images:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No images provided")

    updated = []
    errors = []
    for name in images:
        fname = _sanitize_filename(str(name))
        if not fname or not _allowed_image(fname):
            errors.append({"name": name, "error": "Unsupported or invalid filename"})
            continue
        path = IMAGES_DIR / fname
        if not path.exists():
            errors.append({"name": name, "error": "File not found"})
            continue
        try:
            meta = _load_metadata(path)
            if force:
                meta["title"] = ""
                meta["description"] = ""
                meta["caption"] = ""
                meta["author"] = ""
                meta["tags"] = []
                meta["ai_generated"] = False
            meta = _populate_missing_metadata(path, meta)
            _write_sidecar(path, meta)
            updated.append({"name": fname, "metadata": meta})
        except Exception as exc:
            errors.append({"name": name, "error": str(exc)})

    dashboard = _gather_admin_dashboard_data()
    request.app.state.pending_images = dashboard["pending"]
    return JSONResponse(
        {
            "updated": updated,
            "errors": errors,
            "pending": dashboard["pending"],
            "reviewed": dashboard["reviewed"],
        }
    )


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

    dashboard = _gather_admin_dashboard_data()
    request.app.state.pending_images = dashboard["pending"]
    message = "Uploaded files successfully" if saved else "No supported files uploaded"
    return JSONResponse(
        {
            "saved": saved,
            "skipped": skipped,
            "message": message,
            "pending": dashboard["pending"],
            "reviewed": dashboard["reviewed"],
        }
    )


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

    dashboard = _gather_admin_dashboard_data()
    request.app.state.pending_images = dashboard["pending"]
    return JSONResponse(
        {
            "copied": copied,
            "skipped": skipped,
            "pending": dashboard["pending"],
            "reviewed": dashboard["reviewed"],
        }
    )


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
    caption: str = Form(""),
    author: str = Form(""),
    copyright: str = Form(""),
    tags: str = Form(""),
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

    if action == "mark_unreviewed":
        existing = _load_metadata(image_path)
        existing["reviewed"] = False
        _write_sidecar(image_path, existing)
        pending = new_files_detected()
        request.app.state.pending_images = pending
        return RedirectResponse(
            url=request.url_for("review_added_files"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    clean_metadata = {
        "title": title.strip() or image_path.stem,
        "description": description.strip(),
        "caption": caption.strip(),
        "author": author.strip(),
        "copyright": copyright.strip(),
    }
    tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
    clean_metadata["tags"] = tags_list
    # Merge with existing sidecar and mark as reviewed
    existing = _load_metadata(image_path)
    existing.update(clean_metadata)
    existing["reviewed"] = True
    existing["ai_generated"] = False
    _write_sidecar(image_path, existing)

    pending = new_files_detected()
    request.app.state.pending_images = pending

    return RedirectResponse(
        url=request.url_for("review_added_files"),
        status_code=status.HTTP_303_SEE_OTHER,
    )



@app.delete("/admin/image/{image_name}", response_class=JSONResponse)
async def delete_image(request: Request, image_name: str) -> JSONResponse:
    filename = _sanitize_filename(image_name)
    if not filename or not _allowed_image(filename):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    image_path = IMAGES_DIR / filename
    json_path = image_path.with_suffix(".json")

    if not image_path.exists() and not json_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    try:
        if image_path.exists():
            image_path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    with suppress(OSError):
        if json_path.exists():
            json_path.unlink()

    dashboard = _gather_admin_dashboard_data()
    request.app.state.pending_images = dashboard["pending"]
    return JSONResponse(
        {
            "message": f"Removed {filename}",
            "pending": dashboard["pending"],
            "reviewed": dashboard["reviewed"],
        }
    )


@app.get("/artwork/{image_filename}", response_class=HTMLResponse)
async def artwork_detail(request: Request, image_filename: str):
    """
    Displays the details of a single piece of artwork.
    """
    filename = _sanitize_filename(image_filename)
    if not filename or not _allowed_image(filename):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artwork not found")

    image_path = IMAGES_DIR / filename
    if not image_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artwork not found")

    metadata = _load_metadata(image_path)
    image_url = f"/static/images/{filename}"

    artwork_data = {
        "title": metadata.get("title", "Artwork"),
        "description": metadata.get("description", ""),
        "image_url": image_url,
    }

    return templates.TemplateResponse(
        "artwork_detail.html",
        {"request": request, "artwork": artwork_data},
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
