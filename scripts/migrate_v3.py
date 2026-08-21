#!/usr/bin/env python3
"""Schema v3 migration: collections arrays + curation registries.

Converts non-empty v2 ``collection`` strings into v3 ``collections`` slug
arrays with matching registry entries, creates empty registries when absent,
re-syncs sidecar ``series`` mirrors, and validates referential integrity.
Idempotent — safe to re-run. Respects the IMAGES_DIR environment variable.

Usage:
  python scripts/migrate_v3.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, curation


def main() -> int:
    print(f"Images directory: {config.IMAGES_DIR}")
    curation.ensure_registries()
    migrated = curation.migrate_legacy_collections()
    mirrored = curation.sync_series_mirrors()
    report = curation.validate_registries(repair=True)

    print(f"Migrated {migrated} sidecars (collection string -> collections array).")
    print(f"Re-synced series mirrors on {mirrored} sidecars.")
    for warning in report["warnings"]:
        print(f"[warn] {warning}")
    for error in report["errors"]:
        print(f"[error] {error}")
    if report["errors"]:
        return 1
    print("Registries valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
