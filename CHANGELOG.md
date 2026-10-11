# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

> Do not release this section to `main` until ArtazzenMobile loads images
> through `/admin/image/{name}` with credentials (or the public `/images`
> URLs the API returns). The app currently builds `/static/images/<name>`
> URLs itself and sends no auth, and those URLs now return 404.

### Added

- WebP derivatives for every image: 480 px for gallery, collection and series
  grids and 1600 px for the artwork page, stored in `IMAGES_DIR/.derived/`.
  Built on upload and import, backfilled by the watcher for existing images
  (five per scan), never upscaled, EXIF orientation applied, none for animated
  GIFs. Pages use the original until a derivative exists.
- Versioned URLs for images and the stylesheet (`/images/v<token>/<name>`,
  `/static/v<token>/css/styles.css`) served with
  `Cache-Control: public, max-age=31536000, immutable`. Unversioned URLs get
  one hour, and a stale or invented token redirects (308) to the current URL.
- `GET /admin/image/{image_name}` (Basic auth, `no-store`, optional
  `?w=480|1600`) for previews of images of any status.
- Cloudflare purge by `Cache-Tag` when an image is unapproved or deleted,
  enabled by `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID`. Without them
  shared caches are capped at one day (`s-maxage=86400`).
- "Use artist's name in prompt" checkbox in the admin AI settings
  (`artist_in_prompt`, off by default). While off, the artist's name is left
  out of the AI metadata prompt, so generated descriptions and captions no
  longer name the artist. Existing installs pick up the off default on upgrade;
  tick the box to send the name again.

### Changed

- **Breaking:** images are served only from `/images`, and only when their
  status is `approved`. Sidecar JSON, `.curation/`, `.trash/`, and pending or
  hidden images return 404. `/static/images/...` returns 404 in every
  environment; previously it served every file in the folder when no volume
  was configured.
- `/artwork/{name}` returns 404 unless the image is approved; it used to show
  the title, description and tags of pending and hidden images.
- An unapproved collection cover is ignored in favour of the first approved
  member.
- `/admin/api/new-files` items carry `thumb_url` (and `display_url` for
  gallery items); pending `url` values point at `/admin/image/{name}`.
- The "Reasoning effort" setting in the admin AI settings is labelled
  "Effort". The stored key (`reasoning_effort`) is unchanged.

## [0.3.0] - 2026-10-10

### Added

- Reasoning effort setting in the admin AI settings (`none`, `minimal`, `low`,
  `medium`, `high`; default `low`), sent to GPT-5 and GPT-6 models. Efforts a
  model rejects (`none` on `gpt-6-astra`; `none` and `minimal` on
  `gpt-6.1-sol`) are disabled in the form and fall back to `low` on the
  server.
- `AI_MAX_RETRIES` (default 5) and `AI_RETRY_DELAY_SECONDS` (default 60)
  environment variables for the watcher's automatic AI retries.
- WAI DocBot configuration (`.github/wai-docbot.yml`).

### Changed

- Default AI metadata model is now `gpt-6-luna` (code default and the shipped
  `ai_config.json`, which takes precedence over
  `OPENAI_IMAGE_METADATA_MODEL`).
- The admin model list is now `gpt-6.1-sol`, `gpt-6-luna` and `gpt-6-astra`;
  older models are no longer offered. A previously saved model that is no
  longer listed stays visible and selected.
- GPT-6 models are handled like GPT-5: no `temperature` is sent and
  `max_output_tokens` is raised to at least 1200.
- The admin temperature control is removed. `/admin/config` still accepts and
  returns `temperature` for older clients; it is sent only to non-reasoning
  models.
- Copilot code-review instructions now ask for all findings in the first
  review and limit re-reviews to changed lines.
- Dependency updates, including FastAPI 0.142.2, Starlette 1.7.0, Uvicorn
  0.54.0, Pydantic 2.13.5 and sentry-sdk 2.70.0. `pydantic-core` is no longer
  pinned directly.

### Fixed

- Background watcher no longer re-sends an image to OpenAI on every 5-second
  poll when an attempt leaves fields empty. After the first attempt it makes
  at most `AI_MAX_RETRIES` further tries per image, at least
  `AI_RETRY_DELAY_SECONDS` apart. A restart grants a new set of retries.
  Admin-triggered regeneration is not limited.
- The retry count starts over when an image file is replaced under the same
  name or regenerated from the admin page, is not used up while AI is
  disabled or no API key is set, and is dropped when the image is deleted.
- An unexpected error during an automatic AI request is recorded on the
  sidecar as `error_processing` and counts as a failed attempt, instead of
  being retried on every poll;
  preview and other non-saving requests still raise it.

## [0.2.0] - 2026-09-02

### Added

- SEO foundation (`app/seo.py`): canonical URLs, Open Graph and Twitter Card
  meta tags, JSON-LD structured data (`VisualArtwork` for artwork pages,
  `BreadcrumbList` for artwork and collection pages), dynamic `/sitemap.xml`
  (approved artworks + collections that are non-empty or have child
  collections, `<lastmod>` from filesystem mtimes), and `/robots.txt`
  (disallows `/admin`, advertises sitemap).
- Collections (schema v3): nested, multi-membership albums. Sidecars record
  memberships in a `collections` slug array; collection metadata (title,
  parent chain, cover, order) lives in the `IMAGES_DIR/.curation/collections.json`
  registry. New public pages `/collections` and `/collections/{slug}`.
- Series (schema v3): ordered groups of related edits owned by one collection,
  rendered as strips inside the collection page (`#series-{id}` anchors) with
  an authoritative `IMAGES_DIR/.curation/series.json` registry mirrored into
  sidecar `series` arrays.
- Admin curation APIs (`/admin/api/collections`, `/admin/api/series`) and a
  minimal curation panel in the admin Settings tab.
- Preview mode for AI regeneration: per-field regens fill the edit form
  without persisting; only Approve & Save writes the sidecar.
- Base templates (`base.html`, `base_admin.html`) with shared header, site
  navigation, footer, and theme init; all pages extend them.
- `scripts/migrate_v3.py` (idempotent) and registry validation in
  `manage_sidecars.py validate`.
- Semantic versioning with GitHub tagged releases, CI-gated version bumps on
  PRs to `main`, and automated changelog-based release notes.

### Changed

- Gallery grid: live CSS shimmer replaces dead skeleton CSS, stops on image
  load via `img-loaded` class toggle.
- Detail page grayscale reduced from 10% to 8% and transition shortened from
  0.5s to 0.4s for consistency with gallery grid.
- Active nav link uses `aria-current="page"` instead of class-based styling.
- Modularized `main.py` into the layered `app/` package (config, sidecars,
  ai_metadata, curation, watcher, security, routers, factory); `main.py` is
  now a thin entrypoint + compatibility shim.
- `max_output_tokens` is floored at 1200 for gpt-5\* reasoning models.

### Fixed

- Broken images now hide gracefully with CSS-only fallback and set
  `aria-label` for screen readers.
- Footer simplified to plain text "Artazzen" (removed non-functional
  "AUTHENTICATED ARTIFACT" line).
- Shimmer animation respects `prefers-reduced-motion`.
- AI-regenerated titles could contain the whole JSON reply; the response
  parser now unwraps nested JSON, strips code fences, decodes double-encoded
  replies, rejects truncated (incomplete) responses, and no longer crashes on
  empty output.
- A failed AI call after force-regenerate no longer blanks stored metadata,
  and regeneration no longer double-writes the sidecar.
- Cancel on the review edit form now genuinely reverts all fields.

### Removed

- The SwiftUI iOS app moved to its own repository (`~/Projects/ArtazzenMobile`).

## [0.1.1] - 2026-04-21

### Added

- Implemented the new "Techno-Botanical" design system for a unique and beautiful visual experience.
- Added a comprehensive test suite to ensure application stability and prevent future regressions.
- You can now manage your artwork with the new admin dashboard, which includes features for reviewing, uploading, and importing images.
- Artwork pages now feature dynamic accent colors extracted from the art itself, creating a more immersive viewing experience.
- Added a "Zoom & Bloom" animation for a more engaging transition when viewing artwork.

### Changed

- Refactor admin routes to use FastAPI dependency injection
- Refactor event handlers to use lifespan context manager
- Update TemplateResponse calls to resolve deprecation warnings

### Fixed

- Resolve dependency conflicts with Python 3.14
- Fix various test failures and warnings
- Resolve merge conflict in .gitignore
