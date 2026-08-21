"""Uvicorn entrypoint and compatibility shim.

The application now lives in the ``app/`` package (config, sidecars,
ai_metadata, watcher, security, routes_admin, routes_public, factory).
This module re-exports the public surface so ``uvicorn main:app`` and
``import main`` keep working. When monkeypatching in tests, patch the
defining module (e.g. ``app.config.IMAGES_DIR``,
``app.ai_metadata._populate_missing_metadata``) — re-exported names here
are snapshots, not live bindings.
"""

import httpx  # noqa: F401  (legacy patch target: gallery_app.httpx)

from app import ai_metadata, config, curation, security, sidecars, watcher  # noqa: F401
from app.ai_metadata import (  # noqa: F401
    _build_openai_prompt,
    _get_openai_api_key,
    _populate_missing_metadata,
    _prepare_image_for_openai,
    _request_openai_metadata,
    _strip_json_fences,
    _unwrap_nested_json,
)
from app.config import (  # noqa: F401
    ALLOWED_IMAGE_EXTENSIONS,
    BASE_DIR,
    CONFIG_PATH,
    GALLERY_TITLE,
    IMAGES_DIR,
    IMAGES_URL_PREFIX,
    IMPORT_ROOT,
    MAX_UPLOAD_SIZE_BYTES,
    SCHEMA_PATH,
    STATIC_DIR,
    TEMPLATES_DIR,
    _default_ai_config_from_env,
    _get_ai_config,
    _load_ai_config,
    _sanitize_ai_config,
    _save_ai_config,
    templates,
)
from app.factory import create_app, lifespan  # noqa: F401
from app.routes_admin import (  # noqa: F401
    _select_import_files,
    admin_home,
    api_new_files,
    get_admin_config,
    import_from_path,
    list_collections,
    list_series,
    mutate_collections,
    mutate_series,
    preview_image_metadata,
    regenerate_ai_metadata,
    reset_admin_config,
    review_added_files,
    soft_delete_image,
    unapprove_image,
    update_admin_config,
    update_image_metadata,
    upload_images,
)
from app.routes_public import (  # noqa: F401
    artwork_detail,
    collection_detail,
    collections_index,
    read_root,
)
from app.security import (  # noqa: F401
    _http_basic,
    _SecurityHeadersMiddleware,
    _verify_admin,
)
from app.sidecars import (  # noqa: F401
    _allowed_image,
    _apply_schema_defaults,
    _atomic_write_json,
    _coerce_bool,
    _ensure_sidecar,
    _extract_exif_metadata,
    _load_metadata,
    _load_schema,
    _resolve_image_path,
    _sanitize_filename,
    _set_status_sidecar,
    _validate_and_migrate_sidecars,
    _write_sidecar,
    get_artwork_files,
)
from app.watcher import (  # noqa: F401
    _refresh_pending_files,
    _watch_image_directory,
    get_pending_files,
    new_files_detected,
    refresh_pending_files,
)

app = create_app()
