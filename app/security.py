"""Admin authentication and security headers."""

import os
import secrets
from pathlib import PurePosixPath
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Scope

from app import config, print_master

_http_basic = HTTPBasic(auto_error=False)

# Directories beneath a static mount that must never be served publicly.
# Print masters are the full-resolution sellable asset; they persist under
# IMAGES_DIR (the Railway volume) and are streamed only by the
# authenticated /admin/print-master/{image}/file route. Trash contents and
# curation registries are internal state rather than public gallery assets.
PRIVATE_STATIC_DIRS = frozenset(
    {print_master.PRINT_MASTER_DIRNAME, ".trash", ".curation"}
)


class _PublicStaticFiles(StaticFiles):
    """StaticFiles that refuses paths touching ``PRIVATE_STATIC_DIRS``."""

    async def get_response(self, path: str, scope: Scope):
        # ``path`` is already normalised by StaticFiles.get_path (no '..').
        if PRIVATE_STATIC_DIRS.intersection(PurePosixPath(path).parts):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return await super().get_response(path, scope)


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security-relevant HTTP response headers to every reply."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        return response


def _verify_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_http_basic),
) -> None:
    """FastAPI dependency that enforces HTTP Basic Auth on admin routes.

    Credentials are read from env vars ``ADMIN_USERNAME`` (default: ``admin``)
    and ``ADMIN_PASSWORD`` (required; admin access is disabled when unset).

    With ``auto_error=False`` on the :class:`HTTPBasic` scheme, this function
    receives ``None`` when the browser sends no credentials, allowing it to
    return a 503 when the password is not configured or a 401 prompting for
    credentials.
    """
    expected_password = os.getenv(config.ADMIN_PASSWORD_ENV, "")
    if not expected_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Admin interface is not configured. "
                f"Set the {config.ADMIN_PASSWORD_ENV} environment variable."
            ),
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Artwork Admin"'},
        )
    expected_username = os.getenv(config.ADMIN_USERNAME_ENV, "admin")
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        expected_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Artwork Admin"'},
        )
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin") or request.headers.get("referer", "")
        host = request.headers.get("host", "")
        if origin and host:
            # Compare the parsed authority, not a substring: a substring
            # check accepts e.g. https://example.com.attacker.tld for host
            # example.com.
            origin_host = urlparse(origin).netloc.lower()
            if origin_host != host.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cross-origin request rejected",
                )
