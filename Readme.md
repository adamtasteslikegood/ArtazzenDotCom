# Artwork Gallery Web Application

ArtazzenDotCom is a FastAPI + Jinja2 project for curating artwork with rich metadata. Images live on disk with JSON “sidecars” that describe each piece, while the app provides both a public gallery and an admin workflow for uploads, reviews, and optional AI assistance.

## Highlights
- Responsive gallery view backed by `templates/index.html`.
- Admin dashboard (`/admin`) for uploads, metadata review, and AI configuration.
- Per-image JSON sidecars validated against `ImageSidecar.schema.json`; no centralized manifest.
- Startup background watcher keeps the pending review queue fresh.
- Optional OpenAI-powered title and description generation.

## Requirements
- Python 3.10 or newer
- `pip` for dependency management
- (Optional) OpenAI API key for AI metadata suggestions

## Quick Start
```bash
git clone https://github.com/adamtasteslikegood/ArtazzenDotCom.git
cd ArtazzenDotCom
python -m venv .venv
source .venv/bin/activate            # use .\.venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn main:app --reload
```
Then open `http://127.0.0.1:8000/` for the gallery or `http://127.0.0.1:8000/admin` for the dashboard.

## Project Layout
```
.
├── main.py                     # FastAPI application entry point
├── Static/                     # Static assets served at /static
│   ├── images/                 # Artwork images and their *.json sidecars
│   └── css/                    # Stylesheets
├── templates/                  # Jinja2 templates (gallery, admin flows)
├── ai_config.json              # Persisted runtime AI settings
├── ImageSidecar.schema.json    # Expected schema for image sidecars
├── manage_sidecars.py          # CLI for validating/migrating sidecars
└── test_main.http              # Handy HTTP snippets for manual testing
```

## Metadata Workflow
1. Drop images into `Static/images/`. Supported formats include JPG, PNG, GIF, WEBP, SVG, BMP, and TIFF.
2. Create a matching JSON sidecar (same filename, `.json` extension) with the schema fields:
   - `title` (string)
   - `description` (string)
   - `reviewed` (boolean)
   - `detected_at` (unix timestamp)
3. Missing sidecars are created automatically when the watcher detects new files.
4. The admin review page lets you edit metadata, mark items as reviewed, and save changes atomically.

## AI Metadata Support
Enable automatic suggestions with environment variables:
```bash
export MY_OPENAI_API_KEY=sk-...          # or legacy My_OpenAI_APIKey
export OPENAI_IMAGE_METADATA_MODEL=gpt-4o-mini   # optional override
```
Runtime settings persist in `ai_config.json` and are also editable from the admin UI under **AI Metadata Settings**. The app triggers AI generation when new assets arrive or when you request suggestions during review.

## Useful Commands
- Run with reload: `uvicorn main:app --reload`
- Validate sidecars: `python manage_sidecars.py validate`
- List pending reviews: `curl http://127.0.0.1:8000/admin/api/new-files`
- Upload via API: `curl -F "files=@/path/to/image.jpg" http://127.0.0.1:8000/admin/upload`
- Inspect AI config: `curl http://127.0.0.1:8000/admin/config`
- Update AI config:
  ```bash
  curl -X POST -H 'Content-Type: application/json' \
    -d '{"ai":{"enabled":true,"model":"gpt-5-mini","temperature":0.6,"max_output_tokens":600}}' \
    http://127.0.0.1:8000/admin/config
  ```

## Development Notes
- Follow PEP 8 with 4-space indentation and type hints.
- Use the built-in logger (`logging.getLogger(__name__)`) instead of `print`.
- Keep handlers asynchronous and avoid blocking I/O on request paths.
- Manual acceptance checks:
  - Public gallery loads thumbnails and metadata.
  - Admin dashboard lists pending items, supports uploads, and saves edits.
  - Sidecars remain valid after edits (`manage_sidecars.py validate`).
- When adding tests, use `pytest` with `httpx` clients under `tests/`.

## Contributing
- Keep commits small, imperative, and scoped (e.g., `Add admin metadata review`).
- Document UI changes with screenshots and verification steps in PRs.
- Note any new assets or sidecar updates under `Static/images/`.
- Discuss significant architectural changes before implementation.

## License & Credits
This project is released under the MIT License—see `LICENSE` for details.

Maintainers: Adam Schoen, Allison Lunn, Gemini 2.5, Claude 3.5 Sonnet  
Built with FastAPI, Jinja2, Pillow, and friends.
