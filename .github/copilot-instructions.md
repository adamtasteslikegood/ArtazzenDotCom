# Copilot Instructions for ArtazzenDotCom

## Project Overview
ArtazzenDotCom is a FastAPI + Jinja2 artwork gallery with an admin dashboard. The entry point is `main.py`. Images are stored in `Static/images/`; each image has a companion JSON sidecar file (same base name, `.json` extension) that holds metadata.

## Key Architecture
- **`main.py`** — all routes, background polling, and business logic. Mount order matters: `StaticFiles` is mounted at `/static` from the `Static/` directory (capital S must be preserved).
- **`templates/`** — Jinja2 templates: `index.html` (gallery), `reviewAddedFiles.html` (admin review), `previewImageText.html` (metadata preview).
- **`Static/images/`** — image files + sidecar `.json` files.
- **`ImageSidecar.schema.json`** — JSON Schema for sidecar files (the authoritative definition). Required fields: `title`, `description`, `ai_generated`, `ai_details`, `reviewed`, `detected_at`.
- **`ai_config.json`** — AI feature flags (`enabled`, `model`, `temperature`, `max_output_tokens`).
- **`manage_sidecars.py`** — CLI to validate/migrate sidecars: `python manage_sidecars.py validate`.

## Coding Standards
- Python ≥ 3.10, PEP 8, type hints throughout.
- Logging via `logging.getLogger(__name__)` — no `print()` in production paths.
- `snake_case` for functions/variables; `PascalCase` for classes.
- Never rename or relocate the `Static/` directory — FastAPI mount depends on the exact capitalisation.
- Sidecar JSON must conform to `ImageSidecar.schema.json`; always validate after writing.

## Environment & Dependencies
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload          # dev server → http://127.0.0.1:8000/
```
Key env vars (optional):
- `MY_OPENAI_API_KEY` — OpenAI API key for AI metadata generation.
- `OPENAI_IMAGE_METADATA_MODEL` — overrides the model in `ai_config.json`.
- `OPENAI_TIMEOUT_SECONDS` — float, default `30`.

## Testing & Validation
No automated test suite yet. Validate changes manually:
```bash
python manage_sidecars.py validate          # sidecar schema check
curl http://127.0.0.1:8000/admin/api/new-files
curl http://127.0.0.1:8000/admin/config
curl -F "files=@/path/to/image.jpg" http://127.0.0.1:8000/admin/upload
```
When adding tests use `pytest` + `httpx` in `tests/test_*.py`.
Regression-check: gallery view (`/`), admin dashboard (`/admin`), upload flow, and metadata persistence.

## Common Pitfalls
- The background watcher runs as an asyncio task, not a thread; use the module-level lock when writing shared sidecar/config state rather than for the poll loop itself.
- Image uploads are validated against `ALLOWED_IMAGE_EXTENSIONS`; unsupported formats are rejected.
- Sidecar writes must be atomic (`write temp → rename`) to avoid corruption during polling.
- Do not introduce extra keys beyond `ImageSidecar.schema.json`, and do not drop required keys from sidecar JSON.
