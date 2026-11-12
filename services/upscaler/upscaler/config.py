"""Service settings, read once from the environment.

On Railway every value comes from a variable reference: the bucket's
credentials from ``wrapped-stand``, the admin login from the gallery service,
and ``GALLERY_URL`` from the gallery's private domain. Nothing is copied.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent

# Same list as the gallery (app/config.py ALLOWED_IMAGE_EXTENSIONS).
ALLOWED_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}
)

# Gallery derivative width used for picker thumbnails (gallery THUMB_WIDTH).
GALLERY_THUMB_WIDTH = 480


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    admin_username: str = "admin"
    admin_password: str = field(default="", repr=False)
    gallery_url: str = ""
    # Public gallery admin URL for the "back to gallery" link. GALLERY_URL is
    # the private-network address, which a browser cannot reach.
    gallery_admin_url: str = ""
    bucket: str = ""
    endpoint: str = ""
    access_key_id: str = ""
    secret_access_key: str = field(default="", repr=False)
    region: str = "auto"
    # Optional key prefix inside the bucket, e.g. "dev/" for local runs
    # against the production bucket.
    bucket_prefix: str = ""
    import_root: Path = SERVICE_DIR / "imports"
    max_upload_mb: float = 50.0
    max_megapixels: float = 100.0
    # Replicate. The model's input names (image, scale, face_enhance) come
    # from PR #130's working code. The input ceiling, timing and price are
    # assumptions until checked against the model page; each is an env var.
    replicate_api_token: str = field(default="", repr=False)
    replicate_model: str = "nightmareai/real-esrgan"
    replicate_version: str = ""
    replicate_max_input_mp: float = 4.0
    replicate_timeout_seconds: float = 1800.0
    poll_seconds: float = 3.0
    seconds_per_mp: float = 10.0
    price_per_second: float = 0.000225
    max_concurrent_jobs: int = 1
    # Pillow refuses to decode beyond this; post-processing raises it on
    # purpose because a 4x master is 16x the input's pixels.
    max_output_megapixels: float = 400.0
    print_dpi: int = 300

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @classmethod
    def from_env(cls) -> Settings:
        prefix = os.getenv("UPSCALER_BUCKET_PREFIX", "").strip().strip("/")
        return cls(
            admin_username=os.getenv("ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("ADMIN_PASSWORD", ""),
            gallery_url=os.getenv("GALLERY_URL", "").strip().rstrip("/"),
            gallery_admin_url=os.getenv("GALLERY_ADMIN_URL", "").strip(),
            bucket=os.getenv("BUCKET", "").strip(),
            endpoint=os.getenv("ENDPOINT", "").strip(),
            access_key_id=os.getenv("ACCESS_KEY_ID", "").strip(),
            secret_access_key=os.getenv("SECRET_ACCESS_KEY", "").strip(),
            region=os.getenv("REGION", "").strip() or "auto",
            bucket_prefix=f"{prefix}/" if prefix else "",
            import_root=Path(
                os.getenv("UPSCALER_IMPORT_ROOT", "") or SERVICE_DIR / "imports"
            ),
            max_upload_mb=_float("UPSCALER_MAX_UPLOAD_MB", 50.0),
            max_megapixels=_float("UPSCALER_MAX_MEGAPIXELS", 100.0),
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN", "").strip(),
            replicate_model=os.getenv("REPLICATE_UPSCALE_MODEL", "").strip()
            or "nightmareai/real-esrgan",
            replicate_version=os.getenv("REPLICATE_UPSCALE_VERSION", "").strip(),
            replicate_max_input_mp=_float("UPSCALER_REPLICATE_MAX_INPUT_MP", 4.0),
            replicate_timeout_seconds=_float("REPLICATE_TIMEOUT_SECONDS", 1800.0),
            poll_seconds=_float("UPSCALER_POLL_SECONDS", 3.0),
            seconds_per_mp=_float("UPSCALER_SECONDS_PER_MP", 10.0),
            price_per_second=_float("UPSCALER_PRICE_PER_SECOND", 0.000225),
            max_concurrent_jobs=max(1, _int("UPSCALER_MAX_CONCURRENT_JOBS", 1)),
            max_output_megapixels=_float("UPSCALER_MAX_OUTPUT_MEGAPIXELS", 400.0),
            print_dpi=_int("UPSCALER_PRINT_DPI", 300),
        )
