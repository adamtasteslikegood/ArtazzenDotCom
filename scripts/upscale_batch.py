#!/usr/bin/env python3
"""Batch-upscale a folder of 72 DPI originals into 300 DPI print masters.

Back-catalog companion to the in-app pipeline (app/print_master.py). Point it
at a folder of Procreate Pocket exports and it writes AI-upscaled PNG
masters tagged at 300 DPI, ready for large-format printing or for
uploading to the gallery.

Examples:
    # Local torch backend (pip install -r requirements-upscale.txt)
    python3 scripts/upscale_batch.py --src ~/ArtazZen/Originals_72DPI \\
        --dst ~/ArtazZen/Master_300DPI_Upscaled --model digital

    # Hosted backend (export REPLICATE_API_TOKEN=...)
    python3 scripts/upscale_batch.py --src ./originals --dst ./masters \\
        --backend replicate
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _patch_basicsr() -> None:
    """basicsr 1.4.2 imports a symbol torchvision>=0.17 removed."""
    try:
        import basicsr  # noqa: F401
    except ImportError:
        return
    except Exception:  # noqa: S110 - basicsr present but unhealthy; still patch
        pass
    try:
        import torchvision.transforms.functional_tensor  # noqa: F401

        return  # old torchvision, nothing to patch
    except ImportError:
        pass
    import types

    import torchvision.transforms.functional as F

    shim = types.ModuleType("torchvision.transforms.functional_tensor")
    shim.rgb_to_grayscale = F.rgb_to_grayscale
    sys.modules["torchvision.transforms.functional_tensor"] = shim


EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="Folder of 72 DPI originals")
    ap.add_argument("--dst", required=True, help="Output folder for masters")
    ap.add_argument(
        "--model",
        choices=["general", "digital"],
        default="general",
        help="'digital' = anime/flat-art model (faster); "
        "'general' = photographic/painterly (default)",
    )
    ap.add_argument("--scale", type=int, default=4, choices=[2, 3, 4])
    ap.add_argument(
        "--backend",
        choices=["torch", "binary", "replicate"],
        default=None,
        help="Force a backend (default: auto)",
    )
    ap.add_argument("--suffix", default="_master300")
    args = ap.parse_args()

    _patch_basicsr()
    from app import print_master as pm

    src_dir, dst_dir = Path(args.src).expanduser(), Path(args.dst).expanduser()
    files = sorted(
        p for p in src_dir.iterdir() if p.is_file() and p.suffix.lower() in EXTS
    )
    if not files:
        print(f"No images found in {src_dir}")
        return 1

    backend = args.backend or pm.available_backend()
    if not backend:
        print(
            "No upscale backend available. Either:\n"
            "  pip install -r requirements-upscale.txt   (torch)\n"
            "  export REALESRGAN_BIN=/path/to/realesrgan-ncnn-vulkan\n"
            "  export REPLICATE_API_TOKEN=r8_..."
        )
        return 2

    # The module writes to <images_dir>/print_masters/<stem>_master300.png;
    # for the CLI we treat --dst as that folder directly.
    pm.PRINT_MASTER_DIRNAME = "."
    pm.PRINT_MASTER_SUFFIX = args.suffix
    dst_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"backend={backend} model={args.model} scale={args.scale}x "
        f"files={len(files)}"
    )
    failures = 0
    for i, f in enumerate(files, 1):
        result = pm.generate_print_master(
            f, dst_dir, scale=args.scale, model=args.model, backend=backend
        )
        if result["status"] == "done":
            print(
                f"[{i}/{len(files)}] {f.name} -> "
                f"{result['width']}x{result['height']} @300dpi "
                f"(prints {result['width']/300:.1f}\" x "
                f"{result['height']/300:.1f}\")"
            )
        else:
            failures += 1
            print(f"[{i}/{len(files)}] {f.name} FAILED: {result['error']}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
