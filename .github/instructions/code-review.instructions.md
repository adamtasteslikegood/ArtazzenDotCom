---
applyTo: "**"
---

# Code Review Instructions

## Scope

Review only application code. Skip these paths entirely — do not read, analyze, or comment on them:

- `.claude/**`
- `.copilot/**`
- `.github/instructions/**`
- `artazzen-design-system/**`
- `AGENTS.md`

## Efficiency Rules

Copilot reviews consume tokens. Follow these rules to avoid waste:

1. **No repeat comments.** If you have already posted a comment on a file in this PR, do not re-raise the same feedback on subsequent review passes. On re-review, comment only on lines changed since your last review.
2. **No drive-by nitpicks.** Do not comment on style preferences, whitespace, import ordering, or formatting — automated tools (ruff, black, prettier) handle those. Only flag issues that tools cannot catch.
3. **One comment per issue.** If the same pattern appears in multiple places, post one comment referencing all locations rather than separate comments on each.

## Priority Levels

Use these priority tags in comment headers:

- **CRITICAL** — blocks merge: security vulnerabilities (injection, auth bypass, secrets in code), data loss risks, race conditions, broken error handling that silently swallows failures.
- **IMPORTANT** — requires discussion before merge: logic errors, missing validation at system boundaries, API contract violations, incorrect schema usage.
- **SUGGESTION** — non-blocking: performance improvements, readability, better error messages, test coverage gaps.

Do not post comments below SUGGESTION level. If a file has no issues worth a SUGGESTION or higher, leave no comment on that file.

## Project-Specific Checks

- Sidecar JSON must conform to `ImageSidecar.schema.json`. Required fields: `title`, `description`, `ai_generated`, `ai_details`, `status`, `detected_at`.
- `Static/` directory capitalisation must be preserved in all references.
- Application code belongs in the `app/` package, not in `main.py`.
- Module layering must be respected: `config → sidecars → ai_metadata → curation → watcher → security/routes → factory → main`. No cycles.
- Atomic file writes for sidecars (write temp → rename).
- No `print()` in production paths — use `logging.getLogger(__name__)`.

## Comment Format

```
**[PRIORITY]** Summary of the issue

Why this matters: [one sentence impact]

Suggested fix: [concrete code or approach]
```
