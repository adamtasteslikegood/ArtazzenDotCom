# CLAUDE.md — ArtazzenDotCom

Artwork gallery and curation platform built with FastAPI + Jinja2. Public gallery at `/`, admin dashboard at `/admin`.

@AGENTS.md
@DESIGN.md
@BRANCHING_STRATEGY.md

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ADMIN_PASSWORD + API keys
uvicorn main:app --reload
```

Gallery: `http://127.0.0.1:8000/` | Admin: `http://127.0.0.1:8000/admin`

## Architecture

Single-file FastAPI app (`main.py`, ~46KB) serving Jinja2 templates with on-disk image storage.

```
main.py                  # All routes, models, startup logic
manage_sidecars.py       # CLI: validate/migrate sidecar JSON files
ImageSidecar.schema.json # Authoritative schema for per-image metadata
templates/               # Jinja2: index, artwork_detail, review views
Static/                  # Mounted at /static (preserve capital S)
  css/                   # Stylesheets (Techno-Botanical design system)
  images/                # Artwork files + co-located .json sidecars
artazzen-design-system/  # Design system spec and tokens
scripts/ahead-behind.sh  # Branch divergence checker
tests/test_main.py       # Pytest suite
```

### Key Concepts

- **Image sidecars**: Every image in `Static/images/` has a co-located `.json` file conforming to `ImageSidecar.schema.json`. Required fields: `title`, `description`, `ai_generated`, `ai_details`, `reviewed`, `detected_at`. These are the source of truth for artwork metadata.
- **Background watcher**: On startup, scans for new images and queues them for review.
- **AI metadata**: Optional OpenAI integration generates titles/descriptions. Controlled via `/admin/config`.

### Route Map

| Path | Method | Purpose |
|------|--------|---------|
| `/` | GET | Public gallery |
| `/artwork/{image_filename}` | GET | Single artwork detail |
| `/admin` | GET | Admin dashboard |
| `/admin/review` | GET | Review queue |
| `/admin/review/{image_name}` | GET | Review specific image |
| `/admin/api/new-files` | GET | JSON: pending files |
| `/admin/upload` | POST | Upload artwork |
| `/admin/import-path` | POST | Import from filesystem |
| `/admin/metadata/{image_name}` | POST | Save image metadata |
| `/admin/config` | GET/POST | AI config CRUD |
| `/admin/config/reset` | POST | Reset AI config |
| `/admin/ai/regenerate` | POST | Trigger AI regeneration |

## Tech Stack

- **Runtime**: Python 3.10+, FastAPI, Uvicorn
- **Templating**: Jinja2
- **Image processing**: Pillow
- **Validation**: jsonschema, Pydantic
- **HTTP client**: httpx (for AI API calls)
- **Monitoring**: Sentry SDK
- **Testing**: pytest, pytest-asyncio, Playwright
- **Deployment**: Procfile-based (Heroku/Railway style)

## Development Rules

- All code in `main.py` — no splitting into modules unless discussed first.
- Sidecar JSON must validate against `ImageSidecar.schema.json`. Run `python manage_sidecars.py validate` after schema changes.
- `Static/` is capital-S everywhere; FastAPI mounts it at `/static`.
- Templates use the Techno-Botanical design system from `DESIGN.md`.
- Python: PEP 8, type hints, `logging.getLogger(__name__)`.

## Testing

```bash
pytest                    # Run test suite
python manage_sidecars.py validate  # Validate all sidecars
```

Manual verification endpoints:
```bash
curl http://127.0.0.1:8000/admin/api/new-files
curl -F "files=@image.jpg" http://127.0.0.1:8000/admin/upload
curl http://127.0.0.1:8000/admin/config
```

## Git Workflow

`dev` is the primary working branch. `main` is the deploy target.

```bash
# Sync local dev with remote
git checkout dev && git fetch origin && git pull origin dev

# Check ahead/behind status across all branches
bash scripts/ahead-behind.sh          # top 10 branches vs repo default
bash scripts/ahead-behind.sh --base dev  # compare against dev

# Start a new feature branch from dev
git checkout dev && git pull origin dev
git checkout -b feature/my-thing dev
```

Always branch from `dev`, never from `main`. PRs target `dev`.

On completion of any `feat/`, `fix/`, `docs/`, or `chore/` branch: commit, push, and open a PR targeting `dev`. Open as **draft** if work is still in progress or needs discussion; open as **ready for review** if all checks should pass and it's mergeable.

### Branch Protection

Direct pushes to `dev` and `main` are **blocked** by GitHub rulesets. All changes go through pull requests. See `BRANCHING_STRATEGY.md` for full ruleset details.

### PR Lifecycle

1. **Create a PR** from your feature branch targeting `dev`.
2. **Wait for automated checks** — CodeQL, Copilot review, and code quality must pass.
3. **Request review** if needed; respond to every comment.
4. **Read all review comments** — do not merge with unread feedback.
5. **Fix requested changes**, push new commits, and reply to each thread.
6. **Resolve all comment threads** (required on `main` by ruleset).
7. **Merge** via rebase or merge commit (squash is not allowed by ruleset).

## Deployment

**Production**: https://artazzen.com — deployed on Railway, auto-deploys from `main`.

### Infrastructure

- **Hosting**: Railway (dedicated project), Procfile: `uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`
- **DNS**: Cloudflare nameservers. Apex domain (`artazzen.com`) is canonical.
- **www redirect**: `www.artazzen.com` → `artazzen.com` via Cloudflare 301 permanent redirect rule. `www` uses a proxied DNS record that resolves through Cloudflare edge IPs.
- **CDN/Proxy**: Cloudflare proxy enabled on apex — provides SSL termination, DDoS protection, and caching.

### Railway Volume

A persistent volume is attached to the FastAPI service, mounted at `/data/images`. In production, set `IMAGES_DIR=/data/images` so artwork persists across deploys. Locally, `IMAGES_DIR` defaults to `Static/images/`.

The app detects volume mode automatically (`_USING_VOLUME` flag) and switches the image URL prefix from `/static/images` to `/images` (a separate StaticFiles mount).

### Admin Authentication

Admin routes (`/admin/*`) are protected by HTTP Basic Auth.
- `ADMIN_USERNAME` — defaults to `admin`
- `ADMIN_PASSWORD` — **required**; admin access is disabled when unset

### Environment Variables

See `.env.example` for the full list. Key vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGES_DIR` | `Static/images` | Image storage path. Set to `/data/images` on Railway |
| `IMPORT_ROOT` | `imports` | Only server directory allowed as a source for admin filesystem imports |
| `ADMIN_USERNAME` | `admin` | Basic auth username for admin |
| `ADMIN_PASSWORD` | *(none)* | Basic auth password (**required** for admin) |
| `MY_OPENAI_API_KEY` | *(none)* | OpenAI API key for AI metadata |
| `OPENAI_IMAGE_METADATA_MODEL` | `gpt-4o-mini` | Model for AI descriptions |
| `OPENAI_TIMEOUT_SECONDS` | `30` | Timeout for OpenAI calls |
| `MAX_UPLOAD_SIZE_MB` | `50` | Max upload file size |
| `PORT` | *(uvicorn default)* | Server port (set by Railway) |

## Behavioral Guidelines

Follow the four Karpathy principles:
1. **Think Before Coding** — Understand the full context before making changes.
2. **Simplicity First** — Prefer the simplest solution that works.
3. **Surgical Changes** — Minimize diff size; touch only what's needed.
4. **Goal-Driven Execution** — Stay focused on the stated objective.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
