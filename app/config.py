"""Paths, environment configuration, and runtime AI settings."""

import logging
import os
import threading
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

# --- Configuration ---
# The repository root (this file lives in app/).
BASE_DIR = Path(__file__).resolve().parent.parent
# Static files are served from the URL path `/static`, but the folder in
# the repository is named with a capital "S".
STATIC_DIR = BASE_DIR / "Static"
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", STATIC_DIR / "images"))
_USING_VOLUME = IMAGES_DIR != STATIC_DIR / "images"
# Images are always served from /images (approved-only, see app/media.py),
# whether or not IMAGES_DIR is a mounted volume.
IMAGES_URL_PREFIX = "/images"
# Pre-generated WebP derivative widths: gallery grids and the detail page.
THUMB_WIDTH = 480
DISPLAY_WIDTH = 1600
WEBP_QUALITY = 80
# Derivatives built for existing images per watcher scan (5 s apart).
DERIVATIVE_BACKFILL_PER_SCAN = 5
# Cloudflare cache purge for images that stop being public; both optional.
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID", "").strip()
IMPORT_ROOT = Path(os.getenv("IMPORT_ROOT", BASE_DIR / "imports"))
GALLERY_TITLE = os.getenv("GALLERY_TITLE", "Artazzen Gallery")
SITE_URL = os.getenv("SITE_URL", "https://artazzen.com").rstrip("/")
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
OPENAI_DEFAULT_MODEL = "gpt-6-luna"
# Reasoning model families: no 'temperature' parameter, and they spend output
# tokens on reasoning before emitting text.
REASONING_MODEL_PREFIXES = ("gpt-5", "gpt-6")
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high")
DEFAULT_REASONING_EFFORT = "low"
# Efforts a model rejects with HTTP 400.
UNSUPPORTED_REASONING_EFFORTS: dict[str, frozenset[str]] = {
    "gpt-6-astra": frozenset({"none"}),
    "gpt-6.1-sol": frozenset({"none", "minimal"}),
}


def _coerce_reasoning_effort(value: Any, model: str) -> str:
    """Return a reasoning effort the given model accepts."""
    effort = str(value or "").strip().lower()
    if effort not in REASONING_EFFORTS:
        return DEFAULT_REASONING_EFFORT
    if effort in UNSUPPORTED_REASONING_EFFORTS.get(model, frozenset()):
        return DEFAULT_REASONING_EFFORT
    return effort


try:
    OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
except ValueError:
    OPENAI_TIMEOUT_SECONDS = 30.0

# Create necessary directories if they don't exist
STATIC_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
IMPORT_ROOT.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True)  # For optional CSS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["site_url"] = SITE_URL

# RLock: writers that must make a read-merge-write cycle atomic (e.g. the
# AI populate persist path) hold it across _write_sidecar, which acquires
# it again.
sidecar_lock = threading.RLock()
config_lock = threading.Lock()

# Runtime AI configuration, populated by the app lifespan and the admin
# config routes. Kept at module level (not app.state) so every layer reads
# the same source of truth.
runtime_ai_config: dict[str, Any] = {}


def _coerce_bool(value: Any) -> bool:
    """Safely coerce a bool or string to a Python bool.

    Strings like "false"/"0"/"no" become False; plain bool() would treat
    any non-empty string as True.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _get_ai_config() -> dict[str, Any]:
    """Return runtime AI config with env fallbacks."""
    cfg = runtime_ai_config
    enabled = _coerce_bool(cfg.get("enabled", True))
    model = str(cfg.get("model", os.getenv(OPENAI_MODEL_ENV, OPENAI_DEFAULT_MODEL)))
    try:
        temperature = float(cfg.get("temperature", 0.6))
    except (TypeError, ValueError):
        temperature = 0.6
    try:
        max_output_tokens = int(cfg.get("max_output_tokens", 600))
    except (TypeError, ValueError):
        max_output_tokens = 600
    # Reasoning models spend output tokens on reasoning before emitting text;
    # too small a budget yields incomplete (empty-text) responses.
    if model.startswith(REASONING_MODEL_PREFIXES) and max_output_tokens < 1200:
        max_output_tokens = 1200
    return {
        "enabled": enabled,
        "model": model,
        "temperature": temperature,
        "reasoning_effort": _coerce_reasoning_effort(
            cfg.get("reasoning_effort"), model
        ),
        "max_output_tokens": max_output_tokens,
        "default_artist": str(cfg.get("default_artist", "")),
        "artist_in_prompt": _coerce_bool(cfg.get("artist_in_prompt", True)),
        "default_copyright": str(cfg.get("default_copyright", "")),
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


# Automatic (watcher) OpenAI retries for an image whose attempt left fields
# empty: at most AI_MAX_RETRIES more tries, AI_RETRY_DELAY_SECONDS apart.
# Without a limit one failing image is re-uploaded on every poll.
AI_MAX_RETRIES = max(0, _parse_int_env(os.getenv("AI_MAX_RETRIES"), 5))
AI_RETRY_DELAY_SECONDS = max(
    float(POLL_INTERVAL_SECONDS),
    _parse_float_env(os.getenv("AI_RETRY_DELAY_SECONDS"), 60.0),
)


def _default_ai_config_from_env() -> dict[str, Any]:
    return {
        "enabled": _parse_bool_env(os.getenv("AI_METADATA_ENABLED"), True),
        "model": os.getenv(OPENAI_MODEL_ENV, OPENAI_DEFAULT_MODEL),
        "temperature": _parse_float_env(
            os.getenv("OPENAI_IMAGE_METADATA_TEMPERATURE"), 0.6
        ),
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "max_output_tokens": _parse_int_env(
            os.getenv("OPENAI_IMAGE_METADATA_MAX_TOKENS"), 600
        ),
        "default_artist": os.getenv("DEFAULT_ARTIST", ""),
        "artist_in_prompt": True,
        "default_copyright": os.getenv("DEFAULT_COPYRIGHT", ""),
    }


def _sanitize_ai_config(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(_default_ai_config_from_env())
    if isinstance(cfg, dict):
        if "enabled" in cfg:
            out["enabled"] = _coerce_bool(cfg.get("enabled"))
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
        if isinstance(cfg.get("default_artist"), str):
            out["default_artist"] = cfg["default_artist"].strip()
        if "artist_in_prompt" in cfg:
            out["artist_in_prompt"] = _coerce_bool(cfg.get("artist_in_prompt"))
        if isinstance(cfg.get("default_copyright"), str):
            out["default_copyright"] = cfg["default_copyright"].strip()
        out["reasoning_effort"] = _coerce_reasoning_effort(
            cfg.get("reasoning_effort", out["reasoning_effort"]), out["model"]
        )
    return out


def _load_ai_config() -> dict[str, Any]:
    import json
    from contextlib import suppress

    base = _default_ai_config_from_env()
    if CONFIG_PATH.exists():
        with suppress(json.JSONDecodeError, OSError):
            persisted = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return _sanitize_ai_config({**base, **(persisted or {})})
    return base


def _save_ai_config(cfg: dict[str, Any]) -> None:
    from app import sidecars

    with config_lock:
        sidecars._atomic_write_json(CONFIG_PATH, _sanitize_ai_config(cfg))
