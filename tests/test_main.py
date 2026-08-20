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
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)

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
    monkeypatch.setattr(gallery_app.config, "IMPORT_ROOT", import_root)

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
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)

    sidecar = image_root / "safe.json"
    gallery_app._atomic_write_json(sidecar, {"title": "Safe"})
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"title": "Safe"}

    with pytest.raises(ValueError, match="outside an approved storage root"):
        gallery_app._atomic_write_json(tmp_path / "outside.json", {"secret": True})


def test_regenerate_metadata_does_not_expose_exception_details(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    (image_root / "safe.jpg").touch()
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)

    secret_detail = "/srv/private/secret-key.txt"

    def fail_metadata(*_args, **_kwargs):
        raise RuntimeError(secret_detail)

    monkeypatch.setattr(
        gallery_app.ai_metadata, "_populate_missing_metadata", fail_metadata
    )
    monkeypatch.setattr(
        gallery_app.watcher,
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
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)
    monkeypatch.setattr(
        gallery_app.watcher, "_refresh_pending_files", lambda _request: []
    )

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
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)
    monkeypatch.setattr(gallery_app.config, "IMPORT_ROOT", import_root)
    monkeypatch.setattr(
        gallery_app.watcher,
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

    monkeypatch.setattr(
        gallery_app.ai_metadata, "_get_openai_api_key", lambda: "test-key"
    )
    monkeypatch.setattr(
        gallery_app.ai_metadata,
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

    monkeypatch.setattr(
        gallery_app.ai_metadata, "_get_openai_api_key", lambda: "test-key"
    )
    monkeypatch.setattr(
        gallery_app.ai_metadata,
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
# OpenAI response parser hardening
# ---------------------------------------------------------------------------


def _patch_openai_transport(monkeypatch, payload):
    """Patch key/image/httpx so _request_openai_metadata sees `payload`."""

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        gallery_app.ai_metadata, "_get_openai_api_key", lambda: "test-key"
    )
    monkeypatch.setattr(
        gallery_app.ai_metadata,
        "_prepare_image_for_openai",
        lambda _path: "data:image/jpeg;base64,eA==",
    )
    monkeypatch.setattr(gallery_app.httpx, "Client", FakeClient)


def _output_text_payload(text: str) -> dict:
    return {
        "id": "resp_test",
        "status": "completed",
        "usage": {},
        "output": [{"content": [{"type": "output_text", "text": text}]}],
    }


def test_request_incomplete_response_returns_error(monkeypatch, tmp_path):
    """Truncated (incomplete) responses must not be parsed or stored."""
    payload = {
        "id": "resp_test",
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "usage": {},
        "output": [],
    }
    _patch_openai_transport(monkeypatch, payload)
    result = gallery_app._request_openai_metadata(tmp_path / "x.jpg", {}, ["title"])
    assert result["details"]["status"] == "error_incomplete"
    assert "max_output_tokens" in result["details"]["error"]
    assert result["title"] == ""


def test_request_fenced_json_parses(monkeypatch, tmp_path):
    """A markdown-fenced JSON reply is unwrapped and parsed."""
    text = '```json\n{"title": "Neon Fern"}\n```'
    _patch_openai_transport(monkeypatch, _output_text_payload(text))
    result = gallery_app._request_openai_metadata(tmp_path / "x.jpg", {}, ["title"])
    assert result["details"]["status"] == "success"
    assert result["title"] == "Neon Fern"


def test_request_double_encoded_json_parses(monkeypatch, tmp_path):
    """A JSON object double-encoded as a JSON string is decoded twice."""
    text = json.dumps(json.dumps({"title": "Neon Fern"}))
    _patch_openai_transport(monkeypatch, _output_text_payload(text))
    result = gallery_app._request_openai_metadata(tmp_path / "x.jpg", {}, ["title"])
    assert result["details"]["status"] == "success"
    assert result["title"] == "Neon Fern"


def test_request_non_dict_parse_errors(monkeypatch, tmp_path):
    """A parseable but non-object reply is a parse error, not a crash."""
    _patch_openai_transport(monkeypatch, _output_text_payload("[1, 2, 3]"))
    result = gallery_app._request_openai_metadata(tmp_path / "x.jpg", {}, ["title"])
    assert result["details"]["status"] == "error_parse"
    assert result["title"] == ""


def test_request_json_inside_title_unwrapped(monkeypatch, tmp_path):
    """A whole JSON object nested inside the title value is unwrapped."""
    nested = json.dumps({"title": "Clean Title", "description": "noise"})
    text = json.dumps({"title": nested})
    _patch_openai_transport(monkeypatch, _output_text_payload(text))
    result = gallery_app._request_openai_metadata(tmp_path / "x.jpg", {}, ["title"])
    assert result["details"]["status"] == "success"
    assert result["title"] == "Clean Title"


def test_request_empty_content_no_crash(monkeypatch, tmp_path):
    """Empty output must produce a parse error, not an AttributeError."""
    payload = {"id": "resp_test", "status": "completed", "usage": {}, "output": []}
    _patch_openai_transport(monkeypatch, payload)
    result = gallery_app._request_openai_metadata(tmp_path / "x.jpg", {}, ["title"])
    assert result["details"]["status"] == "error_parse"
    assert result["title"] == ""


def test_ai_config_raises_token_floor_for_gpt5(monkeypatch):
    """Reasoning models get a higher max_output_tokens floor."""
    monkeypatch.setattr(
        gallery_app.config,
        "runtime_ai_config",
        {"model": "gpt-5-mini", "max_output_tokens": 624},
    )
    cfg = gallery_app._get_ai_config()
    assert cfg["max_output_tokens"] == 1200


# ---------------------------------------------------------------------------
# Module split compatibility
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Point config persistence at a temp file so POSTing /admin/config
    never rewrites the repo's real ai_config.json during tests."""
    monkeypatch.setattr(gallery_app.config, "CONFIG_PATH", tmp_path / "ai_config.json")
    monkeypatch.setattr(gallery_app.config, "runtime_ai_config", {})


def test_admin_config_string_false_disables_ai(authed_client, isolated_config):
    """JSON string booleans like \"false\" must not enable via truthiness."""
    response = authed_client.post("/admin/config", json={"ai": {"enabled": "false"}})
    assert response.status_code == 200
    assert response.json()["ai"]["enabled"] is False


def test_admin_post_rejects_lookalike_origin(authed_client, isolated_config):
    """Origin whose host merely contains ours as a substring is rejected."""
    response = authed_client.post(
        "/admin/config",
        json={"ai": {}},
        headers={"Origin": "https://testserver.attacker.tld"},
    )
    assert response.status_code == 403


def test_admin_post_allows_same_origin(authed_client, isolated_config):
    response = authed_client.post(
        "/admin/config",
        json={"ai": {}},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Watcher event-loop offload (issue #69)
# ---------------------------------------------------------------------------


def test_pending_scans_are_serialized(monkeypatch):
    """Concurrent scans must not overlap (duplicate OpenAI calls)."""
    import threading
    import time as _time

    active = {"count": 0, "max": 0}
    guard = threading.Lock()

    def slow_scan():
        with guard:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        _time.sleep(0.05)
        with guard:
            active["count"] -= 1
        return []

    monkeypatch.setattr(gallery_app.watcher, "_scan_pending_files", slow_scan)
    threads = [
        threading.Thread(target=gallery_app.watcher.new_files_detected)
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert active["max"] == 1


async def test_get_pending_files_does_not_block_event_loop(monkeypatch):
    """The event loop must keep running while a slow scan is in flight.

    Before the fix, get_pending_files ran the scan inline on the loop, so
    the ticker below would record zero ticks until the scan finished.
    """
    import time as _time

    def slow_refresh(_request):
        _time.sleep(0.2)
        return ["scan-result"]

    monkeypatch.setattr(gallery_app.watcher, "_refresh_pending_files", slow_refresh)

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        result = await gallery_app.watcher.get_pending_files(None)
        ticks_at_return = ticks
    finally:
        task.cancel()

    assert result == ["scan-result"]
    assert ticks_at_return >= 5


def test_main_shim_exposes_compat_surface():
    """`import main` keeps exposing the pre-split public surface."""
    for name in ("app", "IMAGES_DIR", "_sanitize_filename", "templates"):
        assert hasattr(gallery_app, name), f"main no longer exposes {name}"


def test_all_routes_registered():
    """Every pre-split route path is still registered on main.app."""
    expected = {
        "/",
        "/artwork/{image_filename}",
        "/admin",
        "/admin/review",
        "/admin/review/{image_name}",
        "/admin/api/new-files",
        "/admin/api/collections",
        "/admin/config",
        "/admin/config/reset",
        "/admin/ai/regenerate",
        "/admin/upload",
        "/admin/import-path",
        "/admin/metadata/{image_name}",
        "/admin/unapprove/{image_name}",
        "/admin/delete/{image_name}",
    }
    registered = {getattr(r, "path", None) for r in app.routes}
    missing = expected - registered
    assert not missing, f"routes missing after split: {missing}"


# ---------------------------------------------------------------------------
# Collections API
# ---------------------------------------------------------------------------


def test_collections_requires_auth(client: TestClient):
    response = client.get("/admin/api/collections")
    assert response.status_code in (401, 503)


def test_collections_returns_distinct_values(authed_client, tmp_path, monkeypatch):
    image_root = tmp_path / "images"
    image_root.mkdir()
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)
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


def _regen_request(body_dict: dict) -> Request:
    """Build a fake POST request for regenerate_ai_metadata."""
    body = json.dumps(body_dict).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/ai/regenerate",
            "headers": [(b"content-type", b"application/json")],
            "app": app,
        },
        receive,
    )


def _write_regen_sidecar(image_root, name="regen_test"):
    img = image_root / f"{name}.jpg"
    img.touch()
    sidecar = image_root / f"{name}.json"
    sidecar.write_text(
        json.dumps(
            {
                "title": "Original Title",
                "description": "Original description",
                "caption": "",
                "tags": [],
                "ai_generated": False,
                "ai_fields": [],
                "status": "approved",
                "detected_at": 0,
                "ai_details": {},
            }
        )
    )
    return sidecar


def test_populate_persist_false_leaves_sidecar_unchanged(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    sidecar = _write_regen_sidecar(image_root)
    before = sidecar.read_bytes()
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)
    monkeypatch.setattr(
        gallery_app.ai_metadata,
        "_request_openai_metadata",
        lambda path, meta, fields: {
            "title": "AI Title",
            "details": {"status": "success"},
        },
    )

    meta = {"title": "", "description": "keep", "ai_details": {}}
    result = gallery_app._populate_missing_metadata(
        image_root / "regen_test.jpg", meta, only_fields=["title"], persist=False
    )

    assert result["title"] == "AI Title"
    assert sidecar.read_bytes() == before


def test_regenerate_force_failure_leaves_sidecar_unchanged(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    sidecar = _write_regen_sidecar(image_root)
    before = sidecar.read_bytes()
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)
    monkeypatch.setattr(
        gallery_app.ai_metadata,
        "_populate_missing_metadata",
        lambda path, meta, only_fields=None, persist=True: {
            **meta,
            "ai_details": {"status": "error_parse"},
        },
    )
    monkeypatch.setattr(gallery_app.watcher, "_refresh_pending_files", lambda _req: [])

    response = asyncio.run(
        gallery_app.regenerate_ai_metadata(
            _regen_request(
                {"images": ["regen_test.jpg"], "fields": ["title"], "force": True}
            ),
            _=None,
        )
    )
    payload = json.loads(response.body)

    assert payload["updated"] == []
    assert len(payload["errors"]) == 1
    assert "sidecar left unchanged" in payload["errors"][0]["error"]
    assert sidecar.read_bytes() == before


def test_regenerate_preview_returns_values_without_write(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    sidecar = _write_regen_sidecar(image_root)
    before = sidecar.read_bytes()
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)
    monkeypatch.setattr(
        gallery_app.ai_metadata,
        "_populate_missing_metadata",
        lambda path, meta, only_fields=None, persist=True: {
            **meta,
            "title": "AI Title",
            "ai_details": {"status": "success"},
        },
    )
    monkeypatch.setattr(gallery_app.watcher, "_refresh_pending_files", lambda _req: [])

    response = asyncio.run(
        gallery_app.regenerate_ai_metadata(
            _regen_request(
                {
                    "images": ["regen_test.jpg"],
                    "fields": ["title"],
                    "force": True,
                    "preview": True,
                }
            ),
            _=None,
        )
    )
    payload = json.loads(response.body)

    assert len(payload["updated"]) == 1
    assert payload["updated"][0]["preview"] is True
    assert payload["updated"][0]["metadata"]["title"] == "AI Title"
    assert sidecar.read_bytes() == before


def test_regenerate_success_writes_once(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    sidecar = _write_regen_sidecar(image_root)
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)
    monkeypatch.setattr(
        gallery_app.ai_metadata,
        "_populate_missing_metadata",
        lambda path, meta, only_fields=None, persist=True: {
            **meta,
            "title": "AI Title",
            "ai_details": {"status": "success"},
        },
    )
    monkeypatch.setattr(gallery_app.watcher, "_refresh_pending_files", lambda _req: [])

    writes = []
    orig_write = gallery_app._write_sidecar

    def counting_write(path, meta):
        writes.append(path.name)
        return orig_write(path, meta)

    monkeypatch.setattr(gallery_app.sidecars, "_write_sidecar", counting_write)

    response = asyncio.run(
        gallery_app.regenerate_ai_metadata(
            _regen_request(
                {"images": ["regen_test.jpg"], "fields": ["title"], "force": True}
            ),
            _=None,
        )
    )
    payload = json.loads(response.body)

    assert len(payload["updated"]) == 1
    assert writes == ["regen_test.jpg"]
    assert json.loads(sidecar.read_text())["title"] == "AI Title"


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
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)
    monkeypatch.setattr(
        gallery_app.ai_metadata,
        "_populate_missing_metadata",
        lambda path, meta, only_fields=None, persist=True: {
            **meta,
            "ai_details": {"status": "success"},
        },
    )
    monkeypatch.setattr(
        gallery_app.watcher,
        "_refresh_pending_files",
        lambda _req: [],
    )

    response = asyncio.run(
        gallery_app.regenerate_ai_metadata(
            _regen_request(
                {"images": ["field_test.jpg"], "fields": ["caption"], "force": True}
            ),
            _=None,
        )
    )
    payload = json.loads(response.body)

    assert len(payload["updated"]) == 1
    meta = payload["updated"][0]["metadata"]
    assert meta["title"] == "Keep"
    assert meta["description"] == "Keep"
    assert meta["caption"] == ""
    assert meta["tags"] == ["keep"]


# ---------------------------------------------------------------------------
# AI provenance through the preview-then-save flow
# ---------------------------------------------------------------------------


def _write_provenance_sidecar(image_root, name="prov_test"):
    img = image_root / f"{name}.jpg"
    img.touch()
    sidecar = image_root / f"{name}.json"
    sidecar.write_text(
        json.dumps(
            {
                "title": "Old",
                "description": "Old",
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
    return sidecar


def test_metadata_post_unions_ai_fields(authed_client, tmp_path, monkeypatch):
    image_root = tmp_path / "images"
    image_root.mkdir()
    sidecar = _write_provenance_sidecar(image_root)
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)

    response = authed_client.post(
        "/admin/metadata/prov_test.jpg",
        data={
            "title": "AI Title",
            "description": "Manually written",
            "ai_fields": "title,caption",
            "ai_generated": "true",
            "action": "save",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    assert saved["ai_fields"] == ["caption", "title"]
    assert saved["ai_generated"] is True


def test_metadata_post_drops_invalid_ai_fields(authed_client, tmp_path, monkeypatch):
    image_root = tmp_path / "images"
    image_root.mkdir()
    sidecar = _write_provenance_sidecar(image_root)
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)

    response = authed_client.post(
        "/admin/metadata/prov_test.jpg",
        data={
            "title": "AI Title",
            "ai_fields": "title,bogus,__proto__",
            "action": "save",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    assert saved["ai_fields"] == ["title"]


def test_review_page_has_preview_regen_and_hidden_ai_fields(authed_client):
    response = authed_client.get("/admin/review/test_image.jpg")
    assert response.status_code == 200
    assert "preview: true" in response.text
    assert 'id="ai_fields"' in response.text
    assert 'id="cancel-button"' in response.text


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
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)

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


def test_regenerate_rejects_unsupported_fields(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    (image_root / "x.jpg").touch()
    monkeypatch.setattr(gallery_app.config, "IMAGES_DIR", image_root)

    body = json.dumps({"images": ["x.jpg"], "fields": ["artist"]}).encode()

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
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(gallery_app.regenerate_ai_metadata(request, _=None))
    assert exc_info.value.status_code == 400
    assert "No supported fields" in exc_info.value.detail
