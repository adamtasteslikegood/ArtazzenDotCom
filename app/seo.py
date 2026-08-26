"""Helpers for consistent metadata on public pages."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from fastapi import Request

from app import config


def absolute_url(path: str) -> str:
    """Return an absolute URL rooted at the configured canonical origin."""
    return urljoin(f"{config.SITE_URL}/", path.lstrip("/"))


def build_context(
    request: Request,
    *,
    title: str,
    description: str,
    image_url: str | None = None,
    page_type: str = "website",
    breadcrumbs: list[dict[str, str]] | None = None,
    structured_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build values consumed by the shared SEO template blocks."""
    canonical = absolute_url(request.url.path)
    data: list[dict[str, Any]] = []
    if structured_data:
        data.append(structured_data)
    if breadcrumbs:
        data.append(
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": index,
                        "name": crumb["name"],
                        "item": absolute_url(crumb["path"]),
                    }
                    for index, crumb in enumerate(breadcrumbs, 1)
                ],
            }
        )
    return {
        "seo_title": title,
        "seo_description": description[:160],
        "seo_canonical": canonical,
        "seo_image": absolute_url(image_url) if image_url else None,
        "seo_type": page_type,
        "seo_json_ld": data,
    }
