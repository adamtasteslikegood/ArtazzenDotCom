# SEO Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add consistent public-page SEO metadata, structured data, and robust request-time sitemap generation without changing artwork access control or image assets.

**Architecture:** Add a focused SEO context/serialization helper in the public application layer. Public routes pass page-specific title, description, image, and breadcrumb data to the shared base template; the sitemap uses XML-safe serialization and filesystem timestamps.

**Tech Stack:** FastAPI, Jinja2, Python standard-library `json`/`xml.etree`, pytest/httpx.

---

### Task 1: Add SEO context helpers

**Files:**

- Create: `app/seo.py`
- Test: `tests/test_main.py`

- [ ] Add helpers for canonical URL joining, description fallback/truncation, absolute image URLs, and JSON-LD serialization. Ensure query strings never enter canonical URLs and JSON-LD is safely escaped for HTML script embedding.
- [ ] Add tests covering URL joining, HTML-sensitive metadata values, and valid JSON-LD output.
- [ ] Run `pytest tests/test_main.py -q` (or report missing pytest dependency).
- [ ] Commit: `feat: add public SEO context helpers`.

### Task 2: Wire metadata into public templates/routes

**Files:**

- Modify: `app/routes_public.py`
- Modify: `templates/base.html`
- Modify: `templates/index.html`
- Modify: `templates/collections_index.html`
- Modify: `templates/collection_detail.html`
- Modify: `templates/artwork_detail.html`
- Test: `tests/test_main.py`

- [ ] Pass an SEO dictionary for each public route, using sidecar title/description and concise page fallbacks.
- [ ] Render description, canonical, Open Graph (`og:type`, title, description, URL, image), and Twitter card tags from the shared base template.
- [ ] Render JSON-LD blocks for artwork and breadcrumb lists, omitting optional properties when metadata is absent.
- [ ] Add route tests asserting page-specific metadata, absolute social URLs, valid JSON-LD, and breadcrumbs.
- [ ] Run the focused SEO tests and commit: `feat: add public page SEO metadata`.

### Task 3: Harden dynamic sitemap and robots output

**Files:**

- Modify: `app/routes_public.py`
- Test: `tests/test_main.py`

- [ ] Build sitemap XML with `xml.etree.ElementTree` (or equivalent) so site URLs, slugs, and filenames are escaped correctly.
- [ ] Include home, collections index, resolvable non-empty public collections, and approved artwork. Keep request-time scanning so approval changes add/remove entries immediately.
- [ ] Add UTC ISO-8601 `<lastmod>` values from sidecar/image mtimes where available.
- [ ] Preserve robots’ admin disallow and configured absolute sitemap URL.
- [ ] Add tests that parse XML, verify lastmod, special-character escaping, empty collection exclusion, and approval transition add/remove behavior.
- [ ] Run sitemap/robots tests and commit: `feat: harden sitemap generation`.

### Task 4: Verification and delivery

**Files:**

- Modify: none unless test fixes are required.

- [ ] Run `python -m compileall -q app main.py`.
- [ ] Run the complete available test suite; record any environment limitation if pytest is unavailable.
- [ ] Inspect `git diff`, confirm no WebP/AVIF/srcset or access-control changes, and verify branch is `feat/seo-foundation`.
- [ ] Push all commits and open a PR targeting `dev` with summary, tests, and explicit scope exclusions.
