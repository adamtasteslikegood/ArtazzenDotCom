# Agent Handbook

This guide summarizes how autonomous coding agents should work inside the ArtazzenDotCom repository. Keep it handy while you collaborate with the human maintainers.

## Mission Profile
- Deliver well-explained code or documentation improvements without breaking existing flows.
- Respect the FastAPI + Jinja2 architecture centered around `main.py`.
- Treat sidecar JSON files next to each image as the source of truth—the schema lives in `ImageSidecar.schema.json`.
- Preserve `Static/` capitalization; FastAPI mounts it at `/static`.
- Preserve the current product split: the public gallery (`/`, `/artwork/*`, `/collections/*`, `/order/*`) and the admin curation surface (`/admin/*`) are separate experiences and should not be merged during UI redesign work.

## Daily Workflow
1. **Understand the request.** Confirm whether it is a code change, doc update, or review. Ask clarifying questions only when truly needed.
2. **Check the repo state.** Assume the working tree may be dirty—never revert changes you did not introduce.
3. **Plan first.** Use the planning tool for any non-trivial task (multi-file edits, new features, refactors). Skip it only for the simplest 1–2 step requests.
4. **Work incrementally.** Prefer `apply_patch` for manual edits. Do not run destructive git commands or rely on global `cd`; set `workdir` on shell calls.
5. **Validate.** Run targeted commands when possible (formatters, scripts, manual curl checks). If sandboxing blocks a critical command, request approval with a clear justification.

## Coding Standards
- Python code follows PEP 8, uses type hints, and logs through `logging.getLogger(__name__)`.
- Functions use `snake_case`; classes use `PascalCase`.
- Sidecar files must follow `ImageSidecar.schema.json` and currently include `title`, `description`, `caption`, `author`, `copyright`, `tags`, `ai_generated`, `ai_details`, `reviewed`, and `detected_at`.
- Template filenames stay aligned with existing naming (`index.html`, `reviewAddedFiles.html`, etc.).

## Architecture Guardrails
- Keep `main.py` as the source of truth for application behavior; treat template and CSS work as presentation changes layered over the existing route and metadata model.
- Do not expose admin/curation actions in the public gallery UI. The gallery is public-facing; curation remains in `/admin`, `/admin/review/*`, `/admin/config`, and `/admin/advanced`.
- Preserve the sidecar-first workflow: uploads/imports create or update `Static/images/<image>.json`, and metadata edits or AI regeneration write back to that sidecar instead of introducing a database-backed replacement.
- Preserve the AI-assisted curation flow. Today the app can generate missing `title`, `description`, `caption` (short summary), `author`, and `tags`, and records provenance in `ai_generated` / `ai_details`.
- Preserve the artwork inquiry flow: `artwork_detail.html` links to `/order/{image_filename}`, and submissions append to `data/orders.jsonl`.

## Documentation & Communication
- Write concise, actionable commit-ready descriptions even if you are not creating the commit.
- In final responses: lead with the change explanation, cite files as `path:line`, and offer natural next steps (tests, review reminders) when relevant.
- Summaries should be informative yet brief; avoid dumping entire file contents.

## Tooling Expectations
- Python ≥3.10 recommended (virtual env: `python -m venv .venv` → `source .venv/bin/activate`).
- Install dependencies with `pip install -r requirements.txt`.
- Local server: `uvicorn main:app --reload` and visit `http://127.0.0.1:8000/`.
- Production containers: prefer the root `Dockerfile`, which runs `uvicorn main:app` directly (no Gunicorn), with `uvloop`/`httptools` enabled and workers controlled via `UVICORN_WORKERS`.
- Useful API probes:
  - `curl http://127.0.0.1:8000/admin/api/new-files`
  - `curl -F "files=@/path/to/image.jpg" http://127.0.0.1:8000/admin/upload`
  - `curl http://127.0.0.1:8000/admin/config`
- Sidecar management CLI: `python manage_sidecars.py validate`.

## Testing & Quality
- No formal automated suite yet—lean on manual verification via browser, `test_main.http`, or curl.
- When adding tests, prefer `pytest` + `httpx` in `tests/test_*.py`, keeping runs fast and isolated.
- Watch for regressions in gallery view (`/`), artwork detail (`/artwork/*`), order flow (`/order/*`), admin dashboard (`/admin`), upload/import flow, AI regeneration, and sidecar metadata persistence.

## Sandbox & Approvals
- Default sandbox mode is `workspace-write`; network is restricted. Request escalation only if absolutely required and provide one-sentence justification.
- Never execute GUI apps or destructive commands without explicit user direction.
- If unexpected repo changes appear mid-task, stop and ask how to proceed.

Stay deliberate, keep communication tight, and ensure each hand-off leaves the repository healthier than you found it.
