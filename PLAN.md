# Plan: Artazzen Mobile — Schema v2 + Mobile Web + SwiftUI Spec

> **Historical document.** This plan was written for the `feat/artazzen-mobile`
> branch (2026-08-18). Schema v2 has been superseded by v3 (see CHANGELOG.md
> `[0.2.0.0]`), the codebase has been modularized into the `app/` package, and
> the SwiftUI iOS app has moved to its own repository
> ([ArtazzenMobile](https://github.com/adamtasteslikegood/ArtazzenMobile)).
> Refer to `CLAUDE.md` for the current architecture and conventions.

> Supersedes the "Admin Page Gallery Curation & UI Overhaul" plan.
> Source: Claude Design project `0d04de68-334e-4421-8f13-7595824d032b` ("Artazzen Mobile")
> Date: 2026-08-18 | Branch: `feat/artazzen-mobile`

## Overview

Two-track deliverable from the Artazzen Mobile design prototype:

- **Track A (Mobile Web)** — Add mobile-responsive views and missing functionality to the existing FastAPI + Jinja2 app
- **Track B (SwiftUI Spec)** — Author a standalone iOS 17+ app specification (specs only — cannot build/test on Linux)

Both tracks share a backend contract: schema v2, updated API endpoints, and sidecar migration.

## Taste Decisions (for user at gate)

1. **`author` vs `artist`**: Existing sidecars and AI prompt use `author`. Design spec says `artist`. Recommend: adopt `artist` per design, migrate `author` → `artist`, keep `author` in schema as deprecated (same pattern as `reviewed`).

## Current State (empirical findings)

- **Schema validation is broken**: `manage_sidecars.py validate` fails on dozens of sidecars — they contain `author`, `caption`, `copyright`, `tags` which `additionalProperties: false` rejects. The app tolerates this silently at runtime (`_validate_and_migrate_sidecars` catches ValidationError, logs a warning, and writes back the sidecar unchanged).
- **OpenAI prompt is v1**: `_build_openai_prompt()` only requests `title` and `description`. The JSON schema sent to OpenAI only accepts those two fields. Response parser only maps those back. Sidecars with caption/author/tags got them from a previous code version.
- **Templates partially implemented**: `reviewAddedFiles.html` already has admin tabs (Dashboard/Settings), search bar, gallery/pending sections, upload, action buttons (edit, unapprove, delete). `artwork_detail.html` is minimal — inline styles, 2-column grid, no v2 fields, no mobile responsiveness.

---

## Part 0: Shared Backend (both tracks depend on this)

### 0.1 Schema v2 — ImageSidecar.schema.json

Update the existing schema. New fields (all with defaults for backwards compat):

| Field        | Type                                            | Default | Notes                                                      |
| ------------ | ----------------------------------------------- | ------- | ---------------------------------------------------------- |
| `caption`    | string                                          | `""`    | Already in sidecars, not in schema                         |
| `tags`       | string[]                                        | `[]`    | Already in sidecars, not in schema                         |
| `artist`     | string                                          | `""`    | New canonical name (replaces `author`)                     |
| `copyright`  | string                                          | `""`    | Already in sidecars, not in schema                         |
| `collection` | string                                          | `""`    | New field                                                  |
| `ai_fields`  | string[] (enum: title/caption/description/tags) | `[]`    | Tracks which fields AI generated                           |
| `author`     | string                                          | `""`    | **Deprecated** — kept for backwards compat like `reviewed` |

Keep `reviewed` (deprecated). Keep `additionalProperties: false`. Keep `author` as deprecated (do NOT remove — production sidecars on Railway volume would fail validation between deploy and migration run if the field is removed from schema before migration runs).

**Effect**: Schema v2 immediately fixes the existing validation failures — all currently-present fields become schema-legal.

### 0.2 Sidecar Migration Script

`scripts/migrate_v2.py`:

1. For each `.json` sidecar in IMAGES_DIR:
   - Add missing v2 fields with defaults
   - Copy `author` → `artist` if `author` present and `artist` empty
   - Keep `author` in the sidecar (deprecated, not removed)
   - For sidecars with `ai_generated: true`: set `ai_fields: ["title", "description"]` (these are the only fields the v1 prompt actually generated)
   - For sidecars with `ai_generated: false` or missing: set `ai_fields: []`
   - Write back atomically (write to `.tmp`, rename)
2. Validate against updated schema
3. Report: migrated count, error count, already-current count
4. Idempotent — safe to re-run

### 0.3 manage_sidecars.py Updates

- Import and validate against updated schema
- Handle v2 fields in report output

### 0.4 API Endpoint Changes in main.py

#### 0.4a — Extend `POST /admin/metadata/{image_name}` (line 1336)

Add Form fields: `caption`, `tags` (comma-separated string → list), `artist`, `copyright`, `collection`. Merge into sidecar on save.

#### 0.4b — Extend `POST /admin/ai/regenerate` (line 1153)

Add optional `fields` parameter (string[]). When provided, only regenerate the specified fields (title, caption, description, tags). When absent, regenerate all AI-eligible fields (current behavior).

**Force-regenerate scope**: v2 force blanks `title`, `description`, `caption`, and `tags` (not just title+description as v1 does).

Track regenerated fields in `ai_fields` array. Example: if `fields=["caption"]`, only blank `caption`, re-request from AI, and set `ai_fields` to include `"caption"`.

#### 0.4c — New `GET /admin/api/collections` endpoint

Returns distinct `collection` values from all sidecars. Protected by `_verify_admin` — follows convention of `/admin/api/new-files`. The collections picker serves admin flows; an unauthenticated endpoint would leak pending/hidden curation data.

```python
@app.get("/admin/api/collections", response_class=JSONResponse)
async def list_collections(_: None = Depends(_verify_admin)) -> JSONResponse:
    ...
```

#### 0.4d — Update AI prompt + response pipeline

Three functions need changes:

1. **`_build_openai_prompt()` (line 395)**: Expand to request `caption`, `tags`, `artist`, `copyright` in addition to `title` and `description`. Make field-aware — only request fields being regenerated.

2. **`_request_openai_metadata()` (line 463)**: Update the `json_schema` sent to OpenAI to include `caption` (string), `tags` (array of strings), `artist` (string), `copyright` (string). Update response extraction at line 643 to map all fields from parsed response.

3. **`_populate_missing_metadata()` (line 648)**: Check for missing caption/tags/artist/copyright in addition to title/description. Map all AI-returned fields into sidecar. Update `ai_fields` array with which fields were set by AI.

### 0.5 Template Context Updates

All templates that display metadata need the new fields in their context dict. Update template rendering to include v2 fields where displayed.

---

## Part 1: Track A — Mobile Web (FastAPI + Jinja2)

### 1.1 Mobile-Responsive Layout

Update `Static/css/styles.css`:

- Add mobile breakpoint (`max-width: 600px`) styles
- Touch targets >= 44x44px
- Single-column layouts for all views on mobile

### 1.2 Dark Mode

Add `.az-light` / `.az-dark` class scoping:

- Carbon (#121212) <-> Parchment (#F9F7F2) swap
- CSS custom properties for theme colors
- JS toggle that sets class on `<html>` and persists to localStorage
- `prefers-color-scheme` media query as default

### 1.3 Admin Bottom Tab Bar (admin templates only)

**Scoped to admin views** — the public gallery does NOT get a bottom tab bar.

- Bottom fixed navigation bar on mobile for admin templates
- 5 tabs: Queue, Review, Capture, Gallery, Settings
- Tab icons (inline SVG)
- Active tab highlighting
- Smooth tab transitions
- Hidden on desktop (admin already has top nav tabs)

### 1.4 Review Queue Enhancements (reviewAddedFiles.html)

The admin page already has segmented Dashboard/Settings tabs, search bar, gallery/pending sections. Enhancements:

- Status filter segmented control: All / Pending / Approved / Hidden
- Tag-based filtering in search
- Swipe-to-approve/hide on mobile (touch gesture JS)
- Card layout responsive improvements

### 1.5 Swipe Deck View (new template section or JS mode)

- Card stack UI for reviewing pending artworks
- Swipe right = approve, swipe left = hide
- Animated card transitions (CSS + touch event JS)
- Fallback to button-based approve/hide on non-touch devices

### 1.6 Artwork Detail Enhancements (artwork_detail.html)

- Display all v2 fields (caption, tags, artist, copyright, collection)
- Card-to-card navigation (prev/next arrows)
- Per-field AI regeneration buttons (calls extended `/admin/ai/regenerate` with `fields` param)
- Mobile-responsive single-column layout (replace inline 2-column grid)
- Remove inline styles, use CSS classes

### 1.7 Capture Flow (new template section)

- Camera input via `<input type="file" accept="image/*" capture="environment">`
- Upload preview with AI metadata generation
- Progress indicator during AI processing
- Form to edit generated metadata before save

### 1.8 Settings View Enhancement

- Dark mode toggle (new)
- Existing AI config (toggle, model, temperature, tokens) already in place

---

## Part 2: Track B — SwiftUI Specification

> **Moved.** The SwiftUI iOS app now lives in its own repository:
> [ArtazzenMobile](https://github.com/adamtasteslikegood/ArtazzenMobile).
> The `ArtazzenMobile/` directory was removed from this repo in v0.2.0.0.
> See the CHANGELOG entry for details.

---

## Implementation Order

1. **Schema v2 + migration** (0.1, 0.2) — fixes existing validation failures, both tracks need this
2. **API changes** (0.3, 0.4) — both tracks consume these endpoints
3. **Track A: Mobile web** (Part 1) — extends existing app
4. **Track B: SwiftUI spec** (Part 2) — standalone deliverable

## Constraints

- ~~All Python code stays in `main.py` per project rules~~ (Superseded: code now lives in the `app/` package; `main.py` is a thin entrypoint shim.)
- SwiftUI specs are **authored, not verified** (Linux — no Xcode)
- Feature branch from `dev`, PR targeting `dev`
- Workflows capped at <5 agents
- `Static/` capital-S preserved everywhere

## Files Modified

| File                              | Change                                                                                            |
| --------------------------------- | ------------------------------------------------------------------------------------------------- |
| `ImageSidecar.schema.json`        | Add v2 fields, keep `author` deprecated, fix validation                                           |
| `main.py`                         | Extended endpoints, new `/admin/api/collections`, expanded AI prompt+parser, `ai_fields` tracking |
| `manage_sidecars.py`              | v2 validation support                                                                             |
| `Static/css/styles.css`           | Mobile responsive, dark mode, bottom tab bar (admin only), new components                         |
| `templates/reviewAddedFiles.html` | Status filter, swipe deck, mobile tab bar, responsive enhancements                                |
| `templates/artwork_detail.html`   | v2 fields, per-field regen, mobile responsive, remove inline styles                               |
| `templates/index.html`            | Mobile responsive gallery grid                                                                    |
| `templates/previewImageText.html` | v2 fields in review form                                                                          |
| `scripts/migrate_v2.py`           | New — sidecar migration script                                                                    |
| `ArtazzenMobile/`                 | ~~New — SwiftUI package (Track B)~~ (Moved to own repo)                                           |
