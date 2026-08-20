"""Collections and series curation.

Collections are album-like groups; nesting is expressed through each
registry entry's ``parent`` slug chain, and an image records its
memberships in the sidecar ``collections`` array (authoritative).

Series are ordered groups of related edits owned by exactly one
collection. The series registry is authoritative for membership and
order; sidecar ``series`` arrays are denormalized mirrors kept in sync
by this module (registry wins on drift).

Both registries live under ``IMAGES_DIR/.curation/`` so they survive the
Railway volume and are skipped by every image-listing loop.
"""

import copy
import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from jsonschema import ValidationError
from jsonschema import validate as js_validate

from app import config, sidecars

logger = logging.getLogger(__name__)

CURATION_DIRNAME = ".curation"
COLLECTIONS_FILENAME = "collections.json"
SERIES_FILENAME = "series.json"
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_EMPTY_COLLECTIONS: dict[str, Any] = {"version": 1, "collections": []}
_EMPTY_SERIES: dict[str, Any] = {"version": 1, "series": []}


def slugify(value: str) -> str:
    """Turn an arbitrary label into a registry slug."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "untitled"


def _curation_dir() -> Path:
    return config.IMAGES_DIR / CURATION_DIRNAME


def _registry_path(filename: str) -> Path:
    return _curation_dir() / filename


def _load_registry(filename: str, empty: dict[str, Any], key: str) -> dict[str, Any]:
    path = _registry_path(filename)
    if not path.exists():
        return copy.deepcopy(empty)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Unable to load registry %s: %s", path, exc)
        return copy.deepcopy(empty)
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        logger.warning("Registry %s has an unexpected shape; ignoring", path)
        return copy.deepcopy(empty)
    return data


def _save_registry(filename: str, data: dict[str, Any]) -> None:
    _curation_dir().mkdir(parents=True, exist_ok=True)
    sidecars._atomic_write_json(_registry_path(filename), data)


def load_collections() -> dict[str, Any]:
    return _load_registry(COLLECTIONS_FILENAME, _EMPTY_COLLECTIONS, "collections")


def load_series() -> dict[str, Any]:
    return _load_registry(SERIES_FILENAME, _EMPTY_SERIES, "series")


def save_collections(data: dict[str, Any]) -> None:
    _save_registry(COLLECTIONS_FILENAME, data)


def save_series(data: dict[str, Any]) -> None:
    _save_registry(SERIES_FILENAME, data)


def ensure_registries() -> None:
    """Create empty registry files if they do not exist yet."""
    if not _registry_path(COLLECTIONS_FILENAME).exists():
        save_collections(copy.deepcopy(_EMPTY_COLLECTIONS))
    if not _registry_path(SERIES_FILENAME).exists():
        save_series(copy.deepcopy(_EMPTY_SERIES))


# --- Lookups ---------------------------------------------------------------


def _by_id(registry: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    return {
        entry["id"]: entry
        for entry in registry.get(key, [])
        if isinstance(entry, dict) and entry.get("id")
    }


def get_collection(slug: str) -> dict[str, Any] | None:
    return _by_id(load_collections(), "collections").get(slug)


def _sorted_collections(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda c: (c.get("order", 0), c.get("title", "")))


def top_level_collections() -> list[dict[str, Any]]:
    reg = load_collections()
    return _sorted_collections(
        [c for c in reg.get("collections", []) if not c.get("parent")]
    )


def children_of(slug: str) -> list[dict[str, Any]]:
    reg = load_collections()
    return _sorted_collections(
        [c for c in reg.get("collections", []) if c.get("parent") == slug]
    )


def breadcrumb(slug: str) -> list[dict[str, Any]]:
    """Return the parent chain root -> ... -> slug (cycle-safe)."""
    by_slug = _by_id(load_collections(), "collections")
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = by_slug.get(slug)
    while current and current["id"] not in seen:
        seen.add(current["id"])
        chain.append(current)
        current = by_slug.get(current.get("parent", ""))
    return list(reversed(chain))


def series_in_collection(slug: str) -> list[dict[str, Any]]:
    reg = load_series()
    return [s for s in reg.get("series", []) if s.get("collection") == slug]


def series_for_image(filename: str) -> list[dict[str, Any]]:
    reg = load_series()
    return [s for s in reg.get("series", []) if filename in (s.get("images") or [])]


# --- Sidecar helpers -------------------------------------------------------


def _iter_image_sidecars():
    """Yield (image_path, sidecar_path, raw_sidecar_dict) for every image."""
    try:
        names = os.listdir(config.IMAGES_DIR)
    except OSError as exc:
        logger.error("Unable to list images for curation: %s", exc)
        return
    for name in sorted(names):
        image_path = config.IMAGES_DIR / name
        if not (image_path.is_file() and sidecars._allowed_image(name)):
            continue
        json_path = image_path.with_suffix(".json")
        data: dict[str, Any] = {}
        if json_path.exists():
            try:
                loaded = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Unable to read sidecar %s: %s", json_path, exc)
                continue
        yield image_path, json_path, data


def _approved_metadata(filename: str) -> dict[str, Any] | None:
    """Return display metadata (with url/name) for an approved image, else None."""
    image_path = config.IMAGES_DIR / filename
    if not image_path.is_file():
        return None
    meta = sidecars._load_metadata(image_path)
    if meta.get("status", "pending") != "approved":
        return None
    meta.update({"url": f"{config.IMAGES_URL_PREFIX}/{filename}", "name": filename})
    return meta


def collection_members(slug: str) -> list[dict[str, Any]]:
    """Approved direct members of a collection, sorted by filename."""
    members = []
    for image_path, _json_path, data in _iter_image_sidecars():
        if slug in (data.get("collections") or []):
            meta = _approved_metadata(image_path.name)
            if meta:
                members.append(meta)
    return members


def collection_cover_url(entry: dict[str, Any]) -> str:
    """Resolve a collection's cover image URL ('' when it has no artwork)."""
    cover = (entry.get("cover") or "").strip()
    if cover and (config.IMAGES_DIR / cover).is_file():
        return f"{config.IMAGES_URL_PREFIX}/{cover}"
    members = collection_members(entry["id"])
    if members:
        return members[0]["url"]
    for series in series_in_collection(entry["id"]):
        for filename in series.get("images") or []:
            meta = _approved_metadata(filename)
            if meta:
                return meta["url"]
    return ""


def collection_view(slug: str) -> dict[str, Any] | None:
    """Assemble everything a collection page needs, applying the dedup rule:
    an image that is both a direct member and in one of this collection's
    series renders only inside the series strip."""
    entry = get_collection(slug)
    if entry is None:
        return None

    series_list = []
    series_member_names: set[str] = set()
    for series in series_in_collection(slug):
        resolved = []
        for filename in series.get("images") or []:
            meta = _approved_metadata(filename)
            if meta:
                resolved.append(meta)
                series_member_names.add(filename)
        series_list.append({**series, "artworks": resolved})

    direct = collection_members(slug)
    standalone = [m for m in direct if m["name"] not in series_member_names]

    children = [
        {**child, "cover_url": collection_cover_url(child)}
        for child in children_of(slug)
    ]

    return {
        "collection": entry,
        "breadcrumb": breadcrumb(slug),
        "children": children,
        "series": series_list,
        "artworks": standalone,
    }


def membership_counts() -> dict[str, int]:
    """Count sidecar memberships (any status) per collection slug."""
    counts: dict[str, int] = {}
    for _image_path, _json_path, data in _iter_image_sidecars():
        for slug in data.get("collections") or []:
            counts[slug] = counts.get(slug, 0) + 1
    return counts


def collections_for_image(filename: str) -> list[dict[str, Any]]:
    """Collections an image belongs to (registry entries, sorted)."""
    image_path = config.IMAGES_DIR / filename
    if not image_path.is_file():
        return []
    meta = sidecars._load_metadata(image_path)
    by_slug = _by_id(load_collections(), "collections")
    entries = [by_slug[s] for s in (meta.get("collections") or []) if s in by_slug]
    return _sorted_collections(entries)


# --- Mutations (single writer; callers hold no locks) ----------------------


def sync_series_mirrors() -> int:
    """Re-sync every sidecar's ``series`` array from the registry.

    The registry is authoritative; drifted sidecars are repaired.
    Returns the number of sidecars updated.
    """
    reg = load_series()
    membership: dict[str, list[str]] = {}
    for series in reg.get("series", []):
        for filename in series.get("images") or []:
            membership.setdefault(filename, []).append(series["id"])

    changed = 0
    for image_path, json_path, data in _iter_image_sidecars():
        if not json_path.exists():
            continue
        expected = sorted(membership.get(image_path.name, []))
        if data.get("series", []) != expected:
            data["series"] = expected
            sidecars._write_sidecar(image_path, data)
            changed += 1
    return changed


def migrate_legacy_collections() -> int:
    """v2 -> v3: convert non-empty ``collection`` strings into ``collections``
    slugs plus registry entries. Idempotent; the deprecated string is kept.
    Returns the number of sidecars migrated."""
    ensure_registries()
    reg = load_collections()
    by_slug = _by_id(reg, "collections")
    migrated = 0
    registry_changed = False

    for image_path, _json_path, data in _iter_image_sidecars():
        legacy = str(data.get("collection") or "").strip()
        if not legacy or data.get("collections"):
            continue
        slug = slugify(legacy)
        data["collections"] = [slug]
        if slug not in by_slug:
            entry = {
                "id": slug,
                "title": legacy,  # first-seen original title wins
                "description": "",
                "parent": "",
                "cover": "",
                "order": len(reg["collections"]),
            }
            reg["collections"].append(entry)
            by_slug[slug] = entry
            registry_changed = True
        sidecars._write_sidecar(image_path, data)
        migrated += 1

    if registry_changed:
        save_collections(reg)
    return migrated


def upsert_collection(entry: dict[str, Any]) -> dict[str, Any]:
    """Create or update a collection registry entry."""
    slug = str(entry.get("id") or "").strip() or slugify(str(entry.get("title", "")))
    if not SLUG_RE.match(slug):
        raise ValueError(f"Invalid collection id: {slug!r}")
    parent = str(entry.get("parent") or "").strip()
    reg = load_collections()
    by_slug = _by_id(reg, "collections")
    if parent:
        if parent not in by_slug:
            raise ValueError(f"Unknown parent collection: {parent!r}")
        if parent == slug:
            raise ValueError("A collection cannot be its own parent")
        # Reject cycles: walk up from the proposed parent.
        current, seen = parent, set()
        while current and current not in seen:
            if current == slug:
                raise ValueError("Collection nesting would create a cycle")
            seen.add(current)
            current = by_slug.get(current, {}).get("parent", "")

    existing = by_slug.get(slug)
    clean = {
        "id": slug,
        "title": str(entry.get("title") or (existing or {}).get("title") or slug),
        "description": str(
            entry.get("description", (existing or {}).get("description", ""))
        ),
        "parent": parent,
        "cover": str(entry.get("cover", (existing or {}).get("cover", ""))),
        "order": int(
            entry.get("order", (existing or {}).get("order", len(reg["collections"])))
        ),
    }
    if existing:
        reg["collections"] = [
            clean if c.get("id") == slug else c for c in reg["collections"]
        ]
    else:
        reg["collections"].append(clean)
    save_collections(reg)
    return clean


def delete_collection(slug: str) -> None:
    """Delete a collection: children re-parent to its parent; sidecar
    memberships are removed. Refuses when it owns series and has no parent
    to hand them to (delete or re-own the series first)."""
    reg = load_collections()
    by_slug = _by_id(reg, "collections")
    entry = by_slug.get(slug)
    if entry is None:
        raise KeyError(slug)
    parent = entry.get("parent", "")

    owned = series_in_collection(slug)
    if owned and not parent:
        titles = ", ".join(s["id"] for s in owned)
        raise ValueError(
            f"Collection {slug!r} owns series ({titles}) and has no parent; "
            "re-own or delete those series first"
        )

    reg["collections"] = [c for c in reg["collections"] if c.get("id") != slug]
    for c in reg["collections"]:
        if c.get("parent") == slug:
            c["parent"] = parent
    save_collections(reg)

    if owned:
        series_reg = load_series()
        for s in series_reg.get("series", []):
            if s.get("collection") == slug:
                s["collection"] = parent
        save_series(series_reg)

    for image_path, json_path, data in _iter_image_sidecars():
        memberships = data.get("collections") or []
        if slug in memberships:
            data["collections"] = [m for m in memberships if m != slug]
            sidecars._write_sidecar(image_path, data)


def upsert_series(entry: dict[str, Any]) -> dict[str, Any]:
    """Create or update a series registry entry; re-syncs sidecar mirrors."""
    slug = str(entry.get("id") or "").strip() or slugify(str(entry.get("title", "")))
    if not SLUG_RE.match(slug):
        raise ValueError(f"Invalid series id: {slug!r}")
    reg = load_series()
    by_slug = _by_id(reg, "series")
    existing = by_slug.get(slug)

    collection = str(
        entry.get("collection") or (existing or {}).get("collection") or ""
    ).strip()
    if not collection or get_collection(collection) is None:
        raise ValueError(f"Series {slug!r} requires an existing owning collection")

    images_in = entry.get("images", (existing or {}).get("images", []))
    if not isinstance(images_in, list):
        raise TypeError("Series images must be a list of filenames")
    images = []
    for filename in images_in:
        name = sidecars._sanitize_filename(str(filename))
        if name and (config.IMAGES_DIR / name).is_file():
            images.append(name)
        else:
            logger.warning("Series %s: dropping missing image %r", slug, filename)

    clean = {
        "id": slug,
        "title": str(entry.get("title") or (existing or {}).get("title") or slug),
        "description": str(
            entry.get("description", (existing or {}).get("description", ""))
        ),
        "collection": collection,
        "images": images,
    }
    if existing:
        reg["series"] = [clean if s.get("id") == slug else s for s in reg["series"]]
    else:
        reg["series"].append(clean)
    save_series(reg)
    sync_series_mirrors()
    return clean


def delete_series(slug: str) -> None:
    reg = load_series()
    if slug not in _by_id(reg, "series"):
        raise KeyError(slug)
    reg["series"] = [s for s in reg["series"] if s.get("id") != slug]
    save_series(reg)
    sync_series_mirrors()


# --- Validation ------------------------------------------------------------


def _load_registry_schema(name: str) -> dict[str, Any] | None:
    path = config.BASE_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Unable to load registry schema %s: %s", path, exc)
        return None


def validate_registries(repair: bool = True) -> dict[str, list[str]]:
    """Validate both registries and referential integrity.

    Returns {"errors": [...], "warnings": [...]}. With repair=True,
    repairable problems (dangling slugs, missing files, mirror drift) are
    fixed in place; errors (schema violations, parent cycles, missing series
    owners) are only reported.
    """
    errors: list[str] = []
    warnings: list[str] = []

    collections_reg = load_collections()
    series_reg = load_series()

    for schema_name, reg in (
        ("CollectionsRegistry.schema.json", collections_reg),
        ("SeriesRegistry.schema.json", series_reg),
    ):
        schema = _load_registry_schema(schema_name)
        if schema:
            try:
                js_validate(instance=reg, schema=schema)
            except ValidationError as exc:
                errors.append(f"{schema_name}: {exc.message}")

    by_slug = _by_id(collections_reg, "collections")

    # Parent integrity + cycle detection
    for entry in collections_reg.get("collections", []):
        parent = entry.get("parent", "")
        if parent and parent not in by_slug:
            warnings.append(
                f"collection {entry.get('id')!r}: unknown parent {parent!r} cleared"
            )
            if repair:
                entry["parent"] = ""
        current, seen = entry.get("id"), set()
        while current:
            if current in seen:
                errors.append(f"collection parent cycle involving {current!r}")
                break
            seen.add(current)
            current = by_slug.get(current, {}).get("parent", "")

    # Series integrity
    for series in series_reg.get("series", []):
        owner = series.get("collection", "")
        if owner not in by_slug:
            errors.append(
                f"series {series.get('id')!r}: owning collection {owner!r} missing"
            )
        kept = []
        for filename in series.get("images") or []:
            if (config.IMAGES_DIR / filename).is_file():
                kept.append(filename)
            else:
                warnings.append(
                    f"series {series.get('id')!r}: missing image {filename!r} dropped"
                )
        if repair and kept != (series.get("images") or []):
            series["images"] = kept

    if repair:
        save_collections(collections_reg)
        save_series(series_reg)

    # Sidecar membership integrity (dangling slugs)
    for image_path, json_path, data in _iter_image_sidecars():
        if not json_path.exists():
            continue
        memberships = data.get("collections") or []
        kept = [m for m in memberships if m in by_slug]
        if kept != memberships:
            dangling = sorted(set(memberships) - set(kept))
            warnings.append(
                f"{image_path.name}: dangling collection slugs {dangling} dropped"
            )
            if repair:
                data["collections"] = kept
                sidecars._write_sidecar(image_path, data)

    if repair:
        repaired = sync_series_mirrors()
        if repaired:
            warnings.append(f"re-synced series mirrors on {repaired} sidecars")

    return {"errors": errors, "warnings": warnings}
