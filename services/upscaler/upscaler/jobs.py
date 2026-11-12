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

from PIL import Image

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


class JobError(ValueError):
    """The request cannot be carried out; the message is user-facing."""


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
    job.update(changes)
    job["updated_at"] = now_iso()
    storage.put_json(job_name(job["id"]), job)
    return job


def set_state(
    storage: Storage, job: dict[str, Any], state: str, **changes: Any
) -> dict[str, Any]:
    save_job(storage, job, state=state, **changes)
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

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            src = img
            fmt = img.format or ""
            dpi = img.info.get("dpi", (0, 0))[0]
            icc = bool(img.info.get("icc_profile"))
            width, height = img.size
            warnings: list[str] = []
            blockers: list[str] = []
            seams = analysis.seam_report(src)
            tile_info = None

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
                    storage.put_bytes(
                        f"{staging}/tile.png", _png(tile.tile), "image/png"
                    )
                    storage.put_bytes(
                        f"{staging}/proof.jpg",
                        _jpeg(analysis.proof(tile.tile, 3)),
                        "image/jpeg",
                    )
                    grid = analysis.repeat_grid(tile.tile, 3)
                    input_name = f"{staging}/input.png"
                    storage.put_bytes(input_name, _png(grid), "image/png")
                    base = tile.tile.size
                    input_size = grid.size
            elif mode == "wrap":
                if seams.verdict != "seamless":
                    warnings.append(
                        f"The edges do not look seamless (verdict: {seams.verdict}); "
                        "“Seamless pattern” keeps a seam that is already there."
                    )
                padded = analysis.wrap_pad(src)
                input_name = f"{staging}/input.png"
                storage.put_bytes(input_name, _png(padded), "image/png")
                base = (width, height)
                input_size = padded.size
            else:
                base = (width, height)
                input_size = (width, height)
                if fmt in _PASSTHROUGH and src.mode in ("RGB", "RGBA", "L"):
                    input_name = source_name
                else:
                    input_name = f"{staging}/input.png"
                    rgb = src.convert("RGBA" if "A" in src.getbands() else "RGB")
                    storage.put_bytes(input_name, _png(rgb), "image/png")
    except Exception:
        delete_prefix(storage, f"{staging}/")
        raise

    if mode == "tile" and tile_info is None:
        input_name, base, input_size = "", (0, 0), (0, 0)

    input_mp = input_size[0] * input_size[1] / 1_000_000
    if input_size[0] and input_mp > settings.replicate_max_input_mp:
        blockers.append(
            f"Replicate input would be {input_size[0]}×{input_size[1]} "
            f"({input_mp:.1f} MP), above the {settings.replicate_max_input_mp:g} MP "
            "limit set for this model."
        )
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
    save_job(storage, job)
    log_event(storage, job, "staged", kind=kind, import_id=import_id)
    return job


def cancel_staged(storage: Storage, job: dict[str, Any]) -> dict[str, Any]:
    delete_prefix(storage, f"staging/{job['id']}/")
    return set_state(storage, job, "cancelled", finished_at=now_iso())


# --- post-processing -----------------------------------------------------------


def postprocess(
    storage: Storage, settings: Settings, job: dict[str, Any], output: Path
) -> dict[str, str]:
    """Crop, tag DPI, copy ICC, upload results. Runs in a worker thread."""
    # A 4x master has 16x the input's pixels; Pillow's default decompression
    # ceiling (~89 MP warning, ~179 MP error) is below that. Raise it to the
    # configured output ceiling on purpose; intake keeps its own lower limit.
    Image.MAX_IMAGE_PIXELS = int(settings.max_output_megapixels * 1_000_000)
    source = storage.get_bytes(job["staging"]["source"]) or b""
    with Image.open(io.BytesIO(source)) as src:
        icc = src.info.get("icc_profile")
    scale = job["scale"]
    results: dict[str, str] = {}
    with Image.open(output) as out:
        out.load()
        expected = (job["input"]["width"] * scale, job["input"]["height"] * scale)
        if out.size != expected:
            raise ReplicateError(
                f"Output is {out.size[0]}×{out.size[1]}, expected "
                f"{expected[0]}×{expected[1]}"
            )
        box = analysis.crop_box(job["mode"], tuple(job["base"]), scale)
        master = out.crop(box) if box else out
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
        job = await self._io(
            set_state, self.storage, job, "queued", queued_at=now_iso()
        )
        self.start(job["id"])
        return job

    async def cancel(self, job: dict[str, Any]) -> dict[str, Any]:
        state = job["state"]
        if state == "staged":
            return await self._io(cancel_staged, self.storage, job)
        if state not in ACTIVE:
            raise JobError(f"Job is already {state}")
        cancel_url = (job.get("prediction") or {}).get("cancel_url")
        if cancel_url:
            try:
                await self.replicate.cancel(cancel_url)
            except ReplicateError as exc:
                logger.warning("Cancel of %s failed: %s", job["id"], exc)
        job = await self._io(
            set_state, self.storage, job, "cancelled", finished_at=now_iso()
        )
        task = self._tasks.get(job["id"])
        if task:
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
                # Interrupted before the prediction id was saved: starting a
                # new prediction could bill twice, so stop and say so.
                await self._io(
                    set_state,
                    self.storage,
                    job,
                    "error",
                    error="Interrupted by a restart before Replicate confirmed the "
                    "job. Prepare it again.",
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
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            job = await self._fresh(job_id)
            if job and job["state"] not in FINAL:
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
            job = await self._io(
                set_state,
                self.storage,
                job,
                "running",
                prediction=prediction,
                started_at=now_iso(),
            )
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
        latest = await self._fresh(job["id"])
        if not latest or latest["state"] in FINAL:
            return
        await self._io(
            set_state,
            self.storage,
            latest,
            "done",
            results=results,
            finished_at=now_iso(),
            run_seconds=round(time.monotonic() - started, 1),
            predict_seconds=metrics.get("predict_time"),
        )
        await self._io(delete_prefix, self.storage, f"staging/{job['id']}/")
