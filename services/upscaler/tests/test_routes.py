from fastapi.testclient import TestClient
from upscaler.app import create_app
from upscaler.config import Settings
from upscaler.intake import list_imports

from tests.conftest import auth_header, png_bytes


def test_health_needs_no_auth(client):
    client.headers.pop("Authorization")
    assert client.get("/health").json() == {"ok": True}


def test_pages_need_auth(client):
    client.headers.pop("Authorization")
    assert client.get("/library").status_code == 401
    client.headers.update(auth_header(password="wrong"))
    assert client.get("/library").status_code == 401


def test_503_when_password_unset(storage):
    app = create_app(settings=Settings(), storage=storage)
    with TestClient(app) as c:
        assert c.get("/library", headers=auth_header()).status_code == 503


def test_cross_origin_post_rejected(client):
    resp = client.post(
        "/import/path",
        data={"path": "x.png"},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


def test_import_page_lists_gallery_pending_and_approved(client):
    page = client.get("/import")
    assert page.status_code == 200
    assert "pending.png" in page.text and "approved.png" in page.text
    assert page.headers["x-frame-options"] == "DENY"


def test_import_tabs_have_server_rendered_fallback(client):
    page = client.get("/import?tab=upload")
    assert 'href="/import?tab=upload"' in page.text

    def opening_tag(element_id: str) -> str:
        element = page.text.index(f'id="{element_id}"')
        start = page.text.rfind("<section", 0, element)
        end = page.text.index(">", element)
        return page.text[start : end + 1]

    assert "hidden" in opening_tag("gallery")
    assert "hidden" not in opening_tag("upload")


def test_gallery_thumb_proxy_asks_for_thumbnail_width(client, fake_gallery):
    resp = client.get("/gallery/thumb/pending.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert fake_gallery.requests[-1].url.params["w"] == "480"


def test_import_from_gallery_copies_original(client, storage, fake_gallery):
    resp = client.post("/import/gallery", data={"names": ["pending.png", "nope.png"]})
    assert resp.status_code == 200
    assert "imported" in resp.text and "not found" in resp.text
    records = list_imports(storage)
    assert len(records) == 1
    assert records[0]["source"] == {"kind": "gallery", "name": "pending.png"}
    assert storage.get_bytes(records[0]["object"]) == fake_gallery.files["pending.png"]
    # The original was fetched without a width parameter.
    assert "w" not in fake_gallery.requests[-2].url.params


def test_upload_import_and_refusals(client, storage):
    resp = client.post(
        "/import/upload",
        files=[
            ("files", ("good.png", png_bytes(), "image/png")),
            ("files", ("bad.png", b"nope", "image/png")),
            ("files", ("big.png", b"x" * (1024 * 1024 + 1), "image/png")),
        ],
    )
    assert resp.status_code == 200
    assert "not a readable image" in resp.text
    assert "larger than the upload limit" in resp.text
    assert [r["original_name"] for r in list_imports(storage)] == ["good.png"]


def test_path_import(client, storage, settings):
    (settings.import_root / "set").mkdir()
    (settings.import_root / "set" / "one.png").write_bytes(png_bytes())
    resp = client.post("/import/path", data={"path": "set"})
    assert resp.status_code == 200
    assert list_imports(storage)[0]["source"] == {"kind": "path", "name": "set/one.png"}

    resp = client.post("/import/path", data={"path": "../etc"})
    assert "relative to the configured import root" in resp.text


def test_library_lists_imports_and_file_redirects_to_presigned_url(client):
    client.post(
        "/import/upload", files=[("files", ("a.png", png_bytes(), "image/png"))]
    )
    imports = client.get("/api/imports").json()["imports"]
    assert len(imports) == 1
    library = client.get("/library").text
    assert "a.png" in library
    assert f'href="/imports/{imports[0]["id"]}/file"' in library
    resp = client.get(f"/imports/{imports[0]['id']}/file", follow_redirects=False)
    assert resp.status_code == 307
    assert "X-Amz-Signature" in resp.headers["location"]
    assert client.get("/imports/000000000000/file").status_code == 404


def test_import_post_does_not_relist_gallery(client, fake_gallery):
    client.post("/import/gallery", data={"names": ["pending.png"]})
    paths = [r.url.path for r in fake_gallery.requests]
    assert "/admin/api/new-files" not in paths


def test_megapixel_ceiling_not_pillow_warning_applies(settings):
    from dataclasses import replace

    from PIL import Image
    from upscaler.intake import check_image

    from tests.conftest import png_bytes

    # Above Pillow's warning threshold but under our ceiling: accepted.
    roomy = replace(settings, max_megapixels=1)
    old = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 2000
    try:
        assert check_image(png_bytes(size=(60, 50)), "a.png", roomy).width == 60
    finally:
        Image.MAX_IMAGE_PIXELS = old
