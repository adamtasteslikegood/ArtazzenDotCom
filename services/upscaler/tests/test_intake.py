import pytest
from upscaler.intake import (
    IntakeError,
    check_image,
    get_import,
    import_bytes,
    list_imports,
    safe_stem,
)
from upscaler.sources import select_path_files

from tests.conftest import png_bytes


def test_safe_stem_strips_path_and_odd_characters():
    assert safe_stem("../../etc/My Art (v2).png") == "My-Art-v2"
    assert safe_stem("C:\\x\\..png") == "image"


@pytest.mark.parametrize(
    ("data", "name", "message"),
    [
        (png_bytes(), "art.svg", "not allowed"),
        (b"", "art.png", "empty"),
        (b"not an image at all", "art.png", "not a readable image"),
        (png_bytes(size=(2000, 1000)), "big.png", "MP limit"),
        (b"x" * (1024 * 1024 + 1), "huge.png", "MB limit"),
    ],
)
def test_check_image_refuses(settings, data, name, message):
    with pytest.raises(IntakeError, match=message):
        check_image(data, name, settings)


def test_check_image_reads_dimensions(settings):
    info = check_image(png_bytes(size=(64, 48)), "art.PNG", settings)
    assert (info.ext, info.width, info.height, info.format) == (".png", 64, 48, "PNG")


def test_import_stores_copy_record_and_dedupes(storage, settings):
    data = png_bytes()
    record, created = import_bytes(
        storage, data, "My Art.png", {"kind": "upload"}, settings
    )
    assert created
    assert record["object"] == f"imports/{record['id']}-My-Art.png"
    assert storage.get_bytes(record["object"]) == data
    # The bucket prefix is applied to every key.
    keys = [
        o["Key"]
        for o in storage.client.list_objects_v2(Bucket=storage.bucket)["Contents"]
    ]
    assert all(k.startswith("dev/imports/") for k in keys)

    again, created_again = import_bytes(
        storage, data, "renamed.png", {"kind": "upload"}, settings
    )
    assert not created_again
    assert again["id"] == record["id"]
    assert [r["id"] for r in list_imports(storage)] == [record["id"]]
    assert get_import(storage, record["id"]) == record
    assert get_import(storage, "../etc") is None


def test_select_path_files_guards(settings):
    root = settings.import_root
    (root / "batch").mkdir()
    (root / "batch" / "a.png").write_bytes(png_bytes())
    (root / "b.png").write_bytes(png_bytes())
    outside = root.parent / "secret.png"
    outside.write_bytes(png_bytes())
    (root / "link.png").symlink_to(outside)

    assert [p.name for p in select_path_files("batch", root)] == ["a.png"]
    assert [p.name for p in select_path_files("b.png", root)] == ["b.png"]
    # The symlink resolves outside the root and is never offered.
    assert "secret.png" not in [p.name for p in select_path_files(".", root)]
    for bad in ("/etc/passwd", "../secret.png", "", "a\x00b", "missing"):
        with pytest.raises(IntakeError):
            select_path_files(bad, root)
