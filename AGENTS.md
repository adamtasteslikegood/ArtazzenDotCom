# Agent Handbook

This guide summarizes how autonomous coding agents should work inside the ArtazzenDotCom repository. Keep it handy while you collaborate with the human maintainers.

## Mission Profile
- Deliver well-explained code or documentation improvements without breaking existing flows.
- Respect the FastAPI + Jinja2 architecture centered around `main.py`.
- Treat sidecar JSON files next to each image as the source of truth—the schema lives in `ImageSidecar.schema.json`.
- Preserve `Static/` capitalization; FastAPI mounts it at `/static`.

## Daily Workflow
1. **Understand the request.** Confirm whether it is a code change, doc update, or review. Ask clarifying questions only when truly needed.
2. **Check the repo state.** Assume the working tree may be dirty—never revert changes you did not introduce.
3. **Plan first.** Use the planning tool for any non-trivial task (multi-file edits, new features, refactors). Skip it only for the simplest 1–2 step requests.
4. **Work incrementally.** Prefer `apply_patch` for manual edits. Do not run destructive git commands or rely on global `cd`; set `workdir` on shell calls.
5. **Validate.** Run targeted commands when possible (formatters, scripts, manual curl checks). If sandboxing blocks a critical command, request approval with a clear justification.

## Coding Standards
- Python code follows PEP 8, uses type hints, and logs through `logging.getLogger(__name__)`.
- Functions use `snake_case`; classes use `PascalCase`.
- Sidecar files must only contain `title`, `description`, `reviewed`, `detected_at`.
- Template filenames stay aligned with existing naming (`index.html`, `reviewAddedFiles.html`, etc.).

## Documentation & Communication
- Write concise, actionable commit-ready descriptions even if you are not creating the commit.
- In final responses: lead with the change explanation, cite files as `path:line`, and offer natural next steps (tests, review reminders) when relevant.
- Summaries should be informative yet brief; avoid dumping entire file contents.

## Tooling Expectations
- Python ≥3.10 recommended (virtual env: `python -m venv .venv` → `source .venv/bin/activate`).
- Install dependencies with `pip install -r requirements.txt`.
- Local server: `uvicorn main:app --reload` and visit `http://127.0.0.1:8000/`.
- Useful API probes:
  - `curl http://127.0.0.1:8000/admin/api/new-files`
  - `curl -F "files=@/path/to/image.jpg" http://127.0.0.1:8000/admin/upload`
  - `curl http://127.0.0.1:8000/admin/config`
- Sidecar management CLI: `python manage_sidecars.py validate`.

## Testing & Quality
- No formal automated suite yet—lean on manual verification via browser, `test_main.http`, or curl.
- When adding tests, prefer `pytest` + `httpx` in `tests/test_*.py`, keeping runs fast and isolated.
- Watch for regressions in gallery view (`/`), admin dashboard (`/admin`), upload flow, and metadata persistence.

## Sandbox & Approvals
- Default sandbox mode is `workspace-write`; network is restricted. Request escalation only if absolutely required and provide one-sentence justification.
- Never execute GUI apps or destructive commands without explicit user direction.
- If unexpected repo changes appear mid-task, stop and ask how to proceed.

Stay deliberate, keep communication tight, and ensure each hand-off leaves the repository healthier than you found it.
