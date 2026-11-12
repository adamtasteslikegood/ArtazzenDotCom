import base64
import io
from pathlib import Path

import boto3
import httpx
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from PIL import Image
from upscaler.app import create_app
from upscaler.config import Settings
from upscaler.sources import GalleryClient
from upscaler.storage import Storage

BUCKET = "test-bucket"


def png_bytes(size=(64, 48), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def auth_header(user="admin", password="testpass") -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    root = tmp_path / "imports"
    root.mkdir()
    return Settings(
        admin_password="testpass",
        gallery_url="http://gallery.internal",
        bucket=BUCKET,
        region="us-east-1",
        bucket_prefix="dev/",
        import_root=root,
        max_upload_mb=1,
        max_megapixels=1,
    )


@pytest.fixture
def storage(settings):
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        # Built the production way, so the signing/addressing config is tested.
        yield Storage.from_settings(settings)


class FakeGallery:
    """Serves the two gallery admin endpoints the upscaler uses."""

    def __init__(self):
        self.files = {
            "pending.png": png_bytes(),
            "approved.png": png_bytes(color=(1, 2, 3)),
        }
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != auth_header()["Authorization"]:
            return httpx.Response(401)
        path = request.url.path
        if path == "/admin/api/new-files":
            return httpx.Response(
                200,
                json={
                    "pending": [{"name": "pending.png", "metadata": {"title": "P"}}],
                    "gallery": [{"name": "approved.png", "title": "A"}],
                },
            )
        prefix = "/admin/image/"
        if path.startswith(prefix):
            data = self.files.get(path[len(prefix) :])
            if data is None:
                return httpx.Response(404)
            return httpx.Response(
                200, content=data, headers={"content-type": "image/png"}
            )
        return httpx.Response(404)


@pytest.fixture
def fake_gallery() -> FakeGallery:
    return FakeGallery()


@pytest.fixture
def client(settings, storage, fake_gallery):
    gallery = GalleryClient(settings, transport=httpx.MockTransport(fake_gallery))
    app = create_app(settings=settings, storage=storage, gallery=gallery)
    with TestClient(app) as c:
        c.headers.update(auth_header())
        yield c
