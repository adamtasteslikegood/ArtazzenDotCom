# Copilot Instructions for ArtazzenDotCom

## Project Overview

ArtazzenDotCom is a FastAPI + Jinja2 artwork gallery and curation platform. Public gallery at `/`, admin dashboard at `/admin`. Deployed on Railway, auto-deploys from `main`.

## Architecture

Modular FastAPI app with layered `app/` package. `main.py` is the uvicorn entrypoint and compatibility shim; application logic lives in the `app/` package.

```
main.py                  # Entrypoint + compat shim (uvicorn main:app)
app/
  config.py              # Paths, env, runtime AI config
  sidecars.py            # Schema, path safety, sidecar/metadata I/O
  ai_metadata.py         # OpenAI prompt/request/populate pipeline
  curation.py            # Collections + series registries, migration
  watcher.py             # Pending-file detection and background poll
  seo.py                 # Canonical URLs, OG/Twitter context, JSON-LD builders
  security.py            # Basic auth dependency + security headers
  routes_admin.py        # All /admin routes (APIRouter)
  routes_public.py       # Gallery, artwork detail, collections (APIRouter)
  factory.py             # create_app: lifespan, mounts, middleware, routers
manage_sidecars.py       # CLI: validate/migrate sidecars + curation registries
ImageSidecar.schema.json # Authoritative schema for per-image metadata
templates/               # Jinja2: base + base_admin, pages extend them
Static/                  # Mounted at /static (preserve capital S)
  css/                   # Stylesheets
  images/                # Artwork files + co-located .json sidecars
    .curation/           # collections.json + series.json registries
tests/test_main.py       # Pytest suite
```

Layering (no cycles): `config → sidecars → ai_metadata → curation → watcher → seo → security/routes → factory → main`.

## Key Concepts

- **Image sidecars**: Every image in `Static/images/` has a co-located `.json` sidecar conforming to `ImageSidecar.schema.json`. Required fields: `title`, `description`, `ai_generated`, `ai_details`, `status`, `detected_at`.
- **Collections (v3)**: Album-like groups. Sidecar `collections` array is authoritative membership; metadata lives in `.curation/collections.json`.
- **Series (v3)**: Ordered groups of related edits, owned by one collection. Registry at `.curation/series.json` is authoritative.
- **Background watcher**: Scans for new images on startup and queues them for review.
- **AI metadata**: Optional OpenAI integration generates titles/descriptions, controlled via `/admin/config`.
- **SEO metadata**: Every public page gets canonical URLs, Open Graph and Twitter Card tags, and optional JSON-LD (`VisualArtwork`, `BreadcrumbList`). `/robots.txt` disallows `/admin`; `/sitemap.xml` is generated at request time for approved artworks and collections that are non-empty or have child collections.

## Coding Standards

- Python >= 3.11, PEP 8, type hints throughout.
- Logging via `logging.getLogger(__name__)` — no `print()` in production paths.
- `snake_case` for functions/variables; `PascalCase` for classes.
- Never rename or relocate the `Static/` directory — FastAPI mount depends on the exact capitalisation.
- Sidecar JSON must conform to `ImageSidecar.schema.json`; always validate after writing.
- New application code goes in the `app/` module that owns its layer, not in `main.py`.

## Environment & Dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload          # dev server → http://127.0.0.1:8000/
```

Key env vars: `ADMIN_PASSWORD` (required for admin), `MY_OPENAI_API_KEY`, `IMAGES_DIR` (defaults to `Static/images`), `OPENAI_IMAGE_METADATA_MODEL`, `OPENAI_TIMEOUT_SECONDS`.

## Testing & Validation

```bash
pytest                              # test suite
python manage_sidecars.py validate  # sidecar + curation registry schema check
```

Regression-check: gallery view (`/`), admin dashboard (`/admin`), upload flow, collections (`/collections`), metadata persistence, and SEO output (`/robots.txt`, `/sitemap.xml`, canonical/OG/Twitter tags, JSON-LD).

## Common Pitfalls

- The background watcher runs as an asyncio task; use the module-level lock when writing shared sidecar/config state.
- Image uploads are validated against `ALLOWED_IMAGE_EXTENSIONS`.
- Sidecar writes must be atomic (`write temp → rename`) to avoid corruption during polling.
- Do not introduce extra keys beyond `ImageSidecar.schema.json`, and do not drop required keys from sidecar JSON.
- Cross-module calls go through module attributes (e.g. `config.IMAGES_DIR`).

## 📚 AI-Generated Code Documentation

DocBot can generate repository documentation under `_docs/` after a documentation run is approved. This configuration change does not create that folder by itself.

When `_docs/` is present, it may provide:

- **Function-level documentation** - Parameters, return values, and function relationships
- **File overviews** - Purpose and functionality of each module
- **Directory indexes** - Navigation that mirrors the repository structure
- **Direct source code links** - Line references to the source revision used for generation

**When assisting with development:**

- Use `_docs/` as a navigation aid, not as an authoritative source
- Verify generated claims and line links against the current source code
- Treat the current source code and tests as authoritative when they disagree with generated documentation

**Expected documentation structure:**

- `_docs/README.md` - Main documentation index
- Additional folders mirror the documented repository structure

## Excluded Paths

Do not analyze, lint, or comment on files in these directories — they contain agent skills and generated artifacts that are not part of the application codebase:

- `.claude/skills/`
- `.claude/agents/`
- `.claude/commands/`
- `.copilot/skills/`
- `.github/instructions/`
- `artazzen-design-system/`
- `AGENTS.md` (generated file)
