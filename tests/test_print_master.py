import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import print_master as pm
from app.config import IMAGES_DIR
from main import app
from test_main import _basic_auth_header

IMG_NAME = "pm_test_image.png"


@pytest.fixture()
def art_image():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGES_DIR / IMG_NAME
    Image.new("RGB", (40, 60), (120, 30, 200)).save(path, dpi=(72, 72))
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


def test_master_path_for():
    p = pm.master_path_for(Path("/x/images/foo.png"), Path("/x/images"))
    assert p == Path("/x/images/print_masters/foo_master300.png")


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


def test_upscale_config_defaults():
    from app import config

    cfg = config._get_ai_config()
    assert cfg["upscale_enabled"] is False  # opt-in by default
    assert cfg["upscale_scale"] == 4
    assert cfg["upscale_model"] == "general"


def test_print_master_endpoints(art_image, authed_client, monkeypatch):
    monkeypatch.setattr(pm, "available_backend", lambda: "torch")
    monkeypatch.setitem(pm._BACKENDS, "torch", _fake_backend_factory())

    resp = authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert resp.status_code == 200
    assert resp.json()["print_master"]["status"] == "processing"

    # TestClient runs the loop per-request; poll until the task lands.
    for _ in range(50):
        status_resp = authed_client.get(f"/admin/print-master/{IMG_NAME}")
        assert status_resp.status_code == 200
        state = status_resp.json()["print_master"]
        if state.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    assert state["status"] == "done"
    assert state["file"].startswith("print_masters/")
    assert state["url_path"].endswith(state["file"])

    # Sidecar carries the print_master block
    sidecar = json.loads((IMAGES_DIR / IMG_NAME).with_suffix(".json").read_text())
    assert sidecar["print_master"]["status"] == "done"

    # Second call without force is a no-op
    resp2 = authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert "already exists" in resp2.json()["message"]


def test_print_master_no_backend_returns_503(art_image, authed_client, monkeypatch):
    monkeypatch.setattr(pm, "available_backend", lambda: None)
    resp = authed_client.post(f"/admin/print-master/{IMG_NAME}")
    assert resp.status_code == 503
