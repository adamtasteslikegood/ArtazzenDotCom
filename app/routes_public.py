"""Public gallery routes."""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette import status

from app import config, sidecars

logger = logging.getLogger(__name__)

router = APIRouter()


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
