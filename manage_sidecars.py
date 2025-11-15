#!/usr/bin/env python3
"""
Sidecar management CLI

Validates and migrates image sidecar JSON files under Static/images/
to conform to ImageSidecar.schema.json. Safe to run multiple times.

Usage:
  python manage_sidecars.py validate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

from jsonschema import validate as js_validate, ValidationError


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "Static"
IMAGES_DIR = STATIC_DIR / "images"
SCHEMA_PATH = BASE_DIR / "ImageSidecar.schema.json"

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


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _load_schema() -> Dict[str, Any]:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[warn] Unable to load schema {SCHEMA_PATH}: {exc}")
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "default": ""},
                "description": {"type": "string", "default": ""},
                "ai_generated": {"type": "boolean", "default": False},
                "ai_details": {
                    "type": "object",
                    "default": {},
                    "additionalProperties": False,
                    "properties": {
                        "provider": {"type": "string", "default": ""},
                        "model": {"type": "string", "default": ""},
                        "prompt": {"type": "string", "default": ""},
                        "response_id": {"type": "string", "default": ""},
                        "finish_reason": {"type": "string", "default": ""},
                        "created": {"type": "number", "default": 0},
                        "attempted_at": {"type": "number", "default": 0},
                        "status": {"type": "string", "default": ""},
                        "error": {"type": "string", "default": ""},
                        "error_body": {"type": "string", "default": ""},
                        "raw_response": {"type": "object", "default": {}},
                    },
                },
                "reviewed": {"type": "boolean", "default": False},
                "detected_at": {"type": "number", "default": 0},
            },
            "required": [
                "title",
                "description",
                "ai_generated",
                "ai_details",
                "reviewed",
                "detected_at",
            ],
            "additionalProperties": False,
        }


def _apply_schema_defaults(data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    props = schema.get("properties", {})
    for key, spec in props.items():
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
            elif spec.get("type") == "array":
                data[key] = []

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
    return data


def _ensure_sidecar(image_path: Path, schema: Dict[str, Any]) -> None:
    json_path = image_path.with_suffix(".json")
    if json_path.exists():
        return
    now = time.time()
    sidecar: Dict[str, Any] = {}
    for key, spec in schema.get("properties", {}).items():
        if "default" in spec:
            sidecar[key] = spec["default"]
    sidecar.setdefault("title", "")
    sidecar.setdefault("description", "")
    sidecar.setdefault("ai_generated", False)
    if not isinstance(sidecar.get("ai_details"), dict):
        sidecar["ai_details"] = {}
    sidecar.setdefault("reviewed", False)
    sidecar.setdefault("detected_at", now)
    _atomic_write_json(json_path, sidecar)


def validate_and_migrate(images_dir: Path = IMAGES_DIR) -> int:
    schema = _load_schema()
    try:
        names = os.listdir(images_dir)
    except OSError as exc:
        print(f"[error] Unable to list images in {images_dir}: {exc}")
        return 1

    changed = 0
    total = 0
    for name in names:
        path = images_dir / name
        if not (path.is_file() and path.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS):
            continue
        total += 1
        _ensure_sidecar(path, schema)
        json_path = path.with_suffix(".json")
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[warn] {json_path} invalid JSON, recreating")
            data = {}
        before = json.dumps(data, sort_keys=True)
        data = _apply_schema_defaults(data, schema)
        try:
            js_validate(instance=data, schema=schema)
        except ValidationError as exc:
            print(f"[warn] {json_path} failed schema validation: {exc.message}")
            data = _apply_schema_defaults(data, schema)
        after = json.dumps(data, sort_keys=True)
        if before != after:
            _atomic_write_json(json_path, data)
            changed += 1

    print(f"Validated {total} images; updated {changed} sidecars.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate/migrate image sidecar JSON files.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="Validate and migrate sidecars under Static/images/")
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        return validate_and_migrate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
