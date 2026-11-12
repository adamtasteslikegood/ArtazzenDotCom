"""Synthetic artwork for analysis and job tests."""

import io

import numpy as np
from PIL import Image, ImageCms


def periodic(width: int, height: int, period: int = 50) -> Image.Image:
    """A pattern repeating every ``period`` px on both axes."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    t = 2 * np.pi / period
    r = 127 + 90 * np.sin(t * x) * np.cos(t * y)
    g = 127 + 90 * np.cos(2 * t * x + 1.0)
    b = 127 + 90 * np.sin(3 * t * y + 0.5) * np.cos(t * x)
    arr = np.stack([r, g, b], axis=2).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def gradient(width: int = 200, height: int = 160) -> Image.Image:
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    arr = np.stack(
        [x / width * 255, y / height * 255, (x + y) / (width + height) * 255], axis=2
    )
    return Image.fromarray(arr.astype(np.uint8))


def srgb_icc() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def png(img: Image.Image, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", **kwargs)
    return buf.getvalue()
