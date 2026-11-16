"""HTTP Basic auth against the gallery's admin credentials.

A copy of the gallery's ``app/security.py::_verify_admin`` so both services
accept the same login: constant-time comparison, 503 when no password is
configured, and a same-origin check on mutating requests.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware

_http_basic = HTTPBasic(auto_error=False)
_REALM = {"WWW-Authenticate": 'Basic realm="Artwork Admin"'}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add the gallery's security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        return response


def verify_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_http_basic),
) -> None:
    settings = request.app.state.settings
    expected_password = settings.admin_password
    if not expected_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upscaler is not configured. Set ADMIN_PASSWORD.",
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers=_REALM,
        )
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.admin_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers=_REALM,
        )
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin") or request.headers.get("referer", "")
        host = request.headers.get("host", "")
        if origin and host and urlparse(origin).netloc.lower() != host.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-origin request rejected",
            )
