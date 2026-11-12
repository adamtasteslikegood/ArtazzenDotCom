"""Seam analysis, repeat extraction and the wrap/tile pad-and-crop maths.

Ported from the art-upscaler skill scripts (``_common.seam_scores``,
``inspect_batch.find_periods``, ``extract_tile.search_tile`` and the mode
handling in ``upscale.py``). Pure numpy/Pillow; nothing here talks to the
network or the bucket.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

SEAMLESS_MAX_RATIO = 2.0
PERIOD_MIN_CORR = 0.55
PERIOD_MIN_PX = 40
GOOD_TILE_RATIO = 1.5
WRAP_PAD = 32
# Verdicts run on a downscaled copy above this size; the seam ratios are
# relative to the image's own detail, so they survive the resize.
ANALYSIS_MAX_PIXELS = 4_000_000
# Repeat extraction needs full resolution; refuse beyond this.
TILE_SEARCH_MAX_PIXELS = 16_000_000


def to_rgb_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"))


def seam_scores(arr: np.ndarray) -> tuple[float, float]:
    """(left-right, top-bottom) wrap-seam difference over mean internal detail.

    About 1 or less means the edges wrap; much more than 1 is a visible seam.
    """
    a = arr.astype(np.float32)
    lr = np.abs(a[:, 0] - a[:, -1]).mean()
    tb = np.abs(a[0, :] - a[-1, :]).mean()
    internal = (
        np.abs(np.diff(a, axis=1)).mean() + np.abs(np.diff(a, axis=0)).mean()
    ) / 2
    internal = max(float(internal), 1e-6)
    return float(lr / internal), float(tb / internal)


def find_periods(arr: np.ndarray, axis: int) -> list[tuple[int, float]]:
    """FFT autocorrelation along ``axis``: up to three ``(lag, corr)`` peaks."""
    a = arr.astype(np.float32).mean(axis=2)
    a -= a.mean()
    n = a.shape[axis]
    f = np.fft.rfft(a, axis=axis)
    ac = np.fft.irfft(f * np.conj(f), axis=axis, n=n)
    prof = ac.mean(axis=1 - axis)
    prof = prof / max(float(prof[0]), 1e-9)
    cands = []
    for lag in range(PERIOD_MIN_PX, n // 2):
        if (
            prof[lag] > prof[lag - 1]
            and prof[lag] >= prof[lag + 1]
            and prof[lag] > PERIOD_MIN_CORR
        ):
            cands.append((int(lag), round(float(prof[lag]), 3)))
    cands.sort(key=lambda c: -c[1])
    return cands[:3]


@dataclass(frozen=True)
class SeamReport:
    lr_ratio: float
    tb_ratio: float
    periods_h: list[tuple[int, float]]
    periods_v: list[tuple[int, float]]
    verdict: str  # seamless | repeating | composition
    scale: float  # analysed size / real size (1.0 = full resolution)


def seam_report(img: Image.Image) -> SeamReport:
    w, h = img.size
    scale = 1.0
    work = img
    if w * h > ANALYSIS_MAX_PIXELS:
        scale = (ANALYSIS_MAX_PIXELS / (w * h)) ** 0.5
        work = img.resize(
            (max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS
        )
    arr = to_rgb_array(work)
    lr, tb = seam_scores(arr)
    ph = find_periods(arr, 1)
    pv = find_periods(arr, 0)
    if lr < SEAMLESS_MAX_RATIO and tb < SEAMLESS_MAX_RATIO:
        verdict = "seamless"
    elif ph and pv:
        verdict = "repeating"
    else:
        verdict = "composition"
    return SeamReport(round(lr, 2), round(tb, 2), ph, pv, verdict, scale)


def search_tile(
    arr: np.ndarray,
    pw0: int,
    ph0: int,
    span: int = 6,
    origin_max: int = 80,
    step: int = 2,
) -> tuple[float, tuple[int, int, int, int] | None]:
    """Best ``(seam, (x0, y0, pw, ph))`` crop around period ``(pw0, ph0)``."""
    a = arr.astype(np.float32).mean(axis=2)
    height, width = a.shape
    best: tuple[float, tuple[int, int, int, int] | None] = (np.inf, None)
    for pw in range(pw0 - span, pw0 + span + 1):
        if pw <= 0 or pw >= width - 1:
            continue
        ccol = np.cumsum(np.abs(a[:, : width - pw] - a[:, pw:]), axis=0)
        for ph in range(ph0 - span, ph0 + span + 1):
            if ph <= 0 or ph >= height - 1:
                continue
            crow = np.cumsum(np.abs(a[: height - ph, :] - a[ph:, :]), axis=1)
            for y0 in range(0, min(origin_max, height - ph - 1), step):
                lr_all = (ccol[y0 + ph - 1] - (ccol[y0 - 1] if y0 else 0)) / ph
                for x0 in range(0, min(origin_max, width - pw - 1), step):
                    tb = (crow[y0, x0 + pw - 1] - (crow[y0, x0 - 1] if x0 else 0)) / pw
                    s = float((lr_all[x0] + tb) / 2)
                    if s < best[0]:
                        best = (s, (x0, y0, pw, ph))
    return best


@dataclass(frozen=True)
class TileResult:
    box: tuple[int, int, int, int]  # x0, y0, width, height
    seam_ratio: float
    tile: Image.Image

    @property
    def good(self) -> bool:
        return self.seam_ratio < GOOD_TILE_RATIO


class AnalysisError(ValueError):
    """The image cannot be prepared this way; the message is user-facing."""


def extract_tile(img: Image.Image, report: SeamReport) -> TileResult:
    w, h = img.size
    if w * h > TILE_SEARCH_MAX_PIXELS:
        raise AnalysisError(
            f"{w}×{h} is too large to search for a repeat; crop it to a few "
            "repeats first"
        )
    if not (report.periods_h and report.periods_v):
        raise AnalysisError(
            "No repeat was found, so there is no tile to extract. Use "
            "“Print master” for a standalone artwork."
        )
    arr = to_rgb_array(img)
    pw0 = round(report.periods_h[0][0] / report.scale)
    ph0 = round(report.periods_v[0][0] / report.scale)
    seam, box = search_tile(arr, pw0, ph0)
    if box is None:
        raise AnalysisError("No tile crop fits inside the image")
    x0, y0, pw, ph = box
    crop = arr[y0 : y0 + ph, x0 : x0 + pw].astype(np.float32)
    internal = (
        np.abs(np.diff(crop, axis=1)).mean() + np.abs(np.diff(crop, axis=0)).mean()
    ) / 2
    ratio = round(seam / max(float(internal), 1e-6), 2)
    tile = img.convert("RGB").crop((x0, y0, x0 + pw, y0 + ph))
    return TileResult((x0, y0, pw, ph), ratio, tile)


def repeat_grid(img: Image.Image, n: int) -> Image.Image:
    """``img`` tiled ``n``×``n``."""
    w, h = img.size
    grid = Image.new(img.mode, (w * n, h * n))
    for dx in range(n):
        for dy in range(n):
            grid.paste(img, (dx * w, dy * h))
    return grid


def proof(img: Image.Image, n: int, max_side: int = 1200) -> Image.Image:
    """An ``n``×``n`` tiling preview at most ``max_side`` px wide.

    Shrinks first, so a large master never becomes an n²-sized grid in memory.
    """
    small = img.convert("RGB")
    if max(small.size) * n > max_side:
        small = small.copy()
        small.thumbnail((max(1, max_side // n), max(1, max_side // n)))
    return repeat_grid(small, n)


def wrap_pad(img: Image.Image, pad: int = WRAP_PAD) -> Image.Image:
    arr = np.asarray(img.convert("RGB"))
    return Image.fromarray(np.pad(arr, ((pad, pad), (pad, pad), (0, 0)), mode="wrap"))


def crop_box(
    mode: str, base_size: tuple[int, int], scale: int
) -> tuple[int, int, int, int] | None:
    """The box to cut from the upscaled output, or None to keep it whole.

    ``base_size`` is the source (wrap) or the extracted tile (tile).
    """
    w, h = base_size
    if mode == "wrap":
        p = WRAP_PAD * scale
        return (p, p, p + w * scale, p + h * scale)
    if mode == "tile":
        return (w * scale, h * scale, 2 * w * scale, 2 * h * scale)
    return None
