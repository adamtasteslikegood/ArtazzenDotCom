import asyncio
import base64
import io
import json
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import main as gallery_app
from main import ALLOWED_IMAGE_EXTENSIONS, IMAGES_DIR, app


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
    svg_content = (
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    )
    response = authed_client.post(
        "/admin/upload",
        files=[("files", ("evil.svg", io.BytesIO(svg_content), "image/svg+xml"))],
    )
    assert response.status_code == 200
    data = response.json()
    assert "evil.svg" in data.get("skipped", [])
    assert "evil.svg" not in data.get("saved", [])


# ---------------------------------------------------------------------------
# Filesystem containment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["../secret.jpg", "nested/secret.jpg", r"nested\secret.jpg", "..secret.jpg"],
)
def test_sanitize_filename_rejects_path_syntax(filename):
    assert gallery_app._sanitize_filename(filename) == ""


def test_resolve_image_path_rejects_escape_and_symlink(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.touch()
    (image_root / "escape.jpg").symlink_to(outside)
    monkeypatch.setattr(gallery_app, "IMAGES_DIR", image_root)

    assert gallery_app._resolve_image_path("safe.jpg") == image_root / "safe.jpg"
    for candidate in ("../outside.jpg", str(outside), "escape.jpg"):
        with pytest.raises(HTTPException) as exc_info:
            gallery_app._resolve_image_path(candidate)
        assert exc_info.value.status_code == 404


def test_select_import_files_uses_root_allowlist(monkeypatch, tmp_path):
    import_root = tmp_path / "imports"
    import_root.mkdir()
    nested = import_root / "batch"
    nested.mkdir()
    safe_file = nested / "safe.jpg"
    safe_file.touch()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.jpg"
    outside_file.touch()
    (import_root / "escape.jpg").symlink_to(outside_file)
    monkeypatch.setattr(gallery_app, "IMPORT_ROOT", import_root)

    assert gallery_app._select_import_files("batch") == [safe_file]
    assert gallery_app._select_import_files("batch/safe.jpg") == [safe_file]
    assert gallery_app._select_import_files(".") == [safe_file]
    for candidate in ("../outside", str(outside), "escape.jpg"):
        with pytest.raises(HTTPException) as exc_info:
            gallery_app._select_import_files(candidate)
        assert exc_info.value.status_code == 400


def test_atomic_json_write_rejects_unapproved_destination(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    monkeypatch.setattr(gallery_app, "IMAGES_DIR", image_root)

    sidecar = image_root / "safe.json"
    gallery_app._atomic_write_json(sidecar, {"title": "Safe"})
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"title": "Safe"}

    with pytest.raises(ValueError, match="outside an approved storage root"):
        gallery_app._atomic_write_json(tmp_path / "outside.json", {"secret": True})


def test_regenerate_metadata_does_not_expose_exception_details(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    (image_root / "safe.jpg").touch()
    monkeypatch.setattr(gallery_app, "IMAGES_DIR", image_root)

    secret_detail = "/srv/private/secret-key.txt"

    def fail_metadata(*_args, **_kwargs):
        raise RuntimeError(secret_detail)

    monkeypatch.setattr(gallery_app, "_populate_missing_metadata", fail_metadata)
    monkeypatch.setattr(
        gallery_app,
        "_refresh_pending_files",
        lambda _request: [{"name": "fresh-state.jpg"}],
    )
    body = json.dumps({"images": ["safe.jpg"]}).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/ai/regenerate",
            "headers": [(b"content-type", b"application/json")],
            "app": app,
        },
        receive,
    )
    response = asyncio.run(
        gallery_app.regenerate_ai_metadata(
            request,
            _=None,
        )
    )
    payload = json.loads(response.body)

    assert payload["errors"] == [
        {"name": "safe.jpg", "error": "Metadata regeneration failed"}
    ]
    assert payload["pending"] == [{"name": "fresh-state.jpg"}]
    assert secret_detail not in response.body.decode("utf-8")


def test_upload_without_size_attribute_uses_streaming_limit(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    monkeypatch.setattr(gallery_app, "IMAGES_DIR", image_root)
    monkeypatch.setattr(gallery_app, "_refresh_pending_files", lambda _request: [])

    class UploadWithoutSize:
        filename = "no-size.png"

        def __init__(self):
            self.file = io.BytesIO(b"small image payload")

        async def read(self, size):
            return self.file.read(size)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/upload",
            "headers": [],
            "app": app,
        }
    )
    response = asyncio.run(
        gallery_app.upload_images(
            request,
            files=[UploadWithoutSize()],
            _=None,
        )
    )
    payload = json.loads(response.body)

    assert payload["saved"] == ["no-size.png"]
    assert (image_root / "no-size.png").exists()


def test_import_returns_refreshed_pending_state(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    import_root = tmp_path / "imports"
    batch = import_root / "batch"
    batch.mkdir(parents=True)
    (batch / "imported.jpg").touch()
    monkeypatch.setattr(gallery_app, "IMAGES_DIR", image_root)
    monkeypatch.setattr(gallery_app, "IMPORT_ROOT", import_root)
    monkeypatch.setattr(
        gallery_app,
        "_refresh_pending_files",
        lambda _request: [{"name": "fresh-state.jpg"}],
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/import-path",
            "headers": [],
            "app": app,
        }
    )

    response = asyncio.run(
        gallery_app.import_from_path(
            request,
            path="batch",
            _=None,
        )
    )
    payload = json.loads(response.body)

    assert payload["copied"] == ["imported.jpg"]
    assert payload["pending"] == [{"name": "fresh-state.jpg"}]
    assert (image_root / "imported.jpg").exists()


def test_openai_http_error_details_are_not_exposed(monkeypatch, tmp_path):
    image_path = tmp_path / "safe.jpg"
    image_path.touch()
    secret_detail = "/srv/private/openai-response.txt"

    class FailingClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            request = gallery_app.httpx.Request(
                "POST", "https://api.openai.com/v1/responses"
            )
            raise gallery_app.httpx.ConnectError(secret_detail, request=request)

    monkeypatch.setattr(gallery_app, "_get_openai_api_key", lambda: "test-key")
    monkeypatch.setattr(
        gallery_app,
        "_prepare_image_for_openai",
        lambda _path: "data:image/jpeg;base64,eA==",
    )
    monkeypatch.setattr(gallery_app.httpx, "Client", FailingClient)

    result = gallery_app._request_openai_metadata(
        image_path, {}, ["title", "description"]
    )
    details = result["details"]

    assert details["error"] == "OpenAI metadata request failed."
    assert details["error_body"] == ""
    assert secret_detail not in json.dumps(result)


def test_openai_parse_error_details_are_not_exposed(monkeypatch, tmp_path):
    image_path = tmp_path / "safe.jpg"
    image_path.touch()
    secret_detail = "/srv/private/invalid-response.txt"

    class InvalidJsonResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "response-id",
                "model": "test-model",
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": f"not-json {secret_detail}"}
                        ]
                    }
                ],
            }

    class InvalidJsonClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            return InvalidJsonResponse()

    monkeypatch.setattr(gallery_app, "_get_openai_api_key", lambda: "test-key")
    monkeypatch.setattr(
        gallery_app,
        "_prepare_image_for_openai",
        lambda _path: "data:image/jpeg;base64,eA==",
    )
    monkeypatch.setattr(gallery_app.httpx, "Client", InvalidJsonClient)

    result = gallery_app._request_openai_metadata(
        image_path, {}, ["title", "description"]
    )

    assert result["details"]["error"] == "OpenAI metadata response could not be parsed."
    assert secret_detail not in result["details"]["error"]


# ---------------------------------------------------------------------------
# Collections API
# ---------------------------------------------------------------------------


def test_collections_requires_auth(client: TestClient):
    response = client.get("/admin/api/collections")
    assert response.status_code in (401, 503)


def test_collections_returns_distinct_values(authed_client, tmp_path, monkeypatch):
    image_root = tmp_path / "images"
    image_root.mkdir()
    monkeypatch.setattr(gallery_app, "IMAGES_DIR", image_root)
    (image_root / "a.json").write_text(json.dumps({"collection": "Flora"}))
    (image_root / "b.json").write_text(json.dumps({"collection": "Flora"}))
    (image_root / "c.json").write_text(json.dumps({"collection": "Fauna"}))
    (image_root / "d.json").write_text(json.dumps({"collection": ""}))

    response = authed_client.get("/admin/api/collections")
    assert response.status_code == 200
    data = response.json()
    assert data["collections"] == ["Fauna", "Flora"]


# ---------------------------------------------------------------------------
# Per-field regeneration
# ---------------------------------------------------------------------------


def test_regenerate_with_fields_blanks_only_targeted(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    img = image_root / "field_test.jpg"
    img.touch()
    sidecar = image_root / "field_test.json"
    sidecar.write_text(
        json.dumps(
            {
                "title": "Keep",
                "description": "Keep",
                "caption": "Keep",
                "tags": ["keep"],
                "ai_generated": False,
                "ai_fields": [],
                "status": "pending",
                "detected_at": 0,
                "ai_details": {},
            }
        )
    )
    monkeypatch.setattr(gallery_app, "IMAGES_DIR", image_root)
    monkeypatch.setattr(
        gallery_app,
        "_populate_missing_metadata",
        lambda path, meta, only_fields=None: meta,
    )
    monkeypatch.setattr(
        gallery_app,
        "_refresh_pending_files",
        lambda _req: [],
    )

    body = json.dumps(
        {"images": ["field_test.jpg"], "fields": ["caption"], "force": True}
    ).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/ai/regenerate",
            "headers": [(b"content-type", b"application/json")],
            "app": app,
        },
        receive,
    )
    response = asyncio.run(gallery_app.regenerate_ai_metadata(request, _=None))
    payload = json.loads(response.body)

    assert len(payload["updated"]) == 1
    meta = payload["updated"][0]["metadata"]
    assert meta["title"] == "Keep"
    assert meta["description"] == "Keep"
    assert meta["caption"] == ""
    assert meta["tags"] == ["keep"]


# ---------------------------------------------------------------------------
# Metadata POST persists v2 fields
# ---------------------------------------------------------------------------


def test_metadata_post_persists_v2_fields(authed_client, tmp_path, monkeypatch):
    image_root = tmp_path / "images"
    image_root.mkdir()
    img = image_root / "v2test.jpg"
    img.touch()
    sidecar = image_root / "v2test.json"
    sidecar.write_text(
        json.dumps(
            {
                "title": "",
                "description": "",
                "caption": "",
                "tags": [],
                "artist": "",
                "copyright": "",
                "collection": "",
                "ai_generated": False,
                "ai_fields": [],
                "ai_details": {},
                "status": "pending",
                "detected_at": 0,
            }
        )
    )
    monkeypatch.setattr(gallery_app, "IMAGES_DIR", image_root)

    response = authed_client.post(
        "/admin/metadata/v2test.jpg",
        data={
            "title": "Bloom",
            "description": "A flower",
            "caption": "Delicate petals",
            "tags": "botanical, flora",
            "artist": "Ada",
            "copyright": "2026",
            "collection": "Garden",
            "action": "save",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    assert saved["caption"] == "Delicate petals"
    assert saved["tags"] == ["botanical", "flora"]
    assert saved["artist"] == "Ada"
    assert saved["copyright"] == "2026"
    assert saved["collection"] == "Garden"
    assert saved["status"] == "approved"
