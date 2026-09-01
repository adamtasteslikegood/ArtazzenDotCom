# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- SEO foundation (`app/seo.py`): canonical URLs, Open Graph and Twitter Card
  meta tags, JSON-LD structured data (`VisualArtwork` for artwork pages,
  `BreadcrumbList` for artwork and collection pages), dynamic `/sitemap.xml`
  (approved artworks + non-empty collections, `<lastmod>` from filesystem
  mtimes), and `/robots.txt` (disallows `/admin`, advertises sitemap).

## [0.2.0.0] - 2026-08-20

### Added

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

### Changed

- Modularized `main.py` into the layered `app/` package (config, sidecars,
  ai_metadata, curation, watcher, security, routers, factory); `main.py` is
  now a thin entrypoint + compatibility shim.
- `max_output_tokens` is floored at 1200 for gpt-5* reasoning models.

### Fixed

- AI-regenerated titles could contain the whole JSON reply; the response
  parser now unwraps nested JSON, strips code fences, decodes double-encoded
  replies, rejects truncated (incomplete) responses, and no longer crashes on
  empty output.
- A failed AI call after force-regenerate no longer blanks stored metadata,
  and regeneration no longer double-writes the sidecar.
- Cancel on the review edit form now genuinely reverts all fields.

### Removed

- The SwiftUI iOS app moved to its own repository (`~/Projects/ArtazzenMobile`).

## [0.1.1.0] - 2026-04-21

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
