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

from app import config, routes_admin, sidecars
from app import print_master as pm
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
    config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = config.IMAGES_DIR / IMG_NAME
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
    master = pm.master_path_for(path, config.IMAGES_DIR)
    master.unlink(missing_ok=True)
    trash = config.IMAGES_DIR / ".trash"
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
        art_image, config.IMAGES_DIR, scale=4, model="general", backend="torch"
    )
    assert result["status"] == "done"
    assert result["width"] == 160 and result["height"] == 240
    master = config.IMAGES_DIR / result["file"]
    assert master.exists()
    with Image.open(master) as im:
        dpi = im.info.get("dpi")
    assert dpi and round(dpi[0]) == 300
    # Atomic save leaves no staging file behind.
    assert not list(master.parent.glob(".*.tmp"))


def test_torch_backend_reports_missing_weights_clearly(
    art_image, tmp_path, monkeypatch
):
    monkeypatch.setenv("UPSCALE_MODELS_DIR", str(tmp_path))
    with pytest.raises(RuntimeError) as excinfo:
        pm._upscale_torch(art_image, 4, "general")
    message = str(excinfo.value)
    assert "RealESRGAN_x4plus.pth" in message
    assert "UPSCALE_MODELS_DIR" in message


def test_generate_print_master_error_is_captured(art_image, monkeypatch):
    def _boom(src, scale, model):
        raise RuntimeError("backend exploded")

    monkeypatch.setitem(pm._BACKENDS, "torch", _boom)
    result = pm.generate_print_master(art_image, config.IMAGES_DIR, backend="torch")
    assert result["status"] == "error"
    assert "backend exploded" in result["error"]


def test_generate_print_master_no_backend(art_image, monkeypatch):
    monkeypatch.setattr(pm, "available_backend", lambda: None)
    result = pm.generate_print_master(art_image, config.IMAGES_DIR)
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
    seen_auth: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        seen_auth.append((request.url.host, request.headers.get("authorization")))
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
    # Replicate API calls are authenticated, but the provider-controlled
    # output URL may use third-party storage and must never receive the token.
    assert any(
        host == "api.replicate.com" and auth == "Bearer r8_test"
        for host, auth in seen_auth
    )
    assert any(host == "cdn" and auth is None for host, auth in seen_auth)


def test_replicate_rejects_unsupported_digital_model(art_image, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
    with pytest.raises(RuntimeError, match="supports only the general model"):
        pm._upscale_replicate(art_image, 4, "digital")


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
    sidecar = json.loads(
        (config.IMAGES_DIR / IMG_NAME).with_suffix(".json").read_text()
    )
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
    assert (config.IMAGES_DIR / state["file"]).is_file()

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


def test_initial_print_master_link_honors_root_path(art_image, monkeypatch):
    sidecar = art_image.with_suffix(".json")
    data = json.loads(sidecar.read_text())
    data["print_master"] = {
        "status": "done",
        "url_path": f"/admin/print-master/{IMG_NAME}/file",
        "width": 160,
        "height": 240,
        "dpi": 300,
    }
    sidecars._write_sidecar(art_image, data)

    monkeypatch.setenv("ADMIN_PASSWORD", "testpass")
    with TestClient(app, root_path="/gallery") as client:
        client.headers.update(_basic_auth_header())
        page = client.get(f"/admin/review/{IMG_NAME}")

    assert page.status_code == 200
    assert f'href="/gallery/admin/print-master/{IMG_NAME}/file"' in page.text


def test_print_master_no_backend_returns_503(art_image, authed_client, monkeypatch):
    monkeypatch.setattr(pm, "available_backend", lambda: None)
    resp = authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert resp.status_code == 503


def test_print_master_in_flight_run_is_not_duplicated(
    art_image, authed_client, monkeypatch, tmp_path
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

        # Deleting the source while its master is being written could orphan
        # the task output or recreate a master for a deleted image.
        delete = authed_client.post(f"/admin/delete/{IMG_NAME}")
        assert delete.status_code == 409
        assert art_image.is_file()

        original_bytes = art_image.read_bytes()
        replacement = authed_client.post(
            "/admin/upload?force=true",
            files=[("files", (IMG_NAME, _png_bytes((20, 30)), "image/png"))],
        )
        assert replacement.status_code == 200
        assert IMG_NAME in replacement.json()["skipped"]
        assert art_image.read_bytes() == original_bytes

        import_source = tmp_path / IMG_NAME
        import_source.write_bytes(_png_bytes((10, 15)))
        monkeypatch.setattr(config, "IMPORT_ROOT", tmp_path)
        imported = authed_client.post(
            "/admin/import-path?force=true", data={"path": IMG_NAME}
        )
        assert imported.status_code == 200
        assert IMG_NAME in imported.json()["skipped"]
        assert art_image.read_bytes() == original_bytes
    finally:
        gate.set()

    state = _wait_for_settled(authed_client, IMG_NAME)
    assert state["status"] == "done"
    assert calls == [IMG_NAME]


def test_task_failure_persists_error_block(art_image, authed_client, monkeypatch):
    """A failure outside generate_print_master (which never raises) must not
    leave the sidecar on 'processing' or surface as an unretrieved task
    exception; it lands as an error block the UI can show."""
    monkeypatch.setattr(pm, "available_backend", lambda: "torch")

    def _boom(*args, **kwargs):
        raise RuntimeError("scheduling exploded")

    monkeypatch.setattr(pm, "generate_print_master", _boom)
    resp = authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert resp.status_code == 200
    state = _wait_for_settled(authed_client, IMG_NAME)
    assert state["status"] == "error"
    assert "scheduling exploded" in state["error"]
    sidecar = json.loads(art_image.with_suffix(".json").read_text())
    assert sidecar["print_master"]["status"] == "error"
    assert not pm.is_in_flight(art_image)


def test_sidecar_upload_during_run_keeps_both_writers(
    art_image, authed_client, monkeypatch
):
    """A .json sidecar upload while a master is generating goes through the
    sidecar mutation lock, so neither the uploaded fields nor the task's
    print_master block is lost."""
    gate = threading.Event()

    def _blocking(src: Path, scale: int, model: str) -> Image.Image:
        gate.wait(timeout=10)
        return Image.new("RGB", (8, 8))

    monkeypatch.setattr(pm, "available_backend", lambda: "torch")
    monkeypatch.setitem(pm._BACKENDS, "torch", _blocking)
    try:
        authed_client.post(f"/admin/print-master/{IMG_NAME}")
        uploaded = {
            "title": "Uploaded while processing",
            "description": "x",
            "ai_generated": False,
            "ai_details": {},
            "status": "approved",
            "detected_at": time.time(),
        }
        resp = authed_client.post(
            "/admin/upload?force=true",
            files=[
                (
                    "files",
                    (
                        Path(IMG_NAME).with_suffix(".json").name,
                        json.dumps(uploaded).encode(),
                        "application/json",
                    ),
                )
            ],
        )
        assert resp.status_code == 200
    finally:
        gate.set()

    assert _wait_for_settled(authed_client, IMG_NAME)["status"] == "done"
    sidecar = json.loads(art_image.with_suffix(".json").read_text())
    assert sidecar["title"] == "Uploaded while processing"
    assert sidecar["print_master"]["status"] == "done"


def test_stale_processing_block_is_reported_as_error_and_rerunnable(
    art_image, authed_client, monkeypatch
):
    """A 'processing' block with no worker attached (app restarted mid-run)
    must not leave the UI disabled and polling forever."""
    # Write under the mutation lock like every real writer does: the
    # watcher's startup scan runs a locked read-merge-write (AI populate)
    # for this image concurrently, and an unlocked write can be lost to it.
    with sidecars.sidecar_mutation_lock.held():
        data = sidecars._load_metadata(art_image)
        data["print_master"] = {"status": "processing", "backend": "torch"}
        sidecars._write_sidecar(art_image, data)

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
    path = config.IMAGES_DIR / UPLOAD_NAME
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
        pm.master_path_for(path, config.IMAGES_DIR).unlink(missing_ok=True)


def test_soft_delete_moves_master_to_trash(art_image, authed_client, monkeypatch):
    monkeypatch.setattr(pm, "available_backend", lambda: "torch")
    monkeypatch.setitem(pm._BACKENDS, "torch", _fake_backend_factory())
    authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert _wait_for_settled(authed_client, IMG_NAME)["status"] == "done"
    master = pm.master_path_for(art_image, config.IMAGES_DIR)
    assert master.is_file()

    resp = authed_client.post(f"/admin/delete/{IMG_NAME}")
    assert resp.status_code == 200
    assert not master.exists()
    assert (
        config.IMAGES_DIR / ".trash" / pm.PRINT_MASTER_DIRNAME / master.name
    ).is_file()


def test_soft_delete_preserves_existing_trash_master(
    art_image, authed_client, monkeypatch
):
    monkeypatch.setattr(pm, "available_backend", lambda: "torch")
    monkeypatch.setitem(pm._BACKENDS, "torch", _fake_backend_factory())
    authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert _wait_for_settled(authed_client, IMG_NAME)["status"] == "done"

    trash = config.IMAGES_DIR / ".trash"
    trash_masters = trash / pm.PRINT_MASTER_DIRNAME
    trash_masters.mkdir(parents=True, exist_ok=True)
    old_image = trash / IMG_NAME
    old_master = trash_masters / pm.master_path_for(art_image, config.IMAGES_DIR).name
    old_image.write_bytes(b"older image")
    old_master.write_bytes(b"older master")
    renamed_image = None
    renamed_sidecar = None
    renamed_master = None
    try:
        resp = authed_client.post(f"/admin/delete/{IMG_NAME}")
        assert resp.status_code == 200
        assert old_image.read_bytes() == b"older image"
        assert old_master.read_bytes() == b"older master"

        candidates = list(trash.glob(f"{art_image.stem}_*{art_image.suffix}"))
        assert len(candidates) == 1
        renamed_image = candidates[0]
        renamed_sidecar = renamed_image.with_suffix(".json")
        renamed_master = trash_masters / pm.master_path_for(renamed_image, trash).name
        assert renamed_sidecar.is_file()
        assert renamed_master.is_file()
    finally:
        for path in (renamed_image, renamed_sidecar, renamed_master):
            if path is not None:
                path.unlink(missing_ok=True)


def test_incoming_sidecar_files_take_mutation_lock(tmp_path, monkeypatch):
    events: list[str] = []

    class Held:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, exc_type, exc_value, traceback):
            events.append("exit")

    class TrackingLock:
        def held(self):
            return Held()

    monkeypatch.setattr(sidecars, "sidecar_mutation_lock", TrackingLock())
    destination = tmp_path / "artwork.json"

    staged = tmp_path / "staged.upload"
    staged.write_text('{"source": "upload"}')
    routes_admin._install_incoming_file(staged, destination, move=True)
    assert not staged.exists()
    assert json.loads(destination.read_text()) == {"source": "upload"}

    imported = tmp_path / "import.json"
    imported.write_text('{"source": "import"}')
    routes_admin._install_incoming_file(imported, destination, move=False)
    assert imported.exists()
    assert json.loads(destination.read_text()) == {"source": "import"}
    assert events == ["enter", "exit", "enter", "exit"]
