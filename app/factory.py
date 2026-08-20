"""Application factory: lifespan, mounts, middleware, routers."""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config, sidecars, watcher
from app.routes_admin import router as admin_router
from app.routes_public import router as public_router
from app.security import _SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    config.runtime_ai_config = config._load_ai_config()
    sidecars._validate_and_migrate_sidecars()
    app.state.pending_images = watcher.new_files_detected()
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
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
    if config._USING_VOLUME:
        app.mount("/images", StaticFiles(directory=config.IMAGES_DIR), name="images")
    app.add_middleware(_SecurityHeadersMiddleware)
    app.include_router(admin_router)
    app.include_router(public_router)
    return app
