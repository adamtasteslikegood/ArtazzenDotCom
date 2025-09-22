# Repository Guidelines

## Project Structure & Module Organization
- App entrypoint: `main.py` (FastAPI + Jinja2).
- Templates: `templates/` (`index.html`, `reviewAddedFiles.html`, `previewImageText.html`).
- Static assets: `Static/` (note capital S), with `Static/images/` and `Static/css/` mounted at `/static`.
- Sidecar schema: `ImageSidecar.schema.json` defines required fields on `*.json` files next to images.
- Dependencies: `requirements.txt`.
- HTTP request samples: `test_main.http` (use with IDE REST client or `curl`).

## Build, Test, and Development Commands
- Create venv: `python -m venv .venv` and activate (`source .venv/bin/activate`).
- Install deps: `pip install -r requirements.txt`.
- Run dev server: `uvicorn main:app --reload` then open `http://127.0.0.1:8000/`.
- Sample API checks:
  - List pending: `curl http://127.0.0.1:8000/admin/api/new-files`.
  - Upload: `curl -F "files=@/path/to/image.jpg" http://127.0.0.1:8000/admin/upload`.

## Coding Style & Naming Conventions
- Python: PEP 8, 4‑space indents, type hints required. Functions `snake_case`, classes `PascalCase`.
- Logging: use the module logger (`logger = logging.getLogger(__name__)`); avoid `print` in app code.
- Paths: preserve `Static/` capitalization; generate URLs via `/static` (e.g., `/static/images/foo.jpg`).
- Sidecars: keep only schema fields (`title`, `description`, `reviewed`, `detected_at`). Avoid ad‑hoc keys.
- Templates: keep filenames consistent with existing ones (e.g., `reviewAddedFiles.html`).

## Testing Guidelines
- No formal test suite yet. Validate via browser, `test_main.http`, and `curl` examples above.
- When adding tests, prefer `pytest` + `httpx` client. Name files `tests/test_*.py` and keep tests fast and isolated.
- Manual acceptance: verify gallery (`/`), admin dashboard (`/admin`), upload, review, and metadata save flows.
- On server start, sidecars are validated/migrated to `ImageSidecar.schema.json`.

## Commit & Pull Request Guidelines
- Commits: imperative, concise, and scoped (e.g., "Add admin metadata review"). Group related changes.
- PRs must include:
  - What/why summary and screenshots for UI changes.
  - Repro/verification steps and impacted routes.
  - Notes on data/asset changes under `Static/images/`.

## Architecture & Tips
- FastAPI app with a background poller (`_watch_image_directory`) derives pending items from sidecars (`reviewed: false`).
- Sidecar JSON is the source of truth. Schema enforced via `ImageSidecar.schema.json` at startup.
- Writes use atomic replace to reduce corruption risk under multi‑worker servers.
- Keep request handlers non‑blocking; use `async` where appropriate and avoid long I/O on the main path.
