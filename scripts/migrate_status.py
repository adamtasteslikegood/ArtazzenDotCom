#!/usr/bin/env python3
"""Migrate sidecar JSON files from reviewed (boolean) to status (enum).

Usage:
    python scripts/migrate_status.py [--images-dir Static/images]
    python scripts/migrate_status.py --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def migrate(images_dir: Path, dry_run: bool = False) -> int:
    if not images_dir.is_dir():
        print(f"[error] Not a directory: {images_dir}")
        return 1

    migrated = 0
    skipped = 0
    total = 0

    for name in sorted(os.listdir(images_dir)):
        path = images_dir / name
        if not (path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS):
            continue
        total += 1
        json_path = path.with_suffix(".json")
        if not json_path.exists():
            skipped += 1
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[warn] {json_path.name}: {exc}")
            skipped += 1
            continue

        if "status" in data and data["status"] in ("pending", "approved", "hidden"):
            skipped += 1
            continue

        reviewed = _coerce_bool(data.get("reviewed", False))
        data["status"] = "approved" if reviewed else "pending"

        if not dry_run:
            tmp = json_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(json_path)

        status_label = data["status"]
        print(f"[migrated] {json_path.name}: reviewed={reviewed} → status={status_label}")
        migrated += 1

    print(f"\nTotal images: {total}, migrated: {migrated}, skipped: {skipped}")
    if dry_run:
        print("(dry run — no files changed)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate sidecars from reviewed to status enum.")
    parser.add_argument("--images-dir", type=Path, default=Path("Static/images"),
                        help="Path to images directory (default: Static/images)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be migrated without writing files")
    args = parser.parse_args()
    return migrate(args.images_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
