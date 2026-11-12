import base64
import io
import json
from pathlib import Path
from urllib.parse import urlparse

import boto3
import httpx
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from PIL import Image
from upscaler.app import create_app
from upscaler.config import Settings
from upscaler.replicate import ReplicateClient
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
        replicate_api_token="r8_test",
        poll_seconds=0,
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


class FakeReplicate:
    """Replicate's API plus its output host.

    The "upscale" fetches the presigned input from the mocked bucket and
    resizes it by the requested scale, so crops and sizes are checked for real.
    """

    API = "https://api.replicate.com/v1"

    def __init__(self, storage):
        self.storage = storage
        self.requests: list[httpx.Request] = []
        self.predictions: dict[str, dict] = {}
        self.polls_before_done = 1
        self.fail_with = ""
        self.created = 0

    def _prediction(self, pid):
        return {
            "id": pid,
            "status": "starting",
            "urls": {
                "get": f"{self.API}/predictions/{pid}",
                "cancel": f"{self.API}/predictions/{pid}/cancel",
            },
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if request.url.host == "replicate.delivery":
            pid = request.url.path.split("/")[1]
            return httpx.Response(200, content=self.predictions[pid]["png"])
        if request.headers.get("authorization") != "Bearer r8_test":
            return httpx.Response(401, json={"detail": "bad token"})
        if url == f"{self.API}/models/nightmareai/real-esrgan":
            return httpx.Response(
                200, json={"is_official": False, "latest_version": {"id": "v123"}}
            )
        if url == f"{self.API}/predictions" and request.method == "POST":
            body = json.loads(request.content)
            assert body["version"] == "v123"
            self.created += 1
            pid = f"p{self.created}"
            self.predictions[pid] = {
                "input": body["input"],
                "polls": 0,
                "status": "starting",
            }
            return httpx.Response(201, json=self._prediction(pid))
        if url.endswith("/cancel"):
            pid = url.split("/")[-2]
            self.predictions[pid]["status"] = "canceled"
            return httpx.Response(200, json={"status": "canceled"})
        if url.startswith(f"{self.API}/predictions/"):
            pid = url.rsplit("/", 1)[1]
            pred = self.predictions[pid]
            pred["polls"] += 1
            out = self._prediction(pid)
            if pred["status"] == "canceled":
                out["status"] = "canceled"
            elif pred["polls"] <= self.polls_before_done:
                out["status"] = "processing"
                out["logs"] = "Running upscale..."
            elif self.fail_with:
                out["status"] = "failed"
                out["error"] = self.fail_with
            else:
                pred["png"] = self._upscale(pred["input"])
                out.update(
                    status="succeeded",
                    output=f"https://replicate.delivery/{pid}/out.png",
                    metrics={"predict_time": 2.5},
                    logs="done",
                )
            return httpx.Response(200, json=out)
        return httpx.Response(404)

    def _upscale(self, inp) -> bytes:
        key = urlparse(inp["image"]).path.lstrip("/")
        if key.startswith(BUCKET + "/"):
            key = key[len(BUCKET) + 1 :]
        data = self.storage.client.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        s = inp["scale"]
        out = img.resize((img.width * s, img.height * s), Image.NEAREST)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()


@pytest.fixture
def fake_replicate(storage) -> FakeReplicate:
    return FakeReplicate(storage)


@pytest.fixture
def client(settings, storage, fake_gallery, fake_replicate):
    gallery = GalleryClient(settings, transport=httpx.MockTransport(fake_gallery))
    replicate = ReplicateClient(settings, transport=httpx.MockTransport(fake_replicate))
    app = create_app(
        settings=settings, storage=storage, gallery=gallery, replicate=replicate
    )
    with TestClient(app) as c:
        c.headers.update(auth_header())
        yield c
