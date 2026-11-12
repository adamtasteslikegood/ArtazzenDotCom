"""Jobs: prepare a staged copy, confirm, run on Replicate, post-process.

Every job starts from an import that is already in the bucket and works on
its own copy in ``staging/<job>/``. Nothing starts until the user confirms.

Bucket layout written here::

    staging/<job>/source.<ext>     copy of the import
    staging/<job>/input.png        what Replicate sees, when it differs
    staging/<job>/tile.png         extracted repeat (tile jobs)
    staging/<job>/proof.jpg        3x3 proof of the tile (tile jobs)
    results/<job>/master.png       300 DPI master, source ICC kept
    results/<job>/proof.jpg        2x2 tiling proof (pattern jobs)
    jobs/<job>.json                state, analysis, estimate, timings, error
    logs/<YYYY-MM-DD>.jsonl        one line per job event

States: staged → queued → running → postprocessing → done | error | cancelled
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import mimetypes
import re
import secrets
import statistics
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from upscaler import analysis
from upscaler.config import Settings
from upscaler.intake import get_import
from upscaler.replicate import TERMINAL, ReplicateClient, ReplicateError, output_url
from upscaler.storage import Storage

logger = logging.getLogger(__name__)

JOB_ID_RE = re.compile(r"^[0-9a-f]{12}$")
KINDS = {
    "print": {"label": "Print master", "mode": "plain"},
    "seamless": {"label": "Seamless pattern (keep the wrap)", "mode": "wrap"},
    "tile": {"label": "Pattern → seamless tile", "mode": "tile"},
}
SCALES = (4, 2)
ACTIVE = frozenset({"queued", "running", "postprocessing"})
FINAL = frozenset({"done", "error", "cancelled"})
# Replicate accepts these as-is; anything else is converted to PNG first.
_PASSTHROUGH = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_LOG_LOCK = threading.Lock()
# Every job-record write re-reads under this lock, so a write made from a
# stale copy can never undo a final state (one process; see README).
_JOB_LOCK = threading.Lock()
# Pillow's decompression ceiling is process-global. Serialize temporary
# changes while an output is opened, and restore the previous value promptly.
_PILLOW_LOCK = threading.Lock()
_EXIF_ORIENTATION = 0x0112


class JobError(ValueError):
    """The request cannot be carried out; the message is user-facing."""


class JobFinished(JobError):
    """The job reached a final state elsewhere; the write was refused."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def job_name(job_id: str) -> str:
    return f"jobs/{job_id}.json"


def get_job(storage: Storage, job_id: str) -> dict[str, Any] | None:
    if not JOB_ID_RE.match(job_id):
        return None
    return storage.get_json(job_name(job_id))


def list_jobs(storage: Storage) -> list[dict[str, Any]]:
    jobs = []
    for name in storage.list_names("jobs/"):
        if JOB_ID_RE.match(Path(name).stem) and name.endswith(".json"):
            job = storage.get_json(name)
            if job:
                jobs.append(job)
    return sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)


def log_event(storage: Storage, job: dict[str, Any], event: str, **extra: Any) -> None:
    """Append one line to today's log. Read-modify-write: one process only."""
    line = {"at": now_iso(), "job": job["id"], "event": event, **extra}
    name = f"logs/{line['at'][:10]}.jsonl"
    try:
        with _LOG_LOCK:
            existing = storage.get_bytes(name) or b""
            storage.put_bytes(
                name,
                existing + json.dumps(line).encode("utf-8") + b"\n",
                "application/x-ndjson",
            )
    except Exception:
        logger.exception("Could not write job log line for %s", job["id"])


def save_job(storage: Storage, job: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """Merge ``changes`` into the stored record and return the result.

    The stored copy wins over ``job`` for every field not in ``changes``, and
    a job already in a final state is never written again: a poll that read
    the record before a cancel cannot flip it back to running.
    """
    with _JOB_LOCK:
        stored = storage.get_json(job_name(job["id"]))
        if stored and stored.get("state") in FINAL:
            raise JobFinished(f"Job is already {stored['state']}")
        if stored and "state" in changes and stored.get("state") != job.get("state"):
            # A second confirm/cancel request may have read an older copy.
            # Never let that stale transition move a running job backwards.
            raise JobFinished(f"Job is already {stored.get('state', 'unknown')}")
        record = dict(stored or job)
        record.update(changes)
        record["updated_at"] = now_iso()
        storage.put_json(job_name(record["id"]), record)
    return record


def set_state(
    storage: Storage, job: dict[str, Any], state: str, **changes: Any
) -> dict[str, Any]:
    job = save_job(storage, job, state=state, **changes)
    log_event(
        storage,
        job,
        state,
        **({"error": changes["error"]} if "error" in changes else {}),
    )
    return job


def delete_prefix(storage: Storage, prefix: str) -> None:
    for name in storage.list_names(prefix):
        try:
            storage.delete(name)
        except Exception:
            logger.exception("Could not delete %s", name)


# --- estimates ---------------------------------------------------------------


def seconds_per_mp(storage: Storage, settings: Settings) -> tuple[float, str]:
    """Median of finished jobs' seconds per input megapixel, else the setting."""
    rates = []
    for job in list_jobs(storage):
        mp = (job.get("input") or {}).get("megapixels")
        secs = job.get("predict_seconds") or job.get("run_seconds")
        if job.get("state") == "done" and mp and secs:
            rates.append(secs / mp)
    if rates:
        return statistics.median(rates), f"median of {len(rates)} finished job(s)"
    return settings.seconds_per_mp, "configured rate (no finished jobs yet)"


def estimate(storage: Storage, settings: Settings, input_mp: float) -> dict[str, Any]:
    rate, basis = seconds_per_mp(storage, settings)
    seconds = max(5.0, rate * input_mp)
    return {
        "seconds": round(seconds),
        "cost_usd": round(seconds * settings.price_per_second, 4),
        "basis": basis,
        "seconds_per_mp": round(rate, 2),
        "price_per_second": settings.price_per_second,
    }


# --- prepare -----------------------------------------------------------------


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def prepare(
    storage: Storage, settings: Settings, import_id: str, kind: str, scale: int
) -> dict[str, Any]:
    """Copy an import to ``staging/<job>/`` and analyse the copy.

    Returns the staged job. Nothing is sent to Replicate.
    """
    if kind not in KINDS:
        raise JobError("Unknown job type")
    if scale not in SCALES:
        raise JobError("Scale must be 2 or 4")
    record = get_import(storage, import_id)
    if not record:
        raise JobError("That import no longer exists")
    data = storage.get_bytes(record["object"])
    if data is None:
        raise JobError("The imported file is missing from the bucket")

    job_id = secrets.token_hex(6)
    mode = KINDS[kind]["mode"]
    ext = Path(record["object"]).suffix
    staging = f"staging/{job_id}"
    source_name = f"{staging}/source{ext}"
    storage.put_bytes(
        source_name, data, mimetypes.guess_type(source_name)[0] or "image/png"
    )

    warnings: list[str] = []
    blockers: list[str] = []
    tile_info = None
    input_name = ""
    base: tuple[int, int] = (0, 0)
    input_size: tuple[int, int] = (0, 0)

    def too_big(size: tuple[int, int]) -> bool:
        # Checked from arithmetic before any pad, grid or PNG is built, so a
        # large import is refused without holding a second copy in memory.
        mp = size[0] * size[1] / 1_000_000
        if mp <= settings.replicate_max_input_mp:
            return False
        blockers.append(
            f"Replicate input would be {size[0]}×{size[1]} ({mp:.1f} MP), above "
            f"the {settings.replicate_max_input_mp:g} MP limit set for this model."
        )
        return True

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            fmt = img.format or ""
            dpi = img.info.get("dpi", (0, 0))[0]
            icc = bool(img.info.get("icc_profile"))
            # The model may honour EXIF orientation and return a rotated
            # result whose size no longer matches; send upright pixels.
            rotated = img.getexif().get(_EXIF_ORIENTATION, 1) not in (0, 1)
            src = ImageOps.exif_transpose(img) if rotated else img
            width, height = src.size
            seams = analysis.seam_report(src)

            if mode == "tile":
                try:
                    tile = analysis.extract_tile(src, seams)
                except analysis.AnalysisError as exc:
                    blockers.append(str(exc))
                    tile = None
                if tile is not None:
                    tile_info = {
                        "box": list(tile.box),
                        "seam_ratio": tile.seam_ratio,
                        "good": tile.good,
                    }
                    if not tile.good:
                        warnings.append(
                            f"The best tile's seam ratio is {tile.seam_ratio}; "
                            "check the proof before confirming."
                        )
                    base = tile.tile.size
                    input_size = (base[0] * 3, base[1] * 3)
                    storage.put_bytes(
                        f"{staging}/tile.png", _png(tile.tile), "image/png"
                    )
                    storage.put_bytes(
                        f"{staging}/proof.jpg",
                        _jpeg(analysis.proof(tile.tile, 3)),
                        "image/jpeg",
                    )
                    if not too_big(input_size):
                        grid = analysis.repeat_grid(tile.tile, 3)
                        input_name = f"{staging}/input.png"
                        storage.put_bytes(input_name, _png(grid), "image/png")
            elif mode == "wrap":
                if seams.verdict != "seamless":
                    warnings.append(
                        f"The edges do not look seamless (verdict: {seams.verdict}); "
                        "“Seamless pattern” keeps a seam that is already there."
                    )
                base = (width, height)
                pad = 2 * analysis.WRAP_PAD
                input_size = (width + pad, height + pad)
                if not too_big(input_size):
                    padded = analysis.wrap_pad(src)
                    input_name = f"{staging}/input.png"
                    storage.put_bytes(input_name, _png(padded), "image/png")
            else:
                base = (width, height)
                input_size = (width, height)
                if too_big(input_size):
                    pass
                elif (
                    not rotated
                    and fmt in _PASSTHROUGH
                    and src.mode in ("RGB", "RGBA", "L")
                ):
                    input_name = source_name
                else:
                    input_name = f"{staging}/input.png"
                    rgb = src.convert("RGBA" if "A" in src.getbands() else "RGB")
                    storage.put_bytes(input_name, _png(rgb), "image/png")
    except Exception:
        delete_prefix(storage, f"{staging}/")
        raise

    input_mp = input_size[0] * input_size[1] / 1_000_000
    if not settings.replicate_api_token:
        blockers.append("REPLICATE_API_TOKEN is not set on this service.")
    target = (base[0] * scale, base[1] * scale)

    job = {
        "id": job_id,
        "import_id": import_id,
        "original_name": record.get("original_name", ""),
        "kind": kind,
        "mode": mode,
        "scale": scale,
        "state": "staged",
        "created_at": now_iso(),
        "staging": {"source": source_name, "input": input_name},
        "source": {
            "width": width,
            "height": height,
            "megapixels": round(width * height / 1_000_000, 2),
            "format": fmt,
            "dpi_tag": round(float(dpi)) if dpi else 0,
            "icc": icc,
            "exif_rotated": rotated,
        },
        "seams": {
            "lr_ratio": seams.lr_ratio,
            "tb_ratio": seams.tb_ratio,
            "verdict": seams.verdict,
            "period_h": seams.periods_h[0][0] if seams.periods_h else None,
            "period_v": seams.periods_v[0][0] if seams.periods_v else None,
            "analysed_at_scale": round(seams.scale, 3),
        },
        "tile": tile_info,
        "base": list(base),
        "input": {
            "width": input_size[0],
            "height": input_size[1],
            "megapixels": round(input_mp, 2),
        },
        "target": {
            "width": target[0],
            "height": target[1],
            "dpi": settings.print_dpi,
            "print_inches": [
                round(target[0] / settings.print_dpi, 1),
                round(target[1] / settings.print_dpi, 1),
            ],
        },
        "estimate": estimate(storage, settings, input_mp),
        "warnings": warnings,
        "blockers": blockers,
        "results": {},
        "logs": "",
        "error": "",
    }
    job = save_job(storage, job)
    log_event(storage, job, "staged", kind=kind, import_id=import_id)
    return job


def cancel_staged(storage: Storage, job: dict[str, Any]) -> dict[str, Any]:
    job = set_state(storage, job, "cancelled", finished_at=now_iso())
    delete_prefix(storage, f"staging/{job['id']}/")
    return job


# --- post-processing -----------------------------------------------------------


def _state(storage: Storage, job_id: str) -> str:
    current = get_job(storage, job_id)
    return current.get("state", "") if current else "cancelled"


def postprocess(
    storage: Storage, settings: Settings, job: dict[str, Any], output: Path
) -> dict[str, str]:
    """Crop, tag DPI, copy ICC, upload results. Runs in a worker thread.

    Cancelling the asyncio task does not stop this thread, so it re-checks
    the job before and after uploading and leaves no results for a job that
    was cancelled meanwhile.
    """
    source = storage.get_bytes(job["staging"]["source"]) or b""
    with Image.open(io.BytesIO(source)) as src:
        icc = src.info.get("icc_profile")
    scale = job["scale"]
    results: dict[str, str] = {}
    expected = (job["input"]["width"] * scale, job["input"]["height"] * scale)
    output_limit = int(settings.max_output_megapixels * 1_000_000)
    if expected[0] * expected[1] > output_limit:
        raise ReplicateError(
            f"Expected output is {expected[0]}×{expected[1]}, above the "
            f"{settings.max_output_megapixels:g} MP output limit"
        )
    # Compare the provider-controlled header before decoding pixels. This
    # avoids loading an unexpectedly huge response merely to reject its size.
    with _PILLOW_LOCK:
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = output_limit
        try:
            with Image.open(output) as out:
                if out.size != expected:
                    raise ReplicateError(
                        f"Output is {out.size[0]}×{out.size[1]}, expected "
                        f"{expected[0]}×{expected[1]}"
                    )
                out.load()
                box = analysis.crop_box(job["mode"], tuple(job["base"]), scale)
                master = out.crop(box) if box else out.copy()
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit
    if master.mode not in ("RGB", "RGBA", "L"):
        master = master.convert("RGB")
    save_kwargs: dict[str, Any] = {
        "format": "PNG",
        "dpi": (settings.print_dpi, settings.print_dpi),
    }
    if icc:
        save_kwargs["icc_profile"] = icc
    with tempfile.TemporaryDirectory() as tmp:
        master_path = Path(tmp) / "master.png"
        master.save(master_path, **save_kwargs)
        if _state(storage, job["id"]) in FINAL:
            raise JobFinished("Job ended during post-processing")
        name = f"results/{job['id']}/master.png"
        storage.upload_file(name, str(master_path), "image/png")
        results["master"] = name
        if job["mode"] in ("wrap", "tile"):
            proof_name = f"results/{job['id']}/proof.jpg"
            storage.put_bytes(
                proof_name, _jpeg(analysis.proof(master, 2)), "image/jpeg"
            )
            results["proof"] = proof_name
        results["size"] = f"{master.size[0]}x{master.size[1]}"
    state = _state(storage, job["id"])
    if state in FINAL:
        # Only a cancel removes results; never touch what a done job lists.
        if state == "cancelled":
            delete_prefix(storage, f"results/{job['id']}/")
        raise JobFinished("Job ended during post-processing")
    return results


# --- runner --------------------------------------------------------------------


class JobRunner:
    """Runs confirmed jobs as asyncio tasks, at most N on Replicate at once."""

    def __init__(
        self, storage: Storage, settings: Settings, replicate: ReplicateClient
    ) -> None:
        self.storage = storage
        self.settings = settings
        self.replicate = replicate
        self._gate: asyncio.Semaphore | None = None
        self._tasks: dict[str, asyncio.Task] = {}

    def _semaphore(self) -> asyncio.Semaphore:
        if self._gate is None:
            self._gate = asyncio.Semaphore(self.settings.max_concurrent_jobs)
        return self._gate

    async def _io(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    def start(self, job_id: str) -> None:
        if job_id in self._tasks and not self._tasks[job_id].done():
            return
        task = asyncio.create_task(self._run(job_id), name=f"job-{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(job_id, None))

    async def confirm(self, job: dict[str, Any]) -> dict[str, Any]:
        if job["state"] != "staged":
            raise JobError(f"Job is {job['state']}, not waiting for confirmation")
        if job.get("blockers"):
            raise JobError(job["blockers"][0])
        try:
            job = await self._io(
                set_state, self.storage, job, "queued", queued_at=now_iso()
            )
        except JobFinished as exc:
            raise JobError(str(exc)) from None
        self.start(job["id"])
        return job

    async def cancel(self, job: dict[str, Any]) -> dict[str, Any]:
        state = job["state"]
        if state == "staged":
            try:
                return await self._io(cancel_staged, self.storage, job)
            except JobFinished as exc:
                raise JobError(str(exc)) from None
        if state not in ACTIVE:
            raise JobError(f"Job is already {state}")
        try:
            job = await self._io(
                set_state, self.storage, job, "cancelled", finished_at=now_iso()
            )
        except JobFinished as exc:
            raise JobError(str(exc)) from None
        # Take the cancel URL from the record just written, not the copy the
        # caller read: the prediction may have been saved in between.
        cancel_url = (job.get("prediction") or {}).get("cancel_url")
        if cancel_url:
            try:
                await self.replicate.cancel(cancel_url)
            except ReplicateError as exc:
                logger.warning("Cancel of %s failed: %s", job["id"], exc)
        task = self._tasks.get(job["id"])
        # An empty prediction means the create call is in flight. Aborting it
        # could leave a prediction Replicate already accepted with nobody to
        # stop it; the task cancels it itself once the call returns.
        if task and job.get("prediction") != {}:
            task.cancel()
        await self._io(delete_prefix, self.storage, f"staging/{job['id']}/")
        return job

    async def resume(self) -> list[str]:
        """Restart queued jobs and re-attach to running predictions."""
        resumed = []
        for job in await self._io(list_jobs, self.storage):
            state = job.get("state")
            if state == "queued" or (
                state in ("running", "postprocessing")
                and (job.get("prediction") or {}).get("get_url")
            ):
                self.start(job["id"])
                resumed.append(job["id"])
            elif state in ("running", "postprocessing"):
                # Interrupted while the prediction was being created: one may
                # exist on Replicate without its id here. Starting another
                # could bill twice, so stop and say so.
                await self._io(
                    set_state,
                    self.storage,
                    job,
                    "error",
                    error="Interrupted by a restart while the job was being sent "
                    "to Replicate. It may have run once there; check the "
                    "Replicate dashboard before preparing it again.",
                    finished_at=now_iso(),
                )
        return resumed

    async def _fresh(self, job_id: str) -> dict[str, Any] | None:
        return await self._io(get_job, self.storage, job_id)

    async def _run(self, job_id: str) -> None:
        try:
            async with self._semaphore():
                job = await self._fresh(job_id)
                if not job or job["state"] in FINAL:
                    return
                await self._execute(job)
        except asyncio.CancelledError:
            raise
        except JobFinished:
            return  # cancelled (or finished) elsewhere; nothing to record
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            job = await self._fresh(job_id)
            if job and job["state"] not in FINAL:
                cancel_url = (job.get("prediction") or {}).get("cancel_url")
                if cancel_url:
                    try:
                        await self.replicate.cancel(cancel_url)
                    except ReplicateError as cancel_exc:
                        logger.warning("Cancel of %s failed: %s", job_id, cancel_exc)
                message = (
                    str(exc)
                    if isinstance(exc, (ReplicateError, JobError))
                    else (f"{type(exc).__name__} during processing; see service logs")
                )
                await self._io(
                    set_state,
                    self.storage,
                    job,
                    "error",
                    error=message,
                    finished_at=now_iso(),
                )

    async def _execute(self, job: dict[str, Any]) -> None:
        started = time.monotonic()
        prediction = job.get("prediction") or {}
        if not prediction.get("get_url"):
            # Mark the job running before the create call. A restart from here
            # on finds "running" with no prediction and stops, instead of
            # treating it as queued and creating (and billing) a second one.
            job = await self._io(
                set_state,
                self.storage,
                job,
                "running",
                prediction={},
                started_at=now_iso(),
            )
            url = await self._io(
                self.storage.presign_get, job["staging"]["input"], expires=3600
            )
            created = await self.replicate.create(url, job["scale"])
            prediction = {
                "id": created.get("id", ""),
                "get_url": (created.get("urls") or {}).get("get", ""),
                "cancel_url": (created.get("urls") or {}).get("cancel", ""),
            }
            if not prediction["get_url"]:
                raise ReplicateError("Replicate did not return a prediction URL")
            try:
                job = await self._io(save_job, self.storage, job, prediction=prediction)
            except JobFinished:
                # Cancelled while the create call was in flight: the cancel
                # had no prediction to stop, so stop it here.
                if prediction["cancel_url"]:
                    try:
                        await self.replicate.cancel(prediction["cancel_url"])
                    except ReplicateError as exc:
                        logger.warning("Cancel of %s failed: %s", job["id"], exc)
                raise
        deadline = started + self.settings.replicate_timeout_seconds
        while True:
            current = await self.replicate.get(prediction["get_url"])
            status_ = current.get("status", "")
            logs = (current.get("logs") or "")[-2000:]
            latest = await self._fresh(job["id"])
            if not latest or latest["state"] in FINAL:
                return  # cancelled meanwhile
            job = latest
            if logs != job.get("logs"):
                job = await self._io(save_job, self.storage, job, logs=logs)
            if status_ in TERMINAL:
                break
            if time.monotonic() > deadline:
                if prediction.get("cancel_url"):
                    try:
                        await self.replicate.cancel(prediction["cancel_url"])
                    except ReplicateError:
                        pass
                raise ReplicateError("Timed out waiting for Replicate")
            await asyncio.sleep(self.settings.poll_seconds)
        if status_ != "succeeded":
            error = current.get("error") or status_
            raise ReplicateError(f"Replicate prediction {status_}: {str(error)[:300]}")

        job = await self._io(set_state, self.storage, job, "postprocessing")
        max_bytes = int(self.settings.max_output_megapixels * 1_000_000 * 4 + 1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "output"
            await self.replicate.download(output_url(current), out_path, max_bytes)
            results = await self._io(
                postprocess, self.storage, self.settings, job, out_path
            )
        metrics = current.get("metrics") or {}
        await self._io(delete_prefix, self.storage, f"staging/{job['id']}/")
        try:
            await self._io(
                set_state,
                self.storage,
                job,
                "done",
                results=results,
                finished_at=now_iso(),
                run_seconds=round(time.monotonic() - started, 1),
                predict_seconds=metrics.get("predict_time"),
            )
        except JobFinished:
            if await self._io(_state, self.storage, job["id"]) == "cancelled":
                await self._io(delete_prefix, self.storage, f"results/{job['id']}/")
            raise
