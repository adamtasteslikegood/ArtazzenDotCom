<!-- /autoplan restore point: /home/allisone/.gstack/projects/adamtasteslikegood-ArtazzenDotCom/docs-production-infra-autoplan-restore-20260816-050641.md -->

# Plan: Admin Page Gallery Curation & UI Overhaul

## Problem

The admin page currently only shows unreviewed ("pending") images. Once an image is reviewed (`reviewed: true`), it vanishes from admin entirely — the owner has no way to see, search, edit, or un-approve gallery items. The public gallery shows ALL images regardless of review status, meaning unreviewed uploads appear publicly immediately.

The card layout, search/filtering, and introductory content are also missing or broken.

## Goals

### Phase A — Content-control fix (ship first, separate PR)
1. **Public gallery shows only reviewed images** — filter `get_artwork_files()` to return only `reviewed: true`
2. **Bulk migration** — one-shot script to set `reviewed: true` on all existing ~184 images so the gallery doesn't go empty

### Phase B — Admin curation overhaul
3. **Separate pending/gallery sections on admin** — two distinct views: "Pending Review" (unreviewed) and "Gallery" (approved/reviewed) with counts
4. **Search bar filtering** — client-side filtering by title/description/filename across both admin sections, with server-side pagination (50 per page)
5. **Pretext/hero** — introductory text on the public gallery and admin dashboard; update gallery title from placeholder
6. **Card layout fix** — fix admin `.admin-container` grid so pending/gallery sections span full width; verify public gallery grid
7. **Full gallery curation** — from the admin gallery section: edit metadata, un-approve (move back to pending), soft-delete (move to `.trash/` subdirectory)
8. **Admin navigation** — tab bar in header for Dashboard / Settings with active states
9. **Settings page** — move AI config to its own `/admin/settings` route/template

## Scope

### In scope
- Backend: new routes, modify `get_artwork_files()`, add soft-delete/un-approve endpoints, settings route, pagination
- Templates: refactor `reviewAddedFiles.html` with gallery section + search + nav tabs, new `admin_settings.html`, update `index.html`
- CSS: fix admin grid, search bar styles, nav tab styles, interaction states
- Schema: add `status` enum (`pending`/`approved`/`hidden`) to sidecar, replacing `reviewed` boolean
- Migration: bulk-migrate existing sidecars (`reviewed: true` → `approved`, `reviewed: false` → `pending`)
- Tests: pytest tests for all new endpoints

### Out of scope
- Image reordering/sorting beyond alphabetical
- User accounts or role-based permissions
- Full design system visual overhaul (Techno-Botanical implementation deferred)
- Batch operations beyond existing select-all + AI regen

### NOT in scope (deferred to TODOS.md)
- Server-side search (client-side sufficient at current scale with pagination)
- Gallery artwork list caching via watcher (performance optimization, defer until measured)

## Implementation

### Phase A: Content-control fix (separate PR)

#### A1. Add `status` field to sidecar schema + migration
- **File**: `ImageSidecar.schema.json` — add `status` field: enum `["pending", "approved", "hidden"]`, default `"pending"`
- **File**: `main.py` — update `_load_metadata()`, `_ensure_sidecar()`, `_set_review_status_sidecar()` to use `status` instead of `reviewed`. Keep backwards-compat: if sidecar has `reviewed` but no `status`, convert on read (`reviewed: true` → `"approved"`, `false` → `"pending"`)
- **New file**: `scripts/migrate_status.py` — bulk-migrate all existing sidecars: add `status` field based on `reviewed` value, remove `reviewed` key
- **Run before deploying A2** to prevent gallery from going empty
- **Idempotent**: safe to re-run

#### A2. Filter public gallery to approved-only
- **File**: `main.py` — `get_artwork_files()` (~line 922)
- **Change**: Add `if meta.get("status", "pending") != "approved": continue` after loading metadata at line 931
- **Impact**: Public gallery only shows curated work; pending/hidden uploads stay private

### Phase B: Admin curation overhaul

#### B1. Admin layout restructure
- **File**: `templates/reviewAddedFiles.html`
- **Section order (top to bottom)**:
  1. Header with nav tabs: Dashboard (active) | Settings
  2. Upload section — full width, collapsible, drag-drop + server path import
  3. Search bar — full width, `<input type="search">` with JS instant-filter (debounce 200ms, min 0 chars)
  4. Gallery section — full width, shows `status: "approved"` images with count badge
  5. Pending section — full width, shows `status: "pending"` images with count badge
- **Admin grid fix**: Change `.admin-container` so all sections use `grid-column: 1 / -1` (full width)
- **Gallery cards**: Reuse `.pending-card` layout pattern with additional action buttons

#### B2. Gallery section with curation actions
- **File**: `main.py` — `/admin` route (~line 963)
- **Change**: Pass both `pending_images` and `gallery_images` to template
- **New function**: `get_gallery_images()` — scans IMAGES_DIR, returns images where `status: "approved"`
- **Gallery card actions**:
  - "Edit" — links to existing `/admin/review/{image_name}` route
  - "Move to Pending" — calls `POST /admin/unapprove/{image_name}`
  - "Delete" — calls `POST /admin/delete/{image_name}` (soft-delete)
- **Interaction states per action**:
  - Loading: button disabled + spinner icon during fetch
  - Success: card animates out (CSS transition, 300ms fade), counter updates
  - Error: inline error message below card, auto-dismiss after 5s
  - Delete confirmation: inline expand below card ("Are you sure? This moves the image to trash.") with Confirm/Cancel buttons — NOT browser `confirm()` dialog

#### B3. New endpoints
- **File**: `main.py`
- `POST /admin/unapprove/{image_name}`:
  - Uses `_resolve_image_path()` (path traversal protection)
  - Uses `Depends(_verify_admin)`
  - Sets `status: "pending"` in sidecar
  - Preserves existing AI metadata (title, description, ai_details) — documented behavior
  - Returns updated pending + gallery lists as JSON
- `POST /admin/delete/{image_name}`:
  - Uses `_resolve_image_path()` (path traversal protection)
  - Uses `Depends(_verify_admin)`
  - **Soft-delete**: moves image + sidecar to `IMAGES_DIR/.trash/` subdirectory (create if needed)
  - Acquires `sidecar_lock` before moving files (prevents race with watcher)
  - Returns updated gallery list as JSON
  - Uses POST not DELETE (HTML forms can't send DELETE; simpler JS)

#### B4. Watcher race condition fix
- **File**: `main.py` — `new_files_detected()` (~line 700)
- **Change**: Wrap `_load_metadata` call in try/except for `FileNotFoundError`, skip vanished files
- **Impact**: Prevents ghost entries when files are deleted mid-scan

#### B5. Search bar
- **File**: `templates/reviewAddedFiles.html`
- **Placement**: Full-width bar below nav tabs, above gallery/pending sections
- **Behavior**: JS filters visible cards by matching query against title, description, and filename. Filters both gallery and pending sections simultaneously. Shows "No matches" empty state per section.
- **Style**: Uses Instrument Sans font, 8px-based padding, matches existing form input styling from `.ai-config-form input`

#### B6. Settings page
- **File**: `main.py` — new `GET /admin/settings` route with `Depends(_verify_admin)`
- **New template**: `templates/admin_settings.html`
- **Content**: AI config form (moved from dashboard), same fetch-based save/reset
- **Nav**: Header tab "Settings" links here; "Dashboard" links back to `/admin`

#### B7. Pretext and gallery title
- **File**: `templates/index.html` — add intro paragraph below header: gallery description text
- **File**: `templates/reviewAddedFiles.html` — update subheading with contextual dashboard description
- **File**: `main.py` line 1313 — change gallery title from "My Girlfriend's Artwork Gallery" to proper title (configurable via env var `GALLERY_TITLE`, default "Artazzen Gallery")
- **New env var**: `GALLERY_TITLE` added to `.env.example`

#### B8. Admin card/grid layout fix
- **File**: `Static/css/styles.css`
- **Fix**: `.admin-container` grid — make pending and gallery sections span full width
- **Public gallery**: `.gallery-grid` CSS is already correct (`repeat(auto-fill, minmax(300px, 1fr))`); verify no parent constrains width
- **Admin gallery cards**: Reuse `.pending-card` component with additional action button row

## Files Modified

| File | Changes |
|------|---------|
| `main.py` | Filter gallery, new routes (settings, unapprove, soft-delete), gallery data to admin, env var for title, watcher race fix |
| `templates/reviewAddedFiles.html` | Gallery section, search bar, nav tabs, remove inline AI settings, pretext, interaction states |
| `templates/admin_settings.html` | New — AI config form (moved from dashboard) |
| `templates/index.html` | Add intro/pretext paragraph, use GALLERY_TITLE |
| `Static/css/styles.css` | Admin grid fix, search bar styles, nav tab styles, card action styles, transition animations |
| `ImageSidecar.schema.json` | Add `status` enum field, update required fields |
| `scripts/migrate_status.py` | New — migrate sidecars from `reviewed` boolean to `status` enum |
| `.env.example` | Add GALLERY_TITLE |
| `tests/test_main.py` | New tests for all new endpoints |

## Test Plan

### Automated (pytest)
- `test_gallery_shows_only_reviewed` — public `/` excludes `reviewed: false`
- `test_admin_shows_pending_and_gallery` — `/admin` returns both sections
- `test_delete_requires_auth` — unauthenticated POST returns 401
- `test_delete_removes_image_to_trash` — happy path, verify `.trash/` contents
- `test_delete_path_traversal` — `../` payloads rejected
- `test_delete_nonexistent_returns_404`
- `test_unapprove_requires_auth` — unauthenticated POST returns 401
- `test_unapprove_sets_reviewed_false` — verify sidecar after
- `test_unapprove_preserves_metadata` — title/description/ai_details survive
- `test_settings_page_loads` — `/admin/settings` returns 200
- `test_settings_page_requires_auth`

### Manual verification
1. Upload images, verify they appear in admin pending (not public gallery)
2. Review/approve images, verify they move to admin gallery section and appear on public gallery
3. Un-approve from gallery, verify return to pending with metadata intact
4. Soft-delete from gallery, verify moved to `.trash/`
5. Search filter across both sections — matches and "no matches" state
6. Settings page loads, saves, resets AI config
7. Card grid layout responsive at 1200px, 900px, 600px breakpoints
8. Nav tabs highlight active page
9. All existing functionality preserved (upload, import, AI regen)

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|---------------|-----------|-----------|----------|
| 1 | CEO | Add migration to bulk-approve existing images | Mechanical | P1 completeness | Without it, gallery drops to ~10 images | Ship without migration |
| 2 | CEO | Ship reviewed-only filter as separate Phase A PR | Mechanical | P6 action | Content-control bug shouldn't wait for features | Bundle everything |
| 3 | CEO | Status enum vs reviewed boolean | TASTE → OVERRIDE | P1 completeness | User chose status enum (pending/approved/hidden) | Reviewed boolean |
| 4 | CEO | Soft-delete instead of hard delete | Mechanical | P1 completeness | Irreversible on irreplaceable art | os.remove |
| 5 | CEO | Add pagination | Mechanical | P1 completeness | 184 images, growing | Client-only filter |
| 6 | CEO | Drop settings extraction → keep in plan but lower priority | Mechanical | P3 pragmatic | Cleans up admin, low effort | Remove entirely |
| 7 | CEO | Update gallery title from placeholder | Mechanical | P1 completeness | Live placeholder in production | Leave as-is |
| 8 | Design | Specify admin section order | Mechanical | P5 explicit | Search > Gallery > Pending > Upload | Let implementer decide |
| 9 | Design | Add interaction states for new actions | Mechanical | P1 completeness | Delete/un-approve need feedback | Skip states |
| 10 | Design | Gallery first for returning curators | TASTE → OVERRIDE | P5 explicit | User chose Upload-first (initial population phase) | Gallery first |
| 11 | Design | Reuse .pending-card for gallery cards | Mechanical | P5 explicit | Existing pattern, consistent | New component |
| 12 | Design | Fix admin grid to full-width sections | Mechanical | P5 explicit | Current 1fr/2fr squashes content | Keep current grid |
| 13 | Design | Define admin nav as tab bar | Mechanical | P5 explicit | Dashboard + Settings need navigation | No nav |
| 14 | Design | Reference design system tokens | Mechanical | P1 completeness | Techno-Botanical consistency | Ad-hoc styles |
| 15 | Eng | Delete must use _resolve_image_path | Mechanical | P5 explicit | Path traversal protection | Direct path construction |
| 16 | Eng | Handle FileNotFoundError in watcher | Mechanical | P1 completeness | Race condition fix | Ignore |
| 17 | Eng | Un-approve preserves AI metadata | Mechanical | P5 explicit | Document the behavior | Clear metadata |
| 18 | Eng | Auth on all new endpoints | Mechanical | P1 completeness | Every admin route uses Depends | Skip auth |
| 19 | Eng | Soft-delete aligns with CEO finding | Mechanical | P1 completeness | .trash/ subdirectory | Hard delete |
| 20 | Eng | Add 11 pytest tests | Mechanical | P1 completeness | New endpoints need coverage | Manual only |
| 21 | Eng | Cache gallery list (deferred) | Mechanical | P3 pragmatic | Defer until measured | Implement now |

## GSTACK REVIEW REPORT

**Reviewed by**: /autoplan (CEO + Design + Eng, Claude subagent-only — Codex unavailable)
**Plan status**: APPROVED — 21 decisions applied, 2 taste decisions overridden by user (status enum + upload-first)
**Phases completed**: CEO (7 findings), Design (7 findings), Eng (7 findings), DX (skipped — no developer scope)
