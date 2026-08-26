"""Public gallery routes."""

import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from starlette import status

from app import config, curation, sidecars

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        f"\nSitemap: {config.SITE_URL}/sitemap.xml\n"
    )


@router.get("/sitemap.xml")
async def sitemap_xml():
    site = config.SITE_URL
    urls = [f"  <url><loc>{site}/</loc></url>"]
    urls.append(f"  <url><loc>{site}/collections</loc></url>")

    for entry in curation.load_collections().get("collections", []):
        slug = entry.get("id", "")
        if slug:
            urls.append(f"  <url><loc>{site}/collections/{quote(slug)}</loc></url>")

    for item in sidecars.get_artwork_files(status_filter="approved"):
        name = item.get("name", "")
        if name:
            urls.append(f"  <url><loc>{site}/artwork/{quote(name)}</loc></url>")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/collections", response_class=HTMLResponse)
async def collections_index(request: Request):
    """Top-level collections grid."""
    collections = [
        {**entry, "cover_url": curation.collection_cover_url(entry)}
        for entry in curation.top_level_collections()
    ]
    return config.templates.TemplateResponse(
        request,
        "collections_index.html",
        {"collections": collections, "gallery_title": config.GALLERY_TITLE},
    )


@router.get("/collections/{slug}", response_class=HTMLResponse)
async def collection_detail(request: Request, slug: str):
    """A collection page: breadcrumb, sub-collections, series strips, grid."""
    view = curation.collection_view(slug)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found"
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

    return config.templates.TemplateResponse(
        request,
        "artwork_detail.html",
        {
            "artwork": artwork_data,
            "prev_artwork": prev_artwork,
            "next_artwork": next_artwork,
            "collections": curation.collections_for_image(filename),
            "series_memberships": curation.series_for_image(filename),
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
    return config.templates.TemplateResponse(request, "index.html", context)
