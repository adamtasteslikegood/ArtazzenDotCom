<!-- GENERATED FILE - DO NOT EDIT.
     Produced by scripts/generate_agents_md.py from CLAUDE.md and its
     @-imports. Edit those source files and re-run the script instead. -->

# AGENTS.md - ArtazzenDotCom

> Flattened, self-contained copy of `CLAUDE.md` and the files it imports,
> for agent tools that do not support `@`-import syntax.
> `CLAUDE.md` remains the source of truth.

Artwork gallery and curation platform built with FastAPI + Jinja2. Public gallery at `/`, admin dashboard at `/admin`.

<!-- Inlined from docs/agent-handbook.md -->

# Agent Handbook

This guide summarizes how autonomous coding agents should work inside the ArtazzenDotCom repository. Keep it handy while you collaborate with the human maintainers.

## Mission Profile

- Deliver well-explained code or documentation improvements without breaking existing flows.
- Respect the FastAPI + Jinja2 architecture centered around `main.py`.
- Treat sidecar JSON files next to each image as the source of truth—the schema lives in `ImageSidecar.schema.json`.
- Preserve `Static/` capitalization; FastAPI mounts it at `/static`.

## Daily Workflow

1. **Understand the request.** Confirm whether it is a code change, doc update, or review. Ask clarifying questions only when truly needed.
2. **Check the repo state.** Assume the working tree may be dirty—never revert changes you did not introduce.
3. **Plan first.** Use the planning tool for any non-trivial task (multi-file edits, new features, refactors). Skip it only for the simplest 1–2 step requests.
4. **Work incrementally.** Prefer `apply_patch` for manual edits. Do not run destructive git commands or rely on global `cd`; set `workdir` on shell calls.
5. **Validate.** Run targeted commands when possible (formatters, scripts, manual curl checks). If sandboxing blocks a critical command, request approval with a clear justification.

## Coding Standards

- Python code follows PEP 8, uses type hints, and logs through `logging.getLogger(__name__)`.
- Functions use `snake_case`; classes use `PascalCase`.
- Sidecar files must conform to `ImageSidecar.schema.json` (the authoritative source). Required fields: `title`, `description`, `ai_generated`, `ai_details`, `status`, `detected_at`.
- Template filenames stay aligned with existing naming (`index.html`, `reviewAddedFiles.html`, etc.).

## Documentation & Communication

- Write concise, actionable commit-ready descriptions even if you are not creating the commit.
- In final responses: lead with the change explanation, cite files as `path:line`, and offer natural next steps (tests, review reminders) when relevant.
- Summaries should be informative yet brief; avoid dumping entire file contents.

## Tooling Expectations

- Python ≥3.10 recommended (virtual env: `python -m venv .venv` → `source .venv/bin/activate`).
- Install dependencies with `pip install -r requirements.txt`.
- Local server: `uvicorn main:app --reload` and visit `http://127.0.0.1:8000/`.
- Useful API probes:
  - `curl http://127.0.0.1:8000/admin/api/new-files`
  - `curl -F "files=@/path/to/image.jpg" http://127.0.0.1:8000/admin/upload`
  - `curl http://127.0.0.1:8000/admin/config`
- Sidecar management CLI: `python manage_sidecars.py validate`.

## Testing & Quality

- No formal automated suite yet—lean on manual verification via browser, `test_main.http`, or curl.
- When adding tests, prefer `pytest` + `httpx` in `tests/test_*.py`, keeping runs fast and isolated.
- Watch for regressions in gallery view (`/`), admin dashboard (`/admin`), upload flow, and metadata persistence.

## Sandbox & Approvals

- Default sandbox mode is `workspace-write`; network is restricted. Request escalation only if absolutely required and provide one-sentence justification.
- Never execute GUI apps or destructive commands without explicit user direction.
- If unexpected repo changes appear mid-task, stop and ask how to proceed.

Stay deliberate, keep communication tight, and ensure each hand-off leaves the repository healthier than you found it.

<!-- End of docs/agent-handbook.md -->
<!-- Inlined from DESIGN.md -->

# Design System — Artazzen

## Product Context

- **What this is:** An artwork gallery and curation platform for high-end digital and physical art.
- **Who it's for:** Collectors, curators, and the artist.
- **Space/industry:** Digital Art, AI Art, Botanical Illustration.
- **Project type:** Web App + Admin Dashboard.

## Aesthetic Direction

- **Direction:** Techno-Botanical
- **Decoration level:** Intentional (Canvas textures, noise shaders, architectural offsets).
- **Mood:** Sophisticated, high-contrast, precise, and organic.

## Typography

- **Display/Hero:** Clash Grotesk — Bold and architectural to match the art's sharp lines.
- **Body:** Instrument Sans — Professional and highly legible.
- **Data/Tables:** JetBrains Mono — For the JSON-based admin workflow.
- **Scale:** Modular 8px scale.

## Color

- **Approach:** Balanced (Monochrome base with dynamic accents).
- **Primary:** #121212 (Carbon)
- **Secondary:** #F9F7F2 (Parchment)
- **Accents:** Dynamic violet, orange, and teal pulled from the artwork.
- **Dark mode:** Redesign surfaces to pure Carbon with reduced saturation for accents.

### Dynamic Accent Algorithm

To ensure brand consistency and accessibility, dynamic accent colors are chosen from artwork using a defined algorithm:

1.  **Extraction:** On processing a new artwork, the backend will extract a palette of 5-8 dominant colors using a k-means clustering algorithm on the image's pixels.
2.  **Selection:** From this palette, the algorithm will select the color that is:
    a. Not too dark or too light (e.g., filter out colors near black or white).
    b. Has the highest saturation.
3.  **Accessibility Check:** The selected color will be checked for a minimum WCAG AA contrast ratio (4.5:1) against the primary backgrounds (#F9F7F2 and #121212). If it fails, the next most saturated color is chosen until one passes. If no color passes, a default accent color (e.g., `--accent-violet`) will be used.
4.  **Storage:** The chosen accent color is stored in the artwork's JSON sidecar file.

**Implementation Note:** The parameters for this algorithm (e.g., number of clusters for k-means, brightness/saturation thresholds) should be kept in the application's configuration code and not exposed through an admin UI, to ensure portability and consistency.

## Spacing & Layout

- **Base unit:** 8px
- **Density:** Hybrid (Spacious for gallery, compact for admin).
- **Layout:** Asymmetric editorial overlap for gallery; strict grid for admin.
- **Border radius:** sm: 2px, md: 4px, lg: 8px.

## Information Architecture

### Page Structure & Flow

The application has two primary areas: the public-facing **Gallery** and the private **Admin Dashboard**.

**1. Public Gallery Flow**

The public gallery follows a simple, two-level hierarchy:

1.  **Gallery (Home):** The main entry point, displaying a curated collection of all artworks.
2.  **Artwork Detail:** A dedicated page for each artwork, accessed from the gallery.

```ascii
[ / (Gallery) ]
      |
      +--> [ /artwork/{id_1} (Detail) ]
      |
      +--> [ /artwork/{id_2} (Detail) ]
      |
      ...
```

**2. Admin Dashboard Flow**

The admin dashboard provides tools for content management and system configuration.

```ascii
[ /admin (Dashboard) ]
      |
      +--> [ /admin/review (Review Queue) ]
      |      |
      |      +--> [ /admin/review/{id} (Review Detail) ]
      |
      +--> [ /admin/config (Configuration) ]
```

### Content Hierarchy (per page)

#### Gallery Page (`/`)

1.  **Primary:** The visual grid of artwork thumbnails. The user's primary focus is browsing art.
2.  **Secondary:** Artwork titles.
3.  **Tertiary:** Artwork descriptions.

#### Artwork Detail Page (`/artwork/{id}`)

1.  **Primary:** The main artwork image.
2.  **Secondary:** The artwork description/text.
    ...
3.  **Tertiary:** Navigation back to the gallery.

## Interaction States

| FEATURE                 | LOADING                                           | EMPTY                                                             | ERROR                                                                     | SUCCESS                             | PARTIAL |
| ----------------------- | ------------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------- | ----------------------------------- | ------- |
| Gallery Grid            | Show skeleton placeholders for each artwork item. | Display a message with a call to action (e.g., "No artwork yet.") | Display a generic error message.                                          | Artworks are displayed in the grid. | N/A     |
| Artwork Image (in grid) | Skeleton placeholder.                             | N/A                                                               | `onerror` handler shows a 'Not Found' placeholder.                        | Image is displayed.                 | N/A     |
| ...                     |
| Artwork Detail Page     | Show skeleton placeholders for image and text.    | N/A                                                               | If artwork not found, the server should return a standard 404 error page. | Artwork details are displayed.      | N/A     |

## User Journey & Emotional Arc

This storyboard maps the user's path through the gallery, ensuring the design supports the intended emotional arc of discovery and appreciation.

| STEP | USER DOES                   | USER FEELS                                                                                                                                                    | PLAN SPECIFIES?                   |
| ---- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| 1    | Lands on the gallery page   | **Intrigued, Curious.** The high-contrast, architectural layout creates a sense of entering a special, curated space.                                         | Asymmetric grid, hero typography. |
| 2    | Scrolls through the artwork | **Engaged, Exploring.** The "bloom" animations and editorial layout make browsing feel like a deliberate, paced experience, not an endless scroll.            | Motion system, layout rules.      |
| 3    | Clicks on an artwork        | **Anticipation.** The user has found something that resonates and wants to see more.                                                                          | "Zoom & Bloom" page transition.   |
| 4    | Views the artwork detail    | **Focused, Appreciative.** The minimal layout with the large image and focused text allows the user to immerse themselves in the artwork without distraction. | Detail page layout, typography.   |
| ...  |
| 5    | Returns to the gallery      | **Satisfied, Ready for more.** The easy navigation encourages further exploration.                                                                            | Back navigation.                  |

## Responsive & Accessibility (A11y)

### Responsive Design

The layout should adapt fluidly to different screen sizes. Key breakpoints are:

- **Desktop ( > 900px):** Full asymmetric grid layout.
- **Tablet (601px - 900px):** Simplified grid, possibly single-column for admin areas.
- **Mobile (<= 600px):** Single-column layout for the gallery grid. All touch targets should be at least 44x44px.

### Accessibility

Accessibility is a primary concern. The application must be usable for everyone.

- **Semantic HTML:** Use appropriate HTML5 tags (`<main>`, `<header>`, `<nav>`, etc.) to give structure to the page.
- **ARIA Roles:** Where necessary, use ARIA roles to enhance semantics for screen readers (e.g., `role="button"` on non-button elements that act as buttons).
- **Keyboard Navigation:** All interactive elements must be focusable and operable via the keyboard. Focus order must be logical. A visible focus indicator is required.
- **Image Alt Text:** All images must have descriptive `alt` text. Decorative images should have an empty `alt=""`.
- **Color Contrast:** All text must meet WCAG AA contrast ratios (4.5:1 for normal text, 3:1 for large text). The current Carbon/Parchment palette has excellent contrast.

## Motion

- **Approach:** Intentional "Bloom" animations.
- **Easing:** ease-out for entrances (blooming), ease-in for exits.
- **Duration:** 250ms short, 400ms medium.
- **Page Transitions:** Use a "Zoom & Bloom" animation when navigating from the gallery to the artwork detail page. This should be implemented using the **View Transitions API**.
  - The clicked artwork thumbnail should be the origin of the transition.
  - For browsers that do not support the View Transitions API, a simple CSS fade-in/fade-out should be used as a fallback.
  - All transitions must respect the `prefers-reduced-motion` media query and be disabled (or reduced to a simple fade) when it is active.

## Changelog

| Date       | Change                        | Notes                                                                |
| ---------- | ----------------------------- | -------------------------------------------------------------------- |
| 2026-04-20 | Initial design system created | Tailored to "Techno-Botanical" art style and Claude Design workflow. |

## Known Gaps

> **Note:** The tokens under `artazzen-design-system/` are incomplete — that
> content was truncated partway through, before Claude Design finished
> implementing this DESIGN.md. Treat the sections above as authoritative and
> re-generate the token files before relying on them.

<!-- End of DESIGN.md -->
<!-- Inlined from BRANCHING_STRATEGY.md -->

# Branching Strategy

## Branch Model

```
main (production)          ← deployed to Railway production environment
  └── dev (integration)    ← default working branch, all feature branches start here
       ├── feat/...        ← new features
       ├── fix/...         ← bug fixes
       ├── docs/...        ← documentation changes
       └── chore/...       ← maintenance, deps, CI config
```

### Branch Roles

| Branch                                 | Purpose                   | Deploys To                            | Protected                               |
| -------------------------------------- | ------------------------- | ------------------------------------- | --------------------------------------- |
| `main`                                 | Production-ready code     | Railway production                    | Yes — PR required, all threads resolved |
| `dev`                                  | Integration and staging   | Railway staging (when configured)     | Yes — PR required                       |
| `feat/*`, `fix/*`, `docs/*`, `chore/*` | Short-lived work branches | Railway PR previews (when configured) | No                                      |

### Rules

- **Always branch from `dev`**, never from `main`.
- PRs from feature branches target `dev`. `dev` is promoted to `main` for production releases.
- Direct pushes to `dev` and `main` are blocked by GitHub rulesets.
- Force-push and branch deletion are blocked on `dev` and `main`.
- Keep branches short-lived — merge or close within days, not weeks.

## GitHub Rulesets

Two rulesets enforce branch protection:

### `dev` (targets default branch)

- No direct push, no force-push, no deletion
- Pull request required (0 approvals minimum)
- Copilot code review on push and drafts
- CodeQL security scanning (high+ security, errors threshold)
- Code quality checks (errors threshold)

### `main_railway_production` (targets `main`, `production`, `prod`)

- Everything in the `dev` ruleset, plus:
- **Required review thread resolution** — every PR comment thread must be resolved before merge
- Allowed merge methods: rebase or merge commit (no squash)

## PR Lifecycle

1. **Branch** — `git checkout dev && git pull origin dev && git checkout -b feat/my-thing dev`
2. **Develop** — make changes, commit with clear messages.
3. **Push** — `git push -u origin feat/my-thing`
4. **Open PR** — target `dev`. Open as draft if still in progress; ready for review if mergeable. Write a summary and test plan.
5. **Automated checks** — wait for CodeQL, Copilot review, and code quality to pass.
6. **Review** — request review if needed. Read every comment carefully.
7. **Respond** — reply to each review thread. Push fix commits (don't force-push).
8. **Resolve threads** — all comment threads must be marked resolved (enforced by ruleset on `main`).
9. **Merge** — use rebase or merge commit. Delete the feature branch after merge.

### Check Branch Status

```bash
bash scripts/ahead-behind.sh              # all branches vs repo default
bash scripts/ahead-behind.sh --base dev   # all branches vs dev
bash scripts/ahead-behind.sh 5 --newest   # 5 most recently updated branches
```

## Railway Environments

Railway supports multiple environments tied to branches. Each environment has its own service instances, variables, and (optionally) volumes.

### Production (`main`)

- **URL**: https://artazzen.com (canonical apex domain)
- **Branch**: `main` — auto-deploys on push/merge
- **Hosting**: Dedicated Railway project
- **DNS**: Cloudflare nameservers. `www.artazzen.com` → 301 redirect to apex via Cloudflare rule. `www` uses a proxied DNS record that resolves through Cloudflare edge IPs.
- **CDN/Proxy**: Cloudflare proxy on apex — SSL termination, DDoS protection, caching
- **Volume**: persistent storage mounted at `/data/images` (`IMAGES_DIR=/data/images`)
- **Variables**: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `MY_OPENAI_API_KEY`, and other production secrets set in Railway dashboard

### PR Deploy Previews (planned)

Railway can spin up isolated environments for each pull request, giving reviewers a live preview before merging.

**What PR previews provide:**

- Temporary environment created automatically when a PR is opened
- Own service instance with the PR's code deployed
- Isolated variables (can inherit from production or use test values)
- Unique preview URL for each PR
- Auto-teardown when the PR is merged or closed

**Setup steps (after initial PRs are merged):**

1. Enable "PR Deploy Previews" in the Railway service settings
2. Connect the GitHub repo if not already linked
3. Configure environment variables for preview environments (use test API keys, separate admin credentials)
4. Decide on volume strategy — previews can share a read-only volume snapshot or use ephemeral storage
5. Set a base environment to inherit variables from

**Considerations for this project:**

- Preview environments will need their own `ADMIN_PASSWORD` (set a shared test password in Railway's PR environment config)
- `IMAGES_DIR` can be left unset (defaults to `Static/images/` with bundled test images) or pointed at a preview volume
- `IMPORT_ROOT` limits admin filesystem imports to one approved staging directory; keep the default ephemeral `imports/` directory or set an explicit preview path
- `MY_OPENAI_API_KEY` — use a separate key with lower rate limits for previews, or leave unset to disable AI features in previews
- Preview URLs are temporary — don't use them for anything persistent

### Environment Variable Matrix

| Variable                      | Production                                                   | PR Preview                    |
| ----------------------------- | ------------------------------------------------------------ | ----------------------------- |
| `IMAGES_DIR`                  | `/data/images` (volume)                                      | unset (uses `Static/images/`) |
| `IMPORT_ROOT`                 | `/data/images/imports` or another approved staging directory | unset (uses `imports/`)       |
| `ADMIN_USERNAME`              | `admin`                                                      | `admin`                       |
| `ADMIN_PASSWORD`              | production secret                                            | shared test password          |
| `MY_OPENAI_API_KEY`           | production key                                               | test key or unset             |
| `OPENAI_IMAGE_METADATA_MODEL` | `gpt-4o-mini`                                                | `gpt-4o-mini`                 |
| `MAX_UPLOAD_SIZE_MB`          | `50`                                                         | `50`                          |
| `PORT`                        | set by Railway                                               | set by Railway                |

## Workflow Summary

```
developer creates feat/thing from dev
       │
       ▼
push to origin/feat/thing
       │
       ▼
open PR targeting dev ──► Railway PR preview spins up (when enabled)
       │
       ▼
automated checks run (CodeQL, Copilot, code quality)
       │
       ▼
code review ◄──► fix and respond to comments
       │
       ▼
all threads resolved, checks pass
       │
       ▼
merge to dev ──► dev promoted to main for production release
       │
       ▼
merge to main ──► Railway production auto-deploys
       │
       ▼
delete feat/thing branch
```

<!-- End of BRANCHING_STRATEGY.md -->

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ADMIN_PASSWORD + API keys
uvicorn main:app --reload
```

Gallery: `http://127.0.0.1:8000/` | Admin: `http://127.0.0.1:8000/admin`

## Architecture

Modular FastAPI app serving Jinja2 templates with on-disk image storage. `main.py` is the uvicorn entrypoint and compatibility shim; the application lives in the layered `app/` package.

```
main.py                  # Entrypoint + compat shim (uvicorn main:app)
app/
  config.py              # Paths, env, runtime AI config (single source of truth)
  sidecars.py            # Schema, path safety, sidecar/metadata I/O
  ai_metadata.py         # OpenAI prompt/request/populate pipeline
  curation.py            # Collections + series registries, migration, dedup
  watcher.py             # Pending-file detection and background poll
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
artazzen-design-system/  # Design system spec and tokens
scripts/                 # ahead-behind.sh, generate_agents_md.py, migrate_v2.py, migrate_v3.py
docs/agent-handbook.md   # Agent Handbook source (imported by CLAUDE.md via @)
.claude/                 # Claude Code hooks + settings
tests/test_main.py       # Pytest suite
```

### Generated Files

- `AGENTS.md` — generated by `scripts/generate_agents_md.py` from `CLAUDE.md` + its `@`-imports. Never edit directly; run `python scripts/generate_agents_md.py` to regenerate or `--check` to validate.

Layering (no cycles): `config → sidecars → ai_metadata → curation → watcher → security/routes → factory → main`. Cross-module calls go through module attributes (e.g. `config.IMAGES_DIR`) so tests monkeypatch the defining module.

### Key Concepts

- **Image sidecars**: Every image in `Static/images/` has a co-located `.json` file conforming to `ImageSidecar.schema.json`. Required fields: `title`, `description`, `ai_generated`, `ai_details`, `status`, `detected_at`. These are the source of truth for artwork metadata.
- **Collections (v3)**: Album-like groups. A sidecar's `collections` array of slugs is the authoritative membership record; collection metadata (title, description, `parent` for nesting, `cover`, `order`) lives in `IMAGES_DIR/.curation/collections.json`. The v2 `collection` string is deprecated but kept; `scripts/migrate_v3.py` (and app startup) migrate it.
- **Series (v3)**: Ordered groups of related edits (usually stylized variants of one source photo) owned by exactly one collection and rendered inside that collection's page (`#series-{id}` anchors). The registry `IMAGES_DIR/.curation/series.json` is authoritative for membership and order; sidecar `series` arrays are mirrors that validation re-syncs (registry wins). On a collection page, an image that is both a direct member and in one of that collection's series renders only in the series strip.
- **Background watcher**: On startup, scans for new images and queues them for review.
- **AI metadata**: Optional OpenAI integration generates titles/descriptions. Controlled via `/admin/config`.

### Route Map

| Path                           | Method   | Purpose                                                  |
| ------------------------------ | -------- | -------------------------------------------------------- |
| `/`                            | GET      | Public gallery                                           |
| `/robots.txt`                  | GET      | SEO: robots.txt with sitemap directive                   |
| `/sitemap.xml`                 | GET      | SEO: dynamic XML sitemap (approved artworks+collections) |
| `/artwork/{image_filename}`    | GET      | Single artwork detail                                    |
| `/admin`                       | GET      | Admin dashboard                                          |
| `/admin/review`                | GET      | Review queue                                             |
| `/admin/review/{image_name}`   | GET      | Review specific image                                    |
| `/admin/api/new-files`         | GET      | JSON: pending files                                      |
| `/admin/upload`                | POST     | Upload artwork                                           |
| `/admin/import-path`           | POST     | Import from filesystem                                   |
| `/admin/metadata/{image_name}` | POST     | Save image metadata                                      |
| `/collections`                 | GET      | Collections index                                        |
| `/collections/{slug}`          | GET      | Collection page (series strips + grid)                   |
| `/admin/api/collections`       | GET/POST | Collections registry CRUD                                |
| `/admin/api/series`            | GET/POST | Series registry CRUD                                     |
| `/admin/config`                | GET/POST | AI config CRUD                                           |
| `/admin/config/reset`          | POST     | Reset AI config                                          |
| `/admin/ai/regenerate`         | POST     | AI regeneration (supports `fields`, `force`, `preview`)  |

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

- Application code lives in the `app/` package (see Architecture); `main.py` stays a thin entrypoint/shim. Put new code in the module that owns its layer.
- Sidecar JSON must validate against `ImageSidecar.schema.json`. Run `python manage_sidecars.py validate` after schema changes (also validates the curation registries).
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

| Variable                      | Default                | Description                                                            |
| ----------------------------- | ---------------------- | ---------------------------------------------------------------------- |
| `SITE_URL`                    | `https://artazzen.com` | Canonical site URL for SEO (sitemap, robots.txt, canonical tags)       |
| `IMAGES_DIR`                  | `Static/images`        | Image storage path. Set to `/data/images` on Railway                   |
| `IMPORT_ROOT`                 | `imports`              | Only server directory allowed as a source for admin filesystem imports |
| `ADMIN_USERNAME`              | `admin`                | Basic auth username for admin                                          |
| `ADMIN_PASSWORD`              | _(none)_               | Basic auth password (**required** for admin)                           |
| `MY_OPENAI_API_KEY`           | _(none)_               | OpenAI API key for AI metadata                                         |
| `OPENAI_IMAGE_METADATA_MODEL` | `gpt-4o-mini`          | Model for AI descriptions                                              |
| `OPENAI_TIMEOUT_SECONDS`      | `30`                   | Timeout for OpenAI calls                                               |
| `MAX_UPLOAD_SIZE_MB`          | `50`                   | Max upload file size                                                   |
| `PORT`                        | _(uvicorn default)_    | Server port (set by Railway)                                           |

## Core Principles

Follow the four Karpathy principles for LLM-assisted coding:

1. **Think Before Coding** — State assumptions before implementing. If a request admits multiple interpretations, list them rather than silently picking one. When something is genuinely unclear, stop and ask.
2. **Simplicity First** — Write the minimum code that solves the stated problem. No speculative features, premature abstractions, or configuration knobs for one call site.
3. **Surgical Changes** — Touch only what the task requires. Do not opportunistically refactor adjacent code. Every changed line should be traceable to the user's request.
4. **Goal-Driven Execution** — Convert vague requests into checkable success criteria before coding. For multi-step tasks, state the plan with verification per step.

## Workflow Instructions

1. **Branch** from `dev` using the appropriate prefix (`feat/`, `fix/`, `docs/`, `chore/`).
2. **Develop** incrementally — commit often with clear messages.
3. **Validate** — run `pytest` and `python manage_sidecars.py validate` before pushing.
4. **Push** and open a PR targeting `dev`. Mark as draft if still in progress.
5. **Review** — wait for CodeQL and Copilot checks; respond to every comment thread.
6. **Merge** via rebase or merge commit (squash is not allowed by ruleset).

See [Git Workflow](#git-workflow) and [BRANCHING_STRATEGY.md](BRANCHING_STRATEGY.md) for full details.

## PR Review — Reading Comments

When receiving code review or preparing to merge, use the GitHub API to read **all** feedback. `gh pr view --comments` misses review bodies and suppressed Copilot reviews.

```bash
# Full review bodies (includes suppressed Copilot reviews)
gh api repos/{owner}/{repo}/pulls/{number}/reviews \
  --jq '.[] | {user: .user.login, state: .state, body: .body}'

# Inline review comments (file-level feedback)
gh api repos/{owner}/{repo}/pulls/{number}/comments \
  --jq '.[] | {user: .user.login, path: .path, body: .body}'

# General PR comments (top-level discussion)
gh api repos/{owner}/{repo}/issues/{number}/comments \
  --jq '.[] | {user: .user.login, body: .body}'
```

A deterministic PreToolUse hook (`.claude/hooks/pretooluse-pr-review-nudge.sh`) guards this: `gh pr merge` requires confirmation that all comments are addressed, `gh pr view --comments` is denied in favor of the API calls above, and reads/replies get skill nudges. It fires only on matching `gh` commands.

> **Hook registration:** Only `pretooluse-pr-review-nudge.sh` is registered in `.claude/settings.json`. `pre-commit.sh` (CLAUDE.md validator) exists but is **not wired up** — register it as a `PreCommit` hook to activate.

## Common Commands

```bash
# Development
uvicorn main:app --reload                    # Start dev server
pytest                                       # Run test suite
python manage_sidecars.py validate           # Validate sidecar JSON

# API probes
curl http://127.0.0.1:8000/admin/api/new-files
curl -F "files=@image.jpg" http://127.0.0.1:8000/admin/upload
curl http://127.0.0.1:8000/admin/config

# Branch management
bash scripts/ahead-behind.sh                 # Branch divergence vs default
bash scripts/ahead-behind.sh --base dev      # Branch divergence vs dev

# Generated files
python scripts/generate_agents_md.py         # Regenerate AGENTS.md from CLAUDE.md
python scripts/generate_agents_md.py --check # Validate AGENTS.md is current
```

## Quality Checklist

Before submitting a PR, verify:

- [ ] Sidecar JSON validates: `python manage_sidecars.py validate`
- [ ] Tests pass: `pytest`
- [ ] Gallery renders correctly at `/`
- [ ] Admin dashboard loads at `/admin`
- [ ] Upload flow works end-to-end
- [ ] No hardcoded secrets or API keys in diff
- [ ] `Static/` capitalization preserved

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
