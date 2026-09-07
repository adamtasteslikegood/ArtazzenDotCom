"""Print-master generation: AI-upscale gallery originals into 300 DPI masters.

Bridges 72 DPI Procreate Pocket exports to print-ready files using
Real-ESRGAN — the same engine and models that power Upscayl.

Three interchangeable backends, selected automatically (or forced via the
``UPSCALE_BACKEND`` environment variable; the admin config controls only
``upscale_enabled`` / ``upscale_scale`` / ``upscale_model``):

``torch``
    Local Real-ESRGAN via PyTorch. Used when the optional dependencies in
    ``requirements-upscale.txt`` are installed. Best for self-hosted boxes
    with real CPU/GPU headroom; too heavy for the Railway web dyno.

``binary``
    Shells out to a ``realesrgan-ncnn-vulkan`` executable (what Upscayl
    bundles). Enabled when ``REALESRGAN_BIN`` points at the binary.

``replicate``
    Calls the hosted Real-ESRGAN model on Replicate over HTTPS. Enabled when
    ``REPLICATE_API_TOKEN`` is set. This is the recommended backend for the
    Railway deployment: no heavy dependencies, pennies per image.

Every backend finishes the same way: the upscaled image is (re)saved with a
300 DPI tag and the original's ICC profile, into
``<images_dir>/print_masters/<stem>_master300.png``. Masters are the
full-resolution sellable asset, so they are never served from the public
static mounts (see ``security._PublicStaticFiles``); the admin download
route streams them to authenticated users only.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import io
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

PRINT_MASTER_SUFFIX = "_master300"
PRINT_MASTER_DIRNAME = "print_masters"
DEFAULT_SCALE = 4
DEFAULT_DPI = 300


def _env_float(name: str, default: float) -> float:
    """Parse a float env var; a bad value must never break app import."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("Ignoring non-numeric %s=%r; using %s", name, raw, default)
        return default


REPLICATE_API_BASE = "https://api.replicate.com/v1"
REPLICATE_MODEL = os.getenv("REPLICATE_UPSCALE_MODEL", "nightmareai/real-esrgan")
# Optional version pin. Community models (the default is one) must be run
# through POST /predictions with an explicit version id; when unset, the
# model's latest published version is resolved once per process.
REPLICATE_VERSION = os.getenv("REPLICATE_UPSCALE_VERSION", "").strip()
REPLICATE_TIMEOUT = _env_float("REPLICATE_TIMEOUT_SECONDS", 300.0)
REPLICATE_POLL_SECONDS = 3.0
# Replicate recommends inline data URLs only for small inputs (< 1 MB);
# anything bigger goes through the Files API.
REPLICATE_INLINE_MAX_BYTES = 200 * 1024

# Lazily-built torch upsamplers, keyed by model name.
_TORCH_UPSAMPLERS: dict[str, Any] = {}
# Resolved Replicate version per model; ``None`` marks an official model
# (which uses the models/{owner}/{name}/predictions endpoint instead).
_REPLICATE_VERSION_CACHE: dict[str, str | None] = {}


# --------------------------------------------------------------------------
# Backend discovery
# --------------------------------------------------------------------------


@functools.cache
def _torch_available() -> bool:
    # Cached: a failed import walks sys.path every call, and this runs on
    # every upload and status poll.
    try:  # pragma: no cover - depends on optional install
        import basicsr  # noqa: F401
        import realesrgan  # noqa: F401

        return True
    except Exception:
        return False


def _binary_path() -> str | None:
    configured = os.getenv("REALESRGAN_BIN", "").strip()
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("realesrgan-ncnn-vulkan")
    return found


def _replicate_token() -> str | None:
    token = os.getenv("REPLICATE_API_TOKEN", "").strip()
    return token or None


def available_backend() -> str | None:
    """Return the backend that would be used, or ``None`` if upscaling is
    unavailable in this environment."""
    forced = os.getenv("UPSCALE_BACKEND", "").strip().lower()
    if forced:
        if forced == "torch" and _torch_available():
            return "torch"
        if forced == "binary" and _binary_path():
            return "binary"
        if forced == "replicate" and _replicate_token():
            return "replicate"
        return None
    if _torch_available():
        return "torch"
    if _binary_path():
        return "binary"
    if _replicate_token():
        return "replicate"
    return None


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------


def _upscale_torch(src: Path, scale: int, model: str) -> Image.Image:
    """Local PyTorch Real-ESRGAN (optional dependency)."""
    import numpy as np
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    models_dir = Path(os.getenv("UPSCALE_MODELS_DIR", Path(__file__).parent / "models"))
    specs = {
        "general": (
            models_dir / "RealESRGAN_x4plus.pth",
            {
                "num_in_ch": 3,
                "num_out_ch": 3,
                "num_feat": 64,
                "num_block": 23,
                "num_grow_ch": 32,
                "scale": 4,
            },
        ),
        "digital": (
            models_dir / "RealESRGAN_x4plus_anime_6B.pth",
            {
                "num_in_ch": 3,
                "num_out_ch": 3,
                "num_feat": 64,
                "num_block": 6,
                "num_grow_ch": 32,
                "scale": 4,
            },
        ),
    }
    weight_path, net_kwargs = specs.get(model, specs["general"])
    if model not in _TORCH_UPSAMPLERS:
        _TORCH_UPSAMPLERS[model] = RealESRGANer(
            scale=4,
            model_path=str(weight_path),
            model=RRDBNet(**net_kwargs),
            tile=int(os.getenv("UPSCALE_TILE", "512")),
            tile_pad=16,
            pre_pad=0,
            half=False,
        )
    upsampler = _TORCH_UPSAMPLERS[model]

    with Image.open(src) as img:
        has_alpha = img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        )
        arr = np.array(img.convert("RGBA" if has_alpha else "RGB"))
    arr = arr[:, :, [2, 1, 0, 3]] if has_alpha else arr[:, :, ::-1]
    out, _ = upsampler.enhance(arr, outscale=scale)
    if out.shape[2] == 4:
        return Image.fromarray(out[:, :, [2, 1, 0, 3]], "RGBA")
    return Image.fromarray(out[:, :, ::-1], "RGB")


def _upscale_binary(src: Path, scale: int, model: str) -> Image.Image:
    """realesrgan-ncnn-vulkan executable (the engine Upscayl bundles)."""
    binary = _binary_path()
    if not binary:
        raise RuntimeError("REALESRGAN_BIN not configured")
    ncnn_model = {
        "general": "realesrgan-x4plus",
        "digital": "realesrgan-x4plus-anime",
    }.get(model, "realesrgan-x4plus")
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / f"{src.stem}_up.png"
        cmd = [
            binary,
            "-i",
            str(src),
            "-o",
            str(out_path),
            "-s",
            str(scale),
            "-n",
            ncnn_model,
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800, check=False
        )
        if proc.returncode != 0 or not out_path.exists():
            raise RuntimeError(
                f"realesrgan binary failed ({proc.returncode}): {proc.stderr[-400:]}"
            )
        with Image.open(out_path) as img:
            img.load()
            return img.copy()


_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _image_mime(path: Path) -> str | None:
    """MIME type for an image file, or ``None`` when it cannot be determined."""
    mime = _IMAGE_MIME.get(path.suffix.lower())
    if mime is None:
        guessed, _ = mimetypes.guess_type(path.name)
        mime = guessed if guessed and guessed.startswith("image/") else None
    return mime


def _replicate_prediction_target(
    client: httpx.Client, headers: dict[str, str]
) -> tuple[str, dict[str, str]]:
    """Return ``(url, extra_body)`` for creating a prediction.

    Replicate's ``/models/{owner}/{name}/predictions`` endpoint only accepts
    *official* models; community models such as the default
    ``nightmareai/real-esrgan`` must be started via ``/predictions`` with an
    explicit version id. Resolve (and cache) that once per process unless
    ``REPLICATE_UPSCALE_VERSION`` pins it.
    """
    if REPLICATE_VERSION:
        return f"{REPLICATE_API_BASE}/predictions", {"version": REPLICATE_VERSION}
    if REPLICATE_MODEL not in _REPLICATE_VERSION_CACHE:
        resp = client.get(
            f"{REPLICATE_API_BASE}/models/{REPLICATE_MODEL}", headers=headers
        )
        resp.raise_for_status()
        info = resp.json()
        if info.get("is_official"):
            _REPLICATE_VERSION_CACHE[REPLICATE_MODEL] = None
        else:
            version = (info.get("latest_version") or {}).get("id")
            if not version:
                raise RuntimeError(
                    f"Replicate model {REPLICATE_MODEL} has no published version"
                )
            _REPLICATE_VERSION_CACHE[REPLICATE_MODEL] = version
    version = _REPLICATE_VERSION_CACHE[REPLICATE_MODEL]
    if version is None:
        return f"{REPLICATE_API_BASE}/models/{REPLICATE_MODEL}/predictions", {}
    return f"{REPLICATE_API_BASE}/predictions", {"version": version}


def _upscale_replicate(src: Path, scale: int, model: str) -> Image.Image:
    """Hosted Real-ESRGAN on Replicate (recommended for Railway).

    The hosted model is the general-purpose ``x4plus`` network; ``model`` is
    recorded in the sidecar but has no effect on this backend.
    """
    token = _replicate_token()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN not configured")
    headers = {"Authorization": f"Bearer {token}"}

    data = src.read_bytes()
    mime = _image_mime(src)
    with httpx.Client(timeout=REPLICATE_TIMEOUT) as client:
        # Small files of a known type travel inline as a data URL; larger or
        # unrecognised ones go through the Replicate Files API.
        if mime and len(data) <= REPLICATE_INLINE_MAX_BYTES:
            image_ref = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        else:
            file_resp = client.post(
                f"{REPLICATE_API_BASE}/files",
                headers=headers,
                files={"content": (src.name, data, mime or "application/octet-stream")},
            )
            file_resp.raise_for_status()
            image_ref = file_resp.json()["urls"]["get"]

        url, extra = _replicate_prediction_target(client, headers)
        pred_resp = client.post(
            url,
            headers={**headers, "Prefer": "wait=60"},
            json={
                **extra,
                "input": {"image": image_ref, "scale": scale, "face_enhance": False},
            },
        )
        pred_resp.raise_for_status()
        prediction = pred_resp.json()

        # Poll until the prediction settles if "Prefer: wait" returned early.
        poll_url = (prediction.get("urls") or {}).get(
            "get"
        ) or f"{REPLICATE_API_BASE}/predictions/{prediction.get('id')}"
        deadline = time.time() + REPLICATE_TIMEOUT
        while prediction.get("status") in ("starting", "processing"):
            if time.time() > deadline:
                raise RuntimeError("Replicate prediction timed out")
            time.sleep(REPLICATE_POLL_SECONDS)
            poll = client.get(poll_url, headers=headers)
            poll.raise_for_status()
            prediction = poll.json()

        if prediction.get("status") != "succeeded":
            raise RuntimeError(
                f"Replicate prediction {prediction.get('status')}: "
                f"{str(prediction.get('error'))[:400]}"
            )

        output = prediction.get("output")
        output_url = output[0] if isinstance(output, list) else output
        if not output_url:
            raise RuntimeError("Replicate prediction succeeded without output")
        # Output URLs may point at third-party object storage. Never forward the\n        # Replicate bearer token outside the API host.\n        img_resp = client.get(output_url, follow_redirects=True)\n        img_resp.raise_for_status()
        img = Image.open(io.BytesIO(img_resp.content))
        img.load()
        return img


_BACKENDS = {
    "torch": _upscale_torch,
    "binary": _upscale_binary,
    "replicate": _upscale_replicate,
}


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def master_path_for(image_path: Path, images_dir: Path) -> Path:
    """Deterministic output location for an image's print master."""
    return (
        images_dir
        / PRINT_MASTER_DIRNAME
        / f"{image_path.stem}{PRINT_MASTER_SUFFIX}.png"
    )


def master_url_path(image_name: str) -> str:
    """Admin-only download URL for an image's print master."""
    return f"/admin/print-master/{quote(image_name)}/file"


def generate_print_master(
    image_path: Path,
    images_dir: Path,
    scale: int = DEFAULT_SCALE,
    dpi: int = DEFAULT_DPI,
    model: str = "general",
    backend: str | None = None,
) -> dict[str, Any]:
    """Upscale ``image_path`` into a 300 DPI print master.

    Blocking — call from a worker thread (``asyncio.to_thread``). Returns a
    dict shaped for the sidecar's ``print_master`` key. Never raises: errors
    are captured in the returned dict's ``status``/``error`` fields.
    """
    started = time.time()
    result: dict[str, Any] = {
        "status": "error",
        "file": "",
        "url_path": "",
        "width": 0,
        "height": 0,
        "dpi": dpi,
        "scale": scale,
        "model": model,
        "backend": "",
        "created": 0.0,
        "error": "",
    }
    try:
        chosen = backend or available_backend()
        if not chosen:
            raise RuntimeError(
                "No upscale backend available (set REPLICATE_API_TOKEN, "
                "REALESRGAN_BIN, or install requirements-upscale.txt)"
            )
        result["backend"] = chosen

        with Image.open(image_path) as src_img:
            icc = src_img.info.get("icc_profile")

        upscaled = _BACKENDS[chosen](image_path, scale, model)
        try:
            dst = master_path_for(image_path, images_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            save_kwargs: dict[str, Any] = {"dpi": (dpi, dpi), "format": "PNG"}
            if icc:
                save_kwargs["icc_profile"] = icc
            # Stage next to the destination and rename: a crash mid-save must
            # never leave a truncated master (regenerate overwrites in place).
            fd, tmp_name = tempfile.mkstemp(
                dir=dst.parent, prefix=f".{dst.stem}.", suffix=".tmp"
            )
            os.close(fd)
            try:
                upscaled.save(tmp_name, **save_kwargs)
                os.replace(tmp_name, dst)
            finally:
                Path(tmp_name).unlink(missing_ok=True)
            width, height = upscaled.size
        finally:
            upscaled.close()

        result.update(
            status="done",
            file=f"{PRINT_MASTER_DIRNAME}/{dst.name}",
            width=width,
            height=height,
            created=time.time(),
        )
        logger.info(
            "Print master ready: %s (%dx%d @%ddpi, backend=%s, %.1fs)",
            dst.name,
            width,
            height,
            dpi,
            chosen,
            time.time() - started,
        )
    except Exception as exc:
        logger.error("Print master failed for %s: %s", image_path.name, exc)
        result["error"] = str(exc)[:500]
        result["created"] = time.time()
    return result


# --------------------------------------------------------------------------
# App orchestration: sidecar tracking + background scheduling
# --------------------------------------------------------------------------
# The engine above is dependency-free (usable from scripts/upscale_batch.py);
# the helpers below wire it into the app. App imports stay inside functions
# so the layering (config -> sidecars -> print_master -> routes) holds and
# tests can monkeypatch the defining modules.

INTERRUPTED_ERROR = "Generation was interrupted (app restarted?). Run it again."

# Strong references to running tasks keyed by resolved image path. A bare
# ``asyncio.create_task`` result can be garbage-collected mid-run, and the
# registry is what lets the endpoints refuse a second concurrent run for
# the same image (two jobs would race on the same output file). It is
# per-process: the deployment runs a single uvicorn worker.
_IN_FLIGHT: dict[str, asyncio.Task[Any]] = {}


def _flight_key(image_path: Path) -> str:
    return os.path.realpath(os.fspath(image_path))


def is_in_flight(image_path: Path) -> bool:
    task = _IN_FLIGHT.get(_flight_key(image_path))
    return task is not None and not task.done()


def reconcile_state(image_path: Path, pm: dict[str, Any] | None) -> dict[str, Any]:
    """Return the effective ``print_master`` block for the admin UI.

    The sidecar alone can mislead: right after scheduling, the task may not
    have written its ``processing`` placeholder yet, and after a restart a
    ``processing`` block can be left behind with no worker attached. Either
    would leave the review page's button disabled and polling forever.
    """
    effective = dict(pm or {})
    if is_in_flight(image_path):
        effective["status"] = "processing"
        effective["error"] = ""
    elif effective.get("status") == "processing":
        effective["status"] = "error"
        effective["error"] = INTERRUPTED_ERROR
    return effective


def _set_print_master_sidecar(image_path: Path, pm: dict[str, Any]) -> None:
    """Persist the ``print_master`` block into the image's sidecar.

    Read-modify-write under the sidecar mutation lock: an admin save or AI
    persist landing between our read and write must not be lost.
    """
    from app import sidecars

    with sidecars.sidecar_mutation_lock.held():
        data = sidecars._load_metadata(image_path)
        data["print_master"] = pm
        data.setdefault("title", "")
        data.setdefault("description", "")
        data.setdefault("ai_generated", False)
        if not isinstance(data.get("ai_details"), dict):
            data["ai_details"] = {}
        data.setdefault("status", "pending")
        data.setdefault("detected_at", time.time())
        sidecars._write_sidecar(image_path, data)


def _print_master_settings() -> dict[str, Any]:
    from app import config

    cfg = config._get_ai_config()
    return {
        "enabled": bool(cfg.get("upscale_enabled", False)),
        "scale": int(cfg.get("upscale_scale", DEFAULT_SCALE)),
        "model": str(cfg.get("upscale_model", "general")),
        "backend": available_backend(),
    }


async def _generate_print_master_task(image_path: Path) -> dict[str, Any]:
    """Run upscaling off the event loop and record progress in the sidecar."""
    from app import config

    settings = _print_master_settings()
    pending = {
        "status": "processing",
        "file": "",
        "url_path": "",
        "width": 0,
        "height": 0,
        "dpi": DEFAULT_DPI,
        "scale": settings["scale"],
        "model": settings["model"],
        "backend": settings["backend"] or "",
        "created": 0.0,
        "error": "",
    }
    try:
        # Sidecar writes take the file lock; keep them off the event loop.
        await asyncio.to_thread(_set_print_master_sidecar, image_path, pending)
        result = await asyncio.to_thread(
            generate_print_master,
            image_path,
            config.IMAGES_DIR,
            settings["scale"],
            DEFAULT_DPI,
            settings["model"],
            settings["backend"],
        )
        if result.get("status") == "done" and result.get("file"):
            result["url_path"] = master_url_path(image_path.name)
        await asyncio.to_thread(_set_print_master_sidecar, image_path, result)
        return result
    except Exception:
        # A stuck "processing" block is reconciled to an error by
        # reconcile_state once this task is no longer in flight.
        logger.exception("Print-master task failed for %s", image_path.name)
        raise


def schedule_print_master(image_path: Path) -> bool:
    """Queue generation unless a run for this image is already in flight.

    Returns ``True`` when a task was created. Must be called from the event
    loop thread (request handlers).
    """
    key = _flight_key(image_path)
    if is_in_flight(image_path):
        return False
    task = asyncio.create_task(_generate_print_master_task(image_path))
    _IN_FLIGHT[key] = task

    def _clear(done: asyncio.Task[Any]) -> None:
        if _IN_FLIGHT.get(key) is done:
            del _IN_FLIGHT[key]

    task.add_done_callback(_clear)
    return True


def _schedule_print_master(image_path: Path) -> None:
    """Fire-and-forget print-master generation for a newly written image.

    Called after an upload or import wrote fresh bytes, so any existing
    master is stale and is regenerated; only an in-flight run is skipped.
    """
    settings = _print_master_settings()
    if not settings["enabled"] or not settings["backend"]:
        return
    schedule_print_master(image_path)
