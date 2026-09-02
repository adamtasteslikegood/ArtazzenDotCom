# SEO Foundation Design

## Goal

Improve crawlability and share previews for public gallery pages while preserving
current route behavior. This session does not change artwork access control and
does not add an image conversion or responsive-asset pipeline.

## Scope

- Build a shared SEO context for public Jinja templates.
- Emit page-specific title and meta description values.
- Emit canonical, Open Graph, and Twitter Card metadata using configured
  `SITE_URL` and existing image URLs.
- Emit JSON-LD for artwork pages and breadcrumb lists for artwork/collection
  pages.
- Generate valid, escaped sitemap XML with `lastmod` values.
- Include only public collection pages in the sitemap while preserving existing
  collection route behavior.
- Add focused tests for metadata and sitemap inclusion/removal behavior.

Explicitly out of scope: changing pending/hidden artwork route access,
WebP/AVIF conversion, `srcset`/`picture` generation, upload asset lifecycle,
and unrelated performance or analytics work.

## Design

### SEO context

Add a small helper owned by the public-route layer that accepts the current
request and page data and returns normalized values for templates: canonical
URL, title, description, preview image, page type, and optional JSON-LD. Keep
`SITE_URL` as the canonical origin and ensure path construction excludes query
strings. Use existing sidecar title/description data, with concise fallbacks for
the gallery, collections index, collection detail, and artwork detail pages.

The shared base template renders the standard title, description, canonical,
Open Graph, and Twitter tags. Page templates provide optional values through
the existing `head_extra` block or shared context. Values must be escaped by
Jinja and JSON-LD must be serialized safely for script embedding.

### Structured data

Artwork detail pages emit an `ImageObject`/`VisualArtwork` JSON-LD object with
name, description, image, URL, and artist when available. Collection and
artwork pages emit `BreadcrumbList` data derived from their existing navigation
context. No claims are added when source metadata is absent.

### Sitemap and robots

Keep `/robots.txt` dynamic and continue advertising the configured sitemap URL.
Refactor sitemap construction to use an XML serializer or equivalent escaping,
rather than interpolating unescaped values. Include the home page, collections
index, public collection pages, and approved artwork pages. A collection is
public for sitemap purposes when it is a valid registry entry and its existing
route can resolve; empty collections remain route-compatible but are excluded
from the sitemap to avoid thin index targets. Add `<lastmod>` where a reliable
filesystem timestamp exists (sidecar/image mtime), using a stable ISO-8601 UTC
date/time format.

The sitemap remains request-time generated, so approval changes are reflected
without a rebuild. Existing URL quoting and canonical origin behavior remain,
with XML escaping layered on top.

### Testing

Extend the route tests to verify:

- each public page has a page-appropriate title, meta description, canonical,
  Open Graph, and Twitter tags;
- artwork pages include escaped JSON-LD and breadcrumbs;
- sitemap XML parses successfully, contains `lastmod`, and escapes special
  characters;
- approved artwork appears while pending/hidden artwork does not, including
  after status changes;
- empty/unresolvable collections are omitted from the sitemap;
- robots continues to advertise the configured sitemap and disallow admin.

Tests should use temporary image/sidecar and curation registries and avoid
network calls or image conversion.

## Acceptance criteria

1. Public pages render complete, page-specific SEO metadata without breaking
   existing templates.
2. Social crawlers receive absolute canonical and artwork image URLs.
3. JSON-LD is valid JSON and contains no unsourced placeholder claims.
4. Sitemap is valid XML, correctly escaped, includes `lastmod`, and reflects
   current approved artwork and public collection state at request time.
5. Existing route behavior, including direct access to non-approved artwork,
   remains unchanged in this session.
6. Focused tests pass; no WebP/AVIF or `srcset` assets are introduced.
