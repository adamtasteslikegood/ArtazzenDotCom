# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- AI print-master pipeline (`app/print_master.py`): opt-in 4x Real-ESRGAN
  upscaling of uploads into 300 DPI print masters stored in
  `IMAGES_DIR/print_masters/` (excluded from the public gallery), tracked in
  the sidecar under an optional `print_master` block. Pluggable backends:
  Replicate hosted (`REPLICATE_API_TOKEN`, recommended on Railway),
  `realesrgan-ncnn-vulkan` binary, local torch (`requirements-upscale.txt`).
- Admin endpoints `POST/GET /admin/print-master/{image}` plus a
  Generate/Regenerate panel with live status on the review page.
- `upscale_enabled` / `upscale_scale` / `upscale_model` admin config keys
  (env: `UPSCALE_ENABLED`, `UPSCALE_SCALE`, `UPSCALE_MODEL`,
  `UPSCALE_BACKEND`); upscaling is off by default and degrades to a no-op
  (automatic path) or a clear 503 (manual button) when no backend is set.
- `scripts/upscale_batch.py` CLI for back-catalog batch upscaling and
  `PRINT_WORKFLOW.md` documenting the 72 DPI -> 300 DPI print workflow.

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
