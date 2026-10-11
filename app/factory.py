"""Application factory: lifespan, mounts, middleware, routers."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app import config, curation, media, sidecars, watcher
from app.routes_admin import router as admin_router
from app.routes_public import router as public_router
from app.security import _SecurityHeadersMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    config.runtime_ai_config = config._load_ai_config()
    sidecars._validate_and_migrate_sidecars()
    curation.ensure_registries()
    curation.migrate_legacy_collections()
    curation.sync_series_mirrors()
    if not media.purge_configured():
        logger.warning(
            "CLOUDFLARE_API_TOKEN or CLOUDFLARE_ZONE_ID is unset: images that "
            "stop being public are not purged, so edge copies are capped at 1 day"
        )
    # Start empty: the watcher task's first cycle runs immediately (off the
    # event loop) and populates the cache; scanning inline here blocked
    # startup — and thus deploy readiness — for a full scan plus any
    # OpenAI calls. Dependency-driven routes use get_pending_files (a fresh
    # scan); the only direct reader is the regenerate preview path, which
    # deliberately serves this possibly-stale cache instead of triggering a
    # scan that could persist other sidecars.
    app.state.pending_images = []
    app.state.watcher_task = asyncio.create_task(watcher._watch_image_directory(app))
    yield
    # Shutdown
    watcher_task = getattr(app.state, "watcher_task", None)
    if watcher_task:
        watcher_task.cancel()
        with suppress(asyncio.CancelledError):
            await watcher_task


def create_app() -> FastAPI:
    app = FastAPI(title="Artwork Gallery", lifespan=lifespan)
    config.templates.env.globals["static_url"] = media.static_url
    app.mount("/static", media.VersionedStaticFiles(), name="static")
    app.mount(config.IMAGES_URL_PREFIX, media.PublicImageFiles(), name="images")
    app.add_middleware(_SecurityHeadersMiddleware)
    app.include_router(admin_router)
    app.include_router(public_router)
    return app
