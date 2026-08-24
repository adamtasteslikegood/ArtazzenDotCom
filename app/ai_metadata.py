"""OpenAI-backed metadata generation for artwork images."""

import base64
import json
import logging
import os
import re
import textwrap
import time
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from app import config, sidecars

logger = logging.getLogger(__name__)


def _build_openai_prompt(
    image_path: Path,
    metadata: dict[str, Any],
    needed_fields: list[str],
) -> str:
    """Create a deterministic prompt for the OpenAI metadata request."""
    hints: list[str] = []
    for key in ("title", "description", "caption", "artist"):
        if metadata.get(key):
            hints.append(f"Existing {key}: {metadata[key]}")
    tags = metadata.get("tags")
    if tags:
        if isinstance(tags, list):
            hints.append(f"Existing tags: {', '.join(str(t) for t in tags)}")
        elif isinstance(tags, str):
            hints.append(f"Existing tags: {tags}")
    hint_text = "\n".join(hints) if hints else "No reliable text metadata was detected."

    field_descriptions: dict[str, str] = {
        "title": "a short but descriptive title (<= 80 characters)",
        "description": "an engaging description (<= 400 characters)",
        "caption": "a concise gallery caption (<= 160 characters)",
        "tags": "3-8 descriptive tags for categorization",
    }
    requested_parts = [
        field_descriptions[f] for f in needed_fields if f in field_descriptions
    ]
    requested = " and ".join(requested_parts)

    field_keys = ", ".join(f'"{f}"' for f in needed_fields)
    tags_instruction = (
        " For tags, return an array of lowercase strings."
        if "tags" in needed_fields
        else ""
    )
    return textwrap.dedent(f"""
        You are assisting with cataloging artwork. Analyze the provided image
        named '{image_path.name}'. {hint_text}
        Generate {requested}. Respond with JSON containing only the keys
        {field_keys} with concise English text suitable for a public art
        gallery.{tags_instruction} Avoid mentioning that information is guessed
        or unavailable.
        """).strip()


def _prepare_image_for_openai(image_path: Path) -> str | None:
    """Return a data URL encoded version of the image for OpenAI vision models."""
    try:
        with Image.open(image_path) as img:
            if img.mode not in {"RGB", "L"}:
                img = img.convert("RGB")
            max_edge = 1024
            img.thumbnail((max_edge, max_edge))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as exc:  # pragma: no cover - dependent on Pillow support
        logger.warning(
            "Failed to prepare %s for OpenAI metadata request: %s", image_path, exc
        )
        return None


def _get_openai_api_key() -> str | None:
    """Return OpenAI API key from env or optional local module.

    Checks env vars `MY_OPENAI_API_KEY` then legacy `My_OpenAI_APIKey`.
    Falls back to optional my_OpenAI_APIkey.py module if present.
    """
    api_key = os.getenv(config.OPENAI_API_KEY_ENV_PRIMARY) or os.getenv(
        config.OPENAI_API_KEY_ENV_LEGACY
    )
    if api_key:
        return api_key
    with suppress(Exception):
        # Lazy import to avoid hard dependency
        import my_OpenAI_APIkey as local_key  # type: ignore

        v = getattr(local_key, "MY_OPENAI_API_KEY", None)
        if v:
            return str(v)
    return None


def _strip_json_fences(text: str) -> str:
    """Remove a wrapping markdown code fence (``` or ```json) from a JSON blob."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()
    return stripped


def _unwrap_nested_json(value: str, field: str) -> str:
    """If a string field value is itself a JSON object containing the field,
    return the inner value.  Loops to handle double-nesting and falls back to
    the first string value when the expected key is absent."""
    for _ in range(5):
        candidate = _strip_json_fences(value)
        if not candidate.startswith("{"):
            return value
        try:
            inner = json.loads(candidate)
        except json.JSONDecodeError:
            return value
        if not isinstance(inner, dict):
            return value
        if isinstance(inner.get(field), str):
            value = inner[field]
            continue
        for v in inner.values():
            if isinstance(v, str) and v.strip():
                return v
        return value
    return value


_EMBEDDED_KEY_RE = re.compile(
    r"""['"](?:tags|description|caption|title)['"]\s*:\s*[\['"{]"""
)

_FIELD_MAX_LEN: dict[str, int] = {
    "title": 320,
    "description": 1600,
    "caption": 640,
}


def _looks_like_stuffed_response(value: str, field: str) -> bool:
    """Return True when a string value looks like the model crammed
    multiple fields into a single JSON string value."""
    max_len = _FIELD_MAX_LEN.get(field)
    if max_len and len(value) > max_len:
        return True
    return bool(_EMBEDDED_KEY_RE.search(value))


def _request_openai_metadata(
    image_path: Path,
    metadata: dict[str, Any],
    needed_fields: list[str],
) -> dict[str, Any]:
    """Request metadata from OpenAI and return the response payload."""
    ai_cfg = config._get_ai_config()
    model = ai_cfg["model"]
    prompt = _build_openai_prompt(image_path, metadata, needed_fields)
    details: dict[str, Any] = {
        "provider": "openai",
        "model": model,
        "prompt": prompt,
        "response_id": "",
        "finish_reason": "",
        "created": 0.0,
        "attempted_at": time.time(),
        "status": "",
        "error": "",
        "raw_response": {},
    }

    api_key = _get_openai_api_key()
    if not api_key:
        details["status"] = "skipped_no_api_key"
        details["error"] = (
            "Missing OpenAI API key. Set env 'MY_OPENAI_API_KEY' "
            "(or legacy 'My_OpenAI_APIKey'), or provide my_OpenAI_APIkey.py."
        )
        return {"title": "", "description": "", "details": details}

    image_payload = _prepare_image_for_openai(image_path)
    if not image_payload:
        details["status"] = "error_image_encoding"
        details["error"] = "Unable to prepare image for OpenAI request."
        return {"title": "", "description": "", "details": details}

    request_body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You create concise, visitor-friendly metadata "
                            "for artwork images."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_payload},
                ],
            },
        ],
        "max_output_tokens": ai_cfg["max_output_tokens"],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "image_metadata",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        f: (
                            {"type": "array", "items": {"type": "string"}}
                            if f == "tags"
                            else {"type": "string"}
                        )
                        for f in needed_fields
                    },
                    "required": sorted(needed_fields),
                    "additionalProperties": False,
                },
            }
        },
    }
    # Some models (e.g., gpt-5-mini) do not accept 'temperature'
    if not str(model).startswith("gpt-5"):
        request_body["temperature"] = ai_cfg["temperature"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        timeout = httpx.Timeout(config.OPENAI_TIMEOUT_SECONDS)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=request_body,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.warning("OpenAI metadata request failed: %s", exc)
        details["status"] = "error_http"
        details["error"] = "OpenAI metadata request failed."
        details["error_body"] = ""
        return {"title": "", "description": "", "details": details}

    details["response_id"] = payload.get("id", "")
    details["created"] = float(payload.get("created", details["attempted_at"]))
    details["model"] = payload.get("model", model)

    # Truncated/failed responses (e.g. reasoning models exhausting
    # max_output_tokens) must never be parsed or stored.
    payload_status = payload.get("status")
    if payload_status and payload_status != "completed":
        reason = (payload.get("incomplete_details") or {}).get("reason", "")
        details["status"] = "error_incomplete"
        details["error"] = f"OpenAI response status '{payload_status}'" + (
            f" ({reason})" if reason else ""
        )
        details["raw_response"] = {
            "id": payload.get("id"),
            "usage": payload.get("usage", {}),
        }
        return {"title": "", "description": "", "details": details}

    details["status"] = "success"

    # Extract JSON from Responses API output; support output_json and output_text
    parsed = None
    content_text = ""
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            parts = (item or {}).get("content", []) or []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype in {"output_json", "json"} and isinstance(
                    part.get("json"), dict
                ):
                    parsed = part.get("json")
                    break
                if ptype in {"output_text", "text"}:
                    text_val = part.get("text", "")
                    if isinstance(text_val, str):
                        content_text += text_val
            if parsed is not None:
                break
    # Fallback for older chat-style payloads
    if parsed is None and not content_text:
        choice: dict[str, Any] = next(iter(payload.get("choices", []) or []), {})
        details["finish_reason"] = choice.get("finish_reason", "")
        message = choice.get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [
                part.get("text", "") for part in content if isinstance(part, dict)
            ]
            content_text = "".join(text_parts)
        elif isinstance(content, str):
            content_text = content

    if parsed is None and content_text:
        try:
            parsed = json.loads(_strip_json_fences(content_text))
        except json.JSONDecodeError:
            parsed = None
    # Some responses double-encode the JSON object as a string.
    if isinstance(parsed, str):
        with suppress(json.JSONDecodeError):
            parsed = json.loads(_strip_json_fences(parsed))
    if not isinstance(parsed, dict):
        logger.warning(
            "Unable to parse OpenAI metadata response (type=%s)",
            type(parsed).__name__,
        )
        details["status"] = "error_parse"
        details["error"] = "OpenAI metadata response could not be parsed."
        # attach brief output excerpt and types for debugging
        try:
            details["raw_response"] = {
                "id": payload.get("id"),
                "usage": payload.get("usage", {}),
                "output_types": [
                    [(p or {}).get("type") for p in ((it or {}).get("content") or [])]
                    for it in (output or [])
                ],
                "text_excerpt": content_text[:200],
            }
        except Exception:
            details["raw_response"] = {
                "id": payload.get("id"),
                "usage": payload.get("usage", {}),
            }
        return {"title": "", "description": "", "details": details}

    # Keep raw id/usage only to avoid bloating sidecar
    details["raw_response"] = {
        "id": payload.get("id"),
        "usage": payload.get("usage", {}),
    }

    result: dict[str, Any] = {"details": details}
    for field in needed_fields:
        val = parsed.get(field)
        if isinstance(val, str):
            val = _unwrap_nested_json(val, field)
        if field == "tags":
            if isinstance(val, list):
                result[field] = [str(t).strip() for t in val if str(t).strip()]
            elif isinstance(val, str) and val.strip():
                result[field] = [t.strip() for t in val.split(",") if t.strip()]
            else:
                result[field] = []
        elif val is not None:
            cleaned = str(val).strip()
            if _looks_like_stuffed_response(cleaned, field):
                logger.warning(
                    "Rejected AI %s for %s: looks like a stuffed response",
                    field, image_path.name,
                )
                details["status"] = "error_field_validation"
                details["error"] = (
                    f"AI returned a {field} containing embedded JSON "
                    f"or exceeding length limits"
                )
                result[field] = ""
            else:
                result[field] = cleaned
        else:
            result[field] = "" if field != "tags" else []

    return result


def _populate_missing_metadata(
    image_path: Path,
    metadata: dict[str, Any],
    only_fields: list[str] | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Fill missing metadata using OpenAI when configured.

    If only_fields is provided, only regenerate those specific fields.
    Otherwise, regenerate any empty AI-eligible field. With persist=False the
    result is returned without writing the sidecar (caller decides).
    """
    ai_eligible = ["title", "description", "caption", "tags"]

    if only_fields is not None:
        needed_fields = []
        for f in only_fields:
            if f not in ai_eligible:
                continue
            val = metadata.get(f)
            if f == "tags":
                if not val:
                    needed_fields.append(f)
            elif not (val or "").strip():
                needed_fields.append(f)
    else:
        needed_fields = []
        for field in ai_eligible:
            val = metadata.get(field)
            if field == "tags":
                if not val:
                    needed_fields.append(field)
            elif not (val or "").strip():
                needed_fields.append(field)

    if not needed_fields:
        return metadata
    if not config._get_ai_config().get("enabled", True):
        return metadata

    ai_details = metadata.get("ai_details")
    if not isinstance(ai_details, dict):
        ai_details = {}
    metadata["ai_details"] = ai_details

    if not _get_openai_api_key() and ai_details.get("status") == "skipped_no_api_key":
        return metadata

    result = _request_openai_metadata(image_path, metadata, needed_fields)
    details = result.get("details", {})
    metadata["ai_details"] = details

    applied_fields: list[str] = []
    if details.get("status") == "success":
        existing_ai_fields = set(metadata.get("ai_fields", []))
        for field in needed_fields:
            val = result.get(field)
            if field == "tags" and isinstance(val, list) and val:
                metadata["tags"] = val
                existing_ai_fields.add("tags")
                applied_fields.append("tags")
            elif isinstance(val, str) and val:
                metadata[field] = val
                existing_ai_fields.add(field)
                applied_fields.append(field)
        metadata["ai_fields"] = sorted(existing_ai_fields)
        metadata["ai_generated"] = True
    else:
        metadata.setdefault("ai_generated", False)

    metadata.setdefault("detected_at", time.time())
    metadata.setdefault("status", "pending")
    if persist:
        return _persist_populated_fields(image_path, metadata, applied_fields)
    return metadata


def _persist_populated_fields(
    image_path: Path,
    metadata: dict[str, Any],
    applied_fields: list[str],
) -> dict[str, Any]:
    """Merge this call's generated fields into the CURRENT sidecar and write.

    The OpenAI request can take many seconds; an admin may approve or edit
    the image meanwhile. Writing the pre-call snapshot back would silently
    revert those changes (e.g. flip status back to pending), so re-read the
    sidecar and overlay only what this call produced. Held under the
    sidecar mutation lock (threads + processes) so the read-merge-write
    cycle is atomic against other writers.
    """
    with sidecars.sidecar_mutation_lock.held():
        fresh = sidecars._load_metadata(image_path)
        for field in applied_fields:
            fresh[field] = metadata[field]
        fresh["ai_details"] = metadata.get("ai_details", {})
        if metadata.get("ai_generated"):
            fresh["ai_generated"] = True
        else:
            fresh.setdefault("ai_generated", False)
        # Union only what THIS call generated: the pre-call snapshot's
        # ai_fields could resurrect provenance a concurrent admin edit
        # deliberately removed.
        fresh["ai_fields"] = sorted(
            set(fresh.get("ai_fields", [])) | set(applied_fields)
        )
        sidecars._write_sidecar(image_path, fresh)
        return fresh
