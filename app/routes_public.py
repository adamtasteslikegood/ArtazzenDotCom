"""Public gallery routes."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from starlette import status

from app import config, curation, seo, sidecars

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    sitemap_url = f"{config.SITE_URL.rstrip('/')}/sitemap.xml"
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        f"\nSitemap: {sitemap_url}\n"
    )


@router.get("/sitemap.xml")
async def sitemap_xml():
    site = config.SITE_URL.rstrip("/")
    root = ElementTree.Element(
        "urlset", {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    )

    def add_url(path: str, source_paths: list[Path] | None = None) -> None:
        url = ElementTree.SubElement(root, "url")
        ElementTree.SubElement(url, "loc").text = f"{site}{path}"
        lastmod = _latest_lastmod(source_paths or [])
        if lastmod:
            ElementTree.SubElement(url, "lastmod").text = lastmod

    add_url("/")
    add_url("/collections")

    registry_path = config.IMAGES_DIR / ".curation" / "collections.json"
    registry_mtime = [registry_path] if registry_path.is_file() else []
    series_registry_path = config.IMAGES_DIR / ".curation" / "series.json"
    series_registry_mtime = (
        [series_registry_path] if series_registry_path.is_file() else []
    )
    for entry in curation.load_collections().get("collections", []):
        slug = entry.get("id", "")
        if not isinstance(slug, str) or not slug:
            continue
        view = curation.collection_view(slug)
        if view is None:
            continue
        members = list(view.get("artworks", []))
        members.extend(
            artwork
            for series in view.get("series", [])
            for artwork in series.get("artworks", [])
        )
        # A collection with child pages is itself useful to crawlers even when
        # it has no direct or series artwork of its own.
        if not members and not view.get("children"):
            continue
        member_paths = registry_mtime[:] + series_registry_mtime[:]
        for member in members:
            name = member.get("name", "")
            if isinstance(name, str) and name:
                member_paths.extend(_artwork_paths(name))
        add_url(f"/collections/{quote(slug, safe='')}", member_paths)

    for item in sidecars.get_artwork_files(status_filter="approved"):
        name = item.get("name", "")
        if isinstance(name, str) and name:
            add_url(f"/artwork/{quote(name, safe='')}", _artwork_paths(name))

    xml = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml, media_type="application/xml")


def _artwork_paths(name: str) -> list[Path]:
    """Return existing image and sidecar paths for sitemap timestamps."""
    if not isinstance(name, str) or not name:
        return []
    try:
        image_path = sidecars._resolve_image_path(name)
    except (HTTPException, OSError, TypeError, ValueError):
        # Registry data is user-editable. A malformed filename must not make
        # the entire sitemap unavailable.
        return []
    paths = [image_path, image_path.with_suffix(".json")]
    return [path for path in paths if path.is_file()]


def _latest_lastmod(paths: list[Path]) -> str | None:
    """Format the newest available file mtime as sitemap UTC ISO-8601."""
    mtimes = []
    for path in paths:
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    if not mtimes:
        return None
    return datetime.fromtimestamp(max(mtimes), UTC).isoformat().replace(
        "+00:00", "Z"
    )


@router.get("/collections", response_class=HTMLResponse)
async def collections_index(request: Request):
    """Top-level collections grid."""
    collections = [
        {**entry, "cover_url": curation.collection_cover_url(entry)}
        for entry in curation.top_level_collections()
    ]
    context = seo.build_context(
        request,
        title=f"Collections — {config.GALLERY_TITLE}",
        description=f"Browse curated collections from {config.GALLERY_TITLE}.",
        breadcrumbs=[{"name": "Gallery", "path": "/"}, {"name": "Collections", "path": "/collections"}],
    )
    return config.templates.TemplateResponse(
        request,
        "collections_index.html",
        {**context, "collections": collections, "gallery_title": config.GALLERY_TITLE},
    )


@router.get("/collections/{slug}", response_class=HTMLResponse)
async def collection_detail(request: Request, slug: str):
    """A collection page: breadcrumb, sub-collections, series strips, grid."""
    view = curation.collection_view(slug)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found"
        )
    context = seo.build_context(
        request,
        title=f"{view['collection'].get('title', slug)} — Collections",
        description=view["collection"].get("description") or f"Explore the {slug} collection.",
        breadcrumbs=[{"name": "Gallery", "path": "/"}, {"name": "Collections", "path": "/collections"}, *[
            {"name": crumb["title"], "path": f"/collections/{quote(crumb['id'])}"}
            for crumb in view["breadcrumb"]
        ]],
    )
    return config.templates.TemplateResponse(
        request,
        "collection_detail.html",
        {
            "collection": view["collection"],
            "breadcrumb": view["breadcrumb"],
            "children": view["children"],
            "series_list": view["series"],
            "artworks": view["artworks"],
            "gallery_title": config.GALLERY_TITLE,
            **context,
        },
    )


@router.get("/artwork/{image_filename}", response_class=HTMLResponse)
async def artwork_detail(request: Request, image_filename: str):
    """
    Displays the details of a single piece of artwork.
    """
    filename = sidecars._sanitize_filename(image_filename)
    if not filename or not sidecars._allowed_image(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artwork not found"
        )

    image_path = sidecars._resolve_image_path(filename)
    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artwork not found"
        )

    metadata = sidecars._load_metadata(image_path)
    image_url = f"{config.IMAGES_URL_PREFIX}/{filename}"

    artwork_data = {
        "title": metadata.get("title", "Artwork"),
        "description": metadata.get("description", ""),
        "caption": metadata.get("caption", ""),
        "tags": metadata.get("tags", []),
        "artist": metadata.get("artist", ""),
        "copyright": metadata.get("copyright", ""),
        "collection": metadata.get("collection", ""),
        "image_url": image_url,
    }

    gallery = sidecars.get_artwork_files(status_filter="approved")
    filenames = [item["name"] for item in gallery]
    prev_artwork = None
    next_artwork = None
    if filename in filenames:
        idx = filenames.index(filename)
        if idx > 0:
            prev_artwork = filenames[idx - 1]
        if idx < len(filenames) - 1:
            next_artwork = filenames[idx + 1]

    context = seo.build_context(
        request,
        title=f"{artwork_data['title']} — Artazzen",
        description=artwork_data["description"] or f"View {artwork_data['title']} in the Artazzen gallery.",
        image_url=image_url,
        page_type="article",
        breadcrumbs=[
            {"name": "Gallery", "path": "/"},
            {"name": artwork_data["title"], "path": f"/artwork/{quote(filename)}"},
        ],
        structured_data={
            "@context": "https://schema.org",
            "@type": "VisualArtwork",
            "name": artwork_data["title"],
            "description": artwork_data["description"],
            "image": seo.absolute_url(image_url),
            "url": seo.absolute_url(f"/artwork/{quote(filename)}"),
            **({"creator": {"@type": "Person", "name": artwork_data["artist"]}} if artwork_data["artist"] else {}),
        },
    )
    return config.templates.TemplateResponse(
        request,
        "artwork_detail.html",
        {
            "artwork": artwork_data,
            "prev_artwork": prev_artwork,
            "next_artwork": next_artwork,
            "collections": curation.collections_for_image(filename),
            "series_memberships": curation.series_for_image(filename),
            **context,
        },
    )


@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    Handles requests to the root URL ('/').
    It gets the list of artwork files and renders the index.html template.
    """
    logger.info("Request received for root path ('/')")
    artwork_list = sidecars.get_artwork_files()

    # Data to pass to the HTML template
    context = {
        "request": request,  # Required by Jinja2Templates
        "artwork_files": artwork_list,
        "gallery_title": config.GALLERY_TITLE,
    }

    # Render the HTML template with the context data
    context.update(
        seo.build_context(
            request,
            title=config.GALLERY_TITLE,
            description=f"Explore curated artwork in the {config.GALLERY_TITLE}.",
            breadcrumbs=[{"name": "Gallery", "path": "/"}],
        )
    )
    return config.templates.TemplateResponse(request, "index.html", context)
