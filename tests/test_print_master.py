import base64
import json
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import print_master as pm
from app.config import IMAGES_DIR
from main import app

IMG_NAME = "pm_test_image.png"
UPLOAD_NAME = "pm_upload_test.png"


def _basic_auth_header(username: str = "admin", password: str = "testpass") -> dict:
    """Authorization header for HTTP Basic Auth (local copy: test modules are
    not importable from each other under every pytest import mode)."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _png_bytes(size=(40, 60)) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", size, (120, 30, 200)).save(buf, format="PNG", dpi=(72, 72))
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clear_in_flight():
    pm._IN_FLIGHT.clear()
    yield
    pm._IN_FLIGHT.clear()


@pytest.fixture()
def art_image():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGES_DIR / IMG_NAME
    path.write_bytes(_png_bytes())
    sidecar = path.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "title": "PM Test",
                "description": "x",
                "ai_generated": False,
                "ai_details": {},
                "status": "approved",
                "detected_at": time.time(),
            }
        )
    )
    yield path
    for p in (path, sidecar):
        p.unlink(missing_ok=True)
    master = pm.master_path_for(path, IMAGES_DIR)
    master.unlink(missing_ok=True)
    trash = IMAGES_DIR / ".trash"
    for p in (trash / IMG_NAME, trash / Path(IMG_NAME).with_suffix(".json").name):
        p.unlink(missing_ok=True)
    shutil.rmtree(trash / pm.PRINT_MASTER_DIRNAME, ignore_errors=True)


@pytest.fixture()
def authed_client(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass")
    with TestClient(app) as c:
        c.headers.update(_basic_auth_header())
        yield c


def _fake_backend_factory(scale=4):
    def _fake(src: Path, scale_arg: int, model: str) -> Image.Image:
        with Image.open(src) as im:
            return Image.new(
                "RGB", (im.size[0] * scale_arg, im.size[1] * scale_arg), (1, 2, 3)
            )

    return _fake


def _wait_for_settled(client, name, tries=100):
    state = {}
    for _ in range(tries):
        status_resp = client.get(f"/admin/print-master/{name}")
        assert status_resp.status_code == 200
        state = status_resp.json()["print_master"]
        if state.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    return state


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def test_master_path_for():
    p = pm.master_path_for(Path("/x/images/foo.png"), Path("/x/images"))
    assert p == Path("/x/images/print_masters/foo_master300.png")


def test_master_url_path_is_admin_route_and_url_encoded():
    assert pm.master_url_path("a b.png") == "/admin/print-master/a%20b.png/file"


def test_env_float_never_raises(monkeypatch):
    monkeypatch.setenv("PM_TEST_TIMEOUT", "not-a-number")
    assert pm._env_float("PM_TEST_TIMEOUT", 300.0) == 300.0
    monkeypatch.setenv("PM_TEST_TIMEOUT", "12.5")
    assert pm._env_float("PM_TEST_TIMEOUT", 300.0) == 12.5
    monkeypatch.setenv("PM_TEST_TIMEOUT", "")
    assert pm._env_float("PM_TEST_TIMEOUT", 300.0) == 300.0


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.png", "image/png"),
        ("a.JPG", "image/jpeg"),
        ("a.webp", "image/webp"),
        ("a.tiff", "image/tiff"),
        ("a.bmp", "image/bmp"),
        ("a.unknownext", None),
    ],
)
def test_image_mime(name, expected):
    assert pm._image_mime(Path(name)) == expected


def test_generate_print_master_success(art_image, monkeypatch):
    monkeypatch.setitem(pm._BACKENDS, "torch", _fake_backend_factory())
    result = pm.generate_print_master(
        art_image, IMAGES_DIR, scale=4, model="general", backend="torch"
    )
    assert result["status"] == "done"
    assert result["width"] == 160 and result["height"] == 240
    master = IMAGES_DIR / result["file"]
    assert master.exists()
    with Image.open(master) as im:
        dpi = im.info.get("dpi")
    assert dpi and round(dpi[0]) == 300
    # Atomic save leaves no staging file behind.
    assert not list(master.parent.glob(".*.tmp"))


def test_generate_print_master_error_is_captured(art_image, monkeypatch):
    def _boom(src, scale, model):
        raise RuntimeError("backend exploded")

    monkeypatch.setitem(pm._BACKENDS, "torch", _boom)
    result = pm.generate_print_master(art_image, IMAGES_DIR, backend="torch")
    assert result["status"] == "error"
    assert "backend exploded" in result["error"]


def test_generate_print_master_no_backend(art_image, monkeypatch):
    monkeypatch.setattr(pm, "available_backend", lambda: None)
    result = pm.generate_print_master(art_image, IMAGES_DIR)
    assert result["status"] == "error"
    assert "No upscale backend" in result["error"]


def test_replicate_community_model_uses_versioned_predictions(art_image, monkeypatch):
    """The default model is not an official Replicate model, so the run must
    go through POST /predictions with a resolved version id."""
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
    monkeypatch.setattr(pm, "REPLICATE_VERSION", "")
    monkeypatch.setattr(pm, "_REPLICATE_VERSION_CACHE", {})
    monkeypatch.setattr(pm, "REPLICATE_POLL_SECONDS", 0)
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.url.path == f"/v1/models/{pm.REPLICATE_MODEL}":
            return httpx.Response(
                200, json={"is_official": False, "latest_version": {"id": "v123"}}
            )
        if request.url.path == "/v1/predictions" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "p1",
                    "status": "processing",
                    "urls": {"get": "https://api.replicate.com/v1/predictions/p1"},
                },
            )
        if request.url.path == "/v1/predictions/p1":
            return httpx.Response(
                200, json={"status": "succeeded", "output": "https://cdn/out.png"}
            )
        if request.url.host == "cdn":
            return httpx.Response(200, content=_png_bytes((160, 240)))
        return httpx.Response(404)

    def _client(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(pm, "httpx", SimpleNamespace(Client=_client))

    img = pm._upscale_replicate(art_image, 4, "general")
    assert img.size == (160, 240)

    create = next(b for m, p, b in seen if p == "/v1/predictions" and m == "POST")
    assert create["version"] == "v123"
    assert create["input"]["image"].startswith("data:image/png;base64,")
    assert create["input"]["scale"] == 4
    # The official-models endpoint must not be used for a community model.
    assert not any(p.endswith("/real-esrgan/predictions") for _, p, _ in seen)


def test_upscale_config_defaults():
    from app import config

    cfg = config._get_ai_config()
    assert cfg["upscale_enabled"] is False  # opt-in by default
    assert cfg["upscale_scale"] == 4
    assert cfg["upscale_model"] == "general"


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


def test_print_master_endpoints(art_image, authed_client, monkeypatch):
    monkeypatch.setattr(pm, "available_backend", lambda: "torch")
    monkeypatch.setitem(pm._BACKENDS, "torch", _fake_backend_factory())

    resp = authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert resp.status_code == 200
    assert resp.json()["print_master"]["status"] == "processing"

    state = _wait_for_settled(authed_client, IMG_NAME)
    assert state["status"] == "done"
    assert state["file"].startswith("print_masters/")
    assert state["backend"] == "torch"
    assert state["url_path"] == f"/admin/print-master/{IMG_NAME}/file"
    first_created = state["created"]

    # Sidecar carries the print_master block
    sidecar = json.loads((IMAGES_DIR / IMG_NAME).with_suffix(".json").read_text())
    assert sidecar["print_master"]["status"] == "done"

    # The master downloads through the authenticated admin route only ...
    dl = authed_client.get(state["url_path"])
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "image/png"
    assert "private" in dl.headers["cache-control"]
    assert len(dl.content) > 0
    anon = TestClient(app).get(state["url_path"])
    assert anon.status_code == 401
    # ... never from the public static mount.
    public = authed_client.get(f"/static/images/{state['file']}")
    assert public.status_code == 404
    assert (IMAGES_DIR / state["file"]).is_file()

    # Second call without force is a no-op
    resp2 = authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert "already exists" in resp2.json()["message"]

    # force=true regenerates
    time.sleep(0.05)
    resp3 = authed_client.post(
        f"/admin/print-master/{IMG_NAME}", data={"force": "true"}
    )
    assert resp3.json()["message"] == "Print master generation started"
    state = _wait_for_settled(authed_client, IMG_NAME)
    assert state["status"] == "done"
    assert state["created"] > first_created


def test_print_master_no_backend_returns_503(art_image, authed_client, monkeypatch):
    monkeypatch.setattr(pm, "available_backend", lambda: None)
    resp = authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert resp.status_code == 503


def test_print_master_in_flight_run_is_not_duplicated(
    art_image, authed_client, monkeypatch
):
    gate = threading.Event()
    calls: list[str] = []

    def _blocking(src: Path, scale: int, model: str) -> Image.Image:
        calls.append(src.name)
        gate.wait(timeout=10)
        return Image.new("RGB", (8, 8))

    monkeypatch.setattr(pm, "available_backend", lambda: "torch")
    monkeypatch.setitem(pm._BACKENDS, "torch", _blocking)
    try:
        first = authed_client.post(f"/admin/print-master/{IMG_NAME}")
        assert first.json()["message"] == "Print master generation started"
        for _ in range(50):
            if calls:
                break
            time.sleep(0.05)
        assert calls == [IMG_NAME]

        # Even force cannot start a second concurrent run for the same image.
        again = authed_client.post(
            f"/admin/print-master/{IMG_NAME}", data={"force": "true"}
        )
        assert again.json()["message"] == "Already processing"
        assert again.json()["print_master"]["status"] == "processing"

        status_resp = authed_client.get(f"/admin/print-master/{IMG_NAME}")
        assert status_resp.json()["print_master"]["status"] == "processing"
    finally:
        gate.set()

    state = _wait_for_settled(authed_client, IMG_NAME)
    assert state["status"] == "done"
    assert calls == [IMG_NAME]


def test_stale_processing_block_is_reported_as_error_and_rerunnable(
    art_image, authed_client, monkeypatch
):
    """A 'processing' block with no worker attached (app restarted mid-run)
    must not leave the UI disabled and polling forever."""
    sidecar = art_image.with_suffix(".json")
    data = json.loads(sidecar.read_text())
    data["print_master"] = {"status": "processing", "backend": "torch"}
    sidecar.write_text(json.dumps(data))

    status_resp = authed_client.get(f"/admin/print-master/{IMG_NAME}")
    reported = status_resp.json()["print_master"]
    assert reported["status"] == "error"
    assert reported["error"] == pm.INTERRUPTED_ERROR

    page = authed_client.get(f"/admin/review/{IMG_NAME}")
    assert page.status_code == 200
    assert pm.INTERRUPTED_ERROR in page.text
    assert "Generate print master" in page.text

    monkeypatch.setattr(pm, "available_backend", lambda: "torch")
    monkeypatch.setitem(pm._BACKENDS, "torch", _fake_backend_factory())
    resp = authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert resp.json()["message"] == "Print master generation started"
    assert _wait_for_settled(authed_client, IMG_NAME)["status"] == "done"


def test_upload_schedules_print_master_when_enabled(authed_client, monkeypatch):
    monkeypatch.setattr(
        pm,
        "_print_master_settings",
        lambda: {"enabled": True, "scale": 4, "model": "general", "backend": "torch"},
    )
    monkeypatch.setitem(pm._BACKENDS, "torch", _fake_backend_factory())
    path = IMAGES_DIR / UPLOAD_NAME
    try:
        resp = authed_client.post(
            "/admin/upload",
            files=[("files", (UPLOAD_NAME, _png_bytes(), "image/png"))],
        )
        assert resp.status_code == 200
        state = _wait_for_settled(authed_client, UPLOAD_NAME)
        assert state["status"] == "done"
        assert state["width"] == 160
    finally:
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)
        pm.master_path_for(path, IMAGES_DIR).unlink(missing_ok=True)


def test_soft_delete_moves_master_to_trash(art_image, authed_client, monkeypatch):
    monkeypatch.setattr(pm, "available_backend", lambda: "torch")
    monkeypatch.setitem(pm._BACKENDS, "torch", _fake_backend_factory())
    authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert _wait_for_settled(authed_client, IMG_NAME)["status"] == "done"
    master = pm.master_path_for(art_image, IMAGES_DIR)
    assert master.is_file()

    resp = authed_client.post(f"/admin/delete/{IMG_NAME}")
    assert resp.status_code == 200
    assert not master.exists()
    assert (IMAGES_DIR / ".trash" / pm.PRINT_MASTER_DIRNAME / master.name).is_file()
