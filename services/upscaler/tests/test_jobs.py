import asyncio
import io
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from upscaler.app import create_app
from upscaler.jobs import (
    JobFinished,
    get_job,
    job_name,
    list_jobs,
    postprocess,
    save_job,
    set_state,
)
from upscaler.replicate import ReplicateClient, ReplicateError

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


def wait_for_prediction(client, job_id, timeout=15):
    """Wait until the job is running with a saved Replicate prediction."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] == "running" and (job.get("prediction") or {}).get("get_url"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"no prediction saved; job is {job['state']}")


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


def test_confirm_rejects_a_job_prepared_for_another_model(
    client, storage, fake_replicate
):
    job_id = prepare(client, upload(client, png(gradient())))
    job = get_job(storage, job_id)
    save_job(storage, job, model="nightmareai/real-esrgan")

    resp = client.post(f"/jobs/{job_id}/confirm", follow_redirects=False)

    assert "Prepare%20a%20new%20job" in resp.headers["location"]
    assert get_job(storage, job_id)["state"] == "staged"
    assert fake_replicate.requests == []

    # A deployment can also find an already-queued job. It must not silently
    # send that job to a different model when the runner resumes it.
    queued_id = prepare(client, upload(client, png(gradient())))
    queued = get_job(storage, queued_id)
    queued = save_job(storage, queued, model="nightmareai/real-esrgan")
    set_state(storage, queued, "queued")
    client.portal.call(client.app.state.runner.start, queued_id)
    failed = wait_for(client, queued_id)
    assert failed["state"] == "error"
    assert "Prepare a new job" in failed["error"]
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
    wait_for_prediction(client, job_id)
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
    assert any("above the 0.01 MP limit set for" in b for b in job["blockers"])


def test_startup_resumes_running_job_and_stops_unknown_ones(
    client, settings, storage, fake_replicate
):
    fake_replicate.polls_before_done = 10_000
    job_id = prepare(client, upload(client, png(gradient())))
    client.post(f"/jobs/{job_id}/confirm")
    wait_for_prediction(client, job_id)
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


def _hold_create(client):
    """Make the runner's next Replicate create wait until released."""
    runner = client.app.state.runner
    gate = asyncio.Event()
    original = runner.replicate.create

    async def held(url, scale):
        await gate.wait()
        return await original(url, scale)

    runner.replicate.create = held
    return gate


def _wait_state(storage, job_id, state, prediction=None, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = get_job(storage, job_id)
        if job["state"] == state and (
            prediction is None or job.get("prediction") == prediction
        ):
            return job
        time.sleep(0.01)
    raise AssertionError(f"job never reached {state}")


def test_restart_during_create_stops_instead_of_billing_twice(
    client, settings, storage, fake_replicate
):
    job_id = prepare(client, upload(client, png(gradient())))
    _hold_create(client)
    client.post(f"/jobs/{job_id}/confirm")
    # Marked running before the create call returned.
    _wait_state(storage, job_id, "running", prediction={})
    tasks = list(client.app.state.runner._tasks.values())
    client.portal.call(lambda: [t.cancel() for t in tasks])
    deadline = time.monotonic() + 5
    while not all(t.done() for t in tasks) and time.monotonic() < deadline:
        time.sleep(0.01)

    replicate = ReplicateClient(settings, transport=httpx.MockTransport(fake_replicate))
    app = create_app(settings=settings, storage=storage, replicate=replicate)
    with TestClient(app) as c:
        from tests.conftest import auth_header

        c.headers.update(auth_header())
        job = wait_for(c, job_id)
    assert job["state"] == "error"
    assert "Replicate dashboard" in job["error"]
    assert fake_replicate.created == 0  # no second create after the restart


def test_cancel_during_create_cancels_the_new_prediction(
    client, storage, fake_replicate
):
    fake_replicate.polls_before_done = 10_000
    job_id = prepare(client, upload(client, png(gradient())))
    gate = _hold_create(client)
    client.post(f"/jobs/{job_id}/confirm")
    _wait_state(storage, job_id, "running", prediction={})
    client.post(f"/jobs/{job_id}/cancel")
    assert get_job(storage, job_id)["state"] == "cancelled"
    client.portal.call(gate.set)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(str(r.url).endswith("/p1/cancel") for r in fake_replicate.requests):
            break
        time.sleep(0.01)
    else:
        raise AssertionError("the prediction created after the cancel kept running")
    job = get_job(storage, job_id)
    assert job["state"] == "cancelled"
    assert not job.get("prediction")


def test_a_stale_copy_cannot_undo_a_cancel(client, storage):
    job_id = prepare(client, upload(client, png(gradient())))
    stale = get_job(storage, job_id)
    client.post(f"/jobs/{job_id}/cancel")
    with pytest.raises(JobFinished):
        save_job(storage, dict(stale, state="running"), logs="late poll")
    job = get_job(storage, job_id)
    assert job["state"] == "cancelled" and job["logs"] == ""


def test_stale_transition_cannot_move_a_running_job_backwards(client, storage):
    job_id = prepare(client, upload(client, png(gradient())))
    stale = get_job(storage, job_id)
    queued = set_state(storage, stale, "queued")
    set_state(storage, queued, "running", prediction={})
    with pytest.raises(JobFinished, match="already running"):
        set_state(storage, stale, "queued")
    assert get_job(storage, job_id)["state"] == "running"


def test_poll_failure_cancels_the_active_prediction(client, storage, fake_replicate):
    runner = client.app.state.runner

    async def failed_poll(_url):
        raise ReplicateError("poll connection failed")

    runner.replicate.get = failed_poll
    job_id = prepare(client, upload(client, png(gradient())))
    client.post(f"/jobs/{job_id}/confirm")
    job = wait_for(client, job_id)
    assert job["state"] == "error"
    assert "poll connection failed" in job["error"]
    assert any(str(r.url).endswith("/cancel") for r in fake_replicate.requests)


def test_wrong_output_dimensions_are_rejected_before_decode(
    client, storage, settings, tmp_path, monkeypatch
):
    job_id = prepare(client, upload(client, png(gradient())))
    job = get_job(storage, job_id)
    output = tmp_path / "wrong.png"
    Image.new("RGB", (1, 1)).save(output)

    def unexpected_load(_self):
        raise AssertionError("mismatched output pixels were decoded")

    monkeypatch.setattr(Image.Image, "load", unexpected_load)
    with pytest.raises(ReplicateError, match="Output is 1×1, expected"):
        postprocess(storage, settings, job, output)


def test_output_download_rejects_unexpected_hosts_and_redirects(settings, tmp_path):
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})

    client = ReplicateClient(settings, transport=httpx.MockTransport(redirect))

    async def download(url: str):
        await client.download(url, Path(tmp_path) / "output", 1024)

    with pytest.raises(ReplicateError, match="Unexpected Replicate output URL"):
        asyncio.run(download("https://example.com/output.png"))
    assert requests == []

    with pytest.raises(ReplicateError, match="Unexpected Replicate output URL"):
        asyncio.run(download("https://replicate.delivery/output.png"))
    assert len(requests) == 1


def test_cancel_holds_while_logs_change(client, storage, fake_replicate):
    fake_replicate.polls_before_done = 10_000
    job_id = prepare(client, upload(client, png(gradient())))
    client.post(f"/jobs/{job_id}/confirm")
    wait_for_prediction(client, job_id)
    client.post(f"/jobs/{job_id}/cancel")
    polls = len(fake_replicate.requests)
    time.sleep(0.2)
    assert get_job(storage, job_id)["state"] == "cancelled"
    assert len(fake_replicate.requests) <= polls + 2  # polling stopped


def test_oversized_input_is_refused_before_it_is_built(settings, storage):
    tight = replace(settings, replicate_max_input_mp=0.01)
    app = create_app(settings=tight, storage=storage)
    with TestClient(app) as c:
        from tests.conftest import auth_header

        c.headers.update(auth_header())
        job_id = prepare(c, upload(c, png(gradient())), kind="seamless")
    job = get_job(storage, job_id)
    assert any("above the 0.01 MP limit set for" in b for b in job["blockers"])
    assert job["input"]["width"] == 200 + 64
    assert job["staging"]["input"] == ""
    assert storage.list_names(f"staging/{job_id}/input") == []


def test_exif_rotated_jpeg_is_sent_upright(client, storage):
    img = gradient(40, 20)
    exif = img.getexif()
    exif[0x0112] = 6  # rotate 90° clockwise on display
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes(), quality=95)
    job_id = prepare(client, upload(client, buf.getvalue(), name="photo.jpg"))
    staged = get_job(storage, job_id)
    assert staged["source"]["exif_rotated"] is True
    assert (staged["source"]["width"], staged["source"]["height"]) == (20, 40)
    assert staged["staging"]["input"].endswith("input.png")
    client.post(f"/jobs/{job_id}/confirm")
    job = wait_for(client, job_id)
    assert job["state"] == "done", job["error"]
    assert master_image(storage, job).size == (80, 160)


def test_cancel_from_a_stale_copy_still_cancels(client, storage, fake_replicate):
    fake_replicate.polls_before_done = 10_000
    job_id = prepare(client, upload(client, png(gradient())))
    stale = get_job(storage, job_id)
    client.post(f"/jobs/{job_id}/confirm")
    wait_for_prediction(client, job_id)
    runner = client.app.state.runner
    job = client.portal.call(runner.cancel, dict(stale, state="queued"))
    assert job["state"] == "cancelled"
    assert get_job(storage, job_id)["state"] == "cancelled"
    assert any(str(r.url).endswith("/p1/cancel") for r in fake_replicate.requests)


def _throttled_client(settings, responses):
    calls = []

    def handler(request):
        calls.append(request)
        return responses.pop(0) if responses else httpx.Response(429)

    client = ReplicateClient(settings, transport=httpx.MockTransport(handler))
    waits = []

    async def no_sleep(seconds):
        waits.append(seconds)

    client._sleep = no_sleep
    return client, calls, waits


def test_throttled_create_waits_and_resends(settings):
    # Low-credit accounts get a burst of one; a 429 created nothing.
    responses = [
        httpx.Response(429, headers={"retry-after": "2"}),
        httpx.Response(429, json={"detail": "throttled"}),
        httpx.Response(201, json={"id": "p1", "status": "starting"}),
    ]
    client, calls, waits = _throttled_client(
        replace(settings, replicate_version="v1"), responses
    )
    prediction = asyncio.run(client.create("https://bucket/x.png", 4))
    assert prediction["id"] == "p1"
    assert len(calls) == 3
    assert waits == [2.0, 10.0]


def test_throttling_that_never_clears_fails_the_job(settings):
    client, calls, waits = _throttled_client(
        replace(settings, replicate_version="v1"), []
    )
    with pytest.raises(ReplicateError, match="Replicate returned 429"):
        asyncio.run(client.create("https://bucket/x.png", 4))
    assert len(calls) == 7
    assert all(w <= 30 for w in waits)


def test_default_model_takes_a_phone_export_in_one_pass():
    from upscaler.config import Settings

    settings = Settings()
    assert settings.replicate_model == "xinntao/realesrgan"
    assert settings.replicate_tile > 0  # untiled Real-ESRGAN stops at 2.1 MP
    # A 2048×2732 iPad export is 5.6 MP.
    assert settings.replicate_max_input_mp * 1_000_000 > 2048 * 2732


def test_default_model_requires_a_tile_size_the_model_will_use():
    from upscaler.config import Settings

    with pytest.raises(ValueError, match="greater than 100"):
        Settings(replicate_tile=100)


def test_xinntao_adapter_is_limited_to_the_supported_model(settings):
    client = ReplicateClient(replace(settings, replicate_model="xinntao/other"))
    sent = client.model_input("https://bucket/input.png", 4)
    assert sent == {
        "image": "https://bucket/input.png",
        "scale": 4,
        "face_enhance": False,
    }


def _xinntao_client(settings, storage, fake_gallery, fake_replicate):
    from upscaler.config import DEFAULT_MODEL
    from upscaler.sources import GalleryClient

    from tests.conftest import auth_header

    real = replace(settings, replicate_model=DEFAULT_MODEL)
    app = create_app(
        settings=real,
        storage=storage,
        gallery=GalleryClient(real, transport=httpx.MockTransport(fake_gallery)),
        replicate=ReplicateClient(real, transport=httpx.MockTransport(fake_replicate)),
    )
    client = TestClient(app)
    client.headers.update(auth_header())
    return client


def test_xinntao_job_sends_tiled_input_and_keeps_the_scale(
    settings, storage, fake_gallery, fake_replicate
):
    with _xinntao_client(settings, storage, fake_gallery, fake_replicate) as c:
        job_id = prepare(c, upload(c, png(gradient(400, 300))), "print", 2)
        c.post(f"/jobs/{job_id}/confirm")
        job = wait_for(c, job_id)
    assert job["state"] == "done", job.get("error")
    assert job["model"] == "xinntao/realesrgan"
    assert master_image(storage, job).size == (800, 600)
    sent = next(iter(fake_replicate.predictions.values()))["input"]
    assert sent["version"] == "General - RealESRGANplus"
    assert sent["tile"] == 400
    assert sent["face_enhance"] is False
    assert "img" in sent and "image" not in sent


def test_xinntao_small_input_is_scaled_back_to_the_requested_size(
    settings, storage, fake_gallery, fake_replicate
):
    # Low-resolution art is the main use. The model doubles an input under
    # 300 px tall, so its 8x output is scaled back down to the 4x master.
    with _xinntao_client(settings, storage, fake_gallery, fake_replicate) as c:
        job_id = prepare(c, upload(c, png(gradient(160, 120))))
        staged = get_job(storage, job_id)
        c.post(f"/jobs/{job_id}/confirm")
        job = wait_for(c, job_id)
    assert staged["prefit"] == 2 and not staged["blockers"]
    assert job["state"] == "done", job.get("error")
    assert master_image(storage, job).size == (640, 480)


def test_small_seamless_input_still_wraps_after_scaling_back(
    settings, storage, fake_gallery, fake_replicate
):
    with _xinntao_client(settings, storage, fake_gallery, fake_replicate) as c:
        job_id = prepare(c, upload(c, png(periodic(200, 150))), "seamless", 2)
        c.post(f"/jobs/{job_id}/confirm")
        job = wait_for(c, job_id)
    assert job["state"] == "done", job.get("error")
    master = master_image(storage, job)
    assert master.size == (400, 300)
    assert job["prefit"] == 2  # 150 + 64 px of wrap pad is under 300


def test_estimate_ignores_jobs_from_another_model(storage, settings):
    from upscaler.jobs import job_name, seconds_per_mp

    old = {
        "id": "0000000000a1",
        "state": "done",
        "input": {"megapixels": 1.0},
        "predict_seconds": 11.0,
    }  # no model field: ran on the T4 model
    new = {
        "id": "0000000000b2",
        "state": "done",
        "input": {"megapixels": 2.0},
        "predict_seconds": 6.0,
        "model": settings.replicate_model,
    }
    for job in (old, new):
        storage.put_json(job_name(job["id"]), job)
    rate, basis = seconds_per_mp(storage, settings)
    assert rate == 3.0
    assert basis == "median of 1 finished job(s)"
