# Artwork Gallery Web Application

ArtazzenDotCom is a FastAPI + Jinja2 artwork gallery and curation platform. Images live on disk with JSON "sidecars" that describe each piece, while the app provides a public gallery, collection pages, and an admin dashboard for uploads, reviews, and optional AI-powered metadata generation.

**Production**: [artazzen.com](https://artazzen.com) — deployed on Railway, auto-deploys from `main`.

## Highlights

- Responsive gallery view with artwork detail pages and the Techno-Botanical accent palette.
- Collections (nested, multi-membership albums) and series (ordered groups of related edits).
- Admin dashboard (`/admin`) for uploads, metadata review, curation, and AI configuration.
- Per-image JSON sidecars validated against `ImageSidecar.schema.json`; no centralized manifest.
- SEO: canonical URLs, Open Graph + Twitter Card tags, JSON-LD (`VisualArtwork`, `BreadcrumbList`), dynamic sitemap, and robots.txt.
- Startup background watcher keeps the pending review queue fresh.
- Optional OpenAI-powered title and description generation with per-field regeneration and preview mode.
- "Techno-Botanical" design system documented in `DESIGN.md`.

## Requirements

- Python 3.11 or newer
- `pip` for dependency management
- (Optional) OpenAI API key for AI metadata suggestions

## Quick Start

```bash
git clone https://github.com/adamtasteslikegood/ArtazzenDotCom.git
cd ArtazzenDotCom
python -m venv .venv
source .venv/bin/activate            # use .\.venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env                 # fill in ADMIN_PASSWORD + API keys
uvicorn main:app --reload --env-file .env
```

Gallery: `http://127.0.0.1:8000/` | Admin: `http://127.0.0.1:8000/admin`

## Project Layout

```
main.py                  # Entrypoint + compat shim (uvicorn main:app)
app/
  config.py              # Paths, env, runtime AI config (single source of truth)
  sidecars.py            # Schema, path safety, sidecar/metadata I/O
  ai_metadata.py         # OpenAI prompt/request/populate pipeline
  curation.py            # Collections + series registries, migration, dedup
  watcher.py             # Pending-file detection and background poll
  seo.py                 # Canonical URLs, OG/Twitter context, JSON-LD builders
  security.py            # Basic auth dependency + security headers
  routes_admin.py        # All /admin routes (APIRouter)
  routes_public.py       # Gallery, artwork detail, collections (APIRouter)
  factory.py             # create_app: lifespan, mounts, middleware, routers
manage_sidecars.py       # CLI: validate/migrate sidecars + curation registries
ImageSidecar.schema.json # Authoritative schema for per-image metadata
CollectionsRegistry.schema.json  # Schema for .curation/collections.json
SeriesRegistry.schema.json       # Schema for .curation/series.json
templates/               # Jinja2: base + base_admin, pages extend them
Static/                  # Mounted at /static (preserve capital S)
  css/                   # Stylesheets (Techno-Botanical design system)
  images/                # Artwork files + co-located .json sidecars
    .curation/           # collections.json + series.json registries
scripts/                 # Migration, branch status, codegen utilities
tests/test_main.py       # Pytest suite
```

Module layering (no cycles): `config -> sidecars -> ai_metadata -> curation -> watcher -> seo -> security/routes -> factory -> main`.

## Route Map

| Path                           | Method   | Purpose                                  |
| ------------------------------ | -------- | ---------------------------------------- |
| `/`                            | GET      | Public gallery                           |
| `/artwork/{image_filename}`    | GET      | Single artwork detail                    |
| `/collections`                 | GET      | Collections index                        |
| `/collections/{slug}`          | GET      | Collection page (series strips + grid)   |
| `/robots.txt`                  | GET      | SEO: robots.txt with sitemap directive   |
| `/sitemap.xml`                 | GET      | SEO: dynamic XML sitemap                 |
| `/admin`                       | GET      | Admin dashboard                          |
| `/admin/review`                | GET      | Review queue                             |
| `/admin/review/{image_name}`   | GET      | Review specific image                    |
| `/admin/upload`                | POST     | Upload artwork                           |
| `/admin/import-path`           | POST     | Import from filesystem                   |
| `/admin/metadata/{image_name}` | POST     | Save image metadata                      |
| `/admin/api/new-files`         | GET      | JSON: pending files                      |
| `/admin/api/collections`       | GET/POST | Collections registry CRUD                |
| `/admin/api/series`            | GET/POST | Series registry CRUD                     |
| `/admin/config`                | GET/POST | AI config CRUD                           |
| `/admin/ai/regenerate`         | POST     | AI regeneration (fields, force, preview) |

## Metadata Workflow

1. Drop images into `Static/images/`. Supported formats: JPG, PNG, GIF, WEBP, BMP, TIFF.
2. The background watcher detects new files and creates a JSON sidecar (same filename, `.json` extension) with required fields:
   - `title` (string)
   - `description` (string)
   - `ai_generated` (boolean)
   - `ai_details` (object)
   - `status` (`"pending"` | `"approved"` | `"hidden"`)
   - `detected_at` (Unix epoch seconds, number)
3. The admin review page (`/admin/review`) lets you edit metadata, approve/hide items, assign collections, and save changes atomically.
4. Sidecars validate against `ImageSidecar.schema.json`. Run `python manage_sidecars.py validate` after any manual edits.

## AI Metadata Support

Enable automatic suggestions via environment variables:

```bash
export MY_OPENAI_API_KEY=sk-...
export OPENAI_IMAGE_METADATA_MODEL=gpt-5.6-luna   # optional override (this is the default)
```

Runtime settings persist in `ai_config.json` and are editable from the admin UI under **AI Metadata Settings**. The app triggers AI generation when new assets arrive or when you request suggestions during review. Per-field regeneration and preview mode are available from the review detail page.

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable                      | Default                | Description                                           |
| ----------------------------- | ---------------------- | ----------------------------------------------------- |
| `SITE_URL`                    | `https://artazzen.com` | Canonical site URL for SEO (sitemap, canonical tags)  |
| `IMAGES_DIR`                  | `Static/images`        | Image storage path. Set to `/data/images` on Railway  |
| `IMPORT_ROOT`                 | `imports`              | Allowed source directory for admin filesystem imports |
| `ADMIN_USERNAME`              | `admin`                | Basic auth username for admin                         |
| `ADMIN_PASSWORD`              | _(none)_               | Basic auth password (**required** for admin access)   |
| `MY_OPENAI_API_KEY`           | _(none)_               | OpenAI API key for AI metadata                        |
| `OPENAI_IMAGE_METADATA_MODEL` | `gpt-5.6-luna`         | Model for AI descriptions                             |
| `OPENAI_TIMEOUT_SECONDS`      | `30`                   | Timeout for OpenAI calls                              |
| `MAX_UPLOAD_SIZE_MB`          | `50`                   | Max upload file size                                  |

## Testing

```bash
pytest                              # Run test suite
python manage_sidecars.py validate  # Validate all sidecars + curation registries
```

CI also runs `ruff check`, `black --check`, and `npx prettier --check`.

## Useful Commands

```bash
# Development
uvicorn main:app --reload --env-file .env     # Start dev server with local env
pytest                                       # Run test suite
python manage_sidecars.py validate           # Validate sidecar JSON

# API probes
curl http://127.0.0.1:8000/admin/api/new-files
curl -F "files=@image.jpg" http://127.0.0.1:8000/admin/upload
curl http://127.0.0.1:8000/admin/config

# Branch management
bash scripts/ahead-behind.sh                 # Branch divergence vs default
bash scripts/ahead-behind.sh --base dev      # Branch divergence vs dev
```

## Development Notes

- Application code lives in the `app/` package; `main.py` is a thin entrypoint/shim. New code goes in the module that owns its layer.
- Follow PEP 8 with type hints and `logging.getLogger(__name__)`.
- Keep handlers asynchronous and avoid blocking I/O on request paths.
- `Static/` is capital-S everywhere; FastAPI mounts it at `/static`.
- Templates use the Techno-Botanical design system from `DESIGN.md`.
- Sidecar JSON must validate against `ImageSidecar.schema.json`.

## Contributing

- Keep commits small, imperative, and scoped (e.g., `Add admin metadata review`).
- Branch from `dev`, never from `main`. PRs target `dev`. See `BRANCHING_STRATEGY.md`.
- Document UI changes with screenshots and verification steps in PRs.
- Discuss significant architectural changes before implementation.

## License & Credits

This project is released under the MIT License — see `LICENSE` for details.

Maintainers: Adam Schoen, Allison Lunn, Gemini 2.5, Claude 3.5 Sonnet
Built with FastAPI, Jinja2, Pillow, and friends.
