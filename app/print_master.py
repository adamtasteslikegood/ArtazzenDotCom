"""Print-master generation: AI-upscale gallery originals into 300 DPI masters.

Bridges 72 DPI Procreate Pocket exports to print-ready files using
Real-ESRGAN — the same engine and models that power Upscayl.

Three interchangeable backends, selected automatically (or forced via the
``UPSCALE_BACKEND`` env var / admin config):

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
``<images_dir>/print_masters/<stem>_master300.png``.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

PRINT_MASTER_SUFFIX = "_master300"
PRINT_MASTER_DIRNAME = "print_masters"
DEFAULT_SCALE = 4
DEFAULT_DPI = 300

REPLICATE_API_BASE = "https://api.replicate.com/v1"
REPLICATE_MODEL = os.getenv("REPLICATE_UPSCALE_MODEL", "nightmareai/real-esrgan")
REPLICATE_TIMEOUT = float(os.getenv("REPLICATE_TIMEOUT_SECONDS", "300"))

# Lazily-built torch upsamplers, keyed by model name.
_TORCH_UPSAMPLERS: dict[str, Any] = {}


# --------------------------------------------------------------------------
# Backend discovery
# --------------------------------------------------------------------------


def _torch_available() -> bool:
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

    img = Image.open(src)
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
        img = Image.open(out_path)
        img.load()
        return img


def _upscale_replicate(src: Path, scale: int, model: str) -> Image.Image:
    """Hosted Real-ESRGAN on Replicate (recommended for Railway)."""
    token = _replicate_token()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN not configured")
    headers = {"Authorization": f"Bearer {token}"}

    data = src.read_bytes()
    with httpx.Client(timeout=REPLICATE_TIMEOUT) as client:
        # Small files can travel as a data URL; larger ones go through the
        # Replicate Files API.
        if len(data) <= 200 * 1024:
            mime = "image/png" if src.suffix.lower() == ".png" else "image/jpeg"
            image_ref = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        else:
            file_resp = client.post(
                f"{REPLICATE_API_BASE}/files",
                headers=headers,
                files={"content": (src.name, data)},
            )
            file_resp.raise_for_status()
            image_ref = file_resp.json()["urls"]["get"]

        pred_resp = client.post(
            f"{REPLICATE_API_BASE}/models/{REPLICATE_MODEL}/predictions",
            headers={**headers, "Prefer": "wait=60"},
            json={"input": {"image": image_ref, "scale": scale, "face_enhance": False}},
        )
        pred_resp.raise_for_status()
        prediction = pred_resp.json()

        # Poll until the prediction settles if "Prefer: wait" returned early.
        poll_url = (prediction.get("urls") or {}).get("get")
        deadline = time.time() + REPLICATE_TIMEOUT
        while prediction.get("status") in ("starting", "processing"):
            if time.time() > deadline:
                raise RuntimeError("Replicate prediction timed out")
            time.sleep(3)
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
        img_resp = client.get(output_url, headers=headers, follow_redirects=True)
        img_resp.raise_for_status()
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

        src_img = Image.open(image_path)
        icc = src_img.info.get("icc_profile")
        src_img.close()

        upscaled = _BACKENDS[chosen](image_path, scale, model)

        dst = master_path_for(image_path, images_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        save_kwargs: dict[str, Any] = {"dpi": (dpi, dpi)}
        if icc:
            save_kwargs["icc_profile"] = icc
        upscaled.save(dst, **save_kwargs)

        result.update(
            status="done",
            file=f"{PRINT_MASTER_DIRNAME}/{dst.name}",
            width=upscaled.size[0],
            height=upscaled.size[1],
            created=time.time(),
        )
        logger.info(
            "Print master ready: %s (%dx%d @%ddpi, backend=%s, %.1fs)",
            dst.name,
            upscaled.size[0],
            upscaled.size[1],
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


def _set_print_master_sidecar(image_path: Path, pm: dict[str, Any]) -> None:
    """Persist the ``print_master`` block into the image's sidecar."""
    from app import sidecars

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
    import asyncio

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
    _set_print_master_sidecar(image_path, pending)
    result = await asyncio.to_thread(
        generate_print_master,
        image_path,
        config.IMAGES_DIR,
        settings["scale"],
        DEFAULT_DPI,
        settings["model"],
    )
    if result.get("status") == "done" and result.get("file"):
        result["url_path"] = f"{config.IMAGES_URL_PREFIX}/{result['file']}"
    _set_print_master_sidecar(image_path, result)
    return result


def _schedule_print_master(image_path: Path) -> None:
    """Fire-and-forget print-master generation for a newly added image."""
    import asyncio

    from app import sidecars

    settings = _print_master_settings()
    if not settings["enabled"] or not settings["backend"]:
        return
    existing = sidecars._load_metadata(image_path).get("print_master") or {}
    if existing.get("status") in ("processing", "done"):
        return
    asyncio.create_task(_generate_print_master_task(image_path))
