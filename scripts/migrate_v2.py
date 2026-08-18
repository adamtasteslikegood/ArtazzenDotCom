#!/usr/bin/env python3
"""Migrate image sidecars to v2 schema.

Adds missing v2 fields (caption, tags, artist, copyright, collection, ai_fields),
copies author→artist, and infers ai_fields from ai_generated flag.

Idempotent — safe to re-run. Validates against the updated schema after migration.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

try:
    from jsonschema import validate as js_validate, ValidationError
except ImportError:
    print("jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "ImageSidecar.schema.json"
DEFAULT_IMAGES_DIR = ROOT / "Static" / "images"

V2_DEFAULTS: dict[str, object] = {
    "caption": "",
    "tags": [],
    "artist": "",
    "copyright": "",
    "collection": "",
    "ai_fields": [],
}


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def migrate_sidecar(data: dict) -> tuple[dict, bool]:
    """Apply v2 migration to a sidecar dict. Returns (data, changed)."""
    changed = False

    for key, default in V2_DEFAULTS.items():
        if key not in data:
            data[key] = default if not isinstance(default, list) else list(default)
            changed = True

    if data.get("author") and not data.get("artist"):
        data["artist"] = data["author"]
        changed = True

    if "ai_fields" in data and not data["ai_fields"]:
        if data.get("ai_generated"):
            data["ai_fields"] = ["title", "description"]
            changed = True

    return data, changed


def atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> None:
    images_dir = Path(os.environ.get("IMAGES_DIR", str(DEFAULT_IMAGES_DIR)))
    if not images_dir.is_dir():
        print(f"Images directory not found: {images_dir}", file=sys.stderr)
        sys.exit(1)

    schema = load_schema()
    migrated = 0
    errors = 0
    current = 0

    for name in sorted(os.listdir(images_dir)):
        if not name.lower().endswith(".json"):
            continue
        json_path = images_dir / name

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[error] {name}: {exc}")
            errors += 1
            continue

        data, changed = migrate_sidecar(data)

        try:
            js_validate(instance=data, schema=schema)
        except ValidationError as exc:
            print(f"[warn] {name} failed validation after migration: {exc.message}")
            errors += 1
            continue

        if changed:
            atomic_write(json_path, data)
            migrated += 1
        else:
            current += 1

    total = migrated + current + errors
    print(f"\nMigration complete: {total} sidecars processed")
    print(f"  Migrated: {migrated}")
    print(f"  Already current: {current}")
    print(f"  Errors: {errors}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
