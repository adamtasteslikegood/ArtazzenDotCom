import base64
import io
import json
import os

import pytest
from fastapi.testclient import TestClient

from main import app, IMAGES_DIR, ALLOWED_IMAGE_EXTENSIONS


def _basic_auth_header(username: str = "admin", password: str = "testpass") -> dict:
    """Return an Authorization header dict for HTTP Basic Auth."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(scope="function")
def client():
    """Create a TestClient instance for the app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def authed_client(monkeypatch):
    """TestClient with ADMIN_PASSWORD set and correct auth headers baked in."""
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass")
    with TestClient(app) as c:
        c.headers.update(_basic_auth_header())
        yield c


def setup_function(function):
    """Create a dummy image file for testing."""
    if not IMAGES_DIR.exists():
        IMAGES_DIR.mkdir(parents=True)
    dummy_image_path = IMAGES_DIR / "test_image.jpg"
    if not dummy_image_path.exists():
        dummy_image_path.touch()

    # Create a dummy sidecar file
    dummy_sidecar_path = IMAGES_DIR / "test_image.json"
    if not dummy_sidecar_path.exists():
        with open(dummy_sidecar_path, "w") as f:
            f.write('{"title": "Test Image", "description": "A test image."}')


def teardown_function(function):
    """Remove dummy files after tests."""
    for name in ("test_image.jpg", "test_image.json", "upload_test.png", "evil.svg"):
        p = IMAGES_DIR / name
        if p.exists():
            os.remove(p)
        # Remove the auto-generated sidecar only for image files (not .json files)
        if p.suffix.lower() != ".json":
            sidecar = p.with_suffix(".json")
            if sidecar.exists():
                os.remove(sidecar)


# ---------------------------------------------------------------------------
# Public gallery routes
# ---------------------------------------------------------------------------

def test_read_root(client: TestClient):
    """Test the root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Artwork Gallery" in response.text


def test_artwork_detail(client: TestClient):
    """Test the artwork detail endpoint."""
    response = client.get("/artwork/test_image.jpg")
    assert response.status_code == 200
    assert "Test Image" in response.text


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

def test_security_headers_on_root(client: TestClient):
    """Ensure security headers are present on public responses."""
    response = client.get("/")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


# ---------------------------------------------------------------------------
# Admin authentication
# ---------------------------------------------------------------------------

def test_admin_requires_auth(client: TestClient):
    """Admin routes must reject unauthenticated requests."""
    response = client.get("/admin")
    # 401 when a password is configured; 503 when no password is set
    assert response.status_code in (401, 503)


def test_admin_wrong_password(monkeypatch):
    """Admin routes must reject incorrect credentials."""
    monkeypatch.setenv("ADMIN_PASSWORD", "correctpass")
    with TestClient(app) as c:
        response = c.get("/admin", headers=_basic_auth_header(password="wrongpass"))
    assert response.status_code == 401


def test_admin_correct_credentials(authed_client):
    """Admin routes must accept correct credentials."""
    response = authed_client.get("/admin")
    assert response.status_code == 200


def test_admin_api_new_files_requires_auth(client: TestClient):
    """API endpoint also requires auth."""
    response = client.get("/admin/api/new-files")
    assert response.status_code in (401, 503)


# ---------------------------------------------------------------------------
# SVG not accepted
# ---------------------------------------------------------------------------

def test_svg_not_in_allowed_extensions():
    """.svg must not be in ALLOWED_IMAGE_EXTENSIONS."""
    assert ".svg" not in ALLOWED_IMAGE_EXTENSIONS


def test_upload_rejects_svg(authed_client):
    """Upload endpoint must skip SVG files."""
    svg_content = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    response = authed_client.post(
        "/admin/upload",
        files=[("files", ("evil.svg", io.BytesIO(svg_content), "image/svg+xml"))],
    )
    assert response.status_code == 200
    data = response.json()
    assert "evil.svg" in data.get("skipped", [])
    assert "evil.svg" not in data.get("saved", [])
