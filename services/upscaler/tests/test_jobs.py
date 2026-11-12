import io
import time
from dataclasses import replace

import httpx
from fastapi.testclient import TestClient
from PIL import Image
from upscaler.app import create_app
from upscaler.jobs import get_job, job_name, list_jobs
from upscaler.replicate import ReplicateClient

from tests.patterns import gradient, periodic, png, srgb_icc


def upload(client, data: bytes, name="art.png") -> str:
    client.post("/import/upload", files=[("files", (name, data, "image/png"))])
    return client.get("/api/imports").json()["imports"][0]["id"]


def prepare(client, import_id, kind="print", scale=4) -> str:
    resp = client.post(
        "/jobs/prepare",
        data={"import_id": import_id, "kind": kind, "scale": scale},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    location = resp.headers["location"]
    assert location.startswith("/jobs/"), location
    return location.rsplit("/", 1)[1]


def wait_for(client, job_id, states=("done", "error", "cancelled"), timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in states:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job stuck in {job['state']}")


def master_image(storage, job) -> Image.Image:
    img = Image.open(io.BytesIO(storage.get_bytes(job["results"]["master"])))
    img.load()
    return img


def test_prepare_stages_a_copy_and_sends_nothing(client, storage, fake_replicate):
    import_id = upload(client, png(gradient()))
    job_id = prepare(client, import_id)
    job = get_job(storage, job_id)
    assert job["state"] == "staged"
    assert storage.get_bytes(job["staging"]["source"]) == storage.get_bytes(
        client.get("/api/imports").json()["imports"][0]["object"]
    )
    assert job["target"]["width"] == 800 and job["target"]["dpi"] == 300
    assert job["target"]["print_inches"] == [2.7, 2.1]
    assert job["estimate"]["seconds"] >= 5 and not job["blockers"]
    assert fake_replicate.requests == []
    page = client.get(f"/jobs/{job_id}").text
    assert "Start upscale" in page and "Cancel and delete the copy" in page


def test_cancel_staged_deletes_the_copy(client, storage):
    job_id = prepare(client, upload(client, png(gradient())))
    resp = client.post(f"/jobs/{job_id}/cancel", follow_redirects=False)
    assert resp.headers["location"] == "/library"
    assert storage.list_names(f"staging/{job_id}/") == []
    assert get_job(storage, job_id)["state"] == "cancelled"
    # The import itself stays.
    assert len(client.get("/api/imports").json()["imports"]) == 1


def test_print_job_runs_and_keeps_icc_at_300_dpi(client, storage, fake_replicate):
    icc = srgb_icc()
    job_id = prepare(client, upload(client, png(gradient(), icc_profile=icc)))
    client.post(f"/jobs/{job_id}/confirm")
    job = wait_for(client, job_id)
    assert job["state"] == "done", job["error"]
    master = master_image(storage, job)
    assert master.size == (800, 640)
    assert round(master.info["dpi"][0]) == 300
    assert master.info["icc_profile"] == icc
    assert job["predict_seconds"] == 2.5
    assert storage.list_names(f"staging/{job_id}/") == []
    # The token went to the API only, never to the output host.
    for req in fake_replicate.requests:
        if req.url.host == "replicate.delivery":
            assert "authorization" not in req.headers
    # The next estimate learns from the finished job.
    next_job = get_job(
        storage, prepare(client, client.get("/api/imports").json()["imports"][0]["id"])
    )
    assert next_job["estimate"]["basis"].startswith("median of 1")
    resp = client.get(f"/jobs/{job_id}/files/master", follow_redirects=False)
    assert resp.status_code == 307 and "X-Amz-Signature" in resp.headers["location"]


def test_seamless_job_pads_then_crops_back(client, storage, fake_replicate):
    job_id = prepare(client, upload(client, png(periodic(200, 150))), "seamless", 2)
    job = get_job(storage, job_id)
    assert job["input"]["width"] == 264 and not job["warnings"]
    client.post(f"/jobs/{job_id}/confirm")
    job = wait_for(client, job_id)
    assert job["state"] == "done", job["error"]
    master = master_image(storage, job)
    assert master.size == (400, 300)
    # Cropped exactly: a nearest-neighbour 2x of the source.
    expected = periodic(200, 150).resize((400, 300), Image.NEAREST)
    assert master.convert("RGB").tobytes() == expected.tobytes()
    assert "proof" in job["results"]


def test_seamless_job_warns_on_a_visible_seam(client, storage):
    job = get_job(storage, prepare(client, upload(client, png(gradient())), "seamless"))
    assert any("do not look seamless" in w for w in job["warnings"])


def test_tile_job_extracts_and_upscales_the_repeat(client, storage):
    job_id = prepare(client, upload(client, png(periodic(230, 230))), "tile", 4)
    job = get_job(storage, job_id)
    assert job["tile"]["box"][2:] == [50, 50]
    assert job["input"]["width"] == 150
    assert (
        client.get(
            f"/jobs/{job_id}/files/tile-proof", follow_redirects=False
        ).status_code
        == 307
    )
    client.post(f"/jobs/{job_id}/confirm")
    job = wait_for(client, job_id)
    assert job["state"] == "done", job["error"]
    assert master_image(storage, job).size == (200, 200)


def test_tile_job_on_a_composition_is_blocked(client, storage, fake_replicate):
    job_id = prepare(client, upload(client, png(gradient())), "tile")
    job = get_job(storage, job_id)
    assert any("No repeat" in b for b in job["blockers"])
    assert "Start upscale" not in client.get(f"/jobs/{job_id}").text
    resp = client.post(f"/jobs/{job_id}/confirm", follow_redirects=False)
    assert "error=" in resp.headers["location"]
    assert get_job(storage, job_id)["state"] == "staged"
    assert fake_replicate.requests == []


def test_replicate_failure_is_recorded(client, storage, fake_replicate):
    fake_replicate.fail_with = "CUDA out of memory"
    job_id = prepare(client, upload(client, png(gradient())))
    client.post(f"/jobs/{job_id}/confirm")
    job = wait_for(client, job_id)
    assert job["state"] == "error"
    assert "CUDA out of memory" in job["error"]


def test_cancel_running_job_cancels_prediction(client, storage, fake_replicate):
    fake_replicate.polls_before_done = 10_000
    job_id = prepare(client, upload(client, png(gradient())))
    client.post(f"/jobs/{job_id}/confirm")
    wait_for(client, job_id, states=("running",))
    client.post(f"/jobs/{job_id}/cancel")
    job = wait_for(client, job_id)
    assert job["state"] == "cancelled"
    assert any(str(r.url).endswith("/cancel") for r in fake_replicate.requests)
    assert storage.list_names(f"staging/{job_id}/") == []


def test_blockers_for_missing_token_and_oversized_input(
    settings, storage, fake_gallery
):
    tight = replace(settings, replicate_api_token="", replicate_max_input_mp=0.01)
    app = create_app(settings=tight, storage=storage)
    with TestClient(app) as c:
        from tests.conftest import auth_header

        c.headers.update(auth_header())
        job = get_job(storage, prepare(c, upload(c, png(gradient()))))
    assert any("REPLICATE_API_TOKEN" in b for b in job["blockers"])
    assert any("above the 0.01 MP limit" in b for b in job["blockers"])


def test_startup_resumes_running_job_and_stops_unknown_ones(
    client, settings, storage, fake_replicate
):
    fake_replicate.polls_before_done = 10_000
    job_id = prepare(client, upload(client, png(gradient())))
    client.post(f"/jobs/{job_id}/confirm")
    wait_for(client, job_id, states=("running",))
    # A second job that died before its prediction id was saved.
    orphan = dict(get_job(storage, job_id), id="0123456789ab", prediction={})
    storage.put_json(job_name(orphan["id"]), orphan)
    # The old process ends: stop its task without touching the job record.
    tasks = list(client.app.state.runner._tasks.values())
    client.portal.call(lambda: [t.cancel() for t in tasks])
    deadline = time.monotonic() + 5
    while not all(t.done() for t in tasks) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert get_job(storage, job_id)["state"] == "running"

    fake_replicate.polls_before_done = 0
    replicate = ReplicateClient(settings, transport=httpx.MockTransport(fake_replicate))
    app = create_app(settings=settings, storage=storage, replicate=replicate)
    with TestClient(app) as c:
        from tests.conftest import auth_header

        c.headers.update(auth_header())
        job = wait_for(c, job_id)
    assert job["state"] == "done", job["error"]
    assert fake_replicate.created == 1  # re-attached, not started again
    assert get_job(storage, orphan["id"])["state"] == "error"


def test_job_routes_need_auth_and_known_names(client):
    job_id = prepare(client, upload(client, png(gradient())))
    assert client.get(f"/jobs/{job_id}/files/nope").status_code == 404
    assert client.get(f"/jobs/{job_id}/files/master").status_code == 404
    assert client.get("/jobs/000000000000").status_code == 404
    assert client.get("/jobs").status_code == 200
    client.headers.pop("Authorization")
    assert client.get(f"/api/jobs/{job_id}").status_code == 401
    assert client.post(f"/jobs/{job_id}/confirm").status_code == 401


def test_logs_written_per_event(client, storage):
    job_id = prepare(client, upload(client, png(gradient())))
    client.post(f"/jobs/{job_id}/cancel")
    names = storage.list_names("logs/")
    assert len(names) == 1 and names[0].endswith(".jsonl")
    lines = storage.get_bytes(names[0]).decode().strip().splitlines()
    assert [line.count(job_id) for line in lines] == [1, 1]
    assert list_jobs(storage)[0]["id"] == job_id
