"""Upscaler service: import copies, then prepare, confirm and run jobs.

Run: ``uvicorn upscaler.app:create_app --factory`` from ``services/upscaler``.

Importing never processes anything. A job starts only after Prepare (which
copies the import to ``staging/`` and analyses the copy) and an explicit
Confirm.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette import status

from upscaler.auth import SecurityHeadersMiddleware, verify_admin
from upscaler.config import Settings
from upscaler.intake import IntakeError, get_import, import_bytes, list_imports
from upscaler.jobs import KINDS, SCALES, JobError, JobRunner, get_job, list_jobs
from upscaler.jobs import prepare as prepare_job
from upscaler.replicate import ReplicateClient
from upscaler.sources import (
    GalleryClient,
    GalleryError,
    read_limited,
    select_path_files,
)
from upscaler.storage import Storage

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
# A directory import stops here so a wrong path cannot copy a whole disk.
MAX_PATH_FILES = 50


def create_app(
    settings: Settings | None = None,
    storage: Storage | None = None,
    gallery: GalleryClient | None = None,
    replicate: ReplicateClient | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    storage = storage or Storage.from_settings(settings)
    runner = JobRunner(storage, settings, replicate or ReplicateClient(settings))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            resumed = await runner.resume()
            if resumed:
                logger.info("Resumed jobs: %s", ", ".join(resumed))
        except Exception:
            logger.exception("Could not resume jobs")
        yield

    app = FastAPI(
        title="Artazzen Upscaler", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.state.settings = settings
    app.state.storage = storage
    app.state.gallery = gallery or GalleryClient(settings)
    app.state.runner = runner
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    templates.env.globals["gallery_admin_url"] = settings.gallery_admin_url

    def _storage(request: Request) -> Storage:
        return request.app.state.storage

    def _gallery(request: Request) -> GalleryClient:
        return request.app.state.gallery

    def _import(
        storage: Storage, data: bytes, filename: str, source: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            record, created = import_bytes(storage, data, filename, source, settings)
        except IntakeError as exc:
            return {"name": filename, "ok": False, "message": str(exc)}
        return {
            "name": filename,
            "ok": True,
            "created": created,
            "id": record["id"],
            "message": "imported" if created else "already in the library",
        }

    def _render_import(
        request: Request, results: list[dict[str, Any]] | None = None, tab: str = ""
    ) -> HTMLResponse:
        gallery = _gallery(request)
        images: list[dict[str, Any]] = []
        gallery_error = ""
        # The gallery's new-files endpoint runs its pending scan, which can
        # write sidecars and call OpenAI. List it only on a plain page load,
        # not again after every import.
        if results is None:
            if gallery.configured:
                try:
                    images = gallery.list_images()
                except GalleryError as exc:
                    gallery_error = str(exc)
            else:
                gallery_error = (
                    "GALLERY_URL is not set, so the gallery cannot be listed."
                )
        active_tab = tab if tab in {"gallery", "upload", "path"} else "gallery"
        return templates.TemplateResponse(
            request,
            "import.html",
            {
                "images": images,
                "gallery_listed": results is None,
                "gallery_error": gallery_error,
                "results": results,
                "tab": active_tab,
                "max_upload_mb": settings.max_upload_mb,
                "import_root": settings.import_root,
            },
        )

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/", include_in_schema=False, dependencies=[Depends(verify_admin)])
    def root() -> RedirectResponse:
        return RedirectResponse("/library", status_code=status.HTTP_303_SEE_OTHER)

    @app.get(
        "/import", response_class=HTMLResponse, dependencies=[Depends(verify_admin)]
    )
    def import_page(request: Request, tab: str = "gallery") -> HTMLResponse:
        return _render_import(request, tab=tab)

    @app.get("/gallery/thumb/{name}", dependencies=[Depends(verify_admin)])
    def gallery_thumb(name: str, request: Request) -> Response:
        try:
            data, content_type = _gallery(request).fetch(name, thumb=True)
        except (GalleryError, IntakeError):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return Response(
            data,
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=300"},
        )

    @app.post(
        "/import/gallery",
        response_class=HTMLResponse,
        dependencies=[Depends(verify_admin)],
    )
    def import_from_gallery(
        request: Request, names: list[str] = Form(default=[])
    ) -> HTMLResponse:
        results = []
        for name in names:
            try:
                data, _ = _gallery(request).fetch(name)
            except (GalleryError, IntakeError) as exc:
                results.append({"name": name, "ok": False, "message": str(exc)})
                continue
            results.append(
                _import(
                    _storage(request), data, name, {"kind": "gallery", "name": name}
                )
            )
        if not results:
            results.append({"name": "", "ok": False, "message": "No images selected"})
        return _render_import(request, results, "gallery")

    @app.post(
        "/import/upload",
        response_class=HTMLResponse,
        dependencies=[Depends(verify_admin)],
    )
    def import_upload(
        request: Request, files: list[UploadFile] = File(default=[])
    ) -> HTMLResponse:
        results = []
        for upload in files:
            filename = upload.filename or "upload"
            try:
                data = read_limited(upload.file, settings.max_upload_bytes, filename)
            except IntakeError as exc:
                results.append({"name": filename, "ok": False, "message": str(exc)})
                continue
            results.append(
                _import(
                    _storage(request),
                    data,
                    filename,
                    {"kind": "upload", "name": filename},
                )
            )
        if not results:
            results.append({"name": "", "ok": False, "message": "No files chosen"})
        return _render_import(request, results, "upload")

    @app.post(
        "/import/path",
        response_class=HTMLResponse,
        dependencies=[Depends(verify_admin)],
    )
    def import_path(request: Request, path: str = Form(...)) -> HTMLResponse:
        try:
            files = select_path_files(path, settings.import_root)
        except IntakeError as exc:
            return _render_import(
                request, [{"name": path, "ok": False, "message": str(exc)}], "path"
            )
        results = []
        if len(files) > MAX_PATH_FILES:
            results.append(
                {
                    "name": path,
                    "ok": False,
                    "message": f"{len(files)} files match; only the first "
                    f"{MAX_PATH_FILES} were imported",
                }
            )
            files = files[:MAX_PATH_FILES]
        root = settings.import_root.resolve()
        for file_path in files:
            relative = file_path.relative_to(root).as_posix()
            try:
                with file_path.open("rb") as handle:
                    data = read_limited(handle, settings.max_upload_bytes, relative)
            except IntakeError as exc:
                results.append({"name": relative, "ok": False, "message": str(exc)})
                continue
            results.append(
                _import(
                    _storage(request),
                    data,
                    relative,
                    {"kind": "path", "name": relative},
                )
            )
        return _render_import(request, results, "path")

    @app.get(
        "/library", response_class=HTMLResponse, dependencies=[Depends(verify_admin)]
    )
    def library(request: Request, error: str = "") -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "library.html",
            {
                "imports": list_imports(_storage(request)),
                "kinds": KINDS,
                "scales": SCALES,
                "error": error[:300],
            },
        )

    @app.get("/api/imports", dependencies=[Depends(verify_admin)])
    def api_imports(request: Request) -> JSONResponse:
        return JSONResponse({"imports": list_imports(_storage(request))})

    @app.get("/imports/{import_id}/file", dependencies=[Depends(verify_admin)])
    def import_file(import_id: str, request: Request) -> RedirectResponse:
        """Redirect to a short-lived presigned URL for the stored copy."""
        storage = _storage(request)
        record = get_import(storage, import_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return RedirectResponse(
            storage.presign_get(record["object"], expires=600),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    # --- jobs ---------------------------------------------------------------

    def _job_or_404(storage: Storage, job_id: str) -> dict[str, Any]:
        job = get_job(storage, job_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return job

    def _see(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/jobs/prepare", dependencies=[Depends(verify_admin)])
    def prepare(
        request: Request,
        import_id: str = Form(...),
        kind: str = Form(...),
        scale: int = Form(4),
    ) -> RedirectResponse:
        try:
            job = prepare_job(_storage(request), settings, import_id, kind, scale)
        except JobError as exc:
            return _see(f"/library?error={quote(str(exc))}")
        return _see(f"/jobs/{job['id']}")

    @app.get("/jobs", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
    def jobs_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "jobs.html", {"jobs": list_jobs(_storage(request)), "kinds": KINDS}
        )

    @app.get(
        "/jobs/{job_id}",
        response_class=HTMLResponse,
        dependencies=[Depends(verify_admin)],
    )
    def job_page(job_id: str, request: Request, error: str = "") -> HTMLResponse:
        job = _job_or_404(_storage(request), job_id)
        return templates.TemplateResponse(
            request,
            "job.html",
            {"job": job, "kinds": KINDS, "error": error[:300]},
        )

    @app.post("/jobs/{job_id}/confirm", dependencies=[Depends(verify_admin)])
    async def confirm(job_id: str, request: Request) -> RedirectResponse:
        storage = _storage(request)
        job = await asyncio.to_thread(_job_or_404, storage, job_id)
        try:
            await runner.confirm(job)
        except JobError as exc:
            return _see(f"/jobs/{job_id}?error={quote(str(exc))}")
        return _see(f"/jobs/{job_id}")

    @app.post("/jobs/{job_id}/cancel", dependencies=[Depends(verify_admin)])
    async def cancel(job_id: str, request: Request) -> RedirectResponse:
        storage = _storage(request)
        job = await asyncio.to_thread(_job_or_404, storage, job_id)
        was_staged = job["state"] == "staged"
        try:
            await runner.cancel(job)
        except JobError as exc:
            return _see(f"/jobs/{job_id}?error={quote(str(exc))}")
        return _see("/library" if was_staged else f"/jobs/{job_id}")

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(verify_admin)])
    def api_job(job_id: str, request: Request) -> JSONResponse:
        return JSONResponse(_job_or_404(_storage(request), job_id))

    # Files a job page may link to: results, and the tile proof while staged.
    _JOB_FILES = {
        "master": ("results", "master"),
        "proof": ("results", "proof"),
        "tile-proof": ("staging", "proof.jpg"),
    }

    @app.get("/jobs/{job_id}/files/{name}", dependencies=[Depends(verify_admin)])
    def job_file(job_id: str, name: str, request: Request) -> RedirectResponse:
        storage = _storage(request)
        job = _job_or_404(storage, job_id)
        if name not in _JOB_FILES:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        where, key = _JOB_FILES[name]
        if where == "results":
            object_name = (job.get("results") or {}).get(key)
        else:
            object_name = f"staging/{job_id}/{key}" if job.get("tile") else None
        if not object_name:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return RedirectResponse(
            storage.presign_get(object_name, expires=600),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    return app
