"""Minimal async client for Replicate predictions.

Salvaged from PR #130's ``app/print_master.py``: community models such as
``nightmareai/real-esrgan`` are started through ``POST /predictions`` with
their latest version id; official models through
``POST /models/{model}/predictions``. The image travels as a presigned bucket
URL, so nothing is uploaded to Replicate first.

The bearer token is only ever sent to ``api.replicate.com``. Output files
are downloaded without it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from upscaler.config import DEFAULT_MODEL, Settings

API_BASE = "https://api.replicate.com/v1"
TERMINAL = frozenset({"succeeded", "failed", "canceled"})
_CHUNK = 1024 * 1024
_MAX_REDIRECTS = 5
# Replicate throttles accounts with little credit to a burst of one request
# (6/min). A 429 means nothing was created, so waiting and resending is safe.
_THROTTLE_RETRIES = 6
_THROTTLE_MAX_WAIT = 30.0
# xinntao/realesrgan's name for the RealESRGAN_x4plus weights.
XINNTAO_VERSION = "General - RealESRGANplus"
# xinntao/realesrgan doubles an input shorter than this before upscaling,
# so its output would no longer be the requested scale.
XINNTAO_MIN_HEIGHT = 300


def _retry_after(resp: httpx.Response) -> float:
    try:
        wait = float(resp.headers.get("retry-after", ""))
    except ValueError:
        wait = 10.0
    return min(max(wait, 1.0), _THROTTLE_MAX_WAIT)


class ReplicateError(RuntimeError):
    """A Replicate call failed; the message is safe to show and store."""


class ReplicateClient:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._target: tuple[str, dict[str, str]] | None = None
        self._sleep = asyncio.sleep  # replaced in tests

    @property
    def configured(self) -> bool:
        return bool(self.settings.replicate_api_token)

    def _api(self) -> httpx.AsyncClient:
        if not self.configured:
            raise ReplicateError("REPLICATE_API_TOKEN is not set")
        return httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.settings.replicate_api_token}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
            transport=self._transport,
        )

    @staticmethod
    def _check_api_url(url: str) -> str:
        # get/cancel URLs come back from Replicate; never send the token
        # anywhere else.
        if not url.startswith(API_BASE + "/"):
            raise ReplicateError("Unexpected Replicate URL")
        return url

    async def _call(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self._api() as client:
                for attempt in range(_THROTTLE_RETRIES + 1):
                    resp = await client.request(method, url, **kwargs)
                    if resp.status_code != 429 or attempt == _THROTTLE_RETRIES:
                        break
                    await self._sleep(_retry_after(resp))
        except httpx.HTTPError as exc:
            raise ReplicateError(f"Replicate request failed: {exc}") from None
        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = str(body.get("detail") or body.get("title") or "")
            except ValueError:
                pass
            raise ReplicateError(
                f"Replicate returned {resp.status_code}"
                + (f": {detail[:300]}" if detail else "")
            )
        return resp.json()

    async def _prediction_target(self) -> tuple[str, dict[str, str]]:
        if self.settings.replicate_version:
            return f"{API_BASE}/predictions", {
                "version": self.settings.replicate_version
            }
        if self._target is None:
            model = self.settings.replicate_model
            info = await self._call("GET", f"{API_BASE}/models/{model}")
            if info.get("is_official"):
                self._target = (f"{API_BASE}/models/{model}/predictions", {})
            else:
                version = (info.get("latest_version") or {}).get("id")
                if not version:
                    raise ReplicateError(
                        f"Replicate model {model} has no published version"
                    )
                self._target = (f"{API_BASE}/predictions", {"version": version})
        return self._target

    def model_input(self, image_url: str, scale: int) -> dict[str, Any]:
        """The prediction input; xinntao's model names its inputs differently."""
        if self.settings.replicate_model == DEFAULT_MODEL:
            return {
                "img": image_url,
                "version": XINNTAO_VERSION,
                "scale": scale,
                "face_enhance": False,
                "tile": self.settings.replicate_tile,
            }
        return {"image": image_url, "scale": scale, "face_enhance": False}

    async def create(self, image_url: str, scale: int) -> dict[str, Any]:
        url, extra = await self._prediction_target()
        body = {**extra, "input": self.model_input(image_url, scale)}
        return await self._call("POST", url, json=body)

    async def get(self, url: str) -> dict[str, Any]:
        return await self._call("GET", self._check_api_url(url))

    async def cancel(self, url: str) -> dict[str, Any]:
        return await self._call("POST", self._check_api_url(url))

    @staticmethod
    def _check_output_url(url: str) -> str:
        """Allow only Replicate's documented output-file hosts.

        The URL comes from a provider response, but it still controls a
        server-side request. Restricting every hop prevents it from becoming
        an SSRF path through redirects or an unexpected response payload.
        """
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower()
            port = parsed.port
        except ValueError:
            raise ReplicateError("Unexpected Replicate output URL") from None
        if (
            parsed.scheme != "https"
            or (
                host != "replicate.delivery"
                and not host.endswith(".replicate.delivery")
            )
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            raise ReplicateError("Unexpected Replicate output URL")
        return url

    async def download(self, url: str, dest: Path, max_bytes: int) -> int:
        """Stream an output file to ``dest`` without the API token."""
        current_url = self._check_output_url(url)
        written = 0
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=10.0),
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    async with client.stream("GET", current_url) as resp:
                        if resp.is_redirect:
                            location = resp.headers.get("location")
                            if not location:
                                raise ReplicateError(
                                    "Output download redirect had no location"
                                )
                            current_url = self._check_output_url(
                                urljoin(str(resp.url), location)
                            )
                            continue
                        if resp.status_code >= 400:
                            raise ReplicateError(
                                f"Output download returned {resp.status_code}"
                            )
                        with dest.open("wb") as handle:
                            async for chunk in resp.aiter_bytes(_CHUNK):
                                written += len(chunk)
                                if written > max_bytes:
                                    raise ReplicateError(
                                        "Output is larger than allowed"
                                    )
                                handle.write(chunk)
                        return written
                raise ReplicateError("Output download redirected too many times")
        except httpx.HTTPError as exc:
            raise ReplicateError(f"Output download failed: {exc}") from None


def output_url(prediction: dict[str, Any]) -> str:
    out = prediction.get("output")
    if isinstance(out, list):
        out = out[0] if out else None
    if not isinstance(out, str) or not out:
        raise ReplicateError("Replicate returned no output file")
    return out
